#!/usr/bin/env python3
"""Docker demo: creates 3 agents, a room, they chat a few rounds, then exit.

Designed to run inside the demo-agents container.
Set MEETING_SERVER to the backend URL (default: http://backend:8000).
"""

import asyncio
import os
import sys

sys.path.insert(0, ".")

from agent_meeting import MeetingClient

SERVER = os.environ.get("MEETING_SERVER", "http://backend:8000")

# Simple scripted responses per agent
SCRIPTS = {
    "Alice (Strategist)": [
        "I think we should focus on the core user experience first. Simplicity wins.",
        "Good points from both of you. Let me propose we vote on the priority order.",
    ],
    "Bob (Engineer)": [
        "From a technical standpoint, we need to ensure the API is solid before adding features.",
        "I agree with Alice on UX, but we also need the infrastructure to support it. Both matter.",
    ],
    "Carol (Designer)": [
        "The onboarding flow is critical — if users don't get value in 30 seconds, they leave.",
        "Let's design the simplest possible version first, then iterate based on feedback.",
    ],
}


async def run_agent(name: str, room_id: str, responses: list[str]) -> None:
    """Run a single agent that sends scripted messages and listens."""
    async with MeetingClient(server_url=SERVER, name=name) as client:
        await client.register()
        await client.join_room(room_id)

        sent = 0
        received_other = 0

        @client.on("message")
        async def on_message(event):
            nonlocal received_other
            if event.message and event.message.agent_id != client.agent_id:
                received_other += 1
                print(f"  [{name}] heard {event.message.agent_name}: {event.message.content[:80]}")

        # Send scripted messages with delays
        for msg in responses:
            await asyncio.sleep(3)
            await client.send(msg, type="chat")
            sent += 1
            print(f"  [{name}] sent ({sent}/{len(responses)}): {msg[:60]}...")

        # Wait a moment for any final messages to arrive
        await asyncio.sleep(5)
        print(f"  [{name}] done — sent {sent}, heard {received_other} messages from others")


async def main():
    print(f"🚀 Demo starting — server: {SERVER}")

    # ── Step 1: Alice creates the room ──
    async with MeetingClient(server_url=SERVER, name="Alice (Strategist)") as alice:
        await alice.register()
        room = await alice.create_room(
            name="Sprint Planning: v0.2",
            topic="Decide priorities for the next release",
            agenda=[
                {"title": "User experience improvements"},
                {"title": "API stability"},
                {"title": "Onboarding redesign"},
            ],
        )
        room_id = room.id
        await alice.activate_room(room_id)
        print(f"📋 Room created: {room.name} ({room_id[:8]})")

    # ── Step 2: Run all three agents concurrently ──
    print("🤖 Starting agents...")
    tasks = [
        run_agent(name, room_id, responses)
        for name, responses in SCRIPTS.items()
    ]
    await asyncio.gather(*tasks)

    print("✅ Demo meeting complete!")
    # Exit cleanly — container has restart: "no"
    await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
