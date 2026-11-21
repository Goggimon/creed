# core/voice/stt.py

import asyncio
import importlib.util
import logging
import platform
import queue
import sys
import threading
import time
import numpy as np
import sounddevice as sd
from config.settings import config
from monitoring.latency_tracker import latency_tracker

logger = logging.getLogger("CreedSTT")


class STTEngine:
    def __init__(
        self,
        event_bus,
        model_size: str = None,
        energy_threshold: float = 0.015,
        silence_limit: float = 0.85,
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
        self.audio_queue: queue.Queue = queue.Queue(maxsize=128)
        self._model_lock = threading.Lock()

        # Barge-in monitoring state during TTS playback
        self._barge_in_active = False
        self._barge_in_thread = None
        self._utterance_seq = 0
        self._latest_partial_seq = 0

        self._load_thread = threading.Thread(target=self._load_model, daemon=True)
        self._load_thread.start()

    @staticmethod
    def is_likely_barge_in(
        rms: float,
        energy_threshold: float,
        consecutive_hits: int,
        elapsed_since_playback_s: float,
        cooldown_s: float = 0.35,
        min_hits: int = 4,
    ) -> tuple[bool, int]:
        """Software echo-guard: require cooldown after TTS start and sustained speech (>=4 blocks ~256ms)."""
        if elapsed_since_playback_s < cooldown_s:
            return False, 0
        if rms > energy_threshold * 1.85:
            new_hits = consecutive_hits + 1
            return new_hits >= min_hits, new_hits
        return False, 0

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
        self.stop_barge_in_monitor()
        self._loop = loop
        self.recording = True
        self._utterance_seq += 1
        self._latest_partial_seq = 0
        self.audio_queue = queue.Queue(maxsize=128)

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

    def start_barge_in_monitor(self, loop):
        """Lightweight VAD monitor running during TTS playback to detect user interruption (<150ms)."""
        if self._barge_in_active or self.recording:
            return
        self._loop = loop
        self._barge_in_active = True
        self._barge_in_thread = threading.Thread(target=self._barge_in_loop, daemon=True)
        self._barge_in_thread.start()

    def stop_barge_in_monitor(self):
        self._barge_in_active = False

    def _barge_in_loop(self):
        barge_q: queue.Queue = queue.Queue(maxsize=32)

        def cb(indata, frames, t, status):
            if self._barge_in_active and not barge_q.full():
                barge_q.put_nowait(indata.copy())

        consecutive_hits = 0
        t_monitor_start = time.monotonic()
        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                blocksize=self.block_size,
                dtype="float32",
                callback=cb,
            ):
                while self._barge_in_active:
                    try:
                        block = barge_q.get(timeout=0.08)
                    except queue.Empty:
                        continue
                    rms = float(np.sqrt(np.mean(block ** 2)))
                    elapsed = time.monotonic() - t_monitor_start
                    triggered, consecutive_hits = self.is_likely_barge_in(
                        rms, self.energy_threshold, consecutive_hits, elapsed
                    )
                    if triggered:
                        t_hit = time.monotonic()
                        logger.info("[STT] Barge-in speech detected during playback!")
                        self._barge_in_active = False
                        self._publish("barge_in_detected", t_hit)
                        break
        except Exception as e:
            logger.debug(f"[STT] Barge-in monitor exited: {e}")
        finally:
            self._barge_in_active = False

    def _audio_callback(self, indata, frames, t, status):
        if status:
            logger.warning(f"[STT] sounddevice status: {status}")
        if self.audio_queue.full():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                pass
        self.audio_queue.put_nowait(indata.copy())

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
        max_silence_blocks = max(4, int(self.silence_limit / block_duration))
        partial_interval_blocks = max(6, int(0.75 / block_duration))
        blocks_since_partial = 0
        dispatched_transcription = False
        level_tick = 0
        t_capture_start = time.monotonic()

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
                    vad_ms = (time.monotonic() - t_capture_start) * 1000.0
                    latency_tracker.record("vad_ms", min(vad_ms, 5000.0))
                    logger.info("[STT] Speech energy threshold crossed - recording")
                    speech_started = True
                    self._publish("status_change", "Recording")
                audio_buffer.append(block)
                silence_blocks = 0
                blocks_since_partial += 1

                # Incremental partial transcription for speculative execution
                if blocks_since_partial >= partial_interval_blocks and self.model is not None:
                    blocks_since_partial = 0
                    self._latest_partial_seq += 1
                    p_seq = self._latest_partial_seq
                    u_seq = self._utterance_seq
                    snapshot = np.concatenate(audio_buffer, axis=0)
                    threading.Thread(
                        target=self._emit_partial,
                        args=(snapshot, u_seq, p_seq),
                        daemon=True,
                    ).start()
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
                    max_pre_speech = int(0.45 / block_duration)
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

    def _emit_partial(self, audio_data: np.ndarray, u_seq: int = 0, p_seq: int = 0):
        t0 = time.monotonic()
        try:
            text = self.transcribe_audio(audio_data, beam_size=1)
            if u_seq != self._utterance_seq or p_seq < self._latest_partial_seq:
                return
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            latency_tracker.record("stt_partial_ms", elapsed_ms)
            if text:
                self._publish("partial_transcript", text)
        except Exception:
            pass

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
        t0 = time.monotonic()

        try:
            transcription = self.transcribe_audio(audio_data, beam_size=3)
            latency_tracker.record("stt_final_ms", (time.monotonic() - t0) * 1000.0)
            logger.info(f"[STT] Completed transcription: '{transcription}'")

            if transcription:
                self._publish("speech_transcribed", transcription)
            else:
                self._publish("status_change", "Idle")
        except Exception as e:
            logger.error(f"[STT] Transcription failed: {e}")
            self._publish("error", f"STT failed: {e}")
            self._publish("status_change", "Idle")
