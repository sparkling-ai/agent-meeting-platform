"""Agent Meeting Platform — FastAPI application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
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
    from app.models.base import Base

    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {settings.db_schema}"))
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Agent Meeting Platform started — tables ensured in schema %s", settings.db_schema)
    yield


app = FastAPI(title="Agent Meeting Platform", version="0.1.0", lifespan=lifespan)

from app.routers import agents, messages, rooms  # noqa: E402
app.include_router(rooms.router)
app.include_router(agents.router)
app.include_router(messages.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
