# Agent Meeting Platform — Implementation Plan

## Project: Agent Meeting Platform (working name: "Collab")

### Phase 0 — Architecture & Setup (NOW)

**Goal:** Repo structure, architecture doc, meeting protocol definition, project skeleton

**Deliverables:**
- [x] Project plan
- [x] **Moderator design spec** → `docs/MODERATOR_DESIGN.md`
- [ ] Architecture doc
- [ ] Meeting protocol spec
- [ ] Repo structure (FastAPI + Next.js monorepo)
- [ ] Docker compose (PostgreSQL + Redis)
- [ ] Backend skeleton (FastAPI app with routes)
- [ ] Database models (SQLAlchemy)
- [ ] Unit test framework (pytest)

### Phase 1 — Core Backend (Parallel Subagents)

**Goal:** Rooms, messages, agent management, WebSocket real-time

**Components:**
1. **Room Service** — CRUD rooms, join/leave, lifecycle
2. **Message Service** — structured messages (QUESTION/PROPOSAL/etc), threads, mentions
3. **Agent Service** — agent registration, auth tokens, capabilities
4. **WebSocket Layer** — real-time message streaming, event bus
5. **Moderator Engine** — speaking turns, summary, loop prevention, convergence

**Database Schema:**
```sql
-- Rooms
rooms: id, name, topic, status(draft/active/archived), created_by, created_at, settings(jsonb)

-- Agents  
agents: id, name, connector_type, capabilities(jsonb), auth_token, owner_id, created_at

-- Room Members
room_members: room_id, agent_id, role(moderator/participant/observer), joined_at

-- Messages
messages: id, room_id, agent_id, type(chat/question/proposal/objection/risk/decision/action_item/vote/summary), 
          content, parent_id(thread), metadata(jsonb), created_at

-- Decisions
decisions: id, room_id, title, status(proposed/accepted/rejected), decided_at, summary

-- Action Items
action_items: id, room_id, decision_id, assignee_agent_id, description, status, due_at

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
