"""Tests for auth endpoints — register, login, /me."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    """Registering a new user returns 201 with JWT and user info."""
    resp = await client.post("/api/auth/register", json={
        "username": "alice",
        "email": "alice@example.com",
        "password": "secret123",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == "alice"
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["role"] == "user"
    assert body["user"]["is_active"] is True
    assert body["user"]["display_name"] == "alice"


@pytest.mark.asyncio
async def test_register_with_display_name(client: AsyncClient):
    """Registering with an explicit display_name uses it instead of username."""
    resp = await client.post("/api/auth/register", json={
        "username": "bob",
        "email": "bob@example.com",
        "password": "secret123",
        "display_name": "Bob Smith",
    })
    assert resp.status_code == 201
    assert resp.json()["user"]["display_name"] == "Bob Smith"


@pytest.mark.asyncio
async def test_register_duplicate_username(client: AsyncClient):
    """Duplicate username returns 409."""
    await client.post("/api/auth/register", json={
        "username": "charlie",
        "email": "charlie@example.com",
        "password": "secret123",
    })
    resp = await client.post("/api/auth/register", json={
        "username": "charlie",
        "email": "other@example.com",
        "password": "secret123",
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    """Duplicate email returns 409."""
    await client.post("/api/auth/register", json={
        "username": "dave",
        "email": "dave@example.com",
        "password": "secret123",
    })
    resp = await client.post("/api/auth/register", json={
        "username": "dave2",
        "email": "dave@example.com",
        "password": "secret123",
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_short_password(client: AsyncClient):
    """Password shorter than 6 chars returns 422 validation error."""
    resp = await client.post("/api/auth/register", json={
        "username": "eve",
        "email": "eve@example.com",
        "password": "short",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_short_username(client: AsyncClient):
    """Username shorter than 3 chars returns 422 validation error."""
    resp = await client.post("/api/auth/register", json={
        "username": "ab",
        "email": "ab@example.com",
        "password": "secret123",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_missing_fields(client: AsyncClient):
    """Missing required fields return 422."""
    resp = await client.post("/api/auth/register", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    """Login with correct credentials returns JWT."""
    await client.post("/api/auth/register", json={
        "username": "frank",
        "email": "frank@example.com",
        "password": "secret123",
    })
    resp = await client.post("/api/auth/login", json={
        "username": "frank",
        "password": "secret123",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["user"]["username"] == "frank"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    """Login with wrong password returns 401."""
    await client.post("/api/auth/register", json={
        "username": "grace",
        "email": "grace@example.com",
        "password": "secret123",
    })
    resp = await client.post("/api/auth/login", json={
        "username": "grace",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient):
    """Login with unknown username returns 401."""
    resp = await client.post("/api/auth/login", json={
        "username": "nobody",
        "password": "secret123",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_with_valid_token(client: AsyncClient):
    """GET /me with valid token returns user info."""
    reg = await client.post("/api/auth/register", json={
        "username": "heidi",
        "email": "heidi@example.com",
        "password": "secret123",
    })
    token = reg.json()["access_token"]
    resp = await client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {token}",
    })
    assert resp.status_code == 200
    assert resp.json()["username"] == "heidi"


@pytest.mark.asyncio
async def test_me_without_token(client: AsyncClient):
    """GET /me without token returns 401."""
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_password_is_hashed(client: AsyncClient, db_session):
    """Verify password is stored as bcrypt hash, not plaintext."""
    from sqlalchemy import select
    from app.models.user import User

    await client.post("/api/auth/register", json={
        "username": "ivan",
        "email": "ivan@example.com",
        "password": "secret123",
    })
    result = await db_session.execute(select(User).where(User.username == "ivan"))
    user = result.scalar_one()
    assert user.password_hash != "secret123"
    assert user.password_hash.startswith("$2")
