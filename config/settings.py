import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from version import VERSION

BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env
load_dotenv(BASE_DIR / ".env")


@dataclass
class CreedConfig:
    assistant_name: str = os.getenv("ASSISTANT_NAME", "Creed")
    version: str = VERSION
    debug: bool = os.getenv("CREED_DEBUG", "true").lower() == "true"
    log_file: str = str(BASE_DIR / "logs" / "creed.log")
    data_file: str = str(BASE_DIR / "data.json")
    db_file: str = str(BASE_DIR / "creed.db")
    allow_in_memory_persistence: bool = (
        os.getenv("CREED_ALLOW_IN_MEMORY_PERSISTENCE", "false").lower() == "true"
    )
    plugins_dir: str = os.getenv("CREED_PLUGINS_DIR", str(BASE_DIR / "plugins"))
    trusted_plugins: str = os.getenv("CREED_TRUSTED_PLUGINS", "")

    # LLM (Local Ollama — Dual-Speed Routing)
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    fast_model: str = os.getenv("CREED_FAST_MODEL", "qwen2.5:3b")
    reasoning_model: str = os.getenv("CREED_REASONING_MODEL", "qwen3:8b")
    jee_tutor_model: str = os.getenv("JEE_TUTOR_MODEL", "qwen3:8b")
    ollama_endpoint: str = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434/api/chat")
    ollama_timeout: float = float(os.getenv("OLLAMA_TIMEOUT", "60.0"))
    max_tool_iterations: int = int(os.getenv("CREED_MAX_TOOL_STEPS", "5"))

    # LLM Routing & Privacy (Tranche 4.3)
    allow_cloud_escalation: bool = (
        os.getenv("CREED_ALLOW_CLOUD_ESCALATION", "false").lower() == "true"
    )
    cloud_privacy_mode: str = os.getenv("CREED_CLOUD_PRIVACY_MODE", "local_on_private")
    local_provider: str = os.getenv("CREED_LOCAL_PROVIDER", "ollama")
    cloud_provider: str = os.getenv("CREED_CLOUD_PROVIDER", "groq")
    cloud_model: str = os.getenv("CREED_CLOUD_MODEL", "llama-3.1-8b-instant")

    # Voice - Wake Word
    porcupine_access_key: str = os.getenv("PORCUPINE_ACCESS_KEY", "")
    wake_keyword: str = os.getenv(
        "CREED_WAKE_WORD",
        "computer" if os.getenv("PORCUPINE_ACCESS_KEY", "") else "creed",
    )

    # Voice - STT ("auto" prefers mlx_whisper on Apple Silicon, then faster_whisper)
    stt_backend: str = os.getenv("CREED_STT_BACKEND", "auto")
    stt_model_size: str = os.getenv("CREED_STT_MODEL", "tiny.en")

    # Voice - TTS ("auto" prefers piper if configured/installed, else macOS 'say')
    tts_backend: str = os.getenv("CREED_TTS_BACKEND", "auto")
    piper_path: str = os.getenv("PIPER_PATH", "")
    piper_model_path: str = os.getenv("PIPER_MODEL_PATH", "")
    macos_tts_voice: str = os.getenv("CREED_MACOS_VOICE", "Samantha")
    macos_tts_rate: int = int(os.getenv("CREED_TTS_RATE", "190"))

    # Multi-system Device Targets & Integrated Apps
    phone_adb_target: str = os.getenv("CREED_PHONE_ADB_TARGET", "")
    vspotify_dir: str = os.getenv(
        "VSPOTIFY_DIR", str(BASE_DIR.parent / "VSpotify")
    )


config = CreedConfig()
