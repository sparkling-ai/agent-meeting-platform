"""LLM-powered meeting moderator — state machine engine with turn management,
loop detection, topic drift, inclusion, investigation budgets, and LLM integration."""

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
    turn_strategy: str = "free"  # round_robin | queue | free | directed

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
            f"Let's begin!"
        )

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
                proposal.votes.append({
                    "agent_id": agent_id,
                    "choice": content.lower().strip(),
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
            # 1. Loop detection (simple heuristic — same agent pair pattern)
            loop_action = self._check_loop_simple(agent_id)
            if loop_action:
                actions.append(loop_action)

            # 2. Dominating agent check
            dom_action = self._check_dominating(agent_id, agent_name)
            if dom_action:
                actions.append(dom_action)

            # 3. Inclusion check
            inclusion_action = await self._check_inclusion(db, agent_name)
            if inclusion_action:
                actions.append(inclusion_action)

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

    # ── Loop detection (heuristic) ───────────────────────────────────
    def _check_loop_simple(self, agent_id: str) -> dict | None:
        """Detect if the same small set of agents keeps going back and forth."""
        history = self.state.message_history
        if len(history) < 4:
            return None

        recent_agents = [m["agent_id"] for m in history[-6:]]
        unique = set(recent_agents)

        # If only 2 agents in last 6 messages, potential loop
        if len(unique) <= 2 and len(recent_agents) >= 6:
            agents_str = " and ".join(unique)
            key = f"loop:{agents_str}"
            self.state.loop_warnings[key] = self.state.loop_warnings.get(key, 0) + 1

            level = self.state.loop_warnings[key]
            if level >= LOOP_DETECTION_THRESHOLD:
                self.state.loop_warnings[key] = 0  # reset after intervention
                return {
                    "action": "intervene",
                    "type": "chat",
                    "content": (
                        "⚠️ We seem to be going in circles on this point. "
                        "Can anyone add **new information or a different perspective**? "
                        "Otherwise, we should move to a vote."
                    ),
                    "metadata": {"trigger": "loop_detected", "level": level},
                }
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
        """Move to voting phase for a proposal."""
        if self.state.phase not in (MeetingPhase.DISCUSSION, MeetingPhase.CONVERGENCE):
            return {"action": "error", "type": "chat", "content": "Cannot initiate vote in current phase."}

        if self.state.phase == MeetingPhase.DISCUSSION:
            self.transition(MeetingPhase.CONVERGENCE)
        self.transition(MeetingPhase.VOTING)

        if proposal_id and proposal_id in self.state.active_proposals:
            proposal = self.state.active_proposals[proposal_id]
            proposal.status = "voting"
        else:
            proposal_id = proposal_id or "current"

        return {
            "action": "vote_open",
            "type": "chat",
            "content": (
                f"🗳️ **Voting is now open** on: {self.state.active_proposals.get(proposal_id, TrackedProposal(proposal_id=proposal_id, proposer_id='', content='the current proposal')).content[:200]}\n\n"
                "Please cast your vote: **yes** or **no** (with optional reasoning)."
            ),
            "metadata": {"trigger": "vote_open", "proposal_id": proposal_id},
        }

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
