import asyncio
import json
import logging
import os
from typing import Any, AsyncGenerator, Optional
from dotenv import load_dotenv
from groq import AsyncGroq
from modules.base_ai import BaseAIProvider, ProviderError, ProviderEvent, ProviderUnavailableError

load_dotenv()
logger = logging.getLogger("CreedCloudAI")

# Verified Groq models supporting OpenAI-compatible function/tool calling.
# Update this registry as new Groq models are verified.
GROQ_TOOL_CAPABLE_MODELS: frozenset[str] = frozenset(
    {
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "llama3-groq-70b-8192-tool-use-preview",
        "llama3-groq-8b-8192-tool-use-preview",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "meta-llama/llama-4-maverick-17b-128e-instruct",
        "qwen/qwen3-32b",
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "moonshotai/kimi-k2-instruct",
        "moonshotai/kimi-k2-instruct-0905",
    }
)


class CloudModule(BaseAIProvider):
    """Optional Groq cloud provider implementing the unified BaseAIProvider contract."""

    provider_name = "groq"
    tier = "cloud"
    supports_tools = True

    def __init__(self, model: str = "llama-3.1-8b-instant", client: Optional[Any] = None):
        if client is None:
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise ProviderUnavailableError("GROQ_API_KEY not set", provider=self.provider_name)
            self.client = AsyncGroq(api_key=api_key)
        else:
            self.client = client
        self.model = model
        self.endpoint = "https://api.groq.com"
        logger.info(f"CloudModule initialized (model={self.model})")

    @staticmethod
    def is_tool_calling_supported(model: Optional[str]) -> bool:
        """Verify tool-calling compatibility for a specific Groq model ID."""
        if not model:
            return False
        normalized = model.strip().lower()
        return normalized in GROQ_TOOL_CAPABLE_MODELS

    def supports_tools_for_model(self, model: Optional[str] = None) -> bool:
        return self.is_tool_calling_supported(model or self.model)

    @staticmethod
    def _format_messages_for_openai(history: list) -> list[dict]:
        """Convert CREED internal tool-loop messages into OpenAI/Groq chat format."""
        formatted: list[dict] = []
        pending_tool_ids: list[str] = []
        call_counter = 0

        for msg in history:
            role = msg.get("role", "user")
            if role == "assistant" and msg.get("tool_calls"):
                openai_calls = []
                pending_tool_ids = []
                for tc in msg.get("tool_calls", []):
                    call_id = tc.get("id") or f"call_{call_counter}"
                    call_counter += 1
                    fn = tc.get("function") or {}
                    args = fn.get("arguments", {})
                    args_str = args if isinstance(args, str) else json.dumps(args or {})
                    openai_calls.append(
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": fn.get("name", ""),
                                "arguments": args_str,
                            },
                        }
                    )
                    pending_tool_ids.append(call_id)
                formatted.append(
                    {
                        "role": "assistant",
                        "content": msg.get("content") or "",
                        "tool_calls": openai_calls,
                    }
                )
            elif role == "tool":
                tool_call_id = msg.get("tool_call_id") or (
                    pending_tool_ids.pop(0) if pending_tool_ids else f"call_{call_counter}"
                )
                formatted.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": str(msg.get("content", "")),
                    }
                )
            else:
                formatted.append(
                    {
                        "role": role,
                        "content": msg.get("content", ""),
                    }
                )
        return formatted

    async def chat(self, history: list, model_override: Optional[str] = None) -> str:
        try:
            response = await self.client.chat.completions.create(
                model=model_override or self.model,
                messages=self._format_messages_for_openai(history),
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
        active_model = model_override or self.model
        if tools and not self.supports_tools_for_model(active_model):
            raise ProviderUnavailableError(
                f"Groq model '{active_model}' does not support tool calling.",
                provider=self.provider_name,
            )

        req_kwargs: dict[str, Any] = {
            "model": active_model,
            "messages": self._format_messages_for_openai(history),
            "stream": True,
            "timeout": timeout_s,
        }
        if tools:
            req_kwargs["tools"] = tools
            req_kwargs["tool_choice"] = "auto"

        assembled_calls: dict[int, dict[str, Any]] = {}

        try:
            response = await self.client.chat.completions.create(**req_kwargs)
            async for chunk in response:
                if cancel_event is not None and cancel_event.is_set():
                    return
                if not getattr(chunk, "choices", None):
                    continue
                delta = chunk.choices[0].delta
                text_delta = getattr(delta, "content", None)
                if text_delta:
                    yield ProviderEvent(type="token", text=text_delta).to_dict()

                delta_tool_calls = getattr(delta, "tool_calls", None)
                if delta_tool_calls:
                    for tc in delta_tool_calls:
                        idx = int(getattr(tc, "index", 0) or 0)
                        entry = assembled_calls.setdefault(
                            idx,
                            {"id": "", "name": "", "arguments_parts": []},
                        )
                        tc_id = getattr(tc, "id", None)
                        if tc_id:
                            entry["id"] = tc_id
                        fn = getattr(tc, "function", None)
                        if fn is not None:
                            fn_name = getattr(fn, "name", None)
                            if fn_name:
                                entry["name"] += fn_name
                            fn_args = getattr(fn, "arguments", None)
                            if fn_args is not None:
                                entry["arguments_parts"].append(str(fn_args))

            if assembled_calls and not (cancel_event and cancel_event.is_set()):
                parsed_calls: list[dict[str, Any]] = []
                for idx in sorted(assembled_calls.keys()):
                    entry = assembled_calls[idx]
                    fn_name = (entry["name"] or "").strip()
                    if not fn_name:
                        raise ProviderError(
                            f"Cloud provider '{self.provider_name}' emitted a tool call without a function name.",
                            provider=self.provider_name,
                        )
                    raw_args = "".join(entry["arguments_parts"]).strip()
                    if not raw_args:
                        parsed_args: dict[str, Any] = {}
                    else:
                        try:
                            loaded = json.loads(raw_args)
                        except json.JSONDecodeError as exc:
                            raise ProviderError(
                                f"Malformed JSON tool arguments for '{fn_name}': {exc}",
                                provider=self.provider_name,
                                cause=exc,
                            ) from exc
                        if not isinstance(loaded, dict):
                            raise ProviderError(
                                f"Tool arguments for '{fn_name}' must decode to a JSON object.",
                                provider=self.provider_name,
                            )
                        parsed_args = loaded
                    parsed_calls.append(
                        {
                            "id": entry["id"] or f"call_{idx}",
                            "function": {
                                "name": fn_name,
                                "arguments": parsed_args,
                            },
                        }
                    )
                yield ProviderEvent(type="tool_calls", calls=parsed_calls).to_dict()
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(str(e), provider=self.provider_name, cause=e) from e
