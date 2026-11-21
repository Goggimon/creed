# utils/logger.py

from __future__ import annotations

import contextvars
import json
import logging
import threading
import traceback
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from config.settings import config

_conversation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("creed_conversation_id", default="")
_turn_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("creed_turn_id", default="")
_task_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("creed_task_id", default="")

_EVENTS_LOCK = threading.Lock()
_RECENT_EVENTS: deque[Dict[str, Any]] = deque(maxlen=500)

_SENSITIVE_KEYS = {
    "prompt",
    "text",
    "content",
    "api_key",
    "apikey",
    "access_key",
    "token",
    "password",
    "secret",
    "authorization",
    "history",
    "messages",
}


def redact_sensitive(value: Any) -> Any:
    """Recursively redact prompt text, credentials, and sensitive fields from diagnostic payloads."""
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in value.items():
            if str(k).strip().lower() in _SENSITIVE_KEYS:
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = redact_sensitive(v)
        return cleaned
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


def set_correlation_context(
    conversation_id: str = "",
    turn_id: str = "",
    task_id: str = "",
) -> tuple[contextvars.Token, contextvars.Token, contextvars.Token]:
    return (
        _conversation_id_var.set(conversation_id),
        _turn_id_var.set(turn_id),
        _task_id_var.set(task_id),
    )


def reset_correlation_context(
    tokens: tuple[contextvars.Token, contextvars.Token, contextvars.Token]
) -> None:
    c_tok, t_tok, k_tok = tokens
    _conversation_id_var.reset(c_tok)
    _turn_id_var.reset(t_tok)
    _task_id_var.reset(k_tok)


@contextmanager
def correlation_scope(conversation_id: str = "", turn_id: str = "", task_id: str = ""):
    tokens = set_correlation_context(
        conversation_id=conversation_id, turn_id=turn_id, task_id=task_id
    )
    try:
        yield
    finally:
        reset_correlation_context(tokens)


def get_correlation_context() -> Dict[str, str]:
    return {
        "conversation_id": _conversation_id_var.get(),
        "turn_id": _turn_id_var.get(),
        "task_id": _task_id_var.get(),
    }


def spawn_correlated_thread(
    target: Callable[..., Any],
    args: tuple = (),
    kwargs: Optional[Dict[str, Any]] = None,
    daemon: bool = True,
) -> threading.Thread:
    """Launch a background thread while preserving active correlation contextvars."""
    ctx = contextvars.copy_context()
    kw = kwargs or {}
    thread = threading.Thread(
        target=lambda: ctx.run(target, *args, **kw),
        daemon=daemon,
    )
    thread.start()
    return thread


def log_event(
    module: str,
    event_name: str,
    level: str = "INFO",
    message: str = "",
    conversation_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    task_id: Optional[str] = None,
    exc: Optional[BaseException] = None,
    **fields: Any,
) -> Dict[str, Any]:
    """Emit a structured, redacted event to both the Python logger and the bounded ring buffer."""
    ctx = get_correlation_context()
    record: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level.upper(),
        "module": module,
        "event": event_name,
        "conversation_id": conversation_id if conversation_id is not None else ctx["conversation_id"],
        "turn_id": turn_id if turn_id is not None else ctx["turn_id"],
        "task_id": task_id if task_id is not None else ctx["task_id"],
    }
    if message:
        record["message"] = message
    if fields:
        record["data"] = redact_sensitive(fields)
    if exc is not None:
        record["exception"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        }

    with _EVENTS_LOCK:
        _RECENT_EVENTS.appendleft(record)

    py_logger = logging.getLogger(module)
    log_level = getattr(logging, record["level"], logging.INFO)
    py_logger.log(log_level, json.dumps(record, default=str))
    return record


def get_recent_events(turn_id: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    bounded_limit = max(1, min(100, int(limit)))
    with _EVENTS_LOCK:
        if not turn_id:
            return list(_RECENT_EVENTS)[:bounded_limit]
        return [ev for ev in _RECENT_EVENTS if ev.get("turn_id") == turn_id][:bounded_limit]


def clear_recent_events() -> None:
    with _EVENTS_LOCK:
        _RECENT_EVENTS.clear()


class _StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        if msg.startswith("{") and msg.endswith("}"):
            return msg
        ctx = get_correlation_context()
        payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "event": "log",
            "conversation_id": ctx["conversation_id"],
            "turn_id": ctx["turn_id"],
            "task_id": ctx["task_id"],
            "message": msg,
        }
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            payload["exception"] = {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": self.formatException(record.exc_info),
            }
        return json.dumps(payload, default=str)


def setup_logger():
    log_path = Path(config.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if config.debug else logging.INFO)

    if not root_logger.handlers:
        formatter = _StructuredFormatter()

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

    return logging.getLogger("creed")
