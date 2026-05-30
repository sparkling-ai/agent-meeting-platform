"""Test /health endpoint — no DB required."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_endpoint():
    """Health check returns status ok without needing a database."""
    # Override lifespan to skip DB setup
    from app.main import app
    from contextlib import asynccontextmanager
    from fastapi import FastAPI

    @asynccontextmanager
    async def _noop_lifespan(app: FastAPI):
        yield

    # Swap lifespan to avoid DB connection
    original_router = app.router.lifespan_context
    app.router.lifespan_context = _noop_lifespan

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")

    app.router.lifespan_context = original_router

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


@pytest.mark.asyncio
async def test_api_index():
    """API index lists available endpoint groups."""
    from app.main import app
    from contextlib import asynccontextmanager
    from fastapi import FastAPI

    @asynccontextmanager
    async def _noop_lifespan(app: FastAPI):
        yield

    original_router = app.router.lifespan_context
    app.router.lifespan_context = _noop_lifespan

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api")

    app.router.lifespan_context = original_router

    assert resp.status_code == 200
    data = resp.json()
    assert "endpoints" in data
    assert "rooms" in data["endpoints"]
    assert "agents" in data["endpoints"]
