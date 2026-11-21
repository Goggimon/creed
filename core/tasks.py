from __future__ import annotations

import asyncio
import copy
import inspect
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Union

from core.event_bus import event_bus
from core.ports.tasks import (
    ApprovalConflictError,
    ApprovalExpiredError,
    ApprovalInvalidatedError,
    ApprovalRequest,
    RetryPolicy,
    StepOutcome,
    TaskError,
    TaskEvent,
    TaskLeaseLostError,
    TaskNotFoundError,
    TaskRecord,
    TaskRecoveryError,
    TaskRepository,
    TaskStateError,
    TaskStatus,
    TaskStep,
    compute_action_payload_hash,
)
from core.policy import AuthorizationDecision
from core.tools import UncertainCancellationError
from utils.logger import correlation_scope, log_event

StepHandler = Callable[[TaskStep, asyncio.Event], Union[Any, Awaitable[Any]]]
StepAuthorizer = Callable[[TaskStep], AuthorizationDecision]


def _emit_task_update(task_id: str, conversation_id: str, status: str, event_type: str) -> None:
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            loop.create_task(
                event_bus.publish(
                    "task_update",
                    {
                        "task_id": task_id,
                        "conversation_id": conversation_id,
                        "status": status,
                        "event_type": event_type,
                    },
                )
            )
    except RuntimeError:
        pass


class InMemoryTaskRepository:
    """Thread-safe in-memory TaskRepository for headless tests."""

    def __init__(self):
        self._lock = threading.RLock()
        self._tasks: dict[str, TaskRecord] = {}
        self._events: list[TaskEvent] = []
        self._event_seq = 0
        self._approvals: dict[str, ApprovalRequest] = {}

    def initialize(self) -> None:
        pass

    def create_task(self, task: TaskRecord) -> TaskRecord:
        with self._lock:
            now = datetime.now().isoformat()
            task.created_at = task.created_at or now
            task.updated_at = task.updated_at or now
            self._tasks[task.id] = copy.deepcopy(task)
            return copy.deepcopy(task)

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            t = self._tasks.get(task_id)
            return copy.deepcopy(t) if t else None

    def list_tasks(
        self,
        conversation_id: str | None = None,
        statuses: list[TaskStatus] | None = None,
        limit: int = 50,
    ) -> list[TaskRecord]:
        with self._lock:
            items = list(self._tasks.values())
            if conversation_id is not None:
                items = [t for t in items if t.conversation_id == conversation_id]
            if statuses:
                allowed = set(statuses)
                items = [t for t in items if t.status in allowed]
            items.sort(key=lambda t: t.created_at, reverse=True)
            return [copy.deepcopy(t) for t in items[:limit]]

    def update_task(self, task: TaskRecord) -> None:
        with self._lock:
            existing = self._tasks.get(task.id)
            if not existing:
                raise TaskNotFoundError(f"Task '{task.id}' not found")
            if task.owner_id is not None and existing.owner_id is not None and existing.owner_id != task.owner_id:
                raise TaskLeaseLostError(
                    f"Task '{task.id}' lease lost to '{existing.owner_id}' (stale worker '{task.owner_id}')"
                )
            task.updated_at = datetime.now().isoformat()
            self._tasks[task.id] = copy.deepcopy(task)

    def claim_task(self, task_id: str, owner_id: str, lease_ttl_s: float = 30.0) -> bool:
        with self._lock:
            t = self._tasks.get(task_id)
            if not t or t.status not in (TaskStatus.QUEUED, TaskStatus.RUNNING):
                return False
            now_dt = datetime.now()
            if (
                t.owner_id is not None
                and t.owner_id != owner_id
                and t.lease_expires_at is not None
                and datetime.fromisoformat(t.lease_expires_at) > now_dt
            ):
                return False
            t.owner_id = owner_id
            t.lease_expires_at = (now_dt + timedelta(seconds=lease_ttl_s)).isoformat()
            t.updated_at = now_dt.isoformat()
            return True

    def release_claim(self, task_id: str, owner_id: str) -> None:
        with self._lock:
            t = self._tasks.get(task_id)
            if t and t.owner_id == owner_id:
                t.owner_id = None
                t.lease_expires_at = None
                t.updated_at = datetime.now().isoformat()

    def save_checkpoint(self, task_id: str, step: TaskStep, current_step_index: int) -> None:
        with self._lock:
            t = self._tasks.get(task_id)
            if not t:
                raise TaskNotFoundError(f"Task '{task_id}' not found")
            now = datetime.now().isoformat()
            step.updated_at = now
            t.steps[step.step_index] = copy.deepcopy(step)
            t.current_step_index = current_step_index
            t.updated_at = now

    def append_event(self, event: TaskEvent) -> TaskEvent:
        with self._lock:
            self._event_seq += 1
            event.id = self._event_seq
            event.timestamp = event.timestamp or datetime.now().isoformat()
            self._events.append(copy.deepcopy(event))
            return copy.deepcopy(event)

    def get_events(self, task_id: str) -> list[TaskEvent]:
        with self._lock:
            return [copy.deepcopy(e) for e in self._events if e.task_id == task_id]

    def get_events_page(self, task_id: str, offset: int = 0, limit: int = 50) -> tuple[list[TaskEvent], int]:
        with self._lock:
            all_ev = [copy.deepcopy(e) for e in self._events if e.task_id == task_id]
            return all_ev[offset : offset + limit], len(all_ev)

    def create_approval(self, approval: ApprovalRequest) -> ApprovalRequest:
        with self._lock:
            self._approvals[approval.id] = copy.deepcopy(approval)
            return copy.deepcopy(approval)

    def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        with self._lock:
            a = self._approvals.get(approval_id)
            return copy.deepcopy(a) if a else None

    def list_pending_approvals(
        self,
        task_id: str | None = None,
        conversation_id: str | None = None,
    ) -> list[ApprovalRequest]:
        with self._lock:
            out = []
            for a in self._approvals.values():
                if a.status != "pending":
                    continue
                if task_id is not None and a.task_id != task_id:
                    continue
                if conversation_id is not None:
                    t = self._tasks.get(a.task_id)
                    if not t or t.conversation_id != conversation_id:
                        continue
                out.append(copy.deepcopy(a))
            out.sort(key=lambda a: a.created_at)
            return out

    def resolve_approval(self, approval_id: str, status: str, resolved_by: str = "user") -> ApprovalRequest:
        with self._lock:
            a = self._approvals.get(approval_id)
            if not a:
                raise TaskNotFoundError(f"Approval '{approval_id}' not found")
            if a.status != "pending":
                raise ApprovalConflictError(f"Approval '{approval_id}' already resolved with status '{a.status}'")
            if a.expires_at and datetime.now() > datetime.fromisoformat(a.expires_at):
                a.status = "expired"
                a.resolved_at = datetime.now().isoformat()
                a.resolved_by = "system"
                raise ApprovalExpiredError(f"Approval '{approval_id}' expired at {a.expires_at}")
            a.status = status
            a.resolved_at = datetime.now().isoformat()
            a.resolved_by = resolved_by
            return copy.deepcopy(a)

    def invalidate_approval(self, approval_id: str, reason: str = "payload_changed") -> None:
        with self._lock:
            a = self._approvals.get(approval_id)
            if a:
                a.status = "invalidated"
                a.resolved_at = datetime.now().isoformat()
                a.resolved_by = reason


class CheckpointManager:
    """Persists explicit step-boundary state: not_started -> uncertain (pre-exec) -> completed/failed."""

    def __init__(self, repo: TaskRepository):
        self.repo = repo

    def mark_step_started(self, task: TaskRecord, step: TaskStep) -> None:
        """Persist UNCERTAIN before executing side effects so crash recovery never blindly duplicates."""
        step.outcome = StepOutcome.UNCERTAIN
        step.attempts += 1
        step.error = None
        self.repo.save_checkpoint(task.id, step, task.current_step_index)
        self.repo.append_event(
            TaskEvent(
                id=None,
                task_id=task.id,
                event_type="step_started",
                status=task.status.value,
                step_index=step.step_index,
                message=f"Started step '{step.name}' (attempt {step.attempts}/{step.max_attempts}).",
                data={"action": step.action, "outcome": step.outcome.value, "attempt": step.attempts},
            )
        )

    def mark_step_completed(self, task: TaskRecord, step: TaskStep, result: Any) -> None:
        step.outcome = StepOutcome.COMPLETED
        step.result = "" if result is None else str(result)
        step.error = None
        task.current_step_index = step.step_index + 1
        self.repo.save_checkpoint(task.id, step, task.current_step_index)
        self.repo.update_task(task)
        self.repo.append_event(
            TaskEvent(
                id=None,
                task_id=task.id,
                event_type="step_completed",
                status=task.status.value,
                step_index=step.step_index,
                message=f"Completed step '{step.name}'.",
                data={"action": step.action, "outcome": step.outcome.value},
            )
        )

    def mark_step_failed(self, task: TaskRecord, step: TaskStep, error: str) -> None:
        step.outcome = StepOutcome.FAILED
        step.error = error
        self.repo.save_checkpoint(task.id, step, task.current_step_index)
        self.repo.append_event(
            TaskEvent(
                id=None,
                task_id=task.id,
                event_type="step_failed",
                status=task.status.value,
                step_index=step.step_index,
                message=f"Step '{step.name}' failed: {error}",
                data={"action": step.action, "outcome": step.outcome.value, "attempt": step.attempts},
            )
        )


class ApprovalManager:
    """Manages cryptographic payload-bound approval gates before consequential or post-crash uncertain actions."""

    def __init__(self, repo: TaskRepository):
        self.repo = repo

    def request_approval(
        self,
        task: TaskRecord,
        step: TaskStep,
        reason: str,
        ttl_s: float | None = None,
        target_status: TaskStatus = TaskStatus.WAITING_FOR_APPROVAL,
    ) -> ApprovalRequest:
        now = datetime.now()
        expires_at = (now + timedelta(seconds=ttl_s)).isoformat() if ttl_s is not None else None
        payload_hash = compute_action_payload_hash(step)
        summary = f"{step.name}: {step.action}({step.args})"
        req = ApprovalRequest(
            id=f"apr-{uuid.uuid4().hex[:8]}",
            task_id=task.id,
            step_index=step.step_index,
            action=step.action,
            args=dict(step.args),
            reason=reason,
            status="pending",
            created_at=now.isoformat(),
            action_summary=summary,
            action_payload_hash=payload_hash,
            expires_at=expires_at,
        )
        self.repo.create_approval(req)
        task.status = target_status
        self.repo.update_task(task)
        self.repo.append_event(
            TaskEvent(
                id=None,
                task_id=task.id,
                event_type="approval_requested",
                status=task.status.value,
                step_index=step.step_index,
                message=reason,
                data={
                    "approval_id": req.id,
                    "action": step.action,
                    "action_payload_hash": payload_hash,
                },
            )
        )
        _emit_task_update(task.id, task.conversation_id, task.status.value, "approval_requested")
        return req

    def verify_payload_integrity(self, approval: ApprovalRequest, step: TaskStep) -> None:
        current_hash = compute_action_payload_hash(step)
        if approval.action_payload_hash and approval.action_payload_hash != current_hash:
            self.repo.invalidate_approval(approval.id, reason="payload_changed")
            self.repo.append_event(
                TaskEvent(
                    id=None,
                    task_id=approval.task_id,
                    event_type="approval_invalidated",
                    status=TaskStatus.WAITING_FOR_APPROVAL.value,
                    step_index=step.step_index,
                    message=f"Approval '{approval.id}' invalidated: step payload changed after request.",
                    data={"approval_id": approval.id},
                )
            )
            raise ApprovalInvalidatedError(
                f"Approval '{approval.id}' invalidated because step '{step.name}' payload changed."
            )

    def approve(self, approval_id: str, resolved_by: str = "user") -> ApprovalRequest:
        existing = self.repo.get_approval(approval_id)
        if not existing:
            raise TaskNotFoundError(f"Approval '{approval_id}' not found")
        req = self.repo.resolve_approval(approval_id, "approved", resolved_by=resolved_by)
        self.repo.append_event(
            TaskEvent(
                id=None,
                task_id=req.task_id,
                event_type="approval_granted",
                status=TaskStatus.WAITING_FOR_APPROVAL.value,
                step_index=req.step_index,
                message=f"Approval '{approval_id}' granted by {resolved_by}.",
                data={"approval_id": approval_id},
            )
        )
        return req

    def reject(self, approval_id: str, resolved_by: str = "user") -> ApprovalRequest:
        req = self.repo.resolve_approval(approval_id, "rejected", resolved_by=resolved_by)
        self.repo.append_event(
            TaskEvent(
                id=None,
                task_id=req.task_id,
                event_type="approval_rejected",
                status=TaskStatus.CANCELLED.value,
                step_index=req.step_index,
                message=f"Approval '{approval_id}' rejected by {resolved_by}.",
                data={"approval_id": approval_id},
            )
        )
        return req


class TaskRunner:
    """Executes individual task steps with cancellation, timeout propagation, and bounded retries."""

    def __init__(
        self,
        step_handler: StepHandler,
        checkpoints: CheckpointManager,
        approvals: ApprovalManager,
        repo: TaskRepository,
        owner_id: str = "local",
        authorizer: StepAuthorizer | None = None,
    ):
        self.step_handler = step_handler
        self.checkpoints = checkpoints
        self.approvals = approvals
        self.repo = repo
        self.owner_id = owner_id
        self.authorizer = authorizer

    async def _invoke_step(self, step: TaskStep, cancel_event: asyncio.Event, timeout_s: float | None) -> Any:
        coro_or_val = self.step_handler(step, cancel_event)
        if inspect.isawaitable(coro_or_val):
            if timeout_s is not None:
                return await asyncio.wait_for(coro_or_val, timeout=timeout_s)
            return await coro_or_val
        return coro_or_val

    async def run(
        self,
        task: TaskRecord,
        cancel_event: asyncio.Event,
        pause_event: asyncio.Event,
        approved_steps: dict[int, ApprovalRequest] | None = None,
    ) -> TaskRecord:
        approved_steps = approved_steps or {}
        with correlation_scope(conversation_id=task.conversation_id, task_id=task.id):
            if not task.started_at:
                task.started_at = datetime.now().isoformat()
            task.status = TaskStatus.RUNNING
            task.error = None
            self.repo.update_task(task)
            self.repo.append_event(
                TaskEvent(
                    id=None,
                    task_id=task.id,
                    event_type="task_running",
                    status=task.status.value,
                    step_index=task.current_step_index,
                    message=f"Running task '{task.title}' from step {task.current_step_index}.",
                )
            )
            log_event("TaskRunner", "task_running", task_id=task.id, step_index=task.current_step_index)

            try:
                while task.current_step_index < len(task.steps):
                    if cancel_event.is_set():
                        task.status = TaskStatus.CANCELLED
                        task.completed_at = datetime.now().isoformat()
                        self.repo.update_task(task)
                        self.repo.append_event(
                            TaskEvent(
                                id=None,
                                task_id=task.id,
                                event_type="task_cancelled",
                                status=task.status.value,
                                step_index=task.current_step_index,
                                message="Task cancelled.",
                            )
                        )
                        return task

                    if pause_event.is_set():
                        task.status = TaskStatus.PAUSED
                        self.repo.update_task(task)
                        self.repo.append_event(
                            TaskEvent(
                                id=None,
                                task_id=task.id,
                                event_type="task_paused",
                                status=task.status.value,
                                step_index=task.current_step_index,
                                message="Task paused at step boundary.",
                            )
                        )
                        return task

                    step = task.steps[task.current_step_index]

                    if step.outcome == StepOutcome.COMPLETED:
                        task.current_step_index += 1
                        self.repo.update_task(task)
                        continue

                    if self.authorizer is not None and step.action != "agent_turn":
                        decision = self.authorizer(step)
                        if not decision.allowed:
                            self.checkpoints.mark_step_failed(task, step, decision.reason)
                            task.status = TaskStatus.FAILED
                            task.error = decision.reason
                            task.completed_at = datetime.now().isoformat()
                            self.repo.update_task(task)
                            self.repo.append_event(
                                TaskEvent(
                                    id=None,
                                    task_id=task.id,
                                    event_type="task_failed",
                                    status=task.status.value,
                                    step_index=step.step_index,
                                    message=decision.reason,
                                )
                            )
                            return task
                        if decision.requires_approval and step.step_index not in approved_steps:
                            self.approvals.request_approval(task, step, reason=decision.reason)
                            return task

                    if step.step_index in approved_steps:
                        try:
                            self.approvals.verify_payload_integrity(approved_steps[step.step_index], step)
                        except ApprovalInvalidatedError as inv_exc:
                            self.approvals.request_approval(
                                task,
                                step,
                                reason=str(inv_exc),
                            )
                            return task
                    else:
                        if step.outcome == StepOutcome.UNCERTAIN:
                            self.approvals.request_approval(
                                task,
                                step,
                                reason=f"Step '{step.name}' was in-flight during a restart; outcome is unknown.",
                                target_status=TaskStatus.UNCERTAIN,
                            )
                            return task

                        if step.requires_approval:
                            self.approvals.request_approval(
                                task,
                                step,
                                reason=f"Step '{step.name}' ({step.action}) requires user approval.",
                            )
                            return task

                    max_attempts = max(1, step.max_attempts or task.retry_policy.max_attempts)
                    step.max_attempts = max_attempts
                    last_err = None

                    while step.attempts < max_attempts:
                        if cancel_event.is_set():
                            task.status = TaskStatus.CANCELLED
                            task.completed_at = datetime.now().isoformat()
                            self.repo.update_task(task)
                            self.repo.append_event(
                                TaskEvent(
                                    id=None,
                                    task_id=task.id,
                                    event_type="task_cancelled",
                                    status=task.status.value,
                                    step_index=step.step_index,
                                    message="Task cancelled before step attempt.",
                                )
                            )
                            return task

                        self.checkpoints.mark_step_started(task, step)
                        try:
                            res = await self._invoke_step(step, cancel_event, task.timeout_s)
                            self.checkpoints.mark_step_completed(task, step, res)
                            last_err = None
                            break
                        except UncertainCancellationError as unc_exc:
                            step.outcome = StepOutcome.UNCERTAIN
                            step.error = str(unc_exc)
                            self.repo.save_checkpoint(task.id, step, task.current_step_index)
                            self.repo.append_event(
                                TaskEvent(
                                    id=None,
                                    task_id=task.id,
                                    event_type="task_cancel_uncertain",
                                    status=TaskStatus.UNCERTAIN.value,
                                    step_index=step.step_index,
                                    message=str(unc_exc),
                                )
                            )
                            self.approvals.request_approval(
                                task,
                                step,
                                reason=str(unc_exc),
                                target_status=TaskStatus.UNCERTAIN,
                            )
                            return task
                        except asyncio.CancelledError:
                            task.status = TaskStatus.CANCELLED
                            task.completed_at = datetime.now().isoformat()
                            self.repo.update_task(task)
                            self.repo.append_event(
                                TaskEvent(
                                    id=None,
                                    task_id=task.id,
                                    event_type="task_cancelled",
                                    status=task.status.value,
                                    step_index=step.step_index,
                                    message="Task cancelled during step execution.",
                                )
                            )
                            raise
                        except asyncio.TimeoutError:
                            last_err = f"Step '{step.name}' timed out after {task.timeout_s}s"
                            self.checkpoints.mark_step_failed(task, step, last_err)
                        except Exception as exc:
                            last_err = str(exc) or type(exc).__name__
                            self.checkpoints.mark_step_failed(task, step, last_err)

                        if step.attempts < max_attempts and not cancel_event.is_set():
                            await asyncio.sleep(task.retry_policy.backoff_s * step.attempts)

                    if last_err is not None:
                        task.status = TaskStatus.FAILED
                        task.error = last_err
                        task.completed_at = datetime.now().isoformat()
                        self.repo.update_task(task)
                        self.repo.append_event(
                            TaskEvent(
                                id=None,
                                task_id=task.id,
                                event_type="task_failed",
                                status=task.status.value,
                                step_index=step.step_index,
                                message=last_err,
                            )
                        )
                        log_event("TaskRunner", "task_failed", level="ERROR", task_id=task.id, error=last_err)
                        return task

                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now().isoformat()
                self.repo.update_task(task)
                self.repo.append_event(
                    TaskEvent(
                        id=None,
                        task_id=task.id,
                        event_type="task_completed",
                        status=task.status.value,
                        step_index=task.current_step_index,
                        message=f"Task '{task.title}' completed.",
                    )
                )
                _emit_task_update(task.id, task.conversation_id, task.status.value, "task_completed")
                log_event("TaskRunner", "task_completed", task_id=task.id)
                return task
            finally:
                self.repo.release_claim(task.id, self.owner_id)


class TaskRecoveryService:
    """Reconciles persisted tasks on startup without blindly repeating uncertain or completed actions."""

    def __init__(self, repo: TaskRepository, approvals: ApprovalManager, instance_id: str):
        self.repo = repo
        self.approvals = approvals
        self.instance_id = instance_id

    def inspect_and_prepare(self) -> list[TaskRecord]:
        resumable: list[TaskRecord] = []
        candidates = self.repo.list_tasks(statuses=[TaskStatus.RUNNING, TaskStatus.QUEUED], limit=200)
        for task in candidates:
            if not self.repo.claim_task(task.id, self.instance_id):
                continue

            if task.status == TaskStatus.QUEUED:
                resumable.append(task)
                continue

            while (
                task.current_step_index < len(task.steps)
                and task.steps[task.current_step_index].outcome == StepOutcome.COMPLETED
            ):
                task.current_step_index += 1

            if task.current_step_index >= len(task.steps):
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now().isoformat()
                self.repo.update_task(task)
                self.repo.release_claim(task.id, self.instance_id)
                self.repo.append_event(
                    TaskEvent(
                        id=None,
                        task_id=task.id,
                        event_type="recovery_completed",
                        status=task.status.value,
                        step_index=task.current_step_index,
                        message="Recovered task already completed all steps.",
                    )
                )
                continue

            step = task.steps[task.current_step_index]
            if step.outcome == StepOutcome.UNCERTAIN:
                existing_pending = self.repo.list_pending_approvals(task_id=task.id)
                if not existing_pending:
                    self.approvals.request_approval(
                        task,
                        step,
                        reason=f"Restart recovery: step '{step.name}' was in-flight and its outcome is unknown.",
                        target_status=TaskStatus.UNCERTAIN,
                    )
                else:
                    task.status = TaskStatus.UNCERTAIN
                    self.repo.update_task(task)
                self.repo.release_claim(task.id, self.instance_id)
            else:
                task.status = TaskStatus.QUEUED
                self.repo.update_task(task)
                self.repo.append_event(
                    TaskEvent(
                        id=None,
                        task_id=task.id,
                        event_type="recovery_requeued",
                        status=task.status.value,
                        step_index=task.current_step_index,
                        message=f"Re-queued task for recovery at step {task.current_step_index}.",
                    )
                )
                resumable.append(task)

        return resumable


class TaskOrchestrator:
    """Schedules, isolates, pauses, cancels, approves, and recovers persistent tasks."""

    def __init__(
        self,
        repo: TaskRepository,
        step_handler: StepHandler,
        instance_id: str | None = None,
        authorizer: StepAuthorizer | None = None,
    ):
        self.repo = repo
        self.instance_id = instance_id or f"orch-{uuid.uuid4().hex[:8]}"
        self.repo.initialize()
        self.checkpoints = CheckpointManager(repo)
        self.approvals = ApprovalManager(repo)
        self.runner = TaskRunner(
            step_handler,
            self.checkpoints,
            self.approvals,
            repo,
            owner_id=self.instance_id,
            authorizer=authorizer,
        )
        self.recovery = TaskRecoveryService(repo, self.approvals, instance_id=self.instance_id)
        self._active_handles: dict[str, tuple[asyncio.Task, asyncio.Event, asyncio.Event]] = {}
        self._lock = threading.Lock()
        self.recovery_completed: bool = False
        self.recovery_error: str | None = None

    def submit_task(
        self,
        title: str,
        steps: list[dict | TaskStep],
        conversation_id: str = "default",
        retry_policy: RetryPolicy | None = None,
        timeout_s: float | None = None,
        metadata: dict | None = None,
        auto_start: bool = True,
    ) -> TaskRecord:
        if self.recovery_error is not None:
            raise TaskRecoveryError(f"Cannot accept new tasks; startup recovery failed: {self.recovery_error}")

        task_id = f"task-{uuid.uuid4().hex[:10]}"
        rp = retry_policy or RetryPolicy()
        normalized_steps = [
            s
            if isinstance(s, TaskStep)
            else TaskStep(
                step_index=idx,
                name=s["name"],
                action=s["action"],
                args=dict(s.get("args", {})),
                requires_approval=bool(s.get("requires_approval", False)),
                idempotent=bool(s.get("idempotent", False)),
                max_attempts=int(s.get("max_attempts", rp.max_attempts)),
            )
            for idx, s in enumerate(steps)
        ]
        task = TaskRecord(
            id=task_id,
            conversation_id=conversation_id,
            title=title,
            status=TaskStatus.QUEUED,
            steps=normalized_steps,
            current_step_index=0,
            metadata=dict(metadata or {}),
            retry_policy=rp,
            timeout_s=timeout_s,
        )
        self.repo.create_task(task)
        self.repo.append_event(
            TaskEvent(
                id=None,
                task_id=task.id,
                event_type="task_queued",
                status=task.status.value,
                step_index=0,
                message=f"Queued task '{title}' with {len(normalized_steps)} steps.",
            )
        )
        if auto_start:
            self.start_task(task.id)
        return task

    def start_task(
        self,
        task_id: str,
        approved_steps: dict[int, ApprovalRequest] | None = None,
    ) -> asyncio.Task | None:
        task = self.repo.get_task(task_id)
        if not task:
            raise TaskNotFoundError(f"Task '{task_id}' not found")
        if task.status in (TaskStatus.PAUSED, TaskStatus.WAITING_FOR_APPROVAL, TaskStatus.UNCERTAIN):
            task.status = TaskStatus.QUEUED
            self.repo.update_task(task)
        if not self.repo.claim_task(task.id, self.instance_id):
            return None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.repo.release_claim(task.id, self.instance_id)
            return None

        cancel_ev = asyncio.Event()
        pause_ev = asyncio.Event()

        async def _run():
            try:
                await self.runner.run(task, cancel_ev, pause_ev, approved_steps=approved_steps)
            except asyncio.CancelledError:
                pass
            finally:
                with self._lock:
                    self._active_handles.pop(task_id, None)

        async_task = loop.create_task(_run())
        with self._lock:
            self._active_handles[task_id] = (async_task, cancel_ev, pause_ev)
        return async_task

    async def wait_for_task(self, task_id: str, timeout: float | None = 5.0) -> TaskRecord | None:
        with self._lock:
            handle = self._active_handles.get(task_id)
        if handle:
            async_task, _, _ = handle
            await asyncio.wait_for(async_task, timeout=timeout)
        return self.repo.get_task(task_id)

    def pause_task(self, task_id: str) -> TaskRecord:
        task = self.repo.get_task(task_id)
        if not task:
            raise TaskNotFoundError(f"Task '{task_id}' not found")
        if task.status not in (TaskStatus.QUEUED, TaskStatus.RUNNING):
            raise TaskStateError(f"Cannot pause task in status '{task.status.value}'")
        with self._lock:
            handle = self._active_handles.get(task_id)
        if handle:
            _, _, pause_ev = handle
            pause_ev.set()
        elif task.status == TaskStatus.QUEUED:
            task.status = TaskStatus.PAUSED
            self.repo.update_task(task)
        return self.repo.get_task(task_id)  # type: ignore[return-value]

    def resume_task(self, task_id: str) -> TaskRecord:
        task = self.repo.get_task(task_id)
        if not task:
            raise TaskNotFoundError(f"Task '{task_id}' not found")
        if task.status not in (TaskStatus.PAUSED, TaskStatus.QUEUED):
            raise TaskStateError(f"Cannot resume task in status '{task.status.value}'")
        self.start_task(task_id)
        return self.repo.get_task(task_id)  # type: ignore[return-value]

    def cancel_task(self, task_id: str) -> TaskRecord:
        task = self.repo.get_task(task_id)
        if not task:
            raise TaskNotFoundError(f"Task '{task_id}' not found")
        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            raise TaskStateError(f"Cannot cancel task in terminal status '{task.status.value}'")
        with self._lock:
            handle = self._active_handles.get(task_id)
        if handle:
            async_task, cancel_ev, _ = handle
            self.repo.append_event(
                TaskEvent(
                    id=None,
                    task_id=task.id,
                    event_type="task_cancel_requested",
                    status=task.status.value,
                    step_index=task.current_step_index,
                    message="Cancellation requested for active task.",
                )
            )
            cancel_ev.set()
            async_task.cancel()
        else:
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now().isoformat()
            self.repo.update_task(task)
            self.repo.release_claim(task.id, self.instance_id)
            self.repo.append_event(
                TaskEvent(
                    id=None,
                    task_id=task.id,
                    event_type="task_cancelled",
                    status=task.status.value,
                    step_index=task.current_step_index,
                    message="Task cancelled.",
                )
            )
        return self.repo.get_task(task_id)  # type: ignore[return-value]

    def approve_and_resume(
        self,
        approval_id: str,
        resolved_by: str = "user",
        mark_uncertain_completed: bool = False,
    ) -> ApprovalRequest:
        existing = self.repo.get_approval(approval_id)
        if not existing:
            raise TaskNotFoundError(f"Approval '{approval_id}' not found")
        task = self.repo.get_task(existing.task_id)
        if not task:
            raise TaskNotFoundError(f"Task '{existing.task_id}' not found")
        step = task.steps[existing.step_index]
        self.approvals.verify_payload_integrity(existing, step)

        req = self.approvals.approve(approval_id, resolved_by=resolved_by)
        if mark_uncertain_completed:
            self.checkpoints.mark_step_completed(task, step, "confirmed_by_user")
            self.start_task(task.id)
        else:
            self.start_task(task.id, approved_steps={req.step_index: req})
        return req

    def reject_and_cancel(self, approval_id: str, resolved_by: str = "user") -> ApprovalRequest:
        req = self.approvals.reject(approval_id, resolved_by=resolved_by)
        task = self.repo.get_task(req.task_id)
        if task and task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            self.cancel_task(req.task_id)
        return req

    def recover_on_startup(self) -> list[TaskRecord]:
        try:
            resumable = self.recovery.inspect_and_prepare()
            self.recovery_completed = True
            self.recovery_error = None
            for t in resumable:
                self.start_task(t.id)
            return resumable
        except Exception as exc:
            self.recovery_completed = False
            self.recovery_error = str(exc) or type(exc).__name__
            log_event("TaskOrchestrator", "task_recovery_failed", level="ERROR", exc=exc)
            raise TaskRecoveryError(f"Startup task recovery failed: {self.recovery_error}") from exc

    def get_task_timeline(self, task_id: str) -> list[TaskEvent]:
        return self.repo.get_events(task_id)
