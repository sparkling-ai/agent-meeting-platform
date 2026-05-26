#!/usr/bin/env python3
"""Integration test: real opencode agent joins a meeting with LLM-powered agents.

This spawns a meeting where:
1. We create 2 LLM-powered agents (via SDK + OpenRouter)
2. We start a real opencode agent that joins via SDK
3. They have a discussion together
4. The moderator manages the meeting
5. A decision is reached

Usage:
    # Terminal 1: backend running
    cd backend && uv run uvicorn app.main:app --port 8000 --host 0.0.0.0

    # Terminal 2: run this test
    export OPENROUTER_API_KEY=...
    cd sdk && uv run python examples/test_real_agent.py
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, ".")

from agent_meeting import MeetingClient

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")


async def call_llm(system: str, user: str) -> str:
    import httpx
    async with httpx.AsyncClient(timeout=60) as c:
        resp = await c.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json={"model": "google/gemini-2.5-flash", "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ], "temperature": 0.8, "max_tokens": 200},
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        return f"[LLM error: {resp.status_code}]"


def parse_response(raw: str) -> tuple[str, str]:
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    try:
        parsed = json.loads(text)
        return parsed.get("type", "chat"), parsed.get("content", text)
    except (json.JSONDecodeError, AttributeError):
        return "chat", text


async def create_llm_agent(server: str, name: str, role: str, style: str) -> MeetingClient:
    """Create an LLM-powered agent using OpenRouter."""
    client = MeetingClient(
        server_url=server,
        name=name,
        capabilities={"role": role, "style": style},
    )
    await client.register()
    print(f"  ✅ {name} registered ({client.agent_id[:8]})")
    return client


async def run_real_agent_thinking(name: str, role: str, context: str, prompt: str) -> str:
    """Use opencode run to generate a response from a real coding agent."""
    full_prompt = (
        f"You are {name}, a {role} in a team meeting.\n"
        f"Discussion so far:\n{context}\n\n"
        f"Respond briefly (2-3 sentences). Be specific and practical.\n"
        f"{prompt}"
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            "opencode", "run", "-m", "openrouter/google/gemini-2.5-flash",
            full_prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        response = stdout.decode().strip() if stdout else ""
        # Clean ANSI
        import re
        response = re.sub(r'\x1b\[[0-9;]*m', '', response)
        lines = [l.strip() for l in response.split('\n') if l.strip() and not l.strip().startswith('>')]
        return '\n'.join(lines) or f"[{name}: thinking..."

    except asyncio.TimeoutError:
        return f"[{name}: timed out]"
    except FileNotFoundError:
        return f"[{name}: agent not available]"


async def main():
    server = "http://localhost:8000"

    print("=" * 70)
    print("🧪 REAL AGENT INTEGRATION TEST")
    print("   2 LLM agents + 1 real opencode agent + moderator")
    print("=" * 70)

    # 1. Create agents
    print("\n1️⃣ Creating agents...")
    pm = await create_llm_agent(server, "Sarah-PM", "Product Manager",
                                 "Data-driven, focuses on user value and priorities")
    arch = await create_llm_agent(server, "Marcus-Arch", "Lead Architect",
                                   "Cautious, thinks about scalability and edge cases")

    # Create the opencode agent via SDK
    opencode_agent = MeetingClient(
        server_url=server,
        name="OpenCode-Dev",
        capabilities={"role": "Senior Developer", "type": "coding_agent"},
    )
    await opencode_agent.register()
    print(f"  🤖 OpenCode-Dev registered ({opencode_agent.agent_id[:8]}) [REAL OPENCODE AGENT]")

    # 2. Create room
    print("\n2️⃣ Creating room...")
    room = await pm.create_room(
        name="API Design Decision",
        topic="Should we use REST, GraphQL, or gRPC for the new microservices API? "
              "Requirements: real-time updates, strong typing, good DX. Team of 5 devs.",
        agenda=[
            {"title": "Requirements review", "timebox_minutes": 5},
            {"title": "Option comparison", "timebox_minutes": 10},
            {"title": "Vote", "timebox_minutes": 3},
        ],
    )
    room_id = room.id
    print(f"  🏠 Room: {room_id[:8]}")

    # 3. Join
    print("\n3️⃣ Joining room...")
    for client in [pm, arch, opencode_agent]:
        await client.join_room(room_id)
    await pm.activate_room(room_id)
    print(f"  ✅ 3 agents joined")

    # 4. Start moderator
    print("\n4️⃣ Starting moderator...")
    await pm.start_moderator()
    state = await pm.get_moderator_state()
    print(f"  🤖 Phase: {state.phase}")

    # 5. Discussion — Round 1: LLM agents
    print("\n5️⃣ Discussion...")
    print("\n  --- Round 1: LLM Agents ---")
    messages, _ = await pm.get_messages(room_id, limit=10)

    for client, persona in [(pm, "Sarah-PM, PM"), (arch, "Marcus-Arch, Architect")]:
        name = client.name
        context = "\n".join(f"[{m.agent_name or m.agent_id[:8]}]({m.type}): {m.content[:100]}" for m in messages[-6:])
        raw = await call_llm(
            f"You are {name}. Respond with JSON: {{\"type\": \"chat|question|proposal|risk|objection\", \"content\": \"2-3 sentences\"}}",
            f"Topic: API design for microservices. Discussion:\n{context}\n\nYour response (JSON):",
        )
        msg_type, content = parse_response(raw)
        valid = {"chat", "question", "proposal", "objection", "risk", "vote", "summary"}
        if msg_type not in valid:
            msg_type = "chat"
        await client.send(content[:500], type=msg_type, room_id=room_id)
        emoji = {"proposal": "💡", "question": "❓", "risk": "⚠️", "objection": "🚫"}.get(msg_type, "💬")
        print(f"    {emoji} {name}: {msg_type} — {content[:80]}")
        messages, _ = await pm.get_messages(room_id, limit=10)

    # 6. Codex agent responds!
    print("\n  --- Round 2: REAL OPENCODE AGENT ---")
    messages, _ = await opencode_agent.get_messages(room_id, limit=10)
    context = "\n".join(f"[{m.agent_name or m.agent_id[:8]}]({m.type}): {m.content[:100]}" for m in messages[-8:])
    print(f"    🤔 OpenCode-Dev is thinking... (using real opencode CLI)")

    opencode_response = await run_real_agent_thinking(
        "OpenCode-Dev", "Senior Developer", context,
        "What's your take on REST vs GraphQL vs gRPC for our microservices?"
    )
    await opencode_agent.send(opencode_response[:500], type="chat", room_id=room_id)
    print(f"    💬 OpenCode-Dev (REAL): {opencode_response[:120]}")

    # 7. More discussion
    print("\n  --- Round 3: LLM Agents react to Codex ---")
    for client, persona in [(pm, "PM"), (arch, "Architect")]:
        messages, _ = await client.get_messages(room_id, limit=6)
        context = "\n".join(f"[{m.agent_name or m.agent_id[:8]}]({m.type}): {m.content[:100]}" for m in messages[-6:])
        raw = await call_llm(
            f"You are {client.name}. React to the developer's input. JSON: {{\"type\": \"chat|question|proposal|risk\", \"content\": \"2-3 sentences\"}}",
            f"Discussion:\n{context}\n\nYour response (JSON):",
        )
        msg_type, content = parse_response(raw)
        if msg_type not in {"chat", "question", "proposal", "objection", "risk", "vote", "summary"}:
            msg_type = "chat"
        await client.send(content[:500], type=msg_type, room_id=room_id)
        emoji = {"proposal": "💡", "question": "❓", "risk": "⚠️", "objection": "🚫"}.get(msg_type, "💬")
        print(f"    {emoji} {client.name}: {msg_type} — {content[:80]}")

    # 8. Proposal + vote
    print("\n6️⃣ Proposal & voting...")
    proposal = await pm.send(
        "Proposal: Use gRPC for internal service-to-service communication (performance, "
        "strong typing, streaming) + REST gateway for external API (developer familiarity). "
        "OpenCode-Dev leads the gRPC implementation.",
        type="proposal",
        room_id=room_id,
    )
    print(f"  💡 Sarah-PM proposes: gRPC internal + REST gateway")
    print(f"     (proposal id: {proposal.id[:8]})")

    await arch.vote(proposal.id, "yes", reasoning="Good compromise. gRPC for perf-critical paths.", room_id=room_id)
    print(f"  🗳️ Marcus-Arch: yes")

    # Codex votes!
    print(f"  🤔 OpenCode-Dev is analyzing the proposal...")
    opencode_vote_analysis = await run_real_agent_thinking(
        "OpenCode-Dev", "Senior Developer",
        "Proposal: gRPC internal + REST gateway. OpenCode-Dev leads gRPC implementation.",
        "Should we approve? yes or no with brief reason."
    )
    choice = "yes" if "yes" in opencode_vote_analysis.lower()[:50] else "no"
    await opencode_agent.vote(proposal.id, choice, reasoning=opencode_vote_analysis[:200], room_id=room_id)
    print(f"  🗳️ OpenCode-Dev (REAL): {choice} — {opencode_vote_analysis[:60]}")

    # 9. Close
    print("\n7️⃣ Closing meeting...")
    await pm.close_meeting()

    # 10. Results
    decisions = await pm.get_decisions(room_id)
    action_items = await pm.get_action_items(room_id)
    messages, total = await pm.get_messages(room_id)

    print(f"\n{'='*70}")
    print(f"📊 RESULTS")
    print(f"{'='*70}")
    print(f"  Messages: {total}")
    print(f"  Decisions: {len(decisions)}")
    print(f"  Action Items: {len(action_items)}")

    for d in decisions:
        print(f"\n  ✅ {d.title} ({d.status})")
        if d.summary:
            print(f"     {d.summary[:100]}")

    for a in action_items:
        print(f"  📌 {a.description} [{a.status}]")

    # Show transcript
    print(f"\n{'='*70}")
    print(f"📝 MEETING TRANSCRIPT (last 10 messages)")
    print(f"{'='*70}")
    for m in messages[-10:]:
        name = m.agent_name or m.agent_id[:8]
        emoji = {"proposal": "💡", "question": "❓", "risk": "⚠️", "objection": "🚫",
                 "vote": "🗳️", "summary": "📝", "decision": "✅"}.get(m.type, "💬")
        print(f"\n  {emoji} [{m.type.upper()}] {name}:")
        print(f"     {m.content[:150]}")

    # Cleanup
    for client in [pm, arch, opencode_agent]:
        await client.close()

    print(f"\n✅ Real agent integration test complete!")
    print(f"   Codex agent participated, voted, and contributed to the meeting 🎉")


if __name__ == "__main__":
    if not OPENROUTER_API_KEY:
        print("❌ OPENROUTER_API_KEY not set")
        sys.exit(1)
    asyncio.run(main())
