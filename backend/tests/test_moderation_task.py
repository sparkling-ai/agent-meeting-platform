"""Tests for predefined moderation task endpoint — unit tests with mocked DB."""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.database import get_db


EXPECTED_OUTPUTS = {
    "topic_review": "Structured summary of key discussion points and recommendations",
    "consensus_vote": "Tally of votes with final consensus decision",
    "risk_assessment": "Identified risks with severity ratings and mitigation suggestions",
}


@pytest.fixture(autouse=True)
def _override_lifespan():
    @asynccontextmanager
    async def _noop(app_instance):
        yield

    original = app.router.lifespan_context
    app.router.lifespan_context = _noop
    yield
    app.router.lifespan_context = original


@pytest.fixture()
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture(autouse=True)
def _mock_db(mock_session):
    async def _get_mock_db():
        yield mock_session

    app.dependency_overrides[get_db] = _get_mock_db
    yield
    app.dependency_overrides.clear()


def _simulate_add(obj):
    """Simulate DB assigning values on the task object."""
    obj.id = uuid.uuid4()
    obj.status = "pending"
    obj.expected_output = EXPECTED_OUTPUTS.get(obj.task_type, "")
    obj.created_at = datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_create_topic_review_task(mock_session):
    mock_session.add = _simulate_add

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/moderation/predefined_task",
            json={"task_type": "topic_review", "topic": "Q4 roadmap"},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["task_type"] == "topic_review"
    assert data["topic"] == "Q4 roadmap"
    assert data["status"] == "pending"
    assert "Structured summary" in data["expected_output"]


@pytest.mark.asyncio
async def test_create_consensus_vote_task(mock_session):
    mock_session.add = _simulate_add

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/moderation/predefined_task",
            json={"task_type": "consensus_vote", "topic": "Adopt framework X"},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["task_type"] == "consensus_vote"
    assert "Tally of votes" in data["expected_output"]


@pytest.mark.asyncio
async def test_create_risk_assessment_task(mock_session):
    mock_session.add = _simulate_add

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/moderation/predefined_task",
            json={"task_type": "risk_assessment", "topic": "Migration to cloud"},
        )

    assert resp.status_code == 201
    assert "Identified risks" in resp.json()["expected_output"]


@pytest.mark.asyncio
async def test_create_task_with_description(mock_session):
    mock_session.add = _simulate_add

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/moderation/predefined_task",
            json={
                "task_type": "topic_review",
                "topic": "Sprint planning",
                "description": "Review sprint backlog items",
            },
        )

    assert resp.status_code == 201
    assert resp.json()["description"] == "Review sprint backlog items"


@pytest.mark.asyncio
async def test_create_task_invalid_type():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/moderation/predefined_task",
            json={"task_type": "invalid_type", "topic": "Something"},
        )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_task_missing_topic():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/moderation/predefined_task",
            json={"task_type": "topic_review"},
        )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_task_empty_topic():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/moderation/predefined_task",
            json={"task_type": "topic_review", "topic": ""},
        )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_task_not_found(mock_session):
    mock_session.get = AsyncMock(return_value=None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/moderation/predefined_task/{uuid.uuid4()}")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_task_found(mock_session):
    task = MagicMock()
    task.id = uuid.uuid4()
    task.task_type = "topic_review"
    task.topic = "Q4 roadmap"
    task.description = None
    task.status = "pending"
    task.expected_output = EXPECTED_OUTPUTS["topic_review"]
    task.created_at = datetime.now(timezone.utc)

    mock_session.get = AsyncMock(return_value=task)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/moderation/predefined_task/{task.id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["task_type"] == "topic_review"
    assert data["topic"] == "Q4 roadmap"
