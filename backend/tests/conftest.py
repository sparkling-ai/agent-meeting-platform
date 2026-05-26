"""Test configuration — uses real PostgreSQL for E2E tests.

Moderator tests don't need DB at all.
"""

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import engine, async_session_factory, get_db
from app.models import Base
from app.main import app


@pytest_asyncio.fixture
async def db_tables():
    """Create schema + tables before test, drop after. For E2E tests only."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS agent_meeting_dev"))
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _get_test_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
        await session.commit()


@pytest_asyncio.fixture
async def client(db_tables) -> AsyncGenerator[AsyncClient, None]:
    """API test client using real PostgreSQL."""
    app.dependency_overrides[get_db] = _get_test_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def db_session(db_tables) -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
