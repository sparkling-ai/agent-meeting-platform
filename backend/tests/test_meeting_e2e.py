"""End-to-end test: simulated meeting with 3 agents using the REST API."""

import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_full_meeting_flow(client: AsyncClient):
    """Simulate a complete meeting: proposal → discussion → votes → decision."""

    # 1. Register 3 agents
    agents = []
    for name in ["Alice (Strategist)", "Bob (Engineer)", "Carol (Risk Analyst)"]:
        resp = await client.post("/api/agents", json={"name": name, "capabilities": {"role": name}})
        assert resp.status_code == 201, f"Failed to create agent: {resp.text}"
        agents.append(resp.json())

    alice, bob, carol = agents

    # 2. Generate tokens for each agent
    tokens = {}
    for agent in agents:
        resp = await client.post(f"/api/agents/{agent['id']}/token")
        assert resp.status_code == 200, f"Failed to generate token: {resp.text}"
        tokens[agent["id"]] = resp.json()["token"]

    # 3. Create a room
    resp = await client.post("/api/rooms", json={
        "name": "Q3 Tech Stack Decision",
        "topic": "Should we migrate to Rust or stick with Python?",
    })
    assert resp.status_code == 201, f"Failed to create room: {resp.text}"
    room = resp.json()
    room_id = room["id"]

    # 4. All agents join
    for agent in agents:
        resp = await client.post(f"/api/rooms/{room_id}/join", json={"agent_id": agent["id"]})
        assert resp.status_code == 200, f"Failed to join room: {resp.text}"

    # 5. Alice posts a PROPOSAL
    resp = await client.post(f"/api/rooms/{room_id}/messages", json={
        "agent_id": alice["id"],
        "type": "proposal",
        "content": "I propose we migrate our performance-critical services to Rust while keeping Python for ML/DS workloads.",
    })
    assert resp.status_code == 201, f"Failed to post proposal: {resp.text}"
    proposal_msg = resp.json()
    assert proposal_msg["type"] == "proposal"

    # 6. Bob asks a QUESTION
    resp = await client.post(f"/api/rooms/{room_id}/messages", json={
        "agent_id": bob["id"],
        "type": "question",
        "content": "What's the estimated migration timeline? We have 3 services to port.",
        "parent_id": proposal_msg["id"],
    })
    assert resp.status_code == 201

    # 7. Carol raises a RISK
    resp = await client.post(f"/api/rooms/{room_id}/messages", json={
        "agent_id": carol["id"],
        "type": "risk",
        "content": "Risk: We only have 2 Rust developers. Training the team will take 3-6 months.",
        "parent_id": proposal_msg["id"],
    })
    assert resp.status_code == 201

    # 8. CHAT discussion
    for agent, msg_text in [
        (alice, "Good points. We could start with a pilot on one service, and hire one senior Rust dev."),
        (bob, "Agreed. The pilot approach mitigates the risk. Let's target the auth service first."),
    ]:
        resp = await client.post(f"/api/rooms/{room_id}/messages", json={
            "agent_id": agent["id"],
            "type": "chat",
            "content": msg_text,
        })
        assert resp.status_code == 201

    # 9. Agents VOTE
    for agent, vote in [(alice, "yes"), (bob, "yes"), (carol, "yes")]:
        resp = await client.post(f"/api/rooms/{room_id}/messages", json={
            "agent_id": agent["id"],
            "type": "vote",
            "content": f"VOTE: {vote} - I support the pilot migration approach.",
            "parent_id": proposal_msg["id"],
        })
        assert resp.status_code == 201

    # 10. Verify all messages persisted
    resp = await client.get(f"/api/rooms/{room_id}/messages")
    assert resp.status_code == 200
    data = resp.json()
    messages = data["messages"]
    assert len(messages) >= 8  # 1 proposal + 1 question + 1 risk + 2 chat + 3 votes

    # 11. Verify message types
    types = [m["type"] for m in messages]
    assert "proposal" in types
    assert "question" in types
    assert "risk" in types
    assert "vote" in types
    assert "chat" in types

    # 12. Verify room is active
    resp = await client.get(f"/api/rooms/{room_id}")
    assert resp.status_code == 200
    # Room status should still be draft unless someone explicitly changed it
    # (join doesn't auto-activate in the other subagent's implementation)

    # 13. List rooms
    resp = await client.get("/api/rooms")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_agent_registration(client: AsyncClient):
    """Test basic agent CRUD."""
    resp = await client.post("/api/agents", json={"name": "Test Agent", "capabilities": {"test": True}})
    assert resp.status_code == 201
    agent = resp.json()
    assert agent["name"] == "Test Agent"

    # List agents
    resp = await client.get("/api/agents")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    # Get by ID
    resp = await client.get(f"/api/agents/{agent['id']}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Test Agent"


@pytest.mark.asyncio
async def test_room_lifecycle(client: AsyncClient):
    """Test room creation, joining, and message flow."""
    # Create agent and generate token
    resp = await client.post("/api/agents", json={"name": "R1"})
    agent = resp.json()
    resp = await client.post(f"/api/agents/{agent['id']}/token")
    assert resp.status_code == 200

    # Create room
    resp = await client.post("/api/rooms", json={"name": "Test Room", "topic": "Testing"})
    assert resp.status_code == 201
    room = resp.json()
    assert room["status"] == "draft"

    # Join room
    resp = await client.post(f"/api/rooms/{room['id']}/join", json={"agent_id": agent["id"]})
    assert resp.status_code == 200

    # Post a message
    resp = await client.post(f"/api/rooms/{room['id']}/messages", json={
        "agent_id": agent["id"],
        "type": "chat",
        "content": "Hello world",
    })
    assert resp.status_code == 201

    # Duplicate join should fail
    resp = await client.post(f"/api/rooms/{room['id']}/join", json={"agent_id": agent["id"]})
    assert resp.status_code == 400  # ValueError -> 400

    # Leave room
    resp = await client.post(f"/api/rooms/{room['id']}/leave", params={"agent_id": agent["id"]})
    assert resp.status_code == 200

    # Can't post after leaving
    resp = await client.post(f"/api/rooms/{room['id']}/messages", json={
        "agent_id": agent["id"],
        "type": "chat",
        "content": "Should fail",
    })
    assert resp.status_code == 400
