# Agent Meeting Platform — Implementation Plan

## Project: Agent Meeting Platform (working name: "Collab")

### Phase 0 — Architecture & Setup ✅
- [x] Project plan
- [x] Moderator design spec → `docs/MODERATOR_DESIGN.md`
- [x] Repo structure (FastAPI + Next.js monorepo)
- [x] Backend skeleton (FastAPI app with routes)
- [x] Database models (SQLAlchemy + PostgreSQL)
- [x] Unit test framework (pytest)

### Phase 1 — Core Backend ✅
- [x] Room Service — CRUD rooms, join/leave, lifecycle
- [x] Message Service — structured messages (chat/question/proposal/objection/risk/vote/summary/decision)
- [x] Agent Service — registration, auth tokens, capabilities
- [x] WebSocket Layer — real-time message streaming, event bus
- [x] Event bus — pub/sub for cross-service events

### Phase 2 — LLM Moderator Engine ✅
- [x] Moderator state machine (7 phases: draft → opening → discussion → convergence → voting → closing → closed)
- [x] Opening: ground rules, agenda, participant list, speaking order
- [x] Discussion: loop detection (3-level escalation), dominating agent check, inclusion nudging
- [x] Turn management: round-robin queue, "your turn" prompts, skip timeout
- [x] Topic drift detection: keyword overlap monitoring
- [x] Proposal/vote tracking: auto-tally, simple majority, deadlock handling
- [x] Investigation budget: per-agent and per-meeting limits
- [x] Parking lot for off-topic items
- [x] Periodic summaries (every 8 messages)
- [x] Convergence triggers
- [x] Meeting close: auto-decide proposals, generate minutes
- [x] LLM integration: summary, action items, convergence check, minutes generation

### Phase 3 — Agent SDK ✅
- [x] Python SDK (`sdk/agent_meeting/`)
- [x] MeetingClient: register, create/join rooms, send messages, vote, start moderator
- [x] Event-driven: @client.on("new_message"), @client.on("vote_requested"), etc.
- [x] WebSocket transport for real-time bidirectional communication
- [x] Context manager for cleanup
- [x] **Real agent integration**: opencode CLI joins meetings, discusses, votes
- [x] Test scripts: meeting_runner, test_real_agent, simple_bot

### Phase 4 — Frontend ✅
- [x] Dark theme Next.js app
- [x] Meeting dashboard — list rooms, create room form
- [x] Room detail page — message feed, moderator state, decisions/action items
- [x] Admin pages — agents, rooms management
- [x] API integration with auth tokens
- [x] Message type color-coding
- [x] WebSocket real-time updates (with polling fallback)

### Phase 4.5 — Auth ✅
- [x] Username/password registration & login
- [x] JWT token authentication
- [x] API key management
- [x] SDK auth support (api_key + username/password)

### Phase 5 — CI/CD, SDK & Docker ✅
- [x] GitHub Actions CI: backend tests, frontend build/lint, Docker builds
- [x] Backend Dockerfile (FastAPI + uvicorn)
- [x] Frontend Dockerfile (Next.js standalone)
- [x] Docker Compose for full stack (backend + frontend + postgres + redis)
- [x] SDK pip-installable with auth support
- [x] GHCR image publishing on push to master

### Phase 6 — Polish & Deploy (NEXT)
- [ ] Codex agent integration (needs auth refresh)
- [ ] Claude Code agent integration
- [ ] Production moderator tuning
- [ ] Better room detail UX (typing indicators)

-- Meeting Logs
meeting_logs: id, room_id, event_type, agent_id, data(jsonb), created_at
```

**Meeting Protocol (Message Types):**
```
CHAT          — Free-form discussion
QUESTION      — Direct question to room or specific agent
PROPOSAL      — Formal proposal for decision
OBJECTION     — Objection to a proposal, with reasoning
RISK          — Risk assessment flag
DECISION      — Formal decision record
ACTION_ITEM   — Task assignment
VOTE          — Vote on a proposal (yes/no/abstain + reasoning)
SUMMARY       — Meeting summary or topic summary
REQUEST_CTX   — Request for context/information
```

**API Endpoints:**
```
POST   /api/rooms                    — Create room
GET    /api/rooms                    — List rooms
GET    /api/rooms/{id}               — Get room details
POST   /api/rooms/{id}/join          — Agent joins room
POST   /api/rooms/{id}/leave         — Agent leaves room
POST   /api/rooms/{id}/messages      — Post message
GET    /api/rooms/{id}/messages      — Get message history
POST   /api/agents                   — Register agent
GET    /api/agents                   — List agents
POST   /api/agents/{id}/token        — Get auth token
WS     /api/rooms/{id}/ws            — WebSocket connection
POST   /api/rooms/{id}/moderate/...  — Moderator actions
```

### Phase 2 — Moderator System (Design: `docs/MODERATOR_DESIGN.md`)

**Goal:** Intelligent meeting moderation following the comprehensive design spec

**Components:**
1. **Moderator State Machine** — FSM managing meeting lifecycle phases (Draft → Opening → Discussion → Convergence → Voting → Closing → Closed)
2. **Agenda Manager** — agenda item tracking with timeboxes and per-item decision requirements
3. **Turn Manager** — multiple strategies (round-robin, queue, free-for-all, directed, timed)
4. **Loop Detector** — semantic similarity-based argument tracking with 3 intervention levels
5. **Topic Drift Detector** — embedding similarity between messages and current agenda item
6. **Inclusion Monitor** — track participation, prompt silent agents
7. **Summary Generator** — LLM-powered summaries at configurable intervals
8. **Decision Tracker** — state machine for proposals (proposed → discussing → voting → accepted/rejected/escalated)
9. **Action Item Extractor** — LLM-powered extraction from decisions
10. **Investigation Budget Manager** — per-agent research budget (default 5 min, max 3 per meeting)
11. **Context Manager** — rolling summary + message window to handle token limits
12. **Anti-Pattern Interventions** — built-in handlers for: infinite loops, dominating agents, analysis paralysis, groupthink, topic drift, silent agents, context explosion
13. **Meeting Templates** — predefined formats for: sprint planning, architecture review, incident post-mortem, decision meeting, brainstorming, standup
14. **Conflict Resolution** — separate positions from interests, steel-manning, common ground finding

**Decision-Making Frameworks (configurable per agenda item):**
- Consensus (with accept vs agree distinction)
- Majority vote
- Roman voting (thumbs up/down/sideways)
- Fist of Five (0-5 confidence scale, blockers must explain)
- RAPID (Recommend/Agree/Perform/Input/Decide)
- Escalate to human

**Agent-Specific Features:**
- Investigation budget with approval workflow
- Partial answers and uncertainty expression
- Async participation support
- Agent capabilities declaration
- Decisions on partial information (with confidence tracking)

**LLM Integration (for moderator intelligence):**
- GLM (zai/glm-5.1) via OpenRouter
- OpenRouter for model flexibility
- LiteLLM abstraction for multi-provider support
- **Tiered model selection:** fast model for detection/classification, quality model for summaries/decisions

### Phase 3 — Agent Connectors

**Goal:** Real agents can join meetings

**Components:**
1. WebSocket connector — agents connect via WS
2. REST webhook connector — agents poll/post via REST  
3. SDK (Python) — simple client library
4. Simulated agents — for testing (using GLM/OpenRouter API)

### Testing Strategy

**Unit Tests:** pytest for all services
**Integration Tests:** WebSocket + API end-to-end
**Simulated Meeting Test:** Multiple fake agents having a real discussion via LLM APIs

**Test Agents (using real LLM calls):**
- Use GLM via OpenRouter for agent reasoning
- Each test agent gets a persona and goal
- Agents respond to messages in a room
- Moderator manages the discussion

### Tech Stack
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic
- **Real-time:** WebSocket (FastAPI native)
- **Database:** PostgreSQL 17 (existing infra, port 25432)
- **Cache/Queue:** Redis
- **LLM:** LiteLLM → GLM/OpenRouter
- **Testing:** pytest, pytest-asyncio, httpx
- **Package Manager:** uv

### Project Structure
```
agent-meeting-platform/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app
│   │   ├── config.py            # Settings
│   │   ├── database.py          # DB connection
│   │   ├── models/              # SQLAlchemy models
│   │   │   ├── room.py
│   │   │   ├── agent.py
│   │   │   ├── message.py
│   │   │   └── decision.py
│   │   ├── schemas/             # Pydantic schemas
│   │   ├── routers/             # API routes
│   │   │   ├── rooms.py
│   │   │   ├── agents.py
│   │   │   ├── messages.py
│   │   │   └── websocket.py
│   │   ├── services/            # Business logic
│   │   │   ├── room_service.py
│   │   │   ├── agent_service.py
│   │   │   ├── message_service.py
│   │   │   └── moderator_service.py
│   │   └── core/
│   │       ├── protocol.py      # Message types & protocol
│   │       ├── events.py        # Event bus
│   │       └── security.py      # Auth
│   ├── migrations/              # Alembic
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_rooms.py
│   │   ├── test_agents.py
│   │   ├── test_messages.py
│   │   ├── test_moderator.py
│   │   └── test_meeting_e2e.py  # Full simulated meeting
│   ├── pyproject.toml
│   └── alembic.ini
├── docs/
│   ├── ARCHITECTURE.md
│   └── PROTOCOL.md
├── PLAN.md
└── README.md
```

## Milestones & Checkpoints

| Milestone | Scope | Success Criteria |
|-----------|-------|-----------------|
| M0: Skeleton | Project setup, DB models, API skeleton | Server starts, health check passes |
| M1: Rooms & Agents | Room CRUD, agent registration, join/leave | Can create rooms, register agents, agents join rooms |
| M2: Messages | Structured messages, history, threads | Can post/retrieve all message types |
| M3: WebSocket | Real-time streaming | Messages appear in real-time via WS |
| M4: Moderator | Turn management, summaries, loop detection | Moderator prevents chaos in simulated meeting |
| M5: LLM Moderator | LLM-powered summaries & decisions | Moderator produces intelligent summaries |
| M6: Simulated Meeting | 3+ LLM agents having a real discussion | Agents discuss a topic, reach a decision |
| M7: SDK | Python SDK for agents | External script can join a meeting |
