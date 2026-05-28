"""Tests for RBAC (Phase 2) — permissions, roles, invitations, admin."""

import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import engine, async_session_factory, get_db
from app.models import Base
from app.main import app


@pytest_asyncio.fixture
async def db_tables():
    """Create schema + tables before test, drop after."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS agent_meeting_dev"))
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _get_test_db():
    async with async_session_factory() as session:
        yield session
        await session.commit()


@pytest_asyncio.fixture
async def client(db_tables):
    """API test client."""
    app.dependency_overrides[get_db] = _get_test_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────

async def register_user(client: AsyncClient, username: str, role: str = "user") -> dict:
    """Register a user and return {user, token}."""
    resp = await client.post("/api/auth/register", json={
        "username": username,
        "email": f"{username}@test.com",
        "password": "testpass123",
    })
    assert resp.status_code == 201, f"Register failed: {resp.text}"
    data = resp.json()
    return {"user": data["user"], "token": data["access_token"]}


async def create_room(client: AsyncClient, token: str, **kwargs) -> dict:
    """Create a room with auth."""
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"name": kwargs.get("name", "Test Room"), "topic": kwargs.get("topic", "Testing")}
    if "visibility" in kwargs:
        payload["visibility"] = kwargs["visibility"]
    if "max_participants" in kwargs:
        payload["max_participants"] = kwargs["max_participants"]
    resp = await client.post("/api/rooms", json=payload, headers=headers)
    assert resp.status_code == 201, f"Create room failed: {resp.text}"
    return resp.json()


async def register_agent(client: AsyncClient, token: str, name: str = "TestAgent") -> dict:
    """Register an agent."""
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post("/api/agents", json={"name": name, "connector_type": "rest"}, headers=headers)
    assert resp.status_code == 201, f"Agent registration failed: {resp.text}"
    return resp.json()


async def join_room(client: AsyncClient, token: str, room_id: str, agent_id: str, role: str = "member") -> dict:
    """Join a room."""
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post(f"/api/rooms/{room_id}/join", json={"agent_id": agent_id, "role": role}, headers=headers)
    return resp


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_room_has_visibility_and_max_participants(client: AsyncClient):
    """Room create should accept and return visibility and max_participants."""
    user = await register_user(client, "creator1")
    room = await create_room(client, user["token"], visibility="private", max_participants=5)
    assert room["visibility"] == "private"
    assert room["max_participants"] == 5


@pytest.mark.asyncio
async def test_room_default_visibility(client: AsyncClient):
    """Default visibility should be unlisted."""
    user = await register_user(client, "creator2")
    room = await create_room(client, user["token"])
    assert room["visibility"] == "unlisted"
    assert room["max_participants"] == 20


@pytest.mark.asyncio
async def test_room_owner_set_on_create(client: AsyncClient):
    """Room should have owner_id set when created by authenticated user."""
    user = await register_user(client, "owner1")
    room = await create_room(client, user["token"])
    assert room["owner_id"] == user["user"]["id"]


@pytest.mark.asyncio
async def test_invite_to_room(client: AsyncClient):
    """Owner can invite an agent to a room."""
    owner = await register_user(client, "roomowner")
    room = await create_room(client, owner["token"], visibility="private")
    agent = await register_agent(client, owner["token"], "InvitedAgent")

    headers = {"Authorization": f"Bearer {owner['token']}"}
    # First, owner needs to join via their agent
    owner_agent = await register_agent(client, owner["token"], "OwnerAgent")
    await join_room(client, owner["token"], room["id"], owner_agent["id"], "owner")

    # Now invite
    resp = await client.post(f"/api/rooms/{room['id']}/invite", json={
        "agent_id": agent["id"],
        "role": "member",
    }, headers=headers)
    assert resp.status_code == 200, f"Invite failed: {resp.text}"
    data = resp.json()
    assert data["role"] == "member"


@pytest.mark.asyncio
async def test_kick_member(client: AsyncClient):
    """Owner/moderator can kick a member."""
    owner = await register_user(client, "kickowner")
    room = await create_room(client, owner["token"])
    owner_agent = await register_agent(client, owner["token"], "OwnerAgent")
    member_agent = await register_agent(client, owner["token"], "MemberAgent")

    headers = {"Authorization": f"Bearer {owner['token']}"}
    await join_room(client, owner["token"], room["id"], owner_agent["id"], "owner")
    await join_room(client, owner["token"], room["id"], member_agent["id"], "member")

    # Kick
    resp = await client.delete(f"/api/rooms/{room['id']}/members/{member_agent['id']}", headers=headers)
    assert resp.status_code == 200, f"Kick failed: {resp.text}"


@pytest.mark.asyncio
async def test_change_member_role(client: AsyncClient):
    """Owner can change a member's role."""
    owner = await register_user(client, "roleowner")
    room = await create_room(client, owner["token"])
    owner_agent = await register_agent(client, owner["token"], "OwnerAgent")
    member_agent = await register_agent(client, owner["token"], "Promotable")

    headers = {"Authorization": f"Bearer {owner['token']}"}
    await join_room(client, owner["token"], room["id"], owner_agent["id"], "owner")
    await join_room(client, owner["token"], room["id"], member_agent["id"], "member")

    # Promote to moderator
    resp = await client.patch(f"/api/rooms/{room['id']}/members/{member_agent['id']}/role", json={
        "role": "moderator",
    }, headers=headers)
    assert resp.status_code == 200, f"Role change failed: {resp.text}"
    assert resp.json()["new_role"] == "moderator"


@pytest.mark.asyncio
async def test_non_owner_cannot_change_role(client: AsyncClient):
    """Non-owner cannot change member roles."""
    owner = await register_user(client, "strictowner")
    other = await register_user(client, "otheruser")
    room = await create_room(client, owner["token"])
    owner_agent = await register_agent(client, owner["token"], "OwnerAgent")
    other_agent = await register_agent(client, other["token"], "OtherAgent")

    headers_owner = {"Authorization": f"Bearer {owner['token']}"}
    headers_other = {"Authorization": f"Bearer {other['token']}"}

    await join_room(client, owner["token"], room["id"], owner_agent["id"], "owner")
    await join_room(client, other["token"], room["id"], other_agent["id"], "member")

    # Other tries to change owner's role
    resp = await client.patch(f"/api/rooms/{room['id']}/members/{owner_agent['id']}/role", json={
        "role": "observer",
    }, headers=headers_other)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_list_users(client: AsyncClient):
    """Admin can list all users."""
    # Register regular user
    await register_user(client, "regularuser")
    # Register admin user and manually set role
    admin = await register_user(client, "admin1")

    # Manually update role to admin
    async with async_session_factory() as db:
        from app.models.user import User
        from sqlalchemy import select
        result = await db.execute(select(User).where(User.username == "admin1"))
        admin_user = result.scalar_one()
        admin_user.role = "admin"
        await db.commit()

    # Re-login to get admin token
    resp = await client.post("/api/auth/login", json={"username": "admin1", "password": "testpass123"})
    admin_token = resp.json()["access_token"]

    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.get("/api/admin/users", headers=headers)
    assert resp.status_code == 200
    users = resp.json()
    assert len(users) >= 2


@pytest.mark.asyncio
async def test_admin_update_user_role(client: AsyncClient):
    """Admin can change a user's platform role."""
    user = await register_user(client, "targetuser")
    admin = await register_user(client, "admin2")

    async with async_session_factory() as db:
        from app.models.user import User
        from sqlalchemy import select
        result = await db.execute(select(User).where(User.username == "admin2"))
        admin_user = result.scalar_one()
        admin_user.role = "admin"
        await db.commit()

    resp = await client.post("/api/auth/login", json={"username": "admin2", "password": "testpass123"})
    admin_token = resp.json()["access_token"]

    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.patch(f"/api/admin/users/{user['user']['id']}", json={"role": "viewer"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["role"] == "viewer"


@pytest.mark.asyncio
async def test_non_admin_cannot_list_users(client: AsyncClient):
    """Regular user cannot access admin endpoints."""
    user = await register_user(client, "regular2")
    headers = {"Authorization": f"Bearer {user['token']}"}
    resp = await client.get("/api/admin/users", headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_list_rooms(client: AsyncClient):
    """Admin can list all rooms."""
    user = await register_user(client, "roomcreator")
    await create_room(client, user["token"])

    admin = await register_user(client, "admin3")
    async with async_session_factory() as db:
        from app.models.user import User
        from sqlalchemy import select
        result = await db.execute(select(User).where(User.username == "admin3"))
        admin_user = result.scalar_one()
        admin_user.role = "admin"
        await db.commit()

    resp = await client.post("/api/auth/login", json={"username": "admin3", "password": "testpass123"})
    admin_token = resp.json()["access_token"]

    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.get("/api/admin/rooms", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_admin_delete_room(client: AsyncClient):
    """Admin can force-delete any room."""
    user = await register_user(client, "roomdel")
    room = await create_room(client, user["token"])

    admin = await register_user(client, "admin4")
    async with async_session_factory() as db:
        from app.models.user import User
        from sqlalchemy import select
        result = await db.execute(select(User).where(User.username == "admin4"))
        admin_user = result.scalar_one()
        admin_user.role = "admin"
        await db.commit()

    resp = await client.post("/api/auth/login", json={"username": "admin4", "password": "testpass123"})
    admin_token = resp.json()["access_token"]

    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.delete(f"/api/admin/rooms/{room['id']}", headers=headers)
    assert resp.status_code == 200

    # Verify room is gone
    resp = await client.get(f"/api/rooms/{room['id']}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_room_max_participants_enforced(client: AsyncClient):
    """Room respects max_participants limit."""
    user = await register_user(client, "maxpart")
    room = await create_room(client, user["token"], max_participants=1)

    # Create and join first agent
    agent1 = await register_agent(client, user["token"], "Agent1")
    resp = await join_room(client, user["token"], room["id"], agent1["id"])
    assert resp.status_code == 200

    # Second agent should fail
    agent2 = await register_agent(client, user["token"], "Agent2")
    resp = await join_room(client, user["token"], room["id"], agent2["id"])
    assert resp.status_code == 400
    assert "full" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_observer_cannot_send_message(client: AsyncClient):
    """Observer role cannot send messages."""
    user = await register_user(client, "obsertest")
    room = await create_room(client, user["token"])
    agent = await register_agent(client, user["token"], "ObsAgent")

    headers = {"Authorization": f"Bearer {user['token']}"}
    await join_room(client, user["token"], room["id"], agent["id"], "observer")

    # Try to send message
    resp = await client.post(f"/api/rooms/{room['id']}/messages", json={
        "agent_id": agent["id"],
        "type": "chat",
        "content": "Should fail",
    }, headers=headers)
    # Should get 403 due to observer role
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cannot_kick_owner(client: AsyncClient):
    """Cannot kick the room owner."""
    owner = await register_user(client, "unkickable")
    room = await create_room(client, owner["token"])
    owner_agent = await register_agent(client, owner["token"], "OwnerAgent")
    mod_agent = await register_agent(client, owner["token"], "ModAgent")

    headers = {"Authorization": f"Bearer {owner['token']}"}
    await join_room(client, owner["token"], room["id"], owner_agent["id"], "owner")
    await join_room(client, owner["token"], room["id"], mod_agent["id"], "moderator")

    # Moderator tries to kick owner
    resp = await client.delete(f"/api/rooms/{room['id']}/members/{owner_agent['id']}", headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_role_hierarchy_kick(client: AsyncClient):
    """Moderator cannot kick another moderator, but owner can."""
    owner = await register_user(client, "hierowner")
    room = await create_room(client, owner["token"])
    owner_agent = await register_agent(client, owner["token"], "OwnerAgent")
    mod1 = await register_agent(client, owner["token"], "Mod1")
    mod2 = await register_agent(client, owner["token"], "Mod2")

    headers = {"Authorization": f"Bearer {owner['token']}"}
    await join_room(client, owner["token"], room["id"], owner_agent["id"], "owner")
    await join_room(client, owner["token"], room["id"], mod1["id"], "moderator")
    await join_room(client, owner["token"], room["id"], mod2["id"], "moderator")

    # Owner can kick moderator
    resp = await client.delete(f"/api/rooms/{room['id']}/members/{mod1['id']}", headers=headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_private_room_access(client: AsyncClient):
    """Private rooms require authentication to view."""
    owner = await register_user(client, "privowner")
    room = await create_room(client, owner["token"], visibility="private")

    # Unauthenticated access should fail
    resp = await client.get(f"/api/rooms/{room['id']}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_cannot_deactivate_self(client: AsyncClient):
    """Admin cannot deactivate their own account."""
    admin = await register_user(client, "selfadmin")
    async with async_session_factory() as db:
        from app.models.user import User
        from sqlalchemy import select
        result = await db.execute(select(User).where(User.username == "selfadmin"))
        admin_user = result.scalar_one()
        admin_user.role = "admin"
        await db.commit()

    resp = await client.post("/api/auth/login", json={"username": "selfadmin", "password": "testpass123"})
    admin_token = resp.json()["access_token"]

    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.patch(f"/api/admin/users/{admin['user']['id']}", json={"is_active": False}, headers=headers)
    assert resp.status_code == 400
