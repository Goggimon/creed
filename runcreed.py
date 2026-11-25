
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
BACKEND_URL = "http://127.0.0.1:8000/"


def wait_for_backend(url: str = BACKEND_URL, timeout_s: float = 15.0, poll_s: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status < 500:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(poll_s)
    return False


def terminate_process_tree(proc: subprocess.Popen | None, timeout_s: float = 3.0) -> None:
    if proc is None or proc.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except OSError:
            proc.terminate()
    else:
        proc.terminate()
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                proc.kill()
        else:
            proc.kill()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass


def launch_creed() -> int:
    python_exe = sys.executable
    popen_kwargs: dict = {"cwd": str(BASE_DIR)}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True

    backend = subprocess.Popen(
        [python_exe, "-m", "uvicorn", "api.server:app", "--host", "127.0.0.1", "--port", "8000"],
        **popen_kwargs,
    )
    gui = None

    def _handle_signal(signum, _frame):
        terminate_process_tree(gui)
        terminate_process_tree(backend)
        raise SystemExit(128 + signum)

    prev_sigint = signal.getsignal(signal.SIGINT)
    prev_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        if not wait_for_backend(BACKEND_URL, timeout_s=15.0):
            print("CREED backend failed to become ready on http://127.0.0.1:8000/", file=sys.stderr)
            return 1
        gui = subprocess.Popen([python_exe, str(BASE_DIR / "gui" / "app.py")], cwd=str(BASE_DIR))
        return int(gui.wait())
    finally:
        signal.signal(signal.SIGINT, prev_sigint)
        signal.signal(signal.SIGTERM, prev_sigterm)
        terminate_process_tree(gui)
        terminate_process_tree(backend)


if __name__ == "__main__":
    raise SystemExit(launch_creed())
