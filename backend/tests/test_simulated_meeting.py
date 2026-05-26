#!/usr/bin/env python3
"""
Simulated meeting with LLM-powered agents. Optimized for speed.
"""

import asyncio
import httpx
import json
import os
import sys

BASE_URL = "http://localhost:8000"
API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

if not API_KEY:
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("OPENROUTER_API_KEY="):
                    API_KEY = line.strip().split("=", 1)[1].strip().strip('"')

AGENT_PERSONAS = [
    {"name": "Sarah-PM", "role": "Product Manager", "style": "Focus on user value, data-driven, prioritizes ruthlessly"},
    {"name": "Marcus-Arch", "role": "Lead Architect", "style": "Cautious, thinks about edge cases, scalability, tech debt"},
    {"name": "Aisha-Dev", "role": "Senior Developer", "style": "Practical, hates over-engineering, wants concrete specs"},
    {"name": "Chen-QA", "role": "QA Lead", "style": "Thinks about failure modes, testability, quality metrics"},
    {"name": "Luna-UX", "role": "UX Designer", "style": "Advocates for simplicity, questions complexity from user perspective"},
]

MEETING_TOPIC = {
    "room_name": "Sprint Planning - Auth Overhaul",
    "topic": "Redesign authentication: implement passwordless (magic links) + SSO (Google/GitHub). Current issues: password resets = 30% of support tickets, no SSO. Timeline: 3 weeks. Discuss feasibility, risks, and plan.",
}


async def call_llm(system: str, user: str) -> str:
    """Quick LLM call via OpenRouter."""
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
                "max_tokens": 200,
            },
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        return f"[LLM error: {resp.status_code}]"


def parse_response(raw: str, fallback_name: str) -> tuple[str, str]:
    """Parse agent response, extract type and content."""
    text = raw.strip()
    # Try JSON
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    try:
        parsed = json.loads(text)
        return parsed.get("type", "chat"), parsed.get("content", text)
    except (json.JSONDecodeError, AttributeError):
        # Try to extract type from text
        for t in ["question", "proposal", "objection", "risk", "vote", "summary", "chat"]:
            if t in text.lower()[:30]:
                return t, text
        return "chat", text


async def run_meeting():
    """Run a full simulated meeting."""
    async with httpx.AsyncClient(timeout=30) as client:
        print("=" * 70)
        print(f"📋 {MEETING_TOPIC['room_name']}")
        print(f"📌 {MEETING_TOPIC['topic'][:80]}...")
        print("=" * 70)

        # Reset
        await client.post(f"{BASE_URL}/api/admin/reset-dev")
        print("\n🧹 Reset dev data")

        # Register agents
        print("\n1️⃣  Registering agents...")
        agent_ids = []
        for p in AGENT_PERSONAS:
            resp = await client.post(f"{BASE_URL}/api/agents", json={
                "name": p["name"],
                "connector_type": "rest",
                "capabilities": {"role": p["role"], "style": p["style"]},
            })
            agent_ids.append(resp.json()["id"])
            print(f"  ✅ {p['name']}")

        # Create room
        resp = await client.post(f"{BASE_URL}/api/rooms", json={
            "name": MEETING_TOPIC["room_name"],
            "topic": MEETING_TOPIC["topic"],
        })
        room_id = resp.json()["id"]
        print(f"\n2️⃣  Room created: {room_id[:8]}")

        # Bulk join
        await client.post(f"{BASE_URL}/api/admin/rooms/{room_id}/bulk-join?role=participant", json=agent_ids)
        await client.patch(f"{BASE_URL}/api/rooms/{room_id}/status", json={"status": "active"})
        print(f"  ✅ 5 agents joined, room active")

        # Discussion — 2 rounds of 5 agents = 10 messages
        print(f"\n3️⃣  Starting discussion (2 rounds, 5 agents)...")

        conversation = [f"TOPIC: {MEETING_TOPIC['topic']}"]
        type_emoji = {
            "chat": "💬", "question": "❓", "proposal": "💡", "objection": "🚫",
            "risk": "⚠️", "decision": "✅", "action_item": "📋", "vote": "🗳️",
            "summary": "📝", "request_ctx": "🔍",
        }

        for round_num in range(1, 3):
            print(f"\n  --- Round {round_num}/2 ---")
            phase = "opening" if round_num == 1 else "wrap-up"

            # All agents think in parallel
            async def agent_speak(idx, persona, agent_id):
                system = (
                    f"You are {persona['name']}, the {persona['role']}. "
                    f"Style: {persona['style']}. "
                    f"Respond with JSON: {{\"type\": \"chat|question|proposal|objection|risk|vote|summary\", \"content\": \"your 1-3 sentence response\"}}"
                )
                user_msg = (
                    f"Meeting phase: {phase}\n"
                    f"Discussion so far:\n" + "\n".join(conversation[-6:]) +
                    f"\n\nYour response as {persona['name']} (JSON only):"
                )
                print(f"  🤔 {persona['name']}...", end=" ", flush=True)
                raw = await call_llm(system, user_msg)
                msg_type, content = parse_response(raw, persona["name"])

                resp = await client.post(f"{BASE_URL}/api/rooms/{room_id}/messages", json={
                    "agent_id": agent_id,
                    "type": msg_type,
                    "content": content[:500],
                })

                if resp.status_code == 201:
                    conversation.append(f"[{persona['name']}]({msg_type}): {content[:200]}")
                    emoji = type_emoji.get(msg_type, "💬")
                    print(f"{emoji} {msg_type}")
                else:
                    print(f"❌ {resp.status_code}")
                return msg_type, content

            await asyncio.gather(*[
                agent_speak(i, p, aid)
                for i, (p, aid) in enumerate(zip(AGENT_PERSONAS, agent_ids))
            ])
            await asyncio.sleep(0.2)

        # Decisions
        print(f"\n4️⃣  Creating decisions...")
        resp = await client.post(f"{BASE_URL}/api/decisions", params={
            "room_id": room_id,
            "title": "Proceed with passwordless auth + SSO",
            "description": "Implement magic link auth + Google/GitHub SSO over 3 weeks",
            "status": "proposed",
            "proposer_agent_id": agent_ids[0],
        })
        decision_id = resp.json()["id"]
        print(f"  ✅ Decision proposed: {decision_id[:8]}")

        await client.patch(f"{BASE_URL}/api/decisions/{decision_id}", params={
            "status": "accepted",
            "summary": "Team agreed: passwordless + SSO. Marcus to design, Aisha to implement, Chen to plan testing.",
        })
        print(f"  ✅ Decision accepted")

        # Action items
        print(f"\n5️⃣  Action items...")
        items = [
            ("Design auth flow diagram", agent_ids[1], "pending"),
            ("Implement magic link service", agent_ids[2], "pending"),
            ("Set up OAuth providers (Google/GitHub)", agent_ids[2], "pending"),
            ("Create test plan for auth flows", agent_ids[3], "pending"),
            ("Design passwordless UX flow", agent_ids[4], "in_progress"),
        ]
        for desc, assignee, status in items:
            await client.post(f"{BASE_URL}/api/action-items", params={
                "room_id": room_id,
                "description": desc,
                "assignee_agent_id": assignee,
                "status": status,
            })
            print(f"  ✅ {desc}")

        # Print transcript
        print(f"\n{'='*70}")
        print(f"📝 MEETING TRANSCRIPT")
        print(f"{'='*70}")

        resp = await client.get(f"{BASE_URL}/api/rooms/{room_id}/messages")
        agent_map = {aid: p["name"] for p, aid in zip(AGENT_PERSONAS, agent_ids)}
        for msg in resp.json()["messages"]:
            name = agent_map.get(msg["agent_id"], "Unknown")
            emoji = type_emoji.get(msg["type"], "💬")
            print(f"\n{emoji} [{msg['type'].upper()}] {name}:")
            print(f"   {msg['content'][:300]}")

        # Final stats
        print(f"\n{'='*70}")
        print(f"📊 FINAL STATS")
        print(f"{'='*70}")
        resp = await client.get(f"{BASE_URL}/api/admin/stats")
        stats = resp.json()
        print(f"  Rooms: {stats['rooms']['total']} ({stats['rooms']['active']} active)")
        print(f"  Agents: {stats['agents']['total']}")
        print(f"  Messages: {stats['messages']['total']}")
        print(f"  Decisions: {stats['decisions']['total']}")
        print(f"  Action Items: {stats['action_items']['total']} ({stats['action_items']['pending']} pending)")

        # Verify counts
        msg_count = stats["messages"]["total"]
        assert msg_count == 10, f"Expected 10 messages, got {msg_count}"
        assert stats["decisions"]["total"] == 1
        assert stats["action_items"]["total"] == 5
        assert stats["agents"]["total"] == 5
        assert stats["rooms"]["active"] == 1

        # Test additional queries
        print(f"\n🧪 Additional API tests...")

        # Filter messages by type
        resp = await client.get(f"{BASE_URL}/api/rooms/{room_id}/messages", params={"type": "proposal"})
        print(f"  ✅ Proposals: {resp.json()['total']}")
        resp = await client.get(f"{BASE_URL}/api/rooms/{room_id}/messages", params={"type": "question"})
        print(f"  ✅ Questions: {resp.json()['total']}")
        resp = await client.get(f"{BASE_URL}/api/rooms/{room_id}/messages", params={"type": "risk"})
        print(f"  ✅ Risks: {resp.json()['total']}")

        # Get decision detail with action items
        resp = await client.get(f"{BASE_URL}/api/decisions/{decision_id}")
        dec_detail = resp.json()
        print(f"  ✅ Decision detail: {dec_detail['title']} ({dec_detail['status']})")
        print(f"     Action items linked: {len(dec_detail.get('action_items', []))}")

        # Action items by assignee
        resp = await client.get(f"{BASE_URL}/api/action-items", params={"assignee_agent_id": agent_ids[2]})
        print(f"  ✅ Aisha's action items: {resp.json()['total']}")

        # Update action item
        all_items = (await client.get(f"{BASE_URL}/api/action-items")).json()["action_items"]
        if all_items:
            await client.patch(f"{BASE_URL}/api/action-items/{all_items[0]['id']}", params={"status": "done"})
            print(f"  ✅ Updated first action item → done")

        # Agent token
        resp = await client.post(f"{BASE_URL}/api/agents/{agent_ids[0]}/token")
        print(f"  ✅ Token for Sarah: {resp.json()['token'][:15]}...")

        # Recent activity
        print(f"\n📋 Recent activity:")
        for rm in stats["recent_messages"][:5]:
            print(f"  [{rm['type']}] {rm['agent_name']}: {rm['content'][:60]}...")

        print(f"\n{'='*70}")
        print(f"✅ ALL TESTS PASSED! {msg_count} messages, 1 decision, 5 action items")
        print(f"{'='*70}")


if __name__ == "__main__":
    if not API_KEY:
        print("❌ OPENROUTER_API_KEY not set")
        sys.exit(1)
    print(f"🔑 API key loaded")
    asyncio.run(run_meeting())
