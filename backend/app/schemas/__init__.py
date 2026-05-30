"""Pydantic schemas for API request/response."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, ConfigDict, model_validator

from app.models.message import MessageType


# Agent
class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    connector_type: str = "rest"
    capabilities: dict | None = None


class AgentResponse(BaseModel):
    id: uuid.UUID
    name: str
    connector_type: str
    capabilities: dict | None
    created_at: datetime
    model_config = {"from_attributes": True}


class AgentTokenResponse(BaseModel):
    agent_id: uuid.UUID
    token: str


# Room
class RoomCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    topic: str | None = None
    settings: dict | None = None
    visibility: str = Field(default="unlisted", pattern="^(public|unlisted|private)$")
    max_participants: int = Field(default=20, ge=1, le=100)


class RoomResponse(BaseModel):
    id: uuid.UUID
    name: str
    topic: str | None
    status: str
    settings: dict | None
    visibility: str = "unlisted"
    max_participants: int = 20
    owner_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class RoomMemberResponse(BaseModel):
    agent_id: uuid.UUID
    agent_name: str
    role: str
    joined_at: datetime


class RoomDetailResponse(RoomResponse):
    members: list[RoomMemberResponse] = []


class RoomJoinRequest(BaseModel):
    agent_id: uuid.UUID
    role: str = "member"


class RoomStatusUpdate(BaseModel):
    status: str


# RBAC
class RoomInviteRequest(BaseModel):
    agent_id: uuid.UUID
    role: str = Field(default="member", pattern="^(owner|moderator|member|observer)$")


class RoomRoleUpdate(BaseModel):
    role: str = Field(..., pattern="^(owner|moderator|member|observer)$")


class AdminUserUpdate(BaseModel):
    role: str | None = Field(None, pattern="^(admin|user|agent|viewer)$")
    is_active: bool | None = None


# Message
class MessageCreate(BaseModel):
    agent_id: uuid.UUID
    type: MessageType = MessageType.CHAT
    content: str = Field(..., min_length=1)
    parent_id: uuid.UUID | None = None
    metadata: dict | None = None


def _message_from_attributes(data: Any) -> dict:
    """Extract fields from a Message ORM object, handling metadata_ column."""
    if isinstance(data, dict):
        return data
    return {
        "id": data.id,
        "room_id": data.room_id,
        "agent_id": data.agent_id,
        "type": data.type,
        "content": data.content,
        "parent_id": data.parent_id,
        "msg_metadata": getattr(data, 'metadata_', None),
        "created_at": data.created_at,
    }


class MessageResponse(BaseModel):
    id: uuid.UUID
    room_id: uuid.UUID
    agent_id: uuid.UUID | None
    agent_name: str | None = None
    type: str
    content: str
    parent_id: uuid.UUID | None
    msg_metadata: dict | None = Field(None, serialization_alias="metadata")
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _from_attributes(cls, data: Any) -> Any:
        if hasattr(data, "metadata_"):
            return _message_from_attributes(data)
        return data


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]
    total: int
    offset: int
    limit: int


# Moderation Task
VALID_TASK_TYPES = ("topic_review", "consensus_vote", "risk_assessment")


class PredefinedTaskCreate(BaseModel):
    task_type: str = Field(..., pattern="^(topic_review|consensus_vote|risk_assessment)$")
    topic: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    room_id: str | None = None


class PredefinedTaskResponse(BaseModel):
    id: uuid.UUID
    task_type: str
    topic: str
    description: str | None
    status: str
    expected_output: str
    result: str | None = None
    room_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ExecuteTaskRequest(BaseModel):
    room_id: str | None = None


class PredefinedTaskListResponse(BaseModel):
    tasks: list[PredefinedTaskResponse]
    total: int
