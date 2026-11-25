import asyncio
import os
import sys
import threading
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

for _mod_name in ("dotenv", "sounddevice", "faster_whisper", "pvporcupine", "groq", "httpx"):
    if _mod_name not in sys.modules:
        try:
            __import__(_mod_name)
        except ImportError:
            stub = types.ModuleType(_mod_name)
            if _mod_name == "dotenv":
                stub.load_dotenv = lambda *args, **kwargs: False
            elif _mod_name == "groq":
                class _DummyAsyncGroq:
                    def __init__(self, *args, **kwargs):
                        pass
                stub.AsyncGroq = _DummyAsyncGroq
            sys.modules[_mod_name] = stub

from core.engine import CreedEngine
from core.event_bus import event_bus
from core.tools import ToolRegistry
from intelligence.model_router import ModelRouter
from modules.base_ai import (
    MockLLMProvider,
    ProviderError,
    ProviderRegistry,
    ProviderUnavailableError,
)
from modules.cloud_disable import CloudModule
from modules.memory import InMemoryMemoryRepository
from modules.memory import Module as MemoryModule

try:
    import PySide6  # noqa: F401
    _HAS_PYSIDE6 = True
except ImportError:
    _HAS_PYSIDE6 = False


class _DummySTT:
    backend = "mock"
    recording = False
    def stop_listening(self): pass
    def start_listening(self, loop): pass


class _DummyTTS:
    backend = "mock"
    def speak(self, text, turn_id=""): pass
    def stop(self, turn_id=None): pass
    def is_speaking(self): return False
    def get_spoken_text(self, turn_id): return ""


class _DummyWake:
    def stop(self): pass
    def start(self): pass


class _DummySystem:
    def __init__(self):
        self.tools = []
    def register_tools(self, registry): pass
    def get_ollama_models(self): return ["qwen2.5:3b"]


class _FakeGroqStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        self._iter = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


def _make_chunk(content=None, tool_calls=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta)
    return SimpleNamespace(choices=[choice])


def _make_tc_delta(index=0, tc_id=None, name=None, arguments=None):
    fn = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=tc_id, function=fn)


class TestTranche44CloudToolsAndUI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._route_events = []
        async def _capture_route(payload):
            self._route_events.append(dict(payload or {}))
        self._capture_route = _capture_route
        event_bus.subscribe("route_update", self._capture_route)

    async def asyncTearDown(self):
        event_bus.unsubscribe("route_update", self._capture_route)

    def test_1_groq_model_tool_compatibility_registry(self):
        self.assertTrue(CloudModule.is_tool_calling_supported("llama-3.3-70b-versatile"))
        self.assertTrue(CloudModule.is_tool_calling_supported("llama-3.1-8b-instant"))
        self.assertTrue(CloudModule.is_tool_calling_supported("openai/gpt-oss-120b"))
        self.assertFalse(CloudModule.is_tool_calling_supported("whisper-large-v3"))
        self.assertFalse(CloudModule.is_tool_calling_supported("llama-guard-4-12b"))
        self.assertFalse(CloudModule.is_tool_calling_supported("unverified-model-x"))
        self.assertFalse(CloudModule.is_tool_calling_supported(""))

        router = ModelRouter()
        cloud_meta = [{
            "name": "groq",
            "tier": "cloud",
            "supports_tools": True,
            "default_model": "llama-3.1-8b-instant",
            "tool_capability_fn": CloudModule.is_tool_calling_supported,
        }]
        local_meta = [{
            "name": "local_custom",
            "tier": "local",
            "supports_tools": True,
            "default_model": "qwen2.5:3b",
        }]

        # Incompatible cloud model on tool-dependent turn must fall back to local
        decision_bad = router.route(
            "open Safari",
            ["qwen2.5:3b"],
            "qwen2.5:3b",
            selected_provider="groq",
            selected_model="whisper-large-v3",
            local_providers=local_meta,
            cloud_providers=cloud_meta,
            active_provider="local_custom",
        )
        self.assertEqual(decision_bad.tier, "local")
        self.assertEqual(decision_bad.provider, "local_custom")
        self.assertTrue(decision_bad.fallback_occurred)
        self.assertIn("lacks tool-calling", decision_bad.fallback_reason)

        # Compatible cloud model on tool-dependent public turn is allowed when manually selected
        decision_ok = router.route(
            "open Safari and check the news",
            ["qwen2.5:3b"],
            "qwen2.5:3b",
            selected_provider="groq",
            selected_model="llama-3.3-70b-versatile",
            local_providers=local_meta,
            cloud_providers=cloud_meta,
            active_provider="local_custom",
        )
        self.assertEqual(decision_ok.tier, "cloud")
        self.assertEqual(decision_ok.provider, "groq")
        self.assertEqual(decision_ok.model, "llama-3.3-70b-versatile")
        self.assertFalse(decision_ok.fallback_occurred)

        # ProviderRegistry.resolve_provider enforces model-level tool check
        reg = ProviderRegistry()
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=None)))
        reg.register_instance(
            "groq",
            CloudModule(model="llama-3.1-8b-instant", client=fake_client),
            tier="cloud",
            supports_tools=True,
        )
        with self.assertRaises(ProviderUnavailableError):
            reg.resolve_provider("groq", require_tools=True, model="whisper-large-v3")

    async def test_2_cloud_streaming_tool_assembly_multiple_calls_and_malformed_json(self):
        chunks = [
            _make_chunk(tool_calls=[
                _make_tc_delta(index=0, tc_id="call_a", name="get_", arguments='{"city":'),
                _make_tc_delta(index=1, tc_id="call_b", name="get_time", arguments=""),
            ]),
            _make_chunk(tool_calls=[
                _make_tc_delta(index=0, name="weather", arguments=' "Delhi"}'),
                _make_tc_delta(index=1, arguments='{"tz": "IST"}'),
            ]),
        ]
        captured_kwargs = {}

        async def _create(**kwargs):
            captured_kwargs.update(kwargs)
            return _FakeGroqStream(chunks)

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
        cloud = CloudModule(model="llama-3.3-70b-versatile", client=fake_client)

        events = []
        async for ev in cloud.stream_turn(
            [{"role": "user", "content": "Weather and time"}],
            tools=[{"type": "function", "function": {"name": "get_weather"}}],
        ):
            events.append(ev)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "tool_calls")
        self.assertEqual(len(events[0]["calls"]), 2)
        self.assertEqual(events[0]["calls"][0]["function"]["name"], "get_weather")
        self.assertEqual(events[0]["calls"][0]["function"]["arguments"], {"city": "Delhi"})
        self.assertEqual(events[0]["calls"][1]["function"]["name"], "get_time")
        self.assertEqual(events[0]["calls"][1]["function"]["arguments"], {"tz": "IST"})
        self.assertEqual(captured_kwargs.get("tool_choice"), "auto")

        # Verify OpenAI history normalization for follow-up tool results
        formatted = CloudModule._format_messages_for_openai([
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "get_time", "arguments": {"tz": "IST"}}}]},
            {"role": "tool", "content": "14:00"},
        ])
        self.assertEqual(formatted[1]["tool_calls"][0]["id"], "call_0")
        self.assertEqual(formatted[2]["tool_call_id"], "call_0")

        # Malformed JSON must raise ProviderError cleanly
        bad_chunks = [
            _make_chunk(tool_calls=[_make_tc_delta(index=0, tc_id="call_bad", name="get_time", arguments='{"tz": ')]),
        ]

        async def _create_bad(**kwargs):
            return _FakeGroqStream(bad_chunks)

        bad_cloud = CloudModule(
            model="llama-3.3-70b-versatile",
            client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create_bad))),
        )
        with self.assertRaises(ProviderError):
            async for _ in bad_cloud.stream_turn(
                [{"role": "user", "content": "time"}],
                tools=[{"type": "function", "function": {"name": "get_time"}}],
            ):
                pass

    async def test_3_cloud_tool_execution_preserves_authorization_and_approval_gates(self):
        executed = []
        tools = ToolRegistry()
        tools.register(
            "read_status",
            "Read safe status",
            {"type": "object", "properties": {}},
            lambda: (executed.append("read_status") or "OK_STATUS"),
            side_effect="read_only",
        )
        tools.register(
            "wipe_disk",
            "Dangerous write",
            {"type": "object", "properties": {}},
            lambda: (executed.append("wipe_disk") or "WIPED"),
            side_effect="system_control",
            requires_approval=True,
        )

        call_num = {"n": 0}

        async def _create(**kwargs):
            call_num["n"] += 1
            if call_num["n"] == 1:
                return _FakeGroqStream([
                    _make_chunk(tool_calls=[
                        _make_tc_delta(index=0, tc_id="c1", name="read_status", arguments="{}"),
                        _make_tc_delta(index=1, tc_id="c2", name="wipe_disk", arguments="{}"),
                    ])
                ])
            return _FakeGroqStream([_make_chunk(content="Status checked safely.")])

        cloud = CloudModule(
            model="llama-3.3-70b-versatile",
            client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create))),
        )
        local = MockLLMProvider(model="local-3b", provider_name="local_custom", tier="local")
        reg = ProviderRegistry()
        reg.register_instance("local_custom", local, default=True, tier="local", supports_tools=True)
        reg.register_instance("groq", cloud, tier="cloud", supports_tools=True)

        mem = MemoryModule(threading.Lock(), repository=InMemoryMemoryRepository(), legacy_json="__none__.json")
        engine = CreedEngine(
            tools=tools,
            memory=mem,
            provider_registry=reg,
        )

        history = []
        await engine.process_text(
            "Check status and run wipe",
            session_id="s-auth",
            history=history,
            selected_provider="groq",
            selected_model="llama-3.3-70b-versatile",
        )
        self.assertEqual(executed, ["read_status"])
        self.assertNotIn("wipe_disk", executed)
        self.assertEqual(history[-1]["content"], "Status checked safely.")

    async def test_4_cloud_tool_fallback_pre_stream_vs_post_tool_no_replay(self):
        executed = []
        tools = ToolRegistry()
        tools.register(
            "ping_tool",
            "Ping",
            {"type": "object", "properties": {}},
            lambda: (executed.append("ping") or "pong"),
            side_effect="read_only",
        )

        # Case A: Pre-stream failure falls back to local and executes tool once
        async def _fail_pre(**kwargs):
            raise RuntimeError("503 Service Unavailable")

        cloud_down = CloudModule(
            model="llama-3.3-70b-versatile",
            client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_fail_pre))),
        )
        local_ok = MockLLMProvider(
            model="local-3b",
            provider_name="local_custom",
            tier="local",
            default_response="Local handled it.",
        )
        reg_a = ProviderRegistry()
        reg_a.register_instance("local_custom", local_ok, default=True, tier="local", supports_tools=True)
        reg_a.register_instance("groq", cloud_down, tier="cloud", supports_tools=True)
        eng_a = CreedEngine(
            tools=tools,
            memory=MemoryModule(threading.Lock(), repository=InMemoryMemoryRepository(), legacy_json="__none__.json"),
            provider_registry=reg_a,
        )
        hist_a = []
        await eng_a.process_text(
            "Run ping tool",
            session_id="s-pre",
            history=hist_a,
            selected_provider="groq",
            selected_model="llama-3.3-70b-versatile",
        )
        self.assertEqual(eng_a._last_route["provider"], "local_custom")
        self.assertEqual(eng_a._last_route["routing_reason"], "cloud_unavailable_fallback")
        self.assertTrue(eng_a._last_route["fallback_occurred"])
        self.assertEqual(eng_a._last_route["status"], "fallback")

        # Case B: Failure AFTER tool execution must NOT replay to local
        turn_calls = {"n": 0}

        async def _fail_post_tool(**kwargs):
            turn_calls["n"] += 1
            if turn_calls["n"] == 1:
                return _FakeGroqStream([
                    _make_chunk(tool_calls=[_make_tc_delta(index=0, tc_id="c1", name="ping_tool", arguments="{}")])
                ])
            raise RuntimeError("Connection dropped after tool")

        cloud_post = CloudModule(
            model="llama-3.3-70b-versatile",
            client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_fail_post_tool))),
        )
        reg_b = ProviderRegistry()
        reg_b.register_instance("local_custom", local_ok, default=True, tier="local", supports_tools=True)
        reg_b.register_instance("groq", cloud_post, tier="cloud", supports_tools=True)
        eng_b = CreedEngine(
            tools=tools,
            memory=MemoryModule(threading.Lock(), repository=InMemoryMemoryRepository(), legacy_json="__none__.json"),
            provider_registry=reg_b,
        )
        await eng_b.process_text(
            "Run ping tool",
            session_id="s-post",
            history=[],
            selected_provider="groq",
            selected_model="llama-3.3-70b-versatile",
        )
        self.assertEqual(executed, ["ping"])
        self.assertEqual(len(local_ok.calls), 1)  # Only from Case A, never Case B
        self.assertEqual(eng_b._last_route["status"], "failed")

    async def test_5_confirmed_route_update_events_and_failure_reporting(self):
        local = MockLLMProvider(model="local-3b", provider_name="local_custom", tier="local")
        reg = ProviderRegistry()
        reg.register_instance("local_custom", local, default=True, tier="local", supports_tools=True)
        eng = CreedEngine(
            tools=ToolRegistry(),
            memory=MemoryModule(threading.Lock(), repository=InMemoryMemoryRepository(), legacy_json="__none__.json"),
            provider_registry=reg,
        )

        await eng.process_text("Hello", session_id="s-obs", history=[], allow_private_cloud=True)
        await asyncio.sleep(0.02)
        self.assertTrue(self._route_events)
        ev1 = self._route_events[-1]
        self.assertEqual(ev1["status"], "confirmed")
        self.assertEqual(ev1["provider"], "local_custom")
        self.assertTrue(ev1["cloud_consent"])

        # Subsequent turn without consent must show cloud_consent=False
        await eng.process_text("Hello again", session_id="s-obs", history=[])
        await asyncio.sleep(0.02)
        self.assertFalse(self._route_events[-1]["cloud_consent"])

        # Unavailable provider must emit failed route_update (never stale previous route)
        await eng.process_text("Hello", session_id="s-obs", history=[], selected_provider="missing_provider")
        await asyncio.sleep(0.02)
        ev_fail = self._route_events[-1]
        self.assertEqual(ev_fail["status"], "failed")
        self.assertEqual(ev_fail["provider"], "missing_provider")
        self.assertIn("unavailable", ev_fail["error"].lower())

    @unittest.skipUnless(_HAS_PYSIDE6, "PySide6 required for GUI test")
    def test_6_gui_cloud_consent_reset_and_routing_ui_sync(self):
        gui_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui")
        if gui_dir not in sys.path:
            sys.path.insert(0, gui_dir)
        from components.input_bar import InputBar
        from main_window import MacGlobalHotkey, MainWindow, WebSocketWorker
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)

        bar = InputBar(enable_cloud_consent=True)
        self.assertFalse(bar.is_cloud_consent_enabled())
        bar.cloud_consent_btn.setChecked(True)
        self.assertTrue(bar.is_cloud_consent_enabled())
        self.assertTrue(bar.consume_cloud_consent())
        self.assertFalse(bar.is_cloud_consent_enabled())

        with patch.object(WebSocketWorker, "start", return_value=None), patch.object(
            MacGlobalHotkey, "start", return_value=None
        ):
            win = MainWindow()
        try:
            # Consent defaults OFF and resets even if send_message raises
            win.input_bar.cloud_consent_btn.setChecked(True)
            def _boom(_msg):
                raise RuntimeError("socket closed")
            win.ws_worker.send_message = _boom
            with self.assertRaises(RuntimeError):
                win.handle_send("test private prompt")
            self.assertFalse(win.input_bar.is_cloud_consent_enabled())

            # Confirmed route update populates all 7 indicators
            win.on_route_update({
                "provider": "groq",
                "model": "llama-3.3-70b-versatile",
                "tier": "cloud",
                "routing_reason": "manual_override",
                "privacy_classification": "private",
                "cloud_consent": True,
                "fallback_occurred": False,
                "status": "confirmed",
            })
            self.assertIn("groq", win.route_provider_label.text())
            self.assertIn("llama-3.3-70b-versatile", win.route_model_label.text())
            self.assertIn("CLOUD", win.route_tier_label.text())
            self.assertIn("manual_override", win.route_reason_label.text())
            self.assertIn("PRIVATE", win.route_privacy_label.text())
            self.assertIn("ALLOWED", win.route_consent_label.text())
            self.assertIn("NONE", win.route_fallback_label.text())

            # Failed route clears stale success state
            win.on_route_update({
                "provider": "missing",
                "model": "--",
                "tier": "unknown",
                "routing_reason": "manual_override",
                "privacy_classification": "public",
                "cloud_consent": False,
                "fallback_occurred": False,
                "status": "failed",
                "error": "Selected provider 'missing' is unavailable.",
            })
            self.assertIn("Failed:", win.route_fallback_label.text())
            self.assertIn("OFF", win.route_consent_label.text())
        finally:
            win._clock_timer.stop()
            win._snapshot_timer.stop()
            win.global_hotkey.stop()
            win.ws_worker.stop()
            win.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
