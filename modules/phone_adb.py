# modules/phone_adb.py

import os
import shutil
import subprocess
from pathlib import Path
from config.settings import config

APP_PACKAGES = {
    "whatsapp": "com.whatsapp",
    "spotify": "com.spotify.music",
    "youtube": "com.google.android.youtube",
    "chrome": "com.android.chrome",
    "settings": "com.android.settings",
    "camera": "com.sec.android.app.camera",
    "instagram": "com.instagram.android",
}

KEYEVENTS = {
    "play_pause": "85",
    "next": "87",
    "previous": "88",
    "volume_up": "24",
    "volume_down": "25",
    "mute": "164",
    "home": "3",
    "back": "4",
    "wakeup": "224",
}


def _find_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    candidates = [
        str(Path.home() / "tools/scrcpy" / name),
        f"/opt/homebrew/bin/{name}",
        f"/usr/local/bin/{name}",
        str(Path.home() / "Library/Android/sdk/platform-tools" / name),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


def _run_adb(args: list[str], timeout: int = 10) -> tuple[int, str, str]:
    adb = _find_tool("adb")
    if not adb:
        return 1, "", "adb is not installed. Install with 'brew install android-platform-tools'."
    proc = subprocess.run(
        [adb] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def phone_connect(target: str = "") -> str:
    endpoint = (target or config.phone_adb_target).strip()
    if not endpoint:
        return "No phone IP:port provided and CREED_PHONE_ADB_TARGET is not set in .env."
    code, out, err = _run_adb(["connect", endpoint])
    if code == 0:
        return out or f"Connected to {endpoint}."
    return f"ADB connect failed: {err or out}"


def phone_status() -> str:
    code, devices, err = _run_adb(["devices"])
    if code != 0:
        return err
    _, battery, _ = _run_adb(["shell", "dumpsys", "battery"])
    batt_lines = [
        line.strip()
        for line in battery.splitlines()
        if any(k in line for k in ("level:", "AC powered:", "USB powered:", "Wireless powered:"))
    ]
    batt_summary = "\n".join(batt_lines) if batt_lines else "Battery info unavailable (no active device)."
    return f"ADB Devices:\n{devices}\n\nPhone Battery:\n{batt_summary}"


def phone_launch_app(app: str) -> str:
    package = APP_PACKAGES.get(app.lower().strip(), app.strip())
    code, out, err = _run_adb(
        ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"]
    )
    if code == 0:
        return f"Launched '{app}' ({package}) on phone."
    return f"Failed to launch '{app}': {err or out}"


def phone_media_key(action: str) -> str:
    key = KEYEVENTS.get(action.lower().strip())
    if not key:
        return f"Unknown action '{action}'. Supported: {', '.join(KEYEVENTS.keys())}"
    code, out, err = _run_adb(["shell", "input", "keyevent", key])
    if code == 0:
        return f"Sent '{action}' to phone."
    return f"Failed to send key '{action}': {err or out}"


def phone_mirror_screen() -> str:
    scrcpy = _find_tool("scrcpy")
    if not scrcpy:
        return "scrcpy is not installed. Install with 'brew install scrcpy'."
    subprocess.Popen(
        [scrcpy, "--turn-screen-off"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return "Started scrcpy screen mirroring."


def register_tools(registry):
    registry.register(
        name="phone_connect",
        description="Connect to the user's Android phone over Wi-Fi via ADB (uses CREED_PHONE_ADB_TARGET if target is omitted).",
        parameters={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Optional IP:port, e.g. 192.168.1.50:5555"}
            },
        },
        handler=phone_connect,
    )
    registry.register(
        name="phone_status",
        description="Check connected ADB phone status and battery level.",
        parameters={"type": "object", "properties": {}},
        handler=phone_status,
    )
    registry.register(
        name="phone_launch_app",
        description="Open an app on the Android phone (e.g., whatsapp, spotify, youtube, settings, camera, or a package name).",
        parameters={
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "App name or Android package ID"}
            },
            "required": ["app"],
        },
        handler=phone_launch_app,
    )
    registry.register(
        name="phone_media_key",
        description="Send a media or navigation key to the Android phone (play_pause, next, previous, volume_up, volume_down, mute, home, back, wakeup).",
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "Key action name"}
            },
            "required": ["action"],
        },
        handler=phone_media_key,
    )
    registry.register(
        name="phone_mirror_screen",
        description="Launch scrcpy on the Mac to mirror and control the Android phone screen.",
        parameters={"type": "object", "properties": {}},
        handler=phone_mirror_screen,
    )
