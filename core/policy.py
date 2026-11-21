from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


VALID_SIDE_EFFECTS = ("unknown", "read_only", "local_write", "system_control", "external")

# Host-owned defaults: capabilities that always require user approval regardless of plugin claims
DEFAULT_APPROVAL_REQUIRED_CAPABILITIES = frozenset(
    {
        "shell_exec",
        "system_control",
        "external_network",
        "destructive_write",
        "credential_access",
    }
)


class AuthorizationError(PermissionError):
    """Raised when a tool or task action is denied by the host authorization policy."""


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    requires_approval: bool
    reason: str
    effective_side_effect: str = "unknown"
    capabilities: tuple[str, ...] = ()


def compute_tool_call_hash(
    action_name: str,
    args: dict[str, Any] | None = None,
    plugin_name: str | None = None,
) -> str:
    """Canonical SHA-256 hash binding an approval to the exact action, arguments, and plugin provenance."""
    canonical = json.dumps(
        {"action": action_name, "args": args or {}, "plugin": plugin_name or ""},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class AuthorizationPolicy:
    """
    Host-owned centralized authorization policy shared by foreground turns,
    background agent turns, and TaskOrchestrator step execution.

    Plugin-declared capabilities and approval flags are treated strictly as
    requests/claims; the host policy makes the final allow/approval decision.
    """

    blocked_tools: set[str] = field(default_factory=set)
    blocked_capabilities: set[str] = field(default_factory=set)
    allowed_plugin_capabilities: set[str] | None = None
    approval_required_tools: set[str] = field(default_factory=set)
    approval_required_side_effects: set[str] = field(
        default_factory=lambda: {"unknown", "system_control", "external"}
    )
    approval_required_capabilities: set[str] = field(
        default_factory=lambda: set(DEFAULT_APPROVAL_REQUIRED_CAPABILITIES)
    )

    def evaluate(
        self,
        tool_spec: Any | None,
        action_name: str,
        args: dict[str, Any] | None = None,
    ) -> AuthorizationDecision:
        if action_name in self.blocked_tools:
            return AuthorizationDecision(
                allowed=False,
                requires_approval=False,
                reason=f"Tool '{action_name}' is blocked by host policy.",
            )

        if tool_spec is None:
            return AuthorizationDecision(
                allowed=False,
                requires_approval=False,
                reason=f"Unknown tool '{action_name}'.",
            )

        caps = tuple(getattr(tool_spec, "capabilities", ()) or ())
        side_effect = getattr(tool_spec, "side_effect", "unknown") or "unknown"
        plugin_name = getattr(tool_spec, "plugin_name", None)

        for cap in caps:
            if cap in self.blocked_capabilities:
                return AuthorizationDecision(
                    allowed=False,
                    requires_approval=False,
                    reason=f"Capability '{cap}' is blocked by host policy.",
                    effective_side_effect=side_effect,
                    capabilities=caps,
                )

        if plugin_name and self.allowed_plugin_capabilities is not None:
            disallowed = [c for c in caps if c not in self.allowed_plugin_capabilities]
            if disallowed:
                return AuthorizationDecision(
                    allowed=False,
                    requires_approval=False,
                    reason=(
                        f"Plugin '{plugin_name}' requested unpermitted capabilities: "
                        f"{', '.join(disallowed)}."
                    ),
                    effective_side_effect=side_effect,
                    capabilities=caps,
                )

        reasons: list[str] = []
        if getattr(tool_spec, "requires_approval", False):
            reasons.append("tool requires approval")
        if action_name in self.approval_required_tools:
            reasons.append("host policy requires approval for this tool")
        if side_effect in self.approval_required_side_effects:
            reasons.append(f"side-effect classification '{side_effect}' requires approval")
        sensitive_caps = [c for c in caps if c in self.approval_required_capabilities]
        if sensitive_caps:
            reasons.append(f"sensitive capability ({', '.join(sensitive_caps)}) requires approval")

        if reasons:
            return AuthorizationDecision(
                allowed=True,
                requires_approval=True,
                reason=f"Approval required for '{action_name}': {'; '.join(reasons)}.",
                effective_side_effect=side_effect,
                capabilities=caps,
            )

        return AuthorizationDecision(
            allowed=True,
            requires_approval=False,
            reason="Allowed by host policy.",
            effective_side_effect=side_effect,
            capabilities=caps,
        )

    @staticmethod
    def verify_approval_binding(
        approval: Any,
        action_name: str,
        args: dict[str, Any] | None = None,
        *,
        task_id: str | None = None,
        plugin_name: str | None = None,
    ) -> bool:
        """Verify an approved request matches the exact action, arguments, task, and plugin provenance."""
        if approval is None or getattr(approval, "status", None) != "approved":
            return False
        if getattr(approval, "action", None) != action_name:
            return False
        if getattr(approval, "args", None) != (args or {}):
            return False
        if task_id is not None and getattr(approval, "task_id", None) != task_id:
            return False
        if plugin_name is not None:
            apr_summary = getattr(approval, "action_summary", "") or ""
            if "[plugin:" in apr_summary and f"[plugin:{plugin_name}]" not in apr_summary:
                return False
        return True
