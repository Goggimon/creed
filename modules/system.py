# modules/system.py

from __future__ import annotations

import subprocess
from datetime import datetime
from typing import Any, Dict, List


class Module:
    name = "system"
    intents = ["time", "date", "hello"]

    def __init__(self, lock):
        self.lock = lock

    def handle(self, intent, text, context):
        now = datetime.now()
        if intent == "time":
            return f"The current time is {now.strftime('%H:%M:%S')}."

        if intent == "date":
            return f"Today is {now.strftime('%A, %B %d, %Y')}."

        if intent == "hello":
            return "Hello."

        return None


class BluetoothAdapter:
    """Independent macOS Bluetooth probe that degrades gracefully if framework is unavailable."""

    def get_status(self) -> Dict[str, Any]:
        try:
            from modules.bt_audio import IOBluetooth, _parse_bt_devices

            devices = _parse_bt_devices()
            connected = [d["name"] for d in devices if d.get("connected")]
            return {
                "id": "bluetooth",
                "name": "Bluetooth & Audio",
                "description": "Paired speaker management and macOS audio output routing.",
                "state": "Online" if IOBluetooth is not None else "Limited (Read-Only)",
                "detail": (
                    f"{len(connected)} connected / {len(devices)} paired"
                    if devices
                    else "No paired speakers"
                ),
            }
        except Exception as e:
            return {
                "id": "bluetooth",
                "name": "Bluetooth & Audio",
                "description": "Paired speaker management and macOS audio output routing.",
                "state": "Degraded",
                "detail": f"Unavailable ({type(e).__name__})",
            }


class ADBAdapter:
    """Independent Android ADB probe that degrades gracefully if adb is missing or disconnected."""

    def get_status(self) -> Dict[str, Any]:
        try:
            from modules.phone_adb import _find_tool

            adb_bin = _find_tool("adb")
            if not adb_bin:
                return {
                    "id": "phone",
                    "name": "Android Phone (ADB)",
                    "description": "Wireless ADB control and scrcpy screen mirroring.",
                    "state": "Standby",
                    "detail": "Not Installed",
                }
            proc = subprocess.run(
                [adb_bin, "devices"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            lines = [
                line for line in proc.stdout.splitlines()[1:] if line.strip() and "device" in line
            ]
            adb_state = f"Connected ({len(lines)} device)" if lines else "Standby (Disconnected)"
            return {
                "id": "phone",
                "name": "Android Phone (ADB)",
                "description": "Wireless ADB control and scrcpy screen mirroring.",
                "state": "Online" if adb_state.startswith("Connected") else "Standby",
                "detail": adb_state,
            }
        except Exception:
            return {
                "id": "phone",
                "name": "Android Phone (ADB)",
                "description": "Wireless ADB control and scrcpy screen mirroring.",
                "state": "Standby",
                "detail": "Standby",
            }


class ModelRuntimeMonitor:
    """Independent Ollama / local LLM runtime monitor with graceful offline fallback."""

    def get_status(self, endpoint: str, active_model: str) -> Dict[str, Any]:
        ollama_online = False
        ollama_detail = "Not running ('ollama serve')"
        ollama_models: List[Dict[str, Any]] = []
        installed_names: List[str] = []

        if endpoint and endpoint.startswith("http"):
            try:
                import httpx

                tags_url = endpoint.replace("/api/chat", "/api/tags")
                r = httpx.get(tags_url, timeout=0.6)
                if r.status_code == 200:
                    raw_models = r.json().get("models", [])
                    ollama_online = True
                    for m in raw_models:
                        details = m.get("details") or {}
                        size_bytes = m.get("size") or 0
                        ollama_models.append(
                            {
                                "name": m.get("name", ""),
                                "size_gb": round(size_bytes / (1024 ** 3), 1) if size_bytes else 0.0,
                                "parameter_size": details.get("parameter_size", "—"),
                                "quantization": details.get("quantization_level", "—"),
                                "family": details.get("family", "—"),
                            }
                        )
                    installed_names = [m["name"] for m in ollama_models]
                    has_model = any(
                        active_model == n or active_model in n for n in installed_names
                    )
                    ollama_detail = (
                        f"{active_model} ready"
                        if has_model
                        else f"Running (pull '{active_model}')"
                    )
            except Exception:
                ollama_online = False

        return {
            "ollama_online": ollama_online,
            "ollama_detail": ollama_detail,
            "ollama_models": ollama_models,
            "installed_model_names": installed_names,
            "system_card": {
                "id": "llm",
                "name": "Local LLM (Ollama)",
                "description": "Primary reasoning and tool-calling engine.",
                "state": "Online" if ollama_online else "Offline",
                "detail": ollama_detail,
            },
        }


class SystemMonitor:
    """Aggregates hardware and runtime adapters into a standardized system-state object."""

    def __init__(
        self,
        bluetooth: BluetoothAdapter = None,
        adb: ADBAdapter = None,
        model_runtime: ModelRuntimeMonitor = None,
    ):
        self.bluetooth = bluetooth or BluetoothAdapter()
        self.adb = adb or ADBAdapter()
        self.model_runtime = model_runtime or ModelRuntimeMonitor()

    def probe(self, endpoint: str, active_model: str) -> Dict[str, Any]:
        bt_card = self.bluetooth.get_status()
        adb_card = self.adb.get_status()
        llm_info = self.model_runtime.get_status(endpoint, active_model)
        mac_card = {
            "id": "mac",
            "name": "macOS Host",
            "description": "Local Apple Silicon control (apps, files, Python runner, clipboard).",
            "state": "Online",
            "detail": "Native open / pbcopy / pmset / fs",
        }
        return {
            "ollama_online": llm_info["ollama_online"],
            "ollama_detail": llm_info["ollama_detail"],
            "ollama_models": llm_info["ollama_models"],
            "installed_model_names": llm_info["installed_model_names"],
            "systems": [mac_card, bt_card, adb_card, llm_info["system_card"]],
        }
