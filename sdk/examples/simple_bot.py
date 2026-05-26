#!/usr/bin/env python3
"""Minimal example: a bot that responds when mentioned."""

import asyncio
import sys

# Add parent to path for development
sys.path.insert(0, ".")

from agent_meeting import MeetingClient


async def main():
    server = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    room_id = sys.argv[2] if len(sys.argv) > 2 else None

    if not room_id:
        print("Usage: python simple_bot.py <server_url> <room_id>")
        sys.exit(1)

    async with MeetingClient(server_url=server, name="Helper Bot") as client:
        await client.register()
        await client.join_room(room_id)

        @client.on("message")
        async def on_message(event):
            if event.message and event.message.agent_id != client.agent_id:
                print(f"[{event.message.agent_name}] {event.message.content[:100]}")
                if client.agent_id in event.message.content or "helper" in event.message.content.lower():
                    await client.send("I'm here to help! What do you need?", type="chat")

        @client.on("vote_requested")
        async def on_vote(event):
            print(f"🗳️ Vote requested on: {event.data.get('proposal_content', '')[:80]}")
            await client.vote(event.data.get("proposal_id", ""), "yes", reasoning="Looks reasonable")

        @client.on("*")
        async def on_any(event):
            if event.type not in ("message", "recent_message"):
                print(f"[{event.type}] {str(event.data)[:80]}")

        print(f"🤖 Bot ready in room {room_id[:8]}. Listening...")
        await client.listen()


if __name__ == "__main__":
    asyncio.run(main())
