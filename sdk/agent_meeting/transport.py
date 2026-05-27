"""Transport layer — WebSocket + REST for the Agent Meeting SDK."""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator, Callable

import httpx
import websockets

from agent_meeting.models import EventType, Event

logger = logging.getLogger(__name__)


class Transport:
    """Handles REST API calls and WebSocket connection to the meeting server."""

    def __init__(self, server_url: str):
        self.server_url = server_url.rstrip("/")
        self._http = httpx.AsyncClient(base_url=self.server_url, timeout=30)
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._token: str | None = None
        self._api_key: str | None = None

    @property
    def token(self) -> str | None:
        return self._token

    @token.setter
    def token(self, value: str):
        self._token = value

    @property
    def api_key(self) -> str | None:
        return self._api_key

    @api_key.setter
    def api_key(self, value: str):
        self._api_key = value

    def _headers(self) -> dict[str, str]:
        """Build auth headers if credentials are set."""
        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    # ── REST API ─────────────────────────────────────────────────────

    async def post(self, path: str, json_data: dict | None = None, params: dict | None = None) -> dict:
        """Make a POST request."""
        resp = await self._http.post(path, json=json_data, params=params, headers=self._headers())
        if resp.status_code >= 400:
            logger.error("POST %s → %d: %s", path, resp.status_code, resp.text[:300])
        resp.raise_for_status()
        return resp.json()

    async def get(self, path: str, params: dict | None = None) -> dict:
        """Make a GET request."""
        resp = await self._http.get(path, params=params, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def patch(self, path: str, json_data: dict | None = None, params: dict | None = None) -> dict:
        """Make a PATCH request."""
        resp = await self._http.patch(path, json=json_data, params=params, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    # ── WebSocket ────────────────────────────────────────────────────

    async def ws_connect(self, room_id: str) -> None:
        """Connect to room WebSocket."""
        if not self._token:
            raise ValueError("No auth token — call register() first")

        ws_url = self.server_url.replace("http", "ws") + f"/api/rooms/{room_id}/ws?token={self._token}"
        self._ws = await websockets.connect(ws_url)
        logger.info("WebSocket connected to room %s", room_id)

    async def ws_send(self, data: dict) -> None:
        """Send a message via WebSocket."""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        await self._ws.send(json.dumps(data))

    async def ws_recv(self) -> dict:
        """Receive a message from WebSocket."""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        raw = await self._ws.recv()
        return json.loads(raw)

    async def ws_events(self) -> AsyncIterator[Event]:
        """Yield events from WebSocket."""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        try:
            async for raw in self._ws:
                data = json.loads(raw)
                yield Event.from_ws(data)
        except websockets.ConnectionClosed:
            logger.info("WebSocket connection closed")
        except Exception as e:
            logger.error("WebSocket error: %s", e)
            raise

    async def ws_close(self) -> None:
        """Close WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def close(self) -> None:
        """Close all connections."""
        await self.ws_close()
        await self._http.aclose()
