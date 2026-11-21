# intelligence/model_router.py

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from config.settings import config
from intelligence.complexity_classifier import ClassificationResult, classify_complexity

ROUTING_REASONS = frozenset(
    {
        "local_default",
        "privacy_restriction",
        "cloud_complexity_escalation",
        "manual_override",
        "cloud_unavailable_fallback",
    }
)

_SENSITIVE_TEXT_FALLBACK = re.compile(
    r"(?:~/|/Users/|\.env\b|\b(?:my notes|my files|my tasks|my reminders|"
    r"password|api[_ ]?key|secret|private key|ssh key|token)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ContextPrivacyMetadata:
    """Explicit privacy metadata supplied by context-producing components."""

    has_retrieved_memories: bool = False
    has_ongoing_work_context: bool = False
    has_local_files: bool = False
    has_personal_notes: bool = False
    has_private_conversation: bool = False
    explicit_sensitivity: Optional[str] = None  # "private" | "public" | None
    sources: tuple[str, ...] = ()

    @property
    def is_private(self) -> bool:
        if self.explicit_sensitivity == "private":
            return True
        return any(
            (
                self.has_retrieved_memories,
                self.has_ongoing_work_context,
                self.has_local_files,
                self.has_personal_notes,
                self.has_private_conversation,
            )
        )


@dataclass
class RouteDecision:
    path: str  # "instant" | "intelligent" | "background"
    model: str
    reason: str
    classifier_ms: float
    needs_tools: bool
    allow_background_tools: bool = False
    provider: str = "local"
    tier: str = "local"  # "local" | "cloud"
    routing_reason: str = "local_default"
    privacy_classification: str = "public"  # "public" | "private"
    fallback_occurred: bool = False
    fallback_reason: str = ""
    requested_provider: str = ""
    requested_model: str = ""
    provider_unavailable: bool = False


class ModelRouter:
    """Privacy-first, capability-aware local/cloud router across Instant, Intelligent, and Background paths."""

    def _pick_installed(self, candidates: list[str], installed: list[str], fallback: str) -> str:
        for cand in candidates:
            if not cand:
                continue
            for m in installed:
                if cand == m:
                    return m
            for m in installed:
                if m.startswith(cand):
                    return m
        return fallback

    @staticmethod
    def classify_privacy(
        text: str,
        privacy_meta: Optional[ContextPrivacyMetadata] = None,
    ) -> str:
        """
        Classify turn privacy using explicit component metadata first,
        with keyword heuristics only as a secondary fallback.
        """
        if privacy_meta is not None:
            if privacy_meta.is_private:
                return "private"
            if privacy_meta.explicit_sensitivity == "public" and not _SENSITIVE_TEXT_FALLBACK.search(text or ""):
                return "public"
        if _SENSITIVE_TEXT_FALLBACK.search(text or ""):
            return "private"
        return "public"

    @staticmethod
    def _pick_local_provider(
        local_providers: Optional[list[dict]],
        *,
        active_provider: str,
        active_tier: str,
        active_supports_tools: bool,
        needs_tools: bool,
        preferred: Optional[str] = None,
    ) -> tuple[str, str, bool]:
        """Select a compatible local provider without hardcoding Ollama as the only backend."""
        providers = list(local_providers or [])
        if not providers:
            if active_tier == "local":
                return active_provider, "", active_supports_tools
            return config.local_provider or "local", "", True

        if preferred:
            pref_key = preferred.strip().lower()
            for p in providers:
                if p.get("name") == pref_key and (not needs_tools or p.get("supports_tools", True)):
                    return p["name"], p.get("default_model", ""), bool(p.get("supports_tools", True))

        if active_tier == "local":
            for p in providers:
                if p.get("name") == active_provider and (not needs_tools or p.get("supports_tools", True)):
                    return p["name"], p.get("default_model", ""), bool(p.get("supports_tools", True))

        for p in providers:
            if not needs_tools or p.get("supports_tools", True):
                return p["name"], p.get("default_model", ""), bool(p.get("supports_tools", True))

        first = providers[0]
        return first["name"], first.get("default_model", ""), bool(first.get("supports_tools", True))

    @staticmethod
    def _pick_cloud_provider(
        cloud_providers: Optional[list[dict]],
        *,
        needs_tools: bool,
        preferred: Optional[str] = None,
    ) -> Optional[dict]:
        providers = list(cloud_providers or [])
        if not providers:
            return None
        if preferred:
            pref_key = preferred.strip().lower()
            for p in providers:
                if p.get("name") == pref_key:
                    if not needs_tools or p.get("supports_tools", False):
                        return p
                    return None
            return None
        pref_cfg = (config.cloud_provider or "").strip().lower()
        for p in providers:
            if p.get("name") == pref_cfg and (not needs_tools or p.get("supports_tools", False)):
                return p
        for p in providers:
            if not needs_tools or p.get("supports_tools", False):
                return p
        return None

    def route(
        self,
        text: str,
        installed_models: list[str],
        active_model: str,
        mode: str = "default",
        *,
        privacy_meta: Optional[ContextPrivacyMetadata] = None,
        allow_cloud_escalation: Optional[bool] = None,
        cloud_privacy_mode: Optional[str] = None,
        allow_private_cloud: bool = False,
        selected_provider: Optional[str] = None,
        selected_model: Optional[str] = None,
        local_providers: Optional[list[dict]] = None,
        cloud_providers: Optional[list[dict]] = None,
        active_provider: str = "ollama",
        active_provider_tier: str = "local",
        active_provider_supports_tools: bool = True,
    ) -> RouteDecision:
        cls: ClassificationResult = classify_complexity(text, mode=mode)
        privacy_classification = self.classify_privacy(text, privacy_meta)
        is_private = privacy_classification == "private"

        eff_allow_cloud = (
            config.allow_cloud_escalation
            if allow_cloud_escalation is None
            else bool(allow_cloud_escalation)
        )
        eff_privacy_mode = (cloud_privacy_mode or config.cloud_privacy_mode or "local_on_private").strip().lower()
        privacy_blocks_cloud = (
            is_private
            and eff_privacy_mode == "local_on_private"
            and not allow_private_cloud
        )

        fast_candidates = [
            config.fast_model,
            "qwen2.5:3b",
            "qwen2.5:1.5b",
            "llama3.2:3b",
            "qwen2.5-coder:7b",
            active_model,
        ]
        reasoning_candidates = [
            config.jee_tutor_model if mode == "jee" else config.reasoning_model,
            config.reasoning_model,
            config.jee_tutor_model,
            "qwen3:8b",
            "deepseek-r1:8b",
            "qwen2.5-coder:7b",
            "llama3.1:8b",
            active_model,
        ]

        if cls.path == "instant":
            default_local_model = self._pick_installed(fast_candidates, installed_models, active_model)
        else:
            default_local_model = self._pick_installed(reasoning_candidates, installed_models, active_model)

        local_name, local_default_model, _ = self._pick_local_provider(
            local_providers,
            active_provider=active_provider,
            active_tier=active_provider_tier,
            active_supports_tools=active_provider_supports_tools,
            needs_tools=cls.needs_tools,
        )
        resolved_local_model = default_local_model or local_default_model or active_model

        req_provider = (selected_provider or "").strip().lower()
        req_model = (selected_model or "").strip()

        # 1. Manual provider/model override
        if req_provider or req_model:
            all_by_name = {
                p["name"]: p for p in list(local_providers or []) + list(cloud_providers or [])
            }
            if not all_by_name and active_provider:
                all_by_name[active_provider.lower()] = {
                    "name": active_provider.lower(),
                    "tier": active_provider_tier,
                    "supports_tools": active_provider_supports_tools,
                    "default_model": active_model,
                }

            target_name = req_provider or (active_provider.lower() if active_provider else local_name)
            target_info = all_by_name.get(target_name)

            if target_info is None:
                return RouteDecision(
                    path=cls.path,
                    model=req_model or resolved_local_model,
                    reason=cls.reason,
                    classifier_ms=cls.latency_ms,
                    needs_tools=cls.needs_tools,
                    allow_background_tools=cls.allow_background_tools,
                    provider=target_name,
                    tier="unknown",
                    routing_reason="manual_override",
                    privacy_classification=privacy_classification,
                    fallback_occurred=False,
                    requested_provider=req_provider,
                    requested_model=req_model,
                    provider_unavailable=True,
                )

            target_tier = target_info.get("tier", "local")
            target_supports_tools = bool(target_info.get("supports_tools", True))

            if target_tier == "cloud":
                if privacy_blocks_cloud:
                    return RouteDecision(
                        path=cls.path,
                        model=resolved_local_model,
                        reason=cls.reason,
                        classifier_ms=cls.latency_ms,
                        needs_tools=cls.needs_tools,
                        allow_background_tools=cls.allow_background_tools,
                        provider=local_name,
                        tier="local",
                        routing_reason="privacy_restriction",
                        privacy_classification=privacy_classification,
                        fallback_occurred=True,
                        fallback_reason=(
                            f"Manual cloud selection '{target_name}' blocked by privacy policy "
                            f"({eff_privacy_mode}); routed to local '{local_name}'."
                        ),
                        requested_provider=req_provider,
                        requested_model=req_model,
                    )

                if cls.needs_tools and not target_supports_tools:
                    return RouteDecision(
                        path=cls.path,
                        model=resolved_local_model,
                        reason=cls.reason,
                        classifier_ms=cls.latency_ms,
                        needs_tools=cls.needs_tools,
                        allow_background_tools=cls.allow_background_tools,
                        provider=local_name,
                        tier="local",
                        routing_reason="local_default",
                        privacy_classification=privacy_classification,
                        fallback_occurred=True,
                        fallback_reason=(
                            f"Cloud provider '{target_name}' lacks tool-calling support for this turn; "
                            f"kept on local '{local_name}'."
                        ),
                        requested_provider=req_provider,
                        requested_model=req_model,
                    )

                chosen_cloud_model = req_model or target_info.get("default_model") or config.cloud_model
                return RouteDecision(
                    path=cls.path,
                    model=chosen_cloud_model,
                    reason=cls.reason,
                    classifier_ms=cls.latency_ms,
                    needs_tools=cls.needs_tools,
                    allow_background_tools=cls.allow_background_tools,
                    provider=target_name,
                    tier="cloud",
                    routing_reason="manual_override",
                    privacy_classification=privacy_classification,
                    fallback_occurred=False,
                    requested_provider=req_provider,
                    requested_model=req_model,
                )

            # Local manual override
            if cls.needs_tools and not target_supports_tools:
                return RouteDecision(
                    path=cls.path,
                    model=resolved_local_model,
                    reason=cls.reason,
                    classifier_ms=cls.latency_ms,
                    needs_tools=cls.needs_tools,
                    allow_background_tools=cls.allow_background_tools,
                    provider=local_name,
                    tier="local",
                    routing_reason="local_default",
                    privacy_classification=privacy_classification,
                    fallback_occurred=True,
                    fallback_reason=(
                        f"Selected local provider '{target_name}' lacks tool-calling support; "
                        f"using compatible local '{local_name}'."
                    ),
                    requested_provider=req_provider,
                    requested_model=req_model,
                )

            chosen_local_model = req_model or resolved_local_model or target_info.get("default_model", "")
            return RouteDecision(
                path=cls.path,
                model=chosen_local_model,
                reason=cls.reason,
                classifier_ms=cls.latency_ms,
                needs_tools=cls.needs_tools,
                allow_background_tools=cls.allow_background_tools,
                provider=target_name,
                tier="local",
                routing_reason="manual_override",
                privacy_classification=privacy_classification,
                fallback_occurred=False,
                requested_provider=req_provider,
                requested_model=req_model,
            )

        # 2. Automatic routing: privacy-first local default vs. optional cloud escalation
        if eff_allow_cloud and cls.path in ("intelligent", "background"):
            if privacy_blocks_cloud:
                return RouteDecision(
                    path=cls.path,
                    model=resolved_local_model,
                    reason=cls.reason,
                    classifier_ms=cls.latency_ms,
                    needs_tools=cls.needs_tools,
                    allow_background_tools=cls.allow_background_tools,
                    provider=local_name,
                    tier="local",
                    routing_reason="privacy_restriction",
                    privacy_classification=privacy_classification,
                )

            cloud_cand = self._pick_cloud_provider(cloud_providers, needs_tools=cls.needs_tools)
            if cloud_cand is not None:
                cloud_model = cloud_cand.get("default_model") or config.cloud_model
                return RouteDecision(
                    path=cls.path,
                    model=cloud_model,
                    reason=cls.reason,
                    classifier_ms=cls.latency_ms,
                    needs_tools=cls.needs_tools,
                    allow_background_tools=cls.allow_background_tools,
                    provider=cloud_cand["name"],
                    tier="cloud",
                    routing_reason="cloud_complexity_escalation",
                    privacy_classification=privacy_classification,
                )

        return RouteDecision(
            path=cls.path,
            model=resolved_local_model,
            reason=cls.reason,
            classifier_ms=cls.latency_ms,
            needs_tools=cls.needs_tools,
            allow_background_tools=cls.allow_background_tools,
            provider=local_name,
            tier="local",
            routing_reason="local_default",
            privacy_classification=privacy_classification,
        )
