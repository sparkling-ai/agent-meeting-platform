"""Pydantic schemas for API request/response."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.core.protocol import MemberRole, MessageType, RoomStatus


# ── Agent ──
class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    connector_type: str = "rest"
    capabilities: dict | None = None
    owner_id: str | None = None


class AgentResponse(BaseModel):
    id: str
    name: str
    connector_type: str
    capabilities: dict | None
    owner_id: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class AgentTokenResponse(BaseModel):
    agent_id: str
    token: str


# ── Room ──
class RoomCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    topic: str | None = None
    created_by: str | None = None
    settings: dict | None = None


class RoomResponse(BaseModel):
    id: str
    name: str
    topic: str | None
    status: str
    created_by: str | None
    settings: dict | None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class RoomMemberResponse(BaseModel):
    agent_id: str
    agent_name: str
    role: str
    joined_at: datetime


class RoomDetailResponse(RoomResponse):
    members: list[RoomMemberResponse] = []


class RoomJoinRequest(BaseModel):
    agent_id: str
    role: MemberRole = MemberRole.PARTICIPANT


class RoomStatusUpdate(BaseModel):
    status: RoomStatus


# ── Message ──
class MessageCreate(BaseModel):
    agent_id: str
    type: MessageType
    content: str = Field(..., min_length=1)
    parent_id: str | None = None
    metadata: dict | None = None


class MessageResponse(BaseModel):
    id: str
    room_id: str
    agent_id: str
    type: str
    content: str
    parent_id: str | None
    metadata_: dict | None = Field(None, alias="metadata")
    created_at: datetime
    model_config = {"from_attributes": True, "populate_by_name": True}


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]
    total: int
    offset: int
    limit: int
