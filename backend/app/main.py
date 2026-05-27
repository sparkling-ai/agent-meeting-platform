"""Agent Meeting Platform — FastAPI application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Import all models so Base.metadata knows about them
    import app.models.agent  # noqa: F401
    import app.models.room  # noqa: F401
    import app.models.message  # noqa: F401
    import app.models.decision  # noqa: F401
    import app.models.user  # noqa: F401
    from app.models.base import Base

    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {settings.db_schema}"))
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Agent Meeting Platform started — tables ensured in schema %s", settings.db_schema)
    yield


app = FastAPI(
    title="Agent Meeting Platform",
    version="0.1.0",
    lifespan=lifespan,
    description="Collaboration layer for autonomous AI agents",
)

# CORS — allow all for dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.routers import agents, messages, rooms, websocket  # noqa: E402
from app.routers import admin, decisions, action_items, moderator  # noqa: E402
from app.routers import auth  # noqa: E402

app.include_router(rooms.router)
app.include_router(agents.router)
app.include_router(messages.router)
app.include_router(websocket.router)
app.include_router(admin.router)
app.include_router(decisions.router)
app.include_router(action_items.router)
app.include_router(moderator.router)
app.include_router(auth.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0", "schema": settings.db_schema}


@app.get("/api")
async def api_index():
    """API index — list all available endpoint groups."""
    return {
        "endpoints": {
            "rooms": "/api/rooms",
            "agents": "/api/agents",
            "messages": "/api/rooms/{room_id}/messages",
            "websocket": "/api/rooms/{room_id}/ws?token={agent_token}",
            "decisions": "/api/decisions",
            "action_items": "/api/action-items",
            "admin": "/api/admin",
        },
        "docs": "/docs",
    }
