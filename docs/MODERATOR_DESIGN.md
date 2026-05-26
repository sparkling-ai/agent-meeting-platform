# Moderator Design Specification

> **Design reference for the LLM-powered meeting moderator.**
> This document translates human meeting best practices into concrete moderator behaviors for an AI agent meeting platform.

---

## Table of Contents

1. [Meeting Lifecycle Phases](#1-meeting-lifecycle-phases)
2. [Moderator Functions & Responsibilities](#2-moderator-functions--responsibilities)
3. [Decision-Making Frameworks](#3-decision-making-frameworks)
4. [Agent-Specific Meeting Rules](#4-agent-specific-meeting-rules)
5. [Anti-Patterns to Avoid](#5-anti-patterns-to-avoid)
6. [Moderator Personality & Behavior](#6-moderator-personality--behavior)
7. [Meeting Templates / Formats](#7-meeting-templates--formats)
8. [Implementation Notes](#8-implementation-notes)

---

## 1. Meeting Lifecycle Phases

The moderator plays a different role at each phase. Every phase maps to concrete system actions.

### 1.1 Pre-Meeting

**Goal:** Ensure everyone arrives prepared and the meeting has a clear purpose.

**Moderator Actions:**
| Action | Implementation |
|--------|---------------|
| Validate agenda exists | Require agenda items when creating a room. Reject meetings without a stated purpose. |
| Share agenda with participants | Push agenda to all joined agents as a system message when room opens. |
| Collect pre-meeting inputs | Allow agents to submit `REQUEST_CTX` or `CHAT` messages with prep materials before the meeting starts. |
| Assign roles | Determine who is decision-maker, who is advisor, who is informed (see RAPID framework). |
| Set meeting parameters | Duration, decision method, timebox per agenda item, speaking order strategy. |
| Capability check | Query each agent's declared capabilities to know who can provide what input. |

**Code Behavior:**
```
ON room_create:
  1. Validate: agenda_items.count >= 1, else reject
  2. Validate: meeting_type is set (decision/brainstorm/standup/etc)
  3. Set room.status = "draft"
  4. Set meeting_parameters from room.settings or defaults

ON agent_join(room):
  1. Record agent.capabilities in room_members
  2. Send welcome message with agenda
  3. If agent has pending prep materials, queue them

ON room_start:
  1. Transition room.status → "active"
  2. Broadcast meeting_start event
  3. Move to Opening phase
```

**Sources:** Google's rule: every meeting has a clear leader who sets the agenda 24 hours in advance. Amazon: pre-read documents distributed before the meeting begins.

### 1.2 Opening

**Goal:** Align all participants on purpose, process, and ground rules.

**Moderator Actions:**
| Action | Implementation |
|--------|---------------|
| Welcome and introductions | Broadcast welcome message. If agents haven't met, share brief capability summaries. |
| State the purpose | Read the meeting objective verbatim. "This meeting will decide X." |
| Walk through agenda | List agenda items with allocated time for each. |
| Set ground rules | Broadcast meeting rules (see below). |
| Designate decision-maker | Explicitly state who has final authority if using RAPID/consensus-with-owner. |
| First check-in | Optional: ask each agent to confirm readiness or share a one-liner context. |

**Ground Rules (broadcast at opening):**
```
1. Stay on topic — flag off-topic items as "parking lot"
2. No repeating arguments — new information or perspectives only
3. Speak concisely — the moderator will summarize and move on
4. State disagreements explicitly — silence ≠ agreement
5. Decisions require explicit votes — no implicit consensus
6. Investigation budget: agents may request up to 5 min to research, must return with findings or "unclear"
7. Timeboxes are enforced — the moderator will cut off discussion and force a vote
```

**Code Behavior:**
```
ON meeting_start:
  1. moderator.broadcast({
       type: "SYSTEM",
       content: welcome_message + purpose + agenda + ground_rules
     })
  2. IF meeting.format == "round_robin":
       moderator.build_turn_queue(all_participants)
  3. moderator.set_phase("discussion")
  4. moderator.start_agenda_timer(first_item)
```

### 1.3 Discussion

**Goal:** Facilitate productive discussion, manage turns, detect problems, keep things on track.

**Moderator Actions:**
| Action | Trigger | Implementation |
|--------|---------|---------------|
| Turn management | After each message | Enforce speaking order. Queue-based or round-robin. |
| Timebox enforcement | Timer expires on agenda item | Warn at 80%, force-move at 100%. |
| Topic drift detection | Message content diverges from agenda item | Flag: "This seems off-topic. Let's park this or create a follow-up." |
| Loop detection | Same argument repeated ≥2 times | Flag: "We've heard this point. Any new information, or should we vote?" |
| Inclusion check | Agent hasn't spoken in N turns | Prompt: "Agent X, do you have input on this?" |
| Summary checkpoint | Every N messages or time interval | Generate and broadcast a brief summary of discussion so far. |
| Question routing | Agent asks a question | Route to specific agent or open to floor. |
| Parking lot | Off-topic but valuable point | Record in parking_lot list, continue current topic. |
| Investigation grant | Agent requests research time | Grant investigation budget (see §4). |

**Code Behavior:**
```
ON message_received(msg):
  1. Validate: msg.agent_id is current speaker (or open floor)
  2. Classify: msg.type → update discussion state
  3. Run loop_detector.check(msg) → flag if duplicate argument
  4. Run topic_monitor.check(msg, current_agenda_item) → flag if drift
  5. Run inclusion_monitor.check() → prompt silent agents
  6. IF msg.type == "QUESTION": route to target or floor
  7. IF msg.type == "PROPOSAL": transition to convergence for this item
  8. Update turn_queue → next speaker
  9. IF agenda_timer.expired(): force convergence

EVERY N messages OR T minutes:
  1. summary = llm.summarize(recent_messages)
  2. broadcast({type: "SUMMARY", content: summary})
```

**Sources:** SessionLab's "Three E's" — Head (purpose), Hands (action), Heart (satisfaction). MIT HR: facilitator explains agenda and tools before discussion begins. Rogelberg: ~50% of meeting time is wasted; active facilitation is the fix.

### 1.4 Convergence

**Goal:** Drive discussion toward a decision or clear outcome.

**Moderator Actions:**
| Action | Trigger | Implementation |
|--------|---------|---------------|
| Propose vote | Discussion has covered key points, or time running out | "We've discussed X. Let's move to a decision." |
| Call for proposals | No clear proposal exists | "Who would like to make a formal proposal?" |
| Clarify options | Multiple competing ideas | Summarize each option clearly, ask agents to vote. |
| Run vote | Proposal submitted | Execute configured voting method (see §3). |
| Force decision | Timebox expired, no consensus | Default to decision-maker's call or escalate to human. |
| Record decision | Vote complete | Create DECISION message with outcome, rationale, dissenting views. |
| Extract action items | Decision made | Parse decision for action items, assign owners and deadlines. |

**Code Behavior:**
```
ON convergence_trigger:
  1. summary = llm.summarize(discussion_on_item)
  2. broadcast({type: "SUMMARY", content: summary})
  3. IF no proposal exists:
       broadcast({type: "SYSTEM", content: "Please submit a PROPOSAL or we'll default to [option]"})
  4. IF proposal exists:
       initiate_vote(proposal, voting_method)
  5. ON vote_complete:
       record_decision(outcome)
       extract_action_items(decision)
       advance_agenda()
```

### 1.5 Closing

**Goal:** Clear end state, everyone knows what happened and what's next.

**Moderator Actions:**
| Action | Implementation |
|--------|---------------|
| Final summary | Generate comprehensive meeting summary covering all decisions. |
| Read back decisions | List every decision with vote counts. |
| Read back action items | List every action item with owner and deadline. |
| Parking lot review | Share any parked topics for future meetings. |
| Next meeting | Schedule or propose next meeting if needed. |
| Explicit close | "This meeting is now closed. Minutes will be distributed." |

**Code Behavior:**
```
ON close_meeting:
  1. final_summary = llm.generate_meeting_summary(all_messages, decisions, action_items)
  2. broadcast({type: "SUMMARY", content: final_summary})
  3. FOR each decision:
       broadcast({type: "DECISION", ...})
  4. FOR each action_item:
       broadcast({type: "ACTION_ITEM", ...})
  5. broadcast({type: "SYSTEM", content: "Meeting closed. Minutes will be shared."})
  6. room.status → "closed"
  7. Persist meeting_minutes to database
```

### 1.6 Post-Meeting

**Goal:** Persistence, follow-up, accountability.

**Moderator Actions:**
| Action | Implementation |
|--------|---------------|
| Distribute minutes | Push structured meeting minutes to all participants (and observers). |
| Create action item tracking | Store action items with status tracking. |
| Schedule follow-ups | If action items have deadlines, create reminder events. |
| Archive room | Set room status to "archived". |
| Analytics | Record meeting metrics (duration, decisions made, participation rate, etc.). |

---

## 2. Moderator Functions & Responsibilities

### 2.1 Agenda Management

**Responsibility:** Keep the meeting on its defined track.

| Function | Detail |
|----------|--------|
| Parse and store agenda | Each item has: title, description, timebox, decision_required (bool), owner |
| Advance agenda items | Move to next item when current is resolved or timeboxed |
| Allow dynamic additions | Participants can propose new agenda items (added to end or parking lot) |
| Track progress | Visual/narrative indicator of where in the agenda the meeting is |

**Data Model:**
```python
class AgendaItem:
    id: str
    title: str
    description: str
    timebox_minutes: int
    decision_required: bool
    owner_agent_id: str | None
    status: "pending" | "active" | "resolved" | "parked"
    decision: Decision | None
```

### 2.2 Turn Management

**Responsibility:** Ensure orderly participation. No one dominates, no one is silenced.

**Strategies:**

| Strategy | When to Use | How It Works |
|----------|------------|--------------|
| **Round-robin** | Structured discussion, equal input needed | Fixed speaking order, each agent speaks once per round |
| **Queue-based** | General discussion | Agents request the floor, moderator grants in order |
| **Free-for-all** | Brainstorming, rapid-fire ideas | Any agent can speak, moderator only intervenes on problems |
| **Directed** | Questions to specific agents | Moderator explicitly asks specific agent to respond |
| **Timed turns** | Heated discussion or long-winded agents | Each agent gets max N seconds/words per turn |

**Code Behavior:**
```python
class TurnManager:
    strategy: TurnStrategy
    queue: deque[agent_id]
    current_speaker: agent_id | None
    turn_history: list[TurnRecord]
    max_turns_per_agent: int  # per agenda item
    max_words_per_turn: int   # or max tokens

    def next_speaker(self) -> agent_id:
        """Return next speaker based on strategy"""
        ...

    def request_floor(self, agent_id: str) -> None:
        """Agent requests to speak"""
        ...

    def check_overuse(self, agent_id: str) -> bool:
        """Has this agent spoken too much?"""
        ...
```

### 2.3 Loop Detection

**Responsibility:** Detect when the same argument is going in circles and break the loop.

**Detection Method:**
1. **Semantic similarity:** Compare each new message against recent messages. If similarity > threshold AND same stance (for/against), flag as potential loop.
2. **Keyword tracking:** Track core arguments. If the same argument appears ≥2 times without new supporting evidence, flag.
3. **Position tracking:** Track each agent's position on each topic. If positions haven't changed after N exchanges, flag.

**Intervention Levels:**
| Level | Trigger | Moderator Action |
|-------|---------|-----------------|
| 1: Gentle nudge | Same argument 2nd time | "I think we've covered this point. Can we hear a new perspective?" |
| 2: Summary + redirect | Same argument 3rd time | Summarize both sides, ask if anyone has NEW information. |
| 3: Force convergence | Same argument 4th+ time | "We're going in circles. Let's vote on this now." |

**Code Behavior:**
```python
class LoopDetector:
    argument_store: list[Argument]  # {agent_id, topic, stance, key_points, count}

    def check(self, message: Message) -> LoopWarning | None:
        """
        1. Extract argument from message (LLM-assisted)
        2. Compare with stored arguments
        3. If similar AND same stance AND no new evidence → warning
        4. Return warning level (1, 2, or 3)
        """
        ...
```

### 2.4 Topic Drift Detection

**Responsibility:** Keep discussion on the current agenda item.

**Detection:**
- Use embedding similarity between message content and current agenda item description
- Threshold: if similarity drops below threshold for N consecutive messages, flag drift

**Intervention:**
- "This seems to be moving away from [current topic]. Let's park this and come back to our agenda item."
- Add drifted topic to parking lot automatically

### 2.5 Decision Tracking

**Responsibility:** Ensure every decision-required agenda item produces a decision.

| State Machine |
|---------------|
| `proposed` → `discussing` → `voting` → `accepted` / `rejected` / `escalated` |

**Decision Record:**
```python
class Decision:
    id: str
    title: str
    proposal_text: str
    proposed_by: agent_id
    status: "proposed" | "discussing" | "voting" | "accepted" | "rejected" | "escalated"
    votes: list[Vote]  # {agent_id, choice, reasoning}
    outcome: str | None
    rationale: str | None
    dissenting_views: list[str]
    decided_at: datetime | None
```

### 2.6 Action Item Extraction

**Responsibility:** Extract concrete tasks from decisions.

**Method:**
- After each decision, LLM parses the decision text and discussion to extract action items
- Each action item needs: description, assignee, deadline, priority

**Code Behavior:**
```python
async def extract_action_items(decision: Decision, messages: list[Message]) -> list[ActionItem]:
    """LLM-powered extraction of action items from a decision"""
    prompt = f"""
    Given this decision: {decision.outcome}
    And the discussion: {summarize(messages)}
    Extract specific, actionable tasks. For each task provide:
    - description (concrete action)
    - suggested_assignee (which agent should do it)
    - priority (high/medium/low)
    - deadline (if mentioned or implied)
    """
    ...
```

### 2.7 Summary Generation

**Responsibility:** Keep all participants aligned with concise summaries.

**When to Summarize:**
| Trigger | Type |
|---------|------|
| Every N messages (configurable) | Progress summary |
| Agenda item complete | Item summary |
| Meeting end | Full meeting summary |
| Loop detected | Summary of positions so far |
| Agent rejoins after investigation | Catch-up summary |

### 2.8 Conflict Resolution

**Responsibility:** Handle disagreements productively.

**Techniques:**
1. **Separate positions from interests:** Ask each side what they actually need (not just what they want)
2. **Find common ground:** Identify what both sides agree on, build from there
3. **Steel-man arguments:** Restate each side's position in its strongest form
4. **Generate alternatives:** Ask "Is there a third option that addresses both concerns?"
5. **Defer to decision-maker:** If consensus impossible, invoke RAPID — the designated decider makes the call

### 2.9 Time Management

**Responsibility:** Keep the meeting within its timebox.

**Rules:**
| Rule | Default | Configurable |
|------|---------|-------------|
| Meeting duration | 30 min | Yes |
| Agenda item timebox | 10 min | Per-item |
| Speaking turn limit | 2 min | Yes |
| Warning at | 80% of timebox | Yes |
| Investigation budget | 5 min | Yes |
| Overtime policy | Force decision | Yes (extend / force / escalate) |

### 2.10 Inclusion

**Responsibility:** Ensure all agents have opportunity to contribute.

**Checks:**
- Track message count per agent per agenda item
- If agent has sent < N messages during an item, prompt them
- Special handling for observer-role agents (they chose not to speak — don't force them)
- Weight inclusion by relevance — an agent whose capabilities match the topic should definitely speak

### 2.11 Convergence Driving

**Responsibility:** Move from discussion to decision.

**Triggers for Convergence:**
1. All agents have spoken at least once on the topic
2. No new arguments in the last N exchanges
3. Timebox nearing expiry
4. Loop detected
5. A formal proposal has been submitted

---

## 3. Decision-Making Frameworks

### 3.1 Framework Comparison

| Framework | Best For | Speed | Buy-in | When to Use |
|-----------|----------|-------|--------|------------|
| **Consensus** | High-stakes, team alignment | Slow | High | Critical decisions where everyone must be on board |
| **Majority Vote** | Clear options, time pressure | Fast | Medium | Multiple options, need a quick resolution |
| **Roman Voting** | Binary decisions, quick check | Very Fast | Medium | Yes/no decisions, go/no-go |
| **Fist of Five** | Confidence check, subtle disagreement | Fast | High | Check alignment, detect quiet concerns |
| **RAPID** | Complex decisions with clear ownership | Medium | Medium | When one agent should own the decision |
| **Escalate to Human** | High stakes beyond agent authority | Varies | N/A | Irreversible decisions, ethical concerns, unknown domain |

### 3.2 Consensus

**How it works:** Discussion continues until all participants agree (or explicitly accept) a proposal.

**Process:**
1. Moderator calls for proposals
2. Proposal submitted (PROPOSAL message)
3. Discussion period (questions, objections, modifications)
4. Modified proposal if needed
5. Consensus check: each agent responds with AGREE / ACCEPT (not ideal but can live with it) / DISAGREE
6. If all AGREE or ACCEPT → decision accepted
7. If any DISAGREE → continue discussion or switch framework

**Implementation Note:** True consensus requires "accept" as an option (not just "agree"). Agents can accept a decision they don't love but can live with. This prevents minority veto.

### 3.3 Majority Vote

**How it works:** Each agent votes. Option with >50% wins.

**Process:**
1. Moderator presents options
2. Each agent casts one VOTE (yes/no or option A/B/C)
3. Moderator tallies and announces result
4. If tie → decision-maker breaks tie or re-discuss

**Message Flow:**
```
MODERATOR → room: "Voting open on: [proposal]. Please cast your vote."
AGENT_A → room: {type: "VOTE", content: "yes", metadata: {reasoning: "..."}}
AGENT_B → room: {type: "VOTE", content: "no", metadata: {reasoning: "..."}}
...
MODERATOR → room: "Vote result: 3 yes, 1 no. Proposal ACCEPTED."
```

### 3.4 Roman Voting

**How it works:** Quick thumbs up (👍), thumbs down (👎), or sideways (➡️) on a proposal.

**Scale:**
- 👍 = I support this
- ➡️ = I'm neutral / need more info
- 👎 = I oppose this

**Implementation:** Same as majority vote but simpler scale. If any 👎, moderator asks for reasoning and brief rebuttal before final vote.

### 3.5 Fist of Five

**How it works:** Each agent shows 0-5 fingers to indicate confidence/agreement level.

**Scale:**
| Fingers | Meaning | Action |
|---------|---------|--------|
| 5 | Full support, will champion this | Proceed |
| 4 | Support, minor concerns | Proceed, note concerns |
| 3 | Neutral, need more discussion | Discuss further |
| 2 | Concerns, significant reservations | Must address before proceeding |
| 1 | Strong opposition, blocking concerns | Stop, major issues to resolve |
| 0 (fist) | Veto / fundamental disagreement | Stop completely, re-evaluate |

**Process:**
1. Moderator calls for Fist of Five vote
2. All agents respond simultaneously (1-5)
3. If any agent votes ≤2, moderator asks them to explain concerns
4. Address concerns, then re-vote (max 3 rounds)
5. If still blocked after 3 rounds → escalate to RAPID or human

**Implementation:**
```python
class FistOfFiveVote:
    agent_id: str
    score: int  # 0-5
    reasoning: str | None  # Required if score <= 2

    @classmethod
    async def run_vote(cls, proposal: str, agents: list[Agent], moderator) -> VoteResult:
        # Collect votes
        votes = await collect_simultaneous_votes(proposal, agents)
        # Check for blockers
        blockers = [v for v in votes if v.score <= 2]
        if blockers:
            # Ask for reasoning, address, re-vote
            ...
        # Calculate average
        avg = sum(v.score for v in votes) / len(votes)
        return VoteResult(proposal=proposal, votes=votes, average=avg, passed=avg >= 3.0)
```

### 3.6 RAPID Framework

**How it works:** Assign clear roles for each decision.

| Role | Letter | Responsibility |
|------|--------|---------------|
| **Recommend** | R | Makes the recommendation / proposal |
| **Agree** | A | Must agree (veto power) — typically legal/compliance |
| **Perform** | P | Executes the decision |
| **Input** | I | Provides input / expertise (consulted but doesn't decide) |
| **Decide** | D | Final decision-maker (breaks ties, overrides) |

**When to Use:**
- When the decision needs a clear owner
- When consensus is unlikely or unnecessary
- When speed matters more than buy-in
- When a human should be the decider

**Implementation:**
- Meeting creator assigns RAPID roles at room creation or per agenda item
- Moderator tracks roles and enforces the process: R proposes → I agents give input → A agrees/rejects → D decides

### 3.7 Escalate to Human

**When to escalate:**
- Decision has significant real-world consequences (money, safety, legal)
- Agents are fundamentally deadlocked after multiple attempts
- Decision requires domain knowledge no agent possesses
- Ethical ambiguity
- Agent capabilities are insufficient to evaluate the options
- The meeting is a recommendation meeting — agents advise, human decides

**Implementation:**
```python
class Escalation:
    topic: str
    summary: str  # LLM-generated summary of the discussion
    options: list[str]  # options considered
    agent_positions: dict[agent_id, str]  # each agent's stance
    recommendation: str | None  # majority recommendation, if any
    reason: str  # why escalation is needed
```

---

## 4. Agent-Specific Meeting Rules

These rules are unique to AI agent meetings and don't have direct human parallels.

### 4.1 Investigation Budget

**Concept:** An agent can pause its participation to research a question, then return with findings.

**Rules:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_investigation_time` | 5 minutes | Maximum wall-clock time for investigation |
| `max_investigations_per_meeting` | 3 per agent | Prevent abuse |
| `investigation_requires_approval` | true | Moderator must approve the investigation request |
| `partial_answer_ok` | true | Agent can return with "inconclusive" or partial findings |

**Process:**
1. Agent sends `INVESTIGATION_REQUEST` message: "I need to research X before I can vote on this."
2. Moderator evaluates: is this relevant? Is the budget available?
3. If approved: agent goes to `investigating` status, timer starts
4. Other agents continue discussion on other topics (or pause if blocking)
5. Agent returns with `INVESTIGATION_RESULT`: findings or "inconclusive"
6. If agent doesn't return in time: moderator notes timeout, proceeds without them on that item

**Code Behavior:**
```python
class InvestigationBudget:
    agent_id: str
    remaining_minutes: float = 5.0
    investigations_used: int = 0
    max_investigations: int = 3

    async def request(self, agent_id: str, topic: str, estimated_time: float) -> Approval:
        if self.investigations_used >= self.max_investigations:
            return Approval(denied=True, reason="Investigation budget exhausted")
        if estimated_time > self.remaining_minutes:
            return Approval(denied=True, reason="Not enough budget remaining")
        return Approval(denied=False)

    async def on_return(self, agent_id: str, result: InvestigationResult):
        self.remaining_minutes -= result.actual_time
        self.investigations_used += 1
```

### 4.2 Partial Answers & Uncertainty

**Rule:** Agents SHOULD express uncertainty rather than fabricate answers.

**Message Types for Uncertainty:**
- `"uncertain"` — I don't have enough information to form a position
- `"needs_investigation"` — I could form a position if I researched X
- `"partial"` — I can speak to aspect A but not aspect B of this question

**Moderator Handling:**
- Partial answers are valid input for decisions
- If all agents are uncertain → escalate to human
- Track uncertainty in decision records: "This decision was made with 60% agent confidence"

### 4.3 Action Items from Unresolved Investigations

**Rule:** When an investigation returns inconclusive, the moderator creates an action item for further research.

**Implementation:**
```python
if result.status == "inconclusive":
    action_item = ActionItem(
        description=f"Investigate: {result.topic}",
        assignee_agent_id=result.agent_id,
        priority="high",
        source_decision=decision.id,
        notes=result.partial_findings
    )
```

### 4.4 Memory & Context Management

**Problem:** LLMs have token limits. Long meetings will exceed context windows.

**Strategies:**

| Strategy | Description |
|----------|------------|
| **Rolling summary** | Keep a running summary; replace old messages with summary text |
| **Message window** | Only include last N messages in context |
| **Relevance filtering** | Include only messages relevant to current agenda item |
| **Key decisions cache** | Always include all decision records regardless of age |
| **Per-agent memory budget** | Each agent gets a token allocation; moderator manages distribution |

**Implementation:**
```python
class ContextManager:
    max_context_tokens: int  # Total budget for meeting context
    summary_threshold: int   # When to summarize (message count)

    def build_context(self, agenda_item: AgendaItem, messages: list[Message]) -> str:
        """
        Build optimized context for current discussion:
        1. Always include: meeting purpose, ground rules, decisions so far
        2. Include: recent messages for current agenda item
        3. Replace: old messages with summaries
        4. Exclude: messages from other agenda items (unless referenced)
        """
        ...
```

### 4.5 Async Participation

**Rule:** Agents don't need to be "live" — meetings can span time.

**Modes:**
| Mode | Description |
|------|------------|
| **Synchronous** | All agents online simultaneously, real-time discussion |
| **Asynchronous** | Agents check in and respond on their own schedule |
| **Hybrid** | Some agents live, some async (moderator bridges the gap) |

**Async Implementation:**
- Agents subscribe to rooms. When they're offline, messages queue.
- When agent reconnects, moderator sends a catch-up summary.
- Decisions can have a voting window (e.g., "votes due within 24 hours").
- Async agents' messages are timestamped but don't block synchronous flow.

### 4.6 Agent Capabilities Declaration

**Rule:** Each agent declares what it can do when joining a meeting.

**Capability Schema:**
```python
class AgentCapabilities:
    agent_id: str
    name: str
    domains: list[str]           # e.g., ["security", "backend", "frontend"]
    can_investigate: bool        # Can this agent do research?
    can_execute_actions: bool    # Can this agent take action on decisions?
    decision_authority: str      # "advisory" | "voting" | "veto" | "decider"
    expertise_level: dict[str, int]  # domain → 1-5 confidence
    tools_available: list[str]   # What tools/APIs this agent has access to
```

**Moderator Use:**
- Route questions to the agent with highest expertise in that domain
- Weight votes by expertise (optional)
- Determine who should investigate what
- Know when to escalate because no agent has relevant expertise

### 4.7 Decisions on Partial Information

**Rule:** It's acceptable to make decisions with incomplete information if explicitly acknowledged.

**Implementation:**
- Decisions include a `confidence_level` field
- Moderator notes when decisions are made without full agent input
- Decision record includes: "Made with 3/5 agents voting, 2 investigating"
- Follow-up meeting scheduled if confidence is below threshold

---

## 5. Anti-Patterns to Avoid

### 5.1 Infinite Loops

**Pattern:** The same argument goes back and forth with no new information.

**Detection:** Loop detector (§2.3)

**Intervention:**
1. "We've discussed this point X times. What new information can anyone add?"
2. "No new information. Moving to vote."
3. Force vote.

**Prevention:**
- Require "new information" rule: agents must add something new, not just restate
- Track argument positions to avoid circling

### 5.2 Dominating Agents

**Pattern:** One agent speaks excessively, drowning out others.

**Detection:**
- Message count per agent exceeds 2x the average
- Speaking time (word count) exceeds threshold

**Intervention:**
- "Thank you, Agent X. Let's hear from others."
- Enforce turn limits
- In extreme cases: mute agent for N turns

**Prevention:**
- Turn time limits from the start
- Round-robin mode for balanced discussions

### 5.3 Analysis Paralysis

**Pattern:** Endless discussion without converging on a decision.

**Detection:**
- Agenda item exceeds timebox
- No proposal submitted after N messages
- Agents keep requesting more information

**Intervention:**
- "We've spent X minutes on this. Let's make a decision with what we have."
- Force a proposal from the most engaged agent
- Default to decision-maker's call

**Prevention:**
- Hard timeboxes with forced convergence
- "Decision required" flag on agenda items
- Default to RAPID if consensus stalls

### 5.4 Groupthink

**Pattern:** Everyone agrees too quickly without critical examination.

**Detection:**
- First vote shows unanimous agreement
- No objections raised during discussion
- No agent plays devil's advocate

**Intervention:**
- "Before we finalize, does anyone see risks or downsides?"
- Assign a devil's advocate role: "Agent X, please argue the opposite position."
- Run a pre-mortem: "Imagine this decision failed. What went wrong?"

**Prevention:**
- For critical decisions, automatically assign devil's advocate
- Require at least one risk/objection before accepting unanimous votes
- Fist of Five instead of binary vote (reveals lukewarm support)

### 5.5 Topic Drift

**Pattern:** Discussion wanders off the current agenda item.

**Detection:** Topic drift detector (§2.4)

**Intervention:**
- "That's an interesting point, but it's not on our agenda. Adding to parking lot."
- "Let's get back to [current topic]."

**Prevention:**
- Clear agenda with timeboxes
- Parking lot mechanism for off-topic but valuable points

### 5.6 Silent Agents

**Pattern:** Agents who join but never speak.

**Detection:**
- Agent has sent 0 messages in N turns
- Agent hasn't voted

**Intervention:**
- "Agent X, you haven't shared your thoughts. What's your position?"
- Direct question: "Agent X, from your expertise in [domain], what do you think?"

**Prevention:**
- Round-robin ensures everyone speaks
- Check-in at the start primes participation

### 5.7 Context Explosion

**Pattern:** Too much information shared, overwhelming the discussion.

**Detection:**
- Message length exceeds token threshold
- Agents copy-paste large documents into chat
- Meeting context window filling up

**Intervention:**
- "Please summarize the key points rather than sharing the full document."
- Auto-summarize long messages
- Suggest using investigation results format (key findings, not raw data)

**Prevention:**
- Message length limits
- Auto-summarization of long inputs
- Pre-meeting document sharing instead of in-meeting dumps

---

## 6. Moderator Personality & Behavior

### 6.1 Core Traits

| Trait | Description | Implementation |
|-------|-------------|----------------|
| **Professional** | Neutral, respectful, never emotional | Use formal language, no humor during decisions |
| **Time-aware** | Always conscious of time constraints | Mention remaining time proactively |
| **Results-oriented** | Focused on outcomes, not process | Keep decisions as the north star |
| **Inclusive** | Ensures all voices are heard | Actively prompt silent agents |
| **Transparent** | Explains moderator actions | "I'm calling a vote because..." |
| **Adaptive** | Adjusts style to meeting format | More structured for decisions, looser for brainstorms |

### 6.2 When to Be Passive

**Let discussion flow when:**
- Agents are engaged and productive
- New ideas are being generated
- No anti-patterns detected
- The discussion is on-topic and progressing
- Agents are building on each other's ideas
- The brainstorming session is flowing well

**Passive behavior:** Just observe, take notes, be ready to intervene.

### 6.3 When to Intervene

| Situation | Intervention |
|-----------|-------------|
| Loop detected | Break the loop, summarize, force convergence |
| Topic drift detected | Redirect to agenda, park the tangent |
| Agent not heard from | Direct question to that agent |
| Agent dominating | Thank them, move to next speaker |
| Timebox at 80% | "We have 2 minutes left on this item." |
| Timebox at 100% | "Time's up. Let's vote." |
| Disagreement escalating | Steel-man both sides, find common ground |
| Investigation request | Approve/deny based on relevance and budget |
| Groupthink risk | Assign devil's advocate, ask for risks |

### 6.4 When to Force a Decision

**Force a decision when:**
- Timebox has expired
- Loop detector has hit level 3
- No new arguments after N exchanges
- Investigation results are inconclusive and can't wait
- Decision-maker invokes their authority (RAPID)
- Meeting is nearing its end time

**How to force:**
1. "We've exhausted discussion on this. Here are the options: [A, B, C]."
2. Run configured vote method.
3. If no majority: decision-maker decides or escalate to human.
4. Record the forced nature of the decision.

### 6.5 Tone Guidelines

**System messages (neutral, informational):**
```
"The current agenda item is: [title]. We have [X] minutes remaining."
"Agent [X] has requested an investigation. Approved. Budget: [Y] minutes."
"Vote result: [outcome]. [N] in favor, [M] against."
```

**Intervention messages (firm but respectful):**
```
"We've discussed this point several times. Can anyone add new information?"
"I'd like to hear from [Agent X] before we move on."
"This topic is outside our current agenda item. I'll add it to the parking lot."
```

**Decision messages (clear, decisive):**
```
"Decision recorded: [title]. Outcome: [accepted/rejected]. Rationale: [summary]."
"Action item: [description]. Assigned to: [agent]. Due: [date]."
```

---

## 7. Meeting Templates / Formats

### 7.1 Template Schema

```python
class MeetingTemplate:
    name: str
    description: str
    default_duration_minutes: int
    agenda_template: list[AgendaItemTemplate]
    voting_method: str  # consensus / majority / roman / fist_of_five / rapid
    turn_strategy: str  # round_robin / queue / free / directed
    ground_rules_override: list[str] | None
    investigation_budget_minutes: float
    moderator_style: str  # structured / moderate / loose
```

### 7.2 Sprint Planning

```yaml
name: Sprint Planning
description: Plan work for the next sprint
duration: 60 minutes
voting: majority
turn_strategy: round_robin
moderator_style: structured

agenda:
  - title: Sprint Review Recap
    timebox: 5
    decision_required: false
  - title: Backlog Grooming
    timebox: 15
    decision_required: false
  - title: Capacity Check
    timebox: 5
    decision_required: false
  - title: Item Estimation
    timebox: 20
    decision_required: true
    voting: fist_of_five  # Per-item confidence
  - title: Sprint Commitment
    timebox: 10
    decision_required: true
    voting: consensus
  - title: Action Items & Assignments
    timebox: 5
    decision_required: false
```

### 7.3 Architecture Review

```yaml
name: Architecture Review
description: Review and approve a technical architecture proposal
duration: 45 minutes
voting: consensus
moderator_style: structured
investigation_budget: 10  # More research time for technical reviews

agenda:
  - title: Proposal Presentation
    timebox: 10
    decision_required: false
  - title: Q&A
    timebox: 10
    decision_required: false
    turn_strategy: queue  # Questions queued
  - title: Risk Assessment
    timebox: 10
    decision_required: false
  - title: Decision
    timebox: 10
    decision_required: true
    voting: fist_of_five
  - title: Action Items
    timebox: 5
    decision_required: false

ground_rules_override:
  - "All agents must state their domain expertise before commenting"
  - "Security agents have veto power on security-related decisions"
```

### 7.4 Incident Post-Mortem

```yaml
name: Incident Post-Mortem
description: Analyze an incident and determine corrective actions
duration: 30 minutes
voting: consensus
moderator_style: moderate

agenda:
  - title: Incident Timeline
    timebox: 5
    decision_required: false
  - title: Root Cause Analysis
    timebox: 10
    decision_required: false
  - title: Contributing Factors
    timebox: 5
    decision_required: false
  - title: Corrective Actions
    timebox: 5
    decision_required: true
    voting: majority
  - title: Prevention Measures
    timebox: 5
    decision_required: true
    voting: consensus

ground_rules_override:
  - "Blameless: focus on systems, not individuals"
  - "No punishment discussion — only improvements"
  - "5 Whys methodology for root cause"
```

### 7.5 Decision Meeting

```yaml
name: Decision Meeting
description: Make a specific decision with input from multiple stakeholders
duration: 30 minutes
voting: rapid  # Requires a decider
moderator_style: structured

agenda:
  - title: Context & Background
    timebox: 5
    decision_required: false
  - title: Options Presentation
    timebox: 5
    decision_required: false
  - title: Discussion
    timebox: 10
    decision_required: false
  - title: Vote / Decision
    timebox: 5
    decision_required: true
    voting: configured_method
  - title: Action Items
    timebox: 5
    decision_required: false

rapid_roles:
  recommend: [agent_id]
  agree: [agent_id]
  perform: [agent_id]
  input: [agent_id, ...]
  decide: [agent_id]  # Could be a human
```

### 7.6 Brainstorming Session

```yaml
name: Brainstorming Session
description: Generate ideas with minimal structure
duration: 30 minutes
voting: none  # No voting in brainstorming
moderator_style: loose
investigation_budget: 0  # No research during brainstorming

agenda:
  - title: Problem Statement
    timebox: 3
    decision_required: false
  - title: Idea Generation
    timebox: 15
    decision_required: false
    turn_strategy: free_for_all
  - title: Idea Clustering
    timebox: 5
    decision_required: false
  - title: Top Ideas Selection
    timebox: 5
    decision_required: true
    voting: majority
  - title: Next Steps
    timebox: 2
    decision_required: false

ground_rules_override:
  - "No criticism during idea generation"
  - "Quantity over quality in idea phase"
  - "Build on others' ideas"
  - "Wild ideas welcome"
```

### 7.7 Status Update / Standup

```yaml
name: Status Update (Standup)
description: Quick sync on progress, plans, and blockers
duration: 15 minutes
voting: none
moderator_style: structured
turn_strategy: round_robin
investigation_budget: 0

agenda:
  - title: Round-Robin Updates
    timebox: 10
    decision_required: false
    per_agent_timebox: 2
  - title: Blocker Discussion
    timebox: 3
    decision_required: false
  - title: Parking Lot & Adjourn
    timebox: 2
    decision_required: false

ground_rules_override:
  - "Each agent: What did you do? What will you do? Any blockers?"
  - "No discussion during updates — questions go to parking lot"
  - "Keep updates under 2 minutes"
```

---

## 8. Implementation Notes

### 8.1 Moderator as a State Machine

The moderator is best implemented as a finite state machine:

```
[DRAFT] → opening → [OPENING] → start_discussion → [DISCUSSION]
    ↑                                                              |
    |                                                              ↓
    |    ← convergence_done ← [CONVERGENCE] ← start_convergence ←┘
    |              |
    |              ↓
    |        [VOTING] → vote_complete → [CLOSING] → [CLOSED]
    |              |
    |              ↓ (if inconclusive)
    |         back to [DISCUSSION]
    |
    ← (if investigation requested) → [INVESTIGATING] → back to [DISCUSSION]
```

### 8.2 LLM Integration Points

The moderator uses LLM for:

| Function | When | Model Requirement |
|----------|------|-------------------|
| Loop detection | Every message | Fast, cheap (classify similarity) |
| Topic drift detection | Every message | Fast, cheap (classify relevance) |
| Summary generation | Periodic / on-demand | Medium quality |
| Action item extraction | After each decision | Medium quality |
| Steel-manning arguments | Conflict resolution | High quality |
| Devil's advocate | Groupthink prevention | High quality |
| Meeting minutes | End of meeting | High quality |

**Recommendation:** Use tiered model selection:
- **Fast path** (detection): Use a fast/cheap model or embedding similarity
- **Quality path** (summaries, decisions): Use GLM or equivalent

### 8.3 Event-Driven Architecture

```python
# Core event flow
ON message_received:
    → classify_message()
    → update_state()
    → run_detectors()  # loop, drift, inclusion
    → check_timers()
    → if triggers_met: run_moderator_actions()
    → advance_turn()

ON timer_expired:
    → handle_timeout()
    → force_convergence() or extend()

ON investigation_return:
    → update_context()
    → notify_agents()
    → resume_discussion()
```

### 8.4 Persistence Requirements

Everything the moderator does must be persisted:
- All messages (with timestamps)
- All state transitions
- All decisions (with votes)
- All action items
- Meeting summary / minutes
- Turn history
- Investigation results

This enables:
- Meeting replay
- Audit trail
- Post-meeting analytics
- Async participant catch-up

### 8.5 API Extensions for Moderator

```
POST   /api/rooms/{id}/moderator/start          — Start meeting
POST   /api/rooms/{id}/moderator/advance        — Advance to next agenda item
POST   /api/rooms/{id}/moderator/vote            — Initiate vote
POST   /api/rooms/{id}/moderator/force-decision  — Force a decision
POST   /api/rooms/{id}/moderator/investigate     — Request investigation
POST   /api/rooms/{id}/moderator/park            — Add topic to parking lot
POST   /api/rooms/{id}/moderator/close           — Close meeting
GET    /api/rooms/{id}/moderator/state           — Get current moderator state
GET    /api/rooms/{id}/moderator/summary         — Get current summary
GET    /api/rooms/{id}/decisions                 — List decisions
GET    /api/rooms/{id}/action-items              — List action items
```

### 8.6 Testing the Moderator

**Test Scenarios:**

1. **Happy path:** 3 agents discuss, reach consensus, moderator summarizes
2. **Loop detection:** 2 agents argue in circles, moderator breaks the loop
3. **Dominating agent:** 1 agent hogs the floor, moderator enforces turns
4. **Silent agent:** 1 agent never speaks, moderator prompts them
5. **Topic drift:** Discussion goes off-topic, moderator redirects
6. **Forced decision:** Time expires, moderator forces a vote
7. **Investigation:** Agent requests research time, returns with findings
8. **Investigation timeout:** Agent doesn't return, moderator proceeds
9. **Groupthink:** Everyone agrees immediately, moderator assigns devil's advocate
10. **Deadlock:** No consensus possible, moderator escalates to human
11. **Async agents:** Agents participate at different times
12. **Context management:** Long meeting exceeds token budget, moderator handles it

---

## References & Sources

- **Meeting Science:** Steven Rogelberg, *The Surprising Science of Meetings* (Oxford, 2019)
- **Google Meeting Rules:** Eric Schmidt & Jonathan Rosenberg, *How Google Works*; Google re:Work
- **Amazon 6-Pager:** Bezos' narrative memo culture; working backwards from press release
- **Agile Ceremonies:** Scrum Guide; Sprint Planning/Standup/Retrospective formats
- **Robert's Rules of Order:** Simplified procedures for formal meetings (motions, seconds, debate, vote)
- **Fist of Five:** Agile consensus-building technique (Scrum.org)
- **RAPID Framework:** Bain & Company decision-rights tool
- **SessionLab:** Meeting facilitation patterns, IDOARRT agenda design
- **MIT HR:** Meeting design and facilitation basics
- **Sherpany:** Executive meeting facilitation techniques

---

*Document version: 1.0 — 2026-05-26*