# core/engine.py

import asyncio
import logging
import shutil
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from config.settings import config
from core.event_bus import event_bus
from core.router import IntentRouter
from core.tools import ToolRegistry
from core.voice.stt import STTEngine
from core.voice.wake import WakeWordDetector
from modules.ai import Module as LocalAI
from modules.tts import TTSModule

logger = logging.getLogger("CreedEngine")

SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "You are CREED, a sharp, multi-system AI agent running on the user's Mac. "
        "You can control the Mac (apps, volume, clipboard, notifications), Bluetooth speakers, "
        "the user's Android phone via ADB/scrcpy, and persistent SQLite memory using your tools. "
        "When the user asks you to perform a system or device action, call the appropriate tool(s) first, "
        "then report the real result concisely in 1–4 short sentences unless detail is requested."
    ),
}


class CreedEngine:
    def __init__(self):
        self.router = IntentRouter()
        self.tools = ToolRegistry()
        self.running = False
        self.start_time = time.monotonic()
        self.sessions = {"default": [SYSTEM_PROMPT.copy()]}
        self.history = self.sessions["default"]
        self.context = {}
        self.lock = threading.Lock()
        self._reminder_task = None
        self._cancel_generation = False

        self.activity_log = deque(maxlen=50)
        self.tool_history = deque(maxlen=30)

        # Core Modules
        self.ai = LocalAI()
        self.tts = TTSModule()
        self.stt = STTEngine(event_bus)

        # Wake Word Detector (uses Porcupine if key set, else local Whisper for 'creed')
        self.wake = WakeWordDetector(
            access_key=config.porcupine_access_key,
            keyword=config.wake_keyword,
            event_bus=event_bus,
            stt_engine=self.stt,
        )

        self.modules = {}
        self.load_modules()
        self._record_activity("CORE", "CreedEngine initialized")

    def _record_activity(self, node: str, message: str):
        entry = {
            "node": node,
            "message": message,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        }
        self.activity_log.appendleft(entry)
        return entry

    async def _emit_activity(self, node: str, message: str):
        entry = self._record_activity(node, message)
        await event_bus.publish("activity", entry)
        await event_bus.publish("node_pulse", node)

    def stop_all(self):
        """Cancel active LLM streaming, TTS playback, and STT listening."""
        self._cancel_generation = True
        self.tts.stop()
        self.stt.stop_listening()

    def get_history(self, session_id: str = "default") -> list:
        if session_id not in self.sessions:
            msgs = [SYSTEM_PROMPT.copy()]
            memory_mod = self.modules.get("memory")
            if memory_mod:
                for m in memory_mod.get_messages(session_id, limit=20):
                    msgs.append({"role": m["role"], "content": m["content"]})
            self.sessions[session_id] = msgs
        return self.sessions[session_id]

    def initialize(self, loop):
        """Initialize async worker threads, event subscriptions, and wake word loops."""
        self.tts.start_worker(loop)
        self.wake.set_loop(loop)

        event_bus.subscribe("wake_word_detected", self._on_wake_word)
        event_bus.subscribe("speech_transcribed", self._on_speech_transcribed)
        event_bus.subscribe("status_change", self._on_status_change)

        def handle_wake():
            logger.info("Wake word callback triggered in detector thread")
            asyncio.run_coroutine_threadsafe(
                event_bus.publish("wake_word_detected"), loop
            )

        self.wake.on_detect = handle_wake
        self.wake.start()

        if self._reminder_task is None:
            self._reminder_task = loop.create_task(self._reminder_loop())

        logger.info("CreedEngine fully initialized.")

    def shutdown(self):
        self.running = False
        if self._reminder_task:
            self._reminder_task.cancel()
            self._reminder_task = None
        self.tts.stop()
        self.stt.stop_listening()
        self.wake.close()

    def get_system_snapshot(self) -> dict:
        from modules.bt_audio import IOBluetooth, _parse_bt_devices
        from modules.phone_adb import _find_tool

        bt_devices = _parse_bt_devices()
        connected_bt = [d["name"] for d in bt_devices if d.get("connected")]

        adb_bin = _find_tool("adb")
        adb_state = "Standby (Disconnected)"
        if adb_bin:
            try:
                proc = subprocess.run(
                    [adb_bin, "devices"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                lines = [
                    l for l in proc.stdout.splitlines()[1:] if l.strip() and "device" in l
                ]
                if lines:
                    adb_state = f"Connected ({len(lines)} device)"
            except Exception:
                adb_state = "Standby"
        else:
            adb_state = "Not Installed"

        memory_mod = self.modules.get("memory")
        notes = memory_mod.list_notes() if memory_mod else []
        reminders = memory_mod.list_reminders() if memory_mod else []

        return {
            "version": config.version,
            "model": self.ai.model,
            "uptime_seconds": int(time.monotonic() - self.start_time),
            "voice": {
                "wake_word": (
                    f"Active ({self.wake.mode})"
                    if self.wake.mode != "disabled"
                    else "Disabled"
                ),
                "wake_keyword": self.wake.keyword,
                "stt_backend": self.stt.backend or "loading",
                "stt_model": self.stt.model_size,
                "tts_backend": self.tts.backend,
                "tts_voice": config.macos_tts_voice,
                "recording": self.stt.recording,
                "speaking": self.tts.is_speaking(),
            },
            "systems": [
                {
                    "id": "mac",
                    "name": "macOS Host",
                    "description": "Local Apple Silicon control (apps, clipboard, battery/uptime).",
                    "state": "Online",
                    "detail": "Native open / pbcopy / pmset",
                },
                {
                    "id": "bluetooth",
                    "name": "Bluetooth & Audio",
                    "description": "Paired speaker management and macOS audio output routing.",
                    "state": "Online" if IOBluetooth is not None else "Limited (Read-Only)",
                    "detail": (
                        f"{len(connected_bt)} connected / {len(bt_devices)} paired"
                        if bt_devices
                        else "No paired speakers"
                    ),
                },
                {
                    "id": "phone",
                    "name": "Android Phone (ADB)",
                    "description": "Wireless ADB control and scrcpy screen mirroring.",
                    "state": "Online" if adb_state.startswith("Connected") else "Standby",
                    "detail": adb_state,
                },
                {
                    "id": "llm",
                    "name": "Local LLM (Ollama)",
                    "description": "Primary reasoning and tool-calling engine.",
                    "state": "Configured",
                    "detail": f"{self.ai.model} @ {self.ai.endpoint}",
                },
            ],
            "tools": [
                {
                    "name": s["function"]["name"],
                    "description": s["function"]["description"],
                    "parameters": s["function"]["parameters"],
                }
                for s in self.tools.get_ollama_schemas()
            ],
            "tool_history": list(self.tool_history),
            "memory": {
                "notes": notes,
                "reminders": reminders,
            },
            "conversations": memory_mod.list_conversations() if memory_mod else [],
            "workflows": memory_mod.list_workflows() if memory_mod else [],
            "chat_history": memory_mod.get_messages("default", limit=50) if memory_mod else [],
            "activity": list(self.activity_log),
            "config": {
                "ollama_model": self.ai.model,
                "ollama_endpoint": self.ai.endpoint,
                "macos_tts_voice": config.macos_tts_voice,
                "macos_tts_rate": config.macos_tts_rate,
                "phone_adb_target": config.phone_adb_target,
                "porcupine_configured": bool(config.porcupine_access_key),
            },
        }

    async def run_workflow(self, workflow_id: int = None, name: str = None) -> dict:
        memory_mod = self.modules.get("memory")
        if not memory_mod:
            return {"status": "error", "message": "Memory module unavailable."}

        wf = memory_mod.get_workflow(workflow_id=workflow_id, name=name)
        if not wf:
            return {"status": "error", "message": "Workflow not found."}

        await self._emit_activity("AUTOMATION", f"Running workflow: {wf['name']}")
        results = []
        for step in wf.get("steps", []):
            tool_name = step.get("tool", "")
            tool_args = step.get("args", {})
            res = await self.tools.execute(tool_name, tool_args)
            self.tool_history.appendleft(
                {
                    "name": tool_name,
                    "args": tool_args,
                    "result": res[:300],
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                }
            )
            results.append({"tool": tool_name, "result": res})

        await self._emit_activity("AUTOMATION", f"Completed: {wf['name']}")
        return {"status": "ok", "workflow": wf["name"], "results": results}

    async def _reminder_loop(self):
        while True:
            try:
                await asyncio.sleep(10)
                memory_module = self.modules.get("memory")
                if memory_module:
                    triggered = memory_module.check_reminders()
                    for reminder in triggered:
                        msg = f"Reminder: {reminder['message']}"
                        await self._emit_activity("AUTOMATION", msg)
                        await event_bus.publish("llm_token", msg)
                        await event_bus.publish("llm_done")
                        self.tts.speak(msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in reminder loop: {e}")

    async def _on_wake_word(self):
        logger.info("[Engine] Received wake_word_detected event")
        await self._emit_activity("VOICE", "Wake word detected")
        await self.handle_wake_event()

    async def handle_wake_event(self):
        self.wake.stop()
        self.tts.stop()
        self.stt.start_listening(asyncio.get_running_loop())
        await event_bus.publish("status_change", "Listening")

    async def _on_speech_transcribed(self, text: str):
        logger.info(f"[Engine] Received speech_transcribed event: '{text}'")
        await self._emit_activity("VOICE", f"Transcribed: {text[:40]}")
        await self.process_text(text)

    def _on_status_change(self, state: str):
        if state == "Idle":
            if not self.wake._running and not self.stt.recording:
                logger.debug("[Engine] System Idle. Ensuring wake word detector is active.")
                self.wake.start()

    async def process_text(self, text: str, session_id: str = "default", history=None):
        if not text or not text.strip():
            return

        if history is None:
            history = self.get_history(session_id)

        self.wake.stop()
        self.stt.stop_listening()
        self.tts.stop()

        await event_bus.publish("status_change", "Processing")
        await self._emit_activity("CONVERSATION", f"Prompt: {text[:45]}")
        logger.info(f"Processing input [{session_id}]: '{text}'")

        # 1. Fast intent router for exact built-in shortcuts
        intent, module = self.router.dispatch(text)
        if module:
            logger.info(f"Routed intent '{intent}' to module '{module.name}'")
            try:
                response = module.handle(intent, text, self.context)
                if response:
                    node = "MEMORY" if module.name == "memory" else "SYSTEMS"
                    await self._emit_activity(node, f"Handled '{intent}'")
                    await event_bus.publish("llm_token", response)
                    await event_bus.publish("llm_done")
                    self.tts.speak(response)
                    return
            except Exception as e:
                logger.error(f"Error executing module '{module.name}': {e}")

        # 2. Check memories for RAG injection
        memory_module = self.modules.get("memory")
        context_memories = ""
        if memory_module:
            try:
                memories = memory_module.retrieve_relevant(text)
                if memories:
                    context_memories = "\n".join(f"- {m['note']}" for m in memories)
                    await self._emit_activity("MEMORY", f"Retrieved {len(memories)} note(s)")
            except Exception as e:
                logger.error(f"Error retrieving memories: {e}")

        history.append({"role": "user", "content": text})
        if memory_module:
            memory_module.save_message(session_id, "user", text)

        temp_history = history.copy()
        if context_memories:
            latest_msg = temp_history[-1]["content"]
            temp_history[-1] = {
                "role": "user",
                "content": (
                    f"[Context memories to help answer the user]\n"
                    f"{context_memories}\n"
                    f"[End of memories]\n\n"
                    f"User: {latest_msg}"
                ),
            }

        # 3. Multi-step Tool-Calling Agent Loop (Ollama)
        self._cancel_generation = False
        tool_schemas = self.tools.get_ollama_schemas()
        spoken_buffer = ""
        final_assistant_text = ""

        try:
            for _ in range(config.max_tool_iterations):
                if self._cancel_generation:
                    break

                turn_text = ""
                turn_tool_calls = []

                async for event in self.ai.stream_turn(temp_history, tools=tool_schemas):
                    if self._cancel_generation:
                        logger.info("LLM streaming cancelled by user.")
                        break

                    if event["type"] == "token":
                        token = event["text"]
                        turn_text += token
                        final_assistant_text += token
                        await event_bus.publish("llm_token", token)

                        spoken_buffer += token
                        if (
                            spoken_buffer.strip().endswith((".", "?", "!"))
                            and not self._cancel_generation
                        ):
                            self.tts.speak(spoken_buffer.strip())
                            spoken_buffer = ""

                    elif event["type"] == "tool_calls":
                        turn_tool_calls.extend(event["calls"])

                if self._cancel_generation:
                    break

                if turn_tool_calls:
                    temp_history.append(
                        {
                            "role": "assistant",
                            "content": turn_text,
                            "tool_calls": turn_tool_calls,
                        }
                    )

                    for call in turn_tool_calls:
                        fn = call.get("function", {})
                        tool_name = fn.get("name", "")
                        tool_args = fn.get("arguments", {})

                        await self._emit_activity("TOOLS", f"Running {tool_name}")
                        await event_bus.publish(
                            "tool_event",
                            {"name": tool_name, "status": "running", "args": tool_args},
                        )

                        result = await self.tools.execute(tool_name, tool_args)
                        record = {
                            "name": tool_name,
                            "args": tool_args,
                            "result": result[:300],
                            "timestamp": datetime.now().strftime("%H:%M:%S"),
                        }
                        self.tool_history.appendleft(record)
                        await event_bus.publish(
                            "tool_event",
                            {"name": tool_name, "status": "done", "result": result[:300]},
                        )
                        temp_history.append({"role": "tool", "content": result})
                    continue

                break

            if spoken_buffer.strip() and not self._cancel_generation:
                self.tts.speak(spoken_buffer.strip())

            if final_assistant_text:
                history.append({"role": "assistant", "content": final_assistant_text})
                if memory_module:
                    memory_module.save_message(session_id, "assistant", final_assistant_text)
            await event_bus.publish("llm_done")

        except Exception as e:
            logger.error(f"Error in stream_turn: {e}")
            await event_bus.publish("error", str(e))
            await event_bus.publish("status_change", "Idle")
            return

        if self._cancel_generation or not self.tts.is_speaking():
            await event_bus.publish("status_change", "Idle")

    async def stream_response(self, text: str, session_id: str = "default", history=None):
        """Legacy generator route compatibility for non-WebSocket fallbacks."""
        if history is None:
            history = self.get_history(session_id)

        history.append({"role": "user", "content": text})
        full_response = ""
        try:
            async for token in self.ai.stream_chat(history):
                full_response += token
                yield token
            history.append({"role": "assistant", "content": full_response})
        except Exception as e:
            yield f"\n[Error] {str(e)}"

    async def run(self):
        """CLI loop (runs in asyncio)."""
        print("\n[Creed] Ready (CLI mode).\n")
        self.running = True
        self.initialize(asyncio.get_running_loop())

        while self.running:
            try:
                user_input = await asyncio.get_running_loop().run_in_executor(
                    None, input, "> "
                )
            except (KeyboardInterrupt, EOFError):
                break

            if user_input.strip().lower() == "exit":
                self.shutdown()
                print("Creed shutting down.")
                break

            await self.process_text(user_input)

    def load_modules(self):
        from modules.memory import Module as MemoryModule, register_tools as register_memory_tools
        from modules.system import Module as SystemModule
        from modules.mac_control import register_tools as register_mac_tools
        from modules.bt_audio import register_tools as register_bt_tools
        from modules.phone_adb import register_tools as register_phone_tools

        memory = MemoryModule(self.lock)
        system = SystemModule(self.lock)

        self.modules["memory"] = memory
        self.modules["system"] = system

        for module in self.modules.values():
            for intent in getattr(module, "intents", []):
                self.router.register(intent, module)

        register_mac_tools(self.tools)
        register_bt_tools(self.tools)
        register_phone_tools(self.tools)
        register_memory_tools(self.tools, memory)

        async def _run_workflow_tool(name: str) -> str:
            res = await self.run_workflow(name=name)
            if res.get("status") != "ok":
                return res.get("message", "Workflow failed.")
            summary = "; ".join(f"{r['tool']}: {r['result']}" for r in res.get("results", []))
            return f"Executed '{res['workflow']}': {summary}"

        self.tools.register(
            name="run_workflow",
            description="Execute a saved multi-step CREED automation workflow by name (e.g., Study Mode, System Health Check, Phone Sync).",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Workflow name"}
                },
                "required": ["name"],
            },
            handler=_run_workflow_tool,
        )

        logger.info(
            f"[+] Modules loaded: {', '.join(self.modules.keys())} | "
            f"Tools registered: {len(self.tools.get_ollama_schemas())}"
        )
