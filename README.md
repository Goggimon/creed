# CREED v3.5.0

**CREED** is a local-first, multi-system AI hub built for macOS (Apple Silicon) with a PySide6 Spatial OS interface, FastAPI + WebSocket backend, local Ollama tool-calling & model management, privacy-first local/cloud model routing, persistent task orchestration, offline Whisper STT/wake-word, macOS/Piper TTS, and SQLite persistence.

## Core Capabilities

* **Privacy-First Local / Cloud Routing** (`intelligence/model_router.py`, `modules/base_ai.py`, `core/engine.py`):
  * Keeps `CREED_ALLOW_CLOUD_ESCALATION=false` and `CREED_CLOUD_PRIVACY_MODE=local_on_private` by default.
  * Blocks private context (retrieved memories, ongoing work, local files, personal notes, prior conversation history) from reaching cloud providers without explicit per-turn permission.
  * Checks provider tool-calling compatibility and supports pre-stream local fallback without duplicating side effects.
* **Local LLM Registry & Tool-Calling Brain**:
  * **Models Tab** (`gui/components/tabs.py`): Inspect installed Ollama models, switch active models, and pull/delete weights directly from the UI.
  * **Multi-Step Tool Loop** (`core/engine.py`, `core/tools.py`): Powered by Ollama (`qwen2.5-coder:7b` / `qwen3:8b` on Apple Silicon) with `keep_alive: 15m` and `num_ctx: 4096`.
* **Persistent Task Orchestration & Approvals** (`core/tasks.py`, `core/policy.py`, `gui/components/tasks_tab.py`):
  * SQLite-backed task lifecycle (`queued`, `running`, `paused`, `waiting_for_approval`, `uncertain`, `completed`, `failed`, `cancelled`) with checkpoint timelines, saved workflows, and hash-bound approval gates.
* **Multi-System Control**:
  * **macOS Host** (`modules/mac_control.py`): Launch/close apps (`open -a`, `pkill`), open browser URLs, list running apps, read/write clipboard (`pbpaste`/`pbcopy`), search/read/write/run Python scripts inside `~/Documents`, and inspect battery/uptime/disk (`pmset`/`uptime`/`df`).
  * **Bluetooth & Audio** (`modules/bt_audio.py`): Native macOS `IOBluetooth` & `system_profiler` device management.
  * **Android Phone** (`modules/phone_adb.py`): Wireless ADB device status, app launching, media keys, and `scrcpy` screen mirroring.
* **Spatial OS Interface & Offline Voice Pipeline**:
  * **8-Tab Spatial Workspace** (`gui/main_window.py`, `gui/components/radial_hub.py`): `00 HUB`, `01 INTELLIGENCE`, `02 MEMORY`, `03 TASKS`, `04 MACHINE`, `05 TOOLS`, `06 MODELS`, and `07 CONFIG`, plus `⌘K` Command Palette. *(VSpotify and JEE Tutor GUI tabs are currently disabled while core routing and orchestration are stabilized.)*
  * **Voice**: Offline Whisper wake-word (`"creed"`) or optional Porcupine, `mlx_whisper`/`faster-whisper` STT, and macOS `say` / Piper TTS.

## Quick Setup (macOS)

1. **Install dependencies with `uv`:**
   ```bash
   uv sync
   # Optional dev tools (ruff, mypy, pytest):
   uv sync --extra dev
   ```

2. **Pull your Ollama model(s):**
   ```bash
   ollama pull qwen2.5-coder:7b
   ```

3. **Configure `.env`:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` as needed. Never commit `.env`, `creed.db`, `data.json`, `logs/`, or `CREED.app/`.

4. **Run CREED:**
   * **Backend:** `.venv/bin/uvicorn api.server:app --host 127.0.0.1 --port 8000`
   * **Desktop GUI:** `.venv/bin/python gui/app.py`
   * **CLI mode:** `.venv/bin/python main.py`

## Testing & Benchmarking

* **Run the full test suite:**
  ```bash
  .venv/bin/python -m unittest discover -s tests -v
  ```
* **Lint & type check:**
  ```bash
  .venv/bin/ruff check intelligence monitoring config utils tests
  .venv/bin/mypy intelligence monitoring config
  ```
* **Latency & voice benchmarking:** See [docs/BENCHMARK_VOICE.md](docs/BENCHMARK_VOICE.md) and inspect live `p50`/`p95`/`p99` and routing telemetry at `GET /api/metrics`.
