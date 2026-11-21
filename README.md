# CREED v3.5.0

**CREED** is a local-first, multi-system AI hub built for macOS (Apple Silicon) with a PySide6 studio interface, FastAPI + WebSocket backend, local Ollama tool-calling & model management, embedded **VSpotify** visualizer player, **JEE Tutor** mode, offline Whisper STT/wake-word, macOS/Piper TTS, and SQLite persistence.

---

## Core Capabilities

* **Local LLM Registry & Tool-Calling Brain**:
  * **AI Models Tab** (`gui/components/tabs.py`): Inspect installed Ollama models, switch active models via dropdown or one-click table actions, and pull new weights directly from the UI.
  * **Multi-Step Tool Loop** (`core/engine.py`, `core/tools.py`): Powered by Ollama (`qwen2.5-coder:7b` / `qwen3:8b` on 16 GB Apple Silicon) with `keep_alive: 15m` and `num_ctx: 4096` for fast local responses.
  * **Privacy-First Local / Cloud Routing** (`intelligence/model_router.py`, `modules/base_ai.py`): Keeps `CREED_ALLOW_CLOUD_ESCALATION=false` and `CREED_CLOUD_PRIVACY_MODE=local_on_private` by default, blocks private context (retrieved memories, ongoing work, local files, personal notes, prior conversation history) from reaching cloud providers without explicit per-turn permission, checks provider tool-calling compatibility, and supports pre-stream local fallback.
* **Embedded VSpotify Hub** (`modules/vspotify.py`, `gui/components/vspotify_tab.py`):
  * Embeds `https://goggimon.github.io/VSpotify/` inside CREED.
  * Voice and AI tools (`vspotify_playback`, `vspotify_set_visualizer`, `vspotify_set_hud`, `vspotify_customize`, `vspotify_open_tab`) control playback, visualizers, HUD layouts, EQ bands, and theme colors in real time.
* **JEE Tutor Mode** (`modules/jee_tutor.py`, `gui/components/jee_tab.py`):
  * **Auto-Reasoning Model + Pre-Loaded Formula/Trap RAG**: Automatically switches to `JEE_TUTOR_MODEL` (default `qwen3:8b`) and injects verified Physics/Chemistry/Maths formulas, sign conventions, and 5-year PYQ patterns into every prompt.
  * **Live SVG Diagrams & LaTeX Math**: Renders formatted LaTeX equations, AI-generated SVG diagrams, and 0ms pre-loaded SVG templates (`Incline FBD`, `Convex Lens Ray`, `Wheatstone Bridge`, `Carnot PV`, `YDSE`, `Zener Diode`).
  * **SQLite Flashcards, Custom Tests & 5-Yr PYQ Vault**: Flip/master custom flashcards, generate timed JEE Main/Advanced MCQ tests with live progress, and browse 2022–2026 chapter weightage & high-ROI patterns.
* **Multi-System Control**:
  * **macOS Host** (`modules/mac_control.py`): Launch/close apps (`open -a`, `pkill`), open browser URLs, list running apps, read/write clipboard (`pbpaste`/`pbcopy`), search/read/write/run Python scripts inside `~/Documents` (`fs_search_files`, `fs_write_file`, `fs_read_file`, `run_python_file`), and inspect battery/uptime/disk (`pmset`/`uptime`/`df`) with zero `osascript` prompts.
  * **Bluetooth & Audio** (`modules/bt_audio.py`): Native macOS `IOBluetooth` & `system_profiler` device management.
  * **Android Phone** (`modules/phone_adb.py`): Wireless ADB device status, app launching, media keys, and `scrcpy` screen mirroring.
* **Studio Interface & Offline Voice Pipeline**:
  * **Overview Hub** (`gui/components/radial_hub.py`): 60 FPS native `QPainter` 3D-projected neural sphere with dynamic state colors and spring-eased navigation cards.
  * **Voice**: Offline Whisper wake-word (`"creed"`) or optional Porcupine, `mlx_whisper`/`faster-whisper` STT, and macOS `say` / Piper TTS.

---

## Quick Setup (macOS)

1. **Create a virtual environment and install dependencies:**
   ```bash
   uv venv --python 3.12 .venv
   source .venv/bin/activate
   uv pip install -r requirements.txt
   ```

2. **Pull your Ollama models:**
   ```bash
   ollama pull qwen2.5-coder:7b
   ollama pull qwen2.5:14b   # Used automatically in JEE Tutor mode
   ```

3. **Configure `.env`:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` as needed. Never commit `.env`, `creed.db`, `data.json`, `logs/`, or `CREED.app/`.

4. **Run CREED:**
   * Backend: `.venv/bin/uvicorn api.server:app --host 127.0.0.1 --port 8000`
   * GUI: `.venv/bin/python gui/app.py` (or open `CREED.app`)
