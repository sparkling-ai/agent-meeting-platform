#!/usr/bin/env python3
"""Quick demo meeting — creates a room, adds agents, discusses, votes, closes."""

import asyncio
import json
import os
import sys
import time

# Use the SDK's venv via uv
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "sdk"))

from agent_meeting import MeetingClient

SERVER = "http://localhost:8000"

# Simulated agent responses (no LLM calls needed for demo)
RESPONSES = {
    "Sarah-PM": [
        ("chat", "Let's start by reviewing the problem. Our current auth system has password resets making up 30% of support tickets."),
        ("question", "What's the engineering effort estimate for magic links vs SSO?"),
        ("proposal", "Proposal: Implement passwordless auth (magic links) + SSO (Google/GitHub). 3-week timeline."),
    ],
    "Marcus-Arch": [
        ("chat", "From an architecture standpoint, magic links are simpler. SSO adds OAuth complexity but high value."),
        ("chat", "I'd estimate 2 weeks for magic links, 1 week for SSO integration. We can parallelize."),
        ("chat", "The proposal looks solid. I'll lead the architecture design."),
    ],
    "Sam-Dev": [
        ("risk", "Risk: Magic link emails might get flagged as spam. We need proper DKIM/SPF setup."),
        ("chat", "Agreed on the approach. I can start on the magic link flow this sprint."),
        ("chat", "One concern: we need a fallback for users without email access."),
    ],
}


async def main():
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║         🤖 Agent Meeting Platform — Live Demo                  ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

    # 1. Create agents
    print("📋 Step 1: Registering agents...")
    agents = {}
    for name in RESPONSES:
        client = MeetingClient(server_url=SERVER, name=name,
                              capabilities={"role": name.split("-")[1]})
        await client.register()
        agents[name] = client
        print(f"   ✅ {name} registered ({client.agent_id[:8]}...)")
    print()

    # 2. Create room
    print("🏠 Step 2: Creating meeting room...")
    room = await agents["Sarah-PM"].create_room(
        name="Auth Strategy Decision",
        topic="Redesign authentication: implement passwordless (magic links) + SSO (Google/GitHub)",
        agenda=[
            {"title": "Problem review", "timebox_minutes": 5},
            {"title": "Solution proposals", "timebox_minutes": 10},
            {"title": "Vote & close", "timebox_minutes": 3},
        ],
    )
    room_id = room.id
    print(f"   🏠 Room: {room.name}")
    print(f"   📝 Topic: {room.topic}")
    print()

    # 3. Join room
    print("👥 Step 3: Agents joining room...")
    for name, client in agents.items():
        await client.join_room(room_id)
        print(f"   👋 {name} joined")
    await agents["Sarah-PM"].activate_room(room_id)
    print(f"   🟢 Room activated")
    print()

    # 4. Start moderator
    print("🧠 Step 4: Starting LLM Moderator...")
    result = await agents["Sarah-PM"].start_moderator(room_id)
    state = await agents["Sarah-PM"].get_moderator_state(room_id)
    print(f"   🤖 Moderator started — Phase: {state.phase}")
    print()

    # 5. Discussion rounds
    print("💬 Step 5: Discussion")
    print("   ┌─────────────────────────────────────────────────────────┐")
    for round_num in range(3):
        print(f"   │  Round {round_num + 1}")
        for name in RESPONSES:
            client = agents[name]
            msg_type, content = RESPONSES[name][round_num]
            msg = await client.send(content, type=msg_type, room_id=room_id)
            emoji = {"proposal": "💡", "question": "❓", "risk": "⚠️", "objection": "🚫"}.get(msg_type, "💬")
            # Truncate for display
            display = content[:65] + "..." if len(content) > 65 else content
            print(f"   │  {emoji} [{name}] {display}")
            await asyncio.sleep(0.1)
    print("   └─────────────────────────────────────────────────────────┘")
    print()

    # 6. Voting
    print("🗳️  Step 6: Voting on proposal...")
    proposal_msg = await agents["Sarah-PM"].send(
        "Implement passwordless auth (magic links) + SSO (Google/GitHub). 3-week timeline.",
        type="proposal", room_id=room_id
    )
    print(f"   💡 Proposal submitted by Sarah-PM")
    for name in ["Marcus-Arch", "Sam-Dev"]:
        await agents[name].vote(proposal_msg.id, "yes",
                               reasoning="Solid plan, good timeline.", room_id=room_id)
        print(f"   🗳️  {name}: ✅ YES")
    await asyncio.sleep(0.1)
    print()

    # 7. Close meeting
    print("🏁 Step 7: Closing meeting...")
    close_result = await agents["Sarah-PM"].close_meeting(room_id)
    print(f"   ✅ Meeting closed")
    print(f"   📊 Messages: {close_result.get('total_messages', 'N/A')}")
    print(f"   📊 Decisions: {close_result.get('decisions', 'N/A')}")
    print(f"   📊 Action Items: {close_result.get('action_items', 'N/A')}")
    print()

    # 8. Show results
    decisions = await agents["Sarah-PM"].get_decisions(room_id)
    action_items = await agents["Sarah-PM"].get_action_items(room_id)
    messages, total = await agents["Sarah-PM"].get_messages(room_id)

    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║                      📊 Meeting Results                        ║")
    print("╠══════════════════════════════════════════════════════════════════╣")
    print(f"║  Total Messages:  {total:<45} ║")
    print(f"║  Decisions:       {len(decisions):<45} ║")
    print(f"║  Action Items:    {len(action_items):<45} ║")
    print("╠══════════════════════════════════════════════════════════════════╣")
    for d in decisions:
        print(f"║  ✅ {d.title[:55]:<55} ║")
    for a in action_items:
        desc = a.description[:52]
        print(f"║  📌 {desc:<55} ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

    # Transcript
    print("📝 Transcript (last 10 messages):")
    print("   ──────────────────────────────────────────────────────────")
    for m in messages[-10:]:
        name = m.agent_name or m.agent_id[:8]
        emoji = {"proposal": "💡", "question": "❓", "risk": "⚠️", "objection": "🚫",
                 "vote": "🗳️", "summary": "📝", "decision": "✅", "action_item": "📌"}.get(m.type, "💬")
        content = m.content[:70] + "..." if len(m.content) > 70 else m.content
        print(f"   {emoji} [{m.type.upper():12s}] {name}: {content}")
    print("   ──────────────────────────────────────────────────────────")
    print()

    # Cleanup
    for client in agents.values():
        await client.close()

    print("🎉 Demo complete! The Agent Meeting Platform is ready for your AI agents.")
    print()
    print("📚 Learn more:")
    print("   • SDK:     sdk/agent_meeting/")
    print("   • Examples: sdk/examples/")
    print("   • API:     http://localhost:8000/docs")
    print("   • Docs:    docs/")


if __name__ == "__main__":
    asyncio.run(main())
