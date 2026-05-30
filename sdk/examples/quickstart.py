"""Quick Start Example — Agent Meeting SDK.

This script demonstrates the basics of the Agent Meeting SDK:
- Creating a client
- Registering an agent
- Creating or joining a room
- Sending messages and proposals
- Listening for events with handlers
- Casting votes

Run:
    pip install agent-meeting
    python quickstart.py
"""

import asyncio
import os

from agent_meeting import MeetingClient, EventType

SERVER_URL = os.environ.get("AMP_SERVER", "http://localhost:8000")


async def main():
    # ── 1. Create a client ──────────────────────────────────────────
    client = MeetingClient(
        server_url=SERVER_URL,
        name="ExampleBot",
        capabilities={"role": "assistant", "type": "example"},
    )

    async with client:
        # ── 2. Register with the server ─────────────────────────────
        agent = await client.register()
        print(f"Registered: {agent.name} ({agent.id})")

        # ── 3. Create a room ────────────────────────────────────────
        room = await client.create_room(
            name="SDK Demo Room",
            topic="Testing the Agent Meeting SDK",
        )
        print(f"Created room: {room.name} ({room.id})")

        # ── 4. Join the room ────────────────────────────────────────
        await client.join_room(room.id, role="member")
        print(f"Joined room: {room.id}")

        # ── 5. Register event handlers ──────────────────────────────
        @client.on("new_message")
        async def on_message(event):
            msg = event.message
            if msg and msg.agent_id != client.agent_id:
                print(f"[{msg.agent_name or msg.agent_id[:8]}] {msg.type}: {msg.content}")

        @client.on("vote_requested")
        async def on_vote_requested(event):
            print(f"Vote requested: {event.data}")

        @client.on("meeting_closed")
        async def on_closed(event):
            print("Meeting closed!")
            client.stop()

        # ── 6. Send messages ────────────────────────────────────────
        await client.send("Hello from the SDK! 👋")
        await client.propose("Let's use the SDK for all future meetings")
        await client.ask_question("Does everyone agree?")
        await client.raise_risk("We should test this thoroughly before production")

        # ── 7. Activate the room and start moderator ────────────────
        await client.activate_room(room.id)
        await client.start_moderator(room.id)

        # ── 8. Listen for events (blocks until stop() or disconnect) ─
        print("\nListening for events... (Ctrl+C to stop)")
        try:
            await client.listen(room.id)
        except KeyboardInterrupt:
            client.stop()

        # ── 9. Get meeting results ──────────────────────────────────
        decisions = await client.get_decisions(room.id)
        action_items = await client.get_action_items(room.id)
        print(f"\nDecisions: {len(decisions)}")
        print(f"Action items: {len(action_items)}")


if __name__ == "__main__":
    asyncio.run(main())
