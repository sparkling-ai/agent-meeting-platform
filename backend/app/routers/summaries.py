"""Meeting summary and transcript export endpoints.

Provides human-readable meeting summaries for non-technical stakeholders:
- Meeting transcript (full chronological log)
- Executive summary (key decisions, action items, participants)
- Markdown export for sharing/archiving
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import optional_auth
from app.database import get_db
from app.models.agent import Agent
from app.models.decision import Decision
from app.models.message import Message, RoomMember
from app.models.room import Room
from app.models.user import User
from app.schemas import RoomMemberResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/rooms/{room_id}", tags=["summaries"])


class ParticipantInfo(BaseModel):
    agent_id: uuid.UUID
    name: str
    role: str
    message_count: int = 0


class DecisionSummary(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    summary: str | None = None


class MeetingSummary(BaseModel):
    """Executive summary — who met, what was discussed, what was decided."""
    room_id: uuid.UUID
    room_name: str
    topic: str | None
    status: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    participants: list[ParticipantInfo] = []
    total_messages: int = 0
    message_type_counts: dict[str, int] = {}
    decisions: list[DecisionSummary] = []
    key_topics: list[str] = []
    duration_minutes: float | None = None


class TranscriptEntry(BaseModel):
    timestamp: datetime
    agent_name: str
    message_type: str
    content: str


class MeetingTranscript(BaseModel):
    """Full chronological transcript."""
    room_id: uuid.UUID
    room_name: str
    topic: str | None
    participants: list[ParticipantInfo] = []
    messages: list[TranscriptEntry] = []
    total_messages: int = 0


async def _get_room_or_404(db: AsyncSession, room_id: str) -> Room:
    result = await db.execute(select(Room).where(Room.id == room_id))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


async def _build_participant_stats(db: AsyncSession, room_id: str) -> list[ParticipantInfo]:
    """Get participants with their message counts."""
    # Get members
    result = await db.execute(
        select(RoomMember, Agent.name)
        .join(Agent, RoomMember.agent_id == Agent.id)
        .where(RoomMember.room_id == room_id)
    )
    members = result.all()

    participants = []
    for member, name in members:
        # Count messages per agent
        count_result = await db.execute(
            select(func.count()).select_from(Message).where(
                Message.room_id == room_id,
                Message.agent_id == member.agent_id,
            )
        )
        msg_count = count_result.scalar() or 0
        participants.append(ParticipantInfo(
            agent_id=member.agent_id,
            name=name,
            role=member.role,
            message_count=msg_count,
        ))
    return participants


@router.get("/summary", response_model=MeetingSummary)
async def get_meeting_summary(
    room_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """Get an executive summary of a meeting.

    Designed for non-technical stakeholders who need to quickly understand:
    who participated, what was discussed, what was decided.
    No authentication required for public/unlisted rooms.
    """
    room = await _get_room_or_404(db, room_id)

    # Get participants
    participants = await _build_participant_stats(db, room_id)

    # Get message stats
    count_result = await db.execute(
        select(Message.type, func.count()).where(
            Message.room_id == room_id,
        ).group_by(Message.type)
    )
    type_counts = {str(msg_type): count for msg_type, count in count_result.all()}
    total = sum(type_counts.values())

    # Get decisions
    decisions_result = await db.execute(
        select(Decision).where(Decision.room_id == room_id)
    )
    decisions = [
        DecisionSummary(
            id=d.id,
            title=d.title,
            status=d.status,
            summary=d.summary,
        )
        for d in decisions_result.scalars().all()
    ]

    # Extract key topics from proposal/summary messages
    topics_result = await db.execute(
        select(Message.content).where(
            Message.room_id == room_id,
            Message.type.in_(["proposal", "summary"]),
        ).order_by(Message.created_at.desc()).limit(5)
    )
    key_topics = [c[:100] for c, in topics_result.all()]

    # Calculate duration
    first_msg = await db.execute(
        select(Message.created_at).where(
            Message.room_id == room_id,
        ).order_by(Message.created_at.asc()).limit(1)
    )
    last_msg = await db.execute(
        select(Message.created_at).where(
            Message.room_id == room_id,
        ).order_by(Message.created_at.desc()).limit(1)
    )
    first_at = first_msg.scalar_one_or_none()
    last_at = last_msg.scalar_one_or_none()
    duration = None
    if first_at and last_at:
        duration = (last_at - first_at).total_seconds() / 60

    return MeetingSummary(
        room_id=room.id,
        room_name=room.name,
        topic=room.topic,
        status=room.status,
        started_at=first_at,
        ended_at=last_at if room.status == "closed" else None,
        participants=participants,
        total_messages=total,
        message_type_counts=type_counts,
        decisions=decisions,
        key_topics=key_topics,
        duration_minutes=round(duration, 1) if duration else None,
    )


@router.get("/transcript", response_model=MeetingTranscript)
async def get_meeting_transcript(
    room_id: str,
    format: str = Query("json", pattern="^(json|markdown)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """Get the full chronological transcript of a meeting.

    Designed for archiving and sharing. Supports JSON and Markdown formats.
    """
    room = await _get_room_or_404(db, room_id)
    participants = await _build_participant_stats(db, room_id)

    # Get all messages with agent names
    result = await db.execute(
        select(Message, Agent.name)
        .outerjoin(Agent, Message.agent_id == Agent.id)
        .where(Message.room_id == room_id)
        .order_by(Message.created_at.asc())
    )
    rows = result.all()

    entries = []
    for msg, agent_name in rows:
        entries.append(TranscriptEntry(
            timestamp=msg.created_at,
            agent_name=agent_name or "Unknown",
            message_type=msg.type,
            content=msg.content,
        ))

    return MeetingTranscript(
        room_id=room.id,
        room_name=room.name,
        topic=room.topic,
        participants=participants,
        messages=entries,
        total_messages=len(entries),
    )


@router.get("/transcript/markdown")
async def get_meeting_transcript_markdown(
    room_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """Get the meeting transcript as a Markdown document.

    Perfect for sharing in wikis, Slack, or documentation.
    """
    room = await _get_room_or_404(db, room_id)
    participants = await _build_participant_stats(db, room_id)

    # Get all messages with agent names
    result = await db.execute(
        select(Message, Agent.name)
        .outerjoin(Agent, Message.agent_id == Agent.id)
        .where(Message.room_id == room_id)
        .order_by(Message.created_at.asc())
    )
    rows = result.all()

    # Build markdown
    lines = [
        f"# {room.name}",
        "",
        f"**Topic:** {room.topic or 'No topic specified'}",
        f"**Status:** {room.status}",
        f"**Date:** {room.created_at.strftime('%Y-%m-%d') if room.created_at else 'N/A'}",
        "",
        "## Participants",
        "",
    ]
    for p in participants:
        lines.append(f"- **{p.name}** ({p.role}) — {p.message_count} messages")
    lines.append("")

    # Decisions
    decisions_result = await db.execute(
        select(Decision).where(Decision.room_id == room_id)
    )
    decisions = list(decisions_result.scalars().all())
    if decisions:
        lines.append("## Decisions")
        lines.append("")
        for d in decisions:
            status_emoji = "✅" if d.status == "accepted" else "❌" if d.status == "rejected" else "🔄"
            lines.append(f"- {status_emoji} **{d.title}** ({d.status})")
            if d.summary:
                lines.append(f"  > {d.summary}")
        lines.append("")

    # Transcript
    lines.append("## Transcript")
    lines.append("")
    for msg, agent_name in rows:
        timestamp = msg.created_at.strftime("%H:%M") if msg.created_at else "??:??"
        type_label = f" *[{msg.type}]*" if msg.type != "chat" else ""
        lines.append(f"**[{timestamp}] {agent_name}**{type_label}: {msg.content}")
        lines.append("")

    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        content="\n".join(lines),
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="meeting-{room.name.lower().replace(" ", "-")}.md"'
        },
    )


@router.post("/join-observer")
async def join_as_observer(
    room_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """Join a room as an observer (read-only, no agent required).

    This allows humans to watch meetings without needing to register an AI agent.
    Creates an observer agent automatically for the user.
    """
    room = await _get_room_or_404(db, room_id)

    if room.status not in ("active", "draft"):
        raise HTTPException(status_code=400, detail="Room is not active")

    # Check if user already has an observer agent in this room
    if current_user:
        existing = await db.execute(
            select(RoomMember)
            .join(Agent, RoomMember.agent_id == Agent.id)
            .where(
                RoomMember.room_id == room_id,
                Agent.owner_id == str(current_user.id),
                RoomMember.role == "observer",
            )
        )
        if existing.scalar_one_or_none():
            # Already an observer
            return {"detail": "Already observing", "room_id": str(room_id)}

    # Create an observer agent
    observer_name = f"Observer-{(current_user.display_name or current_user.username) if current_user else 'Anonymous'}"
    observer_agent = Agent(
        name=observer_name,
        connector_type="observer",
        capabilities={"role": "observer", "human": True},
        owner_id=str(current_user.id) if current_user else None,
    )
    db.add(observer_agent)
    await db.flush()

    # Add as observer member
    member = RoomMember(
        room_id=room_id,
        agent_id=observer_agent.id,
        role="observer",
    )
    db.add(member)
    await db.flush()

    return {
        "detail": "Joined as observer",
        "room_id": str(room_id),
        "agent_id": str(observer_agent.id),
        "agent_name": observer_name,
        "role": "observer",
        "ws_url": f"/api/rooms/{room_id}/ws?token={observer_agent.auth_token or 'request-token'}",
    }
