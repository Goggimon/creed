# creed/modules/ai.py

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional
import httpx
from config.settings import config
from modules.base_ai import (
    BaseAIProvider,
    ProviderError,
    ProviderEvent,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

logger = logging.getLogger("CreedAI")


class Module(BaseAIProvider):
    """
    Concrete Local AI provider targeting Ollama models on Apple Silicon / CPU.
    Default Target Model: qwen2.5:7b (configurable via OLLAMA_MODEL in .env).
    """

    provider_name = "ollama"
    tier = "local"
    supports_tools = True

    def __init__(self, data_lock=None):
        self.name = "ai"
        self.data_lock = data_lock
        self.model = config.ollama_model
        self.endpoint = config.ollama_endpoint
        self.timeout = config.ollama_timeout
        logger.info(f"Local AI module initialized (model={self.model})")

    async def chat(self, history: list, model_override: Optional[str] = None) -> str:
        active_model = model_override or self.model
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.endpoint,
                    json={
                        "model": active_model,
                        "messages": history,
                        "stream": False,
                        "keep_alive": "15m",
                        "options": {"num_ctx": 4096},
                    },
                )
                response.raise_for_status()
                data = response.json()

                if "message" in data and "content" in data["message"]:
                    return data["message"]["content"]

                return "CREED: Unexpected response format."

        except httpx.ConnectError as e:
            raise ProviderUnavailableError(
                "Ollama service is not running. Start it with 'ollama serve'.",
                provider=self.provider_name,
                cause=e,
            ) from e
        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(
                "Ollama request timed out.", provider=self.provider_name, cause=e
            ) from e
        except httpx.RequestError as e:
            raise ProviderError(
                f"Ollama network error: {str(e)}", provider=self.provider_name, cause=e
            ) from e

    async def stream_turn(
        self,
        history: list,
        tools: Optional[list] = None,
        model_override: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
        timeout_s: Optional[float] = None,
    ) -> AsyncGenerator[dict, None]:
        active_model = model_override or self.model
        effective_timeout = timeout_s if timeout_s is not None else self.timeout
        payload = {
            "model": active_model,
            "messages": history,
            "stream": True,
            "keep_alive": "15m",
            "options": {"num_ctx": 4096},
        }
        if tools:
            payload["tools"] = tools

        collected_tool_calls = []

        try:
            async with httpx.AsyncClient(timeout=effective_timeout) as client:
                async with client.stream("POST", self.endpoint, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if cancel_event is not None and cancel_event.is_set():
                            return
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        message = data.get("message") or {}
                        content = message.get("content")
                        if content:
                            yield ProviderEvent(type="token", text=content).to_dict()

                        tool_calls = message.get("tool_calls")
                        if tool_calls:
                            collected_tool_calls.extend(tool_calls)

            if collected_tool_calls and not (cancel_event and cancel_event.is_set()):
                yield ProviderEvent(type="tool_calls", calls=collected_tool_calls).to_dict()

        except httpx.ConnectError as e:
            raise ProviderUnavailableError(
                "Ollama service is not running. Start it with 'ollama serve'.",
                provider=self.provider_name,
                cause=e,
            ) from e
        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(
                "Ollama request timed out during streaming.",
                provider=self.provider_name,
                cause=e,
            ) from e
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"Ollama HTTP {e.response.status_code}: ensure model '{active_model}' is pulled.",
                provider=self.provider_name,
                cause=e,
            ) from e
        except httpx.RequestError as e:
            raise ProviderError(
                f"Ollama network error: {str(e)}", provider=self.provider_name, cause=e
            ) from e
