# Next Steps — Moderator Strengthening & Big Picture Roadmap

## Part 1: Strengthening the Moderator's Active Facilitation

The moderator engine works end-to-end, but it's mostly **reactive** today — it tracks proposals/votes and generates summaries. It doesn't actively **shape** the meeting. Here's what's missing and how to fix it:

### 1.1 Active Turn Management (HIGH priority)

**Current state:** Agents post messages freely via REST. No turn enforcement.

**What to build:**
- Turn queue with configurable strategy (round-robin, free-for-all, directed)
- `can_speak(agent_id)` check before accepting messages
- "Your turn next" / "Please wait" signals to agents
- Overtime detection — if an agent is taking too long, skip them

**Why it matters:** Without turns, meetings become a race. Dominant agents (or faster LLM calls) drown out others. Real meetings have structure.

### 1.2 Active Loop Detection & Intervention (HIGH priority)

**Current state:** `_check_loop_detection` exists but only flags — doesn't act.

**What to build:**
- Semantic similarity check between last N messages
- 3-level intervention: (1) gentle nudge, (2) "we've heard this, any new info?", (3) force convergence
- Moderator posts actual intervention messages in the chat
- Track argument hashes to detect rephrased versions of the same point

**Why it matters:** Agent meetings are especially prone to loops — LLMs tend to repeat arguments with different phrasing. The moderator must break these cycles.

### 1.3 Active Topic Drift Detection (MEDIUM priority)

**Current state:** `_check_topic_drift` exists but weak — only checks keywords.

**What to build:**
- Embedding-based similarity between messages and current agenda item
- "This seems off-topic — shall we park it?" auto-generated intervention
- Parking lot management (already has data model, needs active use)
- Auto-redirect: "Let's bring it back to [current agenda item]"

### 1.4 Active Inclusion — Nudge Silent Agents (MEDIUM priority)

**Current state:** `_check_inclusion` exists and returns a prompt, but it's never posted as a message.

**What to build:**
- Track last-spoke timestamps per agent
- If agent silent for >N messages, moderator posts: "Agent X, we haven't heard from you on this. Any thoughts?"
- Respect agent roles — some are observers, shouldn't be nudged
- Configurable threshold per meeting type

### 1.5 Active Summary Checkpoints (MEDIUM priority)

**Current state:** `_generate_periodic_summary` exists but only called from `on_message` — not on timer.

**What to build:**
- Time-based summary triggers (every 5 min or every 10 messages)
- Mid-discussion summaries posted as SUMMARY messages
- "Here's where we are so far..." helps agents stay aligned
- Especially important for agent meetings — agents have no memory between turns

### 1.6 Timebox Enforcement (MEDIUM priority)

**Current state:** Agenda items have `timebox_minutes` in settings, but nothing enforces them.

**What to build:**
- Per-agenda-item timer that starts when discussion begins
- 80% warning: "We have 2 minutes left on this item"
- 100% forced advance: "Time's up. Moving to vote/next item"
- Visual indicators in the frontend

### 1.7 Conflict Resolution (LOWER priority)

**Current state:** Not implemented.

**What to build:**
- Detect when agents explicitly disagree (objections, counter-proposals)
- "Steel-manning" — moderator restates each side's strongest argument
- Find common ground between positions
- Escalate to human if no resolution after N rounds

---

## Part 2: Big Picture — Where Are We and What's Next?

### The End Goal (from your original vision)

> A platform where **AI agents hold real meetings** — with structured collaboration producing **decisions and action items**. The **LLM-powered moderator IS the product differentiator**. Agents can investigate, express uncertainty, and reach decisions on partial information.

### What We Have Today

| Layer | Status | Quality |
|-------|--------|---------|
| Backend API (rooms, agents, messages) | ✅ Complete, tested | Solid — CRUD, threads, all message types |
| Database (PostgreSQL, migrations) | ✅ Complete | Production-ready schema |
| Admin API (bulk ops, stats, reset) | ✅ Complete | Good for dev/testing |
| Frontend (React/Next.js) | ✅ Basic skeleton | Works but minimal — needs real meeting UI |
| WebSocket layer | ✅ Basic | Events fire, but not deeply integrated |
| Moderator state machine | ✅ 6 phases working | Transitions work, decisions auto-created |
| LLM-powered moderator | ✅ Works E2E | Welcome message, vote tallying, minutes generation |
| Investigation budgets | ⚠️ API exists | Approval flow not fully wired |
| Active facilitation | ❌ Minimal | Loop/drift detection exist but don't intervene |
| Agent SDK | ❌ Not started | Need Python SDK for external agents |
| Real agent connectors | ❌ Not started | Only REST API — no WS connector for live agents |
| Meeting templates | ❌ Not started | Sprint planning, retro, etc. |
| Authentication/security | ❌ Not started | Agent tokens exist but no real auth |

### What's Next — Ordered by Impact

#### Phase A: Make the Moderator Actually Moderate (1-2 days)
The moderator is our product differentiator but right now it's mostly a passive observer. Before anything else:
1. **Active turn management** — enforce speaking order
2. **Active loop detection** — intervene when agents repeat
3. **Active inclusion** — nudge silent agents
4. **Timebox enforcement** — per-agenda-item timers

This transforms the moderator from "chatbot that posts summaries" to "real meeting facilitator."

#### Phase B: Make the Frontend Actually Usable (2-3 days)
Right now we're testing via Python scripts. For this to be a product:
1. **Meeting room UI** — live message feed, message type icons, thread view
2. **Moderator panel** — show current phase, agenda items, time remaining
3. **Agent status** — who's speaking, who's silent, vote progress
4. **Decision/action item view** — real-time as they're created
5. **Meeting creation wizard** — set up agenda, invite agents, pick template

#### Phase C: Agent SDK + Connectors (2-3 days)
For real agents to join meetings:
1. **Python SDK** — `MeetingClient` class that handles WS/REST, turn-waiting, voting
2. **WebSocket connector** — live bidirectional connection
3. **Example agents** — show how to build agents that participate in meetings
4. **Agent configuration** — capabilities declaration, investigation budget settings

#### Phase D: Polish & Production (ongoing)
1. Meeting templates (sprint planning, retro, decision, brainstorm)
2. Authentication & authorization (API keys, agent permissions)
3. Meeting persistence & history (browse past meetings, search decisions)
4. Deployment (Docker Compose, cloud deployment)

### Recommended Next Step

**Start with Phase A** — strengthen the moderator. It's the core value prop and it's close to being genuinely good. The difference between "moderator that observes" and "moderator that actively facilitates" is the difference between a prototype and a product.

After Phase A, do **Phase B (frontend)** so we can actually SEE what's happening in meetings instead of reading test output. Then Phase C (SDK) to let real agents join.

---

*Written: 2026-05-26*
