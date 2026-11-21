# tests/test_tranche_4_3_routing.py

import asyncio
import sys
import threading
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for mod_name, attrs in (
    ("dotenv", {"load_dotenv": lambda *a, **kw: False}),
    ("numpy", {"ndarray": object, "float32": float, "sqrt": lambda x: x, "mean": lambda x: x}),
    ("sounddevice", {"InputStream": object, "stop": lambda: None, "play": lambda *a, **kw: None}),
    ("httpx", {"AsyncClient": object, "Client": object, "ConnectError": Exception, "TimeoutException": Exception, "HTTPStatusError": Exception, "RequestError": Exception}),
):
    if mod_name not in sys.modules:
        try:
            __import__(mod_name)
        except ImportError:
            stub = types.ModuleType(mod_name)
            for k, v in attrs.items():
                setattr(stub, k, v)
            sys.modules[mod_name] = stub

from config.settings import config
from core.engine import CreedEngine
from core.event_bus import event_bus
from core.ports.tasks import TaskRecord, TaskStatus, TaskStep
from core.tasks import InMemoryTaskRepository, TaskOrchestrator
from core.tools import ToolRegistry
from intelligence.model_router import ContextPrivacyMetadata, ModelRouter
from modules.base_ai import (
    MockLLMProvider,
    ProviderError,
    ProviderRegistry,
    ProviderUnavailableError,
)
from modules.memory import InMemoryMemoryRepository
from modules.memory import Module as MemoryModule
from monitoring.latency_tracker import latency_tracker
from utils.logger import clear_recent_events, get_recent_events


def _build_routed_engine(
    *,
    local_provider=None,
    cloud_provider=None,
    local_name: str = "local_custom",
    cloud_name: str = "cloud_mock",
    memory=None,
    task_orchestrator=None,
    tools=None,
):
    reg = ProviderRegistry()
    loc = local_provider or MockLLMProvider(
        model="local-7b",
        default_response="Local reply.",
        tier="local",
        supports_tools=True,
        provider_name=local_name,
    )
    reg.register_instance(local_name, loc, default=True)
    if cloud_provider is not None:
        reg.register_instance(cloud_name, cloud_provider)
    engine = CreedEngine(
        provider_registry=reg,
        memory=memory,
        task_orchestrator=task_orchestrator,
        tools=tools or ToolRegistry(),
    )
    return engine, reg, loc


class TestTranche43LocalCloudRouting(unittest.IsolatedAsyncioTestCase):
    def test_1_privacy_defaults_and_local_first_non_ollama_backend(self):
        self.assertFalse(config.allow_cloud_escalation)
        self.assertEqual(config.cloud_privacy_mode, "local_on_private")

        router = ModelRouter()
        decision = router.route(
            "Explain the photoelectric effect in detail",
            installed_models=["local-7b"],
            active_model="local-7b",
            local_providers=[{"name": "mlx_local", "tier": "local", "supports_tools": True, "default_model": "local-7b"}],
            cloud_providers=[{"name": "groq", "tier": "cloud", "supports_tools": True, "default_model": "llama-3.1-8b"}],
            active_provider="mlx_local",
        )
        self.assertEqual(decision.tier, "local")
        self.assertEqual(decision.provider, "mlx_local")
        self.assertEqual(decision.routing_reason, "local_default")
        self.assertFalse(decision.fallback_occurred)

    async def test_2_cloud_complexity_escalation_when_enabled_and_public(self):
        cloud = MockLLMProvider(
            model="cloud-reasoner",
            default_response="Cloud reasoning reply.",
            tier="cloud",
            supports_tools=True,
            provider_name="cloud_mock",
        )
        engine, _, loc = _build_routed_engine(cloud_provider=cloud)
        hist = [{"role": "system", "content": "sys"}]

        await engine.process_text(
            "Explain why entropy increases in an isolated system",
            session_id="pub-sess",
            history=hist,
            allow_cloud_escalation=True,
            context_privacy=ContextPrivacyMetadata(explicit_sensitivity="public"),
        )
        self.assertEqual(len(cloud.calls), 1)
        self.assertEqual(len(loc.calls), 0)
        self.assertEqual(engine._last_route["provider"], "cloud_mock")
        self.assertEqual(engine._last_route["tier"], "cloud")
        self.assertEqual(engine._last_route["routing_reason"], "cloud_complexity_escalation")
        self.assertEqual(engine._last_route["privacy_classification"], "public")
        self.assertFalse(engine._last_route["fallback_occurred"])

    async def test_3_privacy_restrictions_block_cloud_across_all_sensitive_sources(self):
        cloud = MockLLMProvider(
            model="cloud-reasoner",
            default_response="Should never run.",
            tier="cloud",
            supports_tools=True,
            provider_name="cloud_mock",
        )

        # A. Retrieved memories
        mem = MemoryModule(threading.Lock(), repository=InMemoryMemoryRepository(), legacy_json="__none__.json")
        mem.add_note("personal", "Electrochemistry mock score was 92.")
        engine_mem, _, loc_mem = _build_routed_engine(cloud_provider=cloud, memory=mem)
        await engine_mem.process_text(
            "Explain my electrochemistry score",
            session_id="mem-sess",
            allow_cloud_escalation=True,
        )
        self.assertEqual(len(cloud.calls), 0)
        self.assertEqual(len(loc_mem.calls), 1)
        self.assertEqual(engine_mem._last_route["routing_reason"], "privacy_restriction")
        self.assertEqual(engine_mem._last_route["privacy_classification"], "private")

        # B. Ongoing work context
        task_repo = InMemoryTaskRepository()
        task_repo.create_task(
            TaskRecord(
                id="t-priv",
                conversation_id="other-sess",
                title="Private project refactor",
                status=TaskStatus.PAUSED,
                steps=[TaskStep(step_index=0, name="s0", action="act0")],
            )
        )
        orch = TaskOrchestrator(task_repo, step_handler=lambda s, c: "ok")
        engine_work, _, loc_work = _build_routed_engine(cloud_provider=cloud, task_orchestrator=orch)
        await engine_work.process_text(
            "Where did we leave off on unfinished work?",
            session_id="work-sess",
            allow_cloud_escalation=True,
        )
        self.assertEqual(len(cloud.calls), 0)
        self.assertEqual(len(loc_work.calls), 1)
        self.assertEqual(engine_work._last_route["routing_reason"], "privacy_restriction")

        # C. Local files / explicit component metadata + persistent cloud-enabled setting
        engine_files, _, loc_files = _build_routed_engine(cloud_provider=cloud)
        await engine_files.process_text(
            "Analyze this summary",
            session_id="file-sess",
            allow_cloud_escalation=True,
            context_privacy=ContextPrivacyMetadata(has_local_files=True),
        )
        self.assertEqual(len(cloud.calls), 0)
        self.assertEqual(len(loc_files.calls), 1)
        self.assertEqual(engine_files._last_route["routing_reason"], "privacy_restriction")

        # D. Private conversation history (prior turns)
        engine_conv, _, loc_conv = _build_routed_engine(cloud_provider=cloud)
        prior_hist = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "My secret plan"},
            {"role": "assistant", "content": "Noted."},
        ]
        await engine_conv.process_text(
            "Explain the next step in detail",
            session_id="conv-priv",
            history=prior_hist,
            allow_cloud_escalation=True,
        )
        self.assertEqual(len(cloud.calls), 0)
        self.assertEqual(len(loc_conv.calls), 1)
        self.assertEqual(engine_conv._last_route["routing_reason"], "privacy_restriction")

    async def test_4_explicit_per_turn_privacy_override(self):
        cloud = MockLLMProvider(
            model="cloud-reasoner",
            default_response="Cloud with permission.",
            tier="cloud",
            supports_tools=True,
            provider_name="cloud_mock",
        )
        engine, _, loc = _build_routed_engine(cloud_provider=cloud)
        hist = [{"role": "system", "content": "sys"}]

        # Without allow_private_cloud -> blocked
        await engine.process_text(
            "Explain this private note",
            session_id="ovr-sess",
            history=hist,
            allow_cloud_escalation=True,
            context_privacy=ContextPrivacyMetadata(has_personal_notes=True),
            allow_private_cloud=False,
        )
        self.assertEqual(len(cloud.calls), 0)
        self.assertEqual(len(loc.calls), 1)

        # With explicit per-turn allow_private_cloud=True -> permitted for this turn
        await engine.process_text(
            "Explain this private note",
            session_id="ovr-sess",
            history=hist,
            allow_cloud_escalation=True,
            context_privacy=ContextPrivacyMetadata(has_personal_notes=True),
            allow_private_cloud=True,
        )
        self.assertEqual(len(cloud.calls), 1)
        self.assertEqual(engine._last_route["tier"], "cloud")
        self.assertEqual(engine._last_route["privacy_classification"], "private")

    async def test_5_manual_model_and_provider_selection(self):
        cloud = MockLLMProvider(
            model="cloud-default",
            default_response="Cloud manual.",
            tier="cloud",
            supports_tools=True,
            provider_name="cloud_mock",
        )
        engine, _, loc = _build_routed_engine(cloud_provider=cloud)
        hist = [{"role": "system", "content": "sys"}]

        # Manual local model selection
        await engine.process_text(
            "hello",
            session_id="man-1",
            history=hist,
            selected_provider="local_custom",
            selected_model="custom-qwen:14b",
        )
        self.assertEqual(loc.calls[-1]["model"], "custom-qwen:14b")
        self.assertEqual(engine._last_route["routing_reason"], "manual_override")

        # Manual cloud selection must still respect privacy restrictions
        await engine.process_text(
            "hello",
            session_id="man-priv",
            history=hist,
            selected_provider="cloud_mock",
            selected_model="cloud-pro",
            context_privacy=ContextPrivacyMetadata(has_local_files=True),
        )
        self.assertEqual(len(cloud.calls), 0)
        self.assertEqual(engine._last_route["provider"], "local_custom")
        self.assertEqual(engine._last_route["routing_reason"], "privacy_restriction")
        self.assertTrue(engine._last_route["fallback_occurred"])
        self.assertTrue(any("blocked by privacy policy" in a["message"] for a in engine.activity_log))

        # Manual cloud selection with per-turn permission succeeds with chosen model
        await engine.process_text(
            "hello",
            session_id="man-priv-ok",
            history=[{"role": "system", "content": "sys"}],
            selected_provider="cloud_mock",
            selected_model="cloud-pro",
            context_privacy=ContextPrivacyMetadata(has_local_files=True),
            allow_private_cloud=True,
        )
        self.assertEqual(cloud.calls[-1]["model"], "cloud-pro")
        self.assertEqual(engine._last_route["routing_reason"], "manual_override")

    async def test_6_tool_compatibility_keeps_tool_turns_on_compatible_local(self):
        cloud_no_tools = MockLLMProvider(
            model="groq-no-tools",
            default_response="Cloud without tools.",
            tier="cloud",
            supports_tools=False,
            provider_name="groq_mock",
        )
        tools = ToolRegistry()
        tools.register("ping_tool", "Ping", {"type": "object", "properties": {}}, lambda: "pong", side_effect="read_only")
        engine, _, loc = _build_routed_engine(cloud_provider=cloud_no_tools, cloud_name="groq_mock", tools=tools)

        # Complex turn requiring tools -> cloud lacks tool support -> stays on compatible local provider
        await engine.process_text(
            "Explain and analyze system status",
            session_id="tool-compat",
            history=[{"role": "system", "content": "sys"}],
            allow_cloud_escalation=True,
            context_privacy=ContextPrivacyMetadata(explicit_sensitivity="public"),
        )
        self.assertEqual(len(cloud_no_tools.calls), 0)
        self.assertEqual(len(loc.calls), 1)
        self.assertEqual(engine._last_route["provider"], "local_custom")
        self.assertEqual(engine._last_route["tier"], "local")

    async def test_7_provider_unavailability_produces_clear_error_or_reported_fallback(self):
        engine, reg, loc = _build_routed_engine()
        errors = []
        event_bus.subscribe("error", lambda msg: errors.append(msg))

        # A. Unknown manual provider -> clear error, never silently switches
        await engine.process_text(
            "hello",
            session_id="unavail-1",
            history=[{"role": "system", "content": "sys"}],
            selected_provider="nonexistent_provider",
        )
        self.assertEqual(len(loc.calls), 0)
        self.assertTrue(any("nonexistent_provider" in e for e in errors))

        # B. Registered cloud provider whose backend raises ProviderUnavailableError on get() -> reported fallback to local
        def broken_cloud_factory(**_kw):
            raise ProviderUnavailableError("GROQ_API_KEY missing", provider="groq")

        reg.register("groq", broken_cloud_factory, tier="cloud", supports_tools=True, default_model="llama-3.1-8b")
        await engine.process_text(
            "hello",
            session_id="unavail-2",
            history=[{"role": "system", "content": "sys"}],
            selected_provider="groq",
        )
        self.assertEqual(len(loc.calls), 1)
        self.assertEqual(engine._last_route["provider"], "local_custom")
        self.assertEqual(engine._last_route["routing_reason"], "cloud_unavailable_fallback")
        self.assertTrue(engine._last_route["fallback_occurred"])

    async def test_8_pre_stream_fallback_to_compatible_local_provider(self):
        failing_cloud = MockLLMProvider(
            model="cloud-down",
            fail_with=ProviderUnavailableError("Cloud 503", provider="cloud_mock"),
            tier="cloud",
            supports_tools=True,
            provider_name="cloud_mock",
        )
        engine, _, loc = _build_routed_engine(cloud_provider=failing_cloud)
        hist = [{"role": "system", "content": "sys"}]
        clear_recent_events()

        await engine.process_text(
            "Explain thermodynamics laws",
            session_id="fb-pre",
            history=hist,
            allow_cloud_escalation=True,
            context_privacy=ContextPrivacyMetadata(explicit_sensitivity="public"),
        )
        self.assertEqual(len(failing_cloud.calls), 1)
        self.assertEqual(len(loc.calls), 1)
        self.assertEqual(hist[-1]["content"], "Local reply.")
        self.assertEqual(engine._last_route["provider"], "local_custom")
        self.assertEqual(engine._last_route["tier"], "local")
        self.assertEqual(engine._last_route["routing_reason"], "cloud_unavailable_fallback")
        self.assertTrue(engine._last_route["fallback_occurred"])
        events = get_recent_events(turn_id=engine._active_turn_id)
        self.assertTrue(any(e["event"] == "cloud_pre_stream_fallback" for e in events))

    async def test_9_mid_stream_failure_does_not_replay_and_preserves_confirmed_output(self):
        class MidStreamFailCloud(MockLLMProvider):
            async def stream_turn(self, history, tools=None, model_override=None, cancel_event=None, timeout_s=None):
                self.calls.append({"model": model_override or self.model})
                yield {"type": "token", "text": "Confirmed cloud sentence. "}
                await asyncio.sleep(0.005)
                raise ProviderError("Mid-stream connection reset", provider=self.provider_name)

        from modules.tts import TTSModule
        cloud = MidStreamFailCloud(model="cloud-mid", tier="cloud", supports_tools=True, provider_name="cloud_mock")
        engine, _, loc = _build_routed_engine(cloud_provider=cloud)
        engine.tts = TTSModule(max_queue_size=8)
        engine.tts.backend = "macos_say"
        orig_speak = engine.tts.speak

        def confirm_speak(text, turn_id=""):
            orig_speak(text, turn_id=turn_id)
            engine.tts._spoken_by_turn.setdefault(turn_id or engine._active_turn_id, []).append(text)

        engine.tts.speak = confirm_speak
        hist = [{"role": "system", "content": "sys"}]

        await engine.process_text(
            "Explain quantum tunneling",
            session_id="fb-mid",
            history=hist,
            allow_cloud_escalation=True,
            context_privacy=ContextPrivacyMetadata(explicit_sensitivity="public"),
        )
        # MUST NOT replay on local provider after streaming started
        self.assertEqual(len(cloud.calls), 1)
        self.assertEqual(len(loc.calls), 0)
        # Confirmed spoken output is preserved
        self.assertEqual([m["content"] for m in hist if m["role"] == "assistant"], ["Confirmed cloud sentence."])

    async def test_10_authorization_invariance_across_routing_and_fallback(self):
        executed = []
        tools = ToolRegistry()
        tools.register(
            "danger_op",
            "Dangerous op",
            {"type": "object", "properties": {}},
            lambda: executed.append("ran") or "ok",
            side_effect="system_control",
        )
        tools.register(
            "safe_op",
            "Safe op",
            {"type": "object", "properties": {}},
            lambda: executed.append("safe") or "safe_ok",
            side_effect="read_only",
        )

        # Cloud fails pre-stream -> falls back to local -> local emits unapproved danger_op -> MUST still be gated
        failing_cloud = MockLLMProvider(
            model="cloud-down",
            fail_with=ProviderUnavailableError("Down", provider="cloud_mock"),
            tier="cloud",
            supports_tools=True,
            provider_name="cloud_mock",
        )

        class ToolEmittingLocal(MockLLMProvider):
            async def stream_turn(self, history, tools=None, model_override=None, cancel_event=None, timeout_s=None):
                self.calls.append({"model": model_override or self.model})
                if any(m["role"] == "tool" for m in history):
                    yield {"type": "token", "text": "Done safely."}
                else:
                    yield {
                        "type": "tool_calls",
                        "calls": [
                            {"function": {"name": "safe_op", "arguments": {}}},
                            {"function": {"name": "danger_op", "arguments": {}}},
                        ],
                    }

        loc = ToolEmittingLocal(model="local-7b", tier="local", supports_tools=True, provider_name="local_custom")
        engine, _, _ = _build_routed_engine(local_provider=loc, cloud_provider=failing_cloud, tools=tools)
        hist = [{"role": "system", "content": "sys"}]

        await engine.process_text(
            "Explain and run checks",
            session_id="auth-inv",
            history=hist,
            allow_cloud_escalation=True,
            context_privacy=ContextPrivacyMetadata(explicit_sensitivity="public"),
        )
        # safe_op ran exactly once (no duplicate execution), danger_op was blocked by AuthorizationPolicy
        self.assertEqual(executed, ["safe"])
        self.assertTrue(any(t["name"] == "danger_op" and "Approval required" in t["result"] for t in engine.tool_history))

    async def test_11_routing_observability_snapshot_metrics_and_logs(self):
        cloud = MockLLMProvider(
            model="cloud-obs",
            default_response="Observed cloud reply.",
            tier="cloud",
            supports_tools=True,
            provider_name="cloud_mock",
        )
        engine, _, _ = _build_routed_engine(cloud_provider=cloud)
        clear_recent_events()

        await engine.process_text(
            "Explain Maxwell equations",
            session_id="obs-sess",
            history=[{"role": "system", "content": "sys"}],
            allow_cloud_escalation=True,
            context_privacy=ContextPrivacyMetadata(explicit_sensitivity="public"),
        )

        snap = engine.get_system_snapshot()
        router_snap = snap["router"]
        for key in ("provider", "model", "tier", "routing_reason", "privacy_classification", "fallback_occurred"):
            self.assertIn(key, router_snap)
        self.assertEqual(router_snap["provider"], "cloud_mock")
        self.assertEqual(router_snap["model"], "cloud-obs")
        self.assertEqual(router_snap["tier"], "cloud")
        self.assertEqual(router_snap["routing_reason"], "cloud_complexity_escalation")
        self.assertEqual(router_snap["privacy_classification"], "public")
        self.assertFalse(router_snap["fallback_occurred"])

        recent = latency_tracker.get_summary()["recent_turns"][0]
        self.assertEqual(recent["provider"], "cloud_mock")
        self.assertEqual(recent["tier"], "cloud")
        self.assertEqual(recent["routing_reason"], "cloud_complexity_escalation")
        self.assertEqual(recent["privacy_classification"], "public")
        self.assertFalse(recent["fallback_occurred"])

        events = get_recent_events(turn_id=engine._active_turn_id)
        started = next(e for e in events if e["event"] == "turn_started")
        self.assertEqual(started["data"]["provider"], "cloud_mock")
        self.assertEqual(started["data"]["tier"], "cloud")
        self.assertEqual(started["data"]["routing_reason"], "cloud_complexity_escalation")
        self.assertEqual(started["data"]["privacy_classification"], "public")
        self.assertFalse(started["data"]["fallback_occurred"])

    async def test_12_audit_privacy_aggregation_never_downgraded_by_public_metadata(self):
        cloud = MockLLMProvider(
            model="cloud-reasoner",
            default_response="Should not reach cloud.",
            tier="cloud",
            supports_tools=True,
            provider_name="cloud_mock",
        )
        mem = MemoryModule(threading.Lock(), repository=InMemoryMemoryRepository(), legacy_json="__none__.json")
        mem.add_note("personal", "My private physics score is 95.")
        engine, _, loc = _build_routed_engine(cloud_provider=cloud, memory=mem)

        # Even if caller passes explicit_sensitivity="public", retrieved memories MUST keep turn private
        await engine.process_text(
            "Explain my physics score",
            session_id="agg-sess",
            allow_cloud_escalation=True,
            context_privacy=ContextPrivacyMetadata(explicit_sensitivity="public"),
        )
        self.assertEqual(len(cloud.calls), 0)
        self.assertEqual(len(loc.calls), 1)
        self.assertEqual(engine._last_route["privacy_classification"], "private")
        self.assertEqual(engine._last_route["routing_reason"], "privacy_restriction")

        # Combining multiple flags where one is private + explicit_sensitivity="public" -> still private
        meta = ContextPrivacyMetadata(has_local_files=True, explicit_sensitivity="public")
        self.assertTrue(meta.is_private)
        self.assertEqual(ModelRouter.classify_privacy("hello", meta), "private")

    async def test_13_audit_manual_override_security_cannot_bypass_privacy(self):
        cloud = MockLLMProvider(
            model="cloud-pro",
            default_response="Should not reach cloud.",
            tier="cloud",
            supports_tools=True,
            provider_name="cloud_mock",
        )
        engine, _, loc = _build_routed_engine(cloud_provider=cloud)
        hist = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "Private prior turn"},
            {"role": "assistant", "content": "Ack."},
        ]

        # Manual provider + model + escalation enabled, WITHOUT allow_private_cloud=True -> MUST stay local
        await engine.process_text(
            "Explain next steps",
            session_id="sec-man",
            history=hist,
            selected_provider="cloud_mock",
            selected_model="cloud-pro",
            allow_cloud_escalation=True,
            allow_private_cloud=False,
        )
        self.assertEqual(len(cloud.calls), 0)
        self.assertEqual(len(loc.calls), 1)
        self.assertEqual(engine._last_route["tier"], "local")
        self.assertEqual(engine._last_route["routing_reason"], "privacy_restriction")
        self.assertTrue(engine._last_route["fallback_occurred"])

    async def test_14_audit_consent_lifetime_strictly_single_turn_no_leak(self):
        cloud = MockLLMProvider(
            model="cloud-reasoner",
            default_response="Cloud ok.",
            tier="cloud",
            supports_tools=True,
            provider_name="cloud_mock",
        )
        engine, _, loc = _build_routed_engine(cloud_provider=cloud)
        hist_a = [{"role": "system", "content": "sys"}]
        hist_b = [{"role": "system", "content": "sys"}]

        # Turn 1 (sess-a): explicitly authorized for private cloud
        await engine.process_text(
            "Explain my private note",
            session_id="sess-a",
            history=hist_a,
            allow_cloud_escalation=True,
            context_privacy=ContextPrivacyMetadata(has_personal_notes=True),
            allow_private_cloud=True,
        )
        self.assertEqual(len(cloud.calls), 1)
        self.assertEqual(engine._last_route["tier"], "cloud")

        # Turn 2 (same sess-a, NO allow_private_cloud) -> MUST NOT leak consent
        await engine.process_text(
            "Explain more details",
            session_id="sess-a",
            history=hist_a,
            allow_cloud_escalation=True,
            context_privacy=ContextPrivacyMetadata(has_personal_notes=True),
        )
        self.assertEqual(len(cloud.calls), 1)
        self.assertEqual(len(loc.calls), 1)
        self.assertEqual(engine._last_route["tier"], "local")
        self.assertEqual(engine._last_route["routing_reason"], "privacy_restriction")

        # Turn 3 (different sess-b, NO allow_private_cloud) -> MUST NOT leak consent
        await engine.process_text(
            "Explain my private file",
            session_id="sess-b",
            history=hist_b,
            allow_cloud_escalation=True,
            context_privacy=ContextPrivacyMetadata(has_local_files=True),
        )
        self.assertEqual(len(cloud.calls), 1)
        self.assertEqual(len(loc.calls), 2)
        self.assertEqual(engine._last_route["tier"], "local")

    async def test_15_audit_fallback_integrity_no_duplicate_tools_after_tool_exec(self):
        tool_runs = []
        tools = ToolRegistry()
        tools.register(
            "side_effect_read",
            "Side effect read",
            {"type": "object", "properties": {}},
            lambda: tool_runs.append("ran") or "tool-result",
            side_effect="read_only",
        )

        # Cloud executes tool_calls on pass 1, then fails on pass 2 -> MUST NOT fall back & re-run tool on local
        class ToolThenFailCloud(MockLLMProvider):
            async def stream_turn(self, history, tools=None, model_override=None, cancel_event=None, timeout_s=None):
                self.calls.append({"model": model_override or self.model})
                if any(m["role"] == "tool" for m in history):
                    raise ProviderError("Cloud failed after tool execution", provider=self.provider_name)
                yield {
                    "type": "tool_calls",
                    "calls": [{"function": {"name": "side_effect_read", "arguments": {}}}],
                }

        cloud = ToolThenFailCloud(model="cloud-t", tier="cloud", supports_tools=True, provider_name="cloud_mock")
        engine, _, loc = _build_routed_engine(cloud_provider=cloud, tools=tools)
        hist = [{"role": "system", "content": "sys"}]

        await engine.process_text(
            "Explain and run tool",
            session_id="fb-int",
            history=hist,
            allow_cloud_escalation=True,
            context_privacy=ContextPrivacyMetadata(explicit_sensitivity="public"),
        )
        self.assertEqual(tool_runs, ["ran"])
        self.assertEqual(len(loc.calls), 0)

    async def test_16_audit_background_task_preserves_privacy_and_reports_routing(self):
        cloud = MockLLMProvider(
            model="cloud-reasoner",
            default_response="Cloud should not run background private task.",
            tier="cloud",
            supports_tools=True,
            provider_name="cloud_mock",
        )
        mem = MemoryModule(threading.Lock(), repository=InMemoryMemoryRepository(), legacy_json="__none__.json")
        mem.add_note("secret", "Private project key details.")
        engine, _, loc = _build_routed_engine(cloud_provider=cloud, memory=mem)

        async def dispatch_step(step, cancel_ev):
            if step.action == "agent_turn":
                return await engine.run_background_agent_turn(step.args, cancel_event=cancel_ev)
            return await engine.tools.execute(step.action, step.args)

        orch = TaskOrchestrator(InMemoryTaskRepository(), step_handler=dispatch_step)
        engine.task_orchestrator = orch
        clear_recent_events()

        # Even if foreground turn had allow_private_cloud=True, promoted background task MUST NOT leak consent to cloud
        await engine.process_text(
            "audit my secret project in the background",
            session_id="bg-priv",
            allow_cloud_escalation=True,
            allow_private_cloud=True,
        )
        tasks = orch.repo.list_tasks(conversation_id="bg-priv")
        self.assertEqual(len(tasks), 1)
        done = await orch.wait_for_task(tasks[0].id, timeout=2.0)
        self.assertEqual(done.status, TaskStatus.COMPLETED)
        self.assertEqual(len(cloud.calls), 0)
        self.assertEqual(len(loc.calls), 1)
        self.assertEqual(engine._last_route["path"], "background")
        self.assertEqual(engine._last_route["provider"], "local_custom")
        self.assertEqual(engine._last_route["tier"], "local")
        self.assertEqual(engine._last_route["privacy_classification"], "private")

        bg_events = [e for e in get_recent_events(limit=20) if e["event"] == "background_turn_routed"]
        self.assertEqual(len(bg_events), 1)
        self.assertEqual(bg_events[0]["data"]["privacy_classification"], "private")
        self.assertEqual(bg_events[0]["data"]["tier"], "local")

    async def test_17_background_provider_resolution_no_cloud_model_leak_and_unavailable_local(self):
        cloud = MockLLMProvider(
            model="cloud-ultra-70b",
            default_response="Cloud ok.",
            tier="cloud",
            supports_tools=True,
            provider_name="cloud_mock",
        )
        loc = MockLLMProvider(
            model="local-qwen-7b",
            default_response="Local bg ok.",
            tier="local",
            supports_tools=True,
            provider_name="local_custom",
        )
        engine, _, _ = _build_routed_engine(local_provider=loc, cloud_provider=cloud)

        async def dispatch_step(step, cancel_ev):
            if step.action == "agent_turn":
                return await engine.run_background_agent_turn(step.args, cancel_event=cancel_ev)
            return await engine.tools.execute(step.action, step.args)

        orch = TaskOrchestrator(InMemoryTaskRepository(), step_handler=dispatch_step)
        engine.task_orchestrator = orch

        # Promoting turn escalates to cloud ("cloud-ultra-70b"); background task MUST resolve local provider & local model
        await engine.process_text(
            "audit public docs in the background",
            session_id="bg-cloud-origin",
            allow_cloud_escalation=True,
            context_privacy=ContextPrivacyMetadata(explicit_sensitivity="public"),
        )
        tasks = orch.repo.list_tasks(conversation_id="bg-cloud-origin")
        self.assertEqual(len(tasks), 1)
        self.assertNotEqual(tasks[0].steps[0].args["model"], "cloud-ultra-70b")
        done = await orch.wait_for_task(tasks[0].id, timeout=2.0)
        self.assertEqual(done.status, TaskStatus.COMPLETED)
        self.assertEqual(len(cloud.calls), 0)
        self.assertEqual(len(loc.calls), 1)
        self.assertNotEqual(loc.calls[0]["model"], "cloud-ultra-70b")
        self.assertEqual(loc.calls[0]["model"], "local-qwen-7b")

        # Unavailable local provider -> background task fails cleanly with ProviderUnavailableError (never runs on cloud)
        reg_no_local = ProviderRegistry()
        reg_no_local.register_instance("cloud_only", cloud, default=True)
        engine_no_local = CreedEngine(provider_registry=reg_no_local, tools=ToolRegistry())
        orch_fail = TaskOrchestrator(
            InMemoryTaskRepository(),
            step_handler=lambda step, c: engine_no_local.run_background_agent_turn(step.args, cancel_event=c),
        )
        t_fail = orch_fail.submit_task(
            title="No local backend",
            steps=[{"name": "bg", "action": "agent_turn", "args": {"prompt": "audit", "session_id": "s-noloc"}}],
            conversation_id="s-noloc",
        )
        failed = await orch_fail.wait_for_task(t_fail.id, timeout=2.0)
        self.assertEqual(failed.status, TaskStatus.FAILED)
        err_low = (failed.error or "").lower()
        self.assertTrue("unavailable" in err_low or "unknown llm provider" in err_low)
        self.assertEqual(len(cloud.calls), 0)

    async def test_18_tool_fallback_safety_exceptions_partial_and_failed_responses(self):
        # Case A: Tool 1 produces side effect, Tool 2 raises exception -> MUST NOT replay on local
        side_effects = []
        tools_a = ToolRegistry()
        tools_a.register("t1_ok", "T1", {"type": "object", "properties": {}}, lambda: side_effects.append("t1") or "ok", side_effect="read_only")
        def raising_tool():
            side_effects.append("t2_raised")
            raise RuntimeError("Tool 2 crashed mid-batch")
        tools_a.register("t2_boom", "T2", {"type": "object", "properties": {}}, raising_tool, side_effect="read_only")

        class TwoToolCloud(MockLLMProvider):
            async def stream_turn(self, history, tools=None, model_override=None, cancel_event=None, timeout_s=None):
                self.calls.append({"model": model_override or self.model})
                if any(m["role"] == "tool" for m in history):
                    raise ProviderError("Cloud dropped after partial tool batch", provider=self.provider_name)
                yield {
                    "type": "tool_calls",
                    "calls": [
                        {"function": {"name": "t1_ok", "arguments": {}}},
                        {"function": {"name": "t2_boom", "arguments": {}}},
                    ],
                }

        cloud_a = TwoToolCloud(model="cloud-a", tier="cloud", supports_tools=True, provider_name="cloud_mock")
        engine_a, _, loc_a = _build_routed_engine(cloud_provider=cloud_a, tools=tools_a)
        await engine_a.process_text(
            "Explain and run two tools",
            session_id="fb-exc",
            history=[{"role": "system", "content": "sys"}],
            allow_cloud_escalation=True,
            context_privacy=ContextPrivacyMetadata(explicit_sensitivity="public"),
        )
        self.assertEqual(side_effects, ["t1", "t2_raised"])
        self.assertEqual(len(loc_a.calls), 0)

        # Case B: Tool returns failed response string, then cloud fails on pass 2 -> MUST NOT replay on local
        failed_tool_runs = []
        tools_b = ToolRegistry()
        tools_b.register("t_fail_resp", "TF", {"type": "object", "properties": {}}, lambda: failed_tool_runs.append("ran") or "Error: permission denied", side_effect="read_only")

        class FailedRespThenCloudError(MockLLMProvider):
            async def stream_turn(self, history, tools=None, model_override=None, cancel_event=None, timeout_s=None):
                self.calls.append({"model": model_override or self.model})
                if any(m["role"] == "tool" for m in history):
                    raise ProviderError("Cloud dropped after failed tool response", provider=self.provider_name)
                yield {"type": "tool_calls", "calls": [{"function": {"name": "t_fail_resp", "arguments": {}}}]}

        cloud_b = FailedRespThenCloudError(model="cloud-b", tier="cloud", supports_tools=True, provider_name="cloud_mock")
        engine_b, _, loc_b = _build_routed_engine(cloud_provider=cloud_b, tools=tools_b)
        await engine_b.process_text(
            "Explain and run failing tool",
            session_id="fb-failresp",
            history=[{"role": "system", "content": "sys"}],
            allow_cloud_escalation=True,
            context_privacy=ContextPrivacyMetadata(explicit_sensitivity="public"),
        )
        self.assertEqual(failed_tool_runs, ["ran"])
        self.assertEqual(len(loc_b.calls), 0)

    async def test_19_privacy_metadata_lifecycle_across_sqlite_persistence_and_recovery(self):
        import tempfile

        from core.ports.tasks import TaskStatus
        from infrastructure.sqlite_tasks import SQLiteTaskRepository

        cloud = MockLLMProvider(
            model="cloud-reasoner",
            default_response="Cloud should never run recovered task.",
            tier="cloud",
            supports_tools=True,
            provider_name="cloud_mock",
        )
        loc = MockLLMProvider(
            model="local-7b",
            default_response="Recovered locally.",
            tier="local",
            supports_tools=True,
            provider_name="local_custom",
        )

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "lifecycle.db"
            lock = threading.Lock()
            repo1 = SQLiteTaskRepository(str(db_path), lock)
            engine1, _, _ = _build_routed_engine(local_provider=loc, cloud_provider=cloud)
            orch1 = TaskOrchestrator(
                repo1,
                step_handler=lambda step, c: engine1.run_background_agent_turn(step.args, cancel_event=c),
            )
            engine1.task_orchestrator = orch1

            # Prevent orch1 from executing before simulated restart so task sits QUEUED in SQLite
            orch1.start_task = lambda *a, **kw: None

            await engine1.process_text(
                "audit ~/Documents/notes.txt in the background",
                session_id="sess-life",
                allow_cloud_escalation=True,
                allow_private_cloud=True,
                context_privacy=ContextPrivacyMetadata(has_local_files=True),
            )
            tasks = repo1.list_tasks(conversation_id="sess-life")
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].status, TaskStatus.QUEUED)

            stored_args = repo1.get_task(tasks[0].id).steps[0].args
            self.assertEqual(stored_args["privacy_classification"], "private")
            self.assertTrue(stored_args["privacy_flags"]["has_local_files"])
            self.assertNotIn("allow_private_cloud", stored_args)

            # Simulate restart with fresh engine/orchestrator recovering the persisted task from SQLite
            loc.calls.clear()
            cloud.calls.clear()
            engine2, _, _ = _build_routed_engine(local_provider=loc, cloud_provider=cloud)
            orch2 = TaskOrchestrator(
                SQLiteTaskRepository(str(db_path), lock),
                step_handler=lambda step, c: engine2.run_background_agent_turn(step.args, cancel_event=c),
            )
            engine2.task_orchestrator = orch2
            resumable = orch2.recover_on_startup()
            self.assertEqual([t.id for t in resumable], [tasks[0].id])
            done = await orch2.wait_for_task(tasks[0].id, timeout=2.0)
            self.assertEqual(done.status, TaskStatus.COMPLETED)
            self.assertEqual(len(cloud.calls), 0)
            self.assertEqual(len(loc.calls), 1)
            self.assertEqual(engine2._last_route["privacy_classification"], "private")
            self.assertEqual(engine2._last_route["tier"], "local")


if __name__ == "__main__":
    unittest.main()
