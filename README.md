# CREED v2.0.0

**CREED** is a local-first, multi-system AI agent built for macOS (Apple Silicon) with a cybernetic PySide6 command interface, FastAPI + WebSocket backend, local Ollama tool-calling, offline Whisper speech recognition & wake-word detection, macOS/Piper TTS, and SQLite persistence.

---

## Core Capabilities

* **Local Tool-Calling Brain**: Powered by Ollama (`qwen2.5:7b` recommended on 16 GB Apple Silicon) with a multi-step `ToolRegistry` loop.
* **Multi-System Control**:
  * **macOS Host** (`modules/mac_control.py`): Launch apps, adjust/mute volume, read/write clipboard, check battery/uptime, and send native notifications.
  * **Bluetooth & Audio** (`modules/bt_audio.py`): Native macOS `IOBluetooth` & `system_profiler` device management and audio output inspection.
  * **Android Phone** (`modules/phone_adb.py`): Wireless ADB device status, app launching, media keys, and `scrcpy` screen mirroring.
* **Holographic Cybernetic Interface** (`gui/`):
  * **Overview Hub**: Animated central CREED nucleus with a 64-bar radial visualizer, 3D-projected orbital projectiles, neural pathway pulses, and 7 interactive subsystem nodes.
  * **Multi-Chat & SQLite Memory**: Switch between saved conversations, search/add/delete persistent notes, and schedule background reminders.
  * **Custom Workflows**: Create and run multi-step tool automations from the **Automation** tab or via voice/chat (`run_workflow`).
* **Offline Voice Pipeline**:
  * **Wake Word**: Offline, zero-key energy-gated Whisper detection (`"creed"`) or optional Picovoice Porcupine.
  * **STT**: `mlx_whisper` (Apple Silicon Metal) or `faster-whisper` (`float32` on Apple Silicon).
  * **TTS**: Native macOS `say` (configurable voice & WPM rate) or local Piper ONNX models.

---

## Quick Setup (macOS)

1. **Create a virtual environment and install dependencies:**
   ```bash
   uv venv --python 3.12 .venv
   source .venv/bin/activate
   uv pip install -r requirements.txt
   ```

2. **Pull the local Ollama model:**
   ```bash
   ollama pull qwen2.5:7b
   ```

3. **Configure `.env`:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` as needed (`OLLAMA_MODEL`, `CREED_MACOS_VOICE`, `CREED_TTS_RATE`, `CREED_PHONE_ADB_TARGET`). Never commit `.env`, `creed.db`, or `logs/`.

4. **Run CREED:**
   * Backend: `.venv/bin/uvicorn api.server:app --host 127.0.0.1 --port 8000`
   * GUI: `.venv/bin/python gui/app.py` (or open `CREED.app`)
