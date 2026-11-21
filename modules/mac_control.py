# modules/mac_control.py

import shutil
import subprocess
import sys
from pathlib import Path

DOCUMENTS_ROOT = (Path.home() / "Documents").resolve()


def _run(cmd: list[str], input_text: str = None, timeout: int = 10) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _resolve_safe_path(path_str: str) -> Path:
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = DOCUMENTS_ROOT / p
    resolved = p.resolve()
    if DOCUMENTS_ROOT not in resolved.parents and resolved != DOCUMENTS_ROOT:
        raise ValueError(f"Path must be inside {DOCUMENTS_ROOT}")
    return resolved


def mac_open_app(app_name: str) -> str:
    if sys.platform != "darwin":
        return "mac_open_app is only supported on macOS."
    code, _, err = _run(["open", "-a", app_name])
    if code == 0:
        return f"Opened {app_name}."
    return f"Could not open '{app_name}': {err or 'app not found'}"


def mac_open_url(url: str) -> str:
    u = url.strip()
    if not u.startswith(("http://", "https://")):
        return "URL must start with http:// or https://"
    code, _, err = _run(["open", u])
    return f"Opened {u} in browser." if code == 0 else f"Failed to open URL: {err}"


def mac_list_running_apps() -> str:
    code, out, err = _run(["ps", "-Ao", "comm="])
    if code != 0:
        return f"Failed to list apps: {err}"
    apps = sorted({
        Path(line.strip()).name
        for line in out.splitlines()
        if ".app/Contents/MacOS/" in line
    })
    return "Running apps:\n" + ("\n".join(f"- {a}" for a in apps[:25]) if apps else "(none)")


def mac_close_app(app_name: str) -> str:
    name = app_name.strip()
    if not name:
        return "App name is required."
    code, _, _ = _run(["pkill", "-ix", name])
    return f"Closed {name}." if code == 0 else f"No running process matched '{name}'."


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
    _, disk, _ = _run(["df", "-h", str(Path.home())])
    disk_line = disk.splitlines()[-1] if disk else ""
    return f"Battery:\n{batt}\n\nUptime:\n{up}\n\nHome Disk:\n{disk_line}"


def fs_search_files(query: str, subfolder: str = "") -> str:
    try:
        root = _resolve_safe_path(subfolder) if subfolder.strip() else DOCUMENTS_ROOT
        if not root.exists():
            return f"Folder not found: {root}"
        q = query.strip().lower()
        matches = []
        for p in root.rglob("*"):
            if ".venv" in p.parts or ".git" in p.parts or "node_modules" in p.parts:
                continue
            if p.is_file() and (not q or q in p.name.lower()):
                rel = p.relative_to(DOCUMENTS_ROOT)
                matches.append(f"- {rel} ({p.stat().st_size // 1024} KB)")
                if len(matches) >= 20:
                    break
        return "\n".join(matches) if matches else f"No files matching '{query}' in {root}."
    except Exception as e:
        return f"Search failed: {e}"


def fs_write_file(path: str, content: str, open_in_vscode: bool = True) -> str:
    try:
        target = _resolve_safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if open_in_vscode and sys.platform == "darwin":
            _run(["open", "-a", "Visual Studio Code", str(target)])
        return f"Wrote {len(content)} chars to {target}"
    except Exception as e:
        return f"Failed to write file: {e}"


def fs_read_file(path: str) -> str:
    try:
        target = _resolve_safe_path(path)
        if not target.exists():
            return f"File not found: {target}"
        return target.read_text(encoding="utf-8")[:4000]
    except Exception as e:
        return f"Failed to read file: {e}"


def run_python_file(path: str) -> str:
    try:
        target = _resolve_safe_path(path)
        if not target.exists():
            return f"Python file not found: {target}"
        code, out, err = _run([sys.executable, str(target)], timeout=15)
        if code == 0:
            return f"Output:\n{out or '(no output)'}"
        return f"Exit {code}:\n{err or out}"
    except Exception as e:
        return f"Failed to run script: {e}"


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
        capabilities=["mac_app_control"],
        side_effect="system_control",
    )
    registry.register(
        name="mac_open_url",
        description="Open an http/https URL in the user's default Mac browser.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL starting with https:// or http://"}
            },
            "required": ["url"],
        },
        handler=mac_open_url,
        capabilities=["browser_open"],
        side_effect="external",
    )
    registry.register(
        name="mac_list_running_apps",
        description="List currently running GUI applications on the user's Mac.",
        parameters={"type": "object", "properties": {}},
        handler=mac_list_running_apps,
        capabilities=["mac_read"],
        side_effect="read_only",
    )
    registry.register(
        name="mac_close_app",
        description="Close a running user application on macOS by process/app name.",
        parameters={
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "Application/process name to close"}
            },
            "required": ["app_name"],
        },
        handler=mac_close_app,
        capabilities=["mac_app_control"],
        side_effect="system_control",
        requires_approval=True,
    )
    registry.register(
        name="mac_clipboard_read",
        description="Read the current text contents of the Mac clipboard.",
        parameters={"type": "object", "properties": {}},
        handler=mac_clipboard_read,
        capabilities=["clipboard_read"],
        side_effect="read_only",
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
        capabilities=["clipboard_write"],
        side_effect="local_write",
    )
    registry.register(
        name="mac_system_info",
        description="Get Mac battery status, charging state, system uptime, and home disk space.",
        parameters={"type": "object", "properties": {}},
        handler=mac_system_info,
        capabilities=["mac_read"],
        side_effect="read_only",
    )
    registry.register(
        name="fs_search_files",
        description="Search for files by filename inside ~/Documents (or a subfolder like Apps).",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Filename keyword"},
                "subfolder": {"type": "string", "description": "Optional subfolder inside ~/Documents"},
            },
            "required": ["query"],
        },
        handler=fs_search_files,
        capabilities=["filesystem_read"],
        side_effect="read_only",
    )
    registry.register(
        name="fs_write_file",
        description="Create or overwrite a code/text file inside ~/Documents and optionally open it in VS Code.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to ~/Documents (e.g. Apps/test/sum.py) or absolute path inside ~/Documents"},
                "content": {"type": "string", "description": "Full file content to write"},
                "open_in_vscode": {"type": "boolean", "description": "Open the file in Visual Studio Code (default true)"},
            },
            "required": ["path", "content"],
        },
        handler=fs_write_file,
        capabilities=["filesystem_write"],
        side_effect="local_write",
    )
    registry.register(
        name="fs_read_file",
        description="Read a file inside ~/Documents.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to ~/Documents or absolute path inside ~/Documents"}
            },
            "required": ["path"],
        },
        handler=fs_read_file,
        capabilities=["filesystem_read"],
        side_effect="read_only",
    )
    registry.register(
        name="run_python_file",
        description="Execute a Python script inside ~/Documents and return its stdout/stderr.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the .py file inside ~/Documents"}
            },
            "required": ["path"],
        },
        handler=run_python_file,
        capabilities=["shell_exec"],
        side_effect="system_control",
        requires_approval=True,
    )
