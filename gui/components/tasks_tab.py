# gui/components/tasks_tab.py

from __future__ import annotations

from datetime import datetime
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from components.tabs import AutomationTab, _make_header


_STATUS_COLORS = {
    "queued": "#67E8F9",
    "running": "#38BDF8",
    "paused": "#FBBF24",
    "waiting_for_approval": "#F59E0B",
    "uncertain": "#FB923C",
    "completed": "#22C55E",
    "failed": "#EF4444",
    "cancelled": "#94A3B8",
}

_OUTCOME_LABELS = {
    "not_started": ("NOT STARTED", "#94A3B8"),
    "uncertain": ("UNCERTAIN — OUTCOME UNKNOWN", "#F59E0B"),
    "completed": ("EXECUTED / COMPLETED", "#22C55E"),
    "failed": ("FAILED", "#EF4444"),
}


class TasksTab(QWidget):
    """
    CREED 3.0 Tranche 5.2 — Desktop Task Interface.
    Integrates Task Overview, Execution Timeline, Approval Centre, Task Inspector,
    and Saved Workflows under CREED's Spatial OS navigation without touching SQLite.
    """

    refresh_tasks_requested = Signal(str)  # status filter
    select_task_requested = Signal(str)  # task_id
    load_more_events_requested = Signal(str, int)  # task_id, offset
    pause_task_requested = Signal(str)
    resume_task_requested = Signal(str)
    cancel_task_requested = Signal(str)
    refresh_approvals_requested = Signal()
    resolve_approval_requested = Signal(str, str)  # approval_id, decision

    def __init__(self):
        super().__init__()
        self._tasks: list[dict] = []
        self._selected_task_id: str = ""
        self._selected_task: dict | None = None
        self._events: list[dict] = []
        self._events_total: int = 0
        self._events_has_more: bool = False
        self._approvals: list[dict] = []
        self._inflight_approvals: set[str] = set()
        self._is_connected: bool = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # Header + Connection / Error Banner + Sub-view Switcher
        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(
            _make_header(
                "Task Orchestration",
                "Persistent tasks, checkpoint timelines, approval gates, and recovery inspection",
                "CREED / SYS-05 • TASK ENGINE",
                "#67E8F9",
            ),
            1,
        )

        self.refresh_btn = QPushButton("↻ REFRESH")
        self.refresh_btn.setObjectName("secondary_btn")
        self.refresh_btn.clicked.connect(self._emit_refresh)
        top_row.addWidget(self.refresh_btn)
        root.addLayout(top_row)

        # Explicit error / disconnected / stale-data banner
        self.status_banner = QFrame()
        self.status_banner.setObjectName("panel_card")
        sb_lay = QHBoxLayout(self.status_banner)
        sb_lay.setContentsMargins(12, 6, 12, 6)
        self.status_banner_label = QLabel("")
        self.status_banner_label.setWordWrap(True)
        self.status_banner_label.setObjectName("meta_label")
        sb_lay.addWidget(self.status_banner_label, 1)
        self.status_banner.hide()
        root.addWidget(self.status_banner)

        # Destination Switcher Bar (Overview+Inspector/Timeline | Approval Centre | Workflows)
        sub_nav = QHBoxLayout()
        sub_nav.setSpacing(6)
        self._sub_btns: list[QPushButton] = []
        for idx, label in enumerate(["TASKS & INSPECTOR", "APPROVAL CENTRE (0)", "SAVED WORKFLOWS"]):
            btn = QPushButton(label)
            btn.setObjectName("dock_btn")
            btn.setProperty("active", "true" if idx == 0 else "false")
            btn.clicked.connect(lambda checked=False, i=idx: self._switch_subview(i))
            sub_nav.addWidget(btn)
            self._sub_btns.append(btn)
        sub_nav.addStretch()
        root.addLayout(sub_nav)

        self.sub_stack = QStackedWidget()
        root.addWidget(self.sub_stack, 1)

        # ---- Subview 0: Task Overview (Left) + Inspector & Execution Timeline (Right) ----
        overview_split = QSplitter(Qt.Horizontal)
        overview_split.setChildrenCollapsible(False)

        # Left: Task Overview
        left_pane = QWidget()
        lp_lay = QVBoxLayout(left_pane)
        lp_lay.setContentsMargins(0, 0, 6, 0)
        lp_lay.setSpacing(8)

        filter_row = QHBoxLayout()
        ov_hdr = QLabel("TASK OVERVIEW")
        ov_hdr.setObjectName("section_header")
        self.status_filter = QComboBox()
        self.status_filter.addItems(
            ["all", "running", "queued", "paused", "waiting_for_approval", "uncertain", "completed", "failed", "cancelled"]
        )
        self.status_filter.setStyleSheet(
            "background-color: #10151B; border: 1px solid #22303F; border-radius: 6px; padding: 4px 8px; color: #E6EDF2; font-family: 'Menlo', monospace; font-size: 11px;"
        )
        self.status_filter.currentTextChanged.connect(lambda _: self._emit_refresh())
        filter_row.addWidget(ov_hdr)
        filter_row.addStretch()
        filter_row.addWidget(self.status_filter)
        lp_lay.addLayout(filter_row)

        task_scroll = QScrollArea()
        task_scroll.setWidgetResizable(True)
        task_scroll.setObjectName("chat_area")
        self.task_list_container = QWidget()
        self.task_list_layout = QVBoxLayout(self.task_list_container)
        self.task_list_layout.setSpacing(8)
        self.task_list_layout.addStretch()
        task_scroll.setWidget(self.task_list_container)
        lp_lay.addWidget(task_scroll, 1)
        left_pane.setMinimumWidth(300)

        # Right: Task Inspector + Execution Timeline
        right_pane = QWidget()
        rp_lay = QVBoxLayout(right_pane)
        rp_lay.setContentsMargins(6, 0, 0, 0)
        rp_lay.setSpacing(8)

        detail_tabs = QHBoxLayout()
        detail_tabs.setSpacing(6)
        self._detail_btns: list[QPushButton] = []
        for idx, label in enumerate(["TASK INSPECTOR", "EXECUTION TIMELINE"]):
            btn = QPushButton(label)
            btn.setObjectName("dock_btn")
            btn.setProperty("active", "true" if idx == 0 else "false")
            btn.clicked.connect(lambda checked=False, i=idx: self._switch_detail(i))
            detail_tabs.addWidget(btn)
            self._detail_btns.append(btn)
        detail_tabs.addStretch()
        rp_lay.addLayout(detail_tabs)

        self.detail_stack = QStackedWidget()
        rp_lay.addWidget(self.detail_stack, 1)

        # Detail 0: Task Inspector
        insp_scroll = QScrollArea()
        insp_scroll.setWidgetResizable(True)
        insp_scroll.setObjectName("chat_area")
        self.insp_container = QWidget()
        self.insp_layout = QVBoxLayout(self.insp_container)
        self.insp_layout.setSpacing(8)
        self.insp_empty = QLabel("Select a task from Task Overview to inspect steps, checkpoints, and failure diagnostics.")
        self.insp_empty.setObjectName("meta_label")
        self.insp_empty.setWordWrap(True)
        self.insp_layout.addWidget(self.insp_empty)
        self.insp_layout.addStretch()
        insp_scroll.setWidget(self.insp_container)

        # Detail 1: Execution Timeline
        tl_widget = QWidget()
        tl_lay = QVBoxLayout(tl_widget)
        tl_lay.setContentsMargins(0, 0, 0, 0)
        tl_lay.setSpacing(8)

        tl_scroll = QScrollArea()
        tl_scroll.setWidgetResizable(True)
        tl_scroll.setObjectName("chat_area")
        self.tl_container = QWidget()
        self.tl_layout = QVBoxLayout(self.tl_container)
        self.tl_layout.setSpacing(6)
        self.tl_empty = QLabel("Select a task to view its execution timeline.")
        self.tl_empty.setObjectName("meta_label")
        self.tl_empty.setWordWrap(True)
        self.tl_layout.addWidget(self.tl_empty)
        self.tl_layout.addStretch()
        tl_scroll.setWidget(self.tl_container)
        tl_lay.addWidget(tl_scroll, 1)

        self.load_more_events_btn = QPushButton("LOAD MORE EVENTS")
        self.load_more_events_btn.setObjectName("secondary_btn")
        self.load_more_events_btn.clicked.connect(self._handle_load_more_events)
        self.load_more_events_btn.hide()
        tl_lay.addWidget(self.load_more_events_btn)

        self.detail_stack.addWidget(insp_scroll)
        self.detail_stack.addWidget(tl_widget)
        right_pane.setMinimumWidth(360)

        overview_split.addWidget(left_pane)
        overview_split.addWidget(right_pane)
        overview_split.setSizes([420, 560])

        # ---- Subview 1: Approval Centre ----
        apr_widget = QWidget()
        apr_lay = QVBoxLayout(apr_widget)
        apr_lay.setContentsMargins(0, 4, 0, 0)
        apr_lay.setSpacing(8)

        apr_top = QHBoxLayout()
        apr_hdr = QLabel("PENDING APPROVALS // CRYPTOGRAPHICALLY BOUND TO PAYLOAD HASH")
        apr_hdr.setObjectName("section_header")
        apr_top.addWidget(apr_hdr)
        apr_top.addStretch()
        apr_lay.addLayout(apr_top)

        apr_scroll = QScrollArea()
        apr_scroll.setWidgetResizable(True)
        apr_scroll.setObjectName("chat_area")
        self.apr_container = QWidget()
        self.apr_layout = QVBoxLayout(self.apr_container)
        self.apr_layout.setSpacing(8)
        self.apr_layout.addStretch()
        apr_scroll.setWidget(self.apr_container)
        apr_lay.addWidget(apr_scroll, 1)

        # ---- Subview 2: Saved Workflows (preserved AutomationTab) ----
        self.workflows_tab = AutomationTab()

        self.sub_stack.addWidget(overview_split)
        self.sub_stack.addWidget(apr_widget)
        self.sub_stack.addWidget(self.workflows_tab)

    def _switch_subview(self, index: int):
        self.sub_stack.setCurrentIndex(index)
        for idx, btn in enumerate(self._sub_btns):
            btn.setProperty("active", "true" if idx == index else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _switch_detail(self, index: int):
        self.detail_stack.setCurrentIndex(index)
        for idx, btn in enumerate(self._detail_btns):
            btn.setProperty("active", "true" if idx == index else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _emit_refresh(self):
        self.clear_error()
        flt = self.status_filter.currentText().strip()
        self.refresh_tasks_requested.emit("" if flt == "all" else flt)
        self.refresh_approvals_requested.emit()
        if self._selected_task_id:
            self.select_task_requested.emit(self._selected_task_id)

    def _handle_load_more_events(self):
        if self._selected_task_id and self._events_has_more:
            self.load_more_events_requested.emit(self._selected_task_id, len(self._events))

    def set_connection_state(self, connected: bool):
        self._is_connected = connected
        if not connected:
            self.show_error("BACKEND DISCONNECTED — displayed task state may be stale. Reconnecting...")
        else:
            if "DISCONNECTED" in self.status_banner_label.text():
                self.clear_error()

    def show_error(self, message: str):
        self.status_banner_label.setText(f"⚠ {message}")
        self.status_banner_label.setStyleSheet("color: #F59E0B; font-family: 'Menlo', monospace; font-size: 11px;")
        self.status_banner.show()

    def clear_error(self):
        self.status_banner.hide()
        self.status_banner_label.setText("")

    def update_tasks(self, tasks: list[dict]):
        self._tasks = tasks or []
        while self.task_list_layout.count() > 1:
            item = self.task_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._tasks:
            empty = QLabel("No tasks recorded for this conversation.")
            empty.setObjectName("meta_label")
            self.task_list_layout.insertWidget(0, empty)
            return

        for t in self._tasks:
            tid = t.get("id", "")
            status = t.get("status", "queued")
            color = _STATUS_COLORS.get(status, "#94A3B8")
            steps = t.get("steps", [])
            cur_idx = int(t.get("current_step_index", 0))

            card = QFrame()
            card.setObjectName("panel_card")
            if tid == self._selected_task_id:
                card.setStyleSheet("QFrame#panel_card { border: 1px solid #67E8F9; }")
            v = QVBoxLayout(card)
            v.setContentsMargins(12, 10, 12, 10)
            v.setSpacing(6)

            top = QHBoxLayout()
            title_lbl = QLabel(t.get("title", "Task"))
            title_lbl.setObjectName("accent_label")
            title_lbl.setWordWrap(True)
            st_lbl = QLabel(f"● {status.upper()}")
            st_lbl.setStyleSheet(f"color: {color}; font-family: 'Menlo', monospace; font-size: 10.5px; font-weight: 700;")
            top.addWidget(title_lbl, 1)
            top.addWidget(st_lbl)
            v.addLayout(top)

            meta_lbl = QLabel(
                f"ID: {tid}  •  Step {min(cur_idx, len(steps))}/{len(steps)}  •  {(t.get('updated_at') or '')[:19].replace('T', ' ')}"
            )
            meta_lbl.setObjectName("meta_label")
            meta_lbl.setWordWrap(True)
            v.addWidget(meta_lbl)

            if t.get("error"):
                err_lbl = QLabel(f"Error: {t['error']}")
                err_lbl.setStyleSheet("color: #EF4444; font-family: 'Menlo', monospace; font-size: 10.5px;")
                err_lbl.setWordWrap(True)
                v.addWidget(err_lbl)

            actions = QHBoxLayout()
            actions.setSpacing(6)
            inspect_btn = QPushButton("INSPECT")
            inspect_btn.setObjectName("secondary_btn")
            inspect_btn.clicked.connect(lambda checked=False, task_id=tid: self._select_task(task_id))
            actions.addWidget(inspect_btn)

            if status in ("queued", "running"):
                p_btn = QPushButton("PAUSE")
                p_btn.setObjectName("secondary_btn")
                p_btn.clicked.connect(lambda checked=False, task_id=tid: self.pause_task_requested.emit(task_id))
                actions.addWidget(p_btn)
            if status in ("paused", "queued"):
                r_btn = QPushButton("RESUME")
                r_btn.setObjectName("primary_btn")
                r_btn.clicked.connect(lambda checked=False, task_id=tid: self.resume_task_requested.emit(task_id))
                actions.addWidget(r_btn)
            if status not in ("completed", "failed", "cancelled"):
                c_btn = QPushButton("CANCEL")
                c_btn.setObjectName("secondary_btn")
                c_btn.clicked.connect(lambda checked=False, task_id=tid: self.cancel_task_requested.emit(task_id))
                actions.addWidget(c_btn)
            actions.addStretch()
            v.addLayout(actions)

            self.task_list_layout.insertWidget(self.task_list_layout.count() - 1, card)

    def _select_task(self, task_id: str):
        self._selected_task_id = task_id
        self.select_task_requested.emit(task_id)
        self.update_tasks(self._tasks)

    def update_selected_task(self, task: dict):
        self._selected_task = task
        self._selected_task_id = task.get("id", "")
        while self.insp_layout.count() > 1:
            item = self.insp_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        summary = QFrame()
        summary.setObjectName("panel_card")
        s_lay = QVBoxLayout(summary)
        s_lay.setContentsMargins(12, 10, 12, 10)
        s_lay.setSpacing(4)

        status = task.get("status", "unknown")
        color = _STATUS_COLORS.get(status, "#94A3B8")
        hdr = QLabel(f"{task.get('title', 'Task')}  [{status.upper()}]")
        hdr.setStyleSheet(f"color: {color}; font-family: 'Menlo', monospace; font-size: 12px; font-weight: 700;")
        hdr.setWordWrap(True)
        s_lay.addWidget(hdr)

        meta = QLabel(
            f"Task ID: {task.get('id', '')}  •  Conversation: {task.get('conversation_id', 'default')}\n"
            f"Created: {(task.get('created_at') or '')[:19].replace('T', ' ')}  •  "
            f"Started: {(task.get('started_at') or '—')[:19].replace('T', ' ')}  •  "
            f"Completed: {(task.get('completed_at') or '—')[:19].replace('T', ' ')}"
        )
        meta.setObjectName("meta_label")
        meta.setWordWrap(True)
        s_lay.addWidget(meta)

        if task.get("error"):
            err = QLabel(f"Failure Diagnostic: {task['error']}")
            err.setStyleSheet("color: #EF4444; font-family: 'Menlo', monospace; font-size: 11px;")
            err.setWordWrap(True)
            s_lay.addWidget(err)

        self.insp_layout.insertWidget(self.insp_layout.count() - 1, summary)

        for step in task.get("steps", []):
            scard = QFrame()
            scard.setObjectName("panel_card")
            sv = QVBoxLayout(scard)
            sv.setContentsMargins(12, 8, 12, 8)
            sv.setSpacing(4)

            outcome = step.get("outcome", "not_started")
            out_text, out_color = _OUTCOME_LABELS.get(outcome, (outcome.upper(), "#94A3B8"))
            st_row = QHBoxLayout()
            sname = QLabel(f"Step {step.get('step_index', 0)}: {step.get('name', '')} ({step.get('action', '')})")
            sname.setObjectName("accent_label")
            sname.setWordWrap(True)
            obadge = QLabel(out_text)
            obadge.setStyleSheet(f"color: {out_color}; font-family: 'Menlo', monospace; font-size: 10px; font-weight: 700;")
            st_row.addWidget(sname, 1)
            st_row.addWidget(obadge)
            sv.addLayout(st_row)

            smeta = QLabel(
                f"Attempts: {step.get('attempts', 0)}/{step.get('max_attempts', 1)}  •  "
                f"Approval Gate: {'YES' if step.get('requires_approval') else 'NO'}  •  "
                f"Args: {step.get('args', {})}"
            )
            smeta.setObjectName("meta_label")
            smeta.setWordWrap(True)
            sv.addWidget(smeta)

            if step.get("result"):
                rlbl = QLabel(f"Result: {step['result'][:240]}")
                rlbl.setObjectName("meta_label")
                rlbl.setWordWrap(True)
                sv.addWidget(rlbl)
            if step.get("error"):
                elbl = QLabel(f"Step Error: {step['error']}")
                elbl.setStyleSheet("color: #EF4444; font-family: 'Menlo', monospace; font-size: 10.5px;")
                elbl.setWordWrap(True)
                sv.addWidget(elbl)

            self.insp_layout.insertWidget(self.insp_layout.count() - 1, scard)

    def update_task_events(self, task_id: str, page_data: dict, append: bool = False):
        if task_id != self._selected_task_id and self._selected_task_id:
            return
        items = page_data.get("items", [])
        self._events_total = int(page_data.get("total", len(items)))
        self._events_has_more = bool(page_data.get("has_more", False))
        if append:
            self._events.extend(items)
        else:
            self._events = list(items)

        while self.tl_layout.count() > 1:
            item = self.tl_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._events:
            empty = QLabel("No execution events recorded for this task.")
            empty.setObjectName("meta_label")
            self.tl_layout.insertWidget(0, empty)
            self.load_more_events_btn.hide()
            return

        for ev in self._events:
            card = QFrame()
            card.setObjectName("panel_card")
            v = QVBoxLayout(card)
            v.setContentsMargins(10, 6, 10, 6)
            v.setSpacing(2)

            ts = (ev.get("timestamp") or "")[:19].replace("T", " ")
            step_str = f"step {ev['step_index']}" if ev.get("step_index") is not None else "task"
            hdr = QLabel(f"[{ts}] {ev.get('event_type', '').upper()}  ({step_str} • {ev.get('status', '')})")
            hdr.setObjectName("accent_label")
            hdr.setWordWrap(True)
            msg = QLabel(ev.get("message", ""))
            msg.setObjectName("meta_label")
            msg.setWordWrap(True)
            v.addWidget(hdr)
            v.addWidget(msg)
            self.tl_layout.insertWidget(self.tl_layout.count() - 1, card)

        if self._events_has_more:
            self.load_more_events_btn.setText(f"LOAD MORE ({len(self._events)}/{self._events_total})")
            self.load_more_events_btn.show()
        else:
            self.load_more_events_btn.hide()

    def update_approvals(self, approvals: list[dict]):
        self._approvals = approvals or []
        self._inflight_approvals.intersection_update({a.get("id", "") for a in self._approvals})
        self._sub_btns[1].setText(f"APPROVAL CENTRE ({len(self._approvals)})")

        while self.apr_layout.count() > 1:
            item = self.apr_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._approvals:
            empty = QLabel("No pending approvals for this conversation.")
            empty.setObjectName("meta_label")
            self.apr_layout.insertWidget(0, empty)
            return

        now = datetime.now()
        for apr in self._approvals:
            aid = apr.get("id", "")
            status = apr.get("status", "pending")
            expires_at = apr.get("expires_at")
            is_expired = False
            if expires_at:
                try:
                    is_expired = now > datetime.fromisoformat(expires_at)
                except ValueError:
                    is_expired = False

            is_uncertain = "unknown" in (apr.get("reason") or "").lower() or "uncertain" in (apr.get("reason") or "").lower()
            is_actionable = status == "pending" and not is_expired and aid not in self._inflight_approvals

            card = QFrame()
            card.setObjectName("panel_card")
            v = QVBoxLayout(card)
            v.setContentsMargins(12, 10, 12, 10)
            v.setSpacing(6)

            hdr = QLabel(
                f"APPROVAL {aid}  •  Task {apr.get('task_id', '')} (Step {apr.get('step_index', 0)})"
            )
            hdr.setObjectName("accent_label")
            hdr.setWordWrap(True)
            v.addWidget(hdr)

            if is_uncertain:
                unc_lbl = QLabel("STATE: UNCERTAIN — Previous execution was interrupted; outcome is unknown.")
                unc_lbl.setStyleSheet("color: #F59E0B; font-family: 'Menlo', monospace; font-size: 10.5px; font-weight: 700;")
                unc_lbl.setWordWrap(True)
                v.addWidget(unc_lbl)

            if is_expired or status != "pending":
                st_lbl = QLabel(f"NON-ACTIONABLE: {'EXPIRED' if is_expired else status.upper()}")
                st_lbl.setStyleSheet("color: #EF4444; font-family: 'Menlo', monospace; font-size: 10.5px; font-weight: 700;")
                v.addWidget(st_lbl)

            summary_lbl = QLabel(
                f"Action: {apr.get('action_summary') or apr.get('action', '')}\n"
                f"Reason: {apr.get('reason', '')}\n"
                f"Payload Hash: {(apr.get('action_payload_hash') or '')[:16]}…"
            )
            summary_lbl.setObjectName("meta_label")
            summary_lbl.setWordWrap(True)
            v.addWidget(summary_lbl)

            btn_row = QHBoxLayout()
            btn_row.setSpacing(6)

            app_btn = QPushButton("APPROVE RE-RUN" if is_uncertain else "APPROVE EXECUTION")
            app_btn.setObjectName("primary_btn")
            app_btn.setEnabled(is_actionable)
            app_btn.clicked.connect(
                lambda checked=False, approval_id=aid: self._resolve_approval(approval_id, "approve")
            )
            btn_row.addWidget(app_btn)

            if is_uncertain:
                mark_btn = QPushButton("MARK ALREADY COMPLETED")
                mark_btn.setObjectName("secondary_btn")
                mark_btn.setEnabled(is_actionable)
                mark_btn.clicked.connect(
                    lambda checked=False, approval_id=aid: self._resolve_approval(approval_id, "mark_completed")
                )
                btn_row.addWidget(mark_btn)

            rej_btn = QPushButton("REJECT & CANCEL")
            rej_btn.setObjectName("secondary_btn")
            rej_btn.setEnabled(is_actionable)
            rej_btn.clicked.connect(
                lambda checked=False, approval_id=aid: self._resolve_approval(approval_id, "reject")
            )
            btn_row.addWidget(rej_btn)
            btn_row.addStretch()
            v.addLayout(btn_row)

            self.apr_layout.insertWidget(self.apr_layout.count() - 1, card)

    def _resolve_approval(self, approval_id: str, decision: str):
        self._inflight_approvals.add(approval_id)
        self.update_approvals(self._approvals)
        self.resolve_approval_requested.emit(approval_id, decision)
