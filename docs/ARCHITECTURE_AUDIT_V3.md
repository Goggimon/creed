# CREED 3.0 — Repository Architecture Audit & Overhaul Plan

## 1. Complete Repository Architecture Audit

### Current Module Inventory & Coupling Findings

| Current Path | Responsibility | Observed Architectural Issues |
|---|---|---|
| `core/engine.py` (~36 KB) | God-object orchestrator: LLM loop, RAG, STT/TTS/Wake wiring, Ollama HTTP model pull/delete, ADB/Bluetooth snapshot, JEE tutor imports, workflow runner, tool registration | **Tight coupling & hidden dependencies**: directly instantiates `LocalAI()`, `TTSModule()`, `STTEngine()`, `WakeWordDetector()`, `ModelRouter()`, `MemoryModule`, `SystemModule`; imports `httpx`, `modules.bt_audio`, `modules.phone_adb`, `modules.jee_tutor` inside methods; holds global mutable `latency_tracker` and `event_bus` singletons. |
| `core/event_bus.py` | Global singleton `event_bus` pub/sub | **Untyped string events** (`"status_change"`, `"llm_token"`, etc.) with no payload schemas; global singleton makes isolated multi-instance testing harder. |
| `core/tools.py` | `ToolRegistry` with Ollama schema export & async/thread execution | **No permission model, no manifest/capability metadata, no approval gates**; any registered tool can mutate Mac/ADB/files without policy checks. |
| `modules/ai.py`, `modules/base_ai.py`, `modules/cloud_disable.py` | `BaseAIProvider` ABC (`chat`, `stream_chat`), Ollama `Module`, unused `CloudModule` | **Interface drift**: `engine.py` calls `self.ai.stream_turn(tools=..., model_override=...)`, which is **missing from `BaseAIProvider`**! `cloud_disable.py` is dead/dormant code with `load_dotenv()` side-effect at import time. |
| `modules/memory.py` (~26 KB) | SQLite persistence for messages, notes, reminders, conversations, workflows, JEE flashcards, JEE tests | **Mixed domain + storage**: raw `sqlite3` DDL/queries mixed with RAG retrieval and business logic; no versioned schema migrations or backup mechanism. |
| `modules/jee_tutor.py`, `modules/mac_control.py`, `modules/bt_audio.py`, `modules/phone_adb.py`, `modules/vspotify.py`, `modules/system.py` | Domain tools & legacy intent handlers | **Dual routing legacy**: `core/router.py` (`IntentRouter`) coexists alongside LLM tool-calling (`ToolRegistry`); no standardized plugin manifest or permission declaration. |
| `core/voice/stt.py`, `core/voice/wake.py`, `modules/tts.py` | Audio capture, VAD/barge-in, Whisper STT, Wake word, Piper/`say` TTS | **Voice split across `core/voice/` and `modules/`**: `tts.py` lives in `modules/` while `stt.py`/`wake.py` live in `core/voice/`. `tts.py` and `stt.py` import global `latency_tracker` directly. |
| `api/server.py` | FastAPI HTTP + WebSocket server | **Module-level singleton `engine = CreedEngine()`** created at import time; mixes HTTP routes, WebSocket connection manager, and `.env` file mutation. |
| `gui/app.py`, `gui/main_window.py`, `gui/worker.py`, `gui/components/*` | PySide6 desktop UI + Three.js visualizer | **UI/backend transport coupling**: `gui/worker.py` and `main_window.py` talk to hardcoded `127.0.0.1:8000` via `aiohttp`/`requests`; `runcreed.py` uses Windows-only `subprocess.CREATE_NEW_CONSOLE`. |
| `config/settings.py` | `CreedConfig` dataclass | **Import-time `load_dotenv()` & `os.getenv()`** with no schema validation, type range checks, or `pyproject.toml` integration. |
| `utils/logger.py` | Basic `logging.FileHandler` + `StreamHandler` | **Unstructured plain-text logs**; no correlation/turn IDs, no structured error context, no rotation. |
| `architecture_design_and_milestones.md`, `generate_changelog.py`, `data.json` | Legacy v1/v2 planning & helper scripts | **Stale/duplicate artifacts** from earlier iterations (`data.json` vs `creed.db`). |

---

## 2. Proposed Target Architecture (Modular Monolith)

CREED 3.0 adopts a **Modular Monolith** with explicit domain packages, dependency injection via a composition root (`app/container.py` or `bootstrap`), typed contracts (`Protocol`/ABC), and an automated boundary conformance check in CI:

| Domain | Package | Responsibility | Allowed Dependencies |
|---|---|---|---|
| **Core** | `creed/core/` | Lifecycle, turn orchestration, typed EventBus, task state machine | Domain interfaces (`contracts/`), `infrastructure/logging` |
| **Intelligence** | `creed/intelligence/` | `LLMProvider` protocol, Ollama/Mock/Cloud providers, complexity classifier, model router, context builder | `core/contracts`, `infrastructure/config` |
| **Voice** | `creed/voice/` | `STTEngine`, `TTSEngine`, `WakeDetector`, audio device abstraction, barge-in | `core/contracts`, `monitoring/` |
| **Memory** | `creed/memory/` | Working, episodic, semantic, procedural memory services behind `MemoryStore` repository interface | `core/contracts`, `infrastructure/storage` |
| **Tools & Plugins** | `creed/plugins/`, `creed/tools/` | Plugin manifests, permission gates, lifecycle hooks, capability registry | `core/contracts`, `infrastructure/config` |
| **Interface** | `creed/interface/` | PySide6 5-destination UI (`CORE`, `SYSTEMS`, `MEMORY`, `MACHINE`, `WORKSPACE`) + FastAPI/WS adapter | `core/contracts` (via API/WebSocket DTOs only) |
| **Infrastructure** | `creed/infrastructure/` | Validated config (`pydantic`), versioned SQLite migrations, structured logging, secret handling | Standard library / third-party drivers |
| **Developer** | `creed/developer/`, `monitoring/` | Developer console telemetry, latency tracker, mock providers, diagnostics, benchmarks | Read-only observers across domains |

---

## 3. Current-vs-Target Dependency Map

```text
CURRENT (Tangled Hub):
  gui/main_window.py ──(HTTP/WS 127.0.0.1:8000)──> api/server.py (global CreedEngine)
  core/engine.py ──> modules/ai.py, modules/tts.py, core/voice/stt.py, modules/memory.py,
                     modules/bt_audio.py, modules/phone_adb.py, modules/jee_tutor.py,
                     monitoring/latency_tracker.py (global), core/event_bus.py (global)

TARGET (Dependency-Inverted Modular Monolith):
  bootstrap/container.py (Composition Root — wires concrete implementations)
    ├── interface/ (PySide6 UI + FastAPI) ──> core.contracts (DTOs & Event payloads)
    ├── core/orchestrator.py ────────────────> LLMProvider, TTSEngine, STTEngine, MemoryStore, ToolExecutor (Protocols)
    ├── intelligence/ ───────────────────────> core.contracts (implements LLMProvider)
    ├── voice/ ──────────────────────────────> core.contracts (implements STTEngine, TTSEngine)
    ├── memory/ ─────────────────────────────> storage.Repository (implements MemoryStore)
    ├── plugins/ ────────────────────────────> core.contracts (manifests + permission-gated ToolSpec)
    └── developer/ ──────────────────────────> read-only EventBus & Diagnostics snapshots
```

---

## 4. Technical Debt Inventory

1. **P0 — Interface Mismatch**: `BaseAIProvider` lacks `stream_turn()`, forcing `CreedEngine` to depend on Ollama `Module` internals.
2. **P0 — God-Object `CreedEngine`**: Mixes orchestration, hardware probing (`system_profiler`, `adb`), Ollama model management, and SQLite access.
3. **P0 — Unmigrated SQLite Schema**: `modules/memory.py` creates tables ad-hoc with no `schema_version`, migrations, or backup/restore.
4. **P1 — Untyped Global Singletons**: `event_bus` and `latency_tracker` are module-level globals, preventing parallel isolated engine tests.
5. **P1 — Missing Tool Permissions & Approval Gates**: `fs_write_file`, `run_python_file`, `mac_close_app` lack formal permission manifests or human approval hooks.
6. **P1 — Cross-Platform / Startup Fragility**: `runcreed.py` uses Windows-only `CREATE_NEW_CONSOLE` on a macOS project.
7. **P2 — Dead & Legacy Code**: `modules/cloud_disable.py`, `core/router.py` dual-dispatch, `data.json`, and `architecture_design_and_milestones.md`.

---

## 5. Prioritized Implementation Roadmap

| Phase | Milestone | Scope & Exit Criteria |
|---|---|---|
| **CREED 3.0** | **Foundation** | `pyproject.toml`, CI pipeline, AST boundary conformance tests, `docs/ARCHITECTURE.md`, structured logging, `BaseAIProvider` + `MockLLMProvider` contract, composition root DI, SQLite schema versioning. |
| **CREED 3.1** | **Ecosystem** | Plugin manifest schema (`plugin.json`/TOML), permission declarations & approval gates, provider registry (Ollama, Mock, Groq/OpenAI), persistent task engine (checkpoints, cancel/resume across restarts). |
| **CREED 3.2** | **Intelligence** | Working/episodic/semantic/procedural memory split, context budget optimizer, background workflow scheduler, multimodal hooks. |
| **CREED 3.3** | **Experience** | 5-destination UI (`CORE`, `SYSTEMS`, `MEMORY`, `MACHINE`, `WORKSPACE`), embedded Developer Console, unified design system, UI responsiveness tests. |

---

## 6. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Big-bang rewrite breaks working voice pipeline** | High | High | Keep existing `core/`, `modules/`, `api/`, `gui/` operational while introducing contracts and DI incrementally behind adapters. |
| **Architectural drift returns over time** | Medium | High | Enforce allowed/forbidden imports automatically in CI via `TestArchitectureBoundaryConformance` (baseline + fail on new violations). |
| **UI thread blocking during heavy Ollama/SQLite calls** | Medium | Medium | Keep all model/DB/subprocess I/O in async workers or `asyncio.to_thread`; verify with async concurrency tests. |
| **Plugin privilege escalation** | Medium | High | Require explicit capability/permission declarations in plugin manifests and human approval gates for destructive tools. |

---

## 7. Initial Foundational Implementation Plan (Tranche 1 — Executed Now)

1. **`pyproject.toml`**: Centralize project metadata, dev dependencies (`ruff`, `mypy`, `pytest`), and lint/type/test configuration.
2. **`docs/ARCHITECTURE.md`**: Codify domain boundaries, dependency rules, and the 6 architectural success criteria.
3. **`.github/workflows/ci.yml`**: Automate syntax compilation, unit/regression tests, and architecture boundary conformance checks on every push/PR.
4. **Architecture Boundary Conformance Tests** (`tests/test_creed_v2_architecture.py`): Automated AST import checker verifying that `intelligence/`, `monitoring/`, and `gui/` respect domain isolation rules.
