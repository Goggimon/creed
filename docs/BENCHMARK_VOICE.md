# CREED On-Device Voice Performance Benchmark Procedure

This document defines the manual, real-device benchmark procedure for CREED on Apple Silicon macOS.
All numbers produced here come strictly from live hardware runs—never from deterministic unit tests or mocked stubs.

## 1. Metric Semantics & Backend Caveats

- **`macos_say` (`tts_dispatch_ms`, `e2e_dispatch_ms`, `metric_type="process_launch"`)**:
  Measures only when the macOS `say` subprocess is spawned. It does **not** measure when the first audio sample leaves the speaker. Do **not** compare `tts_dispatch_ms` against `tts_output_submit_ms` or claim acoustic latency from `say`.
- **`piper` (`tts_output_submit_ms`, `e2e_output_submit_ms`, `metric_type="audio_output_submission"`)**:
  Measures synthesis completion up to `sounddevice.play()` buffer handoff. If measuring true acoustic first-sound in air (including CoreAudio buffering), use an external microphone/loopback recording against a known speech-end marker.
- **Completed vs Interrupted/Error Turns**:
  `total_duration_ms` and `llm_tok_s` percentiles exclude interrupted and errored turns; `interrupted_count` and `error_count` are reported separately.

## 2. Prerequisites

1. Start Ollama (`ollama serve`) and verify target models are pulled (e.g. `qwen2.5:3b` for fast path, `qwen3:8b` or `deepseek-r1:8b` for reasoning path).
2. Start CREED backend (`uvicorn api.server:app --host 127.0.0.1 --port 8000`).
3. Record hardware, macOS version, audio devices, and STT config (`16000 Hz`, `1024`-frame blocks) from `GET /api/snapshot` and macOS System Information before each run.

## 3. Benchmark Scenarios (≥ 30 Turns Each)

Run each scenario separately with at least **30 real voice turns**, then save the JSON response from `GET /api/metrics` for each scenario:

1. **Fast model, short conversational requests** (`1_fast_short`, ≥ 30 turns, headphones):
   Example prompts: *"What time is it?"*, *"Open Spotify"*, *"Set volume to 40%"*.
   Record `stt_final_ms`, `classifier_ms`, `llm_ttft_ms`, `llm_tok_s`, `tts_dispatch_ms` (or `tts_output_submit_ms` if `piper`), and `e2e_dispatch_ms` (or `e2e_output_submit_ms` if `piper`).
2. **Reasoning model, multi-step requests** (`2_reasoning_multistep`, ≥ 30 turns, headphones):
   Example prompts: *"Explain why the Arrhenius slope is negative and derive it."*, *"Compare bubble sort and quicksort time complexity."*
3. **First-sentence streaming while generation continues** (`3_first_sentence_stream`, ≥ 30 turns, headphones):
   Use multi-sentence prompts and verify `tts_dispatch_ms` / `tts_output_submit_ms` completes before `total_duration_ms`.
4. **Barge-in during active playback** (`4_barge_in`, ≥ 30 turns, headphones):
   Interrupt CREED mid-sentence during TTS playback; verify `barge_in_ms`, `interrupted_count`, and confirm history stores only spoken text.
5. **Speaker playback with and without headphones** (`5_speaker_vs_headphones`, ≥ 30 turns each):
   Run 30 turns on **headphones** and 30 turns on **MacBook speakers**, noting false barge-ins caused by speaker-to-mic acoustic coupling (since `sounddevice` has no hardware AEC).

## 4. Reporting Checklist

For every published run, include the exported `GET /api/metrics` JSON verbatim, recording:
- `p50` / `p95` / `p99` for `stt_final_ms`, `classifier_ms`, `llm_ttft_ms`, `llm_tok_s`, `tts_dispatch_ms` (or `tts_output_submit_ms` if `piper`), `e2e_dispatch_ms` (or `e2e_output_submit_ms` if `piper`), and `barge_in_ms`;
- macOS version, hardware model & RAM, STT/TTS backends, `tts_metric_type` (`process_launch` vs `audio_output_submission`), model names, audio input/output devices, sample rate (`16000 Hz`), block size (`1024`), and `headphones` vs `speakers`.
