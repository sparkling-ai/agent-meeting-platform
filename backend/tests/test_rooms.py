"""Test room creation — unit tests with mocked database."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _make_room(name="Test Room", status="draft", room_id=None):
    """Create a mock Room object."""
    r = MagicMock()
    r.id = room_id or uuid.uuid4()
    r.name = name
    r.topic = f"Topic for {name}"
    r.status = status
    r.visibility = "unlisted"
    r.max_participants = 20
    r.settings = None
    r.created_by = None
    r.owner_id = None
    r.created_at = "2025-01-01T00:00:00Z"
    r.updated_at = "2025-01-01T00:00:00Z"
    r.members = []
    return r


@pytest.fixture(autouse=True)
def _override_lifespan():
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
async def test_create_room():
    room = _make_room(name="War Room")
    with patch("app.services.room_service.create_room", new_callable=AsyncMock, return_value=room):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/rooms", json={"name": "War Room"})

    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "War Room"


@pytest.mark.asyncio
async def test_list_rooms():
    rooms = [_make_room(name="R1"), _make_room(name="R2")]
    with patch("app.services.room_service.list_rooms", new_callable=AsyncMock, return_value=rooms):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/rooms")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


@pytest.mark.asyncio
async def test_get_room_not_found():
    with patch("app.services.room_service.get_room", new_callable=AsyncMock, return_value=None):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/rooms/{uuid.uuid4()}")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_room_status():
    room = _make_room(name="Active Room", status="active")
    with patch("app.services.room_service.update_room_status", new_callable=AsyncMock, return_value=room):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(f"/api/rooms/{uuid.uuid4()}/status", json={"status": "active"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "active"
