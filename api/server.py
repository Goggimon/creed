# api/server.py

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from config.settings import BASE_DIR, config
from core.engine import CreedEngine
from core.event_bus import event_bus

engine = CreedEngine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    engine.initialize(loop)
    try:
        yield
    finally:
        engine.shutdown()


app = FastAPI(lifespan=lifespan)

vspotify_path = Path(config.vspotify_dir)
if vspotify_path.exists():
    app.mount("/vspotify", StaticFiles(directory=str(vspotify_path), html=True), name="vspotify")


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

        state = "Idle"
        if engine.stt.recording:
            state = "Recording"
        elif engine.tts.is_speaking():
            state = "Speaking"
        await websocket.send_json({"type": "status", "state": state})

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)


manager = ConnectionManager()


async def on_status_change(state):
    await manager.broadcast({"type": "status", "state": state})


async def on_llm_token(token):
    await manager.broadcast({"type": "token", "text": token})


async def on_llm_done():
    await manager.broadcast({"type": "done"})


async def on_speech_transcribed(text):
    await manager.broadcast({"type": "user_transcription", "text": text})


async def on_error(msg):
    await manager.broadcast({"type": "error", "message": msg})


async def on_activity(entry):
    await manager.broadcast({"type": "activity", "entry": entry})


async def on_tool_event(event):
    await manager.broadcast({"type": "tool_event", "event": event})


async def on_node_pulse(node):
    await manager.broadcast({"type": "node_pulse", "node": node})


async def on_voice_level(level):
    await manager.broadcast({"type": "voice_level", "level": level})


async def on_vspotify_command(payload):
    await manager.broadcast({"type": "vspotify_command", "payload": payload})


event_bus.subscribe("status_change", on_status_change)
event_bus.subscribe("llm_token", on_llm_token)
event_bus.subscribe("llm_done", on_llm_done)
event_bus.subscribe("speech_transcribed", on_speech_transcribed)
event_bus.subscribe("error", on_error)
event_bus.subscribe("activity", on_activity)
event_bus.subscribe("tool_event", on_tool_event)
event_bus.subscribe("node_pulse", on_node_pulse)
event_bus.subscribe("voice_level", on_voice_level)
event_bus.subscribe("vspotify_command", on_vspotify_command)


@app.get("/")
def health_check():
    return {"status": "CREED backend online", "version": config.version}


@app.get("/visualizer")
def serve_visualizer():
    return FileResponse(Path(BASE_DIR) / "gui" / "web" / "visualizer.html")


@app.get("/api/snapshot")
def get_snapshot():
    return engine.get_system_snapshot()


@app.post("/api/memory/note")
def add_memory_note(payload: dict):
    tag = (payload.get("tag") or "general").strip()
    note = (payload.get("note") or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail="Note content is required.")
    memory_mod = engine.modules.get("memory")
    if not memory_mod:
        raise HTTPException(status_code=500, detail="Memory module unavailable.")
    created = memory_mod.add_note(tag, note)
    return {"status": "ok", "note": created}


@app.delete("/api/memory/note/{note_id}")
def delete_memory_note(note_id: int):
    memory_mod = engine.modules.get("memory")
    if not memory_mod:
        raise HTTPException(status_code=500, detail="Memory module unavailable.")
    deleted = memory_mod.delete_note_by_id(note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found.")
    return {"status": "ok"}


@app.post("/api/conversations")
def create_conversation(payload: dict = None):
    title = ((payload or {}).get("title") or "New Conversation").strip()
    memory_mod = engine.modules.get("memory")
    if not memory_mod:
        raise HTTPException(status_code=500, detail="Memory module unavailable.")
    convo = memory_mod.create_conversation(title=title)
    return {"status": "ok", "conversation": convo}


@app.get("/api/conversations/{session_id}")
def get_conversation_messages(session_id: str):
    memory_mod = engine.modules.get("memory")
    if not memory_mod:
        raise HTTPException(status_code=500, detail="Memory module unavailable.")
    return {
        "session_id": session_id,
        "messages": memory_mod.get_messages(session_id, limit=100),
    }


@app.delete("/api/conversations/{session_id}")
def delete_conversation(session_id: str):
    memory_mod = engine.modules.get("memory")
    if not memory_mod:
        raise HTTPException(status_code=500, detail="Memory module unavailable.")
    engine.sessions.pop(session_id, None)
    memory_mod.delete_conversation(session_id)
    return {"status": "ok"}


@app.post("/api/workflows")
def create_workflow(payload: dict):
    name = (payload.get("name") or "").strip()
    description = (payload.get("description") or "").strip()
    steps = payload.get("steps") or []
    if not name or not isinstance(steps, list) or not steps:
        raise HTTPException(status_code=400, detail="Workflow name and steps are required.")
    memory_mod = engine.modules.get("memory")
    if not memory_mod:
        raise HTTPException(status_code=500, detail="Memory module unavailable.")
    try:
        wf = memory_mod.create_workflow(name, description or f"Custom workflow: {name}", steps)
        return {"status": "ok", "workflow": wf}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: int):
    res = await engine.run_workflow(workflow_id=workflow_id)
    if res.get("status") != "ok":
        raise HTTPException(status_code=404, detail=res.get("message", "Workflow not found."))
    return res


@app.delete("/api/workflows/{workflow_id}")
def delete_workflow(workflow_id: int):
    memory_mod = engine.modules.get("memory")
    if not memory_mod:
        raise HTTPException(status_code=500, detail="Memory module unavailable.")
    if not memory_mod.delete_workflow(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return {"status": "ok"}


@app.post("/api/settings")
def update_settings(payload: dict):
    env_path = Path(BASE_DIR) / ".env"
    existing = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()

    mapping = {
        "ollama_model": "OLLAMA_MODEL",
        "jee_tutor_model": "JEE_TUTOR_MODEL",
        "ollama_endpoint": "OLLAMA_ENDPOINT",
        "macos_tts_voice": "CREED_MACOS_VOICE",
        "macos_tts_rate": "CREED_TTS_RATE",
        "phone_adb_target": "CREED_PHONE_ADB_TARGET",
    }
    for key, env_key in mapping.items():
        if key in payload:
            val = str(payload[key]).strip()
            existing[env_key] = val
            if key == "macos_tts_rate":
                try:
                    config.macos_tts_rate = int(val)
                except ValueError:
                    pass
            else:
                setattr(config, key, val)

    if "ollama_model" in payload:
        engine.ai.model = config.ollama_model
    if "ollama_endpoint" in payload:
        engine.ai.endpoint = config.ollama_endpoint

    lines = [f"{k}={v}" for k, v in existing.items()]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"status": "saved", "config": engine.get_system_snapshot()["config"]}


@app.post("/api/models/select")
async def select_model(payload: dict):
    model = (payload.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="Model name is required.")
    update_settings({"ollama_model": model})
    await engine._emit_activity("LLM", f"Active model set to {model}")
    return {"status": "ok", "model": model}


@app.post("/api/models/pull")
async def pull_model(payload: dict):
    model = (payload.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="Model name is required.")
    if engine.model_pull_status.get("active"):
        raise HTTPException(
            status_code=409,
            detail=f"Already pulling {engine.model_pull_status.get('model')}.",
        )
    asyncio.create_task(engine.pull_ollama_model(model))
    return {"status": "started", "model": model}


@app.post("/api/models/delete")
async def delete_model(payload: dict):
    model = (payload.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="Model name is required.")
    if model == engine.ai.model:
        raise HTTPException(status_code=400, detail="Cannot delete the currently active model.")
    try:
        return await engine.delete_ollama_model(model)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vspotify/command")
async def vspotify_command(payload: dict):
    from modules.vspotify import dispatch_vspotify_command

    action = (payload.get("action") or "").strip()
    params = payload.get("params") or {}
    if not action:
        raise HTTPException(status_code=400, detail="Action is required.")
    msg = await dispatch_vspotify_command(action, params)
    return {"status": "ok", "message": msg}


@app.post("/api/jee/flashcards")
def add_jee_flashcard(payload: dict):
    memory_mod = engine.modules.get("memory")
    if not memory_mod:
        raise HTTPException(status_code=500, detail="Memory module unavailable.")
    front = (payload.get("front") or "").strip()
    back = (payload.get("back") or "").strip()
    if not front or not back:
        raise HTTPException(status_code=400, detail="Front and back are required.")
    card = memory_mod.add_flashcard(
        payload.get("subject", "Physics"),
        payload.get("chapter", "General"),
        front,
        back,
    )
    return {"status": "ok", "card": card}


@app.post("/api/jee/flashcards/{card_id}/toggle")
def toggle_jee_flashcard(card_id: int):
    memory_mod = engine.modules.get("memory")
    if not memory_mod:
        raise HTTPException(status_code=500, detail="Memory module unavailable.")
    if not memory_mod.toggle_flashcard_mastery(card_id):
        raise HTTPException(status_code=404, detail="Flashcard not found.")
    return {"status": "ok"}


@app.delete("/api/jee/flashcards/{card_id}")
def delete_jee_flashcard(card_id: int):
    memory_mod = engine.modules.get("memory")
    if not memory_mod:
        raise HTTPException(status_code=500, detail="Memory module unavailable.")
    if not memory_mod.delete_flashcard(card_id):
        raise HTTPException(status_code=404, detail="Flashcard not found.")
    return {"status": "ok"}


@app.post("/api/jee/test/generate")
async def generate_jee_test(payload: dict):
    from modules.jee_tutor import generate_jee_quiz, pick_reasoning_model

    subject = (payload.get("subject") or "Physics").strip()
    chapter = (payload.get("chapter") or "").strip()
    difficulty = (payload.get("difficulty") or "JEE Main").strip()
    count = max(1, min(15, int(payload.get("count") or 5)))
    model = pick_reasoning_model(engine.installed_model_names)
    try:
        questions = await generate_jee_quiz(subject, chapter, difficulty, count, model)
        return {"status": "ok", "model": model, "questions": questions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/jee/test/submit")
def submit_jee_test(payload: dict):
    memory_mod = engine.modules.get("memory")
    if not memory_mod:
        raise HTTPException(status_code=500, detail="Memory module unavailable.")
    saved = memory_mod.save_jee_test(
        payload.get("subject", "Mixed"),
        payload.get("difficulty", "JEE Main"),
        int(payload.get("score", 0)),
        int(payload.get("total", 0)),
    )
    return {"status": "ok", "test": saved}


@app.post("/chat")
async def chat(payload: dict):
    """Legacy HTTP endpoint for compatibility."""
    message = payload.get("message", "")
    session_id = payload.get("session_id", "default")

    async def generator():
        async for token in engine.stream_response(message, session_id=session_id):
            yield token

    return StreamingResponse(
        generator(),
        media_type="text/plain; charset=utf-8",
        headers={"Transfer-Encoding": "chunked"},
    )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            session_id = data.get("session_id") or "default"
            mode = data.get("mode") or "default"

            if msg_type == "chat":
                text = data.get("text", "")
                asyncio.create_task(
                    engine.process_text(text, session_id=session_id, mode=mode)
                )
            elif msg_type == "stop":
                engine.stop_all()
                await event_bus.publish("status_change", "Idle")
            elif msg_type == "voice_toggle":
                if engine.stt.recording:
                    engine.stt.stop_listening()
                    await event_bus.publish("status_change", "Idle")
                else:
                    engine.wake.stop()
                    engine.tts.stop()
                    engine.stt.start_listening(asyncio.get_running_loop())
                    await event_bus.publish("status_change", "Listening")

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
