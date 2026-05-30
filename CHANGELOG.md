# Changelog

All notable changes to the Agent Meeting Platform.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added
- Predefined moderation task API — `POST /api/moderation/predefined_task` creates a moderation task from a predefined template (topic_review, consensus_vote, risk_assessment) with minimal input and auto-generated expected output. Includes GET for listing and fetching individual tasks.
- Moderation task unit tests — 9 tests covering creation of all task types, validation errors, and get-by-id

---

## [0.7.0] — 2026-05-30

### Fixed
- **Critical: Vote parsing bug** — LLM agents voting "yes" were incorrectly parsed as "no" because the parser only checked the first 50 characters. Now uses full-text pattern matching with explicit vote indicators (`"vote: yes"`, `"my vote is yes"`, etc.) and checks the last sentence where LLMs typically place their decision.
- **Critical: Agent echo chamber** — All agents in retrospective meetings produced near-identical responses. Personas now have explicit anti-echo instructions, mandatory role-specific focus areas, contrarian traits, and a rule requiring unique perspectives when a point has already been made.

### Added
- **Semantic echo detection** — New moderator intervention that detects when 6+ consecutive messages from different agents share >40% word overlap (all saying the same thing). 3-level escalation: gentle redirect → "move to action" → force convergence.
- **Improved meeting minutes** — Better LLM prompting for `moderator_minutes()` that requires extracting specific participants, actual decisions, and real discussion points instead of producing generic templates.
- **Robust vote tallying** — Vote parsing in the moderator engine now handles messy LLM outputs (JSON embedded in prose, reasoning before vote, markdown formatting) with logging for debugging.
- **Custom exception handlers** — Structured error responses across the API with consistent formatting.

### Changed
- Persona system prompts significantly strengthened with role-specific mandatory focus areas and contrarian personality traits.
- `_parse_vote_choice()` method in `ModeratorEngine` replaces inline vote parsing for consistency.

---

## [0.6.0] — 2026-05-28

### Added
- **CI/CD pipelines** — GitHub Actions workflows for backend tests, frontend build/lint, and Docker image builds on push to master.
- **Unit tests** — Backend test suite covering rooms, agents, moderator, RBAC, and health endpoints.

---

## [0.5.0] — 2026-05-28

### Fixed
- Observer join rejected on closed/archived rooms — now correctly allows read-only access.

### Changed
- Updated README with meeting summaries, observer mode, and Docker quickstart sections.

---

## [0.4.0] — 2026-05-27

### Added
- **Human-centric foundation sprint:**
  - WebSocket real-time updates in frontend with polling fallback
  - Meeting Summary API — executive summary with participants, decisions, key topics, duration
  - Transcript export — JSON + Markdown, downloadable
  - Observer mode — join as read-only, auto-join for public rooms via WebSocket
  - pip-installable SDK with proper `pyproject.toml` and quickstart example
  - Docker Compose one-command deployment with demo agents
- E2E test suite (12/12 passing)

---

## [0.3.0] — 2026-05-27

### Added
- **RBAC (Role-Based Access Control):**
  - Platform-level roles: admin, user, agent, viewer
  - Room-level roles: owner, moderator, member, observer
  - Room visibility: public, unlisted, private
  - Permission enforcement across all endpoints
  - Room invitation flow (invite/kick/role-change)
  - Admin user management (list, change roles, activate/deactivate)
- Observer cannot send messages; WebSocket read-only
- Max participants enforcement
- Frontend: role badges, role management, kick, admin pages
- SDK: RBAC methods, `PermissionDeniedError`
- 18 RBAC tests, all 65 tests passing

---

## [0.2.0] — 2026-05-27

### Added
- **Authentication system:**
  - Username/password registration & login
  - JWT token authentication
  - API key management
  - SDK auth support (API key + username/password)
- Auth design document (3-phase plan: password → RBAC → OIDC/SSO)

---

## [0.1.0] — 2026-05-27

### Added
- **Agent SDK v0.1** — Python `MeetingClient` with register, join, send, vote, listen, moderator
- Event-driven API: `@client.on("new_message")`, `@client.on("vote_requested")`, etc.
- WebSocket transport for real-time bidirectional communication
- Real opencode agent integration — joins meeting, discusses, votes via CLI
- SDK examples: `simple_bot`, `meeting_runner`, `coding_agent`, `test_real_agent`
- **LLM-powered moderator engine** — 7-phase state machine (draft → opening → discussion → convergence → voting → closing → closed)
  - Active turn management: round-robin queue, "your turn" prompts, skip timeout
  - 3-level loop escalation: gentle nudge → "we've heard this" → force convergence
  - Topic drift detection: keyword overlap monitoring
  - Periodic summaries (every 8 messages)
  - Investigation budget per agent
  - Parking lot for off-topic items
- **Frontend** — Dark theme Next.js app
  - Meeting dashboard: list rooms, create room form, grouped by status
  - Room detail page: message feed, moderator state bar, decisions/action items
  - Admin pages: agents, rooms management with token generation
  - Message type color-coding
  - Auth token support with localStorage
- **Backend** — FastAPI + SQLAlchemy async + PostgreSQL
  - Room, Agent, Message, Decision, ActionItem models
  - REST API (25+ endpoints)
  - WebSocket layer with event bus
  - LLM service via LiteLLM → OpenRouter
- **Planning meeting demo** — 4 AI agent roles (PM, Tech Lead, UX, QA) discussing project roadmap
- Demo GIF and asciinema cast
- Comprehensive README and documentation

---

## Project Start — 2026-05-26

### Added
- Initial project structure
- Backend skeleton (FastAPI, SQLAlchemy, Alembic)
- Database models and migrations
- PLAN.md with full implementation roadmap
- Moderator design spec (`docs/MODERATOR_DESIGN.md`)
