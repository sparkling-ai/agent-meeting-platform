"""Agent Meeting Platform — FastAPI application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import engine
from app.models import Base
from app.routers import agents, messages, rooms

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Agent Meeting Platform started — tables ensured")
    yield


app = FastAPI(title="Agent Meeting Platform", version="0.1.0", lifespan=lifespan)

app.include_router(rooms.router)
app.include_router(agents.router)
app.include_router(messages.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
