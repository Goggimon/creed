import asyncio
import logging
import os
from typing import AsyncGenerator, Optional
from dotenv import load_dotenv
from groq import AsyncGroq
from modules.base_ai import BaseAIProvider, ProviderError, ProviderEvent, ProviderUnavailableError

load_dotenv()
logger = logging.getLogger("CreedCloudAI")


class CloudModule(BaseAIProvider):
    """Optional Groq cloud provider implementing the unified BaseAIProvider contract."""

    provider_name = "groq"
    tier = "cloud"
    supports_tools = False

    def __init__(self, model: str = "llama-3.1-8b-instant"):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ProviderUnavailableError("GROQ_API_KEY not set", provider=self.provider_name)

        self.client = AsyncGroq(api_key=api_key)
        self.model = model
        self.endpoint = "https://api.groq.com"
        logger.info(f"CloudModule initialized (model={self.model})")

    async def chat(self, history: list, model_override: Optional[str] = None) -> str:
        try:
            response = await self.client.chat.completions.create(
                model=model_override or self.model,
                messages=history,
                stream=False,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            raise ProviderError(str(e), provider=self.provider_name, cause=e) from e

    async def stream_turn(
        self,
        history: list,
        tools: Optional[list] = None,
        model_override: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
        timeout_s: Optional[float] = None,
    ) -> AsyncGenerator[dict, None]:
        try:
            response = await self.client.chat.completions.create(
                model=model_override or self.model,
                messages=history,
                stream=True,
                timeout=timeout_s,
            )
            async for chunk in response:
                if cancel_event is not None and cancel_event.is_set():
                    return
                delta = chunk.choices[0].delta.content
                if delta:
                    yield ProviderEvent(type="token", text=delta).to_dict()
        except Exception as e:
            raise ProviderError(str(e), provider=self.provider_name, cause=e) from e
