"""Test agent CRUD — unit tests with mocked database."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _make_agent(
    name="TestAgent",
    connector_type="rest",
    capabilities=None,
    agent_id=None,
):
    """Create a mock Agent object that supports from_attributes."""
    a = MagicMock()
    a.id = agent_id or uuid.uuid4()
    a.name = name
    a.connector_type = connector_type
    a.capabilities = capabilities
    a.created_at = "2025-01-01T00:00:00Z"
    return a


@pytest.fixture(autouse=True)
def _override_lifespan():
    """Skip DB-dependent lifespan (schema creation)."""
    from contextlib import asynccontextmanager
    from fastapi import FastAPI

    @asynccontextmanager
    async def _noop(app: FastAPI):
        yield

    original = app.router.lifespan_context
    app.router.lifespan_context = _noop
    yield
    app.router.lifespan_context = original


@pytest.fixture(autouse=True)
def _mock_db():
    """Override get_db with a mock session for all agent tests."""
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.flush = AsyncMock()

    async def _get_mock_db():
        yield mock_session

    from app.database import get_db
    app.dependency_overrides[get_db] = _get_mock_db
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_register_agent():
    agent = _make_agent(name="BotMcBotface")
    with patch("app.services.agent_service.register_agent", new_callable=AsyncMock, return_value=agent):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/agents", json={"name": "BotMcBotface", "connector_type": "rest"})

    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "BotMcBotface"
    assert data["connector_type"] == "rest"


@pytest.mark.asyncio
async def test_list_agents():
    agents = [_make_agent(name="A1"), _make_agent(name="A2")]
    with patch("app.services.agent_service.list_agents", new_callable=AsyncMock, return_value=agents):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/agents")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["name"] == "A1"


@pytest.mark.asyncio
async def test_get_agent():
    aid = uuid.uuid4()
    agent = _make_agent(name="Solo", agent_id=aid)
    with patch("app.services.agent_service.get_agent", new_callable=AsyncMock, return_value=agent):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/agents/{aid}")

    assert resp.status_code == 200
    assert resp.json()["name"] == "Solo"


@pytest.mark.asyncio
async def test_get_agent_not_found():
    with patch("app.services.agent_service.get_agent", new_callable=AsyncMock, return_value=None):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/agents/{uuid.uuid4()}")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_generate_agent_token():
    aid = uuid.uuid4()
    token = "tok_abc123"
    with patch("app.services.agent_service.generate_agent_token", new_callable=AsyncMock, return_value=(aid, token)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"/api/agents/{aid}/token")

    assert resp.status_code == 200
    data = resp.json()
    assert data["token"] == token
