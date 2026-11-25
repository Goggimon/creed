# api/server.py

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse

from config.settings import BASE_DIR, config
from core.event_bus import event_bus
from core.router import build_creed_engine

engine = build_creed_engine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    engine.initialize(loop)
    try:
        yield
    finally:
        engine.shutdown()


app = FastAPI(lifespan=lifespan)



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


async def on_task_update(payload):
    await manager.broadcast({"type": "task_update", "payload": payload})


async def on_route_update(payload):
    await manager.broadcast({"type": "route_update", "payload": payload})


event_bus.subscribe("status_change", on_status_change)
event_bus.subscribe("llm_token", on_llm_token)
event_bus.subscribe("llm_done", on_llm_done)
event_bus.subscribe("speech_transcribed", on_speech_transcribed)
event_bus.subscribe("error", on_error)
event_bus.subscribe("activity", on_activity)
event_bus.subscribe("tool_event", on_tool_event)
event_bus.subscribe("node_pulse", on_node_pulse)
event_bus.subscribe("voice_level", on_voice_level)
event_bus.subscribe("task_update", on_task_update)
event_bus.subscribe("route_update", on_route_update)


@app.get("/")
def health_check():
    return {"status": "CREED backend online", "version": config.version}


@app.get("/visualizer")
def serve_visualizer():
    return FileResponse(Path(BASE_DIR) / "gui" / "web" / "visualizer.html")


@app.get("/api/snapshot")
def get_snapshot():
    return engine.get_system_snapshot()


@app.get("/api/metrics")
def get_metrics():
    from monitoring.latency_tracker import latency_tracker

    summary = latency_tracker.get_summary()
    summary["active_tts_backend"] = engine.tts.backend
    summary["active_llm_provider"] = getattr(engine.ai, "provider_name", "unknown")
    return summary


@app.get("/api/diagnostics/logs")
def get_diagnostic_logs(turn_id: str = "", limit: int = 40):
    from utils.logger import get_recent_events

    return {
        "turn_id": turn_id,
        "events": get_recent_events(turn_id=turn_id, limit=limit),
    }


# -------- TASK & APPROVAL API (Tranche 5.1) --------
from typing import Literal, Optional
from pydantic import BaseModel, Field
from core.ports.tasks import (
    ApprovalConflictError,
    ApprovalExpiredError,
    ApprovalInvalidatedError,
    TaskNotFoundError,
    TaskRecoveryError,
    TaskStateError,
    TaskStatus,
)


class TaskStepModel(BaseModel):
    step_index: int
    name: str
    action: str
    args: dict = Field(default_factory=dict)
    requires_approval: bool = False
    outcome: str
    result: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 0
    max_attempts: int = 1
    updated_at: str = ""


class TaskResponse(BaseModel):
    id: str
    conversation_id: str
    title: str
    status: str
    current_step_index: int
    steps: list[TaskStepModel]
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None


class TaskListResponse(BaseModel):
    conversation_id: str
    tasks: list[TaskResponse]


class TaskEventModel(BaseModel):
    id: Optional[int] = None
    task_id: str
    event_type: str
    status: str
    step_index: Optional[int] = None
    message: str
    data: dict = Field(default_factory=dict)
    timestamp: str


class TaskEventsPageResponse(BaseModel):
    task_id: str
    items: list[TaskEventModel]
    total: int
    offset: int
    limit: int
    has_more: bool


class TaskStepCreateRequest(BaseModel):
    name: str
    action: str
    args: dict = Field(default_factory=dict)
    requires_approval: bool = False


class TaskCreateRequest(BaseModel):
    title: str
    conversation_id: str = "default"
    steps: list[TaskStepCreateRequest]
    timeout_s: Optional[float] = None


class TaskActionResponse(BaseModel):
    status: str
    task: TaskResponse


class ApprovalResponse(BaseModel):
    id: str
    task_id: str
    step_index: int
    action: str
    args: dict = Field(default_factory=dict)
    action_summary: str
    action_payload_hash: str
    reason: str
    status: str
    created_at: str
    expires_at: Optional[str] = None
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None


class ApprovalListResponse(BaseModel):
    conversation_id: str
    approvals: list[ApprovalResponse]


class ApprovalResolveRequest(BaseModel):
    decision: Literal["approve", "reject", "mark_completed"]
    resolved_by: str = "user"


class ApprovalResolveResponse(BaseModel):
    status: str
    resolution: str
    approval: ApprovalResponse


def _require_orchestrator():
    orch = getattr(engine, "task_orchestrator", None)
    if orch is None:
        raise HTTPException(status_code=503, detail="Task orchestrator unavailable.")
    return orch


def _to_task_response(task) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        conversation_id=task.conversation_id,
        title=task.title,
        status=task.status.value,
        current_step_index=task.current_step_index,
        steps=[
            TaskStepModel(
                step_index=s.step_index,
                name=s.name,
                action=s.action,
                args=dict(s.args),
                requires_approval=s.requires_approval,
                outcome=s.outcome.value,
                result=s.result,
                error=s.error,
                attempts=s.attempts,
                max_attempts=s.max_attempts,
                updated_at=s.updated_at,
            )
            for s in task.steps
        ],
        created_at=task.created_at,
        updated_at=task.updated_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        error=task.error,
    )


def _to_approval_response(apr) -> ApprovalResponse:
    return ApprovalResponse(
        id=apr.id,
        task_id=apr.task_id,
        step_index=apr.step_index,
        action=apr.action,
        args=dict(apr.args),
        action_summary=apr.action_summary,
        action_payload_hash=apr.action_payload_hash,
        reason=apr.reason,
        status=apr.status,
        created_at=apr.created_at,
        expires_at=apr.expires_at,
        resolved_at=apr.resolved_at,
        resolved_by=apr.resolved_by,
    )


def _get_scoped_task(orch, task_id: str, conversation_id: str):
    task = orch.repo.get_task(task_id)
    if not task or task.conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@app.get("/api/tasks", response_model=TaskListResponse)
def list_tasks(conversation_id: str = "default", status: str = "", limit: int = 50):
    orch = _require_orchestrator()
    statuses = None
    if status.strip():
        try:
            statuses = [TaskStatus(status.strip())]
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid task status: {status}")
    tasks = orch.repo.list_tasks(
        conversation_id=conversation_id,
        statuses=statuses,
        limit=max(1, min(200, limit)),
    )
    return TaskListResponse(
        conversation_id=conversation_id,
        tasks=[_to_task_response(t) for t in tasks],
    )


@app.post("/api/tasks", response_model=TaskActionResponse)
def create_task(payload: TaskCreateRequest):
    orch = _require_orchestrator()
    if not payload.title.strip() or not payload.steps:
        raise HTTPException(status_code=400, detail="Task title and steps are required.")
    try:
        task = orch.submit_task(
            title=payload.title.strip(),
            steps=[s.model_dump() for s in payload.steps],
            conversation_id=payload.conversation_id,
            timeout_s=payload.timeout_s,
        )
        return TaskActionResponse(status="ok", task=_to_task_response(task))
    except TaskRecoveryError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, conversation_id: str = "default"):
    orch = _require_orchestrator()
    task = _get_scoped_task(orch, task_id, conversation_id)
    return _to_task_response(task)


@app.get("/api/tasks/{task_id}/events", response_model=TaskEventsPageResponse)
def get_task_events(task_id: str, conversation_id: str = "default", offset: int = 0, limit: int = 50):
    orch = _require_orchestrator()
    _get_scoped_task(orch, task_id, conversation_id)
    safe_offset = max(0, offset)
    safe_limit = max(1, min(200, limit))
    items, total = orch.repo.get_events_page(task_id, offset=safe_offset, limit=safe_limit)
    return TaskEventsPageResponse(
        task_id=task_id,
        items=[
            TaskEventModel(
                id=e.id,
                task_id=e.task_id,
                event_type=e.event_type,
                status=e.status,
                step_index=e.step_index,
                message=e.message,
                data=dict(e.data),
                timestamp=e.timestamp,
            )
            for e in items
        ],
        total=total,
        offset=safe_offset,
        limit=safe_limit,
        has_more=(safe_offset + len(items)) < total,
    )


@app.post("/api/tasks/{task_id}/pause", response_model=TaskActionResponse)
def pause_task(task_id: str, conversation_id: str = "default"):
    orch = _require_orchestrator()
    _get_scoped_task(orch, task_id, conversation_id)
    try:
        updated = orch.pause_task(task_id)
        return TaskActionResponse(status="ok", task=_to_task_response(updated))
    except TaskStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/tasks/{task_id}/resume", response_model=TaskActionResponse)
def resume_task(task_id: str, conversation_id: str = "default"):
    orch = _require_orchestrator()
    _get_scoped_task(orch, task_id, conversation_id)
    try:
        updated = orch.resume_task(task_id)
        return TaskActionResponse(status="ok", task=_to_task_response(updated))
    except TaskStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/tasks/{task_id}/cancel", response_model=TaskActionResponse)
def cancel_task(task_id: str, conversation_id: str = "default"):
    orch = _require_orchestrator()
    _get_scoped_task(orch, task_id, conversation_id)
    try:
        updated = orch.cancel_task(task_id)
        return TaskActionResponse(status="ok", task=_to_task_response(updated))
    except TaskStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/approvals", response_model=ApprovalListResponse)
def list_pending_approvals(conversation_id: str = "default"):
    orch = _require_orchestrator()
    items = orch.repo.list_pending_approvals(conversation_id=conversation_id)
    return ApprovalListResponse(
        conversation_id=conversation_id,
        approvals=[_to_approval_response(a) for a in items],
    )


@app.post("/api/approvals/{approval_id}/resolve", response_model=ApprovalResolveResponse)
def resolve_approval(
    approval_id: str,
    payload: ApprovalResolveRequest,
    conversation_id: str = "default",
):
    orch = _require_orchestrator()
    existing = orch.repo.get_approval(approval_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Approval not found.")
    _get_scoped_task(orch, existing.task_id, conversation_id)

    try:
        if payload.decision == "reject":
            apr = orch.reject_and_cancel(approval_id, resolved_by=payload.resolved_by)
            return ApprovalResolveResponse(
                status="ok",
                resolution="rejected",
                approval=_to_approval_response(apr),
            )
        mark_done = payload.decision == "mark_completed"
        apr = orch.approve_and_resume(
            approval_id,
            resolved_by=payload.resolved_by,
            mark_uncertain_completed=mark_done,
        )
        return ApprovalResolveResponse(
            status="ok",
            resolution="marked_completed" if mark_done else "approved_for_execution",
            approval=_to_approval_response(apr),
        )
    except (ApprovalConflictError, ApprovalExpiredError, ApprovalInvalidatedError, TaskStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


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


def _parse_bool_setting(raw) -> bool:
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("true", "1", "yes", "on"):
        return True
    if s in ("false", "0", "no", "off"):
        return False
    raise HTTPException(status_code=422, detail=f"Invalid boolean setting value: {raw!r}")


def _write_env_atomic(env_path: Path, updates: dict[str, str]) -> None:
    import tempfile

    orig_lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    remaining = dict(updates)
    new_lines: list[str] = []
    for line in orig_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            k, _ = line.split("=", 1)
            key = k.strip()
            if key in remaining:
                new_lines.append(f"{key}={remaining.pop(key)}")
                continue
        new_lines.append(line)
    for key, val in remaining.items():
        new_lines.append(f"{key}={val}")

    content = "\n".join(new_lines) + ("\n" if new_lines else "")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".env.tmp.", dir=str(env_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, env_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


@app.post("/api/settings")
def update_settings(payload: dict):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Settings payload must be a JSON object.")

    mapping = {
        "ollama_model": "OLLAMA_MODEL",
        "ollama_endpoint": "OLLAMA_ENDPOINT",
        "local_provider": "CREED_LOCAL_PROVIDER",
        "cloud_provider": "CREED_CLOUD_PROVIDER",
        "cloud_model": "CREED_CLOUD_MODEL",
        "allow_cloud_escalation": "CREED_ALLOW_CLOUD_ESCALATION",
        "cloud_privacy_mode": "CREED_CLOUD_PRIVACY_MODE",
        "macos_tts_voice": "CREED_MACOS_VOICE",
        "macos_tts_rate": "CREED_TTS_RATE",
        "phone_adb_target": "CREED_PHONE_ADB_TARGET",
    }

    staged_env: dict[str, str] = {}
    staged_cfg: dict[str, object] = {}

    for key, env_key in mapping.items():
        if key not in payload:
            continue
        raw_val = payload[key]
        if key == "allow_cloud_escalation":
            bval = _parse_bool_setting(raw_val)
            staged_cfg[key] = bval
            staged_env[env_key] = "true" if bval else "false"
        elif key == "cloud_privacy_mode":
            sval = str(raw_val).strip().lower()
            if sval not in ("local_on_private", "allow_cloud"):
                raise HTTPException(
                    status_code=422,
                    detail="cloud_privacy_mode must be 'local_on_private' or 'allow_cloud'.",
                )
            staged_cfg[key] = sval
            staged_env[env_key] = sval
        elif key == "macos_tts_rate":
            try:
                ival = int(str(raw_val).strip())
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="macos_tts_rate must be an integer.") from exc
            if not (50 <= ival <= 500):
                raise HTTPException(status_code=422, detail="macos_tts_rate must be between 50 and 500.")
            staged_cfg[key] = ival
            staged_env[env_key] = str(ival)
        elif key == "phone_adb_target":
            sval = str(raw_val).strip()
            staged_cfg[key] = sval
            staged_env[env_key] = sval
        else:
            sval = str(raw_val).strip()
            if not sval:
                raise HTTPException(status_code=422, detail=f"{key} cannot be empty.")
            staged_cfg[key] = sval
            staged_env[env_key] = sval

    env_path = Path(BASE_DIR) / ".env"
    if staged_env:
        try:
            _write_env_atomic(env_path, staged_env)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to persist settings to .env: {exc}") from exc

    for key, val in staged_cfg.items():
        setattr(config, key, val)

    if "ollama_model" in staged_cfg:
        engine.ai.model = str(staged_cfg["ollama_model"])
    if "ollama_endpoint" in staged_cfg:
        engine.ai.endpoint = str(staged_cfg["ollama_endpoint"])

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
                    engine.process_text(
                        text,
                        session_id=session_id,
                        mode=mode,
                        allow_private_cloud=bool(data.get("allow_private_cloud", False)),
                        selected_provider=data.get("provider"),
                        selected_model=data.get("model"),
                    )
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
