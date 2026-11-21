# core/tools.py

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from core.policy import VALID_SIDE_EFFECTS, AuthorizationDecision, AuthorizationPolicy

logger = logging.getLogger("CreedTools")


class UncertainCancellationError(Exception):
    """Raised when cancellation is requested while an uninterruptible synchronous tool is still running."""

    def __init__(self, tool_name: str, message: str = ""):
        self.tool_name = tool_name
        super().__init__(
            message
            or f"Cancellation requested while synchronous tool '{tool_name}' was still executing; termination is unconfirmed."
        )


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[..., Any]
    capabilities: tuple[str, ...] = ()
    side_effect: str = "unknown"
    requires_approval: bool = False
    policy_metadata: Dict[str, Any] = field(default_factory=dict)
    plugin_name: Optional[str] = None


class ToolRegistry:
    def __init__(self, policy: Optional[AuthorizationPolicy] = None):
        self._tools: Dict[str, ToolSpec] = {}
        self.policy: AuthorizationPolicy = policy or AuthorizationPolicy()

    def register(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable[..., Any],
        *,
        capabilities: Optional[Iterable[str]] = None,
        side_effect: str = "unknown",
        requires_approval: bool = False,
        policy_metadata: Optional[Dict[str, Any]] = None,
        plugin_name: Optional[str] = None,
    ):
        if side_effect not in VALID_SIDE_EFFECTS:
            raise ValueError(
                f"Invalid side_effect '{side_effect}' for tool '{name}'. Must be one of {VALID_SIDE_EFFECTS}."
            )
        caps = tuple(str(c).strip() for c in (capabilities or ()) if str(c).strip())
        self._tools[name] = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            capabilities=caps,
            side_effect=side_effect,
            requires_approval=bool(requires_approval),
            policy_metadata=dict(policy_metadata or {}),
            plugin_name=plugin_name,
        )
        logger.debug(f"Registered tool: {name}")

    def get_tool(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list_tools(self) -> List[ToolSpec]:
        return list(self._tools.values())

    def authorize(self, name: str, arguments: Any = None) -> AuthorizationDecision:
        parsed_args = self._parse_arguments(arguments)
        return self.policy.evaluate(self._tools.get(name), name, parsed_args)

    @staticmethod
    def _parse_arguments(arguments: Any) -> Dict[str, Any]:
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError:
                return {}
        return arguments if isinstance(arguments, dict) else {}

    def get_ollama_schemas(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in self._tools.values()
        ]

    async def execute(self, name: str, arguments: Any) -> str:
        spec = self._tools.get(name)
        if not spec:
            return f"Error: unknown tool '{name}'."

        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError:
                return f"Error: invalid JSON arguments for '{name}'."

        if not isinstance(arguments, dict):
            arguments = {}

        logger.info(f"Executing tool '{name}' with args={arguments}")
        try:
            if inspect.iscoroutinefunction(spec.handler):
                result = await spec.handler(**arguments)
            else:
                done_ev = threading.Event()

                def _run_sync():
                    try:
                        return spec.handler(**arguments)
                    finally:
                        done_ev.set()

                try:
                    result = await asyncio.to_thread(_run_sync)
                except asyncio.CancelledError:
                    if not done_ev.is_set():
                        raise UncertainCancellationError(name)
                    raise
            return str(result)
        except UncertainCancellationError:
            raise
        except asyncio.CancelledError:
            raise
        except TypeError as e:
            return f"Error calling '{name}': {e}"
        except Exception as e:
            logger.error(f"Tool '{name}' failed: {e}")
            return f"Tool '{name}' failed: {e}"
