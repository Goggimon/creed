import logging
import os
from typing import AsyncGenerator
from dotenv import load_dotenv
from groq import AsyncGroq
from modules.base_ai import BaseAIProvider

load_dotenv()
logger = logging.getLogger("CreedCloudAI")


class CloudModule(BaseAIProvider):
    """Optional Groq cloud provider (kept disabled in CreedEngine by default)."""

    def __init__(self, model: str = "llama-3.1-8b-instant"):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not set")

        self.client = AsyncGroq(api_key=api_key)
        self.model = model
        logger.info(f"CloudModule initialized (model={self.model})")

    async def chat(self, history: list) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=history,
            stream=False,
        )
        return response.choices[0].message.content or ""

    async def stream_chat(self, history: list) -> AsyncGenerator[str, None]:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=history,
            stream=True,
        )

        async for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
