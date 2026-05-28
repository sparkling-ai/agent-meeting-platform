"""WebSocket endpoint for real-time meeting communication."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models import Agent, RoomMember, Message
from app.models.user import User
from app.core.events import event_bus, Event
from app.services.moderator_service import moderator_manager, MeetingPhase
from app.auth.jwt import verify_token
from app.auth.permissions import RoomRole, has_min_room_role

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])

# Track active WS connections: room_id -> set of (websocket, agent_id)
_connections: dict[str, set[tuple]] = {}


async def _authenticate(token: str, db: AsyncSession) -> Optional[Agent]:
    """Authenticate agent by token — supports both legacy agent tokens and JWT tokens."""
    # First try JWT token (new auth system)
    payload = verify_token(token)
    if payload is not None:
        user_id = payload.get("sub")
        if user_id:
            import uuid as _uuid
            try:
                user = await db.get(User, _uuid.UUID(user_id))
            except (ValueError, TypeError):
                user = None
            if user and user.is_active:
                # For JWT-authenticated users, find or create a corresponding agent
                # This allows WebSocket connections for authenticated users
                result = await db.execute(
                    select(Agent).where(Agent.owner_id == str(user.id))
                )
                agent = result.scalars().first()
                if agent:
                    return agent
        return None

    # Fallback: legacy agent token
    from app.services.agent_service import validate_token
    agent = await validate_token(db, token)
    if agent:
        return agent
    # Last resort: check auth_token field directly
    result = await db.execute(select(Agent).where(Agent.auth_token == token))
    return result.scalar_one_or_none()


async def _broadcast_to_room(room_id: str, event: dict, exclude_agent: Optional[str] = None) -> None:
    """Send an event to all connected WebSockets in a room."""
    conns = _connections.get(room_id, set())
    payload = json.dumps(event, default=str)
    dead = []
    for ws, aid in conns:
        if exclude_agent and aid == exclude_agent:
            continue
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append((ws, aid))
    for d in dead:
        conns.discard(d)


async def _on_event(event: Event) -> None:
    """Event bus subscriber — forwards events to WebSocket clients."""
    room_id = event.data.get("room_id")
    if room_id:
        await _broadcast_to_room(str(room_id), {
            "event": event.type,
            "data": event.data,
        })


# Subscribe to event types
for _evt_type in (
    "message_posted", "agent_joined_room", "agent_left_room",
    "room_status_changed", "decision_created",
):
    event_bus.subscribe(_evt_type, _on_event)


@router.websocket("/api/rooms/{room_id}/ws")
async def websocket_endpoint(websocket: WebSocket, room_id: str, token: str = Query(...)):
    """WebSocket endpoint for room communication.

    Auth via ?token= query param.
    On connect: verify membership, send recent messages.
    On message: parse, persist, run moderator, broadcast.
    Broadcast events: new_message, agent_joined, agent_left, decision_made, action_item_created.
    """
    # Authenticate
    async with async_session_factory() as db:
        agent = await _authenticate(token, db)
        if not agent:
            await websocket.close(code=4001, reason="Invalid token")
            return

        # Verify room membership and role
        result = await db.execute(
            select(RoomMember).where(
                RoomMember.room_id == room_id,
                RoomMember.agent_id == agent.id,
            )
        )
        member = result.scalar_one_or_none()
        if not member:
            await websocket.close(code=4003, reason="Not a room member")
            return

        # Check minimum role: observers can only view, not send
        # We allow all roles to connect, but check role on message send
        agent_room_role = member.role

        # Get recent messages
        msgs = await db.execute(
            select(Message)
            .where(Message.room_id == room_id)
            .order_by(Message.created_at.desc())
            .limit(50)
        )
        recent = list(reversed(msgs.scalars().all()))

    # Accept connection
    await websocket.accept()

    # Register connection
    if room_id not in _connections:
        _connections[room_id] = set()
    conn = (websocket, str(agent.id))
    _connections[room_id].add(conn)

    # Send recent messages
    for msg in recent:
        await websocket.send_text(json.dumps({
            "event": "recent_message",
            "data": {
                "id": str(msg.id),
                "room_id": str(msg.room_id),
                "agent_id": str(msg.agent_id),
                "type": msg.type,
                "content": msg.content,
                "parent_id": str(msg.parent_id) if msg.parent_id else None,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            },
        }, default=str))

    # Notify room of new join
    await _broadcast_to_room(room_id, {
        "event": "agent_joined",
        "data": {"agent_id": str(agent.id), "agent_name": agent.name},
    }, exclude_agent=str(agent.id))

    # Main message loop
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"event": "error", "data": {"message": "Invalid JSON"}}))
                continue

            msg_type = data.get("type", "chat")
            content = data.get("content", "")
            parent_id = data.get("parent_id")
            metadata = data.get("metadata", {})

            if not content:
                await websocket.send_text(json.dumps({"event": "error", "data": {"message": "Empty content"}}))
                continue

            # Check if agent has permission to send (not observer)
            if not has_min_room_role(agent_room_role, RoomRole.MEMBER):
                await websocket.send_text(json.dumps({"event": "error", "data": {"message": "Observers cannot send messages"}}))
                continue

            # Persist message
            mod_actions = []
            msg_id = None
            async with async_session_factory() as db:
                msg = Message(
                    room_id=room_id,
                    agent_id=agent.id,
                    type=msg_type,
                    content=content,
                    parent_id=parent_id,
                    metadata_=metadata,
                )
                db.add(msg)
                await db.flush()

                msg_id = str(msg.id)

                # Moderator analysis
                mod = moderator_manager.get(room_id)
                mod_actions = await mod.on_message(msg, db, agent_name=agent.name)

                # If moderator hasn't been set yet, skip
                if not mod.state.moderator_agent_id:
                    mod_actions = []

            # Broadcast to room
            await _broadcast_to_room(room_id, {
                "event": "new_message",
                "data": {
                    "id": msg_id,
                    "room_id": room_id,
                    "agent_id": str(agent.id),
                    "agent_name": agent.name,
                    "type": msg_type,
                    "content": content,
                    "parent_id": parent_id,
                    "moderator_actions": mod_actions,
                },
            })

            # Process moderator actions
            for action in mod_actions:
                if action["action"] == "finalize_decision":
                    async with async_session_factory() as db:
                        from app.models import Decision
                        decision = Decision(
                            room_id=room_id,
                            title="Decision from proposal",
                            status="accepted",
                        )
                        db.add(decision)
                        await db.flush()
                        decision_id = str(decision.id)

                    await _broadcast_to_room(room_id, {
                        "event": "decision_made",
                        "data": {
                            "decision_id": decision_id,
                            "proposal_id": action["proposal_id"],
                        },
                    })

                    await event_bus.publish(Event("decision_created", {
                        "room_id": room_id,
                        "decision_id": decision_id,
                        "proposal_id": action["proposal_id"],
                    }))

                else:
                    await _broadcast_to_room(room_id, {
                        "event": "moderator_action",
                        "data": action,
                    })

    except WebSocketDisconnect:
        logger.info("Agent %s disconnected from room %s", agent.id, room_id)
    except Exception:
        logger.exception("WebSocket error for agent %s in room %s", agent.id, room_id)
    finally:
        _connections.get(room_id, set()).discard(conn)
        if not _connections.get(room_id):
            _connections.pop(room_id, None)

        await _broadcast_to_room(room_id, {
            "event": "agent_left",
            "data": {"agent_id": str(agent.id), "agent_name": agent.name},
        })

        await event_bus.publish(Event("agent_left_room", {
            "room_id": room_id,
            "agent_id": str(agent.id),
        }))
