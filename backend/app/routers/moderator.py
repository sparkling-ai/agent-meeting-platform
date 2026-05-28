"""Moderator REST endpoints — start, advance, vote, close meetings."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, optional_auth
from app.auth.permissions import RoomRole, check_room_permission
from app.database import get_db
from app.models import Agent, Room, RoomMember, Message
from app.models.user import User
from app.services.moderator_service import moderator_manager, MeetingPhase
from app.core.protocol import MessageType
from app.core.events import event_bus, Event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rooms/{room_id}/moderator", tags=["moderator"])


# ── Schemas ──────────────────────────────────────────────────────────────────
class StartMeetingRequest(BaseModel):
    agenda_items: list[dict] | None = None
    """Optional agenda: [{title, description, timebox_minutes, decision_required}]"""


class VoteRequest(BaseModel):
    proposal_id: str | None = None


class InvestigateRequest(BaseModel):
    agent_id: str
    topic: str = Field(..., min_length=1)
    estimated_minutes: float = Field(default=3.0, ge=0.5, le=10.0)


class ParkRequest(BaseModel):
    topic: str = Field(..., min_length=1)
    proposed_by: str = ""


# ── Helpers ──────────────────────────────────────────────────────────────────
def _get_mod_engine(room_id: str):
    """Get moderator engine for a room, or None if no moderator exists."""
    return moderator_manager._engines.get(room_id)


async def _get_room_and_mod(room_id: str, db: AsyncSession):
    """Get room and moderator engine, or 404."""
    room = await db.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    engine = moderator_manager.get(room_id)
    return room, engine


async def _ensure_moderator_agent(room_id: str, db: AsyncSession) -> Agent:
    """Get or create the system moderator agent for a room."""
    # Find existing system moderator
    result = await db.execute(
        select(Agent).where(Agent.connector_type == "system")
    )
    mod_agent = result.scalars().first()

    if not mod_agent:
        mod_agent = Agent(
            name="Meeting Moderator",
            connector_type="system",
            capabilities={"is_moderator": True},
            auth_token=f"mod-{room_id}",
        )
        db.add(mod_agent)
        await db.flush()

    # Ensure moderator is a room member
    existing = await db.execute(
        select(RoomMember).where(
            RoomMember.room_id == room_id,
            RoomMember.agent_id == mod_agent.id,
        )
    )
    if not existing.scalar_one_or_none():
        member = RoomMember(room_id=room_id, agent_id=mod_agent.id, role="moderator")
        db.add(member)
        await db.flush()

    return mod_agent


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/start")
async def start_meeting(
    room_id: str,
    data: StartMeetingRequest = None,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """Start the meeting — transitions from DRAFT to OPENING to DISCUSSION."""
    if current_user:
        await check_room_permission(db, room_id, current_user, RoomRole.MODERATOR)
    room, engine = await _get_room_and_mod(room_id, db)

    # Create/ensure moderator agent
    mod_agent = await _ensure_moderator_agent(room_id, db)
    engine.state.moderator_agent_id = str(mod_agent.id)

    # Get member names
    members = await db.execute(
        select(RoomMember, Agent.name)
        .join(Agent, RoomMember.agent_id == Agent.id)
        .where(RoomMember.room_id == room_id)
    )
    member_names = {str(row[0].agent_id): row[1] for row in members.all()}

    # Start
    agenda = (data.agenda_items if data else None) or []
    result = await engine.start_meeting(
        db, room.name, room.topic,
        agenda_items=agenda,
        member_names=member_names,
    )

    # Post moderator's opening message
    msg = Message(
        room_id=room_id,
        agent_id=mod_agent.id,
        type=MessageType.SUMMARY.value,
        content=result["content"],
        metadata_=result.get("metadata", {}),
    )
    db.add(msg)
    await db.flush()

    # Update room status
    room.status = "active"

    await event_bus.publish(Event("meeting_started", {
        "room_id": room_id,
        "phase": engine.state.phase.value,
    }))

    return {
        "status": "started",
        "phase": engine.state.phase.value,
        "moderator_agent_id": str(mod_agent.id),
        "message_id": str(msg.id),
    }


@router.post("/advance")
async def advance_agenda(
    room_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """Advance to the next agenda item."""
    if current_user:
        await check_room_permission(db, room_id, current_user, RoomRole.MODERATOR)
    _, engine = await _get_room_and_mod(room_id, db)

    if engine.state.phase == MeetingPhase.CLOSED:
        raise HTTPException(status_code=400, detail="Meeting is closed")

    result = await engine.advance_to_next_item(db)

    # Post moderator message
    if result.get("content"):
        mod_agent_id = engine.state.moderator_agent_id
        msg = Message(
            room_id=room_id,
            agent_id=mod_agent_id,
            type=result.get("type", "chat"),
            content=result["content"],
            metadata_={"moderator_action": result["action"]},
        )
        db.add(msg)
        await db.flush()

    return {"status": "advanced", "action": result["action"], "phase": engine.state.phase.value}


@router.post("/vote")
async def initiate_vote(
    room_id: str,
    data: VoteRequest = None,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """Initiate a formal vote on a proposal."""
    if current_user:
        await check_room_permission(db, room_id, current_user, RoomRole.MODERATOR)
    _, engine = await _get_room_and_mod(room_id, db)

    proposal_id = data.proposal_id if data else None
    result = await engine.initiate_vote(proposal_id, db)

    if result.get("content"):
        mod_agent_id = engine.state.moderator_agent_id
        msg = Message(
            room_id=room_id,
            agent_id=mod_agent_id,
            type=result.get("type", "chat"),
            content=result["content"],
            metadata_={"moderator_action": result["action"]},
        )
        db.add(msg)
        await db.flush()

    return {"status": "vote_initiated", "phase": engine.state.phase.value}


@router.post("/force-decision")
async def force_decision(
    room_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """Force a decision when time has expired."""
    if current_user:
        await check_room_permission(db, room_id, current_user, RoomRole.MODERATOR)
    _, engine = await _get_room_and_mod(room_id, db)

    result = await engine.force_decision(db)

    if result.get("content"):
        mod_agent_id = engine.state.moderator_agent_id
        msg = Message(
            room_id=room_id,
            agent_id=mod_agent_id,
            type=result.get("type", "chat"),
            content=result["content"],
            metadata_={"moderator_action": result["action"]},
        )
        db.add(msg)
        await db.flush()

    return {"status": "force_decision", "phase": engine.state.phase.value}


@router.post("/close")
async def close_meeting(
    room_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """Close the meeting and generate minutes."""
    if current_user:
        await check_room_permission(db, room_id, current_user, RoomRole.MODERATOR)
    room, engine = await _get_room_and_mod(room_id, db)

    result = await engine.close_meeting(db)

    # Post moderator closing message
    if result.get("content"):
        mod_agent_id = engine.state.moderator_agent_id
        msg = Message(
            room_id=room_id,
            agent_id=mod_agent_id,
            type=MessageType.SUMMARY.value,
            content=result["content"],
            metadata_={"moderator_action": "meeting_closed"},
        )
        db.add(msg)
        await db.flush()

    # Update room status
    room.status = "archived"

    await event_bus.publish(Event("meeting_closed", {
        "room_id": room_id,
        "total_messages": engine.state.total_messages,
        "decisions": len(engine.state.decision_ids),
    }))

    return {
        "status": "closed",
        "total_messages": engine.state.total_messages,
        "decisions": len(engine.state.decision_ids),
        "action_items": len(engine.state.action_item_ids),
        "message_id": str(msg.id) if result.get("content") else None,
    }


@router.get("/state")
async def get_moderator_state(
    room_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """Get current moderator state (phase, agenda, turns, etc.)."""
    _, engine = await _get_room_and_mod(room_id, db)
    return engine.get_state()


@router.get("/summary")
async def get_moderator_summary(
    room_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """Get current meeting summary."""
    _, engine = await _get_room_and_mod(room_id, db)
    return engine.get_summary()


@router.post("/investigate")
async def request_investigation(
    room_id: str,
    data: InvestigateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """Agent requests investigation time."""
    _, engine = await _get_room_and_mod(room_id, db)

    # Get agent name
    agent = await db.get(Agent, data.agent_id)
    agent_name = agent.name if agent else data.agent_id[:8]

    result = await engine._handle_investigation_request(
        data.agent_id, agent_name,
        {"investigation": True, "topic": data.topic, "estimated_minutes": data.estimated_minutes},
        db,
    )

    if result and result.get("content"):
        mod_agent_id = engine.state.moderator_agent_id
        msg = Message(
            room_id=room_id,
            agent_id=mod_agent_id,
            type=result.get("type", "chat"),
            content=result["content"],
            metadata_={"moderator_action": result["action"]},
        )
        db.add(msg)
        await db.flush()

    return result or {"action": "error", "content": "Investigation request failed"}


@router.post("/park")
async def park_topic(
    room_id: str,
    data: ParkRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """Park a topic for later discussion."""
    _, engine = await _get_room_and_mod(room_id, db)

    result = engine.park_topic(data.topic, data.proposed_by)

    if result.get("content"):
        mod_agent_id = engine.state.moderator_agent_id
        msg = Message(
            room_id=room_id,
            agent_id=mod_agent_id,
            type="chat",
            content=result["content"],
            metadata_={"moderator_action": "topic_parked"},
        )
        db.add(msg)
        await db.flush()

    return {"status": "parked", "topic": data.topic}
