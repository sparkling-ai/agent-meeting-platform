"""Meeting protocol definitions — enums, validation rules.

This module must NOT import from app.models to avoid circular imports.
Models import enums from here.
"""

import enum


class RoomStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class MemberRole(str, enum.Enum):
    MODERATOR = "moderator"
    PARTICIPANT = "participant"
    OBSERVER = "observer"


class MessageType(str, enum.Enum):
    CHAT = "chat"
    QUESTION = "question"
    PROPOSAL = "proposal"
    OBJECTION = "objection"
    RISK = "risk"
    DECISION = "decision"
    ACTION_ITEM = "action_item"
    VOTE = "vote"
    SUMMARY = "summary"
    REQUEST_CTX = "request_ctx"


class DecisionStatus(str, enum.Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ActionItemStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


# Valid room status transitions
VALID_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"active", "archived"},
    "active": {"archived"},
    "archived": set(),
}

# Message types that require a parent_id (must be in a thread)
THREAD_MESSAGE_TYPES = {MessageType.OBJECTION, MessageType.VOTE}

# Message types that can only be posted by moderators
MODERATOR_ONLY_TYPES = {MessageType.DECISION, MessageType.SUMMARY, MessageType.ACTION_ITEM}


def is_valid_status_transition(current: str, target: str) -> bool:
    return target in VALID_STATUS_TRANSITIONS.get(current, set())


def validate_message_type(msg_type: str) -> MessageType | None:
    try:
        return MessageType(msg_type)
    except ValueError:
        return None
