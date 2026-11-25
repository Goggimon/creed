from __future__ import annotations

import difflib
import re
import threading
from pathlib import Path


class IntentRouter:
    def __init__(self):
        self.routes = {}

    def register(self, keyword, module):
        self.routes[keyword.lower()] = module

    def dispatch(self, text):
        text_lower = text.lower().strip()
        if not text_lower:
            return None, None

        for keyword, module in self.routes.items():
            if re.search(rf"\b{re.escape(keyword)}\b", text_lower):
                return keyword, module

        words = re.findall(r"\b\w+\b", text_lower)
        for word in words:
            if len(word) < 3:
                continue
            close = difflib.get_close_matches(
                word, self.routes.keys(), n=1, cutoff=0.8
            )
            if close:
                return close[0], self.routes[close[0]]

        return None, None


def build_creed_engine(
    provider_registry=None,
    ai_provider=None,
    tts=None,
    stt=None,
    wake=None,
    memory=None,
    system_monitor=None,
    task_orchestrator=None,
):
    """
    Single Application Composition Root.
    Wires concrete voice, LLM, memory, task-orchestration, tool, and hardware-monitor implementations
    into CreedEngine via dependency injection.
    """
    from config.settings import config
    from core.engine import CreedEngine
    from core.event_bus import event_bus
    from core.plugins import PluginManager
    from core.tasks import TaskOrchestrator
    from core.tools import ToolRegistry
    from core.voice.stt import STTEngine
    from core.voice.wake import WakeWordDetector
    from infrastructure.sqlite_memory import SQLiteMemoryRepository
    from infrastructure.sqlite_tasks import SQLiteTaskRepository
    from modules.base_ai import ProviderRegistry
    from modules.bt_audio import register_tools as register_bt_tools
    from modules.mac_control import register_tools as register_mac_tools
    from modules.memory import Module as MemoryModule, register_tools as register_memory_tools
    from modules.phone_adb import register_tools as register_phone_tools
    from modules.system import Module as SystemModule, SystemMonitor
    from modules.tts import TTSModule

    lock = threading.Lock()
    router = IntentRouter()
    tools = ToolRegistry()

    reg = provider_registry or ProviderRegistry.create_default()
    resolved_stt = stt if stt is not None else STTEngine(event_bus)
    resolved_tts = tts if tts is not None else TTSModule()
    resolved_wake = (
        wake
        if wake is not None
        else WakeWordDetector(
            access_key=config.porcupine_access_key,
            keyword=config.wake_keyword,
            event_bus=event_bus,
            stt_engine=resolved_stt,
        )
    )
    if memory is not None:
        resolved_memory = memory
    else:
        repo = SQLiteMemoryRepository(config.db_file, lock)
        resolved_memory = MemoryModule(lock, repository=repo, legacy_json=config.data_file)
    system_mod = SystemModule(lock)
    resolved_monitor = system_monitor if system_monitor is not None else SystemMonitor()

    if task_orchestrator is not None:
        resolved_tasks = task_orchestrator
    else:
        task_repo = SQLiteTaskRepository(config.db_file, lock)

        async def _dispatch_task_step(step, cancel_event):
            if step.action == "agent_turn":
                return await engine.run_background_agent_turn(step.args, cancel_event=cancel_event)
            return await tools.execute(step.action, step.args)

        resolved_tasks = TaskOrchestrator(
            task_repo,
            step_handler=_dispatch_task_step,
            authorizer=lambda step: tools.authorize(step.action, step.args),
        )

    for mod in (resolved_memory, system_mod):
        for intent in getattr(mod, "intents", []):
            router.register(intent, mod)

    register_mac_tools(tools)
    register_bt_tools(tools)
    register_phone_tools(tools)
    register_memory_tools(tools, resolved_memory)

    trusted_from_env = [p.strip() for p in config.trusted_plugins.split(",") if p.strip()]
    plugin_manager = PluginManager(
        plugins_dir=config.plugins_dir,
        registry=tools,
        trusted_plugins=trusted_from_env,
        enabled_plugins=trusted_from_env,
        trust_file=Path(config.plugins_dir) / "plugins_trust.json",
    )
    plugin_manager.activate_trusted()

    engine = CreedEngine(
        provider_registry=reg,
        ai_provider=ai_provider,
        tts=resolved_tts,
        stt=resolved_stt,
        wake=resolved_wake,
        memory=resolved_memory,
        system_monitor=resolved_monitor,
        router=router,
        tools=tools,
        lock=lock,
        extra_modules={"system": system_mod},
        task_orchestrator=resolved_tasks,
        plugin_manager=plugin_manager,
    )

    async def _run_workflow_tool(name: str) -> str:
        res = await engine.run_workflow(name=name)
        if res.get("status") != "ok":
            return res.get("message", "Workflow failed.")
        summary = "; ".join(f"{r['tool']}: {r['result']}" for r in res.get("results", []))
        return f"Executed '{res['workflow']}': {summary}"

    tools.register(
        name="run_workflow",
        description="Execute a saved multi-step CREED automation workflow by name (e.g., Study Mode, System Health Check, Phone Sync).",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Workflow name"}},
            "required": ["name"],
        },
        handler=_run_workflow_tool,
        capabilities=["workflow_exec"],
        side_effect="system_control",
    )
    return engine
