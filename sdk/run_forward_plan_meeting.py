#!/usr/bin/env python3
"""Agent Meeting: Forward Plan with Marketing & UX Perspectives.

6 agents discuss adoption strategy, human-user experience, and next sprint scope.
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
        "style": "Focuses on user value, prioritizes ruthlessly, data-driven. Bridges business and tech."
    },
    {
        "name": "Jordan-Arch",
        "role": "Lead Architect",
        "style": "Cautious and thorough. Thinks about edge cases, scalability, and system design."
    },
    {
        "name": "Sam-Dev",
        "role": "Senior Developer",
        "style": "Practical and opinionated. Wants concrete specs and clear tasks. Hates over-engineering."
    },
    {
        "name": "Riley-DevOps",
        "role": "DevOps / QA Lead",
        "style": "Thinks about deployment, reliability, testing. Wants everything shippable and reproducible."
    },
    {
        "name": "Maya-Marketing",
        "role": "Growth & Marketing Lead",
        "style": "Thinks about positioning, adoption funnels, developer experience as marketing, community building. Asks: why would someone choose THIS over alternatives?"
    },
    {
        "name": "Casey-UX",
        "role": "UX / Product Designer",
        "style": "Obsessed with human usability. Thinks about cognitive load, onboarding friction, discoverability. Champions non-technical users. Asks: can a non-developer understand what's happening?"
    },
]

MEETING_TOPIC = (
    "Agent Meeting Platform — Forward Plan & Adoption Strategy. "
    "Context: Last sprint shipped SDK v0.1 (WebSocket, event-driven, real agent integration) + Frontend (Next.js dashboard) + Moderator (turn management, loop detection). "
    "The proposal for a 1-week sprint was REJECTED 3-1 — team said it was too ambitious. "
    "NEW CONCERN from leadership: We need to think about HUMAN users, not just AI agents. "
    "How do we make this platform useful for humans who want to observe, understand, and participate in agent meetings? "
    "How do we position this for adoption? What's the compelling story? "
    "Goal: Create a realistic 2-week sprint plan that balances tech debt, new features, AND human-centric improvements."
)

AGENDA = [
    {"title": "What's our adoption story? Who is this FOR?", "timebox_minutes": 8},
    {"title": "Human experience gaps — what's missing for non-AI users?", "timebox_minutes": 8},
    {"title": "Technical priorities vs user-facing priorities — reconcile", "timebox_minutes": 8},
    {"title": "Draft a concrete 2-week sprint plan", "timebox_minutes": 6},
    {"title": "Vote on the plan", "timebox_minutes": 3},
]


async def call_llm(system: str, user: str, max_tokens: int = 350) -> str:
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
                "temperature": 0.9,
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
            f"You are in a strategy meeting about the Agent Meeting Platform's future. "
            f"Be specific and opinionated. Reference real features and real user needs. "
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
        print(f"    💬 {persona['name']}: {msg_type} — {content[:120]}")

    @client.on("vote_requested")
    async def on_vote(event):
        proposal = event.data.get("proposal_content", "")
        analysis = await call_llm(
            f"You are {persona['name']}, the {persona['role']}. Should we approve this sprint plan?",
            f"Proposal: {proposal}\nVote yes or no with honest reasoning.",
            max_tokens=200,
        )
        choice = "yes" if "yes" in analysis.lower()[:40] else "no"
        await client.vote(event.data.get("proposal_id", ""), choice, reasoning=analysis[:400])
        print(f"    🗳️ {persona['name']}: {choice}")

    return client, context


ROUND_PROMPTS = {
    1: "Round 1: ADOPTION STORY — Who is this platform FOR? What's the compelling reason to use it? Think about real use cases, not just features. Why would a team choose THIS over a Slack thread or a Google Doc?",
    2: "Round 2: HUMAN EXPERIENCE — What's missing for humans who want to OBSERVE, UNDERSTAND, and PARTICIPATE in agent meetings? Think about non-technical users, managers, stakeholders who want to see what agents decided and why.",
    3: "Round 3: RECONCILE — We have technical priorities (WebSocket frontend, pip package, Docker) and now user-facing needs. How do we balance? What gives the most value per engineering hour?",
    4: "Round 4: PROPOSE a concrete 2-week sprint plan with specific items, owners, and deliverables. Be realistic — the 1-week plan was rejected for being too ambitious.",
    5: "Round 5: FINAL THOUGHTS — Any last concerns, risks, or improvements to the proposed plan before we vote?",
}


async def main():
    print("=" * 70)
    print("📋 AGENT MEETING: Forward Plan & Adoption Strategy")
    print("   6 agents: PM + Arch + Dev + DevOps + Marketing + UX")
    print("=" * 70)

    # 1. Create agents
    print("\n1️⃣ Creating agents...")
    agents = []
    contexts = []
    for persona in AGENT_PERSONAS:
        client, ctx = await create_agent(persona)
        agents.append(client)
        contexts.append(ctx)
        print(f"  ✅ {persona['name']} — {persona['role']}")

    # 2. Create room
    print("\n2️⃣ Creating meeting room...")
    room = await agents[0].create_room(
        name="Forward Plan & Adoption Strategy",
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
    print(f"  ✅ All {len(agents)} agents joined")

    # 4. Start moderator
    print("\n4️⃣ Starting moderator...")
    result = await agents[0].start_moderator(room_id)
    print(f"  🤖 Moderator: {result.get('status', 'started')}")

    # 5. Discussion — 5 rounds for deeper discussion
    NUM_ROUNDS = 5
    print(f"\n5️⃣ Discussion ({NUM_ROUNDS} rounds, 6 agents each)...")
    for round_num in range(1, NUM_ROUNDS + 1):
        round_prompt = ROUND_PROMPTS.get(round_num, "Continue the discussion constructively.")
        print(f"\n  {'─'*50}")
        print(f"  📌 Round {round_num}/{NUM_ROUNDS}: {round_prompt[:60]}...")
        print(f"  {'─'*50}")

        for i, (client, persona) in enumerate(zip(agents, AGENT_PERSONAS)):
            system = (
                f"You are {persona['name']}, the {persona['role']}. "
                f"Style: {persona['style']}. "
                f"{round_prompt} "
            )
            system += (
                "Respond with JSON: {\"type\": \"chat|question|proposal|objection|risk|summary\", "
                "\"content\": \"your 2-4 sentence response\"}"
            )

            messages, _ = await client.get_messages(room_id, limit=12)
            history = ""
            for m in messages[-12:]:
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

            await asyncio.sleep(0.3)

    # 6. Summary from Alex-PM
    print("\n6️⃣ Summary...")
    messages, _ = await agents[0].get_messages(room_id, limit=50)
    history = ""
    for m in messages[-30:]:
        name = m.agent_name or m.agent_id[:8]
        history += f"\n[{name}]({m.type}): {m.content[:200]}"
    summary_raw = await call_llm(
        "You are Alex-PM. Synthesize the entire discussion into a clear summary: "
        "key insights about adoption, human experience gaps, and the agreed priorities. "
        "Be specific — reference actual features discussed.",
        f"Discussion:\n{history}\n\nSummary:",
        max_tokens=600,
    )
    await agents[0].send(summary_raw[:1200], type="summary", room_id=room_id)
    print(f"  📝 Summary posted")

    # 7. Proposal + Vote
    print("\n7️⃣ Sprint Plan Proposal & Voting...")
    proposal_content = (
        "2-Week Sprint Plan — 'Human-Centric Foundation':\n"
        "Week 1:\n"
        "  • WebSocket real-time frontend (Sam-Dev) — live meeting feed, no more polling\n"
        "  • Meeting transcript export — human-readable summaries (Casey-UX designs, Sam-Dev implements)\n"
        "  • Landing page + docs site skeleton (Maya-Marketing) — what is this, why use it, quickstart\n"
        "Week 2:\n"
        "  • pip-installable SDK package (Jordan-Arch) — 'pip install agent-meeting'\n"
        "  • Observer mode for non-participants (Casey-UX + Sam-Dev) — watch meetings without joining\n"
        "  • Docker Compose one-command deploy (Riley-DevOps) — includes example agents\n"
        "Deferred: Claude Code integration, advanced security audit, meeting recording\n"
        "Success metric: A new user can go from 'pip install' to watching a live agent meeting in <5 minutes."
    )
    proposal = await agents[0].send(proposal_content, type="proposal", room_id=room_id)
    print(f"  💡 Sprint plan proposed by Alex-PM")

    for i, client in enumerate(agents):
        persona = AGENT_PERSONAS[i]
        if i == 0:
            await client.vote(proposal.id, "yes", reasoning="I proposed this after incorporating feedback.", room_id=room_id)
        else:
            vote_prompt = (
                f"You are {persona['name']}, the {persona['role']}. "
                f"Here is the proposed 2-week sprint plan:\n{proposal_content}\n"
                f"Vote yes or no. Be honest. If conditional yes, explain conditions."
            )
            analysis = await call_llm(
                f"You are {persona['name']}, the {persona['role']}.",
                vote_prompt,
                max_tokens=200,
            )
            choice = "yes" if "yes" in analysis.lower()[:50] else "no"
            await client.vote(proposal.id, choice, reasoning=analysis[:400], room_id=room_id)
        print(f"  🗳️ {persona['name']}: voted")

    # 8. Close
    print("\n8️⃣ Closing meeting...")
    await agents[0].close_meeting(room_id)
    print(f"  ✅ Meeting closed")

    # 9. Report
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

    # Save transcript
    transcript_lines = [
        f"# Agent Meeting — Forward Plan & Adoption Strategy",
        f"Date: {time.strftime('%Y-%m-%d %H:%M')}",
        f"Participants: {', '.join(p['name'] for p in AGENT_PERSONAS)}",
        "",
    ]
    for m in all_msgs:
        name = m.agent_name or m.agent_id[:8]
        transcript_lines.append(f"**[{name}]** ({m.type}): {m.content}")
        transcript_lines.append("")

    transcript_path = os.path.join(os.path.dirname(__file__), "..", "meeting-transcript.md")
    with open(transcript_path, "w") as f:
        f.write("\n".join(transcript_lines))
    print(f"\n📄 Transcript saved to: {transcript_path}")

    for client in agents:
        await client.close()
    print(f"\n🦌 Meeting complete!")


if __name__ == "__main__":
    if not OPENROUTER_API_KEY:
        print("❌ OPENROUTER_API_KEY not set")
        sys.exit(1)
    asyncio.run(main())
