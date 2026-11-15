# modules/tts.py

import asyncio
import logging
import shutil
import sys
from pathlib import Path
import numpy as np
import sounddevice as sd
from config.settings import config
from core.event_bus import event_bus

logger = logging.getLogger("CreedTTS")


class TTSModule:
    def __init__(self):
        self.sample_rate = 22050
        self.piper_path = self._resolve_piper_path()
        self.model_path = self._resolve_model_path()
        self.backend = self._select_backend()

        self.queue = asyncio.Queue()
        self._interrupted = False
        self._is_playing = False
        self._current_process = None
        self._worker_task = None

        logger.info(f"TTS initialized using backend='{self.backend}'")

    def _resolve_piper_path(self) -> str:
        if config.piper_path and Path(config.piper_path).exists():
            return config.piper_path
        found = shutil.which("piper")
        return found or ""

    def _resolve_model_path(self) -> str:
        if config.piper_model_path and Path(config.piper_model_path).exists():
            return config.piper_model_path
        default_local = (
            Path(__file__).resolve().parent.parent
            / "models"
            / "en_US-ryan-medium.onnx"
        )
        if default_local.exists():
            return str(default_local)
        return ""

    def _select_backend(self) -> str:
        preferred = config.tts_backend.lower()
        if preferred == "piper" or (
            preferred == "auto" and self.piper_path and self.model_path
        ):
            if self.piper_path and self.model_path:
                return "piper"
            logger.warning(
                "Piper backend requested but PIPER_PATH or PIPER_MODEL_PATH missing."
            )

        if sys.platform == "darwin" and shutil.which("say"):
            return "macos_say"

        return "none"

    def is_speaking(self) -> bool:
        return (
            self._is_playing
            or self._current_process is not None
            or not self.queue.empty()
        )

    def start_worker(self, loop):
        if self._worker_task is None:
            self._worker_task = loop.create_task(self._worker_loop())
            logger.info("TTS worker task started")

    def speak(self, text: str):
        clean_text = (
            text.replace("*", "")
            .replace(":", ".")
            .replace("#", "")
            .strip()
        )
        if not clean_text or self.backend == "none":
            return

        self._interrupted = False
        self.queue.put_nowait(clean_text)
        logger.debug(f"Queued text for TTS ({self.backend}): '{clean_text}'")

    def stop(self):
        self._interrupted = True
        self._is_playing = False

        while not self.queue.empty():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except asyncio.QueueEmpty:
                break

        try:
            sd.stop()
        except Exception as e:
            logger.error(f"Error stopping sounddevice: {e}")

        if self._current_process:
            try:
                self._current_process.terminate()
            except Exception as e:
                logger.error(f"Error terminating TTS process: {e}")
            self._current_process = None

    async def _speak_piper(self, text: str):
        self._current_process = await asyncio.create_subprocess_exec(
            self.piper_path,
            "-m",
            self.model_path,
            "--output-raw",
            "--quiet",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        try:
            stdout_data, _ = await self._current_process.communicate(
                input=(text + "\n").encode("utf-8")
            )
        except asyncio.CancelledError:
            if self._current_process:
                self._current_process.terminate()
            raise
        finally:
            self._current_process = None

        if stdout_data and not self._interrupted:
            audio_np = np.frombuffer(stdout_data, dtype=np.int16)
            sd.play(audio_np, self.sample_rate)

            total_time = len(audio_np) / self.sample_rate
            elapsed = 0.0
            chunk_time = 0.05
            while elapsed < total_time and not self._interrupted:
                await asyncio.sleep(chunk_time)
                elapsed += chunk_time

            if self._interrupted:
                sd.stop()

    async def _speak_macos_say(self, text: str):
        self._current_process = await asyncio.create_subprocess_exec(
            "say",
            "-v",
            config.macos_tts_voice,
            "-r",
            str(config.macos_tts_rate),
            text,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await self._current_process.wait()
        except asyncio.CancelledError:
            if self._current_process:
                self._current_process.terminate()
            raise
        finally:
            self._current_process = None

    async def _worker_loop(self):
        while True:
            text = await self.queue.get()
            if self._interrupted:
                self.queue.task_done()
                continue

            self._is_playing = True
            logger.info(f"Synthesizing speech ({self.backend}): '{text}'")

            try:
                await event_bus.publish("status_change", "Speaking")

                if self.backend == "piper":
                    await self._speak_piper(text)
                elif self.backend == "macos_say":
                    await self._speak_macos_say(text)

            except Exception as e:
                logger.error(f"TTS execution failed: {e}")
                await event_bus.publish("error", f"TTS error: {str(e)}")
            finally:
                self._is_playing = False
                self.queue.task_done()

            if self.queue.empty() and not self._interrupted:
                await event_bus.publish("status_change", "Idle")
