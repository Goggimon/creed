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

    # LLM (Local Ollama)
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    jee_tutor_model: str = os.getenv("JEE_TUTOR_MODEL", "qwen3:8b")
    ollama_endpoint: str = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434/api/chat")
    ollama_timeout: float = float(os.getenv("OLLAMA_TIMEOUT", "60.0"))
    max_tool_iterations: int = int(os.getenv("CREED_MAX_TOOL_STEPS", "5"))

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
