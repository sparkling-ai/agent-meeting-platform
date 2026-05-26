"""RoomMember and Message models."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class RoomMember(Base):
    __tablename__ = "room_members"
    __table_args__ = {"schema": "agent_meeting_dev"}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_meeting_dev.rooms.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_meeting_dev.agents.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="participant"
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    room: Mapped["Room"] = relationship(back_populates="members")
    agent: Mapped["Agent"] = relationship(back_populates="room_memberships")

    def __repr__(self) -> str:
        return f"<RoomMember room={self.room_id} agent={self.agent_id} role={self.role!r}>"


class MessageType(StrEnum):
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


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = {"schema": "agent_meeting_dev"}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_meeting_dev.rooms.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_meeting_dev.agents.id", ondelete="SET NULL"), nullable=True
    )
    type: Mapped[str] = mapped_column(
        String(50), nullable=False, default=MessageType.CHAT
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_meeting_dev.messages.id", ondelete="SET NULL"), nullable=True
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    room: Mapped["Room"] = relationship(back_populates="messages")
    agent: Mapped["Agent | None"] = relationship(back_populates="messages")
    parent: Mapped["Message | None"] = relationship(
        remote_side="Message.id", backref="replies"
    )

    def __repr__(self) -> str:
        return f"<Message {self.type!r} in room {self.room_id}>"
