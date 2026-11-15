# modules/mac_control.py

import shutil
import subprocess
import sys


def _run(cmd: list[str], input_text: str = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def mac_open_app(app_name: str) -> str:
    if sys.platform != "darwin":
        return "mac_open_app is only supported on macOS."
    code, _, err = _run(["open", "-a", app_name])
    if code == 0:
        return f"Opened {app_name}."
    return f"Could not open '{app_name}': {err or 'app not found'}"


def mac_clipboard_read() -> str:
    if not shutil.which("pbpaste"):
        return "pbpaste not available on this OS."
    code, out, err = _run(["pbpaste"])
    if code == 0:
        return out if out else "(Clipboard is empty)"
    return f"Failed to read clipboard: {err}"


def mac_clipboard_write(text: str) -> str:
    if not shutil.which("pbcopy"):
        return "pbcopy not available on this OS."
    code, _, err = _run(["pbcopy"], input_text=text)
    if code == 0:
        return "Copied text to Mac clipboard."
    return f"Failed to write clipboard: {err}"


def mac_system_info() -> str:
    if sys.platform != "darwin":
        return "mac_system_info is only supported on macOS."
    _, batt, _ = _run(["pmset", "-g", "batt"])
    _, up, _ = _run(["uptime"])
    return f"Battery:\n{batt}\n\nUptime:\n{up}"


def register_tools(registry):
    registry.register(
        name="mac_open_app",
        description="Open an application on the user's Mac (e.g., Spotify, Safari, Terminal, Visual Studio Code).",
        parameters={
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "Application name on macOS"}
            },
            "required": ["app_name"],
        },
        handler=mac_open_app,
    )
    registry.register(
        name="mac_clipboard_read",
        description="Read the current text contents of the Mac clipboard.",
        parameters={"type": "object", "properties": {}},
        handler=mac_clipboard_read,
    )
    registry.register(
        name="mac_clipboard_write",
        description="Copy text to the Mac clipboard.",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to copy to clipboard"}
            },
            "required": ["text"],
        },
        handler=mac_clipboard_write,
    )
    registry.register(
        name="mac_system_info",
        description="Get Mac battery status, charging state, and system uptime.",
        parameters={"type": "object", "properties": {}},
        handler=mac_system_info,
    )
