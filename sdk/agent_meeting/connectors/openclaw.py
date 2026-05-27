"""OpenClaw Agent Connector — allows OpenClaw agents to join meetings.

This connector bridges the Agent Meeting Platform with OpenClaw agents.
It runs as a background process that:
1. Connects to a meeting room via WebSocket
2. Receives meeting events (messages, votes, etc.)
3. Writes events to a shared event file (JSONL) for the OpenClaw agent to read
4. Reads responses from a response file and posts them to the meeting

This design allows the OpenClaw agent to participate in meetings without
needing direct WebSocket access — the bridge handles all real-time communication.

Usage (from OpenClaw agent):
    from agent_meeting.connectors.openclaw import OpenClawMeetingBridge

    bridge = OpenClawMeetingBridge(
        server_url="http://localhost:8000",
        agent_name="Chopper",
        capabilities={"role": "assistant", "type": "openclaw"},
    )

    # Start bridge in background
    await bridge.start(room_id)

    # Later: read pending events
    events = bridge.read_pending_events()

    # Post a response
    await bridge.send_message("Great idea! Let me think about that.")

    # Or: let the bridge auto-respond using a callback
    bridge.set_response_handler(my_handler)
    await bridge.run()  # blocks until meeting closes
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Coroutine

from agent_meeting.client import MeetingClient
from agent_meeting.models import (
    Agent,
    Decision,
    Event,
    EventType,
    Message,
    ModeratorState,
    Room,
)

logger = logging.getLogger(__name__)

# Type aliases
ResponseHandler = Callable[["OpenClawMeetingBridge", Event], Coroutine[Any, Any, str | None]]


class OpenClawMeetingBridge:
    """Bridge between Agent Meeting Platform and an OpenClaw agent session.

    The bridge manages the full lifecycle of joining a meeting:
    - Registration and room join
    - WebSocket event listening
    - Message forwarding (meeting → agent)
    - Response forwarding (agent → meeting)
    - Voting and proposals
    - Meeting close

    Can be used in two modes:
    1. **Event-driven mode**: Set a response_handler and call run() — the bridge
       auto-processes events and calls your handler for each one.
    2. **Manual mode**: Call start() to connect, then periodically call
       read_pending_events() and send_message() as needed.
    """

    def __init__(
        self,
        server_url: str = "http://localhost:8000",
        agent_name: str = "OpenClaw Agent",
        capabilities: dict[str, Any] | None = None,
        work_dir: str | None = None,
    ):
        self.server_url = server_url
        self.agent_name = agent_name
        self.capabilities = capabilities or {"role": "assistant", "type": "openclaw"}

        # Meeting client
        self._client = MeetingClient(
            server_url=server_url,
            name=agent_name,
            capabilities=self.capabilities,
            connector_type="openclaw",
        )

        # State
        self._room_id: str | None = None
        self._room: Room | None = None
        self._running = False
        self._started = False

        # Event queue for manual mode
        self._pending_events: list[Event] = []
        self._all_events: list[Event] = []

        # Response handler for event-driven mode
        self._response_handler: ResponseHandler | None = None

        # Rate limiting to prevent infinite response loops
        self._min_response_interval: float = 3.0  # seconds between responses
        self._max_responses_per_minute: int = 8
        self._last_response_time: float = 0.0
        self._response_timestamps: list[float] = []
        self._total_responses_sent: int = 0

        # Conversation context
        self._context: list[dict] = []
        self._turn_count = 0

        # Work directory for file-based IPC
        self._work_dir = Path(work_dir or f"/tmp/openclaw-meeting-{uuid.uuid4().hex[:8]}")
        self._work_dir.mkdir(parents=True, exist_ok=True)
        self._events_file = self._work_dir / "events.jsonl"
        self._responses_file = self._work_dir / "responses.jsonl"

    @property
    def agent_id(self) -> str:
        return self._client.agent_id

    @property
    def agent(self) -> Agent | None:
        return self._client.agent

    @property
    def room_id(self) -> str | None:
        return self._room_id

    @property
    def room(self) -> Room | None:
        return self._room

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def context(self) -> list[dict]:
        """Full conversation context (list of messages seen)."""
        return self._context

    @property
    def recent_context(self, last_n: int = 20) -> list[dict]:
        """Last N messages in context."""
        return self._context[-last_n:]

    @property
    def turn_count(self) -> int:
        return self._turn_count

    # ── Response Handler ─────────────────────────────────────────────

    def _can_respond(self) -> bool:
        """Check if rate limit allows sending a response."""
        now = time.time()

        # Enforce minimum interval between responses
        if now - self._last_response_time < self._min_response_interval:
            return False

        # Enforce max responses per minute
        cutoff = now - 60.0
        self._response_timestamps = [t for t in self._response_timestamps if t > cutoff]
        if len(self._response_timestamps) >= self._max_responses_per_minute:
            return False

        return True

    def _record_response(self) -> None:
        """Record that a response was sent."""
        self._last_response_time = time.time()
        self._response_timestamps.append(self._last_response_time)
        self._total_responses_sent += 1

    def set_response_handler(self, handler: ResponseHandler) -> None:
        """Set a callback to handle incoming events and generate responses.

        The handler receives (bridge, event) and should return:
        - A string response to send back to the meeting
        - None to skip responding

        Example:
            async def my_handler(bridge, event):
                if event.message and event.message.type == "question":
                    return f"I think we should consider..."
                return None

            bridge.set_response_handler(my_handler)
            await bridge.run()
        """
        self._response_handler = handler

    # ── Lifecycle ────────────────────────────────────────────────────

    async def register(self) -> Agent:
        """Register this agent with the meeting server."""
        return await self._client.register()

    async def create_room(
        self,
        name: str,
        topic: str,
        agenda: list[dict] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> Room:
        """Create a new meeting room and join it."""
        room = await self._client.create_room(name, topic, agenda, settings)
        self._room_id = room.id
        self._room = room
        return room

    async def join_room(self, room_id: str, role: str = "participant") -> Room:
        """Join an existing room."""
        self._room_id = room_id
        room = await self._client.join_room(room_id, role)
        self._room = room
        return room

    async def start(self, room_id: str | None = None) -> None:
        """Start the bridge — register, join room, begin listening.

        If room_id is provided, joins that room. Otherwise uses the room
        set via create_room() or join_room().
        """
        if room_id:
            self._room_id = room_id

        if not self._client.agent:
            await self.register()

        if self._room_id and not self._room:
            await self.join_room(self._room_id)

        self._started = True
        logger.info("Bridge started for agent %s in room %s", self.agent_name, self._room_id)

    async def run(self, room_id: str | None = None) -> None:
        """Start the bridge and run the event loop (blocks until meeting closes).

        Requires a response_handler to be set via set_response_handler().
        """
        await self.start(room_id)

        if not self._response_handler:
            raise ValueError("No response handler set — call set_response_handler() first")

        self._running = True

        # Register event handlers
        @self._client.on("recent_message")
        async def on_recent(event: Event):
            if event.message and event.message.agent_id != self.agent_id:
                self._add_to_context(event.message)
            self._pending_events.append(event)
            self._append_event_to_file(event)

            # Also call response handler for recent messages (catch-up)
            if self._response_handler and event.message and event.message.agent_id != self.agent_id:
                try:
                    response = await self._response_handler(self, event)
                    if response and self._can_respond():
                        self._record_response()
                        await self.send_message(response)
                except Exception as e:
                    logger.error("Response handler error (recent): %s", e)

        @self._client.on("new_message")
        async def on_message(event: Event):
            if not event.message:
                return
            if event.message.agent_id == self.agent_id:
                return

            self._add_to_context(event.message)
            self._pending_events.append(event)
            self._append_event_to_file(event)
            self._turn_count += 1

            # Call response handler
            if self._response_handler:
                try:
                    response = await self._response_handler(self, event)
                    if response and self._can_respond():
                        self._record_response()
                        await self.send_message(response)
                except Exception as e:
                    logger.error("Response handler error: %s", e)

        @self._client.on("vote_requested")
        async def on_vote(event: Event):
            self._pending_events.append(event)
            self._append_event_to_file(event)

            if self._response_handler:
                try:
                    response = await self._response_handler(self, event)
                    if response and self._can_respond() and event.data.get("proposal_id"):
                        # If handler returns "yes" or "no", treat as vote
                        self._record_response()
                        choice = "yes" if "yes" in response.lower()[:20] else "no"
                        await self.vote(
                            event.data["proposal_id"],
                            choice,
                            reasoning=response[:200],
                        )
                except Exception as e:
                    logger.error("Vote handler error: %s", e)

        @self._client.on("meeting_closed")
        async def on_close(event: Event):
            self._pending_events.append(event)
            self._append_event_to_file(event)
            logger.info("Meeting closed")
            self._running = False

        @self._client.on("message_posted")
        async def on_message_posted(event: Event):
            """Handle messages from REST API (relayed via event bus)."""
            if not event.data:
                return
            # Convert data to message-like event
            from agent_meeting.models import Message as Msg
            msg = Msg.from_dict(event.data)
            if msg.agent_id == self.agent_id:
                return

            self._add_to_context(msg)
            self._pending_events.append(event)
            self._append_event_to_file(event)
            self._turn_count += 1

            if self._response_handler:
                try:
                    # Create a synthetic event with the message
                    synth_event = Event(type=EventType.MESSAGE_POSTED, data=event.data, message=msg)
                    response = await self._response_handler(self, synth_event)
                    if response and self._can_respond():
                        self._record_response()
                        await self.send_message(response)
                except Exception as e:
                    logger.error("Response handler error (posted): %s", e)

        @self._client.on("*")
        async def on_any(event: Event):
            if event.type not in (EventType.MESSAGE, EventType.RECENT, EventType.MESSAGE_POSTED, EventType.VOTE_REQUESTED, EventType.MEETING_CLOSED):
                self._pending_events.append(event)
                self._append_event_to_file(event)

        logger.info("🎧 Listening for events in room %s...", self._room_id[:8] if self._room_id else "?")
        await self._client.listen(self._room_id)
        self._running = False

    async def stop(self) -> None:
        """Stop the bridge."""
        self._running = False
        self._client.stop()
        await self._client.close()

    # ── Actions ───────────────────────────────────────────────────────

    async def send_message(
        self,
        content: str,
        msg_type: str = "chat",
        parent_id: str | None = None,
    ) -> Message:
        """Send a message to the meeting."""
        return await self._client.send(
            content=content,
            type=msg_type,
            room_id=self._room_id,
            parent_id=parent_id,
        )

    async def propose(self, content: str) -> Message:
        """Submit a proposal."""
        return await self._client.propose(content, room_id=self._room_id)

    async def vote(
        self,
        proposal_id: str,
        choice: str,
        reasoning: str = "",
    ) -> Message:
        """Cast a vote on a proposal."""
        return await self._client.vote(
            proposal_id=proposal_id,
            choice=choice,
            reasoning=reasoning,
            room_id=self._room_id,
        )

    async def ask_question(self, content: str, parent_id: str | None = None) -> Message:
        """Ask a question."""
        return await self._client.ask_question(content, parent_id=parent_id, room_id=self._room_id)

    async def raise_risk(self, content: str) -> Message:
        """Raise a risk."""
        return await self._client.raise_risk(content, room_id=self._room_id)

    async def request_investigation(self, topic: str, estimated_minutes: int = 5) -> Message:
        """Request investigation time."""
        return await self._client.request_investigation(topic, estimated_minutes, room_id=self._room_id)

    async def get_moderator_state(self) -> ModeratorState:
        """Get current moderator state."""
        return await self._client.get_moderator_state(self._room_id)

    async def start_moderator(self) -> dict:
        """Start the moderator for this room."""
        return await self._client.start_moderator(self._room_id)

    async def close_meeting(self) -> dict:
        """Close the meeting."""
        return await self._client.close_meeting(self._room_id)

    async def get_decisions(self) -> list[Decision]:
        """Get decisions from this meeting."""
        return await self._client.get_decisions(self._room_id)

    async def get_messages(self, limit: int = 50, offset: int = 0) -> tuple[list[Message], int]:
        """Get messages from the meeting."""
        return await self._client.get_messages(self._room_id, limit=limit, offset=offset)

    # ── Manual Mode (read events without blocking) ──────────────────

    def read_pending_events(self) -> list[Event]:
        """Read and clear pending events (for manual polling mode).

        Returns list of events since last call.
        """
        events = self._pending_events.copy()
        self._pending_events.clear()
        return events

    def get_all_events(self) -> list[Event]:
        """Get all events received so far."""
        return self._all_events.copy()

    # ── Context Helpers ──────────────────────────────────────────────

    def format_context(self, last_n: int = 20) -> str:
        """Format recent context as a readable string for LLM prompts."""
        lines = []
        for msg_data in self._context[-last_n:]:
            speaker = msg_data.get("agent_name", msg_data.get("agent_id", "?")[:8])
            msg_type = msg_data.get("type", "chat")
            content = msg_data.get("content", "")
            emoji = {"proposal": "💡", "question": "❓", "risk": "⚠️", "objection": "🚫",
                     "vote": "🗳️", "summary": "📝", "decision": "✅"}.get(msg_type, "💬")
            lines.append(f"{emoji} [{speaker}]({msg_type}): {content[:200]}")
        return "\n".join(lines)

    # ── File-based IPC ───────────────────────────────────────────────

    def _append_event_to_file(self, event: Event) -> None:
        """Append event to JSONL file for external consumers."""
        self._all_events.append(event)
        try:
            data = {
                "type": event.type.value if hasattr(event.type, "value") else str(event.type),
                "timestamp": time.time(),
                "data": event.data,
            }
            if event.message:
                data["message"] = {
                    "id": event.message.id,
                    "agent_id": event.message.agent_id,
                    "agent_name": event.message.agent_name,
                    "type": event.message.type,
                    "content": event.message.content,
                }
            with open(self._events_file, "a") as f:
                f.write(json.dumps(data, default=str) + "\n")
        except Exception as e:
            logger.error("Failed to write event file: %s", e)

    def read_response_file(self) -> list[dict]:
        """Read responses from the response file (for external agent integration)."""
        responses = []
        if not self._responses_file.exists():
            return responses
        try:
            with open(self._responses_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        responses.append(json.loads(line))
            # Clear the file after reading
            self._responses_file.write_text("")
        except Exception as e:
            logger.error("Failed to read response file: %s", e)
        return responses

    # ── Internal ─────────────────────────────────────────────────────

    def _add_to_context(self, message: Message) -> None:
        self._context.append({
            "id": message.id,
            "agent_id": message.agent_id,
            "agent_name": message.agent_name,
            "type": message.type,
            "content": message.content,
        })

    async def __aenter__(self) -> OpenClawMeetingBridge:
        return self

    async def __aexit__(self, *args) -> None:
        await self.stop()
