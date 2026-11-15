# modules/bt_audio.py

import json
import shutil
import subprocess
import sys

try:
    import IOBluetooth
except ImportError:
    IOBluetooth = None


def _find_bin(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for prefix in ("/opt/homebrew/bin", "/usr/local/bin"):
        candidate = f"{prefix}/{name}"
        if shutil.which(candidate):
            return candidate
    return ""


def _parse_bt_devices() -> list[dict]:
    if sys.platform != "darwin":
        return []

    if IOBluetooth is not None:
        try:
            paired = IOBluetooth.IOBluetoothDevice.pairedDevices() or []
            devices = []
            for dev in paired:
                devices.append(
                    {
                        "name": dev.name() or "Unknown Device",
                        "address": dev.addressString() or "",
                        "connected": bool(dev.isConnected()),
                        "type": "Bluetooth",
                    }
                )
            if devices:
                return devices
        except Exception:
            pass

    proc = subprocess.run(
        ["system_profiler", "SPBluetoothDataType", "-json"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return []

    try:
        data = json.loads(proc.stdout)
        entries = data.get("SPBluetoothDataType", [])
        devices = []
        for entry in entries:
            for key, connected in (
                ("device_connected", True),
                ("device_not_connected", False),
            ):
                for item in entry.get(key, []):
                    for name, info in item.items():
                        devices.append(
                            {
                                "name": name,
                                "address": info.get("device_address", ""),
                                "connected": connected,
                                "type": info.get("device_minorType", ""),
                            }
                        )
        return devices
    except Exception:
        return []


def bt_list_devices() -> str:
    if sys.platform != "darwin":
        return "bt_list_devices is only supported on macOS."
    devices = _parse_bt_devices()
    if not devices:
        return "No paired Bluetooth devices found."
    lines = []
    for d in devices:
        status = "Connected" if d["connected"] else "Paired (disconnected)"
        lines.append(f"- {d['name']} [{d['address']}] — {status}")
    return "\n".join(lines)


def _find_iobluetooth_device(name_or_mac: str):
    if IOBluetooth is None:
        return None
    target = name_or_mac.strip().lower()
    paired = IOBluetooth.IOBluetoothDevice.pairedDevices() or []
    for dev in paired:
        name = (dev.name() or "").lower()
        addr = (dev.addressString() or "").lower().replace("-", ":")
        norm_target = target.replace("-", ":")
        if norm_target == addr or target in name:
            return dev
    return None


def bt_connect_device(device: str) -> str:
    if sys.platform != "darwin":
        return "bt_connect_device is only supported on macOS."

    if IOBluetooth is None:
        return (
            "Native macOS Bluetooth requires pyobjc-framework-IOBluetooth. "
            "Install it in .venv with: uv pip install pyobjc-framework-IOBluetooth"
        )

    dev = _find_iobluetooth_device(device)
    if not dev:
        return f"Could not find paired Bluetooth device matching '{device}'."

    if dev.isConnected():
        return f"'{dev.name()}' is already connected."

    result = dev.openConnection()
    if result == 0:
        return f"Connected to '{dev.name()}' ({dev.addressString()})."
    return f"Failed to connect '{dev.name()}' (IOReturn={result}). Make sure the speaker is powered on."


def bt_disconnect_device(device: str) -> str:
    if sys.platform != "darwin":
        return "bt_disconnect_device is only supported on macOS."

    if IOBluetooth is None:
        return (
            "Native macOS Bluetooth requires pyobjc-framework-IOBluetooth. "
            "Install it in .venv with: uv pip install pyobjc-framework-IOBluetooth"
        )

    dev = _find_iobluetooth_device(device)
    if not dev:
        return f"Could not find paired Bluetooth device matching '{device}'."

    if not dev.isConnected():
        return f"'{dev.name()}' is already disconnected."

    result = dev.closeConnection()
    if result == 0:
        return f"Disconnected '{dev.name()}' ({dev.addressString()})."
    return f"Failed to disconnect '{dev.name()}' (IOReturn={result})."


def audio_list_outputs() -> str:
    if sys.platform != "darwin":
        return "audio_list_outputs is only supported on macOS."
    sas = _find_bin("SwitchAudioSource")
    if sas:
        proc = subprocess.run(
            [sas, "-a", "-t", "output"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return "Available audio outputs:\n" + proc.stdout.strip()

    proc = subprocess.run(
        ["system_profiler", "SPAudioDataType", "-json"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if proc.returncode != 0:
        return "Could not query audio outputs."
    try:
        data = json.loads(proc.stdout)
        names = []
        for entry in data.get("SPAudioDataType", []):
            for item in entry.get("_items", []):
                if "_name" in item:
                    names.append(f"- {item['_name']}")
        return "Audio devices:\n" + "\n".join(names) if names else "No audio devices found."
    except Exception as e:
        return f"Failed to parse audio devices: {e}"


def audio_set_output(device_name: str) -> str:
    if sys.platform != "darwin":
        return "audio_set_output is only supported on macOS."
    sas = _find_bin("SwitchAudioSource")
    if not sas:
        return "SwitchAudioSource not installed. Connect your speaker via bt_connect_device or select it in macOS Sound settings."
    proc = subprocess.run(
        [sas, "-s", device_name, "-t", "output"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if proc.returncode == 0:
        return f"Switched Mac audio output to '{device_name}'."
    return f"Failed to switch audio output: {proc.stderr.strip() or proc.stdout.strip()}"


def register_tools(registry):
    registry.register(
        name="bt_list_devices",
        description="List paired and connected Bluetooth speakers/devices on the Mac.",
        parameters={"type": "object", "properties": {}},
        handler=bt_list_devices,
    )
    registry.register(
        name="bt_connect_device",
        description="Connect a paired Bluetooth speaker or device by name (e.g., Marshall Willen, LG-RK37, Echo Dot) or MAC address using native macOS IOBluetooth.",
        parameters={
            "type": "object",
            "properties": {
                "device": {"type": "string", "description": "Device name or MAC address"}
            },
            "required": ["device"],
        },
        handler=bt_connect_device,
    )
    registry.register(
        name="bt_disconnect_device",
        description="Disconnect a connected Bluetooth speaker or device by name or MAC address using native macOS IOBluetooth.",
        parameters={
            "type": "object",
            "properties": {
                "device": {"type": "string", "description": "Device name or MAC address"}
            },
            "required": ["device"],
        },
        handler=bt_disconnect_device,
    )
    registry.register(
        name="audio_list_outputs",
        description="List available macOS audio output devices (speakers, multi-output devices, headphones).",
        parameters={"type": "object", "properties": {}},
        handler=audio_list_outputs,
    )
    registry.register(
        name="audio_set_output",
        description="Switch macOS system audio output to a named speaker or multi-output device.",
        parameters={
            "type": "object",
            "properties": {
                "device_name": {"type": "string", "description": "Exact output device name"}
            },
            "required": ["device_name"],
        },
        handler=audio_set_output,
    )
