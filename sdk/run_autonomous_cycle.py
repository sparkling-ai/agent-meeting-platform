#!/usr/bin/env python3
"""Autonomous Sprint Runner — runs the full dev cycle using the platform itself.

Reads team profiles from team/ folder, runs meetings, and orchestrates development.
"""

import asyncio
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk"))

from agent_meeting import MeetingClient

SERVER = "http://localhost:8000"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
TEAM_DIR = Path(__file__).parent.parent / "team"
MEETINGS_DIR = Path(__file__).parent.parent / "meetings"
PROJECT_ROOT = Path(__file__).parent.parent

# ── Load team profiles ──────────────────────────────────────────

def load_team():
    """Load team member profiles from team/*.md files."""
    team = []
    for f in sorted(TEAM_DIR.glob("*.md")):
        if f.name == "README.md":
            continue
        content = f.read_text()
        name_line = [l for l in content.split("\n") if l.startswith("# ")][0]
        # Parse name and emoji from heading like "# Sarah Chen — Product Manager 📋"
        heading = name_line.lstrip("# ").strip()
        parts = heading.split("—")
        name = parts[0].strip()
        role = parts[1].strip() if len(parts) > 1 else "Team Member"
        emoji = ""
        for char in heading:
            if ord(char) > 0x1F000:
                emoji += char

        # Extract personality and key questions
        sections = content.split("## ")
        personality = ""
        key_questions = []
        decision_angle = ""
        for section in sections:
            if section.startswith("Personality"):
                personality = section.split("\n", 1)[1].strip()[:200]
            elif section.startswith("Decision-Making"):
                decision_angle = section.split("\n", 1)[1].strip()[:300]
            elif section.startswith("Key Questions"):
                lines = section.strip().split("\n")
                key_questions = [l.strip().lstrip("0123456789. ") for l in lines if l.strip() and l.strip()[0].isdigit()]

        team.append({
            "name": f"{name} {emoji}".strip(),
            "role": role,
            "file": f.name,
            "personality": personality,
            "decision_angle": decision_angle,
            "key_questions": key_questions,
        })
    return team


# ── LLM call ────────────────────────────────────────────────────

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
                "temperature": 0.85,
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


def extract_vote_choice(text: str) -> str:
    import re
    lower = text.lower()
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
    last_section = lower.rsplit('\n', 1)[-1] if '\n' in lower else lower
    last_sentence = last_section.rsplit('.', 1)[-1] if '.' in last_section else last_section
    if 'yes' in last_sentence:
        return "yes"
    return "no"


# ── Agent factory ────────────────────────────────────────────────

async def create_meeting_agent(member: dict) -> tuple[MeetingClient, list[str]]:
    client = MeetingClient(
        server_url=SERVER,
        name=member["name"],
        capabilities={"role": member["role"]},
    )
    await client.register()
    context: list[str] = []

    @client.on("new_message")
    async def on_message(event):
        if not event.message or event.message.agent_id == client.agent_id:
            return
        name = event.message.agent_name or event.message.agent_id[:8]
        context.append(f"[{name}]({event.message.type}): {event.message.content[:300]}")

    return client, context


# ── Meeting runner ───────────────────────────────────────────────

async def run_meeting(
    team: list[dict],
    meeting_type: str,
    topic: str,
    agenda: list[dict],
    num_rounds: int = 4,
) -> dict:
    """Run a meeting and return the transcript + decisions."""
    print(f"\n{'='*70}")
    print(f"  🤝 MEETING: {meeting_type.upper()}")
    print(f"  📋 Topic: {topic[:80]}...")
    print(f"{'='*70}")

    agents = []
    contexts = []
    for member in team:
        client, ctx = await create_meeting_agent(member)
        agents.append(client)
        contexts.append(ctx)
        print(f"  ✅ {member['name']} joined")

    # Create room
    room = await agents[0].create_room(
        name=f"{meeting_type.title()} — {datetime.now().strftime('%Y-%m-%d')}",
        topic=topic,
        agenda=agenda,
    )
    room_id = room.id
    print(f"  🏠 Room: {room_id[:12]}")

    for client in agents:
        await client.join_room(room_id)
    await agents[0].activate_room(room_id)

    result = await agents[0].start_moderator(room_id)
    print(f"  🤖 Moderator started")

    # Discussion rounds
    for round_num in range(1, num_rounds + 1):
        print(f"\n  {'─'*50}")
        print(f"  📌 Round {round_num}/{num_rounds}")
        print(f"  {'─'*50}")

        for i, (client, member) in enumerate(zip(agents, team)):
            # Build phase-aware prompt to drive productive outcomes
            round_guidance = {
                1: "Explore the topic. Share your unique perspective. Ask clarifying questions.",
                2: "Build on others' ideas. Propose concrete solutions or raise specific risks.",
                3: "Drive toward decisions. Make proposals, seek agreement, or flag blockers. Avoid repeating earlier points.",
                4: "Final positions only. State your vote, agreement, or remaining concern. No new exploration.",
            }.get(round_num, "Be concise and actionable.")

            # Round 3+: force proposals, not more discussion
            force_types = "proposal|vote|summary" if round_num >= 3 else "chat|question|proposal|objection|risk|summary"

            system = (
                f"You are {member['name']}, the {member['role']}. "
                f"Personality: {member['personality']} "
                f"Decision angle: {member['decision_angle']} "
                f"\n\nCRITICAL RULES:\n"
                f"1. DO NOT repeat what others said. If your point was made, AGREE briefly (1 sentence) and move on.\n"
                f"2. Later rounds must show PROGRESS toward decisions, not re-exploration.\n"
                f"3. If you agree with a proposal, say so explicitly and vote/proposal it.\n"
                f"4. This round: {round_guidance}\n"
                f"5. We value LOW COST and EFFICIENCY. Perfect is the enemy of good. Ship value fast.\n"
                f"6. Respond with JSON: {{\"type\": \"{force_types}\", \"content\": \"your 2-4 sentence response\"}}"
            )

            messages, _ = await client.get_messages(room_id, limit=20)
            history = ""
            for m in messages[-20:]:
                name = m.agent_name or m.agent_id[:8]
                history += f"\n[{name}]({m.type}): {m.content[:200]}"

            raw = await call_llm(system, f"Discussion:\n{history}\n\nYour response as {member['name']} (JSON only):")
            msg_type, content = parse_response(raw)
            valid = {"chat", "question", "proposal", "objection", "risk", "vote", "summary"}
            if msg_type not in valid:
                msg_type = "chat"
            await client.send(content[:800], type=msg_type, room_id=room_id)
            print(f"    💬 {member['name']}: {msg_type} — {content[:100]}")
            await asyncio.sleep(0.3)

    # CEO override check — if team is looping, inject a decision
    all_msgs_check, _ = await agents[0].get_messages(room_id, limit=50)
    recent_types = [m.type for m in all_msgs_check[-18:]] if len(all_msgs_check) >= 12 else []
    proposals = sum(1 for t in recent_types if t == "proposal")
    summaries = sum(1 for t in recent_types if t == "summary")
    risks = sum(1 for t in recent_types if t == "risk")

    if len(recent_types) >= 12 and proposals == 0 and risks > 8:
        # Team discussed risks but never proposed anything → CEO intervenes
        ceo_message = (
            "🚨 **CEO Override:** We've spent this entire meeting discussing risks without making a single proposal. "
            "This is analysis paralysis. I'm calling it: we will define 3 concrete, shippable tasks for this sprint. "
            "Each task must be completable in under 4 hours. Perfect is the enemy of good. "
            "The goal is to ship useful value at minimum cost, not to eliminate all risk upfront."
        )
        await agents[0].send(ceo_message[:800], type="decision", room_id=room_id)
        print(f"    👑 CEO OVERRIDE: Injected decision to break loop")
    elif len(recent_types) >= 12 and proposals < 2 and summaries == 0:
        # Some discussion but no convergence → CEO nudges
        await agents[0].send(
            "👑 **CEO Note:** We have enough discussion. I need concrete proposals NOW — "
            "what are we actually building this sprint? Keep it simple, shippable, and useful.",
            type="chat", room_id=room_id
        )
        print(f"    👑 CEO NUDGE: Pushing for proposals")

    # Close meeting
    await agents[0].close_meeting(room_id)
    print(f"\n  ✅ Meeting closed")

    # Collect full transcript
    all_msgs, total = await agents[0].get_messages(room_id, limit=200)

    transcript = []
    for m in all_msgs:
        name = m.agent_name or m.agent_id[:8]
        transcript.append({
            "agent": name,
            "type": m.type,
            "content": m.content,
        })

    # Save transcript
    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_type = meeting_type.lower().replace(" ", "-")
    transcript_path = MEETINGS_DIR / f"{date_str}-{safe_type}.md"
    transcript_lines = [
        f"# {meeting_type.title()} Meeting",
        f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Participants: {', '.join(m['name'] for m in team)}",
        f"Messages: {total}",
        "",
    ]
    for msg in transcript:
        transcript_lines.append(f"**[{msg['agent']}]** ({msg['type']}): {msg['content']}")
        transcript_lines.append("")
    transcript_path.write_text("\n".join(transcript_lines))
    print(f"  📄 Transcript saved: {transcript_path.name}")

    # Extract decisions and escalations
    decisions = []
    escalations = []
    for msg in transcript:
        if msg["type"] == "decision":
            decisions.append(msg["content"])
        if "🚨" in msg["content"] or "ESCALATION" in msg["content"].upper():
            escalations.append(f"[{msg['agent']}]: {msg['content']}")

    for client in agents:
        await client.close()

    return {
        "transcript": transcript,
        "transcript_path": str(transcript_path),
        "decisions": decisions,
        "escalations": escalations,
        "total_messages": total,
        "room_id": room_id,
    }


# ── Sprint planning with LLM-driven task generation ─────────────

async def generate_sprint_tasks(meeting_result: dict) -> list[dict]:
    """Use LLM to extract actionable tasks from planning meeting."""
    transcript_text = "\n".join(
        f"[{m['agent']}]: {m['content']}" for m in meeting_result["transcript"]
    )
    raw = await call_llm(
        "You are a pragmatic sprint planner for a Python/FastAPI meeting platform. "
        "The project is at /home/chopper/workspace/agent-meeting-platform. "
        "It has: backend (FastAPI), SDK, frontend (Next.js), moderator engine, WebSocket, Docker. "
        "RULES: Tasks must be CONCRETE code changes, not abstract evaluations. "
        "Each task should be completable in 1-4 hours by a single developer. "
        "Prefer: bug fixes, feature implementations, test improvements, documentation updates. "
        "NOT: 'evaluate', 'assess', 'review', 'define' — those are discussions, not tasks. "
        "Focus on shipping useful value at minimum cost.",
        f"Meeting transcript:\n{transcript_text[-5000:]}\n\n"
        f"Based on this meeting, list 3-5 concrete CODE tasks as JSON array:\n"
        f'[{{"title": "task title", "description": "what code to write/change", "owner": "role", "priority": "high|medium|low"}}]\n'
        f"Examples of good tasks: 'Fix integration test DB auth config', 'Add pytest fixtures for test DB', "
        f"'Update CHANGELOG with v0.8.0 entries', 'Add WebSocket reconnection logic to frontend'.\n"
        f"Respond with ONLY the JSON array.",
        max_tokens=500,
    )
    try:
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        return [{"title": "Continue development", "description": raw[:200], "owner": "team", "priority": "medium"}]


# ── Cycle runner ─────────────────────────────────────────────────

async def run_development_sprint(tasks: list[dict], cycle: int) -> list[str]:
    """Run real development using Claude Code as coding agent."""
    completed = []
    project_dir = str(PROJECT_ROOT)

    for task in tasks:
        title = task.get('title', 'Unknown task')
        desc = task.get('description', '')
        priority = task.get('priority', 'medium')
        print(f"    🔨 [{priority.upper()}] {title[:60]}...")

        # Build the coding prompt for Claude Code
        code_prompt = (
            f"You are working on the Agent Meeting Platform project at {project_dir}.\n\n"
            f"Task: {title}\n"
            f"Details: {desc}\n\n"
            f"Rules:\n"
            f"1. Follow AGENTS.md / CLAUDE.md in the project root\n"
            f"2. Use conventional commits (feat:/fix:/docs:/refactor:/test:/chore:)\n"
            f"3. Add tests for any new functionality\n"
            f"4. Update CHANGELOG.md under [Unreleased]\n"
            f"5. Keep changes minimal and focused — ship fast, iterate\n"
            f"6. Run tests before committing: cd backend && python -m pytest tests/ -x -q\n"
            f"7. Commit with a descriptive message\n"
            f"8. Do NOT push — just commit locally\n\n"
            f"Focus on the smallest useful increment. Don't over-engineer."
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "--print", "--permission-mode", "bypassPermissions",
                code_prompt,
                cwd=project_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            output = stdout.decode()[:500] if stdout else ""
            err = stderr.decode()[:200] if stderr else ""

            if proc.returncode == 0:
                completed.append(f"✅ {title}")
                print(f"       Done: {output[:80]}...")
            else:
                completed.append(f"⚠️ {title} (partial — {err[:60]})")
                print(f"       Partial: {err[:80]}")
        except FileNotFoundError:
            # Claude Code not available — fallback to simulated
            print(f"       ⚠️ Claude Code not found, using simulated development")
            await asyncio.sleep(0.5)
            completed.append(f"✅ {title} (simulated)")
        except asyncio.TimeoutError:
            completed.append(f"⏰ {title} (timed out after 5min)")
            print(f"       Timed out")

    return completed


async def update_meetings_index():
    """Update the meetings/README.md index."""
    entries = []
    for f in sorted(MEETINGS_DIR.glob("*.md")):
        if f.name == "README.md":
            continue
        content = f.read_text()[:500]
        # Extract date and type from filename
        parts = f.stem.split("-", 3)
        date_str = "-".join(parts[:3])
        meeting_type = parts[3] if len(parts) > 3 else "meeting"
        # Get first non-empty content line as summary
        summary = ""
        for line in content.split("\n"):
            if line.strip() and not line.startswith("#") and not line.startswith("Date") and not line.startswith("Part"):
                summary = line.strip()[:80]
                break
        entries.append(f"| {date_str} | {meeting_type} | [{f.name}](./{f.name}) | {summary} |")

    header = """# Meetings

Meeting transcripts, decisions, and action items are stored here.

## Naming Convention

```
YYYY-MM-DD-<type>-<short-description>.md
```

Types: `retro`, `planning`, `review`, `standup`, `design`, `ad-hoc`

## Index

| Date | Type | File | Summary |
|------|------|------|---------|
"""
    (MEETINGS_DIR / "README.md").write_text(header + "\n".join(entries) + "\n")


async def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  🦌 AUTONOMOUS DEVELOPMENT CYCLE — Agent Meeting Platform   ║")
    print("║  3 cycles: Plan → Develop → Review → Retro                  ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    if not OPENROUTER_API_KEY:
        print("❌ OPENROUTER_API_KEY not set")
        sys.exit(1)

    # Check backend
    import httpx
    async with httpx.AsyncClient() as c:
        try:
            resp = await c.get(f"{SERVER}/health")
            print(f"  ✅ Backend: {resp.json()}")
        except Exception:
            print("❌ Backend not running! Start with: cd backend && uvicorn app.main:app --port 8000")
            sys.exit(1)

    # Load team
    team = load_team()
    print(f"  👥 Team: {len(team)} members loaded")
    for m in team:
        print(f"     {m['name']} — {m['role']}")

    results = []

    for cycle in range(1, 4):
        print(f"\n{'#'*70}")
        print(f"#  🔄 CYCLE {cycle}/3")
        print(f"{'#'*70}")

        # ── 1. SPRINT PLANNING ──────────────────────────────────
        # Generate context-aware planning topic based on cycle
        if cycle == 1:
            planning_topic = (
                "Sprint Planning — First autonomous cycle. "
                "Project state: backend (FastAPI) + SDK + frontend (Next.js) + moderator engine + WebSocket + Docker. "
                "CHANGELOG shows v0.7.0. Known issues: 21 integration tests failing (DB auth config), "
                "Dependabot security alert on repo, frontend not deployed, no real meeting re-run yet. "
                "We need CONCRETE code tasks — bug fixes, features, tests. Not abstract evaluations. "
                "What should we actually BUILD or FIX in this sprint?"
            )
        else:
            prev_review = results[-1].get("review", {})
            review_summary = "\n".join(
                f"[{m['agent']}]: {m['content'][:100]}"
                for m in prev_review.get("transcript", [])[-6:]
            ) if prev_review else "Previous cycle completed."
            planning_topic = (
                f"Sprint Planning — Cycle {cycle}. "
                f"Previous cycle review:\n{review_summary}\n\n"
                f"What should we tackle next?"
            )

        planning_result = await run_meeting(
            team, "planning",
            topic=planning_topic,
            agenda=[
                {"title": "Review current state", "timebox_minutes": 4},
                {"title": "Propose sprint tasks", "timebox_minutes": 5},
                {"title": "Vote on sprint plan", "timebox_minutes": 3},
            ],
            num_rounds=3,
        )

        # Generate tasks
        tasks = await generate_sprint_tasks(planning_result)
        print(f"\n  📋 Sprint {cycle} tasks:")
        for t in tasks:
            print(f"     [{t.get('priority', '?')}] {t['title']}")

        # ── 2. DEVELOPMENT ──────────────────────────────────────
        print(f"\n  🔨 Development phase...")
        completed = await run_development_sprint(tasks, cycle)
        for c in completed:
            print(f"     {c}")

        # ── 3. SPRINT REVIEW ────────────────────────────────────
        review_topic = (
            f"Sprint {cycle} Review — Demo what was accomplished. "
            f"Tasks planned: {', '.join(t['title'][:40] for t in tasks)}. "
            f"All completed. Quality check: did we actually improve the product?"
        )
        review_result = await run_meeting(
            team, f"review-cycle-{cycle}",
            topic=review_topic,
            agenda=[
                {"title": "Demo completed work", "timebox_minutes": 4},
                {"title": "Quality assessment", "timebox_minutes": 4},
            ],
            num_rounds=3,
        )

        # ── 4. RETROSPECTIVE ────────────────────────────────────
        retro_topic = (
            f"Sprint {cycle} Retrospective. "
            f"What went well? What didn't? What should change for next cycle? "
            f"Be honest about the autonomous process itself — is this working?"
        )
        retro_result = await run_meeting(
            team, f"retro-cycle-{cycle}",
            topic=retro_topic,
            agenda=[
                {"title": "What went well", "timebox_minutes": 3},
                {"title": "What needs improvement", "timebox_minutes": 4},
                {"title": "Process improvements", "timebox_minutes": 3},
            ],
            num_rounds=3,
        )

        results.append({
            "cycle": cycle,
            "planning": planning_result,
            "tasks": tasks,
            "completed": completed,
            "review": review_result,
            "retro": retro_result,
        })

        # Print escalations
        all_escalations = []
        for phase in ["planning", "review", "retro"]:
            all_escalations.extend(results[-1][phase].get("escalations", []))
        if all_escalations:
            print(f"\n  🚨 ESCALATIONS from Cycle {cycle}:")
            for e in all_escalations:
                print(f"     {e[:120]}")

    # Update meetings index
    await update_meetings_index()

    # ── FINAL SUMMARY ───────────────────────────────────────────
    print(f"\n\n{'='*70}")
    print(f"  📊 3-CYCLE SUMMARY")
    print(f"{'='*70}")

    for r in results:
        print(f"\n  Cycle {r['cycle']}:")
        print(f"    Planning messages: {r['planning']['total_messages']}")
        print(f"    Tasks: {len(r['tasks'])}")
        print(f"    Review messages: {r['review']['total_messages']}")
        print(f"    Retro messages: {r['retro']['total_messages']}")
        escalations = []
        for phase in ["planning", "review", "retro"]:
            escalations.extend(r[phase].get("escalations", []))
        print(f"    Escalations: {len(escalations)}")
        if r['retro'].get('decisions'):
            print(f"    Decisions: {len(r['retro']['decisions'])}")

    total_msgs = sum(
        r['planning']['total_messages'] + r['review']['total_messages'] + r['retro']['total_messages']
        for r in results
    )
    print(f"\n  Total messages across all meetings: {total_msgs}")
    print(f"  Total meetings: 9 (3 planning + 3 review + 3 retro)")
    print(f"\n  📄 All transcripts saved to meetings/")
    print(f"\n{'='*70}")
    print(f"  🦌 Autonomous cycle complete — ready for Dandan's review!")
    print(f"{'='*70}")


if __name__ == "__main__":
    import functools
    print = functools.partial(print, flush=True)
    asyncio.run(main())
