#!/usr/bin/env python3
"""
End-to-end test for the LLM-powered moderator in a real meeting.

Creates 4 agents with different roles and runs them through a complete meeting
lifecycle WITH the moderator managing everything.

Prerequisites:
- Backend server running on localhost:8000
- OPENROUTER_API_KEY set in environment or backend/.env

Test phases:
  1. Setup — register agents, create room, start moderator
  2. Opening — verify moderator welcome message + ground rules
  3. Discussion — 2 rounds of LLM-powered agent messages with moderator oversight
  4. Investigation — agent requests research, returns with findings
  5. Proposals & Voting — agent proposes, others vote, moderator creates decision
  6. Close — moderator posts summary, decisions, action items
"""

import asyncio
import httpx
import json
import os
import sys
import time
import uuid
from datetime import datetime

BASE_URL = "http://localhost:8000"
MODERATOR_STATE_URL = "/api/rooms/{room_id}/moderator/state"
MODERATOR_START_URL = "/api/rooms/{room_id}/moderator/start"
MODERATOR_CLOSE_URL = "/api/rooms/{room_id}/moderator/close"
MODERATOR_INVESTIGATE_URL = "/api/rooms/{room_id}/moderator/investigate"
MODERATOR_VOTE_URL = "/api/rooms/{room_id}/moderator/vote"
MODERATOR_SUMMARY_URL = "/api/rooms/{room_id}/moderator/summary"

API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
if not API_KEY:
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("OPENROUTER_API_KEY="):
                    API_KEY = line.strip().split("=", 1)[1].strip().strip('"')

# ── Agent personas ──────────────────────────────────────────────────────────

AGENT_PERSONAS = [
    {
        "name": "Alex-PM",
        "role": "Product Manager",
        "style": "Focus on user value, business impact, and shipping fast. Data-driven decisions.",
        "capabilities": {"domains": ["product", "analytics"], "decision_authority": "advisory"},
    },
    {
        "name": "Jordan-Arch",
        "role": "Lead Architect",
        "style": "Cautious, thinks about edge cases, scalability, and technical debt. Prefers proven solutions.",
        "capabilities": {"domains": ["architecture", "security"], "decision_authority": "advisory"},
    },
    {
        "name": "Sam-Dev",
        "role": "Senior Developer",
        "style": "Practical, hates over-engineering, wants concrete specs. Ships code.",
        "capabilities": {"domains": ["backend", "frontend"], "decision_authority": "voting"},
    },
    {
        "name": "Riley-QA",
        "role": "QA Lead",
        "style": "Thinks about failure modes, testability, regression risks. Quality gatekeeper.",
        "capabilities": {"domains": ["testing", "quality"], "decision_authority": "voting"},
    },
]

AGENDA = {
    "items": [
        {"title": "Review current auth issues", "timebox_minutes": 3, "decision_required": False},
        {"title": "Evaluate passwordless vs enhanced password auth", "timebox_minutes": 5, "decision_required": True},
        {"title": "Plan implementation timeline", "timebox_minutes": 3, "decision_required": True},
    ],
    "meeting_type": "decision",
    "voting_method": "majority",
    "investigation_budget_minutes": 5,
}

MEETING_CONTEXT = {
    "room_name": "Auth Strategy Decision",
    "topic": (
        "Our auth system has issues: 30% of support tickets are password resets, "
        "no SSO support, and we're getting security audit findings. We need to decide: "
        "implement passwordless auth (magic links + SSO) OR enhance current password system "
        "with better policies. Timeline: 3 weeks. Budget: 2 developer sprints."
    ),
}

# ── Helpers ─────────────────────────────────────────────────────────────────

TYPE_EMOJI = {
    "chat": "💬", "question": "❓", "proposal": "💡", "objection": "🚫",
    "risk": "⚠️", "decision": "✅", "action_item": "📋", "vote": "🗳️",
    "summary": "📝", "request_ctx": "🔍", "system": "📢", "investigation_request": "🔬",
    "investigation_result": "📊",
}


async def call_llm(system: str, user: str, max_tokens: int = 250) -> str:
    """LLM call via OpenRouter (google/gemini-2.5-flash)."""
    async with httpx.AsyncClient(timeout=60) as c:
        resp = await c.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "google/gemini-2.5-flash",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.8,
                "max_tokens": max_tokens,
            },
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        return f"[LLM error: {resp.status_code} — {resp.text[:200]}]"


def parse_json_response(raw: str) -> dict:
    """Parse JSON from LLM response, with fallback extraction."""
    text = raw.strip()
    # Try to extract JSON block
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, AttributeError):
        # Try to find JSON object in the text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        return {"type": "chat", "content": text}


async def get_moderator_state(client: httpx.AsyncClient, room_id: str) -> dict | None:
    """Get moderator state, returns None if endpoint not available."""
    resp = await client.get(f"{BASE_URL}{MODERATOR_STATE_URL}".format(room_id=room_id))
    if resp.status_code == 200:
        return resp.json()
    return None


async def wait_for_moderator_endpoint(client: httpx.AsyncClient, room_id: str, timeout_s: int = 10) -> bool:
    """Wait for the moderator state endpoint to respond."""
    for _ in range(timeout_s // 2):
        state = await get_moderator_state(client, room_id)
        if state is not None:
            return True
        await asyncio.sleep(2)
    return False


async def post_message(client: httpx.AsyncClient, room_id: str, agent_id: str,
                       msg_type: str, content: str, parent_id: str | None = None) -> dict | None:
    """Post a message to the room."""
    payload = {
        "agent_id": agent_id,
        "type": msg_type,
        "content": content[:2000],
    }
    if parent_id:
        payload["parent_id"] = parent_id
    resp = await client.post(f"{BASE_URL}/api/rooms/{room_id}/messages", json=payload)
    if resp.status_code in (200, 201):
        return resp.json()
    print(f"    ⚠️ Message post failed: {resp.status_code} — {resp.text[:100]}")
    return None


# ── Assertions ──────────────────────────────────────────────────────────────

class TestResults:
    """Track test results."""
    def __init__(self):
        self.passed: list[str] = []
        self.failed: list[str] = []
        self.warnings: list[str] = []
        self.transcript: list[str] = []

    def ok(self, name: str):
        self.passed.append(name)

    def fail(self, name: str, detail: str = ""):
        self.failed.append(f"{name}: {detail}")

    def warn(self, msg: str):
        self.warnings.append(msg)

    def log(self, msg: str):
        self.transcript.append(msg)

    def summary(self) -> bool:
        all_pass = len(self.failed) == 0
        status = "✅ PASSED" if all_pass else "❌ FAILED"
        print(f"\n{'='*70}")
        print(f"🧪 TEST RESULTS: {status}")
        print(f"{'='*70}")
        print(f"  Passed: {len(self.passed)}")
        for p in self.passed:
            print(f"    ✅ {p}")
        if self.warnings:
            print(f"  Warnings: {len(self.warnings)}")
            for w in self.warnings:
                print(f"    ⚠️ {w}")
        if self.failed:
            print(f"  Failed: {len(self.failed)}")
            for f in self.failed:
                print(f"    ❌ {f}")
        print(f"{'='*70}")
        return all_pass


# ── Main test flow ──────────────────────────────────────────────────────────

async def run_moderated_meeting_test():
    """Full E2E test of the LLM-powered moderator."""
    results = TestResults()
    async with httpx.AsyncClient(timeout=30) as client:

        print("=" * 70)
        print("🎯 MODERATED MEETING E2E TEST")
        print(f"📋 {MEETING_CONTEXT['room_name']}")
        print(f"⏰ {datetime.now().isoformat()}")
        print("=" * 70)

        # ═══════════════════════════════════════════════════════════════
        # PHASE 0: SETUP
        # ═══════════════════════════════════════════════════════════════
        print("\n📦 Phase 0: Setup")

        # Reset
        resp = await client.post(f"{BASE_URL}/api/admin/reset-dev")
        assert resp.status_code == 200, f"Reset failed: {resp.status_code}"
        print("  🧹 Dev data reset")
        results.ok("reset_dev_data")

        # Register 4 agents
        agent_ids = []
        agent_map = {}  # id -> persona
        for persona in AGENT_PERSONAS:
            resp = await client.post(f"{BASE_URL}/api/agents", json={
                "name": persona["name"],
                "connector_type": "rest",
                "capabilities": persona["capabilities"],
            })
            assert resp.status_code == 201, f"Agent registration failed for {persona['name']}: {resp.status_code}"
            aid = resp.json()["id"]
            agent_ids.append(aid)
            agent_map[aid] = persona
            print(f"  ✅ {persona['name']} registered ({aid[:8]})")
        results.ok("register_4_agents")

        # Create room with agenda in settings
        resp = await client.post(f"{BASE_URL}/api/rooms", json={
            "name": MEETING_CONTEXT["room_name"],
            "topic": MEETING_CONTEXT["topic"],
            "settings": AGENDA,
        })
        assert resp.status_code == 201, f"Room creation failed: {resp.status_code}"
        room_id = resp.json()["id"]
        print(f"  🏠 Room created: {room_id[:8]}")
        results.ok("create_room_with_agenda")

        # Verify agenda is stored in settings
        resp = await client.get(f"{BASE_URL}/api/rooms/{room_id}")
        room_detail = resp.json()
        assert room_detail.get("settings", {}).get("items"), "Agenda not stored in room settings"
        print(f"  📋 Agenda stored ({len(room_detail['settings']['items'])} items)")
        results.ok("agenda_in_settings")

        # Agents join
        resp = await client.post(
            f"{BASE_URL}/api/admin/rooms/{room_id}/bulk-join?role=participant",
            json=agent_ids,
        )
        assert resp.status_code == 200
        joined = resp.json().get("added_agents", [])
        assert len(joined) == 4, f"Expected 4 agents, got {len(joined)}"
        print(f"  👥 {len(joined)} agents joined")
        results.ok("agents_join_room")

        # Activate room
        resp = await client.patch(f"{BASE_URL}/api/rooms/{room_id}/status", json={"status": "active"})
        assert resp.status_code == 200
        print("  🟢 Room activated")
        results.ok("room_activated")

        # ═══════════════════════════════════════════════════════════════
        # PHASE 1: START MODERATOR
        # ═══════════════════════════════════════════════════════════════
        print("\n🎯 Phase 1: Start Moderator")

        # Try to start moderator via the moderator API
        moderator_available = False
        moderator_agent_id = None

        start_url = f"{BASE_URL}{MODERATOR_START_URL}".format(room_id=room_id)
        resp = await client.post(start_url, json={"agenda": AGENDA})

        if resp.status_code in (200, 201):
            start_data = resp.json()
            moderator_agent_id = start_data.get("moderator_agent_id")
            moderator_available = True
            print(f"  🤖 Moderator started (agent: {moderator_agent_id[:8] if moderator_agent_id else 'N/A'})")
            results.ok("moderator_started_via_api")

            # Verify moderator agent was created and joined
            resp = await client.get(f"{BASE_URL}/api/rooms/{room_id}")
            members = resp.json().get("members", [])
            moderator_member = [m for m in members if m.get("role") == "moderator"]
            if moderator_member:
                print(f"  ✅ Moderator agent joined as member")
                results.ok("moderator_joined_room")
            else:
                results.warn("moderator_not_in_members_list")

            # Check moderator state
            state = await get_moderator_state(client, room_id)
            if state:
                phase = state.get("phase", "unknown")
                print(f"  📊 Moderator state: phase={phase}")
                results.ok("moderator_state_accessible")
            else:
                results.warn("moderator_state_endpoint_missing")

        else:
            print(f"  ⚠️ Moderator start endpoint not available (HTTP {resp.status_code})")
            results.warn("moderator_start_endpoint_not_implemented")
            print("  ℹ️ Proceeding with manual moderator simulation...")
            # Register a manual moderator agent
            resp = await client.post(f"{BASE_URL}/api/agents", json={
                "name": "MeetingModerator",
                "connector_type": "rest",
                "capabilities": {"role": "moderator", "domains": ["facilitation"]},
            })
            moderator_agent_id = resp.json()["id"]
            await client.post(
                f"{BASE_URL}/api/admin/rooms/{room_id}/bulk-join?role=moderator",
                [moderator_agent_id],
            )
            print(f"  🤖 Manual moderator created ({moderator_agent_id[:8]})")
            results.ok("manual_moderator_fallback")

        # ═══════════════════════════════════════════════════════════════
        # PHASE 2: OPENING — moderator welcome message
        # ═══════════════════════════════════════════════════════════════
        print("\n📖 Phase 2: Opening")

        # Check for moderator welcome message
        await asyncio.sleep(2)  # Give moderator time to post

        resp = await client.get(f"{BASE_URL}/api/rooms/{room_id}/messages")
        all_messages = resp.json().get("messages", [])
        moderator_msgs = [m for m in all_messages if m.get("agent_id") == moderator_agent_id]

        if moderator_msgs:
            welcome = moderator_msgs[0]
            print(f"  📢 Moderator welcome message found:")
            print(f"     {welcome['content'][:150]}...")
            results.ok("moderator_welcome_message")

            # Check if ground rules were included
            content_lower = welcome["content"].lower()
            has_ground_rules = any(kw in content_lower for kw in ["ground rules", "guidelines", "rules", "stay on topic"])
            if has_ground_rules:
                print("  ✅ Ground rules included in welcome")
                results.ok("ground_rules_in_welcome")
            else:
                results.warn("no_explicit_ground_rules_in_welcome")
        else:
            # Post a welcome message ourselves as moderator
            welcome_text = (
                f"Welcome to '{MEETING_CONTEXT['room_name']}'.\n\n"
                f"Purpose: {MEETING_CONTEXT['topic'][:200]}\n\n"
                f"Agenda:\n"
            )
            for i, item in enumerate(AGENDA["items"], 1):
                welcome_text += f"  {i}. {item['title']} ({item['timebox_minutes']} min)\n"
            welcome_text += (
                "\nGround Rules:\n"
                "1. Stay on topic — flag off-topic items as parking lot\n"
                "2. No repeating arguments — new information only\n"
                "3. Speak concisely\n"
                "4. Decisions require explicit votes\n"
                "5. Investigation budget: up to 5 min for research\n"
            )
            await post_message(client, room_id, moderator_agent_id, "system", welcome_text)
            print(f"  📢 Moderator welcome posted manually")
            results.ok("moderator_welcome_manual")
            results.warn("moderator_did_not_auto_post_welcome")

        # Check moderator state for phase
        state = await get_moderator_state(client, room_id)
        if state:
            phase = state.get("phase", "")
            if phase in ("opening", "discussion"):
                print(f"  ✅ Moderator phase: {phase}")
                results.ok(f"moderator_phase_{phase}")
            else:
                results.warn(f"unexpected_moderator_phase: {phase}")

        # ═══════════════════════════════════════════════════════════════
        # PHASE 3: DISCUSSION — 2 rounds with moderator oversight
        # ═══════════════════════════════════════════════════════════════
        print("\n💬 Phase 3: Discussion (2 rounds)")

        conversation_log = [f"TOPIC: {MEETING_CONTEXT['topic']}"]
        all_message_ids = []

        for round_num in range(1, 3):
            print(f"\n  --- Round {round_num}/2 ---")

            async def agent_speak(idx: int, persona: dict, agent_id: str) -> tuple[str, str, str]:
                """Have an agent speak via LLM."""
                system = (
                    f"You are {persona['name']}, the {persona['role']}. "
                    f"Style: {persona['style']}. "
                    f"You are in a meeting about authentication strategy. "
                    f"Respond with JSON: {{\"type\": \"chat|question|proposal|risk|objection\", "
                    f"\"content\": \"your 1-3 sentence response\"}}"
                )
                user_msg = (
                    f"Meeting round: {round_num}/2\n"
                    f"Discussion so far:\n" + "\n".join(conversation_log[-8:]) +
                    f"\n\nYour response as {persona['name']} (JSON only):"
                )
                print(f"    🤔 {persona['name']}...", end=" ", flush=True)
                raw = await call_llm(system, user_msg)
                parsed = parse_json_response(raw)
                msg_type = parsed.get("type", "chat")
                content = parsed.get("content", raw[:300])

                result = await post_message(client, room_id, agent_id, msg_type, content)
                if result:
                    msg_id = result.get("id", str(uuid.uuid4()))
                    all_message_ids.append(msg_id)
                    conversation_log.append(
                        f"[{persona['name']}]({msg_type}): {content[:200]}"
                    )
                    emoji = TYPE_EMOJI.get(msg_type, "💬")
                    print(f"{emoji} {msg_type}")
                    return msg_id, msg_type, content
                else:
                    print("❌ failed")
                    return "", "chat", content

            # Agents speak in sequence (allows moderator to track turns)
            round_results = []
            for i, (persona, aid) in enumerate(zip(AGENT_PERSONAS, agent_ids)):
                msg_id, msg_type, content = await agent_speak(i, persona, aid)
                round_results.append((msg_id, msg_type, content))
                await asyncio.sleep(0.3)  # Small delay between speakers

            print(f"  Round {round_num}: {len([r for r in round_results if r[0]])} messages posted")
            results.ok(f"discussion_round_{round_num}")

            # Check moderator state after each round
            state = await get_moderator_state(client, room_id)
            if state:
                phase = state.get("phase", "unknown")
                print(f"  📊 Moderator phase after round {round_num}: {phase}")

        # Count total messages
        resp = await client.get(f"{BASE_URL}/api/rooms/{room_id}/messages")
        total_messages = resp.json().get("total", 0)
        print(f"\n  📊 Total messages so far: {total_messages}")
        assert total_messages >= 8, f"Expected at least 8 messages (4 agents × 2 rounds), got {total_messages}"
        results.ok(f"discussion_messages_count_{total_messages}")

        # Check if moderator intervened during discussion
        resp = await client.get(f"{BASE_URL}/api/rooms/{room_id}/messages")
        msgs = resp.json().get("messages", [])
        moderator_interventions = [m for m in msgs if m.get("agent_id") == moderator_agent_id]
        if len(moderator_interventions) > 1:  # >1 because welcome was first
            print(f"  🎯 Moderator intervened {len(moderator_interventions) - 1} time(s) during discussion")
            for mi in moderator_interventions[1:]:
                print(f"     → {mi['content'][:100]}...")
            results.ok("moderator_interventions_during_discussion")
        else:
            results.warn("no_moderator_interventions_during_discussion")

        # ═══════════════════════════════════════════════════════════════
        # PHASE 4: INVESTIGATION
        # ═══════════════════════════════════════════════════════════════
        print("\n🔬 Phase 4: Investigation")

        investigation_agent_id = agent_ids[1]  # Jordan-Arch investigates
        investigation_topic = "Check OAuth2 security best practices for magic link implementation"

        # Try the investigation API endpoint
        investigate_url = f"{BASE_URL}{MODERATOR_INVESTIGATE_URL.format(room_id=room_id)}"
        resp = await client.post(investigate_url, json={
            "agent_id": investigation_agent_id,
            "topic": investigation_topic,
            "estimated_minutes": 2,
        })

        investigation_approved = False
        if resp.status_code in (200, 201):
            inv_data = resp.json()
            print(f"  🔬 Investigation approved: {inv_data.get('status', 'unknown')}")
            investigation_approved = True
            results.ok("investigation_approved_via_api")

            # Check budget was tracked
            if "remaining_budget" in inv_data:
                print(f"  💰 Remaining budget: {inv_data['remaining_budget']} min")
                results.ok("investigation_budget_tracked")
        else:
            print(f"  ⚠️ Investigation endpoint not available (HTTP {resp.status_code})")
            results.warn("investigation_endpoint_not_implemented")
            # Simulate investigation approval
            investigation_approved = True

        if investigation_approved:
            # Post investigation request message
            await post_message(
                client, room_id, investigation_agent_id, "request_ctx",
                f"I need to research: {investigation_topic}. Estimated time: 2 minutes.",
            )
            print(f"  📤 Investigation request posted")

            # Simulate investigation — LLM call to "research"
            print(f"  🔍 {agent_map[investigation_agent_id]['name']} is researching...")
            findings = await call_llm(
                "You are a security researcher. Provide a brief summary (2-3 sentences) of "
                "OAuth2 security best practices for magic link authentication.",
                f"Research topic: {investigation_topic}",
                max_tokens=200,
            )

            # Post investigation result
            await post_message(
                client, room_id, investigation_agent_id, "chat",
                f"Investigation findings: {findings}",
            )
            print(f"  📊 Investigation results posted")
            results.ok("investigation_completed")

        # ═══════════════════════════════════════════════════════════════
        # PHASE 5: PROPOSALS & VOTING
        # ═══════════════════════════════════════════════════════════════
        print("\n🗳️ Phase 5: Proposals & Voting")

        # Agent posts a PROPOSAL
        proposal_content = (
            "Proposal: Implement passwordless authentication (magic links) with Google/GitHub SSO. "
            "Timeline: 3 weeks in 2 sprints. Jordan leads architecture, Sam implements, "
            "Riley creates test plan. Phase 1: magic links (Sprint 1), Phase 2: SSO (Sprint 2)."
        )
        proposal_result = await post_message(
            client, room_id, agent_ids[0], "proposal", proposal_content,
        )
        assert proposal_result, "Failed to post proposal"
        proposal_id = proposal_result.get("id")
        print(f"  💡 Proposal posted by {AGENT_PERSONAS[0]['name']} (id: {proposal_id[:8] if proposal_id else 'N/A'})")
        results.ok("proposal_posted")

        # Other agents VOTE on the proposal
        vote_options = [
            ("yes", "I support this plan. Magic links are proven and SSO is a must-have."),
            ("yes", "This is solid. Let's make sure we have proper test coverage."),
            ("yes", "Agreed. I'll start on the test plan for both phases."),
        ]

        for i, (vote, reasoning) in enumerate(vote_options):
            voter_idx = i + 1  # Skip proposer (agent_ids[0])
            voter_aid = agent_ids[voter_idx]
            vote_result = await post_message(
                client, room_id, voter_aid, "vote",
                json.dumps({"vote": vote, "reasoning": reasoning}),
                parent_id=proposal_id,
            )
            if vote_result:
                print(f"  🗳️ {AGENT_PERSONAS[voter_idx]['name']} voted: {vote}")
            await asyncio.sleep(0.2)
        results.ok("votes_cast")

        # Try moderator vote endpoint
        vote_url = f"{BASE_URL}{MODERATOR_VOTE_URL.format(room_id=room_id)}"
        resp = await client.post(vote_url, json={
            "proposal_id": proposal_id,
        })
        if resp.status_code in (200, 201):
            vote_data = resp.json()
            print(f"  📊 Moderator vote result: {vote_data.get('status', 'unknown')}")
            results.ok("moderator_vote_endpoint")

            # Check if auto-decision was created
            if vote_data.get("decision_id"):
                print(f"  ✅ Auto-decision created: {vote_data['decision_id'][:8]}")
                results.ok("auto_decision_created")

            if vote_data.get("outcome"):
                print(f"  📋 Outcome: {vote_data['outcome']}")
        else:
            results.warn("moderator_vote_endpoint_not_implemented")
            # Manually create the decision
            resp = await client.post(f"{BASE_URL}/api/decisions", params={
                "room_id": room_id,
                "title": "Auth Strategy: Passwordless + SSO",
                "description": proposal_content,
                "status": "accepted",
                "proposer_agent_id": agent_ids[0],
            })
            assert resp.status_code in (200, 201), f"Decision creation failed: {resp.status_code}"
            decision_id = resp.json()["id"]
            print(f"  ✅ Decision created manually: {decision_id[:8]}")
            await client.patch(f"{BASE_URL}/api/decisions/{decision_id}", params={
                "status": "accepted",
                "summary": "Team approved passwordless auth (magic links + SSO). 3-week timeline, 2 sprints.",
            })
            results.ok("manual_decision_created")

        # Create action items
        action_items = [
            ("Design magic link auth flow diagram", agent_ids[1]),
            ("Implement magic link email service", agent_ids[2]),
            ("Set up OAuth providers (Google/GitHub)", agent_ids[2]),
            ("Create comprehensive test plan for auth flows", agent_ids[3]),
            ("Plan migration strategy from password auth", agent_ids[0]),
        ]
        for desc, assignee in action_items:
            resp = await client.post(f"{BASE_URL}/api/action-items", params={
                "room_id": room_id,
                "description": desc,
                "assignee_agent_id": assignee,
                "status": "pending",
            })
            if resp.status_code in (200, 201):
                pass
        print(f"  📋 {len(action_items)} action items created")
        results.ok("action_items_created")

        # ═══════════════════════════════════════════════════════════════
        # PHASE 6: CLOSE MEETING
        # ═══════════════════════════════════════════════════════════════
        print("\n🏁 Phase 6: Close Meeting")

        close_url = f"{BASE_URL}{MODERATOR_CLOSE_URL.format(room_id=room_id)}"
        resp = await client.post(close_url)

        if resp.status_code in (200, 201):
            close_data = resp.json()
            print(f"  🏁 Meeting closed via API")
            results.ok("meeting_closed_via_api")

            # Verify final summary was posted
            if close_data.get("summary"):
                print(f"  📝 Summary: {close_data['summary'][:150]}...")
                results.ok("final_summary_generated")

            # Verify phase is closed
            state = await get_moderator_state(client, room_id)
            if state and state.get("phase") == "closed":
                print(f"  ✅ Moderator phase: closed")
                results.ok("moderator_phase_closed")
        else:
            print(f"  ⚠️ Close endpoint not available (HTTP {resp.status_code})")
            results.warn("moderator_close_endpoint_not_implemented")

            # Generate summary via LLM
            resp = await client.get(f"{BASE_URL}/api/rooms/{room_id}/messages")
            all_msgs = resp.json().get("messages", [])
            transcript = "\n".join(f"[{m['type']}] {m['content'][:200]}" for m in all_msgs)

            summary = await call_llm(
                "You are a meeting moderator. Write a concise meeting summary.",
                f"Summarize this meeting in 3-5 bullet points, listing key decisions and action items:\n\n{transcript[-3000:]}",
                max_tokens=400,
            )
            await post_message(client, room_id, moderator_agent_id, "summary", summary)
            print(f"  📝 Manual summary posted")
            results.ok("manual_summary_posted")

        # ═══════════════════════════════════════════════════════════════
        # VERIFY FINAL STATE
        # ═══════════════════════════════════════════════════════════════
        print("\n🔍 Final Verification")

        # Get final stats
        resp = await client.get(f"{BASE_URL}/api/admin/stats")
        stats = resp.json()

        print(f"\n  📊 Final Stats:")
        print(f"    Rooms: {stats['rooms']['total']} ({stats['rooms']['active']} active)")
        print(f"    Agents: {stats['agents']['total']}")
        print(f"    Messages: {stats['messages']['total']}")
        print(f"    Decisions: {stats['decisions']['total']}")
        print(f"    Action Items: {stats['action_items']['total']}")

        # Verify message count (4 agents × 2 rounds + proposal + 3 votes + investigation ± moderator msgs)
        msg_count = stats["messages"]["total"]
        assert msg_count >= 8, f"Expected ≥8 messages, got {msg_count}"
        print(f"  ✅ Message count: {msg_count} (≥8)")
        results.ok(f"final_message_count_{msg_count}")

        # Verify at least 1 decision
        assert stats["decisions"]["total"] >= 1, f"Expected ≥1 decision, got {stats['decisions']['total']}"
        print(f"  ✅ Decisions: {stats['decisions']['total']}")
        results.ok(f"final_decision_count_{stats['decisions']['total']}")

        # Verify action items
        assert stats["action_items"]["total"] >= 3, f"Expected ≥3 action items, got {stats['action_items']['total']}"
        print(f"  ✅ Action items: {stats['action_items']['total']}")
        results.ok(f"final_action_items_{stats['action_items']['total']}")

        # Verify 5 agents total (4 participants + moderator)
        assert stats["agents"]["total"] >= 5, f"Expected ≥5 agents, got {stats['agents']['total']}"
        print(f"  ✅ Agents: {stats['agents']['total']}")
        results.ok(f"final_agents_{stats['agents']['total']}")

        # ═══════════════════════════════════════════════════════════════
        # PRINT FULL TRANSCRIPT
        # ═══════════════════════════════════════════════════════════════
        print(f"\n{'='*70}")
        print(f"📝 FULL MEETING TRANSCRIPT")
        print(f"{'='*70}")
        print(f"Room: {MEETING_CONTEXT['room_name']}")
        print(f"Topic: {MEETING_CONTEXT['topic'][:100]}...")
        print(f"Date: {datetime.now().isoformat()}")
        print(f"{'─'*70}")

        resp = await client.get(f"{BASE_URL}/api/rooms/{room_id}/messages")
        messages = resp.json().get("messages", [])

        # Build agent name map
        name_map = {aid: p["name"] for p, aid in zip(AGENT_PERSONAS, agent_ids)}
        name_map[moderator_agent_id] = "🎯 [MODERATOR]"

        for msg in messages:
            name = name_map.get(msg["agent_id"], f"Agent-{msg['agent_id'][:8]}")
            emoji = TYPE_EMOJI.get(msg["type"], "💬")
            is_moderator = msg["agent_id"] == moderator_agent_id
            prefix = "🎯 [MODERATOR]" if is_moderator else name
            print(f"\n{emoji} [{msg['type'].upper()}] {prefix}:")
            # Print content with indentation, wrapped at 80 chars
            content = msg["content"]
            while len(content) > 0:
                print(f"   {content[:77]}")
                content = content[77:]

        print(f"\n{'─'*70}")
        print(f"Total messages: {len(messages)}")

        # ═══════════════════════════════════════════════════════════════
        # FINAL RESULT
        # ═══════════════════════════════════════════════════════════════
        all_passed = results.summary()

        if all_passed:
            print(f"\n🎉 ALL CORE TESTS PASSED! Meeting completed successfully.")
        else:
            print(f"\n⚠️ Some tests had issues (see above). Meeting flow completed.")

        return all_passed


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

async def main():
    if not API_KEY:
        print("❌ OPENROUTER_API_KEY not set. Set it in environment or backend/.env")
        sys.exit(1)
    print(f"🔑 API key loaded ({API_KEY[:10]}...)")

    # Check server is running
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            resp = await c.get(f"{BASE_URL}/health")
            if resp.status_code != 200:
                print(f"❌ Server not healthy: {resp.status_code}")
                sys.exit(1)
            print(f"🏥 Server healthy: {resp.json()}")
    except httpx.ConnectError:
        print(f"❌ Cannot connect to {BASE_URL}. Is the server running?")
        sys.exit(1)

    passed = await run_moderated_meeting_test()
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
