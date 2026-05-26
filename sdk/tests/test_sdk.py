#!/usr/bin/env python3
"""Integration test for the Agent Meeting SDK.

Requires a running backend server on localhost:8000.
Usage: uv run python tests/test_sdk.py
"""

import asyncio
import sys
import os

sys.path.insert(0, ".")

from agent_meeting import MeetingClient, EventType


async def test_sdk():
    server = "http://localhost:8000"
    errors = []

    print("=" * 70)
    print("🧪 SDK Integration Test")
    print("=" * 70)

    # Test 1: Register agent
    print("\n1️⃣ Register agent...")
    client = MeetingClient(server_url=server, name="SDK Test Agent",
                           capabilities={"role": "tester"})
    agent = await client.register()
    assert agent.id, "Agent should have an ID"
    assert agent.name == "SDK Test Agent"
    print(f"  ✅ Registered: {agent.id[:8]}")

    # Test 2: Create room
    print("\n2️⃣ Create room...")
    room = await client.create_room(
        name="SDK Test Room",
        topic="Testing the SDK",
        agenda=[{"title": "Test item", "timebox_minutes": 5}],
    )
    assert room.id, "Room should have an ID"
    assert room.name == "SDK Test Room"
    print(f"  ✅ Room: {room.id[:8]}")

    # Test 3: Join room
    print("\n2b️⃣ Join room...")
    await client.join_room(room.id)
    await client.activate_room(room.id)
    print(f"  ✅ Joined room")

    # Test 4: Send messages of different types
    print("\n3️⃣ Send messages...")
    msg = await client.send("Hello from SDK!", type="chat")
    assert msg.id, "Message should have an ID"
    print(f"  ✅ Chat: {msg.id[:8]}")

    msg = await client.send("What's the plan?", type="question")
    print(f"  ✅ Question: {msg.id[:8]}")

    msg = await client.send("Risk: test might fail", type="risk")
    print(f"  ✅ Risk: {msg.id[:8]}")

    proposal = await client.send("Proposal: adopt SDK", type="proposal")
    print(f"  ✅ Proposal: {proposal.id[:8]}")

    # Test 4: Vote
    print("\n4️⃣ Vote on proposal...")
    vote = await client.vote(proposal.id, "yes", reasoning="SDK is great")
    assert vote.type == "vote"
    print(f"  ✅ Vote: {vote.id[:8]}")

    # Test 5: Get messages
    print("\n5️⃣ Get messages...")
    messages, total = await client.get_messages()
    assert total >= 5, f"Expected ≥5 messages, got {total}"
    print(f"  ✅ Total messages: {total}")

    # Test 6: Filter by type
    proposals, ptotal = await client.get_messages(msg_type="proposal")
    assert ptotal >= 1, f"Expected ≥1 proposal, got {ptotal}"
    print(f"  ✅ Proposals: {ptotal}")

    # Test 7: Moderator
    print("\n6️⃣ Start moderator...")
    mod_result = await client.start_moderator()
    assert mod_result.get("status") in ("started", "ok"), f"Unexpected: {mod_result}"
    print(f"  ✅ Moderator: {mod_result.get('status')}")

    state = await client.get_moderator_state()
    assert state.phase in ("discussion", "opening", "draft"), f"Unexpected phase: {state.phase}"
    print(f"  ✅ Phase: {state.phase}")

    # Test 8: Send more messages with moderator active
    print("\n7️⃣ Discussion with moderator...")
    for msg_type in ["chat", "question", "proposal"]:
        await client.send(f"SDK test message: {msg_type}", type=msg_type)
    messages2, total2 = await client.get_messages()
    assert total2 > total, "Should have more messages after moderator"
    print(f"  ✅ Messages after moderator: {total2}")

    # Test 9: Close meeting
    print("\n8️⃣ Close meeting...")
    close_result = await client.close_meeting()
    print(f"  ✅ Meeting closed: {close_result}")

    # Test 10: Get decisions and action items
    print("\n9️⃣ Check decisions & action items...")
    decisions = await client.get_decisions()
    action_items = await client.get_action_items()
    print(f"  Decisions: {len(decisions)}")
    print(f"  Action Items: {len(action_items)}")

    # Test 11: Event handler registration
    print("\n🔟 Event handler registration...")
    received = []

    @client.on("new_message")
    async def handler(event):
        received.append(event)

    # Verify handler is registered
    assert EventType.MESSAGE in client._handlers
    assert len(client._handlers[EventType.MESSAGE]) == 1
    print(f"  ✅ Handler registered")

    # Cleanup
    await client.close()

    print(f"\n{'='*70}")
    print(f"✅ ALL SDK TESTS PASSED!")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(test_sdk())
