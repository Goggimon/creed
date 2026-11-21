# monitoring/latency_tracker.py

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 1)
    idx = (len(sorted_vals) - 1) * (pct / 100.0)
    lo = int(math.floor(idx))
    hi = min(len(sorted_vals) - 1, lo + 1)
    frac = idx - lo
    return round(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac, 1)


@dataclass
class TurnTrace:
    turn_id: str
    path: str = "instant"
    model: str = ""
    provider: str = ""
    tier: str = "local"
    routing_reason: str = "local_default"
    privacy_classification: str = "public"
    fallback_occurred: bool = False
    tts_backend: str = ""
    tts_metric_type: str = ""
    t_origin: float = 0.0
    t_speech_start: float = 0.0
    t_stt_done: float = 0.0
    stt_ms: float = 0.0
    classifier_ms: float = 0.0
    t_classified_start: float = 0.0
    t_classified_end: float = 0.0
    t_memory_start: float = 0.0
    t_memory_end: float = 0.0
    t_llm_start: float = 0.0
    t_first_token: float = 0.0
    t_tts_queued: float = 0.0
    t_tts_dispatch: float = 0.0
    t_tts_first_audio: float = 0.0
    t_done: float = 0.0
    token_count: int = 0
    interrupted: bool = False
    error: bool = False


class LatencyTracker:
    """Thread-safe observability tracker computing p50, p95, p99 and per-turn overlapping timelines."""

    STAGES = (
        "vad_ms",
        "stt_partial_ms",
        "stt_final_ms",
        "classifier_ms",
        "memory_retrieval_ms",
        "llm_ttft_ms",
        "llm_tok_s",
        "tts_dispatch_ms",
        "tts_output_submit_ms",
        "e2e_dispatch_ms",
        "e2e_output_submit_ms",
        "total_duration_ms",
        "barge_in_ms",
    )

    STAGE_SEMANTICS = {
        "tts_dispatch_ms": {
            "backend": "macos_say",
            "metric_type": "process_launch",
            "description": "Queue-to-subprocess launch latency (macos_say); does NOT measure audio synthesis or audible sound.",
        },
        "tts_output_submit_ms": {
            "backend": "piper",
            "metric_type": "audio_output_submission",
            "description": "Queue-to-output-buffer submission latency (piper sd.play handoff); does NOT measure acoustic device output.",
        },
        "e2e_dispatch_ms": {
            "backend": "macos_say",
            "metric_type": "process_launch",
            "description": "STT-done (or LLM-start) to TTS subprocess dispatch; excludes OS audio synthesis/buffering.",
        },
        "e2e_output_submit_ms": {
            "backend": "piper",
            "metric_type": "audio_output_submission",
            "description": "STT-done (or LLM-start) to audio output buffer submission; excludes CoreAudio/speaker acoustic delay.",
        },
    }

    def __init__(self, window: int = 200):
        self._lock = threading.Lock()
        self._samples: dict[str, deque[float]] = {
            k: deque(maxlen=window) for k in self.STAGES
        }
        self._traces: dict[str, TurnTrace] = {}
        self._recent_turns: deque[dict] = deque(maxlen=25)
        self._path_counts: dict[str, int] = {"instant": 0, "intelligent": 0, "background": 0}
        self._interrupted_count: int = 0
        self._error_count: int = 0
        self._last_tts_backend: str = ""
        self._last_tts_metric_type: str = ""

    def start_turn(
        self,
        turn_id: str,
        path: str = "instant",
        model: str = "",
        t_stt_done: float = 0.0,
        classifier_ms: float = 0.0,
        stt_ms: float = 0.0,
        provider: str = "",
        tier: str = "local",
        routing_reason: str = "local_default",
        privacy_classification: str = "public",
        fallback_occurred: bool = False,
    ) -> TurnTrace:
        now = time.monotonic()
        last_stt = stt_ms if stt_ms > 0 else (
            self._samples["stt_final_ms"][-1] if (t_stt_done > 0 and self._samples["stt_final_ms"]) else 0.0
        )
        origin = (t_stt_done - (last_stt / 1000.0)) if (t_stt_done > 0 and last_stt > 0) else (t_stt_done or now)
        trace = TurnTrace(
            turn_id=turn_id,
            path=path,
            model=model,
            provider=provider,
            tier=tier,
            routing_reason=routing_reason,
            privacy_classification=privacy_classification,
            fallback_occurred=fallback_occurred,
            t_origin=origin,
            t_stt_done=t_stt_done,
            stt_ms=last_stt,
            classifier_ms=classifier_ms,
            t_classified_start=t_stt_done if t_stt_done > 0 else now,
            t_classified_end=(t_stt_done if t_stt_done > 0 else now) + (classifier_ms / 1000.0),
            t_llm_start=now,
        )
        with self._lock:
            self._traces[turn_id] = trace
            if path in self._path_counts:
                self._path_counts[path] += 1
        return trace

    def update_turn_route(
        self,
        turn_id: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        tier: str | None = None,
        routing_reason: str | None = None,
        privacy_classification: str | None = None,
        fallback_occurred: bool | None = None,
    ) -> None:
        with self._lock:
            tr = self._traces.get(turn_id)
            if not tr:
                return
            if provider is not None:
                tr.provider = provider
            if model is not None:
                tr.model = model
            if tier is not None:
                tr.tier = tier
            if routing_reason is not None:
                tr.routing_reason = routing_reason
            if privacy_classification is not None:
                tr.privacy_classification = privacy_classification
            if fallback_occurred is not None:
                tr.fallback_occurred = fallback_occurred

    def record(self, stage: str, value: float):
        if stage not in self._samples or value < 0:
            return
        with self._lock:
            self._samples[stage].append(float(value))

    def mark_memory_retrieval(self, turn_id: str, t_start: float, t_end: float):
        with self._lock:
            tr = self._traces.get(turn_id)
            if tr:
                tr.t_memory_start = t_start
                tr.t_memory_end = t_end
            dur_ms = max(0.0, (t_end - t_start) * 1000.0)
            self._samples["memory_retrieval_ms"].append(dur_ms)

    def mark_llm_start(self, turn_id: str):
        now = time.monotonic()
        with self._lock:
            tr = self._traces.get(turn_id)
            if tr:
                tr.t_llm_start = now

    def mark_first_token(self, turn_id: str):
        now = time.monotonic()
        with self._lock:
            tr = self._traces.get(turn_id)
            if tr and tr.t_first_token == 0.0:
                tr.t_first_token = now
                if tr.t_llm_start > 0:
                    self._samples["llm_ttft_ms"].append((now - tr.t_llm_start) * 1000.0)

    def add_token(self, turn_id: str):
        with self._lock:
            tr = self._traces.get(turn_id)
            if tr:
                tr.token_count += 1

    def mark_tts_queued(self, turn_id: str):
        now = time.monotonic()
        with self._lock:
            tr = self._traces.get(turn_id)
            if tr and tr.t_tts_queued == 0.0:
                tr.t_tts_queued = now

    def mark_tts_dispatch(self, turn_id: str, backend: str = "macos_say"):
        """Record TTS subprocess/dispatch latency (NOT true acoustic first-audio)."""
        now = time.monotonic()
        with self._lock:
            tr = self._traces.get(turn_id)
            if tr and tr.t_tts_dispatch == 0.0:
                tr.t_tts_dispatch = now
                tr.tts_backend = backend
                tr.tts_metric_type = "process_launch"
                self._last_tts_backend = backend
                self._last_tts_metric_type = "process_launch"
                if tr.t_tts_queued > 0:
                    self._samples["tts_dispatch_ms"].append((now - tr.t_tts_queued) * 1000.0)
                anchor = tr.t_stt_done if tr.t_stt_done > 0 else tr.t_llm_start
                if anchor > 0:
                    self._samples["e2e_dispatch_ms"].append((now - anchor) * 1000.0)

    def mark_tts_output_submit(self, turn_id: str, backend: str = "piper"):
        """Record audio output buffer submission latency (sd.play handoff, not acoustic TTFA)."""
        now = time.monotonic()
        with self._lock:
            tr = self._traces.get(turn_id)
            if tr and tr.t_tts_first_audio == 0.0:
                tr.t_tts_first_audio = now
                tr.tts_backend = backend
                tr.tts_metric_type = "audio_output_submission"
                self._last_tts_backend = backend
                self._last_tts_metric_type = "audio_output_submission"
                if tr.t_tts_queued > 0:
                    self._samples["tts_output_submit_ms"].append((now - tr.t_tts_queued) * 1000.0)
                anchor = tr.t_stt_done if tr.t_stt_done > 0 else tr.t_llm_start
                if anchor > 0:
                    self._samples["e2e_output_submit_ms"].append((now - anchor) * 1000.0)

    @staticmethod
    def _build_timeline(tr: TurnTrace) -> list[dict]:
        """Build overlapping execution intervals relative to tr.t_origin."""
        origin = tr.t_origin or tr.t_llm_start
        intervals: list[dict] = []

        def _add(name: str, t0: float, t1: float, metric_type: str = "wall_clock"):
            if t0 <= 0 or t1 < t0:
                return
            intervals.append(
                {
                    "stage": name,
                    "start_ms": round(max(0.0, (t0 - origin) * 1000.0), 1),
                    "end_ms": round(max(0.0, (t1 - origin) * 1000.0), 1),
                    "duration_ms": round(max(0.0, (t1 - t0) * 1000.0), 1),
                    "metric_type": metric_type,
                }
            )

        if tr.t_stt_done > 0 and tr.stt_ms > 0:
            _add("STT", tr.t_stt_done - (tr.stt_ms / 1000.0), tr.t_stt_done)
        if tr.classifier_ms > 0:
            _add("CLASSIFIER", tr.t_classified_start, tr.t_classified_end)
        if tr.t_memory_start > 0 and tr.t_memory_end >= tr.t_memory_start:
            _add("MEMORY RETRIEVAL", tr.t_memory_start, tr.t_memory_end)
        if tr.t_llm_start > 0 and tr.t_first_token >= tr.t_llm_start:
            _add("LLM TTFT", tr.t_llm_start, tr.t_first_token)
        if tr.t_first_token > 0 and tr.t_done >= tr.t_first_token:
            _add("LLM GENERATION", tr.t_first_token, tr.t_done)
        if tr.t_tts_queued > 0:
            if tr.t_tts_first_audio >= tr.t_tts_queued:
                _add("TTS OUTPUT SUBMIT", tr.t_tts_queued, tr.t_tts_first_audio, "audio_output_submission")
            elif tr.t_tts_dispatch >= tr.t_tts_queued:
                _add("TTS DISPATCH", tr.t_tts_queued, tr.t_tts_dispatch, "process_launch")
        if tr.t_done >= origin:
            _add("TOTAL", origin, tr.t_done)
        return intervals

    def finish_turn(self, turn_id: str, interrupted: bool = False, error: bool = False):
        now = time.monotonic()
        with self._lock:
            tr = self._traces.pop(turn_id, None)
            if not tr:
                return
            tr.t_done = now
            tr.interrupted = interrupted
            tr.error = error
            if interrupted:
                self._interrupted_count += 1
            if error:
                self._error_count += 1
            dur_ms = (now - tr.t_llm_start) * 1000.0 if tr.t_llm_start else 0.0
            gen_sec = (now - tr.t_first_token) if tr.t_first_token > 0 else 0.0
            tok_s = (tr.token_count / gen_sec) if gen_sec > 0.05 and tr.token_count > 1 else 0.0
            if not interrupted and not error:
                if dur_ms > 0:
                    self._samples["total_duration_ms"].append(dur_ms)
                if tok_s > 0:
                    self._samples["llm_tok_s"].append(tok_s)
            timeline = self._build_timeline(tr)
            self._recent_turns.appendleft(
                {
                    "turn_id": turn_id,
                    "path": tr.path,
                    "provider": tr.provider,
                    "model": tr.model,
                    "tier": tr.tier,
                    "routing_reason": tr.routing_reason,
                    "privacy_classification": tr.privacy_classification,
                    "fallback_occurred": tr.fallback_occurred,
                    "tts_backend": tr.tts_backend,
                    "tts_metric_type": tr.tts_metric_type,
                    "ttft_ms": round((tr.t_first_token - tr.t_llm_start) * 1000.0, 1)
                    if tr.t_first_token and tr.t_llm_start
                    else 0.0,
                    "tok_s": round(tok_s, 1),
                    "tokens": tr.token_count,
                    "duration_ms": round(dur_ms, 1),
                    "interrupted": interrupted,
                    "error": error,
                    "timeline": timeline,
                }
            )

    def get_turn_timeline(self, turn_id: str) -> list[dict]:
        with self._lock:
            for t in self._recent_turns:
                if t.get("turn_id") == turn_id:
                    return list(t.get("timeline", []))
            return []

    def get_summary(self) -> dict:
        with self._lock:
            stats = {}
            for stage, dq in self._samples.items():
                vals = sorted(dq)
                entry: dict[str, object] = {
                    "count": len(vals),
                    "last": round(dq[-1], 1) if dq else 0.0,
                    "p50": _percentile(vals, 50),
                    "p95": _percentile(vals, 95),
                    "p99": _percentile(vals, 99),
                }
                if stage in self.STAGE_SEMANTICS:
                    entry["metric_type"] = self.STAGE_SEMANTICS[stage]["metric_type"]
                    entry["backend"] = self.STAGE_SEMANTICS[stage]["backend"]
                stats[stage] = entry
            tts_by_backend = {
                "macos_say": {
                    "metric_type": "process_launch",
                    "comparable_with_output_submission": False,
                    "tts_dispatch_ms": stats["tts_dispatch_ms"],
                    "e2e_dispatch_ms": stats["e2e_dispatch_ms"],
                },
                "piper": {
                    "metric_type": "audio_output_submission",
                    "comparable_with_process_launch": False,
                    "tts_output_submit_ms": stats["tts_output_submit_ms"],
                    "e2e_output_submit_ms": stats["e2e_output_submit_ms"],
                },
            }
            return {
                "stages": stats,
                "tts_by_backend": tts_by_backend,
                "stage_semantics": self.STAGE_SEMANTICS,
                "tts_backend": self._last_tts_backend,
                "tts_metric_type": self._last_tts_metric_type,
                "path_counts": dict(self._path_counts),
                "interrupted_count": self._interrupted_count,
                "error_count": self._error_count,
                "recent_turns": list(self._recent_turns)[:10],
            }


latency_tracker = LatencyTracker()
