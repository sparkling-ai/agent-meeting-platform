"""Integration test: predefined moderation task flow against real PostgreSQL.

Covers the full guaranteed-successful user flow:
  1. Register agents, create room, agents join
  2. Agents post discussion messages and votes
  3. User creates a moderation task (consensus_vote) via the API
  4. Backend executes the task against the room's messages
  5. Verify status transitions, result structure, and listing
"""

import json

import pytest
from httpx import AsyncClient


async def _seed_room_with_votes(client: AsyncClient) -> dict:
    """Create agents, a room, and vote messages. Returns {room_id, agent_ids}."""
    agents = []
    for name in ["Alice (Strategist)", "Bob (Engineer)", "Carol (Risk Analyst)"]:
        resp = await client.post("/api/agents", json={
            "name": name,
            "connector_type": "rest",
            "capabilities": {"role": name},
        })
        assert resp.status_code == 201
        agents.append(resp.json())

    resp = await client.post("/api/rooms", json={
        "name": "Q3 Tech Stack Decision",
        "topic": "Should we adopt framework X?",
    })
    assert resp.status_code == 201
    room_id = resp.json()["id"]

    for agent in agents:
        resp = await client.post(f"/api/rooms/{room_id}/join", json={"agent_id": agent["id"]})
        assert resp.status_code == 200

    # Discussion messages
    for agent, msg in [
        (agents[0], "I propose we adopt framework X for all new services."),
        (agents[1], "The migration path looks solid, I'm in favor."),
        (agents[2], "Works for me, let's do it."),
    ]:
        resp = await client.post(f"/api/rooms/{room_id}/messages", json={
            "agent_id": agent["id"],
            "type": "chat",
            "content": msg,
        })
        assert resp.status_code == 201

    # Vote messages — 2 yes, 1 no
    for agent, vote in [(agents[0], "yes"), (agents[1], "yes"), (agents[2], "no")]:
        resp = await client.post(f"/api/rooms/{room_id}/messages", json={
            "agent_id": agent["id"],
            "type": "vote",
            "content": f"My vote is {vote}",
        })
        assert resp.status_code == 201

    return {"room_id": room_id, "agents": agents}


@pytest.mark.asyncio
async def test_consensus_vote_full_flow(client: AsyncClient):
    """End-to-end: create task → execute → verify result and listing."""
    seed = await _seed_room_with_votes(client)
    room_id = seed["room_id"]

    # 1. Create a consensus_vote moderation task
    resp = await client.post("/api/moderation/predefined_task", json={
        "task_type": "consensus_vote",
        "topic": "Should we adopt framework X?",
        "description": "Vote on adopting framework X for new services",
        "room_id": room_id,
    })
    assert resp.status_code == 201
    task = resp.json()
    task_id = task["id"]

    assert task["task_type"] == "consensus_vote"
    assert task["status"] == "pending"
    assert task["room_id"] == room_id
    assert "Tally of votes" in task["expected_output"]
    assert task["result"] is None

    # 2. Execute the task
    resp = await client.post(f"/api/moderation/predefined_task/{task_id}/execute")
    assert resp.status_code == 200, f"Execute failed: {resp.text}"
    completed = resp.json()

    assert completed["status"] == "completed"
    assert completed["id"] == task_id
    assert completed["room_id"] == room_id

    # 3. Parse and verify the result payload
    result = json.loads(completed["result"])
    assert result["topic"] == "Should we adopt framework X?"
    assert result["votes_for"] == 2
    assert result["votes_against"] == 1
    assert result["votes_unknown"] == 0
    assert result["total_votes"] == 3
    assert result["consensus_reached"] is True
    assert result["decision"] == "accepted"

    # 4. Fetch by ID — should reflect completed state
    resp = await client.get(f"/api/moderation/predefined_task/{task_id}")
    assert resp.status_code == 200
    fetched = resp.json()
    assert fetched["status"] == "completed"
    assert json.loads(fetched["result"])["decision"] == "accepted"

    # 5. List tasks — should include our completed task
    resp = await client.get("/api/moderation/predefined_task")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    ids = [t["id"] for t in body["tasks"]]
    assert task_id in ids

    # 6. Filter by task_type
    resp = await client.get("/api/moderation/predefined_task", params={"task_type": "consensus_vote"})
    assert resp.status_code == 200
    assert all(t["task_type"] == "consensus_vote" for t in resp.json()["tasks"])


@pytest.mark.asyncio
async def test_execute_with_explicit_room_id(client: AsyncClient):
    """Task created without room_id can be executed by passing room_id in the execute request."""
    seed = await _seed_room_with_votes(client)
    room_id = seed["room_id"]

    resp = await client.post("/api/moderation/predefined_task", json={
        "task_type": "consensus_vote",
        "topic": "Explicit room test",
    })
    assert resp.status_code == 201
    task = resp.json()
    assert task["room_id"] is None

    resp = await client.post(
        f"/api/moderation/predefined_task/{task['id']}/execute",
        json={"room_id": room_id},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    result = json.loads(resp.json()["result"])
    assert result["votes_for"] == 2
    assert result["votes_against"] == 1


@pytest.mark.asyncio
async def test_execute_task_not_found(client: AsyncClient):
    """Executing a non-existent task returns 404."""
    resp = await client.post("/api/moderation/predefined_task/00000000-0000-0000-0000-000000000000/execute")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_execute_already_completed(client: AsyncClient):
    """Re-executing a completed task returns 400."""
    seed = await _seed_room_with_votes(client)

    resp = await client.post("/api/moderation/predefined_task", json={
        "task_type": "consensus_vote",
        "topic": "Double execute test",
        "room_id": seed["room_id"],
    })
    task_id = resp.json()["id"]

    resp = await client.post(f"/api/moderation/predefined_task/{task_id}/execute")
    assert resp.status_code == 200

    resp = await client.post(f"/api/moderation/predefined_task/{task_id}/execute")
    assert resp.status_code == 400
    assert "already completed" in resp.json()["detail"]
