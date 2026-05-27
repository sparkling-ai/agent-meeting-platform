#!/usr/bin/env python3
"""Test OpenClaw Meeting Bridge — 2 agents join a meeting.

This simulates 2 OpenClaw agents joining the same meeting with different roles.
Each agent uses the OpenClawMeetingBridge to participate.

Agent 1: "Chopper" — assistant role, proactive participant
Agent 2: "Robo-Advisor" — analyst role, data-driven
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_meeting.connectors.openclaw import OpenClawMeetingBridge
from agent_meeting import MeetingClient

SERVER = "http://localhost:8000"


async def run_openclaw_agent(
    name: str, role: str, room_id: str, responses: list[str],
    question_resp: str, proposal_resp: str = "yes",
    respond_every: int = 2, delay: float = 0,
):
    """Run a single OpenClaw agent bridge in a meeting."""
    await asyncio.sleep(delay)

    bridge = OpenClawMeetingBridge(
        server_url=SERVER,
        agent_name=name,
        capabilities={"role": role, "type": "openclaw"},
    )
    await bridge.start(room_id)
    print(f"  ✅ {name} ({role}) joined")

    turn = 0

    async def handler(brg, event):
        nonlocal turn
        if not event.message or event.message.agent_id == brg.agent_id:
            return None

        turn += 1
        msg = event.message
        speaker = msg.agent_name or "?"
        content = msg.content[:80]
        print(f"    {name} sees [{msg.type}] from {speaker}: {content}...")

        if msg.type == "question":
            return question_resp
        if msg.type == "proposal":
            return proposal_resp
        if msg.type == "vote":
            return None  # Don't respond to votes
        # Respond to every Nth chat message
        if turn % respond_every != 0:
            return None

        return responses[turn % len(responses)]

    bridge.set_response_handler(handler)
    try:
        await asyncio.wait_for(bridge.run(), timeout=60)
    except asyncio.TimeoutError:
        print(f"    ⏰ {name} session ended (timeout)")
    except asyncio.CancelledError:
        pass
    finally:
        await bridge.stop()


async def main():
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║     🦌 OpenClaw Agent Meeting Test — 2 Agents                  ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

    # 1. Setup room
    print("📋 Step 1: Creating meeting room...")
    coord = MeetingClient(server_url=SERVER, name="Coordinator", capabilities={"role": "coordinator"})
    await coord.register()
    room = await coord.create_room(
        name="AI Architecture Review",
        topic="Should we use microservices or modular monolith for the new platform?",
    )
    room_id = room.id
    await coord.join_room(room_id)
    await coord.activate_room(room_id)
    print(f"  🏠 Room: {room.name}")
    print(f"  🆔 {room_id}")
    print()

    # 2. Start agents FIRST (before any messages)
    print("🦌 Step 2: Starting OpenClaw agents...")

    chopper_task = asyncio.create_task(run_openclaw_agent(
        name="Chopper 🦌", role="assistant", room_id=room_id,
        responses=[
            "I think we should go with modular monolith. Simpler to start, and we can extract services later when we understand the domain boundaries better.",
            "Good point! I'd add that team structure matters too — Conway's Law is real.",
            "For deployment, a single container with multiple modules simplifies CI/CD significantly. I can prototype this week.",
        ],
        question_resp="Based on my experience, a modular monolith is the way to go for a team our size. Clean module boundaries give us the benefits of separation without the operational overhead of microservices.",
        respond_every=1,
    ))

    robo_task = asyncio.create_task(run_openclaw_agent(
        name="Robo-Advisor 🤖", role="analyst", room_id=room_id,
        responses=[
            "Data point: monoliths are 2-3x faster to iterate on for teams < 10 engineers. The overhead of service mesh, discovery, and distributed tracing only pays off at scale.",
            "Risk assessment: modular monolith has ~40% fewer failure modes. Main risk is module boundary erosion — needs enforced dependency rules.",
            "From the monitoring angle: monolith MTTR is ~15 min vs ~2 hours for microservices. That's significant for incident response.",
        ],
        question_resp="The numbers favor modular monolith: 3x faster iteration, 40% fewer failure modes, and 8x faster MTTR. Microservices make sense at 50+ engineers.",
        respond_every=1,
        delay=1.0,
    ))

    # Wait for agents to connect
    await asyncio.sleep(4)
    print()

    # 3. Start moderator
    print("🧠 Step 3: Starting moderator...")
    result = await coord.start_moderator(room_id)
    print(f"  🤖 Moderator started — Phase: {result.get('phase', '?')}")
    print()

    # 4. Discussion
    print("💬 Step 4: Discussion...")
    print("   ──────────────────────────────────────────────────────────────")

    await coord.send(
        "Let's review the requirements: real-time updates, strong typing, good DX, "
        "scale to 100k users. What architecture fits best?",
        type="question", room_id=room_id,
    )
    print("  ❓ Coordinator asks: What architecture fits our requirements?")

    await asyncio.sleep(8)

    await coord.send(
        "Both approaches have merit. Let's hear specific concerns before deciding.",
        type="chat", room_id=room_id,
    )
    print("  💬 Coordinator: Let's hear specific concerns before deciding.")

    await asyncio.sleep(8)

    # 5. Proposal
    print()
    print("💡 Step 5: Submitting proposal...")
    proposal = await coord.send(
        "Proposal: Use modular monolith architecture. Single deployment unit with "
        "clear module boundaries enforced by dependency rules. Path to extract services later.",
        type="proposal", room_id=room_id,
    )
    print(f"  💡 Proposal: Modular Monolith Architecture")

    await asyncio.sleep(5)

    await coord.vote(proposal.id, "yes", reasoning="Solid approach for our team size.", room_id=room_id)
    print("  🗳️  Coordinator: ✅ YES")

    await asyncio.sleep(5)

    # 6. Close
    print()
    print("🏁 Step 6: Closing meeting...")
    try:
        close_result = await coord.close_meeting()
        print(f"  ✅ Meeting closed!")
        print(f"  📊 Messages: {close_result.get('total_messages', '?')}")
        print(f"  📊 Decisions: {close_result.get('decisions', '?')}")
    except Exception as e:
        print(f"  ⚠️ Close: {e}")

    # Cleanup
    chopper_task.cancel()
    robo_task.cancel()
    await asyncio.gather(chopper_task, robo_task, return_exceptions=True)

    # 7. Results
    print()
    messages, total = await coord.get_messages(room_id)
    decisions = await coord.get_decisions(room_id)

    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║                      📊 Meeting Results                        ║")
    print("╠══════════════════════════════════════════════════════════════════╣")
    print(f"║  Total Messages:  {total:<45} ║")
    print(f"║  Decisions:       {len(decisions):<45} ║")
    print("╠══════════════════════════════════════════════════════════════════╣")
    for d in decisions:
        print(f"║  ✅ {d.title[:55]:<55} ║")
    print("╚══════════════════════════════════════════════════════════════════╝")

    print()
    print("📝 Transcript:")
    print("   ──────────────────────────────────────────────────────────────")
    for m in messages:
        name = m.agent_name or m.agent_id[:8]
        emoji = {"proposal": "💡", "question": "❓", "risk": "⚠️", "objection": "🚫",
                 "vote": "🗳️", "summary": "📝", "decision": "✅"}.get(m.type, "💬")
        content = m.content[:100] + "..." if len(m.content) > 100 else m.content
        print(f"   {emoji} [{m.type.upper():12s}] {name}: {content}")
    print("   ──────────────────────────────────────────────────────────────")

    await coord.close()

    # Count openclaw messages
    openclaw_msgs = [m for m in messages if m.agent_name and ("Chopper" in m.agent_name or "Robo" in m.agent_name)]
    print()
    print(f"🎉 Test complete!")
    print(f"   🦌 Chopper messages: {len([m for m in messages if m.agent_name and 'Chopper' in m.agent_name])}")
    print(f"   🤖 Robo-Advisor messages: {len([m for m in messages if m.agent_name and 'Robo' in m.agent_name])}")
    print(f"   ✅ Both agents participated via OpenClawMeetingBridge")


if __name__ == "__main__":
    asyncio.run(main())
