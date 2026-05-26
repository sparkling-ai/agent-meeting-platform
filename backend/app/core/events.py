"""In-process async event bus."""

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """An event published on the bus."""
    type: str
    data: dict = field(default_factory=dict)


class EventBus:
    """Simple in-process event bus using asyncio."""

    def __init__(self):
        self._subscribers: dict[str, list[Callable[[Event], Coroutine]]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Callable[[Event], Coroutine]) -> None:
        self._subscribers[event_type].append(handler)

    async def publish(self, event: Event) -> None:
        handlers = self._subscribers.get(event.type, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception:
                logger.exception("Error in event handler for %s", event.type)

    def clear(self) -> None:
        self._subscribers.clear()


# Singleton event bus
event_bus = EventBus()
