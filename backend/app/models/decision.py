"""Decision and ActionItem models."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = {"schema": "agent_meeting_dev"}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_meeting_dev.rooms.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="proposed"
    )
    proposer_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_meeting_dev.agents.id", ondelete="SET NULL"), nullable=True
    )
    summary: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    room: Mapped["Room"] = relationship(back_populates="decisions")
    proposer: Mapped["Agent | None"] = relationship()
    action_items: Mapped[list["ActionItem"]] = relationship(back_populates="decision")

    def __repr__(self) -> str:
        return f"<Decision {self.title!r} ({self.status})>"


class ActionItem(Base):
    __tablename__ = "action_items"
    __table_args__ = {"schema": "agent_meeting_dev"}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_meeting_dev.rooms.id", ondelete="CASCADE"), nullable=False
    )
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_meeting_dev.decisions.id", ondelete="SET NULL"), nullable=True
    )
    assignee_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_meeting_dev.agents.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    room: Mapped["Room"] = relationship(back_populates="action_items")
    decision: Mapped["Decision | None"] = relationship(back_populates="action_items")
    assignee: Mapped["Agent | None"] = relationship()

    def __repr__(self) -> str:
        return f"<ActionItem {self.description[:50]!r} ({self.status})>"
