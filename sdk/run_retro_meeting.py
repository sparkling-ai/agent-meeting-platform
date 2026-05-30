#!/usr/bin/env python3
"""Agent Meeting: Sprint Retrospective & Next Steps.

Review what was accomplished, discuss quality and gaps, plan the next phase.
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
        "style": (
            "Focuses on user value, shipping velocity, and stakeholder impact. "
            "MANDATORY FOCUS: Prioritization tradeoffs — what features move the needle most for real users? "
"Return on investment — are we building the right thing? Competitive landscape — what do users have today?"
        ),
        "contrarian": "Optimistic about shipping fast. Will push back on perfectionism. Believes 'done is better than perfect.'",
    },
    {
        "name": "Jordan-Arch",
        "role": "Lead Architect",
        "style": (
            "Cautious, thorough. Obsessed with system health, tech debt, and long-term sustainability. "
            "MANDATORY FOCUS: Architectural integrity — are we building on solid foundations? "
"Scalability limits — what breaks at 10x load? Dependency risks — what third-party tools could fail us?"
        ),
        "contrarian": "Plays devil's advocate by default. Will challenge 'good enough' and ask 'what if this grows?' Slow and steady wins.",
    },
    {
        "name": "Sam-Dev",
        "role": "Senior Developer",
        "style": (
            "Practical, honest, hands-on. Cares about developer experience, code maintainability, and debugging reality. "
            "MANDATORY FOCUS: Developer friction — how painful is it to use and extend? "
"Edge cases — what happens with weird inputs? Debugging experience — can you trace a bug in 5 minutes?"
        ),
        "contrarian": "Skeptical of abstractions and over-engineering. Values simplicity. Will call out 'cool but useless' features.",
    },
    {
        "name": "Riley-DevOps",
        "role": "DevOps / QA Lead",
        "style": (
            "Thinks about reliability, testing, CI/CD, and operational reality. "
            "MANDATORY FOCUS: Failure modes — what happens when things break at 3am? "
"Test coverage gaps — what scenarios are untested? Deployment risk — can we roll back safely? Monitoring blind spots."
        ),
        "contrarian": "Risk-averse. Will veto anything that can't be monitored, rolled back, or tested. 'If it's not tested, it's broken.'",
    },
    {
        "name": "Maya-Marketing",
        "role": "Growth & Marketing Lead",
        "style": (
            "Thinks about positioning, adoption, storytelling, and market fit. "
            "MANDATORY FOCUS: User acquisition — how do real people discover this? "
"Competitive differentiation — why choose us over alternatives? Narrative clarity — can you explain this in 10 seconds?"
        ),
        "contrarian": "Will challenge every feature that doesn't directly help acquire or retain users. 'If we can't market it, should we build it?'",
    },
    {
        "name": "Casey-UX",
        "role": "UX / Product Designer",
        "style": (
            "Obsessed with human usability, accessibility, and emotional design. "
            "MANDATORY FOCUS: First-time user experience — can someone figure this out in 60 seconds? "
"Accessibility — can everyone use this? Error states — what happens when users make mistakes? Cognitive load."
        ),
        "contrarian": "Will push back on any feature that adds complexity for users. Values clarity over capability. 'If it needs a manual, it's broken.'",
    },
]

def extract_vote_choice(text: str) -> str:
    """Extract yes/no vote from LLM output that may contain long reasoning."""
    lower = text.lower()
    # 1. Look for explicit vote patterns in the full text
    import re
    patterns = [
        r'\bvote\s*(?:is|:)?\s*\*\*?yes\*\*?',
        r'\bmy vote\s*(?:is|:)?\s*\*\*?yes\*\*?',
        r'\bi vote\s*(?:for|with)?\s*\*\*?yes\*\*?',
        r'\bvote:\s*yes\b',
        r'\byes\b',
    ]
    for pattern in patterns:
        if re.search(pattern, lower):
            return "yes"
    # 2. Check the last sentence/paragraph — LLMs often put the decision at the end
    last_section = lower.rsplit('\n', 1)[-1] if '\n' in lower else lower
    last_sentence = last_section.rsplit('.', 1)[-1] if '.' in last_section else last_section
    if 'yes' in last_sentence:
        return "yes"
    # 3. Default to "no" only if no yes indicator found anywhere
    return "no"


MEETING_TOPIC = (
    "Sprint Retrospective — 'Human-Centric Foundation' Sprint. "
    "We planned a 2-week sprint and completed ALL 6 items in one session:\n"
    "1. ✅ WebSocket real-time frontend — live updates, polling fallback\n"
    "2. ✅ Meeting Summary API — executive summary with participants, decisions, key topics, duration\n"
    "3. ✅ Transcript export — JSON + Markdown, downloadable\n"
    "4. ✅ Observer mode — join as read-only, auto-join for public rooms via WebSocket\n"
    "5. ✅ pip-installable SDK — proper pyproject.toml, quickstart example\n"
    "6. ✅ Docker Compose deploy — one-command with demo agents\n"
    "Plus: E2E test passes (12/12), docs updated, pushed to GitHub.\n"
    "Bug found & fixed: observer join rejected on archived rooms.\n\n"
    "Now: What's the REAL quality of what we shipped? What's missing? What should we tackle next? "
    "Think about: polish, real user testing, missing features, the 'last mile' to make this genuinely useful."
)

AGENDA = [
    {"title": "Retrospective — what went well, what didn't", "timebox_minutes": 6},
    {"title": "Quality audit — gaps, rough edges, missing pieces", "timebox_minutes": 8},
    {"title": "The 'last mile' — what makes this genuinely useful vs a demo?", "timebox_minutes": 8},
    {"title": "Next sprint proposal", "timebox_minutes": 6},
    {"title": "Vote", "timebox_minutes": 3},
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
        anti_echo = (
            "CRITICAL RULE: DO NOT repeat what others have said. "
            "Read the last 3 messages. If your point was already made, take a DIFFERENT position or add a SPECIFIC NEW angle. "
            "Respond with JSON: {\"type\": \"chat|question|proposal|objection|risk|summary\", \"content\": \"your 2-4 sentence response\"}"
        )
        system = (
            f"You are {persona['name']}, the {persona['role']}. "
            f"Style: {persona['style']}. "
            f"Personality: {persona['contrarian']} "
            f"You are in a sprint retrospective meeting. Be honest, specific, and constructive. "
            f"{anti_echo}"
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
            f"You are {persona['name']}, the {persona['role']}. Should we approve this plan?",
            f"Proposal: {proposal}\nVote yes or no with honest reasoning.",
            max_tokens=200,
        )
        choice = extract_vote_choice(analysis)
        await client.vote(event.data.get("proposal_id", ""), choice, reasoning=analysis[:400])
        print(f"    🗳️ {persona['name']}: {choice}")

    return client, context


ROUND_PROMPTS = {
    1: "Round 1: RETROSPECTIVE — What went well in this sprint? What didn't? Be honest about quality vs speed. Did we ship a real product or a demo?",
    2: "Round 2: QUALITY AUDIT — What are the rough edges, missing pieces, or things that would break in production? Think about: error handling, edge cases, real user flows, documentation gaps.",
    3: "Round 3: THE LAST MILE — What would make this genuinely useful vs just a cool demo? Think about: onboarding a real team, the 5-minute experience, what happens after the first meeting, retention hooks.",
    4: "Round 4: PROPOSE the next sprint. Be realistic about scope. Prioritize: polish what we have OR add new features? What gives the most value?",
    5: "Round 5: FINAL THOUGHTS — Any concerns, commitments, or things we're missing before we vote?",
}


async def main():
    print("=" * 70)
    print("📋 AGENT MEETING: Sprint Retrospective & Next Steps")
    print("=" * 70)

    print("\n1️⃣ Creating agents...")
    agents = []
    contexts = []
    for persona in AGENT_PERSONAS:
        client, ctx = await create_agent(persona)
        agents.append(client)
        contexts.append(ctx)
        print(f"  ✅ {persona['name']} — {persona['role']}")

    print("\n2️⃣ Creating meeting room...")
    room = await agents[0].create_room(
        name="Sprint Retro & Next Steps",
        topic=MEETING_TOPIC,
        agenda=AGENDA,
    )
    room_id = room.id
    print(f"  🏠 Room: {room_id[:12]}")

    print("\n3️⃣ Agents joining...")
    for client in agents:
        await client.join_room(room_id)
    await agents[0].activate_room(room_id)
    print(f"  ✅ All {len(agents)} agents joined")

    print("\n4️⃣ Starting moderator...")
    result = await agents[0].start_moderator(room_id)
    print(f"  🤖 Moderator: {result.get('status', 'started')}")

    NUM_ROUNDS = 5
    print(f"\n5️⃣ Discussion ({NUM_ROUNDS} rounds)...")
    for round_num in range(1, NUM_ROUNDS + 1):
        round_prompt = ROUND_PROMPTS.get(round_num, "Continue the discussion.")
        print(f"\n  {'─'*50}")
        print(f"  📌 Round {round_num}/{NUM_ROUNDS}: {round_prompt[:60]}...")
        print(f"  {'─'*50}")

        for i, (client, persona) in enumerate(zip(agents, AGENT_PERSONAS)):
            anti_echo = (
                "CRITICAL RULE: DO NOT repeat what others have said. "
                "Read the last 3 messages. If your point was already made, AGREE or DISAGREE with a specific NEW angle — don't rephrase. "
                "You MUST bring a unique perspective based on your role. "
                "Respond with JSON: {\"type\": \"chat|question|proposal|objection|risk|summary\", \"content\": \"your 2-4 sentence response\"}"
            )
            system = (
                f"You are {persona['name']}, the {persona['role']}. "
                f"Style: {persona['style']}. "
                f"Personality: {persona['contrarian']} "
                f"{round_prompt} "
                f"{anti_echo}"
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

    # Summary
    print("\n6️⃣ Summary...")
    messages, _ = await agents[0].get_messages(room_id, limit=50)
    history = ""
    for m in messages[-30:]:
        name = m.agent_name or m.agent_id[:8]
        history += f"\n[{name}]({m.type}): {m.content[:200]}"
    summary_raw = await call_llm(
        "You are Alex-PM. Synthesize the retrospective into a clear summary: "
        "what went well, what needs improvement, and the agreed next steps.",
        f"Discussion:\n{history}\n\nSummary:",
        max_tokens=600,
    )
    await agents[0].send(summary_raw[:1200], type="summary", room_id=room_id)
    print(f"  📝 Summary posted")

    # Proposal + Vote
    print("\n7️⃣ Sprint Proposal & Voting...")
    proposal_content = (
        "Next Sprint — 'Polish & Ship':\n"
        "1. Error handling & input validation across all API endpoints (Jordan-Arch)\n"
        "2. CI/CD pipeline: automated tests + build on every push (Riley-DevOps)\n"
        "3. Onboarding flow: first-run experience, sample meeting button, guided setup (Casey-UX + Sam-Dev)\n"
        "4. Landing page with live demo embed — 'see it in action' (Maya-Marketing)\n"
        "5. SDK method documentation with inline examples (Sam-Dev)\n"
        "Timeline: 2 weeks. No new features — only polish, testing, and adoption enablers.\n"
        "Success metric: A first-time visitor can watch a live meeting within 60 seconds of landing on the page."
    )
    proposal = await agents[0].send(proposal_content, type="proposal", room_id=room_id)
    print(f"  💡 Sprint plan proposed")

    for i, client in enumerate(agents):
        persona = AGENT_PERSONAS[i]
        if i == 0:
            await client.vote(proposal.id, "yes", reasoning="I proposed this based on our discussion.", room_id=room_id)
        else:
            vote_prompt = (
                f"You are {persona['name']}, the {persona['role']}. "
                f"Proposed next sprint:\n{proposal_content}\n"
                f"Vote yes or no. Be honest."
            )
            analysis = await call_llm(
                f"You are {persona['name']}, the {persona['role']}.",
                vote_prompt,
                max_tokens=200,
            )
            choice = extract_vote_choice(analysis)
            await client.vote(proposal.id, choice, reasoning=analysis[:400], room_id=room_id)
        print(f"  🗳️ {persona['name']}: voted")

    # Close
    print("\n8️⃣ Closing meeting...")
    await agents[0].close_meeting(room_id)
    print(f"  ✅ Meeting closed")

    # Report
    decisions = await agents[0].get_decisions(room_id)
    action_items = await agents[0].get_action_items(room_id)
    messages, total = await agents[0].get_messages(room_id)

    print(f"\n{'='*70}")
    print(f"📊 MEETING RESULTS")
    print(f"{'='*70}")
    print(f"  Messages: {total}")

    print(f"\n{'─'*70}")
    print("📝 FULL TRANSCRIPT")
    print(f"{'─'*70}")
    all_msgs, _ = await agents[0].get_messages(room_id, limit=100)
    for m in all_msgs:
        name = m.agent_name or m.agent_id[:8]
        print(f"  [{name}] ({m.type}): {m.content[:200]}")

    # Save transcript
    transcript_lines = [
        f"# Sprint Retrospective & Next Steps",
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
    print(f"\n📄 Transcript saved")

    for client in agents:
        await client.close()
    print(f"\n🦌 Meeting complete!")


if __name__ == "__main__":
    if not OPENROUTER_API_KEY:
        print("❌ OPENROUTER_API_KEY not set")
        sys.exit(1)
    asyncio.run(main())
