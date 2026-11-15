# creed/modules/base_ai.py

from abc import ABC, abstractmethod
from typing import AsyncGenerator


class BaseAIProvider(ABC):
    """
    Abstract base class for all AI models (LLMs) used in CREED.
    Ensures consistent signature interfaces for both local (Ollama)
    and cloud-based (Groq, OpenAI) endpoints.
    """

    @abstractmethod
    async def chat(self, history: list) -> str:
        """
        Execute a chat query against the model and return the completed response.

        Args:
            history (list): A list of dialogue turns (e.g. [{'role': 'user', 'content': '...'}]).

        Returns:
            str: The assistant's text response.
        """
        pass

    @abstractmethod
    async def stream_chat(self, history: list) -> AsyncGenerator[str, None]:
        """
        Execute a chat query against the model and stream the response token-by-token.

        Args:
            history (list): A list of dialogue turns.

        Yields:
            str: The next token of the response.
        """
        pass
