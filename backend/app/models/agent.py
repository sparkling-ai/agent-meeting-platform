"""Agent model."""

import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModelMixin


class Agent(BaseModelMixin, Base):
    __tablename__ = "agents"
    __table_args__ = {"schema": "agent_meeting_dev"}

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    connector_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="webhook",
    )
    capabilities: Mapped[dict | None] = mapped_column(JSONB)
    auth_token_hash: Mapped[str | None] = mapped_column(String(255))
    config: Mapped[dict | None] = mapped_column(JSONB)

    # Relationships
    room_memberships: Mapped[list["RoomMember"]] = relationship(back_populates="agent")
    messages: Mapped[list["Message"]] = relationship(back_populates="agent")

    def __repr__(self) -> str:
        return f"<Agent {self.name!r} ({self.connector_type})>"
