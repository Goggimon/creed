# core/voice/wake.py

import asyncio
import logging
import queue
import threading
import numpy as np
import sounddevice as sd

try:
    import pvporcupine
except ImportError:
    pvporcupine = None

logger = logging.getLogger("CreedWake")


class WakeWordDetector:
    """
    Dual-mode Wake Word detector:
    - Uses Picovoice Porcupine if PORCUPINE_ACCESS_KEY is provided.
    - Otherwise uses 100% local, zero-key energy-gated Whisper detection via STTEngine.
    """

    def __init__(
        self,
        access_key: str = "",
        keyword: str = "creed",
        event_bus=None,
        stt_engine=None,
        energy_threshold: float = 0.018,
    ):
        self.access_key = access_key
        self.keyword = keyword.lower().strip()
        self.event_bus = event_bus
        self.stt_engine = stt_engine
        self.energy_threshold = energy_threshold

        self._running = False
        self._thread = None
        self._loop = None
        self.porcupine = None
        self.mode = "disabled"
        self.sample_rate = 16000
        self.frame_length = 512

        if pvporcupine is not None and self.access_key:
            try:
                self.porcupine = pvporcupine.create(
                    access_key=self.access_key, keywords=[self.keyword]
                )
                self.sample_rate = self.porcupine.sample_rate
                self.frame_length = self.porcupine.frame_length
                self.mode = "porcupine"
                logger.info(f"Porcupine Wake Word initialized (keyword='{self.keyword}').")
                return
            except Exception as e:
                logger.warning(f"[WakeWord] Porcupine init failed, falling back to local Whisper: {e}")
                self.porcupine = None

        if self.stt_engine is not None:
            self.mode = "local_whisper"
            self.sample_rate = 16000
            self.frame_length = 1024
            logger.info(f"[WakeWord] Local offline Whisper wake word ready (keyword='{self.keyword}').")
        else:
            logger.warning("[WakeWord] Neither Porcupine key nor STTEngine available. Wake word disabled.")

    def set_loop(self, loop):
        self._loop = loop

    def on_detect(self):
        """Override this method or assign externally."""
        pass

    def _emit_error(self, message: str):
        if self.event_bus and self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.event_bus.publish("error", message), self._loop
            )

    def _porcupine_callback(self, indata, frames, time, status):
        if not self._running or not self.porcupine:
            return
        try:
            pcm = (indata[:, 0] * 32767).astype(np.int16)
            if self.porcupine.process(pcm) >= 0:
                logger.info(f"Wake word '{self.keyword}' detected!")
                self.on_detect()
        except Exception as e:
            logger.error(f"[WakeWord] Porcupine callback error: {e}")

    def _run_porcupine(self):
        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                blocksize=self.frame_length,
                dtype="float32",
                callback=self._porcupine_callback,
            ):
                while self._running:
                    sd.sleep(100)
        except Exception as e:
            logger.error(f"[WakeWord] InputStream error: {e}")
            self._running = False
            self._emit_error(f"Wake word audio stream failed: {e}")

    def _run_local_whisper(self):
        audio_q = queue.Queue()

        def cb(indata, frames, time, status):
            if self._running:
                audio_q.put(indata.copy())

        block_sec = self.frame_length / self.sample_rate
        max_pre_blocks = int(0.4 / block_sec)
        max_utterance_blocks = int(1.8 / block_sec)
        silence_blocks_limit = int(0.45 / block_sec)

        pre_buffer = []
        speech_buffer = []
        capturing = False
        silence_count = 0

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                blocksize=self.frame_length,
                dtype="float32",
                callback=cb,
            ):
                while self._running:
                    try:
                        block = audio_q.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    rms = float(np.sqrt(np.mean(block ** 2)))
                    if rms > self.energy_threshold:
                        if not capturing:
                            capturing = True
                            speech_buffer = list(pre_buffer)
                        speech_buffer.append(block)
                        silence_count = 0
                    elif capturing:
                        speech_buffer.append(block)
                        silence_count += 1
                        if silence_count >= silence_blocks_limit or len(speech_buffer) >= max_utterance_blocks:
                            clip = np.concatenate(speech_buffer, axis=0)
                            capturing = False
                            speech_buffer = []
                            silence_count = 0

                            if self.stt_engine.model is not None:
                                text = self.stt_engine.transcribe_audio(clip, beam_size=1).lower()
                                if text:
                                    logger.debug(f"[WakeWord] Heard: '{text}'")
                                if self.keyword in text:
                                    logger.info(f"[WakeWord] Local wake word '{self.keyword}' detected!")
                                    self._running = False
                                    self.on_detect()
                                    break
                    else:
                        pre_buffer.append(block)
                        if len(pre_buffer) > max_pre_blocks:
                            pre_buffer.pop(0)
        except Exception as e:
            logger.error(f"[WakeWord] Local Whisper InputStream error: {e}")
            self._running = False
            self._emit_error(f"Wake word audio stream failed: {e}")

    def start(self):
        if self._running or self.mode == "disabled":
            return

        self._running = True
        target = self._run_porcupine if self.mode == "porcupine" else self._run_local_whisper
        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread and self._thread is not threading.current_thread():
            try:
                self._thread.join(timeout=1.0)
            except Exception:
                pass
        self._thread = None

    def close(self):
        self.stop()
        if self.porcupine:
            try:
                self.porcupine.delete()
            except Exception:
                pass
            self.porcupine = None
