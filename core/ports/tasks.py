from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class TaskError(Exception):
    """Base domain error for persistent task orchestration."""


class TaskStorageError(TaskError):
    """Raised when task persistence fails."""


class TaskNotFoundError(TaskError):
    """Raised when a referenced task or approval does not exist."""


class TaskStateError(TaskError):
    """Raised when an invalid task state transition is attempted."""


class ApprovalConflictError(TaskStateError):
    """Raised on duplicate or stale approval resolution."""


class ApprovalExpiredError(TaskStateError):
    """Raised when attempting to resolve or use an expired approval."""


class ApprovalInvalidatedError(TaskStateError):
    """Raised when the underlying action payload changed after approval was requested."""


class TaskRecoveryError(TaskError):
    """Raised when startup recovery failed and task execution must not proceed."""


class TaskLeaseLostError(TaskStateError):
    """Raised when a stale worker attempts to commit state after losing its task lease."""


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    UNCERTAIN = "uncertain"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepOutcome(str, Enum):
    NOT_STARTED = "not_started"
    UNCERTAIN = "uncertain"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class RetryPolicy:
    max_attempts: int = 1
    backoff_s: float = 0.05


@dataclass
class TaskStep:
    step_index: int
    name: str
    action: str
    args: dict = field(default_factory=dict)
    requires_approval: bool = False
    idempotent: bool = False
    outcome: StepOutcome = StepOutcome.NOT_STARTED
    result: str | None = None
    error: str | None = None
    attempts: int = 0
    max_attempts: int = 1
    updated_at: str = ""


def compute_action_payload_hash(step: TaskStep) -> str:
    """Canonical SHA-256 hash binding an approval to the exact step name, action, and args."""
    canonical = json.dumps(
        {"name": step.name, "action": step.action, "args": step.args},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class TaskRecord:
    id: str
    conversation_id: str
    title: str
    status: TaskStatus
    steps: list[TaskStep]
    current_step_index: int = 0
    created_at: str = ""
    updated_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    metadata: dict = field(default_factory=dict)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    timeout_s: float | None = None
    owner_id: str | None = None
    lease_expires_at: str | None = None


@dataclass
class TaskEvent:
    id: int | None
    task_id: str
    event_type: str
    status: str
    step_index: int | None
    message: str
    data: dict = field(default_factory=dict)
    timestamp: str = ""


@dataclass
class ApprovalRequest:
    id: str
    task_id: str
    step_index: int
    action: str
    args: dict
    reason: str
    status: str  # "pending" | "approved" | "rejected" | "invalidated" | "expired"
    created_at: str
    action_summary: str = ""
    action_payload_hash: str = ""
    expires_at: str | None = None
    resolved_at: str | None = None
    resolved_by: str | None = None


@runtime_checkable
class TaskRepository(Protocol):
    """Persistence-agnostic contract for tasks, checkpoints, events, and approvals."""

    def initialize(self) -> None: ...
    def create_task(self, task: TaskRecord) -> TaskRecord: ...
    def get_task(self, task_id: str) -> TaskRecord | None: ...
    def list_tasks(
        self,
        conversation_id: str | None = None,
        statuses: list[TaskStatus] | None = None,
        limit: int = 50,
    ) -> list[TaskRecord]: ...
    def update_task(self, task: TaskRecord) -> None: ...
    def claim_task(self, task_id: str, owner_id: str, lease_ttl_s: float = 30.0) -> bool: ...
    def release_claim(self, task_id: str, owner_id: str) -> None: ...
    def save_checkpoint(self, task_id: str, step: TaskStep, current_step_index: int) -> None: ...
    def append_event(self, event: TaskEvent) -> TaskEvent: ...
    def get_events(self, task_id: str) -> list[TaskEvent]: ...
    def get_events_page(self, task_id: str, offset: int = 0, limit: int = 50) -> tuple[list[TaskEvent], int]: ...
    def create_approval(self, approval: ApprovalRequest) -> ApprovalRequest: ...
    def get_approval(self, approval_id: str) -> ApprovalRequest | None: ...
    def list_pending_approvals(
        self,
        task_id: str | None = None,
        conversation_id: str | None = None,
    ) -> list[ApprovalRequest]: ...
    def resolve_approval(self, approval_id: str, status: str, resolved_by: str = "user") -> ApprovalRequest: ...
    def invalidate_approval(self, approval_id: str, reason: str = "payload_changed") -> None: ...
