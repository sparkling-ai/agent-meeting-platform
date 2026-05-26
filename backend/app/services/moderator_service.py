"""LLM-powered meeting moderator — state machine engine with turn management,
loop detection, topic drift, inclusion, investigation budgets, and LLM integration."""

import json
import logging
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.protocol import MessageType
from app.models import Message, Decision, ActionItem, RoomMember, Agent
from app.services.llm_service import (
    generate_summary,
    extract_action_items as llm_extract_actions,
    check_convergence,
    moderator_intervene,
    moderator_summarize,
    moderator_check_drift,
    moderator_extract_actions,
    moderator_minutes,
    moderator_steel_man,
)

logger = logging.getLogger(__name__)

# ── Configurable thresholds ──────────────────────────────────────────────────
LOOP_DETECTION_THRESHOLD = 2       # Same argument N times → intervene
SUMMARY_INTERVAL_MESSAGES = 8      # Summary every N messages
DOMINATING_AGENT_THRESHOLD = 0.40  # >40% of messages → dominating
INCLUSION_TURN_GAP = 4             # Prompt silent agent after N turns without speaking
INVESTIGATION_BUDGET_MINUTES = 5.0
INVESTIGATION_MAX_PER_AGENT = 3
INVESTIGATION_MAX_PER_MEETING = 10
VOTE_PASS_THRESHOLD = 0.5          # >50% yes to pass (simple majority)

# ── Turn management ────────────────────────────────────────────────────────────
TURN_QUEUE_ENABLED = True          # Enable active turn management
TURN_TIMEOUT_SECONDS = 30          # Seconds before skipping a silent agent
TURN_SKIP_THRESHOLD = 2           # N consecutive skips before removing from queue
CONVERGENCE_MESSAGE_THRESHOLD = 12 # Messages before suggesting convergence
TOPIC_DRIFT_CHECK_INTERVAL = 6    # Check for drift every N messages


# ── Phase enum ───────────────────────────────────────────────────────────────
class MeetingPhase(StrEnum):
    DRAFT = "draft"
    OPENING = "opening"
    DISCUSSION = "discussion"
    CONVERGENCE = "convergence"
    VOTING = "voting"
    CLOSING = "closing"
    CLOSED = "closed"


VALID_PHASE_TRANSITIONS: dict[MeetingPhase, set[MeetingPhase]] = {
    MeetingPhase.DRAFT: {MeetingPhase.OPENING},
    MeetingPhase.OPENING: {MeetingPhase.DISCUSSION},
    MeetingPhase.DISCUSSION: {MeetingPhase.CONVERGENCE, MeetingPhase.CLOSING},
    MeetingPhase.CONVERGENCE: {MeetingPhase.VOTING, MeetingPhase.DISCUSSION, MeetingPhase.CLOSING},
    MeetingPhase.VOTING: {MeetingPhase.CLOSING, MeetingPhase.DISCUSSION, MeetingPhase.CONVERGENCE},
    MeetingPhase.CLOSING: {MeetingPhase.CLOSED},
    MeetingPhase.CLOSED: set(),
}


# ── Data classes ─────────────────────────────────────────────────────────────
@dataclass
class AgendaItem:
    id: str
    title: str
    description: str = ""
    timebox_minutes: int = 10
    decision_required: bool = False
    owner_agent_id: str | None = None
    status: str = "pending"  # pending | active | resolved | parked
    decision_id: str | None = None


@dataclass
class TrackedProposal:
    proposal_id: str
    proposer_id: str
    content: str
    status: str = "discussing"  # discussing | voting | accepted | rejected | escalated
    votes: list[dict] = field(default_factory=list)  # {agent_id, choice, reasoning}
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class InvestigationRecord:
    agent_id: str
    topic: str
    estimated_minutes: float
    approved: bool
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    returned_at: datetime | None = None
    result: str | None = None  # "findings" | "inconclusive" | "timeout"


@dataclass
class InvestigationBudget:
    agent_id: str
    remaining_minutes: float = INVESTIGATION_BUDGET_MINUTES
    investigations_used: int = 0
    max_investigations: int = INVESTIGATION_MAX_PER_AGENT


@dataclass
class ParkedItem:
    topic: str
    proposed_by: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── Moderator state ─────────────────────────────────────────────────────────
@dataclass
class ModeratorState:
    room_id: str
    phase: MeetingPhase = MeetingPhase.DRAFT
    moderator_agent_id: str | None = None

    # Agenda
    agenda: list[AgendaItem] = field(default_factory=list)
    current_agenda_index: int = -1

    # Turn tracking
    message_history: list[dict] = field(default_factory=list)  # {agent_id, content, type, created_at}
    speak_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    turn_queue: deque[str] = field(default_factory=deque)
    turn_strategy: str = "round_robin"  # round_robin | queue | free | directed
    current_speaker: str | None = None
    turn_skips: dict[str, int] = field(default_factory=lambda: defaultdict(int))  # agent_id → consecutive skips
    last_turn_prompts: dict[str, datetime] = field(default_factory=dict)  # agent_id → last "your turn" prompt time

    # Loop escalation (3 levels)
    loop_escalation: dict[str, int] = field(default_factory=lambda: defaultdict(int))  # topic_key → level (1=nudge, 2=we've heard this, 3=force convergence)

    # Topic drift
    topic_keywords: list[str] = field(default_factory=list)  # extracted from meeting topic
    drift_warnings: int = 0

    # Loop detection
    argument_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    loop_warnings: dict[str, int] = field(default_factory=lambda: defaultdict(int))  # topic → level

    # Proposals & Decisions
    active_proposals: dict[str, TrackedProposal] = field(default_factory=dict)

    # Investigation budgets
    investigation_budgets: dict[str, InvestigationBudget] = field(default_factory=dict)
    active_investigations: list[InvestigationRecord] = field(default_factory=list)
    investigation_count: int = 0

    # Parking lot
    parking_lot: list[ParkedItem] = field(default_factory=list)

    # Counters
    messages_since_summary: int = 0
    total_messages: int = 0
    meeting_started_at: datetime | None = None
    meeting_ended_at: datetime | None = None

    # Decisions and action items (IDs)
    decision_ids: list[str] = field(default_factory=list)
    action_item_ids: list[str] = field(default_factory=list)


# ── Moderator Engine ─────────────────────────────────────────────────────────
class ModeratorEngine:
    """Full LLM-powered moderator state machine for a single room."""

    def __init__(self, room_id: str, moderator_agent_id: str):
        self.state = ModeratorState(room_id=room_id, moderator_agent_id=moderator_agent_id)

    # ── Phase management ─────────────────────────────────────────────────
    def can_transition(self, target: MeetingPhase) -> bool:
        return target in VALID_PHASE_TRANSITIONS.get(self.state.phase, set())

    def transition(self, target: MeetingPhase) -> None:
        if not self.can_transition(target):
            raise ValueError(f"Cannot transition from {self.state.phase} to {target}")
        logger.info("Room %s: phase %s → %s", self.state.room_id, self.state.phase, target)
        self.state.phase = target

    # ── Agenda management ────────────────────────────────────────────────
    def set_agenda(self, items: list[dict]) -> None:
        self.state.agenda = [
            AgendaItem(
                id=str(uuid.uuid4()),
                title=item.get("title", "Untitled"),
                description=item.get("description", ""),
                timebox_minutes=item.get("timebox_minutes", 10),
                decision_required=item.get("decision_required", False),
                owner_agent_id=item.get("owner_agent_id"),
            )
            for item in items
        ]

    def current_agenda_item(self) -> AgendaItem | None:
        if 0 <= self.state.current_agenda_index < len(self.state.agenda):
            return self.state.agenda[self.state.current_agenda_index]
        return None

    def advance_agenda(self) -> AgendaItem | None:
        idx = self.state.current_agenda_index + 1
        while idx < len(self.state.agenda):
            item = self.state.agenda[idx]
            if item.status == "pending":
                self.state.current_agenda_index = idx
                item.status = "active"
                logger.info("Room %s: advanced to agenda item %d: %s",
                            self.state.room_id, idx, item.title)
                return item
            idx += 1
        return None

    def park_agenda_item(self, index: int) -> None:
        if 0 <= index < len(self.state.agenda):
            self.state.agenda[index].status = "parked"
            self.state.parking_lot.append(ParkedItem(
                topic=self.state.agenda[index].title,
                proposed_by="moderator",
            ))

    # ── Opening phase ────────────────────────────────────────────────────
    async def start_meeting(self, db: AsyncSession, room_name: str, room_topic: str | None,
                            agenda_items: list[dict] | None = None,
                            member_names: dict[str, str] | None = None) -> dict:
        """Transition DRAFT → OPENING → DISCUSSION. Returns opening message data."""
        self.transition(MeetingPhase.OPENING)
        self.state.meeting_started_at = datetime.now(timezone.utc)

        if agenda_items:
            self.set_agenda(agenda_items)

        # Extract topic keywords for drift detection
        if room_topic:
            # Simple keyword extraction (remove common stop words)
            stop_words = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                          "being", "have", "has", "had", "do", "does", "did", "will", "would",
                          "could", "should", "may", "might", "shall", "can", "need", "dare",
                          "ought", "used", "to", "of", "in", "for", "on", "with", "at",
                          "by", "from", "as", "into", "through", "during", "before", "after",
                          "above", "below", "between", "out", "off", "over", "under", "again",
                          "further", "then", "once", "and", "but", "or", "nor", "not", "so",
                          "yet", "both", "either", "neither", "each", "every", "all", "any",
                          "few", "more", "most", "other", "some", "such", "no", "only", "own",
                          "same", "than", "too", "very", "just", "because", "if", "when",
                          "while", "how", "what", "which", "who", "whom", "this", "that",
                          "these", "those", "it", "its", "we", "our", "us", "i", "me",
                          "my", "you", "your", "he", "she", "they", "them", "their"}
            words = room_topic.lower().split()
            self.state.topic_keywords = [w.strip(".,!?;:") for w in words
                                         if w.strip(".,!?;:") not in stop_words and len(w) > 2]

        # Initialize turn queue with all members
        if TURN_QUEUE_ENABLED and member_names:
            self.state.turn_queue = deque(member_names.keys())
            self.state.turn_strategy = "round_robin"
            if self.state.turn_queue:
                self.state.current_speaker = self.state.turn_queue[0]

        # Build opening message
        purpose = room_topic or room_name
        agenda_text = "\n".join(
            f"  {i+1}. {item.title} ({item.timebox_minutes} min"
            + (", decision required" if item.decision_required else "") + ")"
            for i, item in enumerate(self.state.agenda)
        ) if self.state.agenda else "  (No agenda items defined)"

        members_text = ""
        if member_names:
            members_text = "\n\n**Participants:** " + ", ".join(member_names.values())

        ground_rules = (
            "1. Stay on topic — flag off-topic items as \"parking lot\"\n"
            "2. No repeating arguments — new information or perspectives only\n"
            "3. Speak concisely — the moderator will summarize and move on\n"
            "4. State disagreements explicitly — silence ≠ agreement\n"
            "5. Decisions require explicit votes — no implicit consensus\n"
            "6. Investigation budget: agents may request up to 5 min to research\n"
            "7. Timeboxes are enforced — the moderator will cut off discussion and force a vote"
        )

        content = (
            f"# Meeting Started: {purpose}\n\n"
            f"**Purpose:** {purpose}\n\n"
            f"**Agenda:**\n{agenda_text}\n\n"
            f"**Ground Rules:**\n{ground_rules}"
            f"{members_text}\n\n"
        )

        # Add turn order if using round_robin
        if TURN_QUEUE_ENABLED and self.state.turn_queue:
            turn_names = []
            for aid in self.state.turn_queue:
                name = (member_names or {}).get(aid, aid[:8])
                turn_names.append(name)
            content += f"**Speaking Order:** {' → '.join(turn_names)} (round-robin)\n\n"
            first_speaker_name = (member_names or {}).get(self.state.current_speaker, "first speaker")
            content += f"🎯 **{first_speaker_name}**, you're up first! What are your thoughts?"
        else:
            content += "Let's begin!"

        # Advance agenda to first item
        first_item = self.advance_agenda()

        self.transition(MeetingPhase.DISCUSSION)

        return {
            "type": "summary",
            "content": content,
            "metadata": {"phase": "opening", "first_agenda_item": first_item.title if first_item else None},
        }

    # ── Message processing (Discussion phase) ────────────────────────────
    async def on_message(self, message: Message, db: AsyncSession,
                         agent_name: str = "") -> list[dict]:
        """Process a new message. Returns list of moderator actions (messages to post)."""
        actions: list[dict] = []

        if self.state.phase == MeetingPhase.CLOSED:
            return actions

        agent_id = str(message.agent_id) if message.agent_id else ""
        msg_type = message.type
        content = message.content

        # Track message
        self.state.total_messages += 1
        self.state.messages_since_summary += 1
        self.state.speak_counts[agent_id] += 1
        self.state.message_history.append({
            "agent_id": agent_id,
            "agent_name": agent_name,
            "content": content,
            "type": msg_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        # ── Proposal tracking ────────────────────────────────────────
        if msg_type == MessageType.PROPOSAL.value:
            proposal = TrackedProposal(
                proposal_id=str(message.id),
                proposer_id=agent_id,
                content=content,
            )
            self.state.active_proposals[str(message.id)] = proposal
            actions.append({
                "action": "announce_proposal",
                "content": f"📋 **Proposal submitted by {agent_name}:** {content}",
                "type": "chat",
            })

        # ── Vote tracking ────────────────────────────────────────────
        elif msg_type == MessageType.VOTE.value:
            parent_id = str(message.parent_id) if message.parent_id else None
            if parent_id and parent_id in self.state.active_proposals:
                proposal = self.state.active_proposals[parent_id]
                # Parse vote choice: handle both "yes" and JSON {"vote": "yes", ...}
                vote_choice = content.lower().strip()
                try:
                    parsed = json.loads(vote_choice)
                    if isinstance(parsed, dict):
                        vote_choice = str(parsed.get("vote", vote_choice)).lower().strip()
                except (json.JSONDecodeError, TypeError):
                    pass
                proposal.votes.append({
                    "agent_id": agent_id,
                    "choice": vote_choice,
                    "reasoning": (message.metadata_ or {}).get("reasoning", ""),
                })
                # Check if all members have voted
                member_count = await self._get_member_count(db)
                if len(proposal.votes) >= member_count:
                    result = await self._tally_votes(proposal, db)
                    actions.extend(result)

        # ── Investigation request ────────────────────────────────────
        elif msg_type == MessageType.REQUEST_CTX.value:
            meta = message.metadata_ or {}
            if meta.get("investigation"):
                inv_result = await self._handle_investigation_request(
                    agent_id, agent_name, meta, db
                )
                if inv_result:
                    actions.append(inv_result)

        # ── Discussion analysis (only for chat/question/objection types) ─
        if msg_type in (MessageType.CHAT.value, MessageType.QUESTION.value,
                        MessageType.OBJECTION.value, MessageType.RISK.value):
            # 1. Turn management — advance turn queue
            turn_action = self._advance_turn(agent_id, agent_name)
            if turn_action:
                actions.append(turn_action)

            # 2. Loop detection (3-level escalation)
            loop_action = self._check_loop_escalated(agent_id, content)
            if loop_action:
                actions.append(loop_action)

            # 3. Dominating agent check
            dom_action = self._check_dominating(agent_id, agent_name)
            if dom_action:
                actions.append(dom_action)

            # 4. Inclusion check
            inclusion_action = await self._check_inclusion(db, agent_name)
            if inclusion_action:
                actions.append(inclusion_action)

            # 5. Topic drift detection
            if self.state.total_messages % TOPIC_DRIFT_CHECK_INTERVAL == 0:
                drift_action = self._check_topic_drift(content)
                if drift_action:
                    actions.append(drift_action)

        # ── Periodic summary ─────────────────────────────────────────
        if self.state.messages_since_summary >= SUMMARY_INTERVAL_MESSAGES:
            summary_action = await self._generate_periodic_summary(db)
            if summary_action:
                actions.append(summary_action)
            self.state.messages_since_summary = 0

        # ── Convergence check ────────────────────────────────────────
        if self.state.total_messages % SUMMARY_INTERVAL_MESSAGES == 0 and self.state.total_messages > 5:
            if self.state.phase == MeetingPhase.DISCUSSION:
                conv_action = await self._check_convergence_trigger(db)
                if conv_action:
                    actions.append(conv_action)

        return actions

    # ── Turn management ─────────────────────────────────────────────
    def _advance_turn(self, agent_id: str, agent_name: str) -> dict | None:
        """Advance the turn queue after an agent speaks."""
        if not TURN_QUEUE_ENABLED or not self.state.turn_queue:
            return None

        # Reset skip count for this agent (they spoke)
        self.state.turn_skips[agent_id] = 0

        # If agent is the current speaker, advance to next
        if self.state.current_speaker == agent_id and len(self.state.turn_queue) > 1:
            # Rotate queue
            self.state.turn_queue.rotate(-1)
            self.state.current_speaker = self.state.turn_queue[0]
            self.state.last_turn_prompts[self.state.current_speaker] = datetime.now(timezone.utc)
            return {
                "action": "turn_prompt",
                "type": "chat",
                "content": f"🎯 **{self.state.current_speaker[:8]}**, your turn! What are your thoughts?",
                "metadata": {"trigger": "turn_management", "next_speaker": self.state.current_speaker},
            }
        return None

    def _check_turn_timeout(self) -> dict | None:
        """Check if the current speaker has timed out."""
        if not TURN_QUEUE_ENABLED or not self.state.current_speaker:
            return None

        last_prompt = self.state.last_turn_prompts.get(self.state.current_speaker)
        if not last_prompt:
            return None

        elapsed = (datetime.now(timezone.utc) - last_prompt).total_seconds()
        if elapsed < TURN_TIMEOUT_SECONDS:
            return None

        # Agent timed out — skip them
        skipped = self.state.current_speaker
        self.state.turn_skips[skipped] = self.state.turn_skips.get(skipped, 0) + 1

        if self.state.turn_skips[skipped] >= TURN_SKIP_THRESHOLD:
            # Remove from queue after too many skips
            self.state.turn_queue = deque(a for a in self.state.turn_queue if a != skipped)
            if not self.state.turn_queue:
                return None
            logger.info("Room %s: removed agent %s from turn queue (too many skips)",
                        self.state.room_id, skipped[:8])

        # Advance to next
        self.state.turn_queue.rotate(-1)
        self.state.current_speaker = self.state.turn_queue[0]
        self.state.last_turn_prompts[self.state.current_speaker] = datetime.now(timezone.utc)

        return {
            "action": "turn_skip",
            "type": "chat",
            "content": (
                f"⏭️ {skipped[:8]} didn't respond in time. "
                f"Moving to **{self.state.current_speaker[:8]}** — your turn!"
            ),
            "metadata": {"trigger": "turn_timeout", "skipped": skipped},
        }

    # ── Loop detection (3-level escalation) ───────────────────────────
    def _check_loop_escalated(self, agent_id: str, content: str) -> dict | None:
        """3-level loop escalation: nudge → we've heard this → force convergence."""
        history = self.state.message_history
        if len(history) < 4:
            return None

        recent_agents = [m["agent_id"] for m in history[-6:]]
        unique = set(recent_agents)

        # If only 2 agents in last 6 messages, potential loop
        if len(unique) <= 2 and len(recent_agents) >= 6:
            agents_str = " & ".join(sorted(unique))
            key = f"loop:{agents_str}"
            self.state.loop_escalation[key] = self.state.loop_escalation.get(key, 0) + 1
            level = self.state.loop_escalation[key]

            if level >= 3:
                # Level 3: Force convergence
                self.state.loop_escalation[key] = 0
                return {
                    "action": "force_convergence",
                    "type": "chat",
                    "content": (
                        "🔴 **We've been going back and forth too long on this point.** "
                        "I'm moving us to a decision. "
                        "Does anyone have a **concrete proposal**? If not, we'll vote on what we have."
                    ),
                    "metadata": {"trigger": "loop_escalation", "level": 3},
                }
            elif level >= 2:
                # Level 2: "We've heard this"
                return {
                    "action": "intervene",
                    "type": "chat",
                    "content": (
                        "🟡 **We've heard this point several times now.** "
                        "Unless someone has genuinely new information or a different angle, "
                        "let's move toward a proposal or decision."
                    ),
                    "metadata": {"trigger": "loop_escalation", "level": 2},
                }
            else:
                # Level 1: Gentle nudge
                return {
                    "action": "intervene",
                    "type": "chat",
                    "content": (
                        "🟢 A quick reminder: we want to add **new perspectives** rather than "
                        "repeating what's been said. Does anyone have a different angle?"
                    ),
                    "metadata": {"trigger": "loop_escalation", "level": 1},
                }
        return None

    # ── Topic drift detection ─────────────────────────────────────────
    def _check_topic_drift(self, content: str) -> dict | None:
        """Detect if discussion has drifted from the meeting topic."""
        if not self.state.topic_keywords:
            return None

        # Simple keyword overlap check
        content_words = set(content.lower().split())
        topic_overlap = sum(1 for kw in self.state.topic_keywords if kw in content_words)
        overlap_ratio = topic_overlap / max(len(self.state.topic_keywords), 1)

        # Also check recent messages
        recent = self.state.message_history[-TOPIC_DRIFT_CHECK_INTERVAL:]
        all_recent_words = set()
        for m in recent:
            all_recent_words.update(m["content"].lower().split() if isinstance(m["content"], str) else [])
        recent_overlap = sum(1 for kw in self.state.topic_keywords if kw in all_recent_words)
        recent_ratio = recent_overlap / max(len(self.state.topic_keywords), 1)

        if overlap_ratio < 0.1 and recent_ratio < 0.15 and self.state.total_messages > 8:
            self.state.drift_warnings += 1
            if self.state.drift_warnings <= 2:
                topic_str = ", ".join(self.state.topic_keywords[:5])
                return {
                    "action": "drift_warning",
                    "type": "chat",
                    "content": (
                        f"🧭 **Topic drift detected.** Let's bring the conversation back to our "
                        f"main topic (keywords: {topic_str}). "
                        f"If this is important, we can park it for a separate discussion."
                    ),
                    "metadata": {"trigger": "topic_drift"},
                }
        else:
            # Reset drift counter when on-topic
            self.state.drift_warnings = max(0, self.state.drift_warnings - 1)

        return None

    # ── Dominating agent check ───────────────────────────────────────
    def _check_dominating(self, agent_id: str, agent_name: str) -> dict | None:
        """Check if one agent is dominating the discussion."""
        if self.state.total_messages < 5:
            return None

        total = self.state.total_messages
        for aid, count in self.state.speak_counts.items():
            ratio = count / total
            if ratio > DOMINATING_AGENT_THRESHOLD and count >= 5:
                # Only intervene once per dominance cycle
                if count % 5 == 0:
                    return {
                        "action": "intervene",
                        "type": "chat",
                        "content": (
                            f"Thank you for your active contributions. "
                            f"Let's hear from other participants before continuing."
                        ),
                        "metadata": {"trigger": "dominating_agent", "agent_id": aid},
                    }
        return None

    # ── Inclusion check ──────────────────────────────────────────────
    async def _check_inclusion(self, db: AsyncSession, current_speaker: str) -> dict | None:
        """Prompt agents who haven't spoken recently."""
        if self.state.total_messages < INCLUSION_TURN_GAP:
            return None

        # Get all member IDs
        result = await db.execute(
            select(RoomMember.agent_id).where(RoomMember.room_id == self.state.room_id)
        )
        member_ids = {str(row[0]) for row in result.all()}

        # Exclude moderator
        member_ids.discard(self.state.moderator_agent_id or "")

        # Find agents who haven't spoken recently
        recent_agent_ids = {m["agent_id"] for m in self.state.message_history[-INCLUSION_TURN_GAP:]}
        silent = member_ids - recent_agent_ids

        if silent:
            # Pick one silent agent
            silent_id = min(silent, key=lambda aid: self.state.speak_counts.get(aid, 0))
            # Get agent name
            agent_result = await db.execute(select(Agent.name).where(Agent.id == silent_id))
            name_row = agent_result.first()
            agent_name = name_row[0] if name_row else silent_id[:8]

            return {
                "action": "prompt_agent",
                "type": "chat",
                "content": f"🫵 **{agent_name}**, you haven't shared your thoughts on this topic yet. What's your perspective?",
                "metadata": {"trigger": "inclusion", "agent_id": silent_id},
            }
        return None

    # ── Investigation handling ───────────────────────────────────────
    async def _handle_investigation_request(self, agent_id: str, agent_name: str,
                                             metadata: dict, db: AsyncSession) -> dict | None:
        """Handle an agent's request for investigation time."""
        topic = metadata.get("topic", "unspecified")
        estimated = metadata.get("estimated_minutes", 3.0)

        # Check meeting-level budget
        if self.state.investigation_count >= INVESTIGATION_MAX_PER_MEETING:
            return {
                "action": "deny_investigation",
                "type": "chat",
                "content": f"❌ Investigation budget for this meeting is exhausted. Please continue without investigation.",
            }

        # Check per-agent budget
        budget = self.state.investigation_budgets.get(agent_id)
        if budget is None:
            budget = InvestigationBudget(agent_id=agent_id)
            self.state.investigation_budgets[agent_id] = budget

        if budget.investigations_used >= budget.max_investigations:
            return {
                "action": "deny_investigation",
                "type": "chat",
                "content": f"❌ {agent_name}, you've used all your investigation slots for this meeting.",
            }
        if estimated > budget.remaining_minutes:
            return {
                "action": "deny_investigation",
                "type": "chat",
                "content": f"❌ {agent_name}, you only have {budget.remaining_minutes:.1f} min of investigation budget remaining (requested {estimated:.1f} min).",
            }

        # Approve
        budget.investigations_used += 1
        budget.remaining_minutes -= estimated
        self.state.investigation_count += 1

        record = InvestigationRecord(
            agent_id=agent_id,
            topic=topic,
            estimated_minutes=estimated,
            approved=True,
        )
        self.state.active_investigations.append(record)

        return {
            "action": "approve_investigation",
            "type": "chat",
            "content": (
                f"✅ **{agent_name}** has been granted {estimated:.1f} min to investigate: \"{topic}\".\n"
                f"(Budget remaining: {budget.remaining_minutes:.1f} min)"
            ),
            "metadata": {
                "trigger": "investigation_approved",
                "agent_id": agent_id,
                "topic": topic,
                "estimated_minutes": estimated,
            },
        }

    # ── Vote tallying ────────────────────────────────────────────────
    async def _tally_votes(self, proposal: TrackedProposal, db: AsyncSession) -> list[dict]:
        """Tally votes on a proposal and create decision if threshold met."""
        actions = []
        yes_count = sum(1 for v in proposal.votes if v["choice"] in ("yes", "agree", "accept", "👍"))
        no_count = sum(1 for v in proposal.votes if v["choice"] in ("no", "disagree", "reject", "👎"))
        total = len(proposal.votes)

        if total == 0:
            return actions

        # Simple majority
        if yes_count / total > VOTE_PASS_THRESHOLD:
            proposal.status = "accepted"
            # Create decision in DB
            decision = Decision(
                room_id=self.state.room_id,
                title=f"Decision on: {proposal.content[:200]}",
                description=proposal.content,
                status="accepted",
                proposer_agent_id=proposal.proposer_id,
                summary=f"Accepted {yes_count}-{no_count} (total votes: {total})",
            )
            db.add(decision)
            await db.flush()
            self.state.decision_ids.append(str(decision.id))

            actions.append({
                "action": "decision_made",
                "type": "decision",
                "content": (
                    f"✅ **Decision Accepted:** {proposal.content[:200]}\n"
                    f"Vote: {yes_count} in favor, {no_count} against"
                ),
                "metadata": {"decision_id": str(decision.id), "status": "accepted"},
            })

            # Extract action items
            try:
                action_texts = await llm_extract_actions(proposal.content)
                for at in action_texts[:5]:
                    ai = ActionItem(
                        room_id=self.state.room_id,
                        decision_id=decision.id,
                        description=at,
                        status="pending",
                    )
                    db.add(ai)
                    await db.flush()
                    self.state.action_item_ids.append(str(ai.id))
                    actions.append({
                        "action": "action_item",
                        "type": "action_item",
                        "content": f"📌 Action Item: {at}",
                        "metadata": {"action_item_id": str(ai.id)},
                    })
            except Exception as e:
                logger.warning("Action item extraction failed: %s", e)

        elif no_count / total >= VOTE_PASS_THRESHOLD:
            proposal.status = "rejected"
            decision = Decision(
                room_id=self.state.room_id,
                title=f"Decision on: {proposal.content[:200]}",
                description=proposal.content,
                status="rejected",
                proposer_agent_id=proposal.proposer_id,
                summary=f"Rejected {no_count}-{yes_count} (total votes: {total})",
            )
            db.add(decision)
            await db.flush()
            self.state.decision_ids.append(str(decision.id))

            actions.append({
                "action": "decision_made",
                "type": "decision",
                "content": (
                    f"❌ **Proposal Rejected:** {proposal.content[:200]}\n"
                    f"Vote: {no_count} against, {yes_count} in favor"
                ),
                "metadata": {"decision_id": str(decision.id), "status": "rejected"},
            })
        else:
            # Deadlock — no clear majority
            actions.append({
                "action": "deadlock",
                "type": "chat",
                "content": (
                    f"⚠️ Vote is tied ({yes_count} for, {no_count} against). "
                    f"Let's discuss further or consider alternatives."
                ),
                "metadata": {"trigger": "deadlock"},
            })

        return actions

    # ── Periodic summary ─────────────────────────────────────────────
    async def _generate_periodic_summary(self, db: AsyncSession) -> dict | None:
        """Generate a periodic discussion summary."""
        recent = self.state.message_history[-SUMMARY_INTERVAL_MESSAGES:]
        if not recent:
            return None

        context = "\n".join(f"{m.get('agent_name', m['agent_id'][:8])}: {m['content']}" for m in recent)
        agenda_item = self.current_agenda_item()
        topic = agenda_item.title if agenda_item else "general discussion"

        try:
            summary = await moderator_summarize(context, topic)
        except Exception:
            try:
                summary = await generate_summary(context)
            except Exception as e:
                logger.warning("Summary generation failed: %s", e)
                return None

        return {
            "action": "summary",
            "type": "summary",
            "content": f"📝 **Discussion Summary ({topic}):**\n{summary}",
        }

    # ── Convergence check ────────────────────────────────────────────
    async def _check_convergence_trigger(self, db: AsyncSession) -> dict | None:
        """Check if discussion should move to convergence."""
        if len(self.state.message_history) < 10:
            return None

        recent = self.state.message_history[-10:]
        context = "\n".join(f"{m['agent_name']}: {m['content']}" for m in recent)

        try:
            result = await check_convergence(context)
            if not result.get("converging", False):
                return None
        except Exception:
            return None

        return {
            "action": "suggest_convergence",
            "type": "chat",
            "content": (
                "🔄 It seems like we're ready to move toward a decision on this topic. "
                "Would anyone like to make a formal proposal, or should we continue discussing?"
            ),
            "metadata": {"trigger": "convergence"},
        }

    # ── Vote initiation ──────────────────────────────────────────────
    async def initiate_vote(self, proposal_id: str | None, db: AsyncSession) -> dict:
        """Move to voting phase and tally existing votes."""
        if self.state.phase not in (MeetingPhase.DISCUSSION, MeetingPhase.CONVERGENCE):
            return {"action": "error", "type": "chat", "content": "Cannot initiate vote in current phase."}

        if self.state.phase == MeetingPhase.DISCUSSION:
            self.transition(MeetingPhase.CONVERGENCE)
        self.transition(MeetingPhase.VOTING)

        target_proposal = None
        if proposal_id and proposal_id in self.state.active_proposals:
            target_proposal = self.state.active_proposals[proposal_id]
            target_proposal.status = "voting"
        elif not proposal_id and self.state.active_proposals:
            # Use the most recent proposal
            target_proposal = list(self.state.active_proposals.values())[-1]
            proposal_id = target_proposal.proposal_id

        # Auto-tally if we have enough votes
        actions = []
        if target_proposal and len(target_proposal.votes) > 0:
            yes_count = sum(1 for v in target_proposal.votes if v["choice"] in ("yes", "agree", "accept"))
            if yes_count >= 2:  # Simple majority: at least 2 yes votes
                tally_results = await self._tally_votes(target_proposal, db)
                actions.extend(tally_results)

        content_text = (
            f"🗳️ **Voting is now open** on: {target_proposal.content[:200] if target_proposal else 'the current proposal'}\n\n"
            "Please cast your vote: **yes** or **no** (with optional reasoning)."
        ) if not actions else actions[-1].get("content", content_text if 'content_text' in dir() else "")

        result = {
            "action": "vote_open",
            "type": "chat",
            "content": content_text,
            "metadata": {"trigger": "vote_open", "proposal_id": proposal_id or "current"},
        }
        if actions:
            # Return the decision result instead
            result = actions[0]
            # Also post action items
            for a in actions[1:]:
                # These will be handled by the router
                pass
        return result

    # ── Force decision ───────────────────────────────────────────────
    async def force_decision(self, db: AsyncSession) -> dict:
        """Force a decision when time has expired."""
        if self.state.phase == MeetingPhase.DISCUSSION:
            self.transition(MeetingPhase.CONVERGENCE)
        if self.state.phase == MeetingPhase.CONVERGENCE:
            self.transition(MeetingPhase.VOTING)

        return {
            "action": "force_vote",
            "type": "chat",
            "content": (
                "⏰ **Time's up.** We're moving to a forced vote. "
                "Please cast your vote now: **yes** or **no**."
            ),
            "metadata": {"trigger": "force_decision"},
        }

    # ── Close meeting ────────────────────────────────────────────────
    async def close_meeting(self, db: AsyncSession) -> dict:
        """Generate final minutes and close the meeting."""
        self.state.meeting_ended_at = datetime.now(timezone.utc)

        # Force-decide proposals by querying DB directly (doesn't rely on in-memory state)
        from app.models.message import Message as MsgModel
        proposal_msgs = (await db.execute(
            select(MsgModel).where(
                MsgModel.room_id == self.state.room_id,
                MsgModel.type == "proposal",
            )
        )).scalars().all()

        for pmsg in proposal_msgs:
            # Check if decision already exists for this proposal
            existing = (await db.execute(
                select(Decision).where(Decision.room_id == self.state.room_id)
            )).scalars().first()
            if existing:
                continue

            # Count votes on this proposal
            vote_msgs = (await db.execute(
                select(MsgModel).where(
                    MsgModel.room_id == self.state.room_id,
                    MsgModel.type == "vote",
                    MsgModel.parent_id == pmsg.id,
                )
            )).scalars().all()

            yes_count = 0
            for v in vote_msgs:
                try:
                    parsed = json.loads(v.content.lower().strip())
                    if isinstance(parsed, dict) and parsed.get("vote") in ("yes", "agree", "accept"):
                        yes_count += 1
                except (json.JSONDecodeError, TypeError):
                    if v.content.lower().strip() in ("yes", "agree", "accept"):
                        yes_count += 1

            if yes_count >= 2:  # Simple majority
                decision = Decision(
                    room_id=self.state.room_id,
                    title=f"Decision on: {pmsg.content[:200]}",
                    description=pmsg.content,
                    status="accepted",
                    proposer_agent_id=pmsg.agent_id,
                    summary=f"Accepted by vote ({yes_count} in favor of {len(vote_msgs)} total votes)",
                )
                db.add(decision)
                await db.flush()
                self.state.decision_ids.append(str(decision.id))

        # Commit any pending decisions
        await db.flush()

        # Generate minutes
        all_msgs = "\n".join(
            f"{m.get('agent_name', m['agent_id'][:8])}: {m['content']}"
            for m in self.state.message_history[-50:]  # Last 50 messages for context
        )

        decisions_text = "\n".join(
            f"- {d.title} ({d.status})" for d in (await db.execute(
                select(Decision).where(Decision.room_id == self.state.room_id)
            )).scalars().all()
        ) or "No decisions recorded."

        parking_text = "\n".join(f"- {p.topic}" for p in self.state.parking_lot) or "None."

        try:
            minutes = await moderator_minutes(
                self.state.room_id,
                decisions=decisions_text,
                actions=all_msgs[-3000:],
            )
        except Exception:
            minutes = f"Meeting concluded. {len(self.state.message_history)} messages exchanged. {len(self.state.decision_ids)} decisions made."

        if self.state.phase not in (MeetingPhase.CLOSED,):
            if self.state.phase != MeetingPhase.CLOSING:
                try:
                    self.transition(MeetingPhase.CLOSING)
                except ValueError:
                    pass
            try:
                self.transition(MeetingPhase.CLOSED)
            except ValueError:
                self.state.phase = MeetingPhase.CLOSED

        return {
            "action": "meeting_closed",
            "type": "summary",
            "content": (
                f"# 📋 Meeting Minutes\n\n{minutes}\n\n"
                f"---\n\n"
                f"**Decisions:**\n{decisions_text}\n\n"
                f"**Parking Lot:**\n{parking_text}\n\n"
                f"Meeting closed. Total messages: {self.state.total_messages}."
            ),
            "metadata": {"phase": "closed"},
        }

    # ── Park topic ───────────────────────────────────────────────────
    def park_topic(self, topic: str, proposed_by: str) -> dict:
        """Add a topic to the parking lot."""
        self.state.parking_lot.append(ParkedItem(topic=topic, proposed_by=proposed_by))
        return {
            "action": "topic_parked",
            "type": "chat",
            "content": f"🅿️ **Parked for later:** \"{topic}\" (suggested by {proposed_by})",
        }

    # ── Get state for API ────────────────────────────────────────────
    def get_state(self) -> dict:
        """Return current moderator state for the API."""
        agenda_item = self.current_agenda_item()
        return {
            "room_id": self.state.room_id,
            "phase": self.state.phase.value,
            "total_messages": self.state.total_messages,
            "messages_since_summary": self.state.messages_since_summary,
            "current_agenda_item": {
                "index": self.state.current_agenda_index,
                "title": agenda_item.title if agenda_item else None,
                "status": agenda_item.status if agenda_item else None,
            } if agenda_item else None,
            "agenda_progress": {
                "total": len(self.state.agenda),
                "resolved": sum(1 for a in self.state.agenda if a.status == "resolved"),
                "active": sum(1 for a in self.state.agenda if a.status == "active"),
                "pending": sum(1 for a in self.state.agenda if a.status == "pending"),
                "parked": sum(1 for a in self.state.agenda if a.status == "parked"),
            },
            "active_proposals": len(self.state.active_proposals),
            "parking_lot_count": len(self.state.parking_lot),
            "investigation_count": self.state.investigation_count,
            "decisions_count": len(self.state.decision_ids),
            "action_items_count": len(self.state.action_item_ids),
            "speak_counts": dict(self.state.speak_counts),
            "meeting_started_at": self.state.meeting_started_at.isoformat() if self.state.meeting_started_at else None,
            "meeting_ended_at": self.state.meeting_ended_at.isoformat() if self.state.meeting_ended_at else None,
        }

    # ── Get summary for API ──────────────────────────────────────────
    def get_summary(self) -> dict:
        """Return current meeting summary."""
        agenda_item = self.current_agenda_item()
        return {
            "room_id": self.state.room_id,
            "phase": self.state.phase.value,
            "current_topic": agenda_item.title if agenda_item else None,
            "total_messages": self.state.total_messages,
            "decisions": len(self.state.decision_ids),
            "action_items": len(self.state.action_item_ids),
            "parking_lot": [p.topic for p in self.state.parking_lot],
            "message_history_count": len(self.state.message_history),
        }

    # ── Advance agenda item ──────────────────────────────────────────
    async def advance_to_next_item(self, db: AsyncSession) -> dict:
        """Resolve current agenda item and advance to next."""
        current = self.current_agenda_item()
        if current:
            current.status = "resolved"

        next_item = self.advance_agenda()
        if next_item:
            return {
                "action": "agenda_advanced",
                "type": "chat",
                "content": f"➡️ Moving to next agenda item: **{next_item.title}** ({next_item.timebox_minutes} min)",
            }
        else:
            # No more items — close meeting
            return await self.close_meeting(db)

    # ── Helpers ───────────────────────────────────────────────────────
    async def _get_member_count(self, db: AsyncSession) -> int:
        result = await db.execute(
            select(func.count()).select_from(RoomMember).where(
                RoomMember.room_id == self.state.room_id,
                RoomMember.role != "moderator",
            )
        )
        return max(result.scalar() or 2, 2)


# ── Moderator Manager (singleton) ────────────────────────────────────────────
class ModeratorManager:
    """Manages ModeratorEngine instances per room."""

    def __init__(self):
        self._engines: dict[str, ModeratorEngine] = {}

    def get(self, room_id: str, moderator_agent_id: str | None = None) -> ModeratorEngine:
        if room_id not in self._engines:
            if not moderator_agent_id:
                moderator_agent_id = str(uuid.uuid4())  # temp ID, should be set properly
            self._engines[room_id] = ModeratorEngine(room_id, moderator_agent_id)
        return self._engines[room_id]

    def remove(self, room_id: str) -> None:
        self._engines.pop(room_id, None)

    def has(self, room_id: str) -> bool:
        return room_id in self._engines


moderator_manager = ModeratorManager()
