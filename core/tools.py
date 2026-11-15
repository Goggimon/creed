# core/tools.py

import asyncio
import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

logger = logging.getLogger("CreedTools")


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[..., Any]


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable[..., Any],
    ):
        self._tools[name] = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        )
        logger.debug(f"Registered tool: {name}")

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
                result = await asyncio.to_thread(spec.handler, **arguments)
            return str(result)
        except TypeError as e:
            return f"Error calling '{name}': {e}"
        except Exception as e:
            logger.error(f"Tool '{name}' failed: {e}")
            return f"Tool '{name}' failed: {e}"
