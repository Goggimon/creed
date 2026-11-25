import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
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

from config.settings import config
from core.engine import CreedEngine
from core.ports.tasks import TaskRecord, TaskStatus, TaskStep
from core.tasks import InMemoryTaskRepository, TaskOrchestrator
from core.tools import ToolRegistry
from intelligence.model_router import ModelRouter
from modules.base_ai import MockLLMProvider, ProviderRegistry
from modules.memory import InMemoryMemoryRepository
from modules.memory import Module as MemoryModule

try:
    from fastapi.testclient import TestClient  # noqa: F401
    _HAS_FASTAPI = True
except Exception:
    _HAS_FASTAPI = False

try:
    import PySide6  # noqa: F401
    _HAS_PYSIDE6 = True
except ImportError:
    _HAS_PYSIDE6 = False


class TestTranche45ControlsAndHygiene(unittest.IsolatedAsyncioTestCase):
    async def test_1_local_selection_never_escalates_and_mid_convo_cloud_checks_privacy(self):
        router = ModelRouter()
        local_meta = [{"name": "local_custom", "tier": "local", "supports_tools": True, "default_model": "qwen2.5:3b"}]
        cloud_meta = [{"name": "groq", "tier": "cloud", "supports_tools": True, "default_model": "llama-3.3-70b-versatile"}]

        # Local selection must stay local even with allow_cloud_escalation=True and allow_private_cloud=True
        dec_local = router.route(
            "Analyze the complete architecture of distributed systems",
            ["qwen2.5:3b"],
            "qwen2.5:3b",
            allow_cloud_escalation=True,
            allow_private_cloud=True,
            selected_provider="local_custom",
            selected_model="qwen2.5:3b",
            local_providers=local_meta,
            cloud_providers=cloud_meta,
            active_provider="local_custom",
        )
        self.assertEqual(dec_local.tier, "local")
        self.assertEqual(dec_local.provider, "local_custom")
        self.assertEqual(dec_local.routing_reason, "manual_override")

        # Mid-conversation switch to cloud treats prior conversation history as private
        cloud = MockLLMProvider(model="llama-3.3-70b-versatile", provider_name="groq", tier="cloud")
        local = MockLLMProvider(model="qwen2.5:3b", provider_name="local_custom", tier="local")
        reg = ProviderRegistry()
        reg.register_instance("local_custom", local, default=True, tier="local", supports_tools=True)
        reg.register_instance("groq", cloud, tier="cloud", supports_tools=True)

        engine = CreedEngine(
            provider_registry=reg,
            memory=MemoryModule(threading.Lock(), repository=InMemoryMemoryRepository(), legacy_json="__none__.json"),
            tools=ToolRegistry(),
        )
        history = []
        await engine.process_text("Hello locally", session_id="s-mid", history=history)
        self.assertEqual(len(local.calls), 1)
        self.assertEqual(len(cloud.calls), 0)

        # Switching to cloud mid-conversation without allow_private_cloud=True is blocked by local_on_private
        await engine.process_text(
            "Now summarize what we discussed",
            session_id="s-mid",
            history=history,
            selected_provider="groq",
            selected_model="llama-3.3-70b-versatile",
            allow_private_cloud=False,
        )
        self.assertEqual(len(cloud.calls), 0)
        self.assertEqual(engine._last_route["tier"], "local")
        self.assertEqual(engine._last_route["routing_reason"], "privacy_restriction")

    def test_2_snapshot_dormant_isolation_and_provider_catalog(self):
        local = MockLLMProvider(model="qwen2.5:3b", provider_name="local_custom", tier="local")
        cloud = MockLLMProvider(model="llama-3.3-70b-versatile", provider_name="groq", tier="cloud")
        reg = ProviderRegistry()
        reg.register_instance("local_custom", local, default=True, tier="local", supports_tools=True)
        reg.register_instance("groq", cloud, tier="cloud", supports_tools=True)

        engine = CreedEngine(
            provider_registry=reg,
            memory=MemoryModule(threading.Lock(), repository=InMemoryMemoryRepository(), legacy_json="__none__.json"),
            tools=ToolRegistry(),
        )
        snap = engine.get_system_snapshot()
        for forbidden in ("jee_model", "pyq_vault", "svg_templates", "jee_flashcards", "jee_tests", "vspotify_available", "vspotify_commands"):
            self.assertNotIn(forbidden, snap)
        self.assertIn("provider_catalog", snap)
        self.assertEqual(snap["provider_catalog"]["local"][0]["name"], "local_custom")
        self.assertEqual(snap["provider_catalog"]["cloud"][0]["name"], "groq")
        self.assertIn("allow_cloud_escalation", snap["config"])
        self.assertIn("cloud_privacy_mode", snap["config"])

    def test_3_engine_shutdown_closes_sqlite_repositories(self):
        closed = []

        class _ClosableRepo(InMemoryMemoryRepository):
            def close(self):
                closed.append("memory")

        class _ClosableTaskRepo(InMemoryTaskRepository):
            def close(self):
                closed.append("tasks")

        mem = MemoryModule(threading.Lock(), repository=_ClosableRepo(), legacy_json="__none__.json")
        orch = TaskOrchestrator(_ClosableTaskRepo(), step_handler=lambda s, c: "ok")
        orch.repo.create_task(
            TaskRecord(
                id="t-close",
                conversation_id="default",
                title="t",
                status=TaskStatus.COMPLETED,
                steps=[TaskStep(step_index=0, name="s", action="a")],
            )
        )
        local = MockLLMProvider(model="qwen2.5:3b", provider_name="local_custom", tier="local")
        reg = ProviderRegistry()
        reg.register_instance("local_custom", local, default=True, tier="local", supports_tools=True)

        engine = CreedEngine(provider_registry=reg, memory=mem, task_orchestrator=orch, tools=ToolRegistry())
        engine.shutdown()
        self.assertEqual(closed, ["memory", "tasks"])

    @unittest.skipUnless(_HAS_FASTAPI, "FastAPI TestClient required")
    def test_4_settings_atomic_persistence_validation_and_rollback(self):
        import api.server as srv

        orig_base = srv.BASE_DIR
        orig_cfg = (
            config.ollama_model,
            config.allow_cloud_escalation,
            config.cloud_privacy_mode,
            config.cloud_model,
            srv.engine.ai.model,
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            env_file.write_text(
                "# Keep this comment\nGROQ_API_KEY=gsk_keep_me\nOLLAMA_MODEL=qwen2.5:7b\n",
                encoding="utf-8",
            )
            srv.BASE_DIR = tmp_path
            try:
                client = TestClient(srv.app)

                # Valid update preserves unrelated keys/comments and updates live config
                r_ok = client.post(
                    "/api/settings",
                    json={
                        "ollama_model": "qwen3:8b",
                        "allow_cloud_escalation": True,
                        "cloud_privacy_mode": "local_on_private",
                        "cloud_model": "llama-3.3-70b-versatile",
                    },
                )
                self.assertEqual(r_ok.status_code, 200)
                self.assertTrue(config.allow_cloud_escalation)
                self.assertEqual(config.ollama_model, "qwen3:8b")
                written = env_file.read_text(encoding="utf-8")
                self.assertIn("# Keep this comment", written)
                self.assertIn("GROQ_API_KEY=gsk_keep_me", written)
                self.assertIn("CREED_ALLOW_CLOUD_ESCALATION=true", written)

                # Invalid payload returns 422 and leaves config untouched
                r_bad = client.post("/api/settings", json={"cloud_privacy_mode": "invalid_mode"})
                self.assertEqual(r_bad.status_code, 422)
                self.assertEqual(config.cloud_privacy_mode, "local_on_private")

                # Failed write returns 500 and must NOT mutate live config
                with patch.object(srv, "_write_env_atomic", side_effect=OSError("disk full")):
                    r_fail = client.post(
                        "/api/settings",
                        json={"allow_cloud_escalation": False, "ollama_model": "should_not_apply"},
                    )
                self.assertEqual(r_fail.status_code, 500)
                self.assertTrue(config.allow_cloud_escalation)
                self.assertEqual(config.ollama_model, "qwen3:8b")
            finally:
                srv.BASE_DIR = orig_base
                (
                    config.ollama_model,
                    config.allow_cloud_escalation,
                    config.cloud_privacy_mode,
                    config.cloud_model,
                    srv.engine.ai.model,
                ) = orig_cfg

    @unittest.skipUnless(_HAS_PYSIDE6, "PySide6 required for GUI test")
    def test_5_gui_routing_controls_settings_feedback_and_clean_shutdown(self):
        gui_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui")
        if gui_dir not in sys.path:
            sys.path.insert(0, gui_dir)
        from components.input_bar import InputBar
        from main_window import MacGlobalHotkey, MainWindow, WebSocketWorker
        from PySide6.QtGui import QCloseEvent
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)

        bar = InputBar(enable_cloud_consent=True)
        bar.update_routing_options(
            {
                "local": [{"name": "ollama", "tier": "local", "supports_tools": True, "default_model": "qwen2.5:3b"}],
                "cloud": [{"name": "groq", "tier": "cloud", "supports_tools": True, "default_model": "llama-3.3-70b-versatile"}],
            },
            [{"name": "qwen2.5:3b"}],
            cloud_model="llama-3.3-70b-versatile",
        )
        idx_groq = bar.provider_combo.findData("groq")
        self.assertGreaterEqual(idx_groq, 0)
        bar.provider_combo.setCurrentIndex(idx_groq)
        sel_p, _ = bar.get_routing_selection()
        self.assertEqual(sel_p, "groq")

        with patch.object(WebSocketWorker, "start", return_value=None), patch.object(
            MacGlobalHotkey, "start", return_value=None
        ):
            win = MainWindow()

        sent_msgs = []
        win.ws_worker.send_message = lambda m: sent_msgs.append(m)
        win.input_bar.update_routing_options(
            {"local": [{"name": "ollama", "tier": "local", "supports_tools": True, "default_model": "qwen2.5:3b"}], "cloud": []},
            [{"name": "qwen2.5:3b"}],
        )
        win.input_bar.provider_combo.setCurrentIndex(win.input_bar.provider_combo.findData("ollama"))
        win.input_bar.cloud_consent_btn.setChecked(True)
        win.handle_send("run local check")
        self.assertEqual(sent_msgs[-1]["provider"], "ollama")
        self.assertTrue(sent_msgs[-1]["allow_private_cloud"])
        self.assertFalse(win.input_bar.is_cloud_consent_enabled())

        # Settings error feedback must not claim saved
        win._on_api_error("save_settings", "HTTP 500: disk full")
        self.assertIn("Save failed:", win.settings_tab.status_label.text())
        win._on_api_response("save_settings", {"status": "saved"})
        self.assertIn("Saved to .env", win.settings_tab.status_label.text())

        # Deterministic closeEvent with bounded worker shutdown (must NOT call os._exit)
        fake_worker = SimpleNamespace(
            wait=lambda ms: False,
            isRunning=lambda: True,
            terminate=lambda: None,
        )
        win._active_api_workers.append(fake_worker)
        with patch("os._exit", side_effect=AssertionError("os._exit must not be called")):
            ev = QCloseEvent()
            win.closeEvent(ev)
            self.assertTrue(ev.isAccepted())
            self.assertTrue(win._shutting_down)
        win.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
