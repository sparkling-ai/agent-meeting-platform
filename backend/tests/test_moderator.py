"""Unit tests for the moderator service."""

import pytest

from app.services.moderator_service import ModeratorService


class MockMessage:
    def __init__(self, id: str, agent_id: str, type: str, content: str, parent_id: str | None = None):
        self.id = id
        self.agent_id = agent_id
        self.type = type
        self.content = content
        self.parent_id = parent_id


def _aid(i: int) -> str:
    return f"agent-{i}"


def _mid(i: int) -> str:
    return f"msg-{i}"


class TestTurnManagement:
    def test_speak_counts_tracked(self):
        mod = ModeratorService("room-1")
        a1, a2, a3 = _aid(1), _aid(2), _aid(3)

        mod.speak_counts[a1] += 1
        mod.speak_counts[a2] += 1
        mod.speak_counts[a2] += 1

        assert mod.speak_counts[a1] == 1
        assert mod.speak_counts[a2] == 2

    def test_get_next_speaker_picks_least_spoken(self):
        mod = ModeratorService("room-1")
        a1, a2, a3 = _aid(1), _aid(2), _aid(3)

        mod.speak_counts[a1] = 5
        mod.speak_counts[a2] = 2
        mod.speak_counts[a3] = 3

        assert mod.get_next_speaker() == a2

    def test_get_next_speaker_excludes(self):
        mod = ModeratorService("room-1")
        a1, a2, a3 = _aid(1), _aid(2), _aid(3)

        mod.speak_counts[a1] = 1
        mod.speak_counts[a2] = 1
        mod.speak_counts[a3] = 5

        assert mod.get_next_speaker(exclude=a2) == a1

    def test_get_next_speaker_empty(self):
        mod = ModeratorService("room-1")
        assert mod.get_next_speaker() is None


class TestLoopDetection:
    def test_no_loop_few_messages(self):
        mod = ModeratorService("room-1")
        a1, a2 = _aid(1), _aid(2)

        mod.consecutive_pairs = [(a1, a2), (a2, a1), (a1, a2)]
        assert not mod._detect_loop()

    def test_loop_detected_same_two_agents(self):
        mod = ModeratorService("room-1")
        a1, a2 = _aid(1), _aid(2)

        mod.consecutive_pairs = [(a1, a2)] * 6
        assert mod._detect_loop()

    def test_no_loop_different_agents(self):
        mod = ModeratorService("room-1")
        a1, a2, a3, a4 = _aid(1), _aid(2), _aid(3), _aid(4)

        mod.consecutive_pairs = [(a1, a2), (a2, a3), (a3, a4), (a4, a1)]
        assert not mod._detect_loop()

    def test_loop_cleared_after_detection(self):
        mod = ModeratorService("room-1")
        a1, a2 = _aid(1), _aid(2)

        mod.consecutive_pairs = [(a1, a2)] * 6
        assert mod._detect_loop()
        mod.consecutive_pairs.clear()
        assert not mod._detect_loop()


class TestDecisionTracking:
    @pytest.mark.asyncio
    async def test_proposal_creates_tracking(self):
        from app.core.protocol import MessageType
        mod = ModeratorService("room-1")
        a1 = _aid(1)

        msg = MockMessage(_mid(1), a1, MessageType.PROPOSAL.value, "We should use Python")
        actions = await mod.on_message_posted(msg, db=None)

        assert any(a["action"] == "announce_proposal" for a in actions)
        assert len(mod.active_proposals) == 1

    @pytest.mark.asyncio
    async def test_summary_requested_periodically(self):
        from app.services.moderator_service import MAX_MESSAGES_WITHOUT_SUMMARY
        mod = ModeratorService("room-1")
        a1, a2 = _aid(1), _aid(2)

        has_summary = False
        for i in range(MAX_MESSAGES_WITHOUT_SUMMARY + 2):
            msg = MockMessage(_mid(i), a1 if i % 2 == 0 else a2, "chat", f"msg {i}")
            actions = await mod.on_message_posted(msg, db=None)
            if any(a["action"] == "request_summary" for a in actions):
                has_summary = True
                break

        assert has_summary, "Summary should be requested after MAX_MESSAGES_WITHOUT_SUMMARY"

    @pytest.mark.asyncio
    async def test_votes_trigger_decision(self):
        from app.core.protocol import MessageType
        mod = ModeratorService("room-1")
        a1, a2, a3 = _aid(1), _aid(2), _aid(3)

        # Proposal
        proposal_id = _mid(1)
        msg = MockMessage(proposal_id, a1, MessageType.PROPOSAL.value, "Let's do X")
        await mod.on_message_posted(msg, db=None)

        # Votes — enough for threshold (2 votes, member_count - 1 with fallback of 2)
        msg2 = MockMessage(_mid(2), a2, MessageType.VOTE.value, "yes", parent_id=proposal_id)
        actions = await mod.on_message_posted(msg2, db=None)

        msg3 = MockMessage(_mid(3), a3, MessageType.VOTE.value, "yes", parent_id=proposal_id)
        actions = await mod.on_message_posted(msg3, db=None)

        assert any(a["action"] == "finalize_decision" for a in actions)
