from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Optional

from core.ports.tasks import TaskRecord, TaskStatus

_CONTINUITY_MARKERS = re.compile(
    r"\b(?:working on|worked on|leave off|left off|unfinished|remaining|pending|"
    r"blocked|approval|uncertain|next step|what next|what should we do|yesterday|"
    r"last problem|decision|decisions|continue|resume|progress|status|tasks|project)\b",
    re.IGNORECASE,
)

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "about",
    "and", "or", "but", "not", "this", "that", "it", "i", "me", "my", "you",
    "what", "where", "when", "who", "how", "why", "do", "does", "did", "can",
    "we", "us", "our", "should", "next", "last",
}

_STATUS_LABELS = {
    TaskStatus.RUNNING: "RUNNING (currently executing)",
    TaskStatus.QUEUED: "QUEUED (awaiting execution)",
    TaskStatus.WAITING_FOR_APPROVAL: "BLOCKED (waiting for user approval)",
    TaskStatus.UNCERTAIN: "UNCERTAIN (outcome requires reconciliation; do not auto-retry)",
    TaskStatus.PAUSED: "PAUSED (unfinished)",
    TaskStatus.FAILED: "FAILED",
    TaskStatus.COMPLETED: "COMPLETED",
    TaskStatus.CANCELLED: "CANCELLED (explicitly stopped)",
}


def _tokenize(text: str) -> set[str]:
    return {
        w for w in re.findall(r"\b\w+\b", (text or "").lower())
        if w not in _STOPWORDS and len(w) >= 2
    }


@dataclass(frozen=True)
class WorkContextResult:
    text: str
    has_private_context: bool = False
    privacy_classification: str = "public"
    sources: tuple[str, ...] = ()


class WorkContextBuilder:
    """
    Assembles a compact, read-only summary of ongoing, blocked, uncertain,
    and recently completed work across sessions without executing any tasks.
    """

    @staticmethod
    def _is_continuity_query(query: str) -> bool:
        return bool(_CONTINUITY_MARKERS.search(query or ""))

    @staticmethod
    def _next_action_hint(task: TaskRecord) -> str:
        if task.status == TaskStatus.WAITING_FOR_APPROVAL:
            return "Next: requires explicit user approval in 05 TASKS before execution."
        if task.status == TaskStatus.UNCERTAIN:
            return "Next: outcome is uncertain; ask user to reconcile before resuming."
        if task.status == TaskStatus.FAILED:
            err = (task.error or "unknown error")[:80]
            return f"Next: review failure ({err}) before retrying."
        if task.status == TaskStatus.PAUSED:
            return "Next: ask user whether to resume."
        if task.status in (TaskStatus.RUNNING, TaskStatus.QUEUED):
            return "Next: already in progress."
        return ""

    @staticmethod
    def _score_task(task: TaskRecord, query_tokens: set[str], session_id: str, continuity_query: bool) -> float:
        title_tokens = _tokenize(task.title)
        step_tokens: set[str] = set()
        for s in task.steps:
            step_tokens |= _tokenize(s.name) | _tokenize(s.action)
        all_tokens = title_tokens | step_tokens

        overlap = len(query_tokens & all_tokens)
        score = float(overlap) * 2.0

        if task.conversation_id == session_id:
            score += 1.5
        if task.status in (
            TaskStatus.RUNNING,
            TaskStatus.QUEUED,
            TaskStatus.WAITING_FOR_APPROVAL,
            TaskStatus.UNCERTAIN,
            TaskStatus.PAUSED,
        ):
            score += 1.5
        elif task.status == TaskStatus.FAILED:
            score += 1.0
        elif continuity_query and task.status == TaskStatus.COMPLETED:
            score += 0.5

        if not continuity_query and overlap == 0 and task.conversation_id != session_id:
            return 0.0
        if not continuity_query and overlap == 0 and task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            return 0.0
        return score

    def build(
        self,
        query: str,
        session_id: str = "default",
        task_orchestrator: Any = None,
        memory_module: Any = None,
        *,
        max_chars: int = 1200,
        max_tasks: int = 5,
        exclude_texts: Optional[list[str]] = None,
    ) -> str:
        return self.build_with_metadata(
            query,
            session_id=session_id,
            task_orchestrator=task_orchestrator,
            memory_module=memory_module,
            max_chars=max_chars,
            max_tasks=max_tasks,
            exclude_texts=exclude_texts,
        ).text

    def build_with_metadata(
        self,
        query: str,
        session_id: str = "default",
        task_orchestrator: Any = None,
        memory_module: Any = None,
        *,
        max_chars: int = 1200,
        max_tasks: int = 5,
        exclude_texts: Optional[list[str]] = None,
    ) -> WorkContextResult:
        if not query or not query.strip() or max_chars <= 0:
            return WorkContextResult(text="")

        continuity_query = self._is_continuity_query(query)
        query_tokens = _tokenize(query)
        seen_norm = {re.sub(r"\s+", " ", t.strip().lower()) for t in (exclude_texts or []) if t}

        lines: list[str] = []

        # 1. Read-only task & event inspection across conversations
        repo = getattr(task_orchestrator, "repo", None) if task_orchestrator is not None else None
        if repo is not None:
            try:
                all_tasks = repo.list_tasks(limit=30)
            except Exception:
                all_tasks = []

            scored_tasks: list[tuple[float, str, TaskRecord]] = []
            for t in all_tasks:
                sc = self._score_task(t, query_tokens, session_id, continuity_query)
                if sc > 0:
                    scored_tasks.append((sc, t.updated_at or t.created_at or "", t))

            scored_tasks.sort(key=lambda x: (x[0], x[1]), reverse=True)
            for _, _, task in scored_tasks[:max_tasks]:
                status_label = _STATUS_LABELS.get(task.status, str(task.status.value))
                step_info = f"step {min(task.current_step_index + 1, max(1, len(task.steps)))}/{max(1, len(task.steps))}"
                last_msg = ""
                try:
                    events = repo.get_events(task.id)
                    if events:
                        last_msg = (events[-1].message or "").strip()[:100]
                except Exception:
                    last_msg = ""
                hint = self._next_action_hint(task)
                parts = [f"- [{status_label}] '{task.title[:60]}' (session={task.conversation_id}, {step_info})"]
                if last_msg:
                    parts.append(f"Last: {last_msg}")
                if hint:
                    parts.append(hint)
                line = " | ".join(parts)
                norm_line = re.sub(r"\s+", " ", line.lower())
                if norm_line not in seen_norm:
                    seen_norm.add(norm_line)
                    lines.append(line)

        # 2. Cross-session conversation continuity (only on explicit continuity queries, bounded)
        if continuity_query and memory_module is not None and hasattr(memory_module, "list_conversations"):
            try:
                convs = memory_module.list_conversations()[:4]
                for conv in convs:
                    cid = conv.get("id", "")
                    if not cid or cid == session_id:
                        continue
                    title = str(conv.get("title") or cid)[:48]
                    msgs = memory_module.get_messages(cid, limit=2)
                    if not msgs:
                        continue
                    snippet = str(msgs[-1].get("content", "")).replace("\n", " ").strip()[:100]
                    if not snippet:
                        continue
                    norm_snip = re.sub(r"\s+", " ", snippet.lower())
                    if norm_snip in seen_norm:
                        continue
                    seen_norm.add(norm_snip)
                    lines.append(f"- [PRIOR SESSION '{title}'] Last message: {snippet}")
            except Exception:
                pass

        if not lines:
            return WorkContextResult(text="")

        header = (
            "[BEGIN ONGOING WORK CONTEXT — INFORMATIONAL ONLY]\n"
            "Remembering unfinished, blocked, or uncertain work does NOT authorize execution."
        )
        footer = "[END ONGOING WORK CONTEXT]"
        overhead = len(header) + len(footer) + 2
        if max_chars <= overhead + 16:
            return WorkContextResult(text="")

        budget = max_chars - overhead
        kept: list[str] = []
        used = 0
        for line in lines:
            if used + len(line) + (1 if kept else 0) > budget:
                remaining = budget - used - (1 if kept else 0)
                if remaining > 24:
                    kept.append(line[: remaining - 1].rstrip() + "…")
                break
            kept.append(line)
            used += len(line) + (1 if len(kept) > 1 else 0)

        if not kept:
            return WorkContextResult(text="")
        text_out = header + "\n" + "\n".join(kept) + "\n" + footer
        return WorkContextResult(
            text=text_out,
            has_private_context=True,
            privacy_classification="private",
            sources=("ongoing_work",),
        )
