"""Predefined moderation task model."""

import uuid

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BaseModelMixin

EXPECTED_OUTPUTS = {
    "topic_review": "Structured summary of key discussion points and recommendations",
    "consensus_vote": "Tally of votes with final consensus decision",
    "risk_assessment": "Identified risks with severity ratings and mitigation suggestions",
}


class ModerationTask(BaseModelMixin, Base):
    __tablename__ = "moderation_tasks"
    __table_args__ = {"schema": "agent_meeting_dev"}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    room_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    expected_output: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<ModerationTask {self.task_type!r} — {self.topic!r} ({self.status})>"
