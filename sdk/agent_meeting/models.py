"""Data models for the Agent Meeting SDK."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    """WebSocket event types."""
    MESSAGE = "new_message"
    RECENT = "recent_message"
    AGENT_JOINED = "agent_joined"
    AGENT_LEFT = "agent_left"
    MODERATOR_ACTION = "moderator_action"
    VOTE_REQUESTED = "vote_requested"
    TURN_STARTED = "turn_started"
    DECISION_MADE = "decision_made"
    MEETING_CLOSED = "meeting_closed"
    INVESTIGATION_APPROVED = "investigation_approved"
    ERROR = "error"


class MessageType(StrEnum):
    """Message types matching the backend protocol."""
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


@dataclass
class Message:
    """A meeting message."""
    id: str = ""
    room_id: str = ""
    agent_id: str = ""
    agent_name: str = ""
    type: str = "chat"
    content: str = ""
    parent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> Message:
        return cls(
            id=data.get("id", ""),
            room_id=data.get("room_id", ""),
            agent_id=data.get("agent_id", ""),
            agent_name=data.get("agent_name", ""),
            type=data.get("type", "chat"),
            content=data.get("content", ""),
            parent_id=data.get("parent_id"),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", ""),
        )

    def mentions(self, agent_id: str) -> bool:
        """Check if this message mentions a specific agent."""
        return agent_id in self.content or f"@{agent_id}" in self.content


@dataclass
class Room:
    """A meeting room."""
    id: str = ""
    name: str = ""
    topic: str = ""
    status: str = "draft"
    settings: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> Room:
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            topic=data.get("topic", ""),
            status=data.get("status", "draft"),
            settings=data.get("settings", {}),
            created_at=data.get("created_at", ""),
        )


@dataclass
class Agent:
    """A meeting participant."""
    id: str = ""
    name: str = ""
    connector_type: str = "sdk"
    capabilities: dict[str, Any] = field(default_factory=dict)
    auth_token: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> Agent:
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            connector_type=data.get("connector_type", "sdk"),
            capabilities=data.get("capabilities", {}),
            auth_token=data.get("auth_token", ""),
        )


@dataclass
class Decision:
    """A meeting decision."""
    id: str = ""
    room_id: str = ""
    title: str = ""
    description: str = ""
    status: str = "proposed"
    proposer_agent_id: str = ""
    summary: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> Decision:
        return cls(
            id=data.get("id", ""),
            room_id=data.get("room_id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            status=data.get("status", "proposed"),
            proposer_agent_id=data.get("proposer_agent_id", ""),
            summary=data.get("summary", ""),
        )


@dataclass
class ActionItem:
    """A meeting action item."""
    id: str = ""
    room_id: str = ""
    decision_id: str = ""
    assignee_agent_id: str = ""
    description: str = ""
    status: str = "pending"
    due_at: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> ActionItem:
        return cls(
            id=data.get("id", ""),
            room_id=data.get("room_id", ""),
            decision_id=data.get("decision_id", ""),
            assignee_agent_id=data.get("assignee_agent_id", ""),
            description=data.get("description", ""),
            status=data.get("status", "pending"),
            due_at=data.get("due_at", ""),
        )


@dataclass
class ModeratorState:
    """Current moderator state for a room."""
    room_id: str = ""
    phase: str = "draft"
    current_speaker: str = ""
    agenda_items: list[dict] = field(default_factory=list)
    active_proposals: list[dict] = field(default_factory=list)
    parking_lot: list[dict] = field(default_factory=list)
    total_messages: int = 0
    meeting_started_at: str = ""
    meeting_ended_at: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> ModeratorState:
        return cls(
            room_id=data.get("room_id", ""),
            phase=data.get("phase", "draft"),
            current_speaker=data.get("current_speaker", ""),
            agenda_items=data.get("agenda_items", []),
            active_proposals=data.get("active_proposals", []),
            parking_lot=data.get("parking_lot", []),
            total_messages=data.get("total_messages", 0),
            meeting_started_at=data.get("meeting_started_at", ""),
            meeting_ended_at=data.get("meeting_ended_at", ""),
        )


@dataclass
class Event:
    """An event received from the server."""
    type: EventType
    data: dict = field(default_factory=dict)
    message: Message | None = None

    @classmethod
    def from_ws(cls, raw: dict) -> Event:
        event_type = EventType(raw.get("event", "error"))
        data = raw.get("data", {})
        msg = Message.from_dict(data) if "content" in data or "type" in data else None
        return cls(type=event_type, data=data, message=msg)
