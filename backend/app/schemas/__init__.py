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


class RoomResponse(BaseModel):
    id: uuid.UUID
    name: str
    topic: str | None
    status: str
    settings: dict | None
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
    role: str = "participant"


class RoomStatusUpdate(BaseModel):
    status: str


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
