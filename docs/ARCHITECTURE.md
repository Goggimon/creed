# CREED Architecture Specification & Conformance Rules

This document defines the canonical module boundaries for **CREED** (Modular Monolith).
Following [Qt Architecture Conformance Checking](https://www.qt.io/quality-assurance/software-architecture) principles, any dependency rule not checked automatically will drift—therefore these boundaries are enforced in CI via `TestArchitectureBoundaryConformance`.

## 1. Domain Boundaries

| Domain | Current Paths | Responsibility |
|---|---|---|
| **Core** | `core/` (`engine.py`, `event_bus.py`, `tools.py`, `router.py`) | Application lifecycle, turn orchestration, composition root (`build_creed_engine`), event dispatch, tool registry |
| **Intelligence** | `intelligence/` (`complexity_classifier.py`, `model_router.py`), `modules/ai.py`, `modules/base_ai.py` | LLM provider interfaces (`BaseAIProvider`, `ProviderRegistry`, `MockLLMProvider`), complexity classification, model routing |
| **Voice** | `core/voice/` (`stt.py`, `wake.py`), `modules/tts.py` | Audio capture, VAD, STT, TTS, barge-in echo mitigation |
| **Memory** | `modules/memory.py` | Persistent conversation history, notes, reminders, workflows, knowledge storage |
| **Tools / System Adapters** | `modules/system.py` (`SystemMonitor`, `BluetoothAdapter`, `ADBAdapter`, `ModelRuntimeMonitor`), `modules/mac_control.py`, `modules/bt_audio.py`, `modules/phone_adb.py`, `modules/vspotify.py`, `modules/jee_tutor.py` | External hardware/system adapters and tool integrations |
| **Interface** | `gui/`, `api/` | PySide6 desktop UI and FastAPI HTTP/WebSocket transport |
| **Infrastructure** | `config/`, `utils/` | Configuration, structured/redacted logging with correlation context, environment loading |
| **Developer** | `monitoring/`, `tests/`, `docs/` | Latency observability, regression tests, benchmarks, architecture docs |

## 2. Allowed & Forbidden Dependencies (Enforced in CI)

1. **`intelligence/`** MUST NOT import `gui`, `api`, `modules.tts`, `modules.memory`, or `core.engine`.
2. **`monitoring/`** MUST NOT import `gui`, `api`, `core.engine`, or `modules`.
3. **`gui/`** MUST NOT import `intelligence`, `modules`, or `core.engine` directly (UI communicates with the backend exclusively via HTTP/WebSocket contracts).
4. **`config/`** and **`utils/`** MUST NOT import `core`, `intelligence`, `modules`, `api`, or `gui`.
5. **`core/engine.py`** MUST NOT import concrete LLM providers (`modules.ai`, `modules.cloud_disable`) OR concrete subsystem implementations (`modules.tts`, `modules.memory`, `modules.system`, `modules.mac_control`, `modules.bt_audio`, `modules.phone_adb`, `modules.vspotify`, `core.voice.stt`, `core.voice.wake`) or `sqlite3`. All subsystems are injected via `core.router.build_creed_engine` (Composition Root).
6. **`modules/memory.py`** MUST NOT import `sqlite3`. Memory logic operates exclusively against the `MemoryRepository` protocol (`InMemoryMemoryRepository` for tests/DB-free runs, `SQLiteMemoryRepository` wired in `core/router.py` for production).

## 3. Provider Contracts, Diagnostics & Observability

- **Provider Contract (`modules/base_ai.py`)**: All LLM providers (`Module`/Ollama, `CloudModule`/Groq, `MockLLMProvider`) implement `BaseAIProvider.stream_turn(history, tools, model_override, cancel_event, timeout_s)`, yielding standardized `ProviderEvent` dicts (`token`, `tool_calls`) and raising `ProviderError` / `ProviderUnavailableError` / `ProviderTimeoutError`.
- **Memory Repository & Migrations (`modules/memory.py`, `core/router.py`, `docs/MEMORY_MIGRATIONS.md`)**: `MemoryModule` depends on `MemoryRepository` (`Protocol`) returning domain dicts and raising domain `MemoryError` (never `sqlite3.Row` or `sqlite3.Error`). `SQLiteMigrator` manages versioned transactional migrations via `schema_version`, creating verified `sqlite3.Connection.backup()` snapshots before migrating existing databases and rejecting unsupported future schema versions.
- **Structured & Redacted Logging (`utils/logger.py`)**: JSON-formatted events carrying `timestamp`, `level`, `module`, `event`, `conversation_id`, `turn_id`, `task_id`, and structured `exception` tracebacks, with automatic redaction of prompt text and secrets, and `spawn_correlated_thread()` for thread-boundary propagation.
- **Separated Metrics & Diagnostics API (`api/server.py`)**:
  - `GET /api/metrics`: Pure pipeline latency and throughput percentiles (`p50`/`p95`/`p99`) grouped by TTS backend and metric type.
  - `GET /api/diagnostics/logs`: Bounded, redacted diagnostic event stream filterable by `turn_id`.
- **Overlapping Interval Timelines (`monitoring/latency_tracker.py`, `gui/components/tabs.py`)**: Per-turn timelines record `start_ms..end_ms` intervals for `STT`, `CLASSIFIER`, `MEMORY RETRIEVAL`, `LLM TTFT`, `LLM GENERATION`, `TTS DISPATCH`/`TTS OUTPUT SUBMIT`, and wall-clock `TOTAL` (never summing overlapping intervals).

## 4. Architectural Success Criteria

CREED's architecture is evaluated against six concrete capabilities:
- Add a new LLM provider without modifying `core/engine.py`.
- Add a new plugin/capability without modifying `gui/`.
- Replace SQLite storage without rewriting memory retrieval logic (completed in Tranche 4 via `MemoryRepository` + `InMemoryMemoryRepository` + `SQLiteMemoryRepository`).
- Instantiate and test `CreedEngine` deterministically with mock providers, mock voice systems, and an in-memory repository without touching real hardware.
- Diagnose turn failures from structured logs (`/api/diagnostics/logs`) and `/api/metrics` without tracing 20 files.
- Survive application restarts without losing ongoing task state (completed in Tranche 5 via `core/ports/tasks.py`, `core/tasks.py`, and `infrastructure/sqlite_tasks.py`).

## 5. Phase 3 — Plugin Trust Boundary, Authorization & Closure (CLOSED)

- **Status:** **CLOSED** (verified against 52 unit tests; 50 executed & passed under system `python3`, 2 `.venv`-only FastAPI/PySide6 tests pending local `.venv/bin/python` run outside this sandbox).
- **In-Process Plugin Trust Boundary (Accepted Limitation):** Plugin discovery (`PluginManager.discover()`) inspects `plugin.json` manifests without executing code and blocks path-traversal / symlink escapes. However, **trusted and enabled plugins execute Python in CREED's own process and are NOT sandboxed**. Only enable plugins whose code you trust; a malicious trusted plugin can bypass `ToolRegistry` by importing Python modules directly.
- **Centralized Authorization & Preserved Decisions:**
  - Unclassified tools default to `side_effect="unknown"` in `ToolRegistry.register()` and require approval via `AuthorizationPolicy`.
  - All 30 built-in tools across `modules/` and `core/router.py` are explicitly classified (`read_only`, `local_write`, `system_control`, `external`).
  - Foreground `_run_tool_turn_loop()`, background `run_background_agent_turn()`, `CreedEngine.run_workflow()`, and `TaskRunner.run()` all enforce `tools.authorize(...)` immediately before execution.
  - Approvals are single-use, expire when `expires_at` passes, and are SHA-256 bound to action name, arguments, `task_id`, and `plugin_name` via `ApprovalManager`.
  - `TaskStatus.UNCERTAIN` (`"uncertain"`) distinguishes post-crash / unconfirmed synchronous-tool-cancellation states from initial approval gates (`waiting_for_approval`) and is never auto-retried on `recover_on_startup()`.
- **Synchronous Tool Cancellation Limitation:** Python cannot forcibly terminate an already-running synchronous OS thread mid-call; `ToolRegistry.execute()` detects unconfirmed thread termination on `asyncio.CancelledError` and transitions the task to `TaskStatus.UNCERTAIN` instead of falsely reporting `CANCELLED`.

## 6. Tranche 4.3 — Local / Cloud Model Routing (COMPLETE)

- **Status:** **COMPLETE** (19/19 focused Tranche 4.3 routing tests passed; full available regression suite under system Python 3.9.6: 74 passed, 0 failed, 2 environment-dependent `.venv` skips; Python 3.12 local verification via `.venv/bin/python -m unittest discover -s tests -v` remains outstanding).

- **Privacy-First Defaults (`config/settings.py`, `intelligence/model_router.py`):** `allow_cloud_escalation=False` and `cloud_privacy_mode="local_on_private"` by default. `ModelRouter` classifies turns using explicit `ContextPrivacyMetadata` from `MemoryModule` (`retrieve_relevant`), `WorkContextBuilder` (`build_with_metadata`), local-file/note flags, and prior conversation history, with keyword heuristics only as a secondary fallback. Private context never reaches cloud providers without explicit per-turn `allow_private_cloud=True`.
- **Manual Overrides & Tool Compatibility (`modules/base_ai.py`, `intelligence/model_router.py`):** `ProviderRegistry` tracks provider `tier` (`"local"` | `"cloud"`) and `supports_tools` capabilities without hardcoding Ollama as the only local backend. Manual provider/model selection respects `local_on_private`, keeps tool-dependent turns on compatible local providers when cloud tool support is unavailable, and reports any fallback or unavailable provider clearly rather than silently switching.
- **Pre-Stream Fallback vs. Mid-Stream Failure (`core/engine.py`):** Cloud `ProviderError` failures before the first streamed token (and before any tool execution) fall back once to a compatible local provider with `cloud_unavailable_fallback` logged. Failures after streaming begins never replay the request, preserve already-confirmed output, and leave `AuthorizationPolicy` invariant.
- **Routing Observability (`monitoring/latency_tracker.py`, `core/engine.py`, `utils/logger.py`):** `RouteDecision`, `CreedEngine._last_route` (`/api/snapshot`), `LatencyTracker` (`/api/metrics`), and structured logs record `provider`, `model`, `tier`, `routing_reason` (`local_default`, `privacy_restriction`, `cloud_complexity_escalation`, `manual_override`, `cloud_unavailable_fallback`), `privacy_classification`, and `fallback_occurred`.
- **Verified Routing Guarantees (Security Audit):**
  - *Privacy aggregation:* `ContextPrivacyMetadata` combines flags conservatively; `explicit_sensitivity="public"` never downgrades private context from retrieved memories, ongoing work, local files, personal notes, or prior conversation history.
  - *Manual override security:* `selected_provider`, `selected_model`, and `allow_cloud_escalation=True` cannot bypass `local_on_private` without explicit per-turn `allow_private_cloud=True`.
  - *Consent lifetime:* `allow_private_cloud=True` is scoped strictly to the authorized turn and never leaks into subsequent turns, other sessions, or promoted background tasks.
  - *Fallback integrity:* Pre-stream cloud fallback never replays after streaming begins or after tool execution, preventing duplicate tool calls or authorization bypasses.
  - *Background task consistency:* `run_background_agent_turn()` re-evaluates `ContextPrivacyMetadata` (including persisted `privacy_flags` and `privacy_classification` from SQLite task arguments) with `allow_private_cloud=False` and `allow_cloud_escalation=False`, strips cloud model identifiers on promotion, fails cleanly with `ProviderUnavailableError` if no local provider is available, and records its routing decision in `_last_route` and `background_turn_routed` logs.
- **Verification Results:**
  - `python3 -m compileall -q config core intelligence modules monitoring api tests`: passed (exit code `0`).
  - `python3 -m unittest tests.test_tranche_4_3_routing -v` (system Python `3.9.6`): **19/19 passed**.
  - `python3 -m unittest discover -s tests` (system Python `3.9.6`): **76 tests total** (57 Tranche 4.2 + 19 Tranche 4.3) — **74 passed**, **2 skipped** (`test_5_api_isolation_pagination_and_atomic_approvals`, `test_7_tasks_tab_ui_destinations_and_error_states`, which require `.venv` FastAPI/PySide6).
  - `test_phase2_conversation_concurrency_and_context_consistency` deadlock root-caused to `ConcurrentAI.stream_turn` matching `"in the background"` inside injected `WorkContextBuilder` text; fixed to inspect only `last_user.rsplit("User:", 1)[-1]` and now passes in `0.027s`.
- **Known Limitations & Environment Notes:**
  - `CloudModule` (`modules/cloud_disable.py`) currently sets `supports_tools=False`; tool-dependent turns remain on local providers unless a tool-capable cloud provider is registered.
  - Background tasks promoted to `TaskOrchestrator` (`run_background_agent_turn`) execute locally and do not escalate to cloud mid-task.
  - `.venv/bin/python` (Python 3.12) symlinks outside this sandbox's connected folders (`Operation not permitted`), and `pytest` (an optional `[project.optional-dependencies] dev` package) is not installed in `.venv`; local Python 3.12 verification via `.venv/bin/python -m unittest discover -s tests -v` remains outstanding for the 2 `.venv`-only FastAPI/PySide6 tests.

## 7. Tranche 4.4 — Cloud Tool Support & Routing UI (COMPLETE)

- **Status:** **COMPLETE** (verified in local Python `3.12.16` `.venv` with `82/82` tests passing, `ruff` clean, and `mypy` clean).
- **Roadmap Terminology:**
  - **Tranche:** Individual implementation milestone (e.g., Tranche 4.3, Tranche 4.4).
  - **CREED V1:** Established only after ALL planned V1 tranches are completed and accepted. Completing Tranche 4.4 does **not** establish CREED V1.
  - **V1 Benchmark:** Comprehensive cold-start evaluation performed after CREED V1 is fully established.
  - **ELARIS / CREED V2:** Next major development phase and product evolution; begins only after CREED V1 and the V1 Benchmark are complete.
- **Model-Specific Cloud Tool Calling (`modules/cloud_disable.py`, `modules/base_ai.py`, `intelligence/model_router.py`):**
  - `CloudModule` maintains an explicit, easily updatable `GROQ_TOOL_CAPABLE_MODELS` allowlist and exposes `is_tool_calling_supported(model)` / `supports_tools_for_model(model)`.
  - `ProviderRegistry.resolve_provider(..., require_tools=True, model=...)` and `ModelRouter` check model-level tool compatibility before selecting a cloud model; incompatible cloud models are rejected or routed to a compatible local provider.
  - `CloudModule.stream_turn()` passes OpenAI-format `tools` (`tool_choice="auto"`), normalizes internal tool-turn history (`_format_messages_for_openai`), assembles fragmented `delta.tool_calls` chunks across multiple parallel tool calls, validates JSON arguments (raising `ProviderError` on malformed/non-object JSON), and preserves `ToolRegistry`, `AuthorizationPolicy`, and `ApprovalManager` unchanged.
- **Per-Turn Cloud Consent & Confirmed Routing UI (`gui/components/input_bar.py`, `gui/main_window.py`, `gui/worker.py`, `api/server.py`, `core/engine.py`):**
  - `01 INTELLIGENCE` `InputBar` provides a default-OFF `☁ CONSENT: OFF` toggle (`allow_private_cloud`) scoped strictly to a single submitted turn and reset in a `finally:` block even if submission fails. Consent never persists across turns, sessions, or background tasks.
  - `CreedEngine` publishes `route_update` on `event_bus` only after confirmed provider resolution, pre-stream fallback, or routing/provider failure—never emitting intended routing as confirmed execution.
  - `01 INTELLIGENCE` displays Active Provider, Active Model, Tier, Routing Reason, Privacy Classification, Cloud Consent Status, and Fallback/Failure status, synchronized via both live `route_update` WebSocket events and `/api/snapshot`.
- **Verification Results:**
  - `python3 -m compileall -q core intelligence modules monitoring api config utils gui tests`: passed (exit code `0`).
  - `.venv/bin/python -m unittest discover -s tests -v` (Python `3.12.16` local environment): **82/82 passed** (including all 6 Tranche 4.4 tests and all FastAPI/PySide6 tests, `0` skipped, `0` failed).
  - `.venv/bin/ruff check intelligence monitoring config utils tests`: **All checks passed** (`0` errors).
  - `.venv/bin/mypy intelligence monitoring config`: **No issues** (`0` errors).
