from __future__ import annotations

import importlib.util
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from core.tools import ToolRegistry
from utils.logger import log_event

_VALID_PLUGIN_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_VALID_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+)*(?:-[a-zA-Z0-9._-]+)?$")


class PluginError(Exception):
    """Base error for plugin discovery, validation, or activation."""


@dataclass
class PluginRecord:
    name: str
    version: str
    path: str
    entrypoint: str
    description: str = ""
    capabilities: tuple[str, ...] = ()
    trusted: bool = False
    enabled: bool = False
    loaded: bool = False
    manifest_valid: bool = False
    health: str = "discovered"  # discovered | untrusted | disabled | ready | error
    error: Optional[str] = None
    registered_tools: list[str] = field(default_factory=list)


class _PluginToolRegistrar:
    """Scoped registration facade passed to activated plugins."""

    def __init__(self, registry: ToolRegistry, plugin_name: str, record: PluginRecord):
        self._registry = registry
        self._plugin_name = plugin_name
        self._record = record

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[..., Any],
        *,
        capabilities: Optional[Iterable[str]] = None,
        side_effect: str = "read_only",
        requires_approval: bool = False,
        policy_metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        self._registry.register(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            capabilities=capabilities,
            side_effect=side_effect,
            requires_approval=requires_approval,
            policy_metadata=policy_metadata,
            plugin_name=self._plugin_name,
        )
        if name not in self._record.registered_tools:
            self._record.registered_tools.append(name)


class PluginManager:
    """
    Local manifest-backed plugin discovery and host-gated activation.

    Discovery inspects plugin.json files without importing or executing code.
    Activation requires explicit host trust and enablement.
    """

    def __init__(
        self,
        plugins_dir: str | Path,
        registry: ToolRegistry,
        *,
        trusted_plugins: Optional[Iterable[str]] = None,
        enabled_plugins: Optional[Iterable[str]] = None,
        trust_file: Optional[str | Path] = None,
    ):
        self.plugins_dir = Path(plugins_dir)
        self.registry = registry
        self._trusted: set[str] = {str(p).strip() for p in (trusted_plugins or ()) if str(p).strip()}
        self._enabled: set[str] = {str(p).strip() for p in (enabled_plugins or ()) if str(p).strip()}
        self.trust_file = Path(trust_file) if trust_file else None
        self._records: dict[str, PluginRecord] = {}
        self._load_trust_file()

    def _load_trust_file(self) -> None:
        if not self.trust_file or not self.trust_file.exists():
            return
        try:
            data = json.loads(self.trust_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._trusted.update(str(p) for p in data.get("trusted", []) if p)
                self._enabled.update(str(p) for p in data.get("enabled", []) if p)
        except Exception as exc:
            log_event("PluginManager", "trust_file_load_failed", level="WARNING", exc=exc)

    def _save_trust_file(self) -> None:
        if not self.trust_file:
            return
        self.trust_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "trusted": sorted(self._trusted),
            "enabled": sorted(self._enabled),
        }
        self.trust_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def set_trust(self, name: str, trusted: bool) -> None:
        if trusted:
            self._trusted.add(name)
        else:
            self._trusted.discard(name)
        if name in self._records:
            self._records[name].trusted = trusted
            self._refresh_status(self._records[name])
        self._save_trust_file()

    def set_enabled(self, name: str, enabled: bool) -> None:
        if enabled:
            self._enabled.add(name)
        else:
            self._enabled.discard(name)
        if name in self._records:
            self._records[name].enabled = enabled
            self._refresh_status(self._records[name])
        self._save_trust_file()

    @staticmethod
    def _refresh_status(rec: PluginRecord) -> None:
        if not rec.manifest_valid or rec.error:
            rec.health = "error"
        elif rec.loaded:
            rec.health = "ready"
        elif not rec.trusted:
            rec.health = "untrusted"
        elif not rec.enabled:
            rec.health = "disabled"
        else:
            rec.health = "discovered"

    def discover(self) -> list[PluginRecord]:
        """Discover and validate local plugin.json manifests without executing plugin code."""
        if not self.plugins_dir.exists() or not self.plugins_dir.is_dir():
            return []

        discovered: list[PluginRecord] = []
        for entry in sorted(self.plugins_dir.iterdir()):
            if not entry.is_dir():
                continue
            manifest_path = entry / "plugin.json"
            if not manifest_path.exists():
                continue
            rec = self._parse_and_validate_manifest(entry, manifest_path)
            existing = self._records.get(rec.name)
            if existing and existing.loaded:
                rec.loaded = True
                rec.registered_tools = list(existing.registered_tools)
            self._refresh_status(rec)
            self._records[rec.name] = rec
            discovered.append(rec)
        return discovered

    def _parse_and_validate_manifest(self, plugin_dir: Path, manifest_path: Path) -> PluginRecord:
        fallback_name = plugin_dir.name
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return PluginRecord(
                name=fallback_name,
                version="0.0.0",
                path=str(plugin_dir),
                entrypoint="",
                manifest_valid=False,
                health="error",
                error=f"Invalid JSON in plugin.json: {exc}",
            )

        if not isinstance(raw, dict):
            return PluginRecord(
                name=fallback_name,
                version="0.0.0",
                path=str(plugin_dir),
                entrypoint="",
                manifest_valid=False,
                health="error",
                error="plugin.json must be a JSON object.",
            )

        name = str(raw.get("name", "")).strip()
        version = str(raw.get("version", "")).strip()
        entrypoint = str(raw.get("entrypoint", "")).strip()
        description = str(raw.get("description", "")).strip()
        caps_raw = raw.get("capabilities", [])

        err: Optional[str] = None
        if not _VALID_PLUGIN_NAME.match(name):
            err = f"Invalid plugin name '{name}'."
        elif not _VALID_VERSION.match(version):
            err = f"Invalid plugin version '{version}'."
        elif not isinstance(caps_raw, list) or not all(isinstance(c, str) and c.strip() for c in caps_raw):
            err = "Manifest 'capabilities' must be a list of non-empty strings."
        elif ":" not in entrypoint:
            err = "Manifest 'entrypoint' must be '<relative_module.py>:<callable>'."
        else:
            mod_rel, fn_name = entrypoint.split(":", 1)
            mod_rel = mod_rel.strip()
            fn_name = fn_name.strip()
            if not mod_rel or not fn_name or Path(mod_rel).is_absolute():
                err = f"Invalid entrypoint '{entrypoint}'."
            else:
                try:
                    resolved_dir = plugin_dir.resolve()
                    resolved_mod = (plugin_dir / mod_rel).resolve()
                    resolved_mod.relative_to(resolved_dir)
                except Exception:
                    err = f"Entrypoint '{entrypoint}' escapes plugin directory."
                else:
                    if not resolved_mod.exists() or not resolved_mod.is_file():
                        err = f"Entrypoint file '{mod_rel}' does not exist."

        caps = tuple(c.strip() for c in caps_raw) if isinstance(caps_raw, list) else ()
        effective_name = name or fallback_name
        return PluginRecord(
            name=effective_name,
            version=version or "0.0.0",
            path=str(plugin_dir),
            entrypoint=entrypoint,
            description=description,
            capabilities=caps,
            trusted=effective_name in self._trusted,
            enabled=effective_name in self._enabled,
            loaded=False,
            manifest_valid=err is None,
            health="error" if err else "discovered",
            error=err,
        )

    def activate_plugin(self, name: str) -> PluginRecord:
        """Activate a single discovered plugin if valid, trusted, and enabled."""
        rec = self._records.get(name)
        if rec is None:
            raise PluginError(f"Plugin '{name}' not discovered.")
        if not rec.manifest_valid:
            raise PluginError(f"Cannot activate invalid plugin '{name}': {rec.error}")
        if not rec.trusted:
            rec.health = "untrusted"
            raise PluginError(f"Plugin '{name}' is not trusted by host policy.")
        if not rec.enabled:
            rec.health = "disabled"
            raise PluginError(f"Plugin '{name}' is disabled.")
        if rec.loaded:
            return rec

        mod_rel, fn_name = rec.entrypoint.split(":", 1)
        mod_path = (Path(rec.path) / mod_rel.strip()).resolve()
        try:
            spec = importlib.util.spec_from_file_location(f"creed_plugin_{rec.name}", str(mod_path))
            if spec is None or spec.loader is None:
                raise PluginError(f"Failed to create module spec for '{mod_path}'.")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            register_fn = getattr(module, fn_name.strip(), None)
            if not callable(register_fn):
                raise PluginError(f"Entrypoint callable '{fn_name}' not found in '{mod_rel}'.")

            registrar = _PluginToolRegistrar(self.registry, rec.name, rec)
            register_fn(registrar)
            rec.loaded = True
            rec.error = None
            rec.health = "ready"
            log_event(
                "PluginManager",
                "plugin_activated",
                plugin=rec.name,
                version=rec.version,
                tools=rec.registered_tools,
            )
        except Exception as exc:
            rec.loaded = False
            rec.error = str(exc) or type(exc).__name__
            rec.health = "error"
            log_event(
                "PluginManager",
                "plugin_load_failed",
                level="ERROR",
                exc=exc,
                plugin=rec.name,
            )
        return rec

    def activate_trusted(self) -> list[PluginRecord]:
        """Discover manifests and activate only plugins that are valid, trusted, and enabled."""
        self.discover()
        results: list[PluginRecord] = []
        for name, rec in self._records.items():
            if rec.manifest_valid and rec.trusted and rec.enabled and not rec.loaded:
                results.append(self.activate_plugin(name))
            else:
                self._refresh_status(rec)
                results.append(rec)
        return results

    def list_plugins(self) -> list[PluginRecord]:
        return list(self._records.values())

    def get_snapshot(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for rec in self._records.values():
            approval_tools: list[str] = []
            for tool_name in rec.registered_tools:
                decision = self.registry.authorize(tool_name, {})
                if decision.requires_approval:
                    approval_tools.append(tool_name)
            host_cap_requires_approval = any(
                c in self.registry.policy.approval_required_capabilities for c in rec.capabilities
            )
            out.append(
                {
                    "name": rec.name,
                    "version": rec.version,
                    "description": rec.description,
                    "loaded": rec.loaded,
                    "enabled": rec.enabled,
                    "trusted": rec.trusted,
                    "health": rec.health,
                    "error": rec.error,
                    "capabilities": list(rec.capabilities),
                    "tools": list(rec.registered_tools),
                    "requires_approval": bool(approval_tools or host_cap_requires_approval),
                    "approval_tools": approval_tools,
                }
            )
        return out
