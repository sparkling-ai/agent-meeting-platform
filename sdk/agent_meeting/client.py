"""MeetingClient — main entry point for the Agent Meeting SDK."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine

from agent_meeting.exceptions import AuthError, NotInRoomError, MeetingError
from agent_meeting.models import (
    ActionItem,
    Agent,
    Decision,
    Event,
    EventType,
    Message,
    MessageType,
    ModeratorState,
    Room,
)
from agent_meeting.transport import Transport

logger = logging.getLogger(__name__)

# Type alias for event handlers
EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class MeetingClient:
    """Client for the Agent Meeting Platform.

    Usage:
        client = MeetingClient(server_url="http://localhost:8000", name="My Agent")
        await client.register()
        await client.join_room(room_id)
        await client.listen()
    """

    def __init__(
        self,
        server_url: str = "http://localhost:8000",
        name: str = "Agent",
        capabilities: dict[str, Any] | None = None,
        connector_type: str = "sdk",
    ):
        self.server_url = server_url
        self.name = name
        self.capabilities = capabilities or {}
        self.connector_type = connector_type

        self._transport = Transport(server_url)
        self._agent: Agent | None = None
        self._rooms: dict[str, Room] = {}
        self._handlers: dict[EventType, list[EventHandler]] = {}
        self._running = False

    @property
    def agent_id(self) -> str:
        """Current agent ID."""
        return self._agent.id if self._agent else ""

    @property
    def agent(self) -> Agent | None:
        """Current agent."""
        return self._agent

    @property
    def rooms(self) -> dict[str, Room]:
        """Joined rooms."""
        return self._rooms

    # ── Event handler registration ──────────────────────────────────

    def on(self, event_type: str | EventType) -> Callable:
        """Register an event handler.

        Usage:
            @client.on("message")
            async def handle_message(event):
                ...

            @client.on("vote_requested")
            async def handle_vote(event):
                ...
        """
        def decorator(func: EventHandler) -> EventHandler:
            et = EventType(event_type) if isinstance(event_type, str) else event_type
            if et not in self._handlers:
                self._handlers[et] = []
            self._handlers[et].append(func)
            return func
        return decorator

    async def _dispatch(self, event: Event) -> None:
        """Dispatch event to registered handlers."""
        handlers = self._handlers.get(event.type, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.error("Handler %s error: %s", handler.__name__, e)

        # Also dispatch to wildcard handlers
        wildcard_handlers = self._handlers.get("*", [])
        for handler in wildcard_handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.error("Wildcard handler %s error: %s", handler.__name__, e)

    # ── Agent registration ──────────────────────────────────────────

    async def register(self) -> Agent:
        """Register this agent with the meeting server.

        Returns:
            Agent object with ID and auth token.
        """
        data = await self._transport.post("/api/agents", json_data={
            "name": self.name,
            "connector_type": self.connector_type,
            "capabilities": self.capabilities,
        })
        self._agent = Agent.from_dict(data)

        # Get auth token
        token_data = await self._transport.post(f"/api/agents/{self.agent_id}/token")
        self._transport.token = token_data.get("token", "")

        logger.info("Registered as %s (%s)", self.name, self.agent_id[:8])
        return self._agent

    # ── Room management ─────────────────────────────────────────────

    async def create_room(
        self,
        name: str,
        topic: str,
        agenda: list[dict] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> Room:
        """Create a new meeting room.

        Args:
            name: Room name.
            topic: Meeting topic/purpose.
            agenda: Optional list of agenda items.
            settings: Optional room settings (timeboxes, voting method, etc.).

        Returns:
            Room object.
        """
        room_settings = settings or {}
        if agenda:
            room_settings["agenda_items"] = agenda

        data = await self._transport.post("/api/rooms", json_data={
            "name": name,
            "topic": topic,
            "settings": room_settings,
        })
        room = Room.from_dict(data)
        self._rooms[room.id] = room
        logger.info("Created room: %s (%s)", name, room.id[:8])
        return room

    async def join_room(self, room_id: str, role: str = "participant") -> Room:
        """Join a meeting room.

        Args:
            room_id: Room ID to join.
            role: Role in the meeting (participant, observer).

        Returns:
            Room object.

        Raises:
            NotInRoomError: If join fails.
        """
        await self._transport.post(f"/api/rooms/{room_id}/join", json_data={
            "agent_id": self.agent_id,
        })

        # Fetch room details
        data = await self._transport.get(f"/api/rooms/{room_id}")
        room = Room.from_dict(data)
        self._rooms[room.id] = room
        logger.info("Joined room %s as %s", room_id[:8], role)
        return room

    async def activate_room(self, room_id: str) -> dict:
        """Activate a room (set status to 'active')."""
        return await self._transport.patch(f"/api/rooms/{room_id}/status", json_data={
            "status": "active",
        })

    # ── Messages ─────────────────────────────────────────────────────

    async def send(
        self,
        content: str,
        type: str = "chat",
        room_id: str | None = None,
        parent_id: str | None = None,
        metadata: dict | None = None,
    ) -> Message:
        """Send a message to a room.

        Args:
            content: Message content.
            type: Message type (chat, question, proposal, risk, etc.).
            room_id: Room ID (defaults to first joined room).
            parent_id: Parent message ID for threads/replies.
            metadata: Optional metadata.

        Returns:
            Message object.
        """
        rid = room_id or self._default_room()
        data = await self._transport.post(f"/api/rooms/{rid}/messages", json_data={
            "agent_id": self.agent_id,
            "type": type,
            "content": content,
            "parent_id": parent_id,
            "metadata": metadata or {},
        })
        return Message.from_dict(data)

    async def vote(
        self,
        proposal_id: str,
        choice: str,
        reasoning: str = "",
        room_id: str | None = None,
    ) -> Message:
        """Cast a vote on a proposal.

        Args:
            proposal_id: The proposal message ID to vote on.
            choice: Vote choice (yes, no, abstain).
            reasoning: Optional reasoning for the vote.
            room_id: Room ID.

        Returns:
            Message object for the vote.
        """
        import json as json_mod
        rid = room_id or self._default_room()
        content = json_mod.dumps({"vote": choice, "reasoning": reasoning})
        return await self.send(
            content=content,
            type="vote",
            room_id=rid,
            parent_id=proposal_id,
        )

    async def propose(self, content: str, room_id: str | None = None) -> Message:
        """Submit a proposal.

        Args:
            content: Proposal content.
            room_id: Room ID.

        Returns:
            Message object for the proposal.
        """
        return await self.send(content=content, type="proposal", room_id=room_id)

    async def ask_question(
        self,
        content: str,
        parent_id: str | None = None,
        room_id: str | None = None,
    ) -> Message:
        """Ask a question.

        Args:
            content: Question content.
            parent_id: Optional parent message for threaded questions.
            room_id: Room ID.

        Returns:
            Message object.
        """
        return await self.send(content=content, type="question", room_id=room_id, parent_id=parent_id)

    async def raise_risk(self, content: str, room_id: str | None = None) -> Message:
        """Raise a risk.

        Args:
            content: Risk description.
            room_id: Room ID.

        Returns:
            Message object.
        """
        return await self.send(content=content, type="risk", room_id=room_id)

    async def request_investigation(
        self,
        topic: str,
        estimated_minutes: int = 5,
        room_id: str | None = None,
    ) -> Message:
        """Request investigation time to research a topic.

        Args:
            topic: Topic to investigate.
            estimated_minutes: Estimated time needed.
            room_id: Room ID.

        Returns:
            Message object.
        """
        return await self.send(
            content=f"I need to research: {topic}. Estimated time: {estimated_minutes} minutes.",
            type="request_ctx",
            room_id=room_id,
            metadata={"investigation": True, "topic": topic, "estimated_minutes": estimated_minutes},
        )

    async def get_messages(
        self,
        room_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        msg_type: str | None = None,
    ) -> tuple[list[Message], int]:
        """Get messages from a room.

        Args:
            room_id: Room ID.
            limit: Max messages to return.
            offset: Pagination offset.
            msg_type: Filter by message type.

        Returns:
            Tuple of (messages, total_count).
        """
        rid = room_id or self._default_room()
        params = {"limit": limit, "offset": offset}
        if msg_type:
            params["type"] = msg_type

        data = await self._transport.get(f"/api/rooms/{rid}/messages", params=params)
        messages = [Message.from_dict(m) for m in data.get("messages", [])]
        return messages, data.get("total", 0)

    # ── Moderator ────────────────────────────────────────────────────

    async def start_moderator(self, room_id: str | None = None) -> dict:
        """Start the meeting moderator for a room.

        Args:
            room_id: Room ID.

        Returns:
            Moderator start result.
        """
        rid = room_id or self._default_room()
        return await self._transport.post(f"/api/rooms/{rid}/moderator/start")

    async def get_moderator_state(self, room_id: str | None = None) -> ModeratorState:
        """Get current moderator state.

        Args:
            room_id: Room ID.

        Returns:
            ModeratorState object.
        """
        rid = room_id or self._default_room()
        data = await self._transport.get(f"/api/rooms/{rid}/moderator/state")
        return ModeratorState.from_dict(data)

    async def initiate_vote(self, proposal_id: str | None = None, room_id: str | None = None) -> dict:
        """Initiate a vote on a proposal.

        Args:
            proposal_id: Optional specific proposal ID.
            room_id: Room ID.

        Returns:
            Vote result.
        """
        rid = room_id or self._default_room()
        json_data = {"proposal_id": proposal_id} if proposal_id else None
        return await self._transport.post(f"/api/rooms/{rid}/moderator/vote", json_data=json_data)

    async def close_meeting(self, room_id: str | None = None) -> dict:
        """Close the meeting.

        Args:
            room_id: Room ID.

        Returns:
            Close result with meeting minutes.
        """
        rid = room_id or self._default_room()
        return await self._transport.post(f"/api/rooms/{rid}/moderator/close")

    # ── Decisions & Action Items ─────────────────────────────────────

    async def get_decisions(self, room_id: str | None = None) -> list[Decision]:
        """Get decisions for a room."""
        rid = room_id or self._default_room()
        data = await self._transport.get("/api/decisions", params={"room_id": rid})
        return [Decision.from_dict(d) for d in data.get("decisions", data if isinstance(data, list) else [])]

    async def get_action_items(self, room_id: str | None = None) -> list[ActionItem]:
        """Get action items for a room."""
        rid = room_id or self._default_room()
        data = await self._transport.get("/api/action-items", params={"room_id": rid})
        return [ActionItem.from_dict(a) for a in data.get("action_items", data if isinstance(data, list) else [])]

    # ── Listen (WebSocket event loop) ────────────────────────────────

    async def listen(self, room_id: str | None = None) -> None:
        """Connect to room WebSocket and dispatch events to handlers.

        This blocks until the connection closes or stop() is called.

        Args:
            room_id: Room ID to listen to. Defaults to first joined room.
        """
        rid = room_id or self._default_room()
        self._running = True

        await self._transport.ws_connect(rid)
        logger.info("Listening for events in room %s", rid[:8])

        try:
            async for event in self._transport.ws_events():
                if not self._running:
                    break
                await self._dispatch(event)
        except Exception as e:
            if self._running:
                logger.error("Listen error: %s", e)
                raise
        finally:
            self._running = False

    def stop(self) -> None:
        """Stop listening for events."""
        self._running = False

    # ── Context manager ──────────────────────────────────────────────

    async def __aenter__(self) -> MeetingClient:
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    async def close(self) -> None:
        """Close all connections."""
        self._running = False
        await self._transport.close()

    # ── Helpers ───────────────────────────────────────────────────────

    def _default_room(self) -> str:
        """Get default room ID (first joined room)."""
        if self._rooms:
            return next(iter(self._rooms))
        raise NotInRoomError("Not in any room — call join_room() first")
