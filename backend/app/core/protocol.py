"""Meeting protocol definitions — enums, validation rules."""

import enum

from app.models.message import MessageType


class RoomStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class MemberRole(str, enum.Enum):
    MODERATOR = "moderator"
    PARTICIPANT = "participant"
    OBSERVER = "observer"


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

THREAD_MESSAGE_TYPES = {MessageType.OBJECTION, MessageType.VOTE}
MODERATOR_ONLY_TYPES = {MessageType.DECISION, MessageType.SUMMARY, MessageType.ACTION_ITEM}


def is_valid_status_transition(current: str, target: str) -> bool:
    return target in VALID_STATUS_TRANSITIONS.get(current, set())


def validate_message_type(msg_type: str) -> MessageType | None:
    try:
        return MessageType(msg_type)
    except ValueError:
        return None
