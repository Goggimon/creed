# gui/main_window.py

import os
import sys
from datetime import datetime
import httpx
from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPixmap, QRadialGradient, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from worker import WebSocketWorker
from components.chat_view import ChatView
from components.command_palette import CommandPalette
from components.global_hotkey import MacGlobalHotkey
from components.input_bar import InputBar
from components.radial_hub import CORE_STATE_THEMES, RadialHubWidget
from components.tabs import (
    MemoryTab,
    ModelsTab,
    SettingsTab,
    SystemsTab,
    ToolsTab,
)
from components.tasks_tab import TasksTab


class SpatialCanvasFrame(QFrame):
    """Cached deep atmospheric backdrop for all Spatial OS views."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bg_cache = None
        self._bg_size = (0, 0)

    def _build_bg(self, w: int, h: int) -> QPixmap:
        pix = QPixmap(w, h)
        pix.fill(QColor("#07080C"))
        p = QPainter()
        if not p.begin(pix):
            return pix
        try:
            g1 = QRadialGradient(w * 0.18, h * 0.15, max(w, h) * 0.55)
            g1.setColorAt(0.0, QColor(103, 232, 249, 14))
            g1.setColorAt(1.0, QColor(7, 8, 12, 0))
            p.fillRect(0, 0, w, h, g1)

            g2 = QRadialGradient(w * 0.85, h * 0.82, max(w, h) * 0.50)
            g2.setColorAt(0.0, QColor(167, 139, 250, 14))
            g2.setColorAt(1.0, QColor(7, 8, 12, 0))
            p.fillRect(0, 0, w, h, g2)
        finally:
            p.end()
        return pix

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
            w, h = self.width(), self.height()
            if self._bg_cache is None or self._bg_size != (w, h):
                self._bg_cache = self._build_bg(w, h)
                self._bg_size = (w, h)
            painter.drawPixmap(0, 0, self._bg_cache)
        finally:
            painter.end()


class ConnectionOverlay(QFrame):
    """Translucent overlay displayed when backend connection is lost."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("connection_overlay")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        card = QFrame()
        card.setObjectName("connection_overlay_card")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(28, 18, 28, 18)
        card_lay.setSpacing(6)

        title = QLabel("BACKEND OFFLINE // RETRYING")
        title.setObjectName("connection_overlay_title")
        title.setAlignment(Qt.AlignCenter)

        sub = QLabel("Waiting for CREED FastAPI server (localhost:8000)")
        sub.setObjectName("meta_label")
        sub.setAlignment(Qt.AlignCenter)

        card_lay.addWidget(title)
        card_lay.addWidget(sub)
        layout.addWidget(card)
        self.hide()


class ApiWorker(QThread):
    response_ready = Signal(str, dict)
    api_error = Signal(str, str)

    def __init__(self, method="GET", path="/api/snapshot", payload=None, tag="snapshot"):
        super().__init__()
        self.method = method
        self.path = path
        self.payload = payload
        self.tag = tag

    def run(self):
        base = "http://localhost:8000"
        req_timeout = 10.0
        try:
            with httpx.Client(timeout=req_timeout) as client:
                resp = client.request(self.method, f"{base}{self.path}", json=self.payload)
                if resp.status_code >= 400:
                    detail = ""
                    try:
                        detail = resp.json().get("detail", "")
                    except Exception:
                        detail = resp.text[:200]
                    raise RuntimeError(f"HTTP {resp.status_code}: {detail or resp.reason_phrase}")
                data = resp.json()
                self.response_ready.emit(self.tag, data)
                if self.tag not in (
                    "snapshot",
                    "load_convo",
                    "tasks_list",
                    "task_detail",
                    "task_events",
                    "task_events_more",
                    "approvals_list",
                    "task_mutate",
                ):
                    snap = client.get(f"{base}/api/snapshot")
                    snap.raise_for_status()
                    self.response_ready.emit("snapshot", snap.json())
        except Exception as e:
            self.api_error.emit(self.tag, str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.resize(1340, 840)
        self.setMinimumSize(1040, 660)

        self._old_pos = None
        self.current_ai_bubble = None
        self._active_api_workers = []
        self._uptime_seconds = 0
        self._is_connected = False
        self._history_loaded = False
        self._current_session_id = "default"
        self._active_chat_target = "default"
        self._shutting_down = False

        self.init_ui()
        self.apply_styles()

        self.ws_worker = WebSocketWorker()
        self.ws_worker.status_received.connect(self.on_status_changed)
        self.ws_worker.token_received.connect(self.append_token)
        self.ws_worker.done_received.connect(self.on_response_done)
        self.ws_worker.user_transcription_received.connect(self.handle_transcription)
        self.ws_worker.error_received.connect(self.on_error)
        self.ws_worker.connected_signal.connect(self.on_connected)
        self.ws_worker.disconnected_signal.connect(self.on_disconnected)
        self.ws_worker.task_update_received.connect(self.on_task_update)
        self.ws_worker.route_update_received.connect(self.on_route_update)
        self.ws_worker.start()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()
        self._update_clock()

        self._snapshot_timer = QTimer(self)
        self._snapshot_timer.setInterval(5000)
        self._snapshot_timer.timeout.connect(self.fetch_snapshot)
        self._snapshot_timer.start()

        self.global_hotkey = MacGlobalHotkey(self)
        self.global_hotkey.triggered.connect(self.summon_spotlight)
        self.global_hotkey.start()

    def init_ui(self):
        self.central = QWidget()
        self.central.setObjectName("central_widget")
        self.setCentralWidget(self.central)

        root_layout = QVBoxLayout(self.central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Slim Top Telemetry Header
        self.title_bar = QFrame()
        self.title_bar.setFixedHeight(42)
        self.title_bar.setObjectName("top_telemetry_bar")
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(14, 0, 14, 0)
        title_layout.setSpacing(12)

        self.min_btn = QPushButton("—")
        self.max_btn = QPushButton("▢")
        self.close_btn = QPushButton("✕")
        for btn in (self.min_btn, self.max_btn, self.close_btn):
            btn.setObjectName("win_btn")
            btn.setFixedSize(24, 20)

        self.title_label = QLabel("CREED")
        self.title_label.setObjectName("tab_title")
        self.version_label = QLabel("v3.5.0")
        self.version_label.setObjectName("meta_label")

        self.top_status_pill = QLabel("● CONNECTING")
        self.top_status_pill.setObjectName("accent_label")

        self.top_services_label = QLabel("UVICORN: --  •  OLLAMA: --")
        self.top_services_label.setObjectName("meta_label")

        self.top_model_label = QLabel("MODEL: --")
        self.top_model_label.setObjectName("meta_label")

        self.cmd_btn = QPushButton("⌘K  COMMAND")
        self.cmd_btn.setObjectName("cmd_btn")
        self.cmd_btn.clicked.connect(self.open_command_palette)
        self._cmd_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self._cmd_shortcut.activated.connect(self.open_command_palette)

        self.command_palette = CommandPalette(self)
        self.command_palette.tab_requested.connect(self.switch_tab)
        self.command_palette.prompt_requested.connect(self.handle_overview_send)
        self.command_palette.voice_requested.connect(self.handle_voice_toggle)

        self.clock_label = QLabel("")
        self.clock_label.setObjectName("meta_label")

        if sys.platform == "darwin":
            title_layout.addWidget(self.close_btn)
            title_layout.addWidget(self.min_btn)
            title_layout.addWidget(self.max_btn)
            title_layout.addSpacing(8)
        title_layout.addWidget(self.title_label)
        title_layout.addWidget(self.version_label)
        title_layout.addWidget(self.top_status_pill)
        title_layout.addStretch()
        title_layout.addWidget(self.top_services_label)
        title_layout.addWidget(self.top_model_label)
        title_layout.addWidget(self.cmd_btn)
        title_layout.addWidget(self.clock_label)
        if sys.platform != "darwin":
            title_layout.addWidget(self.min_btn)
            title_layout.addWidget(self.max_btn)
            title_layout.addWidget(self.close_btn)

        root_layout.addWidget(self.title_bar)

        # 2. Full-Bleed Spatial Workspace (NO Left Sidebar, NO Right Box)
        self.workspace_frame = SpatialCanvasFrame()
        self.workspace_frame.setObjectName("workspace_frame")
        ws_layout = QVBoxLayout(self.workspace_frame)
        ws_layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        ws_layout.addWidget(self.stack)
        self.connection_overlay = ConnectionOverlay(self.workspace_frame)
        root_layout.addWidget(self.workspace_frame, 1)

        # Tab 0: Spatial Intelligence Hub (Pre-Rendered Holographic Dot-Mesh Core + Floating Command Input)
        overview_page = QWidget()
        ov_lay = QVBoxLayout(overview_page)
        ov_lay.setContentsMargins(18, 10, 18, 14)
        ov_lay.setSpacing(8)

        self.radial_hub = RadialHubWidget()
        self.radial_hub.node_clicked.connect(self.switch_tab)

        ov_bottom = QHBoxLayout()
        ov_bottom.setSpacing(14)
        self.hub_activity_ticker = QLabel("SYSTEM READY // AWAITING DIRECTIVE")
        self.hub_activity_ticker.setObjectName("meta_label")
        self.hub_activity_ticker.setMinimumWidth(260)

        self.overview_input = InputBar("Direct command to CREED Intelligence...")
        self.overview_input.submitted.connect(self.handle_overview_send)
        self.overview_input.voice_clicked.connect(self.handle_voice_toggle)
        self.overview_input.stop_clicked.connect(self.stop_generation)
        ov_bottom.addWidget(self.hub_activity_ticker)
        ov_bottom.addWidget(self.overview_input, 1)

        ov_lay.addWidget(self.radial_hub, 1)
        ov_lay.addLayout(ov_bottom)

        # Tab 1: Editorial Conversational Intelligence (Left context strip + Right borderless stream)
        conv_page = QWidget()
        conv_root = QHBoxLayout(conv_page)
        conv_root.setContentsMargins(18, 14, 18, 14)
        conv_root.setSpacing(18)

        conv_rail = QFrame()
        conv_rail.setFixedWidth(220)
        conv_rail.setObjectName("panel_card")
        cr_lay = QVBoxLayout(conv_rail)
        cr_lay.setContentsMargins(14, 14, 14, 14)
        cr_lay.setSpacing(10)

        cr_tag = QLabel("CREED / SYS-01")
        cr_tag.setObjectName("section_header")
        self.conv_title_label = QLabel("Primary Session")
        self.conv_title_label.setObjectName("tab_title")
        self.conv_title_label.setWordWrap(True)

        self.conv_model_meta = QLabel("Model: --")
        self.conv_model_meta.setObjectName("accent_label")
        self.conv_uptime_meta = QLabel("Uptime: 00:00:00")
        self.conv_uptime_meta.setObjectName("meta_label")

        hist_btn = QPushButton("Browse Sessions ▸")
        hist_btn.setObjectName("secondary_btn")
        hist_btn.clicked.connect(lambda: self.switch_tab(2))

        act_hdr = QLabel("RECENT TELEMETRY")
        act_hdr.setObjectName("section_header")
        self.activity_feed = QLabel("Waiting for telemetry...")
        self.activity_feed.setObjectName("meta_label")
        self.activity_feed.setWordWrap(True)
        self.activity_feed.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        route_hdr = QLabel("ROUTING STATE")
        route_hdr.setObjectName("section_header")
        self.route_provider_label = QLabel("Provider: --")
        self.route_provider_label.setObjectName("meta_label")
        self.route_model_label = QLabel("Model: --")
        self.route_model_label.setObjectName("meta_label")
        self.route_model_label.setWordWrap(True)
        self.route_tier_label = QLabel("Tier: --")
        self.route_tier_label.setObjectName("meta_label")
        self.route_reason_label = QLabel("Reason: --")
        self.route_reason_label.setObjectName("meta_label")
        self.route_reason_label.setWordWrap(True)
        self.route_privacy_label = QLabel("Privacy: --")
        self.route_privacy_label.setObjectName("meta_label")
        self.route_consent_label = QLabel("Cloud Consent: OFF")
        self.route_consent_label.setObjectName("meta_label")
        self.route_fallback_label = QLabel("Fallback: NONE")
        self.route_fallback_label.setObjectName("meta_label")
        self.route_fallback_label.setWordWrap(True)

        cr_lay.addWidget(cr_tag)
        cr_lay.addWidget(self.conv_title_label)
        cr_lay.addWidget(self.conv_model_meta)
        cr_lay.addWidget(self.conv_uptime_meta)
        cr_lay.addWidget(hist_btn)
        cr_lay.addSpacing(6)
        cr_lay.addWidget(route_hdr)
        cr_lay.addWidget(self.route_provider_label)
        cr_lay.addWidget(self.route_model_label)
        cr_lay.addWidget(self.route_tier_label)
        cr_lay.addWidget(self.route_reason_label)
        cr_lay.addWidget(self.route_privacy_label)
        cr_lay.addWidget(self.route_consent_label)
        cr_lay.addWidget(self.route_fallback_label)
        cr_lay.addSpacing(6)
        cr_lay.addWidget(act_hdr)
        cr_lay.addWidget(self.activity_feed, 1)

        conv_main = QWidget()
        cm_lay = QVBoxLayout(conv_main)
        cm_lay.setContentsMargins(0, 0, 0, 0)
        cm_lay.setSpacing(10)
        self.chat_view = ChatView()
        self.input_bar = InputBar("Communicate with CREED... (Shift+Enter for newline)", enable_cloud_consent=True)
        self.input_bar.submitted.connect(self.handle_send)
        self.input_bar.stop_clicked.connect(self.stop_generation)
        self.input_bar.voice_clicked.connect(self.handle_voice_toggle)
        cm_lay.addWidget(self.chat_view, 1)
        cm_lay.addWidget(self.input_bar)

        conv_root.addWidget(conv_rail)
        conv_root.addWidget(conv_main, 1)

        # Tabs 2..10
        self.memory_tab = MemoryTab()
        self.memory_tab.add_note_requested.connect(self.add_memory_note)
        self.memory_tab.delete_note_requested.connect(self.delete_memory_note)
        self.memory_tab.conversation_selected.connect(self.open_conversation)
        self.memory_tab.new_conversation_requested.connect(self.create_new_conversation)
        self.memory_tab.delete_conversation_requested.connect(self.delete_conversation)

        self.tasks_tab = TasksTab()
        self.tasks_tab.refresh_tasks_requested.connect(self.fetch_tasks)
        self.tasks_tab.select_task_requested.connect(self.fetch_task_detail_and_events)
        self.tasks_tab.load_more_events_requested.connect(self.fetch_more_task_events)
        self.tasks_tab.pause_task_requested.connect(self.pause_task)
        self.tasks_tab.resume_task_requested.connect(self.resume_task)
        self.tasks_tab.cancel_task_requested.connect(self.cancel_task)
        self.tasks_tab.refresh_approvals_requested.connect(self.fetch_approvals)
        self.tasks_tab.resolve_approval_requested.connect(self.resolve_approval)

        self.automation_tab = self.tasks_tab.workflows_tab
        self.automation_tab.run_workflow_requested.connect(self.run_workflow)
        self.automation_tab.create_workflow_requested.connect(self.create_workflow)
        self.automation_tab.delete_workflow_requested.connect(self.delete_workflow)

        self.systems_tab = SystemsTab()
        self.systems_tab.refresh_requested.connect(self.fetch_snapshot)

        self.tools_tab = ToolsTab()

        self.models_tab = ModelsTab()
        self.models_tab.select_model_requested.connect(self.select_model)
        self.models_tab.pull_model_requested.connect(self.pull_model)
        self.models_tab.delete_model_requested.connect(self.delete_model)
        self.models_tab.refresh_requested.connect(self.fetch_snapshot)

        self.settings_tab = SettingsTab()
        self.settings_tab.save_requested.connect(self.save_settings)
        self.settings_tab.restart_gui_requested.connect(self.restart_gui)

        for page in (
            overview_page,
            conv_page,
            self.memory_tab,
            self.tasks_tab,
            self.systems_tab,
            self.tools_tab,
            self.models_tab,
            self.settings_tab,
        ):
            self.stack.addWidget(page)

        # 3. Bottom Spatial Navigation Dock
        self.bottom_dock = QFrame()
        self.bottom_dock.setFixedHeight(44)
        self.bottom_dock.setObjectName("bottom_spatial_dock")
        dock_lay = QHBoxLayout(self.bottom_dock)
        dock_lay.setContentsMargins(14, 4, 14, 4)
        dock_lay.setSpacing(4)

        self.nav_buttons = []
        nav_items = [
            ("00 HUB", 0),
            ("01 INTELLIGENCE", 1),
            ("02 MEMORY", 2),
            ("03 TASKS", 3),
            ("04 MACHINE", 4),
            ("05 TOOLS", 5),
            ("06 MODELS", 6),
            ("07 CONFIG", 7),
        ]
        dock_lay.addStretch()
        for label, idx in nav_items:
            btn = QPushButton(label)
            btn.setObjectName("dock_btn")
            btn.setProperty("active", "true" if idx == 0 else "false")
            btn.clicked.connect(lambda checked=False, i=idx: self.switch_tab(i))
            dock_lay.addWidget(btn)
            self.nav_buttons.append(btn)
        dock_lay.addStretch()

        root_layout.addWidget(self.bottom_dock)

        self.min_btn.clicked.connect(self.showMinimized)
        self.close_btn.clicked.connect(self.close)
        self.max_btn.clicked.connect(self.toggle_fullscreen)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "connection_overlay") and hasattr(self, "workspace_frame"):
            self.connection_overlay.setGeometry(self.workspace_frame.rect())

    def summon_spotlight(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        self.open_command_palette()

    def open_command_palette(self):
        self.command_palette.show_centered()

    def switch_tab(self, index: int):
        if self.stack.currentIndex() != index:
            self.stack.setCurrentIndex(index)
            page = self.stack.currentWidget()
            if page is not None:
                self._page_anim = QPropertyAnimation(page, b"pos", self)
                self._page_anim.setDuration(180)
                self._page_anim.setEasingCurve(QEasingCurve.OutQuart)
                self._page_anim.setStartValue(QPoint(0, 10))
                self._page_anim.setEndValue(QPoint(0, 0))
                self._page_anim.start()
        for idx, btn in enumerate(self.nav_buttons):
            btn.setProperty("active", "true" if idx == index else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if index == 3 and self._is_connected:
            self.fetch_tasks("")
            self.fetch_approvals()
        if index in (2, 3, 4, 5, 6, 7) and self._is_connected:
            self.fetch_snapshot()

    def apply_styles(self):
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            qss_path = os.path.join(current_dir, "styles", "theme.qss")
            if os.path.exists(qss_path):
                with open(qss_path, "r", encoding="utf-8") as f:
                    self.setStyleSheet(f.read())
        except Exception as e:
            print("Failed to apply stylesheet:", e)

    def _format_uptime(self, secs: int) -> str:
        hrs, rem = divmod(max(0, int(secs)), 3600)
        mins, s = divmod(rem, 60)
        return f"{hrs:02d}:{mins:02d}:{s:02d}"

    def _update_clock(self):
        self.clock_label.setText(datetime.now().strftime("%H:%M:%S"))
        if self._is_connected:
            self._uptime_seconds += 1
            self.conv_uptime_meta.setText(f"Uptime: {self._format_uptime(self._uptime_seconds)}")

    def _run_api(self, method: str, path: str, payload: dict = None, tag: str = "snapshot"):
        if self._shutting_down:
            return
        worker = ApiWorker(method=method, path=path, payload=payload, tag=tag)
        worker.response_ready.connect(self._on_api_response)
        worker.api_error.connect(self._on_api_error)
        worker.finished.connect(
            lambda w=worker: self._active_api_workers.remove(w)
            if w in self._active_api_workers
            else None
        )
        self._active_api_workers.append(worker)
        worker.start()

    def _on_api_error(self, tag: str, err: str):
        if tag == "save_settings":
            self.settings_tab.set_save_status(f"Save failed: {err}", is_error=True)
        elif tag in ("tasks_list", "task_detail", "task_events", "task_events_more", "approvals_list", "task_mutate"):
            self.tasks_tab.show_error(err)
            if tag == "task_mutate":
                self.fetch_approvals()
                self.fetch_tasks("")

    def _on_api_response(self, tag: str, data: dict):
        if tag == "save_settings":
            self.settings_tab.set_save_status("Saved to .env and applied.")
        elif tag == "snapshot":
            self.on_snapshot_received(data)
        elif tag == "tasks_list":
            self.tasks_tab.clear_error()
            self.tasks_tab.update_tasks(data.get("tasks", []))
        elif tag == "task_detail":
            self.tasks_tab.clear_error()
            self.tasks_tab.update_selected_task(data)
        elif tag == "task_events":
            self.tasks_tab.update_task_events(data.get("task_id", ""), data, append=False)
        elif tag == "task_events_more":
            self.tasks_tab.update_task_events(data.get("task_id", ""), data, append=True)
        elif tag == "approvals_list":
            self.tasks_tab.update_approvals(data.get("approvals", []))
        elif tag == "task_mutate":
            self.tasks_tab.clear_error()
            self.fetch_tasks("")
            self.fetch_approvals()
            tid = (data.get("task") or {}).get("id") or (data.get("approval") or {}).get("task_id")
            if tid:
                self.fetch_task_detail_and_events(tid)
        elif tag == "load_convo":
            self.chat_view.clear_bubbles()
            self.current_ai_bubble = None
            for msg in data.get("messages", []):
                self.chat_view.add_bubble(msg.get("content", ""), msg.get("role") == "user")
            self.switch_tab(1)
        elif tag == "new_convo":
            convo = data.get("conversation", {})
            sid = convo.get("id", "default")
            self._current_session_id = sid
            self.conv_title_label.setText("New Session")
            self.chat_view.clear_bubbles()
            self.current_ai_bubble = None
            self.switch_tab(1)

    def fetch_tasks(self, status_filter: str = ""):
        if not self._is_connected:
            return
        qs = f"?conversation_id={self._current_session_id}"
        if status_filter:
            qs += f"&status={status_filter}"
        self._run_api("GET", f"/api/tasks{qs}", tag="tasks_list")

    def fetch_task_detail_and_events(self, task_id: str):
        if not self._is_connected or not task_id:
            return
        self._run_api("GET", f"/api/tasks/{task_id}?conversation_id={self._current_session_id}", tag="task_detail")
        self._run_api("GET", f"/api/tasks/{task_id}/events?conversation_id={self._current_session_id}&offset=0&limit=50", tag="task_events")

    def fetch_more_task_events(self, task_id: str, offset: int):
        if not self._is_connected or not task_id:
            return
        self._run_api("GET", f"/api/tasks/{task_id}/events?conversation_id={self._current_session_id}&offset={offset}&limit=50", tag="task_events_more")

    def pause_task(self, task_id: str):
        self._run_api("POST", f"/api/tasks/{task_id}/pause?conversation_id={self._current_session_id}", tag="task_mutate")

    def resume_task(self, task_id: str):
        self._run_api("POST", f"/api/tasks/{task_id}/resume?conversation_id={self._current_session_id}", tag="task_mutate")

    def cancel_task(self, task_id: str):
        self._run_api("POST", f"/api/tasks/{task_id}/cancel?conversation_id={self._current_session_id}", tag="task_mutate")

    def fetch_approvals(self):
        if not self._is_connected:
            return
        self._run_api("GET", f"/api/approvals?conversation_id={self._current_session_id}", tag="approvals_list")

    def resolve_approval(self, approval_id: str, decision: str):
        self._run_api(
            "POST",
            f"/api/approvals/{approval_id}/resolve?conversation_id={self._current_session_id}",
            {"decision": decision, "resolved_by": "user"},
            tag="task_mutate",
        )

    def on_task_update(self, payload: dict):
        conv_id = payload.get("conversation_id")
        if conv_id and conv_id != self._current_session_id:
            return
        if self.stack.currentIndex() == 3 or payload.get("event_type") in ("approval_requested", "approval_granted", "approval_rejected"):
            self.fetch_tasks("")
            self.fetch_approvals()
            tid = payload.get("task_id")
            if tid and tid == self.tasks_tab._selected_task_id:
                self.fetch_task_detail_and_events(tid)

    def fetch_snapshot(self):
        if self._is_connected:
            self._run_api("GET", "/api/snapshot", tag="snapshot")

    def add_memory_note(self, tag: str, note: str):
        self._run_api("POST", "/api/memory/note", {"tag": tag, "note": note}, tag="mutate")

    def delete_memory_note(self, note_id: int):
        self._run_api("DELETE", f"/api/memory/note/{note_id}", tag="mutate")

    def open_conversation(self, session_id: str, title: str):
        self._current_session_id = session_id
        self.conv_title_label.setText(title)
        self._run_api("GET", f"/api/conversations/{session_id}", tag="load_convo")

    def create_new_conversation(self):
        self._run_api("POST", "/api/conversations", {"title": "New Conversation"}, tag="new_convo")

    def delete_conversation(self, session_id: str):
        if session_id == self._current_session_id:
            self._current_session_id = "default"
            self.conv_title_label.setText("Primary Session")
            self.chat_view.clear_bubbles()
        self._run_api("DELETE", f"/api/conversations/{session_id}", tag="mutate")

    def run_workflow(self, workflow_id: int):
        self.radial_hub.pulse_node("AUTOMATION")
        self._run_api("POST", f"/api/workflows/{workflow_id}/run", tag="mutate")

    def create_workflow(self, name: str, description: str, steps: list):
        self._run_api(
            "POST",
            "/api/workflows",
            {"name": name, "description": description, "steps": steps},
            tag="mutate",
        )

    def delete_workflow(self, workflow_id: int):
        self._run_api("DELETE", f"/api/workflows/{workflow_id}", tag="mutate")

    def save_settings(self, cfg: dict):
        self._run_api("POST", "/api/settings", cfg, tag="save_settings")

    def select_model(self, model: str):
        self._run_api("POST", "/api/models/select", {"model": model}, tag="mutate")

    def pull_model(self, model: str):
        self._snapshot_timer.setInterval(1200)
        self._run_api("POST", "/api/models/pull", {"model": model}, tag="mutate")

    def delete_model(self, model: str):
        self._run_api("POST", "/api/models/delete", {"model": model}, tag="mutate")


    def on_snapshot_received(self, data: dict):
        self.version_label.setText(f"v{data.get('version', '3.5.0')}")
        self._uptime_seconds = int(data.get("uptime_seconds", self._uptime_seconds))
        self.conv_uptime_meta.setText(f"Uptime: {self._format_uptime(self._uptime_seconds)}")

        model = data.get("model", "unknown")
        ollama_ok = data.get("ollama_online", False)
        self.top_model_label.setText(f"MODEL: {model}")
        self.conv_model_meta.setText(f"Model: {model}")
        self.top_services_label.setText(
            f"UVICORN: ONLINE  •  OLLAMA: {'ONLINE' if ollama_ok else 'OFFLINE'}"
        )

        tools = data.get("tools", [])
        ollama_models = data.get("ollama_models", [])
        pull_info = data.get("model_pull", {})
        if pull_info.get("active"):
            if self._snapshot_timer.interval() != 1200:
                self._snapshot_timer.setInterval(1200)
        elif self._snapshot_timer.interval() != 5000:
            self._snapshot_timer.setInterval(5000)

        self.memory_tab.update_data(data.get("memory", {}), data.get("conversations", []))
        router_data = data.get("router", {})
        self.systems_tab.update_data(
            data.get("systems", []),
            data.get("latency", {}),
            router_data,
        )
        self.on_route_update(router_data)
        self.tools_tab.update_data(tools, data.get("tool_history", []))
        self.automation_tab.update_data(data.get("workflows", []), tools)
        cfg_data = data.get("config", {})
        self.models_tab.update_data(model, ollama_models, pull_info, ollama_ok)
        self.settings_tab.update_data(cfg_data, ollama_models)
        self.input_bar.update_routing_options(
            data.get("provider_catalog", {}),
            ollama_models,
            cloud_model=cfg_data.get("cloud_model", ""),
        )


        if not self._history_loaded:
            self._history_loaded = True
            for msg in data.get("chat_history", []):
                self.chat_view.add_bubble(msg.get("content", ""), msg.get("role") == "user")

        activity = data.get("activity", [])
        if activity:
            latest = activity[0]
            self.hub_activity_ticker.setText(
                f"[{latest.get('timestamp', '')}] {latest.get('node', '')}: {latest.get('message', '')[:42]}"
            )
            lines = [
                f"[{a.get('timestamp', '')}] {a.get('node', '')}: {a.get('message', '')}"
                for a in activity[:8]
            ]
            self.activity_feed.setText("\n\n".join(lines))

    # Window Drag (Title Bar Only)
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.position().toPoint().y() <= self.title_bar.height() + 6:
            self._old_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self._old_pos:
            delta = event.globalPosition().toPoint() - self._old_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self._old_pos = event.globalPosition().toPoint()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            if event.position().toPoint().y() <= self.title_bar.height() + 10:
                self.toggle_fullscreen()

    def mouseReleaseEvent(self, event):
        self._old_pos = None

    # Chat & Voice Logic
    def handle_overview_send(self, text: str):
        self.handle_send(text)

    def handle_send(self, text: str):
        if self._shutting_down:
            return
        self._active_chat_target = "default"
        allow_private_cloud = False
        try:
            sel_provider, sel_model = self.input_bar.get_routing_selection()
            allow_private_cloud = self.input_bar.consume_cloud_consent()
            self.chat_view.add_bubble(text, True)
            self.current_ai_bubble = self.chat_view.add_bubble("", False)
            self.radial_hub.pulse_node("CONVERSATION")
            msg = {
                "type": "chat",
                "text": text,
                "session_id": self._current_session_id,
                "allow_private_cloud": allow_private_cloud,
            }
            if sel_provider:
                msg["provider"] = sel_provider
            if sel_model:
                msg["model"] = sel_model
            self.ws_worker.send_message(msg)
        finally:
            self.input_bar.reset_cloud_consent()

    def on_route_update(self, route: dict):
        if not route:
            self.route_provider_label.setText("Provider: --")
            self.route_model_label.setText("Model: --")
            self.route_tier_label.setText("Tier: --")
            self.route_reason_label.setText("Reason: --")
            self.route_privacy_label.setText("Privacy: --")
            self.route_consent_label.setText("Cloud Consent: OFF")
            self.route_fallback_label.setText("Fallback: NONE")
            self.route_fallback_label.setStyleSheet("")
            return

        provider = route.get("provider") or "--"
        model = route.get("model") or "--"
        tier = str(route.get("tier") or "--").upper()
        reason = route.get("routing_reason") or "--"
        privacy = str(route.get("privacy_classification") or "--").upper()
        consent_on = bool(route.get("cloud_consent", False))
        fallback_occurred = bool(route.get("fallback_occurred", False))
        fallback_reason = route.get("fallback_reason") or ""
        status = route.get("status") or "confirmed"
        err = route.get("error") or ""

        self.route_provider_label.setText(f"Provider: {provider}")
        self.route_model_label.setText(f"Model: {model}")
        self.route_tier_label.setText(f"Tier: {tier}")
        self.route_reason_label.setText(f"Reason: {reason}")
        self.route_privacy_label.setText(f"Privacy: {privacy}")
        self.route_consent_label.setText(
            "Cloud Consent: ALLOWED (1-TURN)" if consent_on else "Cloud Consent: OFF"
        )

        if status == "failed" or err:
            self.route_fallback_label.setText(f"Failed: {err or 'provider unavailable'}")
            self.route_fallback_label.setStyleSheet(
                "color: #EF4444; font-family: 'Menlo', monospace; font-size: 10.5px;"
            )
        elif fallback_occurred:
            detail = f" ({fallback_reason})" if fallback_reason else ""
            self.route_fallback_label.setText(f"Fallback: YES{detail}")
            self.route_fallback_label.setStyleSheet(
                "color: #F59E0B; font-family: 'Menlo', monospace; font-size: 10.5px;"
            )
        else:
            self.route_fallback_label.setText("Fallback: NONE")
            self.route_fallback_label.setStyleSheet("")

    def handle_voice_toggle(self):
        self.radial_hub.pulse_node("VOICE")
        self.ws_worker.send_message({"type": "voice_toggle"})

    def stop_generation(self):
        self.ws_worker.send_message({"type": "stop"})

    def append_token(self, token: str):
        if self.current_ai_bubble is None:
            self.current_ai_bubble = self.chat_view.add_bubble("", False)
        self.current_ai_bubble.append_text(token)
        self.chat_view.scroll_to_bottom()

    def on_response_done(self):
        self.current_ai_bubble = None
        self.fetch_snapshot()

    def handle_transcription(self, text: str):
        self.chat_view.add_bubble(text, True)
        self.current_ai_bubble = self.chat_view.add_bubble("", False)

    def restart_gui(self):
        import subprocess
        from pathlib import Path

        app_path = Path(__file__).resolve().parent / "app.py"
        subprocess.Popen([sys.executable, str(app_path)], start_new_session=True)
        self.close()

    def on_status_changed(self, state: str):
        _, _, glow_hex, _ = CORE_STATE_THEMES.get(state, CORE_STATE_THEMES["Idle"])
        self.radial_hub.set_core_state(state)
        self.top_status_pill.setText(f"● {state.upper()}")
        self.top_status_pill.setStyleSheet(
            f"color: {glow_hex}; font-family: 'Menlo', monospace; font-size: 11px; font-weight: 700;"
        )

    def on_connected(self):
        self._is_connected = True
        self.connection_overlay.hide()
        self.tasks_tab.set_connection_state(True)
        self.on_status_changed("Idle")
        self.fetch_snapshot()
        self.fetch_tasks("")
        self.fetch_approvals()

    def on_disconnected(self):
        self._is_connected = False
        self.tasks_tab.set_connection_state(False)
        self.connection_overlay.setGeometry(self.workspace_frame.rect())
        self.connection_overlay.show()
        self.connection_overlay.raise_()
        self.top_services_label.setText("UVICORN: OFFLINE  •  OLLAMA: UNKNOWN")
        self.on_status_changed("Retrying Connection")

    def on_error(self, error: str):
        if "Connection lost" in error:
            self.on_disconnected()
            return
        self.current_ai_bubble = None
        self.chat_view.add_bubble(f"System: {error}", False)
        self.on_status_changed("Error")

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def closeEvent(self, event):
        # 1. Stop accepting new work
        self._shutting_down = True
        self.input_bar.setEnabled(False)
        # 2. Stop timers and background polling
        self._clock_timer.stop()
        self._snapshot_timer.stop()
        # 3. Signal workers to terminate & close connections
        self.global_hotkey.stop()
        self.ws_worker.stop()
        # 4. Bounded waits (never unbounded wait or os._exit)
        self.global_hotkey.wait(500)
        self.ws_worker.wait(800)
        for w in list(self._active_api_workers):
            if not w.wait(500) and w.isRunning():
                w.terminate()
                w.wait(200)
        self._active_api_workers.clear()
        # 5. Normal Qt shutdown
        event.accept()
        QApplication.quit()
