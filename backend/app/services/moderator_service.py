"""Meeting moderator service — turn management, loop detection, decision tracking."""

import logging
from collections import defaultdict
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.protocol import MessageType
from app.models import Message, Decision, ActionItem, RoomMember
from app.services.llm_service import generate_summary, extract_action_items, check_convergence

logger = logging.getLogger(__name__)

# Configurable thresholds
MAX_CONSECUTIVE_SAME_AGENTS = 4
MAX_MESSAGES_WITHOUT_SUMMARY = 20
CONVERGENCE_CHECK_INTERVAL = 8


class ModeratorService:
    """Manages meeting moderation for a room."""

    def __init__(self, room_id: str):
        self.room_id = room_id
        self.speaking_queue: list[str] = []
        self.speak_counts: dict[str, int] = defaultdict(int)
        self.consecutive_pairs: list[tuple[str, str]] = []
        self.messages_since_summary = 0
        self.total_messages = 0
        self.active_proposals: dict[str, dict] = {}
        self._moderator_agent_id: Optional[str] = None

    def set_moderator_agent(self, agent_id: str) -> None:
        self._moderator_agent_id = agent_id

    async def on_message_posted(self, message: Message, db: AsyncSession) -> list[dict]:
        """Called when a new message is posted. Returns moderator actions to take."""
        actions = []
        self.total_messages += 1
        self.messages_since_summary += 1

        self.speak_counts[message.agent_id] += 1
        self.speaking_queue.append(message.agent_id)

        # Track consecutive speaker pairs for loop detection
        if len(self.speaking_queue) >= 2:
            last_two = (self.speaking_queue[-2], self.speaking_queue[-1])
            self.consecutive_pairs.append(last_two)

        if self._detect_loop():
            logger.info("Loop detected in room %s, requesting summary", self.room_id)
            actions.append({"action": "request_summary", "reason": "loop_detected"})
            self.consecutive_pairs.clear()

        if self.messages_since_summary >= MAX_MESSAGES_WITHOUT_SUMMARY:
            actions.append({"action": "request_summary", "reason": "periodic"})
            self.messages_since_summary = 0

        # Handle proposals
        if message.type == MessageType.PROPOSAL.value:
            self.active_proposals[message.id] = {
                "votes": [],
                "proposer": message.agent_id,
                "content": message.content,
            }
            actions.append({
                "action": "announce_proposal",
                "proposal_id": message.id,
                "content": message.content,
            })

        # Handle votes
        elif message.type == MessageType.VOTE.value:
            parent_id = message.parent_id
            if parent_id and parent_id in self.active_proposals:
                self.active_proposals[parent_id]["votes"].append({
                    "agent_id": message.agent_id,
                    "content": message.content,
                })
                member_count = await self._get_member_count(db)
                votes = self.active_proposals[parent_id]["votes"]
                if len(votes) >= max(2, member_count - 1):
                    actions.append({
                        "action": "finalize_decision",
                        "proposal_id": parent_id,
                        "votes": votes,
                    })

        # Periodic convergence check
        if self.total_messages % CONVERGENCE_CHECK_INTERVAL == 0 and self.total_messages > 5:
            actions.append({"action": "check_convergence"})

        return actions

    def _detect_loop(self) -> bool:
        if len(self.consecutive_pairs) < MAX_CONSECUTIVE_SAME_AGENTS:
            return False
        recent = self.consecutive_pairs[-MAX_CONSECUTIVE_SAME_AGENTS:]
        agents_involved = set()
        for a, b in recent:
            agents_involved.add(a)
            agents_involved.add(b)
        return len(agents_involved) <= 2 and len(recent) >= MAX_CONSECUTIVE_SAME_AGENTS

    def get_next_speaker(self, exclude: Optional[str] = None) -> Optional[str]:
        if not self.speak_counts:
            return None
        candidates = [aid for aid in self.speak_counts if aid != exclude]
        if not candidates:
            return None
        return min(candidates, key=lambda aid: self.speak_counts[aid])

    async def _get_member_count(self, db: AsyncSession) -> int:
        if db is None:
            return 2
        result = await db.execute(
            select(func.count()).select_from(RoomMember).where(RoomMember.room_id == self.room_id)
        )
        return result.scalar() or 2

    def reset_summary_counter(self) -> None:
        self.messages_since_summary = 0


class ModeratorManager:
    """Manages ModeratorService instances per room."""

    def __init__(self):
        self._moderators: dict[str, ModeratorService] = {}

    def get(self, room_id: str) -> ModeratorService:
        if room_id not in self._moderators:
            self._moderators[room_id] = ModeratorService(room_id)
        return self._moderators[room_id]

    def remove(self, room_id: str) -> None:
        self._moderators.pop(room_id, None)


# Singleton
moderator_manager = ModeratorManager()
