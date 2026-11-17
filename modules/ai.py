# creed/modules/ai.py

import json
import logging
from typing import AsyncGenerator, Optional
import httpx
from config.settings import config
from modules.base_ai import BaseAIProvider

logger = logging.getLogger("CreedAI")


class Module(BaseAIProvider):
    """
    Concrete Local AI module targeting Ollama models on Apple Silicon / CPU.
    Default Target Model: qwen2.5:7b (configurable via OLLAMA_MODEL in .env).
    """

    def __init__(self, data_lock=None):
        self.name = "ai"
        self.data_lock = data_lock
        self.model = config.ollama_model
        self.endpoint = config.ollama_endpoint
        self.timeout = config.ollama_timeout
        logger.info(f"Local AI module initialized (model={self.model})")

    async def chat(self, history: list) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.endpoint,
                    json={
                        "model": self.model,
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

        except httpx.ConnectError:
            return "CREED: Ollama service is not running."
        except httpx.TimeoutException:
            return "CREED: Request timed out."
        except httpx.RequestError as e:
            return f"CREED: Network error: {str(e)}"
        except Exception as e:
            return f"CREED: Internal error: {str(e)}"

    async def stream_chat(self, history: list) -> AsyncGenerator[str, None]:
        async for event in self.stream_turn(history):
            if event["type"] == "token":
                yield event["text"]

    async def stream_turn(
        self, history: list, tools: Optional[list] = None, model_override: Optional[str] = None
    ) -> AsyncGenerator[dict, None]:
        active_model = model_override or self.model
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
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", self.endpoint, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        message = data.get("message") or {}
                        content = message.get("content")
                        if content:
                            yield {"type": "token", "text": content}

                        tool_calls = message.get("tool_calls")
                        if tool_calls:
                            collected_tool_calls.extend(tool_calls)

            if collected_tool_calls:
                yield {"type": "tool_calls", "calls": collected_tool_calls}

        except httpx.ConnectError as e:
            raise RuntimeError(
                "Ollama service is not running. Start it with 'ollama serve'."
            ) from e
        except httpx.TimeoutException as e:
            raise RuntimeError("Ollama request timed out during streaming.") from e
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Ollama HTTP {e.response.status_code}: ensure model '{self.model}' is pulled."
            ) from e
        except httpx.RequestError as e:
            raise RuntimeError(f"Ollama network error: {str(e)}") from e
