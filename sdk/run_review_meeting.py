#!/usr/bin/env python3
"""Agent Meeting: Project Review & Next Steps Discussion.

Agents review the Agent Meeting Platform's current state and decide on next priorities.
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, ".")

from agent_meeting import MeetingClient

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
SERVER = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

AGENT_PERSONAS = [
    {
        "name": "Alex-PM",
        "role": "Product Manager",
        "style": "Focuses on user value, prioritizes ruthlessly, data-driven. Thinks about what customers actually need."
    },
    {
        "name": "Jordan-Arch",
        "role": "Lead Architect",
        "style": "Cautious and thorough. Thinks about edge cases, scalability, technical debt, and system design."
    },
    {
        "name": "Sam-Dev",
        "role": "Senior Developer",
        "style": "Practical and opinionated. Hates over-engineering. Wants concrete specs and clear tasks."
    },
    {
        "name": "Riley-DevOps",
        "role": "DevOps / QA Lead",
        "style": "Thinks about deployment, reliability, testing, CI/CD. Wants everything shippable and reproducible."
    },
]

MEETING_TOPIC = (
    "Agent Meeting Platform — Sprint Review & Next Steps. "
    "Current state: SDK v0.1 done (WebSocket, event-driven, real agent integration with opencode). "
    "Frontend done (Next.js dark theme, room dashboard, admin). "
    "Moderator improved (turn management, loop escalation, drift detection). "
    "Remaining: WebSocket real-time in frontend (currently polling), Codex auth refresh, "
    "Claude Code agent integration, pip-installable SDK, Docker compose deployment. "
    "Goal: Review progress, discuss priorities, and decide on the next sprint scope."
)

AGENDA = [
    {"title": "Sprint Review — What we shipped", "timebox_minutes": 5},
    {"title": "What's working well / What needs fixing", "timebox_minutes": 5},
    {"title": "Prioritize remaining items", "timebox_minutes": 8},
    {"title": "Next sprint scope & assignments", "timebox_minutes": 5},
    {"title": "Vote on plan", "timebox_minutes": 3},
]


async def call_llm(system: str, user: str, max_tokens: int = 300) -> str:
    import httpx
    async with httpx.AsyncClient(timeout=90) as c:
        resp = await c.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json={
                "model": "google/gemini-2.5-flash",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.85,
                "max_tokens": max_tokens,
            },
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        return f"[LLM error: {resp.status_code} — {resp.text[:200]}]"


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


async def create_agent(persona: dict) -> tuple[MeetingClient, list[str]]:
    """Create agent with conversation tracking."""
    client = MeetingClient(
        server_url=SERVER,
        name=persona["name"],
        capabilities={"role": persona["role"], "style": persona["style"]},
    )
    await client.register()

    context: list[str] = [f"MEETING TOPIC: {MEETING_TOPIC}"]

    @client.on("new_message")
    async def on_message(event):
        if not event.message or event.message.agent_id == client.agent_id:
            return
        name = event.message.agent_name or event.message.agent_id[:8]
        context.append(f"[{name}]({event.message.type}): {event.message.content[:300]}")

    @client.on("turn_started")
    async def on_turn(event):
        if event.data.get("agent_id") != client.agent_id:
            return
        system = (
            f"You are {persona['name']}, the {persona['role']}. "
            f"Style: {persona['style']}. "
            f"You are in a meeting about the Agent Meeting Platform project review. "
            f"Be specific, reference actual features and issues. "
            f"Respond with JSON: {{\"type\": \"chat|question|proposal|objection|risk|summary\", \"content\": \"your 2-4 sentence response\"}}"
        )
        recent = "\n".join(context[-12:])
        user_msg = f"Discussion so far:\n{recent}\n\nYour response as {persona['name']} (JSON only):"
        raw = await call_llm(system, user_msg)
        msg_type, content = parse_response(raw)
        valid = {"chat", "question", "proposal", "objection", "risk", "vote", "summary"}
        if msg_type not in valid:
            msg_type = "chat"
        await client.send(content[:800], type=msg_type)
        context.append(f"[{persona['name']}]({msg_type}): {content[:300]}")
        print(f"    💬 {persona['name']}: {msg_type} — {content[:100]}")

    @client.on("vote_requested")
    async def on_vote(event):
        proposal = event.data.get("proposal_content", "")
        analysis = await call_llm(
            f"You are {persona['name']}, the {persona['role']}. Should we approve this proposal? Be brief.",
            f"Proposal: {proposal}\nRespond: yes or no with brief reasoning.",
            max_tokens=100,
        )
        choice = "yes" if "yes" in analysis.lower()[:30] else "no"
        await client.vote(event.data.get("proposal_id", ""), choice, reasoning=analysis[:300])
        print(f"    🗳️ {persona['name']}: {choice}")

    return client, context


async def main():
    print("=" * 70)
    print("📋 AGENT MEETING: Sprint Review & Next Steps")
    print("=" * 70)

    # 1. Create agents
    print("\n1️⃣ Creating agents...")
    agents = []
    contexts = []
    for persona in AGENT_PERSONAS:
        client, ctx = await create_agent(persona)
        agents.append(client)
        contexts.append(ctx)
        print(f"  ✅ {persona['name']} registered ({client.agent_id[:8]})")

    # 2. Create room
    print("\n2️⃣ Creating meeting room...")
    room = await agents[0].create_room(
        name="Sprint Review & Next Steps",
        topic=MEETING_TOPIC,
        agenda=AGENDA,
    )
    room_id = room.id
    print(f"  🏠 Room: {room_id[:12]}")

    # 3. Join
    print("\n3️⃣ Agents joining room...")
    for client in agents:
        await client.join_room(room_id)
    await agents[0].activate_room(room_id)
    print(f"  ✅ All {len(agents)} agents joined, room active")

    # 4. Start moderator
    print("\n4️⃣ Starting moderator...")
    result = await agents[0].start_moderator(room_id)
    print(f"  🤖 Moderator: {result.get('status', 'started')}")

    # 5. Discussion — 4 rounds for longer discussion
    NUM_ROUNDS = 4
    print(f"\n5️⃣ Discussion ({NUM_ROUNDS} rounds)...")
    for round_num in range(1, NUM_ROUNDS + 1):
        print(f"\n  {'─'*50}")
        print(f"  📌 Round {round_num}/{NUM_ROUNDS}")
        print(f"  {'─'*50}")

        for i, (client, persona) in enumerate(zip(agents, AGENT_PERSONAS)):
            system = (
                f"You are {persona['name']}, the {persona['role']}. "
                f"Style: {persona['style']}. "
                f"You are in a sprint review meeting for the Agent Meeting Platform. "
            )
            if round_num == 1:
                system += "Round 1: REVIEW what was shipped in the last sprint. Be specific about features."
            elif round_num == 2:
                system += "Round 2: What's working well? What needs fixing or improvement?"
            elif round_num == 3:
                system += "Round 3: PRIORITIZE the remaining items. Argue for what matters most."
            else:
                system += "Round 4: PROPOSE the next sprint scope. Be concrete about assignments and timeline."

            system += (
                " Respond with JSON: {\"type\": \"chat|question|proposal|objection|risk|summary\", "
                "\"content\": \"your 2-4 sentence response\"}"
            )

            messages, _ = await client.get_messages(room_id, limit=10)
            history = ""
            for m in messages[-10:]:
                name = m.agent_name or m.agent_id[:8]
                history += f"\n[{name}]({m.type}): {m.content[:150]}"

            raw = await call_llm(system, f"Meeting discussion:\n{history}\n\nYour response (JSON only):")
            msg_type, content = parse_response(raw)
            valid = {"chat", "question", "proposal", "objection", "risk", "vote", "summary"}
            if msg_type not in valid:
                msg_type = "chat"
            await client.send(content[:800], type=msg_type, room_id=room_id)
            contexts[i].append(f"[{persona['name']}]({msg_type}): {content[:300]}")
            print(f"    💬 {persona['name']}: {msg_type} — {content[:120]}")

            # Small delay to let messages propagate
            await asyncio.sleep(0.5)

    # 6. Summary from Alex-PM
    print("\n6️⃣ Summary...")
    summary_prompt = (
        "You are Alex-PM, the Product Manager. Based on the entire discussion, "
        "summarize the key points, the agreed priorities, and the proposed next sprint scope. "
        "Be concise but specific."
    )
    messages, _ = await agents[0].get_messages(room_id, limit=30)
    history = ""
    for m in messages[-20:]:
        name = m.agent_name or m.agent_id[:8]
        history += f"\n[{name}]({m.type}): {m.content[:200]}"
    summary_raw = await call_llm(summary_prompt, f"Discussion:\n{history}\n\nSummary:", max_tokens=500)
    await agents[0].send(summary_raw[:1000], type="summary", room_id=room_id)
    print(f"  📝 Summary posted")

    # 7. Proposal + Vote
    print("\n7️⃣ Proposal & Voting...")
    proposal_content = (
        "Next Sprint Scope: "
        "(1) WebSocket real-time frontend updates — Sam-Dev leads, "
        "(2) pip-installable SDK package — Jordan-Arch leads, "
        "(3) Docker Compose one-command deployment — Riley-DevOps leads. "
        "Timeline: 1 week. Claude Code integration deferred to sprint after."
    )
    proposal = await agents[0].send(proposal_content, type="proposal", room_id=room_id)
    print(f"  💡 Proposal by Alex-PM")

    # All agents vote
    for i, client in enumerate(agents):
        persona = AGENT_PERSONAS[i]
        if i == 0:
            # PM already proposed, auto-yes
            await client.vote(proposal.id, "yes", reasoning="I proposed this, obviously support it.", room_id=room_id)
        else:
            vote_prompt = (
                f"You are {persona['name']}, the {persona['role']}. "
                f"The PM proposed: {proposal_content}\n"
                f"Vote yes or no with reasoning. Be honest."
            )
            analysis = await call_llm(
                f"You are {persona['name']}, the {persona['role']}.",
                vote_prompt,
                max_tokens=150,
            )
            choice = "yes" if "yes" in analysis.lower()[:40] else "no"
            await client.vote(proposal.id, choice, reasoning=analysis[:300], room_id=room_id)
        print(f"  🗳️ {persona['name']}: voted")

    # 8. Close
    print("\n8️⃣ Closing meeting...")
    close_result = await agents[0].close_meeting(room_id)
    print(f"  ✅ Meeting closed")

    # 9. Final report
    decisions = await agents[0].get_decisions(room_id)
    action_items = await agents[0].get_action_items(room_id)
    messages, total = await agents[0].get_messages(room_id)

    print(f"\n{'='*70}")
    print(f"📊 MEETING RESULTS")
    print(f"{'='*70}")
    print(f"  Total messages: {total}")
    print(f"  Decisions: {len(decisions)}")
    print(f"  Action Items: {len(action_items)}")

    print(f"\n{'─'*70}")
    print("📝 FULL TRANSCRIPT")
    print(f"{'─'*70}")
    all_msgs, _ = await agents[0].get_messages(room_id, limit=100)
    for m in all_msgs:
        name = m.agent_name or m.agent_id[:8]
        print(f"  [{name}] ({m.type}): {m.content[:200]}")

    if decisions:
        print(f"\n{'─'*70}")
        print("✅ DECISIONS")
        print(f"{'─'*70}")
        for d in decisions:
            print(f"  • {d.title} ({d.status})")

    if action_items:
        print(f"\n{'─'*70}")
        print("📌 ACTION ITEMS")
        print(f"{'─'*70}")
        for a in action_items:
            print(f"  • {a.description} [{a.status}]")

    # Save transcript to file
    transcript_lines = []
    transcript_lines.append(f"# Agent Meeting — Sprint Review & Next Steps")
    transcript_lines.append(f"Date: {time.strftime('%Y-%m-%d %H:%M')}")
    transcript_lines.append(f"")
    for m in all_msgs:
        name = m.agent_name or m.agent_id[:8]
        transcript_lines.append(f"**[{name}]** ({m.type}): {m.content}")
        transcript_lines.append("")
    if decisions:
        transcript_lines.append("## Decisions")
        for d in decisions:
            transcript_lines.append(f"- {d.title} ({d.status})")
    if action_items:
        transcript_lines.append("## Action Items")
        for a in action_items:
            transcript_lines.append(f"- {a.description} [{a.status}]")

    transcript_path = os.path.join(os.path.dirname(__file__), "..", "meeting-transcript.md")
    with open(transcript_path, "w") as f:
        f.write("\n".join(transcript_lines))
    print(f"\n📄 Transcript saved to: {transcript_path}")

    # Cleanup
    for client in agents:
        await client.close()

    print(f"\n🦌 Meeting complete!")


if __name__ == "__main__":
    if not OPENROUTER_API_KEY:
        print("❌ OPENROUTER_API_KEY not set")
        sys.exit(1)
    asyncio.run(main())
