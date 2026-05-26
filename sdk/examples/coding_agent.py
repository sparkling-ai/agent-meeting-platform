#!/usr/bin/env python3
"""CodingAgent — uses codex CLI to join meetings and respond as a real coding agent.

This is a real agent integration: codex joins a meeting, listens to messages,
thinks about them using its LLM, and posts responses back.

Usage:
    # Terminal 1: Start backend
    cd backend && uv run uvicorn app.main:app --port 8000 --host 0.0.0.0

    # Terminal 2: Create a room and start moderator
    python -c "
    import asyncio
    from agent_meeting import MeetingClient
    async def main():
        c = MeetingClient(server_url='http://localhost:8000', name='Setup')
        await c.register()
        room = await c.create_room(name='Architecture Review', topic='Should we use microservices or monolith?')
        await c.join_room(room.id)
        await c.activate_room(room.id)
        await c.start_moderator()
        print(f'Room ID: {room.id}')
        await c.close()
    asyncio.run(main())
    "

    # Terminal 3: Start coding agent
    python coding_agent.py --room <room_id> --name "Dev Agent" --role "Senior Developer"
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from agent_meeting import MeetingClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("coding_agent")


class CodingAgent:
    """An agent that uses codex/opencode CLI to participate in meetings."""

    def __init__(
        self,
        server_url: str,
        name: str,
        role: str = "Senior Developer",
        working_dir: str | None = None,
        use_codex: bool = True,
    ):
        self.server_url = server_url
        self.name = name
        self.role = role
        self.working_dir = working_dir or os.getcwd()
        self.use_codex = use_codex
        self.client = MeetingClient(
            server_url=server_url,
            name=name,
            capabilities={"role": role, "type": "coding_agent", "can_investigate": True},
        )
        self._context: list[str] = []
        self._turn_count = 0

    async def register_and_join(self, room_id: str) -> None:
        """Register agent and join the room."""
        await self.client.register()
        await self.client.join_room(room_id)
        logger.info("✅ %s registered and joined room %s", self.name, room_id[:8])

    async def think_and_respond(self, prompt: str, max_tokens: int = 500) -> str:
        """Use codex/opencode to generate a response."""
        if self.use_codex:
            return await self._codex_think(prompt, max_tokens)
        else:
            return await self._opencode_think(prompt, max_tokens)

    async def _codex_think(self, prompt: str, max_tokens: int = 500) -> str:
        """Use codex exec to think about something."""
        try:
            result = await asyncio.create_subprocess_exec(
                "codex", "exec",
                "--full-auto",
                "--ephemeral",
                "-m", "o4-mini",
                "-o", "/dev/stderr",  # last message to stderr for debugging
                prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_dir,
            )
            stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=120)
            response = stdout.decode().strip() if stdout else ""

            if not response:
                # Try to extract from stderr
                err = stderr.decode().strip() if stderr else ""
                if err:
                    # codex writes the last message to the output file
                    response = err[-500:] if len(err) > 500 else err

            return response or "[No response from codex]"

        except asyncio.TimeoutError:
            logger.warning("Codex timeout")
            return "[Codex timed out after 120s]"
        except FileNotFoundError:
            logger.error("codex not found — falling back to basic response")
            return f"As {self.name} ({self.role}), I need to review this further."

    async def _opencode_think(self, prompt: str, max_tokens: int = 500) -> str:
        """Use opencode run to think about something."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "opencode", "run", "-m", "openrouter/google/gemini-2.5-flash",
                prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_dir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            # opencode outputs the response to stdout, with some ANSI formatting
            response = stdout.decode().strip() if stdout else ""
            # Clean ANSI escape codes
            import re
            response = re.sub(r'\x1b\[[0-9;]*m', '', response)
            # Remove the "> build" line and other metadata
            lines = [l.strip() for l in response.split('\n') if l.strip() and not l.strip().startswith('>')]
            return '\n'.join(lines) or "[No response from opencode]"

        except asyncio.TimeoutError:
            return f"[opencode timed out]"
        except FileNotFoundError:
            return f"[opencode not found]"

    async def run(self, room_id: str) -> None:
        """Main event loop — listen and respond."""
        from agent_meeting.models import EventType

        @self.client.on("recent_message")
        async def on_recent(event):
            """Catch up on recent messages."""
            if event.message and event.message.agent_id != self.client.agent_id:
                self._context.append(
                    f"[{event.message.agent_name or event.message.agent_id[:8]}]({event.message.type}): {event.message.content[:200]}"
                )

        @self.client.on("new_message")
        async def on_message(event):
            """React to new messages."""
            if not event.message:
                return
            if event.message.agent_id == self.client.agent_id:
                return  # Skip own messages

            msg = event.message
            speaker = msg.agent_name or msg.agent_id[:8]
            self._context.append(f"[{speaker}]({msg.type}): {msg.content[:200]}")
            self._turn_count += 1

            # Only respond every few messages (don't dominate)
            if self._turn_count % 3 != 0 and msg.type == "chat":
                return

            # Generate response using codex
            prompt = (
                f"You are {self.name}, a {self.role} in a team meeting.\n"
                f"The topic is being discussed. Here's what's been said recently:\n"
                + "\n".join(self._context[-10:]) +
                f"\n\n{speaker} just said: {msg.content}\n\n"
                f"Write a brief, insightful response (2-3 sentences max). "
                f"Be specific and practical. Focus on your area of expertise as {self.role}."
            )

            logger.info("🤔 Thinking about: '%s' from %s...", msg.content[:50], speaker)
            response = await self.think_and_respond(prompt)

            if response and response != "[No response from codex]":
                # Determine message type
                msg_type = "chat"
                if "?" in msg.content:
                    msg_type = "chat"  # Answer questions
                if msg.type == "proposal":
                    msg_type = "chat"  # Comment on proposals

                await self.client.send(response[:500], type=msg_type)
                logger.info("💬 Responded: %s", response[:80])

        @self.client.on("vote_requested")
        async def on_vote(event):
            """Vote on proposals."""
            proposal = event.data.get("proposal_content", "")
            prompt = (
                f"You are {self.name}, a {self.role}. Should we approve this proposal?\n\n"
                f"Proposal: {proposal}\n\n"
                f"Context:\n" + "\n".join(self._context[-10:]) +
                "\n\nRespond with ONLY 'yes' or 'no' and a brief reason."
            )
            logger.info("🗳️ Analyzing proposal...")
            analysis = await self.think_and_respond(prompt)
            choice = "yes" if "yes" in analysis.lower()[:50] else "no"
            await self.client.vote(
                event.data.get("proposal_id", ""),
                choice,
                reasoning=analysis[:200],
            )
            logger.info("🗳️ Voted: %s", choice)

        @self.client.on("investigation_approved")
        async def on_investigate(event):
            """Handle investigation requests."""
            topic = event.data.get("topic", "")
            prompt = (
                f"You are {self.name}, a {self.role}. Research this topic:\n\n"
                f"{topic}\n\nProvide a concise summary (2-3 sentences) with key findings."
            )
            logger.info("🔍 Investigating: %s", topic[:60])
            findings = await self.think_and_respond(prompt)
            await self.client.send(
                f"📊 Investigation findings: {findings[:500]}",
                type="chat",
            )
            logger.info("📊 Posted investigation results")

        @self.client.on("meeting_closed")
        async def on_close(event):
            """Handle meeting close."""
            logger.info("🏁 Meeting closed!")
            self.client.stop()

        logger.info("🎧 Listening for events...")
        await self.client.listen(room_id)


async def main():
    parser = argparse.ArgumentParser(description="Coding Agent — joins a meeting via codex/opencode")
    parser.add_argument("--server", default="http://localhost:8000", help="Server URL")
    parser.add_argument("--room", required=True, help="Room ID to join")
    parser.add_argument("--name", default="Dev Agent", help="Agent name")
    parser.add_argument("--role", default="Senior Developer", help="Agent role")
    parser.add_argument("--codex", action="store_true", default=True, help="Use codex (default)")
    parser.add_argument("--opencode", action="store_true", help="Use opencode instead")
    parser.add_argument("--cwd", default=None, help="Working directory for codex")
    args = parser.parse_args()

    agent = CodingAgent(
        server_url=args.server,
        name=args.name,
        role=args.role,
        working_dir=args.cwd,
        use_codex=not args.opencode,
    )

    print(f"🤖 {args.name} ({args.role}) joining room {args.room[:8]}...")
    print(f"   Engine: {'codex' if agent.use_codex else 'opencode'}")

    await agent.register_and_join(args.room)
    await agent.run(args.room)


if __name__ == "__main__":
    asyncio.run(main())
