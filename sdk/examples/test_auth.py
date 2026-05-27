#!/usr/bin/env python3
"""Test script for Phase 1 authentication.

Tests:
1. Register a user
2. Login
3. Create an API key
4. Use API key to create an agent + room + join + send messages
5. Verify auth is enforced (401 without token)
"""

import asyncio
import httpx
import sys

BASE_URL = "http://localhost:8000"


async def test_auth():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        print("=" * 60)
        print("Phase 1 Auth Test")
        print("=" * 60)

        # ── 0. Health check ──────────────────────────────────────────
        print("\n[0] Health check...")
        resp = await client.get("/health")
        assert resp.status_code == 200, f"Health failed: {resp.status_code}"
        print(f"    ✓ Server is healthy: {resp.json()}")

        # ── 1. Register a user ───────────────────────────────────────
        print("\n[1] Registering user...")
        register_data = {
            "username": f"testuser_{asyncio.get_event_loop().time():.0f}",
            "email": f"test_{asyncio.get_event_loop().time():.0f}@example.com",
            "password": "testpassword123",
            "display_name": "Test User",
        }
        resp = await client.post("/api/auth/register", json=register_data)
        assert resp.status_code == 201, f"Register failed: {resp.status_code} {resp.text}"
        register_result = resp.json()
        token = register_result["access_token"]
        user = register_result["user"]
        print(f"    ✓ Registered: {user['username']} (id={user['id'][:8]}...)")
        print(f"    ✓ Token: {token[:30]}...")

        # ── 2. Login ─────────────────────────────────────────────────
        print("\n[2] Logging in...")
        resp = await client.post("/api/auth/login", json={
            "username": register_data["username"],
            "password": register_data["password"],
        })
        assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
        login_result = resp.json()
        token = login_result["access_token"]
        print(f"    ✓ Logged in as {login_result['user']['username']}")

        # ── 3. Get current user (/me) ───────────────────────────────
        print("\n[3] Getting current user...")
        resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, f"Me failed: {resp.status_code}"
        me = resp.json()
        print(f"    ✓ Current user: {me['username']} (role={me['role']})")

        # ── 4. Create an API key ─────────────────────────────────────
        print("\n[4] Creating API key...")
        resp = await client.post(
            "/api/auth/api-keys",
            json={"name": "Test Agent Key", "permissions": ["read", "write"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201, f"API key create failed: {resp.status_code} {resp.text}"
        api_key_result = resp.json()
        api_key = api_key_result["api_key"]
        api_key_info = api_key_result["api_key_info"]
        print(f"    ✓ API key created: {api_key[:16]}... (prefix={api_key_info['key_prefix']})")

        # ── 5. List API keys ─────────────────────────────────────────
        print("\n[5] Listing API keys...")
        resp = await client.get("/api/auth/api-keys", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, f"List keys failed: {resp.status_code}"
        keys = resp.json()
        print(f"    ✓ Found {len(keys)} API key(s)")

        # ── 6. Use API key to create agent ───────────────────────────
        print("\n[6] Creating agent with API key...")
        resp = await client.post(
            "/api/agents",
            json={"name": "Auth Test Agent", "connector_type": "rest", "capabilities": {"test": True}},
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 201, f"Agent create failed: {resp.status_code} {resp.text}"
        agent = resp.json()
        agent_id = agent["id"]
        print(f"    ✓ Agent created: {agent['name']} (id={agent_id[:8]}...)")

        # ── 7. Use API key to create room ────────────────────────────
        print("\n[7] Creating room with API key...")
        resp = await client.post(
            "/api/rooms",
            json={"name": "Auth Test Room", "topic": "Testing authentication"},
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 201, f"Room create failed: {resp.status_code} {resp.text}"
        room = resp.json()
        room_id = room["id"]
        print(f"    ✓ Room created: {room['name']} (id={room_id[:8]}...)")

        # ── 8. Use API key to join room ──────────────────────────────
        print("\n[8] Joining room with API key...")
        resp = await client.post(
            f"/api/rooms/{room_id}/join",
            json={"agent_id": agent_id, "role": "participant"},
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 200, f"Join failed: {resp.status_code} {resp.text}"
        print(f"    ✓ Joined room successfully")

        # ── 9. Use API key to send message ───────────────────────────
        print("\n[9] Sending message with API key...")
        resp = await client.post(
            f"/api/rooms/{room_id}/messages",
            json={"agent_id": agent_id, "type": "chat", "content": "Hello from authenticated agent!"},
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 201, f"Message failed: {resp.status_code} {resp.text}"
        msg = resp.json()
        print(f"    ✓ Message sent: {msg['content']}")

        # ── 10. Verify unauthenticated access still works (optional_auth) ──
        print("\n[10] Verifying unauthenticated access (backward compat)...")
        resp = await client.get("/api/rooms")
        assert resp.status_code == 200, f"Unauth rooms failed: {resp.status_code}"
        print(f"    ✓ Unauthenticated room listing works ({len(resp.json())} rooms)")

        # ── 11. Verify admin endpoints require admin role ─────────────
        print("\n[11] Verifying admin protection...")
        resp = await client.delete(
            f"/api/admin/rooms/{room_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        # Should be 403 since test user is not admin
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
        print(f"    ✓ Admin-only endpoint correctly rejected non-admin user (403)")

        # ── 12. Verify register with duplicate username fails ─────────
        print("\n[12] Verifying duplicate registration...")
        resp = await client.post("/api/auth/register", json=register_data)
        assert resp.status_code == 409, f"Expected 409, got {resp.status_code}"
        print(f"    ✓ Duplicate registration correctly rejected (409)")

        # ── 13. Verify bad password login fails ───────────────────────
        print("\n[13] Verifying bad password...")
        resp = await client.post("/api/auth/login", json={
            "username": register_data["username"],
            "password": "wrongpassword",
        })
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print(f"    ✓ Bad password correctly rejected (401)")

        # ── 14. Verify /me without token fails ───────────────────────
        print("\n[14] Verifying /me without token...")
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print(f"    ✓ /me without token correctly rejected (401)")

        # ── 15. Revoke API key ───────────────────────────────────────
        print("\n[15] Revoking API key...")
        resp = await client.delete(
            f"/api/auth/api-keys/{api_key_info['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204, f"Revoke failed: {resp.status_code}"
        print(f"    ✓ API key revoked")

        # Verify revoked key no longer works
        resp = await client.get(
            "/api/auth/me",
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 401, f"Expected 401 with revoked key, got {resp.status_code}"
        print(f"    ✓ Revoked API key correctly rejected (401)")

        print("\n" + "=" * 60)
        print("✅ All 15 tests passed!")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_auth())
