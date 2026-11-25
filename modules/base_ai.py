# modules/base_ai.py

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional


class ProviderError(RuntimeError):
    """Base error raised by all LLM providers."""

    def __init__(self, message: str, provider: str = "", cause: Optional[BaseException] = None):
        super().__init__(message)
        self.provider = provider
        self.cause = cause


class ProviderUnavailableError(ProviderError):
    """Raised when a provider backend or model endpoint cannot be reached."""


class ProviderTimeoutError(ProviderError):
    """Raised when a provider request or stream exceeds its configured timeout."""


@dataclass
class ProviderRequest:
    messages: List[Dict[str, Any]]
    model: Optional[str] = None
    tools: Optional[List[Dict[str, Any]]] = None
    timeout_s: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderEvent:
    type: str  # "token" | "tool_calls" | "done"
    text: str = ""
    calls: List[Dict[str, Any]] = field(default_factory=list)
    usage: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        if self.type == "token":
            return {"type": "token", "text": self.text}
        if self.type == "tool_calls":
            return {"type": "tool_calls", "calls": self.calls}
        return {"type": self.type, "text": self.text, "calls": self.calls, "usage": self.usage}


class BaseAIProvider(ABC):
    """
    Unified provider-agnostic contract for all LLMs (local Ollama, cloud, or mock).
    Providers must NOT import UI, engine, or storage internals.
    """

    provider_name: str = "base"
    tier: str = "local"
    supports_tools: bool = True
    model: str = ""
    endpoint: str = ""

    @abstractmethod
    async def chat(self, history: list, model_override: Optional[str] = None) -> str:
        """Execute a non-streaming completion and return the full assistant text."""

    @abstractmethod
    async def stream_turn(
        self,
        history: list,
        tools: Optional[list] = None,
        model_override: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
        timeout_s: Optional[float] = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Stream standardized turn events:
          - {"type": "token", "text": "..."}
          - {"type": "tool_calls", "calls": [...]}
        Must honor `cancel_event` and `timeout_s`, and raise ProviderError subclasses on failure.
        """
        if False:  # pragma: no cover
            yield {}

    async def stream_chat(self, history: list) -> AsyncGenerator[str, None]:
        """Compatibility adapter yielding plain text tokens from stream_turn()."""
        async for event in self.stream_turn(history):
            if event.get("type") == "token":
                yield event.get("text", "")

    def supports_tools_for_model(self, model: Optional[str] = None) -> bool:
        return bool(self.supports_tools)

    async def health_check(self) -> Dict[str, Any]:
        return {"provider": self.provider_name, "model": self.model, "ok": True}


class MockLLMProvider(BaseAIProvider):
    """
    Deterministic mock provider for offline development and automated testing.
    Supports deterministic responses, chunked streaming, configurable latency,
    simulated failures/timeouts, and cancellation.
    """

    provider_name = "mock"
    tier = "local"
    supports_tools = True

    def __init__(
        self,
        model: str = "mock-llm:latest",
        responses: Optional[Dict[str, str]] = None,
        default_response: str = "Mock response ready.",
        chunk_size: int = 8,
        chunk_delay_s: float = 0.0,
        fail_with: Optional[BaseException] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tier: str = "local",
        supports_tools: bool = True,
        provider_name: str = "mock",
    ):
        self.provider_name = provider_name
        self.tier = tier
        self.supports_tools = supports_tools
        self.model = model
        self.endpoint = "mock://local" if tier == "local" else "mock://cloud"
        self.responses = responses or {}
        self.default_response = default_response
        self.chunk_size = max(1, chunk_size)
        self.chunk_delay_s = max(0.0, chunk_delay_s)
        self.fail_with = fail_with
        self.tool_calls = tool_calls or []
        self.calls: List[Dict[str, Any]] = []

    def _resolve_text(self, history: list) -> str:
        last_user = ""
        for msg in reversed(history):
            if msg.get("role") == "user":
                last_user = str(msg.get("content", ""))
                break
        for key, val in self.responses.items():
            if key.lower() in last_user.lower():
                return val
        return self.default_response

    async def chat(self, history: list, model_override: Optional[str] = None) -> str:
        tokens: List[str] = []
        async for ev in self.stream_turn(history, model_override=model_override):
            if ev.get("type") == "token":
                tokens.append(ev.get("text", ""))
        return "".join(tokens)

    async def stream_turn(
        self,
        history: list,
        tools: Optional[list] = None,
        model_override: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
        timeout_s: Optional[float] = None,
    ) -> AsyncGenerator[dict, None]:
        self.calls.append(
            {"model": model_override or self.model, "tools": tools, "history_len": len(history)}
        )
        if self.fail_with is not None:
            if isinstance(self.fail_with, ProviderError):
                raise self.fail_with
            raise ProviderError(str(self.fail_with), provider=self.provider_name, cause=self.fail_with)

        text = self._resolve_text(history)
        start = asyncio.get_running_loop().time()

        for i in range(0, len(text), self.chunk_size):
            if cancel_event is not None and cancel_event.is_set():
                return
            if timeout_s is not None and (asyncio.get_running_loop().time() - start) > timeout_s:
                raise ProviderTimeoutError(
                    f"MockLLMProvider timed out after {timeout_s}s", provider=self.provider_name
                )
            if self.chunk_delay_s > 0:
                await asyncio.sleep(self.chunk_delay_s)
            if cancel_event is not None and cancel_event.is_set():
                return
            if timeout_s is not None and (asyncio.get_running_loop().time() - start) > timeout_s:
                raise ProviderTimeoutError(
                    f"MockLLMProvider timed out after {timeout_s}s", provider=self.provider_name
                )
            yield ProviderEvent(type="token", text=text[i : i + self.chunk_size]).to_dict()

        if self.tool_calls and not (cancel_event and cancel_event.is_set()):
            yield ProviderEvent(type="tool_calls", calls=list(self.tool_calls)).to_dict()


class ProviderRegistry:
    """Central registry decoupling CreedEngine from concrete LLM provider classes."""

    def __init__(self):
        self._factories: Dict[str, Callable[..., BaseAIProvider]] = {}
        self._instances: Dict[str, BaseAIProvider] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}
        self._active_name: str = ""

    def register(
        self,
        name: str,
        factory: Callable[..., BaseAIProvider],
        default: bool = False,
        *,
        tier: str = "local",
        supports_tools: bool = True,
        default_model: str = "",
        tool_capability_fn: Optional[Callable[[Optional[str]], bool]] = None,
    ) -> None:
        key = name.strip().lower()
        self._factories[key] = factory
        self._metadata[key] = {
            "name": key,
            "tier": tier,
            "supports_tools": bool(supports_tools),
            "default_model": default_model,
            "tool_capability_fn": tool_capability_fn,
        }
        if default or not self._active_name:
            self._active_name = key

    def register_instance(
        self,
        name: str,
        instance: BaseAIProvider,
        default: bool = False,
        *,
        tier: Optional[str] = None,
        supports_tools: Optional[bool] = None,
        tool_capability_fn: Optional[Callable[[Optional[str]], bool]] = None,
    ) -> None:
        key = name.strip().lower()
        self._instances[key] = instance
        self._factories[key] = lambda **_: instance
        self._metadata[key] = {
            "name": key,
            "tier": tier or getattr(instance, "tier", "local"),
            "supports_tools": (
                bool(supports_tools)
                if supports_tools is not None
                else bool(getattr(instance, "supports_tools", True))
            ),
            "default_model": getattr(instance, "model", ""),
            "tool_capability_fn": tool_capability_fn or getattr(instance, "supports_tools_for_model", None),
        }
        if default or not self._active_name:
            self._active_name = key

    def has_provider(self, name: str) -> bool:
        return (name or "").strip().lower() in self._factories

    def get_metadata(self, name: str) -> Dict[str, Any]:
        key = (name or "").strip().lower()
        if key not in self._factories:
            raise ProviderUnavailableError(f"Unknown LLM provider '{key}'.", provider=key)
        meta = dict(
            self._metadata.get(
                key,
                {"name": key, "tier": "local", "supports_tools": True, "default_model": ""},
            )
        )
        if key in self._instances:
            inst = self._instances[key]
            meta["tier"] = getattr(inst, "tier", meta["tier"])
            meta["supports_tools"] = bool(getattr(inst, "supports_tools", meta["supports_tools"]))
            meta["default_model"] = getattr(inst, "model", meta.get("default_model", ""))
        return meta

    def list_provider_metadata(self, tier: Optional[str] = None) -> List[Dict[str, Any]]:
        ordered = []
        if self._active_name and self._active_name in self._factories:
            ordered.append(self._active_name)
        for k in sorted(self._factories.keys()):
            if k not in ordered:
                ordered.append(k)
        out = [self.get_metadata(k) for k in ordered]
        if tier is not None:
            out = [m for m in out if m.get("tier") == tier]
        return out

    def get(self, name: Optional[str] = None, **kwargs) -> BaseAIProvider:
        key = (name or self._active_name).strip().lower()
        if key in self._instances and not kwargs:
            return self._instances[key]
        if key not in self._factories:
            raise ProviderUnavailableError(
                f"Unknown LLM provider '{key}'. Registered: {sorted(self._factories.keys())}",
                provider=key,
            )
        inst = self._factories[key](**kwargs)
        if not kwargs:
            self._instances[key] = inst
        return inst

    def resolve_provider(
        self,
        name: Optional[str] = None,
        *,
        tier: Optional[str] = None,
        require_tools: bool = False,
        model: Optional[str] = None,
        **kwargs,
    ) -> tuple[str, BaseAIProvider]:
        if name is not None:
            key = name.strip().lower()
            inst = self.get(key, **kwargs)
            if require_tools and not inst.supports_tools_for_model(model):
                raise ProviderUnavailableError(
                    f"Provider '{key}' (model '{model or getattr(inst, 'model', '')}') does not support required tool calling.",
                    provider=key,
                )
            return key, inst

        candidates = self.list_provider_metadata(tier=tier)
        last_err: Optional[Exception] = None
        for meta in candidates:
            if require_tools and not meta.get("supports_tools", True):
                continue
            cand = meta["name"]
            try:
                inst = self.get(cand, **kwargs)
                if require_tools and not inst.supports_tools_for_model(model):
                    continue
                return cand, inst
            except ProviderError as exc:
                last_err = exc
                continue
        if last_err is not None:
            raise ProviderUnavailableError(
                f"No compatible '{tier or 'any'}' provider available: {last_err}",
                provider=tier or "",
                cause=last_err,
            ) from last_err
        raise ProviderUnavailableError(
            f"No compatible '{tier or 'any'}' provider registered (require_tools={require_tools}).",
            provider=tier or "",
        )

    def list_providers(self) -> List[str]:
        return sorted(self._factories.keys())

    @property
    def active_name(self) -> str:
        return self._active_name

    @classmethod
    def create_default(cls) -> "ProviderRegistry":
        from modules.ai import Module as OllamaProvider

        cloud_cls: Optional[Any] = None
        _groq_tool_fn: Optional[Callable[[Optional[str]], bool]] = None
        try:
            from modules.cloud_disable import CloudModule

            cloud_cls = CloudModule
            _groq_tool_fn = CloudModule.is_tool_calling_supported
        except Exception:
            cloud_cls = None
            _groq_tool_fn = None

        def _make_groq(**kw):
            if cloud_cls is None:
                raise ProviderUnavailableError(
                    "Groq cloud provider unavailable: groq package not installed.",
                    provider="groq",
                )
            try:
                return cloud_cls(**kw)
            except Exception as exc:
                raise ProviderUnavailableError(
                    f"Groq cloud provider unavailable: {exc}", provider="groq", cause=exc
                ) from exc

        reg = cls()
        reg.register("ollama", lambda **kw: OllamaProvider(**kw), default=True, tier="local", supports_tools=True)
        reg.register("mock", lambda **kw: MockLLMProvider(**kw), tier="local", supports_tools=True)
        reg.register(
            "groq",
            _make_groq,
            tier="cloud",
            supports_tools=bool(_groq_tool_fn is not None),
            default_model="llama-3.1-8b-instant",
            tool_capability_fn=_groq_tool_fn,
        )
        return reg
