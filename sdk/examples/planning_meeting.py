#!/usr/bin/env python3
"""Product Planning Meeting — Agent Meeting Platform Roadmap

Roles:
- Sarah (Product Manager): Strategic direction, user needs, prioritization
- Alex (Tech Lead): Architecture, technical debt, scalability
- Jordan (UX/Design): Developer experience, API design, onboarding
- Morgan (QA/DevOps): Testing, CI/CD, deployment, reliability

Each agent uses OpenClawMeetingBridge to join and discuss the project roadmap.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_meeting.connectors.openclaw import OpenClawMeetingBridge
from agent_meeting import MeetingClient

SERVER = "http://localhost:8000"

# ── Project Context (shared knowledge) ─────────────────────────

PROJECT_CONTEXT = """
Agent Meeting Platform — Current State (May 2026):

COMPLETED:
- Multi-agent meeting rooms with WebSocket real-time events
- LLM-powered moderator (7-phase state machine)
- Python SDK (MeetingClient) with event-driven API
- Frontend (Next.js) with meeting UI
- OpenClaw connector (OpenClawMeetingBridge) for agent participation
- REST API (25+ endpoints) + WebSocket events
- Voting, proposals, decisions
- Action items extraction
- Meeting minutes generation
- Rate limiting on agent responses
- Event bus bridge (REST → WebSocket)
- GitHub: Sparkling-AI/agent-meeting-platform (public)

KNOWN ISSUES:
- Moderator LLM minutes are generic (needs better prompting)
- No authentication/authorization
- No persistent rooms (all in-memory via DB but no room recovery)
- Frontend not deployed (local only)
- No SDK published to PyPI
- Action items not assigned automatically
- No multi-meeting support (can't chain meetings)

TECH STACK:
- Backend: FastAPI, PostgreSQL, SQLAlchemy async
- Frontend: Next.js 16
- SDK: Python (httpx + websockets)
- LLM: OpenRouter (Gemini 2.5 Flash)
"""

# ── Agent Personas ──────────────────────────────────────────────

PERSONAS = {
    "sarah": {
        "name": "Sarah Chen",
        "role": "product-manager",
        "emoji": "📋",
        "perspective": "user needs, market fit, prioritization, growth",
        "responses": {
            "question": [
                "From a product perspective, our biggest gap is the developer onboarding experience. We need a 5-minute quickstart that gets someone from `pip install` to their first meeting. That's what drives adoption.",
                "Looking at the competitive landscape, the differentiator is the LLM moderator. But right now it produces generic summaries. We need to invest in making the moderator truly useful — structured decisions, clear action items, follow-up tracking.",
                "I think we should target 3 user segments: (1) solo devs wanting to coordinate multiple AI agents, (2) teams building multi-agent systems, (3) researchers experimenting with agent collaboration.",
                "The priority should be: auth + deployment first (unblocks real users), then SDK polish + PyPI package, then advanced moderator features.",
            ],
            "chat": [
                "Good point. But we need to balance features with stability. I'd rather ship a solid v0.1 with 5 great features than a buggy v0.5 with 20 features.",
                "User research shows developers want simplicity. The SDK API is clean, but the deployment story is complex — Docker + PostgreSQL + LLM key. We need a hosted option or at least a one-click deploy.",
                "Agreed. Let's also think about the meeting lifecycle — right now meetings are one-off. Users want meeting series, recurring syncs, and action item tracking across meetings.",
                "From the GitHub readme, the demo GIF is great but we need a hosted demo. People want to try it without setting up local infra.",
            ],
            "proposal": "As PM, I support anything that moves us toward a shippable v1.0. Key criteria: new users can go from discovery to first meeting in under 10 minutes.",
        },
    },
    "alex": {
        "name": "Alex Rivera",
        "role": "tech-lead",
        "emoji": "🔧",
        "perspective": "architecture, scalability, technical debt, security",
        "responses": {
            "question": [
                "Technically, the architecture is solid for the current scope. FastAPI + PostgreSQL + WebSocket is a proven stack. The main concern is the moderator's LLM dependency — if OpenRouter is down, meetings still work but lose moderation. We need graceful degradation.",
                "The biggest technical debt is auth. Right now anyone can join any room. For a public release, we need: API key auth for agents, JWT for frontend users, and room-level permissions. I'd estimate 2-3 days of work.",
                "The event bus pattern we implemented is clean, but it's in-process only. For horizontal scaling, we'd need Redis pub/sub or similar. But that's a v2 concern — single-server works for now.",
                "I'd prioritize: (1) auth layer, (2) CI/CD pipeline with tests, (3) PyPI package, (4) deployment docs with Docker Compose. The code itself is in good shape.",
            ],
            "chat": [
                "The OpenClaw connector rate limiting is a good pattern. We should extend it to all SDK operations — prevent any single agent from overwhelming the system.",
                "On the database side, we should add indexes on room_id and created_at for the messages table. With large meetings, queries will slow down without them.",
                "One thing I noticed: the moderator's close_meeting creates decisions from votes, but the vote matching logic is fragile. It parses JSON content strings. We should normalize vote storage.",
                "For testing, we need integration tests that actually spin up the server. The unit test coverage is decent but we have zero integration coverage for the WebSocket flow.",
            ],
            "proposal": "Tech lead perspective: I'm on board if we address auth and testing before any new features. We can't ship public without basic security.",
        },
    },
    "jordan": {
        "name": "Jordan Park",
        "role": "ux-design",
        "emoji": "🎨",
        "perspective": "developer experience, API design, documentation, onboarding",
        "responses": {
            "question": [
                "From a DX perspective, the SDK API is actually really nice. `MeetingClient` with event handlers is intuitive. But the installation process needs work — `pip install -e ./sdk` is not user-friendly. We need `pip install agent-meeting`.",
                "The documentation is comprehensive but it's all reference docs. We need guides: 'Your First Meeting', 'Connecting Your Agent', 'Custom Moderators'. Think Django's tutorial approach.",
                "The frontend UI is functional but feels like a dev tool. For broader adoption, we need polish: better message formatting, real-time typing indicators, agent avatar support, meeting timeline visualization.",
                "Biggest DX gap: error messages. When something fails, users get generic errors. We need specific, actionable error messages with links to docs.",
            ],
            "chat": [
                "Love that suggestion. I'd add: we should have a visual meeting flow diagram in the docs. The 7-phase moderator state machine is powerful but hard to understand from text alone.",
                "For the SDK, the OpenClaw connector pattern is excellent. We should create similar connectors for: LangChain agents, AutoGen, CrewAI. That's how we build an ecosystem.",
                "The README demo GIF is good marketing. But we also need a asciinema cast for terminal-focused developers. Some people prefer seeing CLI flows over animations.",
                "On onboarding: a `npx create-agent-meeting` or `cookiecutter` template that scaffolds a project with a working agent would be huge. 5-minute quickstart or bust.",
            ],
            "proposal": "Design perspective: fully support this. The user journey from discovery to value needs to be under 10 minutes. That's our north star metric.",
        },
    },
    "morgan": {
        "name": "Morgan Wu",
        "role": "qa-devops",
        "emoji": "🚀",
        "perspective": "testing, CI/CD, deployment, monitoring, reliability",
        "responses": {
            "question": [
                "From a reliability standpoint, the platform works but has no observability. We need: health checks, metrics (messages/sec, meeting duration, error rates), and structured logging. Without this, we're flying blind in production.",
                "Testing is the biggest gap. Zero integration tests. The WebSocket flow is the core feature and it has no automated testing. We need a test suite that: starts the server, creates agents, runs a meeting, verifies the transcript. CI should run this on every PR.",
                "For deployment, Docker Compose works for dev but we need production guidance. Options: Fly.io (easy), Railway (easy), AWS ECS (enterprise). We should provide templates for at least one.",
                "I'd also flag: no rate limiting at the API level. A single agent can spam messages. The SDK-level rate limiting helps but doesn't protect against malicious clients.",
            ],
            "chat": [
                "Agreed on CI/CD. GitHub Actions with: lint (ruff), unit tests, integration tests, Docker build. We should also add a smoke test that deploys to a staging environment.",
                "For monitoring, I'd suggest OpenTelemetry integration. It's vendor-neutral and gives us traces for the full meeting lifecycle: room creation → agent joins → messages → moderator actions → decisions → close.",
                "The PostgreSQL schema needs migrations. Right now it uses auto-create. For production, we need versioned migrations (Alembic) with rollback support.",
                "Security checklist before public release: rate limiting, input validation on message content (prevent XSS in frontend), CORS configuration, secrets management for LLM keys.",
            ],
            "proposal": "QA/DevOps view: approve if we commit to CI/CD pipeline + integration tests as part of the next sprint. No merging without tests.",
        },
    },
}


async def run_agent(
    persona_key: str, room_id: str, delay: float = 0,
):
    """Run a single agent with its persona."""
    p = PERSONAS[persona_key]
    name = f"{p['name']} {p['emoji']}"
    role = p["role"]
    resp_idx = {"question": 0, "chat": 0}

    await asyncio.sleep(delay)

    bridge = OpenClawMeetingBridge(
        server_url=SERVER,
        agent_name=name,
        capabilities={"role": role, "department": "engineering"},
    )
    await bridge.start(room_id)
    print(f"  {p['emoji']} {p['name']} ({role}) joined")

    async def handler(brg, event):
        if not event.message or (event.message.agent_id == brg.agent_id):
            return None

        msg = event.message
        # Don't respond to own messages or moderator summaries
        if msg.type in ("summary", "vote"):
            return None

        speaker = msg.agent_name or "?"
        content = msg.content[:100]
        print(f"    {p['emoji']} {p['name']} sees [{msg.type}] from {speaker}: {content}...")

        if msg.type == "proposal":
            try:
                await brg.vote(event.message.id, "yes", reasoning=p["responses"]["proposal"][:200])
                print(f"    {p['emoji']} {p['name']} voted ✅")
            except Exception as e:
                print(f"    {p['emoji']} vote error: {e}")
            return None

        if msg.type == "question":
            idx = resp_idx["question"] % len(p["responses"]["question"])
            resp_idx["question"] += 1
            return p["responses"]["question"][idx]

        if msg.type == "chat":
            idx = resp_idx["chat"] % len(p["responses"]["chat"])
            resp_idx["chat"] += 1
            return p["responses"]["chat"][idx]

        return None

    bridge.set_response_handler(handler)
    try:
        await asyncio.wait_for(bridge.run(), timeout=90)
    except asyncio.TimeoutError:
        print(f"  {p['emoji']} {p['name']} session ended")
    except asyncio.CancelledError:
        pass
    finally:
        await bridge.stop()


async def main():
    print("╔══════════════════════════════════════════════════════════════════════════╗")
    print("║  🏢 Product Planning Meeting — Agent Meeting Platform Roadmap          ║")
    print("╚══════════════════════════════════════════════════════════════════════════╝")
    print()
    print("📋 Project Context:")
    print("   Public open-source multi-agent meeting platform with LLM moderator")
    print("   Repo: github.com/Sparkling-AI/agent-meeting-platform")
    print()

    # 1. Create room
    print("📋 Step 1: Creating planning meeting...")
    coord = MeetingClient(
        server_url=SERVER,
        name="Meeting Facilitator",
        capabilities={"role": "facilitator"},
    )
    await coord.register()
    room = await coord.create_room(
        name="Q2 2026 Roadmap Planning",
        topic="What should the Agent Meeting Platform v1.0 look like? Prioritize the next 4 weeks of work.",
        agenda=[
            {"title": "Current state review", "timebox_minutes": 3},
            {"title": "User needs & market fit", "timebox_minutes": 5},
            {"title": "Technical priorities", "timebox_minutes": 5},
            {"title": "Roadmap proposal & vote", "timebox_minutes": 5},
        ],
    )
    room_id = room.id
    await coord.join_room(room_id)
    await coord.activate_room(room_id)
    print(f"  🏠 Room: {room.name}")
    print(f"  📝 Topic: {room.topic}")
    print(f"  🆔 {room_id[:8]}")
    print()

    # 2. Start agents (before moderator)
    print("👥 Step 2: Team joining...")
    agent_tasks = [
        asyncio.create_task(run_agent("sarah", room_id, delay=0)),
        asyncio.create_task(run_agent("alex", room_id, delay=0.5)),
        asyncio.create_task(run_agent("jordan", room_id, delay=1.0)),
        asyncio.create_task(run_agent("morgan", room_id, delay=1.5)),
    ]
    await asyncio.sleep(5)
    print()

    # 3. Start moderator
    print("🧠 Step 3: Starting moderator...")
    result = await coord.start_moderator(room_id)
    print(f"  🤖 Moderator started — Phase: {result.get('phase', '?')}")
    print()

    # 4. Kick off discussion
    print("💬 Step 4: Discussion begins!")
    print("   ══════════════════════════════════════════════════════════════════════")
    print()

    await coord.send(
        "Welcome everyone! Let's align on the Agent Meeting Platform roadmap. "
        "We shipped the core platform (multi-agent meetings, LLM moderator, Python SDK, "
        "OpenClaw connector) and published it open-source. Now: what's next? "
        "What should v1.0 look like, and what do we prioritize in the next 4 weeks?",
        type="question",
        room_id=room_id,
    )
    print("  🎯 Facilitator: What should v1.0 look like and what do we prioritize?")
    print()

    await asyncio.sleep(12)

    # 5. Follow-up questions by topic
    print("  📊 Facilitator: Let's drill into priorities...")
    await coord.send(
        "Great perspectives! Let me synthesize: we all agree on auth and testing as "
        "foundational. But there's tension between 'ship fast' vs 'build it right'. "
        "Sarah, Alex — how do we balance quick iteration with solid foundations? "
        "And Jordan, what's the minimum DX investment needed?",
        type="question",
        room_id=room_id,
    )
    print("  🎯 Facilitator: How to balance speed vs quality?")
    print()

    await asyncio.sleep(15)

    # 6. Technical deep-dive
    await coord.send(
        "OK, we're converging. Let's talk specifics for the tech stack. "
        "Alex, what's the effort for auth? Morgan, what does the CI pipeline look like?",
        type="chat",
        room_id=room_id,
    )
    print("  🎯 Facilitator: Let's talk specific implementation effort.")
    print()

    await asyncio.sleep(12)

    # 7. Proposal — 4-week roadmap
    print()
    print("💡 Step 7: Facilitator proposes the roadmap...")
    proposal = await coord.send(
        "Proposal: Agent Meeting Platform v1.0 Roadmap (4 weeks)\n\n"
        "Week 1-2: Foundation\n"
        "  - Add API key + JWT authentication layer\n"
        "  - Set up GitHub Actions CI (lint + unit tests + integration tests)\n"
        "  - Add Alembic migrations for database schema\n"
        "  - Add rate limiting at API level\n\n"
        "Week 3: Polish & Package\n"
        "  - Publish SDK to PyPI as `agent-meeting`\n"
        "  - Write tutorial guides (Your First Meeting, Custom Agents, Connectors)\n"
        "  - Improve moderator prompt for better minutes/decisions\n"
        "  - Docker Compose one-click deploy template\n\n"
        "Week 4: Launch\n"
        "  - Hosted demo on Fly.io or Railway\n"
        "  - Blog post + launch on HN/Reddit\n"
        "  - Create connector templates (LangChain, AutoGen, CrewAI)\n"
        "  - Record video walkthrough\n\n"
        "Success Metric: New user goes from `pip install agent-meeting` to first "
        "multi-agent meeting in under 10 minutes.",
        type="proposal",
        room_id=room_id,
    )
    print(f"  💡 Roadmap proposed (4-week plan)")
    print()

    await asyncio.sleep(8)

    # Facilitator votes
    await coord.vote(
        proposal.id, "yes",
        reasoning="Comprehensive plan that balances foundation with launch. 10-min quickstart is the right north star.",
        room_id=room_id,
    )
    print("  🗳️  Facilitator: ✅ YES")
    print()

    await asyncio.sleep(8)

    # 8. Close meeting
    print("🏁 Step 8: Closing meeting...")
    try:
        close_result = await coord.close_meeting()
        print(f"  ✅ Meeting closed!")
        print(f"  📊 Messages: {close_result.get('total_messages', '?')}")
        print(f"  📊 Decisions: {close_result.get('decisions', '?')}")
    except Exception as e:
        print(f"  ⚠️ Close: {e}")

    # Cleanup
    for t in agent_tasks:
        t.cancel()
    await asyncio.gather(*agent_tasks, return_exceptions=True)

    # 9. Full results
    print()
    messages, total = await coord.get_messages(room_id)
    decisions = await coord.get_decisions(room_id)
    action_items = await coord.get_action_items(room_id)

    print("╔══════════════════════════════════════════════════════════════════════════╗")
    print("║                      📊 MEETING RESULTS                                ║")
    print("╠══════════════════════════════════════════════════════════════════════════╣")
    print(f"║  Total Messages:  {total:<55} ║")
    print(f"║  Decisions:       {len(decisions):<55} ║")
    print(f"║  Action Items:    {len(action_items):<55} ║")
    print("╠══════════════════════════════════════════════════════════════════════════╣")
    print("║                          DECISIONS                                     ║")
    print("╠══════════════════════════════════════════════════════════════════════════╣")
    for d in decisions:
        title = d.title[:65]
        print(f"║  ✅ {title:<68} ║")
        if d.summary:
            print(f"║     {d.summary[:68]:<68} ║")
    print("╠══════════════════════════════════════════════════════════════════════════╣")
    print("║                        ACTION ITEMS                                    ║")
    print("╠══════════════════════════════════════════════════════════════════════════╣")
    if action_items:
        for a in action_items:
            print(f"║  📌 {a.title[:68]:<68} ║")
    else:
        print("║  (Moderator did not auto-extract action items)                        ║")
    print("╚══════════════════════════════════════════════════════════════════════════╝")

    # 10. Transcript
    print()
    print("📝 FULL TRANSCRIPT:")
    print("   ══════════════════════════════════════════════════════════════════════")

    # Group by participant
    participant_msgs = {}
    for m in messages:
        name = m.agent_name or m.agent_id[:8]
        if name not in participant_msgs:
            participant_msgs[name] = 0
        participant_msgs[name] += 1

    for m in messages:
        name = m.agent_name or m.agent_id[:8]
        emoji = {"proposal": "💡", "question": "❓", "risk": "⚠️", "objection": "🚫",
                 "vote": "🗳️", "summary": "📝", "decision": "✅", "action_item": "📌"}.get(m.type, "💬")
        content = m.content[:120] + "..." if len(m.content) > 120 else m.content
        print(f"   {emoji} [{m.type.upper():12s}] {name}:")
        print(f"      {content}")
        print()

    print("   ══════════════════════════════════════════════════════════════════════")

    # 11. Participant summary
    print()
    print("👥 PARTICIPATION:")
    for name, count in sorted(participant_msgs.items(), key=lambda x: -x[1]):
        print(f"   {name}: {count} messages")

    await coord.close()

    # 12. Synthesized action plan (from Chopper's perspective)
    print()
    print("╔══════════════════════════════════════════════════════════════════════════╗")
    print("║  🦌 CHOPPER'S TAKEAWAY — Actionable Next Steps                        ║")
    print("╠══════════════════════════════════════════════════════════════════════════╣")
    print("║                                                                        ║")
    print("║  📅 WEEK 1-2: Foundation                                               ║")
    print("║    □ Add API key + JWT auth (Alex leads)                               ║")
    print("║    □ GitHub Actions CI pipeline (Morgan leads)                         ║")
    print("║    □ Alembic migrations (Alex)                                         ║")
    print("║    □ API-level rate limiting (Alex)                                    ║")
    print("║                                                                        ║")
    print("║  📅 WEEK 3: Polish & Package                                           ║")
    print("║    □ PyPI package: agent-meeting (Jordan leads)                        ║")
    print("║    □ Tutorial guides (Jordan)                                          ║")
    print("║    □ Improve moderator prompts (Sarah + Alex)                          ║")
    print("║    □ Docker Compose deploy template (Morgan)                           ║")
    print("║                                                                        ║")
    print("║  📅 WEEK 4: Launch                                                     ║")
    print("║    □ Hosted demo on Fly.io/Railway (Morgan)                            ║")
    print("║    □ Blog post + HN/Reddit launch (Sarah)                              ║")
    print("║    □ Connector templates: LangChain, AutoGen, CrewAI (Jordan)          ║")
    print("║    □ Video walkthrough (Sarah)                                         ║")
    print("║                                                                        ║")
    print("║  🎯 North Star: pip install → first meeting in < 10 minutes           ║")
    print("║                                                                        ║")
    print("╚══════════════════════════════════════════════════════════════════════════╝")
    print()
    print("🎉 Planning meeting complete!")


if __name__ == "__main__":
    asyncio.run(main())
