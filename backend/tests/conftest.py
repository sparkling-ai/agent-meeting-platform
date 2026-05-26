"""Test configuration — SQLite in-memory for API tests."""

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.models import Base
from app.main import app
from app.database import get_db

# SQLite in-memory for tests
# We need to handle JSONB -> JSON for SQLite compat
test_engine = create_async_engine("sqlite+aiosqlite://", echo=False)
TestSessionFactory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create and drop all tables for each test — only if test uses DB."""
    # Tables will be created on demand; skip for pure unit tests
    yield
    # Cleanup
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionFactory() as session:
        yield session
        await session.commit()


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """API test client — creates tables first."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionFactory() as session:
        yield session
