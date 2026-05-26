#!/usr/bin/env python3
"""Multi-agent meeting: creates a room, starts agents, runs a full meeting."""

import asyncio
import json
import os
import sys

sys.path.insert(0, ".")

from agent_meeting import MeetingClient

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

AGENT_PERSONAS = [
    {"name": "Alex-PM", "role": "Product Manager", "style": "Focus on user value, data-driven, prioritizes ruthlessly"},
    {"name": "Jordan-Arch", "role": "Lead Architect", "style": "Cautious, thinks about edge cases, scalability, tech debt"},
    {"name": "Sam-Dev", "role": "Senior Developer", "style": "Practical, hates over-engineering, wants concrete specs"},
    {"name": "Riley-QA", "role": "QA Lead", "style": "Thinks about failure modes, testability, quality metrics"},
]

MEETING_TOPIC = "Redesign authentication: implement passwordless (magic links) + SSO (Google/GitHub). Current issues: password resets = 30% of support tickets, no SSO. Timeline: 3 weeks."


async def call_llm(system: str, user: str) -> str:
    """Quick LLM call via OpenRouter."""
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


def parse_llm_response(raw: str) -> tuple[str, str]:
    """Parse LLM response into (type, content)."""
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


async def create_agent_client(server_url: str, persona: dict) -> MeetingClient:
    """Create and register an agent client."""
    client = MeetingClient(
        server_url=server_url,
        name=persona["name"],
        capabilities={"role": persona["role"], "style": persona["style"]},
    )
    await client.register()

    # Track conversation context
    context = [f"TOPIC: {MEETING_TOPIC}"]

    @client.on("message")
    async def on_message(event):
        if not event.message or event.message.agent_id == client.agent_id:
            return

        # Track what others say
        name = event.message.agent_name or event.message.agent_id[:8]
        context.append(f"[{name}]({event.message.type}): {event.message.content[:200]}")

    @client.on("turn_started")
    async def on_turn(event):
        if event.data.get("agent_id") != client.agent_id:
            return

        system = (
            f"You are {persona['name']}, the {persona['role']}. "
            f"Style: {persona['style']}. "
            f"Respond with JSON: {{\"type\": \"chat|question|proposal|objection|risk|vote|summary\", \"content\": \"your 1-3 sentence response\"}}"
        )
        user_msg = f"Discussion so far:\n" + "\n".join(context[-8:]) + f"\n\nYour response as {persona['name']} (JSON only):"

        raw = await call_llm(system, user_msg)
        msg_type, content = parse_llm_response(raw)
        await client.send(content[:500], type=msg_type)
        context.append(f"[{persona['name']}]({msg_type}): {content[:200]}")
        print(f"  💬 {persona['name']}: {msg_type} — {content[:80]}")

    @client.on("vote_requested")
    async def on_vote(event):
        proposal = event.data.get("proposal_content", "")
        analysis = await call_llm(
            f"You are {persona['name']}, the {persona['role']}. Should we approve this proposal?",
            f"Proposal: {proposal}\nRespond: yes or no with brief reasoning.",
        )
        choice = "yes" if "yes" in analysis.lower()[:20] else "no"
        await client.vote(event.data.get("proposal_id", ""), choice, reasoning=analysis[:200])
        print(f"  🗳️ {persona['name']}: {choice}")

    return client


async def main():
    server = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

    print("=" * 70)
    print("📋 SDK Multi-Agent Meeting Test")
    print("=" * 70)

    # Create agents
    print("\n1️⃣ Creating agents...")
    agents = []
    for persona in AGENT_PERSONAS:
        client = await create_agent_client(server, persona)
        agents.append(client)
        print(f"  ✅ {persona['name']} registered ({client.agent_id[:8]})")

    # Create room
    print("\n2️⃣ Creating room...")
    room = await agents[0].create_room(
        name="Auth Strategy Decision",
        topic=MEETING_TOPIC,
        agenda=[
            {"title": "Problem review", "timebox_minutes": 5},
            {"title": "Solution proposals", "timebox_minutes": 10},
            {"title": "Vote", "timebox_minutes": 3},
        ],
    )
    room_id = room.id
    print(f"  🏠 Room created: {room_id[:8]}")

    # All agents join
    print("\n3️⃣ Joining room...")
    for client in agents[1:]:
        await client.join_room(room_id)
    await agents[0].activate_room(room_id)
    print(f"  ✅ {len(agents)} agents joined, room active")

    # Start moderator
    print("\n4️⃣ Starting moderator...")
    result = await agents[0].start_moderator(room_id)
    print(f"  🤖 Moderator: {result.get('status', 'started')}")
    state = await agents[0].get_moderator_state(room_id)
    print(f"  📊 Phase: {state.phase}")

    # Discussion rounds
    print("\n5️⃣ Discussion rounds...")
    for round_num in range(1, 3):
        print(f"\n  --- Round {round_num} ---")
        for client in agents:
            persona = next(p for p in AGENT_PERSONAS if p["name"] == client.name)
            system = (
                f"You are {persona['name']}, the {persona['role']}. "
                f"Style: {persona['style']}. "
                f"Respond with JSON: {{\"type\": \"chat|question|proposal|objection|risk\", \"content\": \"your 1-3 sentence response\"}}"
            )
            messages, _ = await client.get_messages(room_id, limit=6)
            context = "\n".join(f"[{m.agent_name}]({m.type}): {m.content[:100]}" for m in messages[-6:])
            raw = await call_llm(system, f"Discussion:\n{context}\n\nYour response (JSON only):")
            msg_type, content = parse_llm_response(raw)
            await client.send(content[:500], type=msg_type, room_id=room_id)
            print(f"    💬 {persona['name']}: {msg_type}")

    # Proposal + vote
    print("\n6️⃣ Proposal & voting...")
    proposal = await agents[0].send(
        "Proposal: Implement passwordless auth (magic links + SSO). "
        "3-week timeline. Jordan leads architecture, Sam implements, Riley tests.",
        type="proposal",
        room_id=room_id,
    )
    print(f"  💡 Proposal by {agents[0].name} (id: {proposal.id[:8]})")

    for client in agents[1:]:
        await client.vote(proposal.id, "yes", reasoning="Agreed, solid plan.", room_id=room_id)
        print(f"  🗳️ {client.name}: yes")

    # Close meeting
    print("\n7️⃣ Closing meeting...")
    close_result = await agents[0].close_meeting(room_id)
    print(f"  ✅ Meeting closed")

    # Final stats
    decisions = await agents[0].get_decisions(room_id)
    action_items = await agents[0].get_action_items(room_id)
    messages, total = await agents[0].get_messages(room_id)

    print(f"\n{'='*70}")
    print(f"📊 RESULTS")
    print(f"{'='*70}")
    print(f"  Messages: {total}")
    print(f"  Decisions: {len(decisions)}")
    print(f"  Action Items: {len(action_items)}")
    for d in decisions:
        print(f"  ✅ {d.title} ({d.status})")
    for a in action_items:
        print(f"  📌 {a.description} [{a.status}]")

    # Cleanup
    for client in agents:
        await client.close()

    print(f"\n✅ Meeting complete!")


if __name__ == "__main__":
    if not OPENROUTER_API_KEY:
        print("❌ OPENROUTER_API_KEY not set")
        sys.exit(1)
    asyncio.run(main())
