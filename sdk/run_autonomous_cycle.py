#!/usr/bin/env python3
"""Autonomous Sprint Runner V4 — with iteration inputs, parallel dev, and Chopper observation.

Reads iteration inputs from iterations/, runs meetings with context, 
parallelizes Claude Code tasks, and generates observation notes.
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
ITERATIONS_DIR = Path(__file__).parent.parent / "iterations"
PROJECT_ROOT = Path(__file__).parent.parent

# ── Load iteration inputs ────────────────────────────────────────

def load_latest_iteration() -> str:
    """Load the most recent iteration document as meeting input."""
    iters = sorted(ITERATIONS_DIR.glob("[0-9]*.md"))
    if not iters:
        return ""
    content = iters[-1].read_text()
    return content


def load_project_context() -> str:
    """Load actual project state for grounded task generation."""
    parts = []
    changelog = PROJECT_ROOT / "CHANGELOG.md"
    if changelog.exists():
        parts.append(f"CHANGELOG (last 20 lines):\n{changelog.read_text()[-1500:]}")
    
    # List actual files for reference
    backend_files = list((PROJECT_ROOT / "backend/app").rglob("*.py"))[:20]
    frontend_files = list((PROJECT_ROOT / "frontend/src").rglob("*.tsx"))[:15] if (PROJECT_ROOT / "frontend/src").exists() else []
    parts.append(f"Backend files: {', '.join(f.name for f in backend_files)}")
    if frontend_files:
        parts.append(f"Frontend files: {', '.join(f.name for f in frontend_files)}")
    
    test_files = list((PROJECT_ROOT / "backend/tests").glob("*.py"))
    parts.append(f"Test files: {', '.join(f.name for f in test_files)}")
    
    return "\n".join(parts)


# ── Load team profiles ──────────────────────────────────────────

def load_team():
    """Load team member profiles from team/*.md files."""
    team = []
    for f in sorted(TEAM_DIR.glob("*.md")):
        if f.name == "README.md":
            continue
        content = f.read_text()
        name_line = [l for l in content.split("\n") if l.startswith("# ")][0]
        heading = name_line.lstrip("# ").strip()
        parts = heading.split("—")
        name = parts[0].strip()
        role = parts[1].strip() if len(parts) > 1 else "Team Member"
        emoji = ""
        for char in heading:
            if ord(char) > 0x1F000:
                emoji += char

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
    num_rounds: int = 3,
) -> dict:
    """Run a meeting and return the transcript + decisions."""
    print(f"\n{'='*70}")
    print(f"  🤝 MEETING: {meeting_type.upper()}")
    print(f"  📋 Topic: {topic[:100]}...")
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
        name=f"{meeting_type.title()} — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
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
            round_guidance = {
                1: "Explore the topic. Share your unique perspective based on your role.",
                2: "Build on others' ideas. Propose concrete solutions or raise specific risks.",
                3: "Drive toward decisions. Make proposals, seek agreement. NO new exploration.",
                4: "Final positions only. Vote, agree, or state remaining concern. Be brief.",
            }.get(round_num, "Be concise and actionable.")

            force_types = "proposal|vote|summary|decision" if round_num >= num_rounds else "chat|question|proposal|objection|risk|summary"

            system = (
                f"You are {member['name']}, the {member['role']}. "
                f"Personality: {member['personality']} "
                f"Decision angle: {member['decision_angle']} "
                f"\n\nCRITICAL RULES:\n"
                f"1. DO NOT repeat what others said. If your point was made, AGREE briefly (1 sentence) and move on.\n"
                f"2. Later rounds must show PROGRESS toward decisions, not re-exploration.\n"
                f"3. If you agree with a proposal, say so explicitly and cast your vote.\n"
                f"4. This round: {round_guidance}\n"
                f"5. COST AWARENESS: Dev cost is LOW with agentic coding. Building is cheap. "
                f"But UX complexity is costly — keep features simple for users. "
                f"User acquisition cost is still HIGH — distribution matters.\n"
                f"6. The moderator has FINAL SAY. If the team is looping, the moderator decides. "
                f"Votes guide but don't bind the moderator. Disagree and commit.\n"
                f"7. Respond with JSON: {{\"type\": \"{force_types}\", \"content\": \"your 2-4 sentence response\"}}"
            )

            messages, _ = await client.get_messages(room_id, limit=20)
            history = ""
            for m in messages[-20:]:
                name = m.agent_name or m.agent_id[:8]
                history += f"\n[{name}]({m.type}): {m.content[:200]}"

            raw = await call_llm(system, f"Discussion:\n{history}\n\nYour response as {member['name']} (JSON only):")
            msg_type, content = parse_response(raw)
            valid = {"chat", "question", "proposal", "objection", "risk", "vote", "summary", "decision"}
            if msg_type not in valid:
                msg_type = "chat"
            await client.send(content[:800], type=msg_type, room_id=room_id)
            print(f"    💬 {member['name']}: {msg_type} — {content[:120]}")
            await asyncio.sleep(0.3)

    # CEO override check
    all_msgs_check, _ = await agents[0].get_messages(room_id, limit=50)
    recent_types = [m.type for m in all_msgs_check[-18:]] if len(all_msgs_check) >= 12 else []
    proposals = sum(1 for t in recent_types if t in ("proposal", "decision"))
    risks = sum(1 for t in recent_types if t == "risk")

    if len(recent_types) >= 12 and proposals == 0 and risks > 6:
        ceo_message = (
            "🚨 **CEO Decision:** We've been discussing without converging. "
            "I'm making the call now based on what I've heard. "
            "Dev cost is low with agentic coding, so we ship fast and iterate. "
            "No more discussion — here's what we build this sprint."
        )
        await agents[0].send(ceo_message[:800], type="decision", room_id=room_id)
        print(f"    👑 CEO OVERRIDE: Injected decision")
    elif len(recent_types) >= 12 and proposals < 2:
        await agents[0].send(
            "👑 **Moderator:** Enough discussion. I need concrete proposals NOW. "
            "If nobody proposes in the next message, I'll decide for us.",
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
        transcript.append({"agent": name, "type": m.type, "content": m.content})

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

    decisions = [msg["content"] for msg in transcript if msg["type"] == "decision"]
    escalations = [f"[{msg['agent']}]: {msg['content']}" for msg in transcript
                   if "🚨" in msg["content"] or "ESCALATION" in msg["content"].upper()]

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


# ── Task generation with project context ─────────────────────────

async def generate_sprint_tasks(meeting_result: dict, project_context: str) -> list[dict]:
    """Use LLM to extract actionable tasks from planning meeting."""
    transcript_text = "\n".join(
        f"[{m['agent']}]: {m['content']}" for m in meeting_result["transcript"]
    )
    raw = await call_llm(
        "You are a pragmatic sprint planner for a Python/FastAPI meeting platform. "
        "The project is at /home/chopper/workspace/agent-meeting-platform. "
        "It has: backend (FastAPI), SDK, frontend (Next.js), moderator engine, WebSocket, Docker. "
        "RULES: Tasks must be CONCRETE code changes, not abstract evaluations. "
        "Each task should be completable in 1-2 hours by a single developer. "
        "Prefer: bug fixes, feature implementations, test improvements, documentation updates. "
        "NOT: 'evaluate', 'assess', 'review', 'define' — those are discussions, not tasks. "
        "Focus on shipping useful value at minimum cost. "
        "Dev cost is LOW (agentic coding). UX simplicity is HIGH value. "
        "Reference actual file names and paths when possible.",
        f"Meeting transcript:\n{transcript_text[-4000:]}\n\n"
        f"Project context:\n{project_context[:2000]}\n\n"
        f"Based on this meeting, list 3-5 concrete CODE tasks as JSON array:\n"
        f'[{{"title": "task title", "description": "what code to write/change, include file paths", "owner": "role", "priority": "high|medium|low"}}]\n'
        f"Examples of good tasks: 'Fix DB auth in backend/tests/conftest.py', "
        f"'Add moderator_mindset/ config folder with default.yaml', "
        f"'Create /moderation setup guide in docs/for-agents.md'.\n"
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


# ── Parallel development with Claude Code ────────────────────────

async def run_single_task(task: dict, project_dir: str, idx: int) -> tuple[str, str]:
    """Run a single Claude Code task. Returns (status, output)."""
    title = task.get('title', 'Unknown task')
    desc = task.get('description', '')
    
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
        f"6. Do NOT push — just commit locally\n\n"
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
        output = stdout.decode()[:300] if stdout else ""
        err = stderr.decode()[:200] if stderr else ""

        if proc.returncode == 0:
            return f"✅ {title}", output[:80]
        else:
            return f"⚠️ {title} (exit {proc.returncode}: {err[:60]})", err[:80]
    except FileNotFoundError:
        return f"⏭️ {title} (Claude Code not found)", "skipped"
    except asyncio.TimeoutError:
        return f"⏰ {title} (timed out 5min)", "timeout"


async def run_development_sprint(tasks: list[dict], cycle: int) -> list[str]:
    """Run development tasks IN PARALLEL using Claude Code."""
    completed = []
    project_dir = str(PROJECT_ROOT)
    
    print(f"    🚀 Running {len(tasks)} tasks in parallel...")
    
    # Run all tasks concurrently
    coros = [run_single_task(task, project_dir, i) for i, task in enumerate(tasks)]
    results = await asyncio.gather(*coros, return_exceptions=True)
    
    for result in results:
        if isinstance(result, Exception):
            completed.append(f"❌ Error: {str(result)[:60]}")
            print(f"    ❌ Error: {str(result)[:80]}")
        else:
            status, detail = result
            completed.append(status)
            print(f"    {status}")
            if detail:
                print(f"       → {detail[:100]}")
    
    return completed


# ── Chopper observation step ──────────────────────────────────────

async def chopper_observe(cycle: int, results_so_far: list[dict]) -> str | None:
    """Chopper observes the cycle and generates improvement notes."""
    if not results_so_far:
        return None
    
    last = results_so_far[-1]
    
    # Analyze meeting quality
    planning = last.get("planning", {})
    review = last.get("review", {})
    retro = last.get("retro", {})
    
    # Count message types
    all_transcript = []
    for phase in [planning, review, retro]:
        all_transcript.extend(phase.get("transcript", []))
    
    type_counts = {}
    for msg in all_transcript:
        t = msg.get("type", "chat")
        type_counts[t] = type_counts.get(t, 0) + 1
    
    # Build observation
    observations = []
    observations.append(f"# Chopper's Observation — Cycle {cycle}")
    observations.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    observations.append("")
    observations.append("## Message Type Distribution")
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        observations.append(f"- {t}: {count}")
    
    proposal_ratio = type_counts.get("proposal", 0) / max(sum(type_counts.values()), 1)
    vote_ratio = type_counts.get("vote", 0) / max(sum(type_counts.values()), 1)
    risk_ratio = type_counts.get("risk", 0) / max(sum(type_counts.values()), 1)
    
    observations.append("")
    observations.append("## Quality Assessment")
    if proposal_ratio < 0.1:
        observations.append("- ⚠️ Low proposal rate — team discusses but doesn't propose enough")
    else:
        observations.append(f"- ✅ Proposal rate: {proposal_ratio:.0%}")
    
    if vote_ratio < 0.05:
        observations.append("- ⚠️ Almost no voting — decisions aren't being formalized")
    else:
        observations.append(f"- ✅ Vote rate: {vote_ratio:.0%}")
    
    if risk_ratio > 0.4:
        observations.append("- ⚠️ Risk-heavy discussion — too much worrying, not enough doing")
    
    # Check for looping
    contents = [m.get("content", "")[:50].lower() for m in all_transcript]
    unique_count = len(set(contents))
    total_count = len(contents)
    repeat_ratio = 1 - (unique_count / max(total_count, 1))
    if repeat_ratio > 0.3:
        observations.append(f"- ⚠️ High repetition ({repeat_ratio:.0%}) — agents saying similar things")
    
    # Dev phase results
    completed = last.get("completed", [])
    real_commits = [c for c in completed if c.startswith("✅") and "simulated" not in c]
    observations.append(f"\n## Dev Phase: {len(real_commits)}/{len(completed)} tasks completed with real code")
    
    # Generate recommendations
    observations.append("\n## Recommendations for Next Cycle")
    if proposal_ratio < 0.1:
        observations.append("- Force proposal-only in round 2+ (not just round 3)")
    if risk_ratio > 0.4:
        observations.append("- Cap risk messages per meeting — max 30% of messages can be 'risk' type")
    if repeat_ratio > 0.3:
        observations.append("- Improve anti-repetition in prompts")
    if len(real_commits) < len(completed) * 0.8:
        observations.append("- Improve task specificity — reference actual files and line numbers")
    
    obs_text = "\n".join(observations)
    
    # Save observation
    obs_path = ITERATIONS_DIR / f"{datetime.now().strftime('%Y-%m-%d')}-chopper-obs-cycle-{cycle}.md"
    obs_path.write_text(obs_text)
    print(f"  🦌 Chopper's observation saved: {obs_path.name}")
    
    return obs_text


# ── Meeting index update ──────────────────────────────────────────

async def update_meetings_index():
    entries = []
    for f in sorted(MEETINGS_DIR.glob("*.md")):
        if f.name == "README.md":
            continue
        parts = f.stem.split("-", 3)
        date_str = "-".join(parts[:3])
        meeting_type = parts[3] if len(parts) > 3 else "meeting"
        content = f.read_text()[:500]
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


# ── Main ──────────────────────────────────────────────────────────

async def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  🦌 AUTONOMOUS CYCLE V4 — Agent Meeting Platform            ║")
    print("║  With: iteration inputs, parallel dev, Chopper observation  ║")
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
            print("❌ Backend not running!")
            sys.exit(1)

    # Load context
    team = load_team()
    iteration_input = load_latest_iteration()
    project_context = load_project_context()
    
    print(f"  👥 Team: {len(team)} members")
    for m in team:
        print(f"     {m['name']} — {m['role']}")
    
    if iteration_input:
        print(f"  📋 Iteration input loaded ({len(iteration_input)} chars)")
    print(f"  📁 Project context loaded")

    results = []

    for cycle in range(1, 4):
        print(f"\n{'#'*70}")
        print(f"#  🔄 CYCLE {cycle}/3")
        print(f"{'#'*70}")

        # ── 1. SPRINT PLANNING ──────────────────────────────────
        if cycle == 1:
            planning_topic = (
                "Sprint Planning — V4 Cycle with iteration inputs.\n\n"
                "KEY ISSUES FROM LAST RETRO (iteration 001):\n"
                "1. Team loops instead of deciding — need stronger moderator authority\n"
                "2. Dev phase only ran 1/3 cycles — now running parallel Claude Code tasks\n"
                "3. Tasks too abstract — now referencing actual project files\n"
                "4. Voting isn't always best — moderator has final say, 'disagree and commit'\n"
                "5. Dev cost is LOW with agentic coding — build fast, keep UX simple\n"
                "6. Users will use AI agents to set up — need agent-friendly docs\n"
                "7. Moderator mindset should be a configurable plugin\n\n"
                "PROJECT STATE:\n"
                f"{project_context[:1500]}\n\n"
                "What should we BUILD or FIX? Concrete code tasks only. "
                "Reference actual files. Keep it simple, shippable, useful."
            )
        else:
            prev_review = results[-1].get("review", {})
            chopper_obs = results[-1].get("chopper_observation", "")
            review_summary = "\n".join(
                f"[{m['agent']}]: {m['content'][:100]}"
                for m in prev_review.get("transcript", [])[-6:]
            ) if prev_review else "Previous cycle completed."
            planning_topic = (
                f"Sprint Planning — Cycle {cycle}.\n\n"
                f"Previous review:\n{review_summary}\n\n"
            )
            if chopper_obs:
                planning_topic += f"Chopper's observations:\n{chopper_obs[:1000]}\n\n"
            planning_topic += "What should we tackle next? Concrete code tasks only."

        planning_result = await run_meeting(
            team, f"planning-cycle-{cycle}",
            topic=planning_topic,
            agenda=[
                {"title": "Review current state and iteration inputs", "timebox_minutes": 4},
                {"title": "Propose concrete sprint tasks", "timebox_minutes": 5},
                {"title": "Decide sprint plan", "timebox_minutes": 3},
            ],
            num_rounds=3,
        )

        # Generate tasks with project context
        tasks = await generate_sprint_tasks(planning_result, project_context)
        print(f"\n  📋 Sprint {cycle} tasks:")
        for t in tasks:
            print(f"     [{t.get('priority', '?')}] {t['title'][:70]}")
            if t.get('description'):
                print(f"         → {t['description'][:80]}")

        # ── 2. DEVELOPMENT (PARALLEL) ────────────────────────────
        print(f"\n  🔨 Development phase (parallel)...")
        dev_start = time.time()
        completed = await run_development_sprint(tasks, cycle)
        dev_elapsed = time.time() - dev_start
        print(f"  ⏱️ Dev phase took {dev_elapsed:.0f}s")

        # ── 3. SPRINT REVIEW ────────────────────────────────────
        review_topic = (
            f"Sprint {cycle} Review. "
            f"Tasks: {', '.join(t['title'][:40] for t in tasks)}. "
            f"Dev took {dev_elapsed:.0f}s. "
            f"Did we ship useful value? What needs improvement?"
        )
        review_result = await run_meeting(
            team, f"review-cycle-{cycle}",
            topic=review_topic,
            agenda=[
                {"title": "Demo completed work", "timebox_minutes": 4},
                {"title": "Quality + UX assessment", "timebox_minutes": 4},
            ],
            num_rounds=3,
        )

        # ── 4. RETROSPECTIVE ────────────────────────────────────
        retro_topic = (
            f"Sprint {cycle} Retrospective. "
            f"What went well? What didn't? What should change? "
            f"Be honest. Focus on process, not just tech."
        )
        retro_result = await run_meeting(
            team, f"retro-cycle-{cycle}",
            topic=retro_topic,
            agenda=[
                {"title": "What went well", "timebox_minutes": 3},
                {"title": "What needs improvement", "timebox_minutes": 4},
                {"title": "Process improvements for next cycle", "timebox_minutes": 3},
            ],
            num_rounds=3,
        )

        # ── 5. CHOPPER OBSERVATION ──────────────────────────────
        cycle_data = {
            "cycle": cycle,
            "planning": planning_result,
            "tasks": tasks,
            "completed": completed,
            "review": review_result,
            "retro": retro_result,
            "dev_elapsed": dev_elapsed,
        }
        chopper_obs = await chopper_observe(cycle, [cycle_data])
        cycle_data["chopper_observation"] = chopper_obs or ""
        results.append(cycle_data)

        # Print escalations
        all_escalations = []
        for phase in ["planning", "review", "retro"]:
            all_escalations.extend(cycle_data[phase].get("escalations", []))
        if all_escalations:
            print(f"\n  🚨 ESCALATIONS from Cycle {cycle}:")
            for e in all_escalations:
                print(f"     {e[:120]}")

    # Update meetings index
    await update_meetings_index()

    # ── FINAL SUMMARY ───────────────────────────────────────────
    print(f"\n\n{'='*70}")
    print(f"  📊 V4 CYCLE SUMMARY")
    print(f"{'='*70}")

    for r in results:
        print(f"\n  Cycle {r['cycle']}:")
        print(f"    Planning: {r['planning']['total_messages']} msgs")
        print(f"    Tasks: {len(r['tasks'])}")
        print(f"    Dev time: {r.get('dev_elapsed', 0):.0f}s")
        real = [c for c in r['completed'] if c.startswith("✅")]
        print(f"    Completed: {len(real)}/{len(r['completed'])} real commits")
        print(f"    Review: {r['review']['total_messages']} msgs")
        print(f"    Retro: {r['retro']['total_messages']} msgs")
        escalations = []
        for phase in ["planning", "review", "retro"]:
            escalations.extend(r[phase].get("escalations", []))
        print(f"    Escalations: {len(escalations)}")

    total_msgs = sum(
        r['planning']['total_messages'] + r['review']['total_messages'] + r['retro']['total_messages']
        for r in results
    )
    total_real = sum(len([c for c in r['completed'] if c.startswith("✅")]) for r in results)
    total_tasks = sum(len(r['tasks']) for r in results)
    
    print(f"\n  📊 Totals:")
    print(f"    Messages: {total_msgs}")
    print(f"    Real commits: {total_real}/{total_tasks} tasks")
    print(f"    Meetings: 9 (3 plan + 3 review + 3 retro)")
    print(f"    Observations: 3 (Chopper)")
    print(f"\n  📄 Transcripts → meetings/")
    print(f"  📄 Observations → iterations/")
    print(f"\n{'='*70}")
    print(f"  🦌 V4 complete — ready for review!")
    print(f"{'='*70}")


if __name__ == "__main__":
    import functools
    print = functools.partial(print, flush=True)
    asyncio.run(main())
