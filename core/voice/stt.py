# core/voice/stt.py

import asyncio
import importlib.util
import logging
import platform
import queue
import sys
import threading
import numpy as np
import sounddevice as sd
from config.settings import config

logger = logging.getLogger("CreedSTT")


class STTEngine:
    def __init__(
        self,
        event_bus,
        model_size: str = None,
        energy_threshold: float = 0.015,
        silence_limit: float = 1.5,
    ):
        self.event_bus = event_bus
        self.model_size = model_size or config.stt_model_size
        self.energy_threshold = energy_threshold
        self.silence_limit = silence_limit
        self.sample_rate = 16000
        self.block_size = 1024

        self.backend = None  # "mlx" or "faster_whisper"
        self.model = None
        self.recording = False
        self.stream = None
        self._loop = None
        self._capture_thread = None
        self.audio_queue = queue.Queue()
        self._model_lock = threading.Lock()

        self._load_thread = threading.Thread(target=self._load_model, daemon=True)
        self._load_thread.start()

    def _is_apple_silicon(self) -> bool:
        return sys.platform == "darwin" and platform.machine() == "arm64"

    def _load_model(self):
        preferred = config.stt_backend.lower()

        if preferred in ("auto", "mlx") and self._is_apple_silicon():
            if importlib.util.find_spec("mlx_whisper") is not None:
                try:
                    import mlx_whisper

                    self.model = mlx_whisper
                    self.backend = "mlx"
                    logger.info(
                        f"[STT] Using mlx_whisper (Apple Silicon Metal) with model '{self.model_size}'."
                    )
                    return
                except Exception as e:
                    logger.warning(f"[STT] mlx_whisper init failed, falling back: {e}")

        try:
            from faster_whisper import WhisperModel

            compute_type = "float32" if self._is_apple_silicon() else "int8"
            logger.info(
                f"[STT] Loading faster-whisper '{self.model_size}' on CPU ({compute_type})..."
            )
            self.model = WhisperModel(
                self.model_size, device="cpu", compute_type=compute_type
            )
            self.backend = "faster_whisper"
            logger.info("[STT] faster-whisper model loaded successfully.")
        except Exception as e:
            logger.error(f"[STT] Failed to load STT model: {e}")

    def _publish(self, event: str, *args):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.event_bus.publish(event, *args), self._loop
            )

    def start_listening(self, loop):
        if self.recording:
            return
        self._loop = loop
        self.recording = True
        self.audio_queue = queue.Queue()

        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

    def stop_listening(self):
        was_recording = self.recording
        self.recording = False
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception as e:
                logger.error(f"[STT] Error closing stream: {e}")
            self.stream = None
        if was_recording:
            self._publish("status_change", "Idle")

    def _audio_callback(self, indata, frames, time, status):
        if status:
            logger.warning(f"[STT] sounddevice status: {status}")
        self.audio_queue.put(indata.copy())

    def _capture_loop(self):
        try:
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                blocksize=self.block_size,
                dtype="float32",
                callback=self._audio_callback,
            )
            self.stream.start()
        except Exception as e:
            logger.error(f"[STT] Failed to open audio input stream: {e}")
            self.recording = False
            self._publish("error", f"Microphone init failed: {e}")
            self._publish("status_change", "Idle")
            return

        logger.info("[STT] Microphone capturing started...")

        speech_started = False
        audio_buffer = []
        silence_blocks = 0
        block_duration = self.block_size / self.sample_rate
        max_silence_blocks = int(self.silence_limit / block_duration)
        dispatched_transcription = False
        level_tick = 0

        while self.recording:
            try:
                block = self.audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            rms = float(np.sqrt(np.mean(block ** 2)))
            level_tick += 1
            if level_tick % 2 == 0:
                self._publish("voice_level", min(1.0, rms * 12.0))

            if rms > self.energy_threshold:
                if not speech_started:
                    logger.info("[STT] Speech energy threshold crossed - recording")
                    speech_started = True
                    self._publish("status_change", "Recording")
                audio_buffer.append(block)
                silence_blocks = 0
            else:
                if speech_started:
                    audio_buffer.append(block)
                    silence_blocks += 1
                    if silence_blocks > max_silence_blocks:
                        logger.info("[STT] Silence limit crossed - speech ended")
                        speech_started = False
                        self.recording = False
                        dispatched_transcription = True

                        full_audio = np.concatenate(audio_buffer, axis=0)
                        threading.Thread(
                            target=self._transcribe_and_publish,
                            args=(full_audio,),
                            daemon=True,
                        ).start()
                        break
                else:
                    audio_buffer.append(block)
                    max_pre_speech = int(0.5 / block_duration)
                    if len(audio_buffer) > max_pre_speech:
                        audio_buffer.pop(0)

        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

        if not dispatched_transcription:
            self._publish("status_change", "Idle")

    def transcribe_audio(self, audio_data: np.ndarray, beam_size: int = 5) -> str:
        if self.model is None:
            return ""
        audio_flat = audio_data.flatten().astype(np.float32)
        with self._model_lock:
            if self.backend == "mlx":
                repo_id = f"mlx-community/whisper-{self.model_size}-mlx"
                result = self.model.transcribe(audio_flat, path_or_hf_repo=repo_id)
                return result.get("text", "").strip()
            segments, _ = self.model.transcribe(audio_flat, beam_size=beam_size)
            return "".join(segment.text for segment in segments).strip()

    def _transcribe_and_publish(self, audio_data):
        if self.model is None:
            logger.warning("[STT] Transcription requested but model is not loaded yet")
            self._publish("error", "Speech model still loading")
            self._publish("status_change", "Idle")
            return

        self._publish("status_change", "Processing")

        try:
            transcription = self.transcribe_audio(audio_data, beam_size=5)
            logger.info(f"[STT] Completed transcription: '{transcription}'")

            if transcription:
                self._publish("speech_transcribed", transcription)
            else:
                self._publish("status_change", "Idle")
        except Exception as e:
            logger.error(f"[STT] Transcription failed: {e}")
            self._publish("error", f"STT failed: {e}")
            self._publish("status_change", "Idle")
