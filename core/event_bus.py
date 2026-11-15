# core/event_bus.py

import asyncio
import logging
from typing import Callable, Dict, List

logger = logging.getLogger("CreedEventBus")


class EventBus:
    def __init__(self):
        self._listeners: Dict[str, List[Callable]] = {}

    def subscribe(self, event: str, callback: Callable):
        if event not in self._listeners:
            self._listeners[event] = []
        if callback not in self._listeners[event]:
            self._listeners[event].append(callback)
            logger.debug(f"Subscribed callback to event: {event}")

    def unsubscribe(self, event: str, callback: Callable):
        if event in self._listeners:
            try:
                self._listeners[event].remove(callback)
                logger.debug(f"Unsubscribed callback from event: {event}")
            except ValueError:
                pass

    async def publish(self, event: str, *args, **kwargs):
        if event not in self._listeners:
            return

        tasks = []
        for callback in list(self._listeners[event]):
            try:
                if asyncio.iscoroutinefunction(callback):
                    tasks.append(callback(*args, **kwargs))
                else:
                    callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error publishing {event} to listener {callback}: {e}")

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Async listener error on '{event}': {result}")


# Global event bus instance
event_bus = EventBus()
