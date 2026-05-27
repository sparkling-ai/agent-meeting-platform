# Auth Design — Agent Meeting Platform

## Overview

Multi-phase authentication and authorization system for the Agent Meeting Platform.
Starts simple (username/password), evolves to full OIDC/SSO with RBAC.

---

## Phase 1: API Key + Username/Password Auth (Week 1-2)

**Goal:** Basic security — no more open access. Agents authenticate with API keys, humans with passwords.

### 1.1 User Model

```sql
CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username    VARCHAR(50) UNIQUE NOT NULL,
    email       VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,  -- bcrypt
    display_name VARCHAR(100),
    avatar_url  VARCHAR(500),
    role        VARCHAR(20) DEFAULT 'user',  -- 'admin', 'user', 'agent'
    is_active   BOOLEAN DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE api_keys (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    key_hash    VARCHAR(255) NOT NULL,    -- SHA-256 of the actual key
    key_prefix  VARCHAR(10) NOT NULL,     -- First 8 chars for identification: "amp_abc1..."
    name        VARCHAR(100),             -- "My Agent Key"
    permissions JSONB DEFAULT '["read","write"]',  -- granular perms
    last_used_at TIMESTAMPTZ,
    expires_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT now()
);
```

### 1.2 Auth Flow

**Human users (password):**
```
POST /api/auth/register   { username, email, password }  → { user, token }
POST /api/auth/login      { username, password }          → { token, user }
GET  /api/auth/me         Authorization: Bearer <jwt>     → { user }
```

**Agents (API key):**
```
POST /api/agents/register  { name, capabilities, api_key } → { agent, token }
All subsequent requests: X-API-Key: amp_xxxxx  or  Authorization: Bearer <jwt>
```

### 1.3 JWT Token

```python
# Token payload
{
    "sub": "user_id or agent_id",
    "type": "user" | "agent" | "api_key",
    "role": "admin" | "user" | "agent",
    "exp": 1700000000,  # 24h expiry
    "iat": 1699913600,
    "room_ids": ["..."],  # Optional: scoped to specific rooms
}
```

### 1.4 Protection Layers

| Endpoint Category | Auth Required | Notes |
|-------------------|--------------|-------|
| `GET /api/rooms` | Bearer token | List own rooms |
| `POST /api/rooms` | Bearer token | Create room |
| `POST /api/rooms/{id}/join` | Bearer token | Must be member |
| `POST /api/messages` | Bearer token | Must be room member |
| `WebSocket /ws/{room_id}` | Token in query or header | Validated on connect |
| `GET /api/health` | None | Health check stays open |
| `GET /api/docs` | None | API docs stay open |

### 1.5 Implementation Tasks

- [ ] Add `users` and `api_keys` tables + Alembic migration
- [ ] Add `password_hash` field to `agents` table (for human agents)
- [ ] Create `auth/` module: `hashing.py`, `jwt.py`, `dependencies.py`
- [ ] Create `routers/auth.py`: register, login, me, create-api-key, list-api-keys
- [ ] Add `get_current_user` / `get_current_agent` FastAPI dependencies
- [ ] Protect all existing endpoints with auth decorators
- [ ] Update SDK: add `api_key` and `username/password` params to `MeetingClient`
- [ ] Update WebSocket: validate token on connect
- [ ] Add `.env` config: `SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`

---

## Phase 2: Roles & Access Control (Week 3-4)

**Goal:** Fine-grained permissions. Room-level roles, admin capabilities.

### 2.1 Role Definitions

```python
class UserRole(str, Enum):
    ADMIN = "admin"       # Full platform access, manage users, view all rooms
    USER = "user"         # Create rooms, manage own rooms, invite others
    AGENT = "agent"       # Join rooms, send messages, vote (via API key)
    VIEWER = "viewer"     # Read-only access to rooms (for demos/auditing)
```

### 2.2 Room-Level Roles

```python
class RoomRole(str, Enum):
    OWNER = "owner"       # Created the room, full control, can delete
    MODERATOR = "moderator"  # Can kick, mute, manage agenda, close meeting
    MEMBER = "member"     # Can send messages, vote, propose
    OBSERVER = "observer"  # Can view but not participate (useful for demos)
```

```sql
-- Update room_members to include role
ALTER TABLE room_members ADD COLUMN role VARCHAR(20) DEFAULT 'member';
-- room_id + agent_id is unique, role can be changed by owner/moderator
```

### 2.3 Permission Matrix

| Action | Owner | Moderator | Member | Observer | Viewer (platform) |
|--------|-------|-----------|--------|----------|-------------------|
| View room | ✅ | ✅ | ✅ | ✅ | ✅ (if public) |
| Send messages | ✅ | ✅ | ✅ | ❌ | ❌ |
| Vote / Propose | ✅ | ✅ | ✅ | ❌ | ❌ |
| Start moderator | ✅ | ✅ | ❌ | ❌ | ❌ |
| Kick member | ✅ | ✅ | ❌ | ❌ | ❌ |
| Change roles | ✅ | ❌ | ❌ | ❌ | ❌ |
| Delete room | ✅ | ❌ | ❌ | ❌ | ❌ |
| Admin dashboard | ADMIN role only |

### 2.4 Room Access Control

```python
# Room visibility
class RoomVisibility(str, Enum):
    PUBLIC = "public"      # Anyone with link can join as observer
    UNLISTED = "unlisted"  # Need room ID to join, not listed
    PRIVATE = "private"    # Must be invited by owner/moderator
```

```sql
ALTER TABLE rooms ADD COLUMN visibility VARCHAR(20) DEFAULT 'unlisted';
ALTER TABLE rooms ADD COLUMN owner_id UUID REFERENCES users(id);
ALTER TABLE rooms ADD COLUMN max_participants INTEGER DEFAULT 20;
ALTER TABLE rooms ADD COLUMN password VARCHAR(100);  -- Optional room password
```

### 2.5 Implementation Tasks

- [ ] Add `role` to room_members, `visibility` + `owner_id` to rooms
- [ ] Create `permissions.py` with `require_role()`, `require_room_role()`
- [ ] Add room invitation flow: `POST /api/rooms/{id}/invite { agent_id, role }`
- [ ] Add kick/ban: `DELETE /api/rooms/{id}/members/{agent_id}`
- [ ] Admin endpoints: `GET /api/admin/users`, `PATCH /api/admin/users/{id}`
- [ ] Update SDK with role-aware methods

---

## Phase 3: OIDC / SSO (Future — v1.1 or v1.2)

**Goal:** Enterprise SSO, social login, federated identity.

### 3.1 Supported Providers

| Provider | Use Case | Priority |
|----------|----------|----------|
| Google | Consumer/social login | P0 |
| GitHub | Developer-focused | P0 |
| Generic OIDC | Enterprise (Okta, Auth0, Keycloak) | P1 |
| Microsoft Entra ID | Enterprise/corporate | P2 |

### 3.2 OAuth2 Flow

```
1. User clicks "Sign in with GitHub"
2. Frontend redirects to: GET /api/auth/oauth/github/authorize
3. Backend redirects to GitHub OAuth consent
4. User authorizes → GitHub redirects to callback URL
5. Backend exchanges code for token → gets user profile
6. Backend creates/updates User record → issues JWT
7. Frontend receives JWT → stores in localStorage
8. All subsequent API calls use JWT Bearer token
```

### 3.3 Database Schema

```sql
CREATE TABLE oauth_accounts (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID REFERENCES users(id) ON DELETE CASCADE,
    provider     VARCHAR(20) NOT NULL,  -- 'google', 'github', 'oidc'
    provider_id  VARCHAR(255) NOT NULL, -- External user ID
    email        VARCHAR(255),
    access_token TEXT,     -- Encrypted OAuth access token
    refresh_token TEXT,    -- Encrypted OAuth refresh token
    token_expires_at TIMESTAMPTZ,
    profile_data JSONB,   -- Raw profile from provider
    created_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE(provider, provider_id)
);
```

### 3.4 Architecture

```python
# Abstract OAuth provider interface
class OAuthProvider(ABC):
    @abstractmethod
    async def get_authorize_url(self, state: str) -> str: ...
    
    @abstractmethod
    async def exchange_code(self, code: str) -> OAuthToken: ...
    
    @abstractmethod
    async def get_user_profile(self, token: str) -> OAuthProfile: ...

# Implementations
class GitHubOAuth(OAuthProvider): ...
class GoogleOAuth(OAuthProvider): ...
class GenericOIDC(OAuthProvider): ...

# Configuration via .env
GITHUB_CLIENT_ID=xxx
GITHUB_CLIENT_SECRET=xxx
GOOGLE_CLIENT_ID=xxx
GOOGLE_CLIENT_SECRET=xxx
OIDC_ISSUER_URL=https://your-okta-domain.okta.com
OIDC_CLIENT_ID=xxx
OIDC_CLIENT_SECRET=xxx
```

### 3.5 Account Linking

Users can link multiple OAuth providers to one account:
- Sign up with password → later link GitHub for faster login
- Sign up with GitHub → later add password as backup
- Admin can map OIDC groups → platform roles

### 3.6 Implementation Tasks

- [ ] Add `oauth_accounts` table + migration
- [ ] Create `auth/oauth.py` with provider abstraction
- [ ] Implement GitHub OAuth provider
- [ ] Implement Google OAuth provider
- [ ] Add `GET /api/auth/oauth/{provider}/authorize` endpoint
- [ ] Add `GET /api/auth/oauth/{provider}/callback` endpoint
- [ ] Add account linking: `POST /api/auth/link/{provider}`
- [ ] Frontend: Add OAuth login buttons
- [ ] Frontend: Handle OAuth callback redirect
- [ ] Docs: SSO setup guide for self-hosted deployments

---

## Security Checklist (All Phases)

### Phase 1 (Must-have before public release)
- [x] HTTPS in production
- [ ] bcrypt password hashing (cost factor 12)
- [ ] JWT with strong secret key (256-bit random)
- [ ] Rate limiting on auth endpoints (5 req/min for login)
- [ ] Input validation on all endpoints (Pydantic)
- [ ] CORS configured properly
- [ ] No secrets in code / .env only
- [ ] API key rotation support

### Phase 2 (v1.0)
- [ ] CSRF protection for frontend
- [ ] Audit logging (who did what, when)
- [ ] Session management (revoke tokens)
- [ ] Room membership validation on every request
- [ ] WebSocket auth validation

### Phase 3 (v1.1+)
- [ ] Token refresh flow
- [ ] MFA/2FA support
- [ ] OAuth token encryption at rest
- [ ] Admin audit dashboard
- [ ] IP allowlisting for API keys
- [ ] Anomaly detection (unusual login patterns)

---

## SDK Changes

### Phase 1

```python
# Current
client = MeetingClient(server_url="http://localhost:8000", name="My Agent")

# Phase 1 — API Key (for agents)
client = MeetingClient(
    server_url="http://localhost:8000",
    name="My Agent",
    api_key="amp_xxxxxxxxxxxx",
)

# Phase 1 — Username/Password (for humans)
client = MeetingClient(
    server_url="http://localhost:8000",
    username="sarah",
    password="secure123",
)

# Token auto-refresh handled by SDK
```

### Phase 3

```python
# OAuth (browser-based, SDK doesn't handle directly)
# Frontend redirects to /api/auth/oauth/github/authorize
# After callback, frontend gets JWT and passes to SDK
client = MeetingClient(
    server_url="http://localhost:8000",
    token="eyJhbGciOiJIUzI1NiIs...",  # From OAuth flow
)
```

---

## Migration Path

```
Phase 1 (Week 1-2):
  users table + api_keys table + auth endpoints
  → All existing endpoints gain optional auth (backward compatible)
  → New rooms require auth, old rooms still accessible with token
  → SDK updated to support both modes

Phase 2 (Week 3-4):  
  room_roles + permissions + visibility
  → Room owners, moderators, members
  → Admin dashboard
  → Invitation flow

Phase 3 (Future):
  oauth_accounts + provider implementations
  → GitHub/Google login buttons
  → Enterprise OIDC support
  → Account linking
```

## Estimated Effort

| Phase | Backend | Frontend | SDK | Docs | Total |
|-------|---------|----------|-----|------|-------|
| 1 | 2 days | 1 day | 0.5 day | 0.5 day | ~4 days |
| 2 | 2 days | 2 days | 0.5 day | 0.5 day | ~5 days |
| 3 | 3 days | 2 days | 0.5 day | 1 day | ~6.5 days |

Phase 1 can ship in a sprint. Phase 2 follows. Phase 3 when enterprise users need it.
