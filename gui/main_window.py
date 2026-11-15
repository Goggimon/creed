# gui/main_window.py

import os
import sys
from datetime import datetime
import httpx
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
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
from components.input_bar import InputBar
from components.insignia import CreedInsigniaWidget
from components.radial_hub import RadialHubWidget
from components.status_bar import StatusBar
from components.tabs import (
    AutomationTab,
    MemoryTab,
    SettingsTab,
    SystemsTab,
    ToolsTab,
    VoiceTab,
)


class TechWorkspaceFrame(QFrame):
    """Workspace container with subtle Swiss micro-grid and radial cyan glow."""

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        grad = QRadialGradient(w * 0.5, h * 0.45, max(w, h) * 0.65)
        grad.setColorAt(0.0, QColor(14, 34, 44, 75))
        grad.setColorAt(1.0, QColor(8, 11, 15, 0))
        painter.fillRect(0, 0, w, h, grad)

        step = 42
        painter.setPen(QPen(QColor(86, 217, 232, 9), 1.0))
        for x in range(0, w, step):
            painter.drawLine(x, 0, x, h)
        for y in range(0, h, step):
            painter.drawLine(0, y, w, y)


class ConnectionOverlay(QFrame):
    """Translucent shadow overlay displayed over the workspace when backend connection is lost."""

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

        title = QLabel("CONNECTION LOST, RETRYING…")
        title.setObjectName("connection_overlay_title")
        title.setAlignment(Qt.AlignCenter)

        sub = QLabel("Waiting for CREED backend (127.0.0.1:8000)")
        sub.setObjectName("meta_label")
        sub.setAlignment(Qt.AlignCenter)

        card_lay.addWidget(title)
        card_lay.addWidget(sub)
        layout.addWidget(card)
        self.hide()


class ApiWorker(QThread):
    response_ready = Signal(str, dict)
    api_error = Signal(str)

    def __init__(self, method="GET", path="/api/snapshot", payload=None, tag="snapshot"):
        super().__init__()
        self.method = method
        self.path = path
        self.payload = payload
        self.tag = tag

    def run(self):
        base = "http://localhost:8000"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.request(self.method, f"{base}{self.path}", json=self.payload)
                resp.raise_for_status()
                data = resp.json()
                self.response_ready.emit(self.tag, data)
                if self.tag not in ("snapshot", "load_convo"):
                    snap = client.get(f"{base}/api/snapshot")
                    snap.raise_for_status()
                    self.response_ready.emit("snapshot", snap.json())
        except Exception as e:
            self.api_error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.resize(1320, 820)
        self.setMinimumSize(1060, 680)

        self._old_pos = None
        self.current_ai_bubble = None
        self._right_collapsed = False
        self._active_api_workers = []
        self._uptime_seconds = 0
        self._is_connected = False
        self._history_loaded = False
        self._current_session_id = "default"

        self.init_ui()
        self.apply_styles()

        # WebSocket client
        self.ws_worker = WebSocketWorker()
        self.ws_worker.status_received.connect(self.on_status_changed)
        self.ws_worker.token_received.connect(self.append_token)
        self.ws_worker.done_received.connect(self.on_response_done)
        self.ws_worker.user_transcription_received.connect(self.handle_transcription)
        self.ws_worker.error_received.connect(self.on_error)
        self.ws_worker.connected_signal.connect(self.on_connected)
        self.ws_worker.disconnected_signal.connect(self.on_disconnected)
        self.ws_worker.start()

        # 1-second stopwatch & clock timer
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()
        self._update_clock()

        self._snapshot_timer = QTimer(self)
        self._snapshot_timer.setInterval(5000)
        self._snapshot_timer.timeout.connect(self.fetch_snapshot)
        self._snapshot_timer.start()

    def init_ui(self):
        self.central = QWidget()
        self.central.setObjectName("central_widget")
        self.setCentralWidget(self.central)

        root_layout = QVBoxLayout(self.central)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        # ----------------------------
        # Top Command Bar
        # ----------------------------
        self.title_bar = QFrame()
        self.title_bar.setFixedHeight(44)
        self.title_bar.setObjectName("title_bar")
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(12, 0, 12, 0)
        title_layout.setSpacing(10)

        self.min_btn = QPushButton("—")
        self.max_btn = QPushButton("▢")
        self.close_btn = QPushButton("✕")
        for btn in (self.min_btn, self.max_btn, self.close_btn):
            btn.setObjectName("win_btn")
            btn.setFixedSize(26, 22)

        self.top_insignia = CreedInsigniaWidget(size=24)
        self.title_label = QLabel("CREED")
        self.title_label.setObjectName("tab_title")
        self.version_label = QLabel("v2.0.0")
        self.version_label.setObjectName("meta_label")
        self.top_status_pill = QLabel("● RETRYING CONNECTION")
        self.top_status_pill.setObjectName("accent_label")

        self.clock_label = QLabel("")
        self.clock_label.setObjectName("meta_label")

        self.collapse_right_btn = QPushButton("PANEL ▸")
        self.collapse_right_btn.setObjectName("secondary_btn")
        self.collapse_right_btn.clicked.connect(self.toggle_right_panel)

        if sys.platform == "darwin":
            title_layout.addWidget(self.close_btn)
            title_layout.addWidget(self.min_btn)
            title_layout.addWidget(self.max_btn)
            title_layout.addSpacing(8)
            title_layout.addWidget(self.top_insignia)
            title_layout.addWidget(self.title_label)
            title_layout.addWidget(self.version_label)
            title_layout.addWidget(self.top_status_pill)
            title_layout.addStretch()
            title_layout.addWidget(self.clock_label)
            title_layout.addWidget(self.collapse_right_btn)
        else:
            title_layout.addWidget(self.top_insignia)
            title_layout.addWidget(self.title_label)
            title_layout.addWidget(self.version_label)
            title_layout.addWidget(self.top_status_pill)
            title_layout.addStretch()
            title_layout.addWidget(self.clock_label)
            title_layout.addWidget(self.collapse_right_btn)
            title_layout.addWidget(self.min_btn)
            title_layout.addWidget(self.max_btn)
            title_layout.addWidget(self.close_btn)

        root_layout.addWidget(self.title_bar)

        # ----------------------------
        # Main 3-Area Body
        # ----------------------------
        body_layout = QHBoxLayout()
        body_layout.setSpacing(8)
        root_layout.addLayout(body_layout, 1)

        # LEFT: Navigation Rail
        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(185)
        self.sidebar.setObjectName("sidebar")
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(10, 14, 10, 12)
        side_layout.setSpacing(4)

        brand_box = QVBoxLayout()
        brand_box.setAlignment(Qt.AlignCenter)
        self.side_insignia = CreedInsigniaWidget(size=54)
        brand_title = QLabel("CREED")
        brand_title.setObjectName("tab_title")
        brand_title.setAlignment(Qt.AlignCenter)
        brand_sub = QLabel("MULTI-SYSTEM AGENT")
        brand_sub.setObjectName("meta_label")
        brand_sub.setAlignment(Qt.AlignCenter)
        brand_box.addWidget(self.side_insignia, alignment=Qt.AlignCenter)
        brand_box.addWidget(brand_title)
        brand_box.addWidget(brand_sub)
        side_layout.addLayout(brand_box)
        side_layout.addSpacing(12)

        self.nav_buttons = []
        nav_items = [
            ("⌂  Overview", 0),
            ("◈  Conversation", 1),
            ("▤  Memory", 2),
            ("❖  Systems", 3),
            ("⚙  Tools", 4),
            ("◉  Voice", 5),
            ("⚡  Automation", 6),
            ("☰  Settings", 7),
        ]
        for label, idx in nav_items:
            btn = QPushButton(label)
            btn.setObjectName("nav_btn")
            btn.setProperty("active", "true" if idx == 0 else "false")
            btn.clicked.connect(lambda checked=False, i=idx: self.switch_tab(i))
            side_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        side_layout.addStretch()

        uptime_card = QFrame()
        uptime_card.setObjectName("panel_card")
        up_lay = QVBoxLayout(uptime_card)
        up_lay.setContentsMargins(10, 8, 10, 8)
        up_hdr = QLabel("SYSTEM UPTIME")
        up_hdr.setObjectName("section_header")
        self.uptime_value = QLabel("00:00:00")
        self.uptime_value.setObjectName("accent_label")
        up_lay.addWidget(up_hdr)
        up_lay.addWidget(self.uptime_value)
        side_layout.addWidget(uptime_card)

        # CENTRE: Tech Workspace Stack + Shadow Overlay
        self.workspace_frame = TechWorkspaceFrame()
        self.workspace_frame.setObjectName("workspace_frame")
        ws_layout = QVBoxLayout(self.workspace_frame)
        ws_layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        self._stack_opacity = QGraphicsOpacityEffect(self.stack)
        self.stack.setGraphicsEffect(self._stack_opacity)
        self._stack_anim = QPropertyAnimation(self._stack_opacity, b"opacity", self)
        self._stack_anim.setDuration(180)
        self._stack_anim.setEasingCurve(QEasingCurve.OutCubic)
        ws_layout.addWidget(self.stack)

        self.connection_overlay = ConnectionOverlay(self.workspace_frame)

        # Tab 0: Overview (Holographic Nucleus + Quick Command Input)
        overview_page = QWidget()
        ov_lay = QVBoxLayout(overview_page)
        ov_lay.setContentsMargins(12, 10, 12, 10)
        ov_lay.setSpacing(6)
        ov_hdr = QLabel("CREED // CENTRAL INTELLIGENCE HUB")
        ov_hdr.setObjectName("section_header")
        self.radial_hub = RadialHubWidget()
        self.radial_hub.node_clicked.connect(self.switch_tab)
        self.overview_input = InputBar("Command CREED across Mac, Bluetooth, or Phone...")
        self.overview_input.submitted.connect(self.handle_overview_send)
        self.overview_input.voice_clicked.connect(self.handle_voice_toggle)
        self.overview_input.stop_clicked.connect(self.stop_generation)
        ov_lay.addWidget(ov_hdr)
        ov_lay.addWidget(self.radial_hub, 1)
        ov_lay.addWidget(self.overview_input)

        # Tab 1: Conversation (with Back to Memory/Chats button)
        conv_page = QWidget()
        conv_lay = QVBoxLayout(conv_page)
        conv_lay.setContentsMargins(14, 12, 14, 12)
        conv_lay.setSpacing(8)

        conv_top = QHBoxLayout()
        back_btn = QPushButton("◂ CHATS / MEMORY")
        back_btn.setObjectName("secondary_btn")
        back_btn.clicked.connect(lambda: self.switch_tab(2))
        self.conv_title_label = QLabel("CONVERSATION // PRIMARY SESSION")
        self.conv_title_label.setObjectName("section_header")
        conv_top.addWidget(back_btn)
        conv_top.addSpacing(10)
        conv_top.addWidget(self.conv_title_label)
        conv_top.addStretch()

        self.chat_view = ChatView()
        self.input_bar = InputBar("Ask CREED anything... (Shift+Enter for new line)")
        self.input_bar.submitted.connect(self.handle_send)
        self.input_bar.stop_clicked.connect(self.stop_generation)
        self.input_bar.voice_clicked.connect(self.handle_voice_toggle)
        conv_lay.addLayout(conv_top)
        conv_lay.addWidget(self.chat_view, 1)
        conv_lay.addWidget(self.input_bar)

        # Tabs 2-7
        self.memory_tab = MemoryTab()
        self.memory_tab.add_note_requested.connect(self.add_memory_note)
        self.memory_tab.delete_note_requested.connect(self.delete_memory_note)
        self.memory_tab.conversation_selected.connect(self.open_conversation)
        self.memory_tab.new_conversation_requested.connect(self.create_new_conversation)
        self.memory_tab.delete_conversation_requested.connect(self.delete_conversation)

        self.systems_tab = SystemsTab()
        self.systems_tab.refresh_requested.connect(self.fetch_snapshot)

        self.tools_tab = ToolsTab()

        self.voice_tab = VoiceTab()
        self.voice_tab.voice_toggle_requested.connect(self.handle_voice_toggle)
        self.voice_tab.stop_requested.connect(self.stop_generation)

        self.automation_tab = AutomationTab()
        self.automation_tab.run_workflow_requested.connect(self.run_workflow)
        self.automation_tab.create_workflow_requested.connect(self.create_workflow)
        self.automation_tab.delete_workflow_requested.connect(self.delete_workflow)

        self.settings_tab = SettingsTab()
        self.settings_tab.save_requested.connect(self.save_settings)

        for page in (
            overview_page,
            conv_page,
            self.memory_tab,
            self.systems_tab,
            self.tools_tab,
            self.voice_tab,
            self.automation_tab,
            self.settings_tab,
        ):
            self.stack.addWidget(page)

        # RIGHT: Collapsible Telemetry Panel
        self.right_panel = QFrame()
        self.right_panel.setFixedWidth(290)
        self.right_panel.setObjectName("right_panel")
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(10)

        self.status_bar = StatusBar()

        self.activity_panel = QFrame()
        self.activity_panel.setObjectName("activity_panel")
        act_lay = QVBoxLayout(self.activity_panel)
        act_lay.setContentsMargins(14, 12, 14, 12)
        act_lay.setSpacing(6)
        act_hdr = QLabel("RECENT ACTIVITY")
        act_hdr.setObjectName("section_header")
        self.activity_feed = QLabel("Waiting for backend telemetry...")
        self.activity_feed.setObjectName("meta_label")
        self.activity_feed.setWordWrap(True)
        self.activity_feed.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        act_lay.addWidget(act_hdr)
        act_lay.addWidget(self.activity_feed, 1)

        right_layout.addWidget(self.status_bar)
        right_layout.addWidget(self.activity_panel, 1)

        body_layout.addWidget(self.sidebar)
        body_layout.addWidget(self.workspace_frame, 1)
        body_layout.addWidget(self.right_panel)

        self.min_btn.clicked.connect(self.showMinimized)
        self.close_btn.clicked.connect(self.close)
        self.max_btn.clicked.connect(self.toggle_fullscreen)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "connection_overlay") and hasattr(self, "workspace_frame"):
            self.connection_overlay.setGeometry(self.workspace_frame.rect())

    def switch_tab(self, index: int):
        if self.stack.currentIndex() != index:
            self.stack.setCurrentIndex(index)
            self._stack_anim.stop()
            self._stack_anim.setStartValue(0.45)
            self._stack_anim.setEndValue(1.0)
            self._stack_anim.start()
        for idx, btn in enumerate(self.nav_buttons):
            btn.setProperty("active", "true" if idx == index else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if index in (2, 3, 4, 5, 6, 7) and self._is_connected:
            self.fetch_snapshot()

    def toggle_right_panel(self):
        self._right_collapsed = not self._right_collapsed
        self.right_panel.setVisible(not self._right_collapsed)
        self.collapse_right_btn.setText("PANEL ◂" if self._right_collapsed else "PANEL ▸")
        QTimer.singleShot(10, lambda: self.connection_overlay.setGeometry(self.workspace_frame.rect()))

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
        self.clock_label.setText(datetime.now().strftime("%H:%M:%S  •  %d %b %Y"))
        if self._is_connected:
            self._uptime_seconds += 1
            self.uptime_value.setText(self._format_uptime(self._uptime_seconds))

    def _run_api(self, method: str, path: str, payload: dict = None, tag: str = "snapshot"):
        worker = ApiWorker(method=method, path=path, payload=payload, tag=tag)
        worker.response_ready.connect(self._on_api_response)
        worker.finished.connect(
            lambda w=worker: self._active_api_workers.remove(w)
            if w in self._active_api_workers
            else None
        )
        self._active_api_workers.append(worker)
        worker.start()

    def _on_api_response(self, tag: str, data: dict):
        if tag == "snapshot":
            self.on_snapshot_received(data)
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
            self.conv_title_label.setText("CONVERSATION // NEW SESSION")
            self.chat_view.clear_bubbles()
            self.current_ai_bubble = None
            self.switch_tab(1)

    def fetch_snapshot(self):
        if self._is_connected:
            self._run_api("GET", "/api/snapshot", tag="snapshot")

    def add_memory_note(self, tag: str, note: str):
        self._run_api("POST", "/api/memory/note", {"tag": tag, "note": note}, tag="mutate")

    def delete_memory_note(self, note_id: int):
        self._run_api("DELETE", f"/api/memory/note/{note_id}", tag="mutate")

    def open_conversation(self, session_id: str, title: str):
        self._current_session_id = session_id
        self.conv_title_label.setText(f"CONVERSATION // {title.upper()}")
        self._run_api("GET", f"/api/conversations/{session_id}", tag="load_convo")

    def create_new_conversation(self):
        self._run_api("POST", "/api/conversations", {"title": "New Conversation"}, tag="new_convo")

    def delete_conversation(self, session_id: str):
        if session_id == self._current_session_id:
            self._current_session_id = "default"
            self.conv_title_label.setText("CONVERSATION // PRIMARY SESSION")
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
        self._run_api("POST", "/api/settings", cfg, tag="mutate")

    def on_snapshot_received(self, data: dict):
        self.version_label.setText(f"v{data.get('version', '2.0.0')}")
        self._uptime_seconds = int(data.get("uptime_seconds", self._uptime_seconds))
        self.uptime_value.setText(self._format_uptime(self._uptime_seconds))

        tools = data.get("tools", [])
        self.status_bar.update_snapshot(data)
        self.memory_tab.update_data(data.get("memory", {}), data.get("conversations", []))
        self.systems_tab.update_data(data.get("systems", []))
        self.tools_tab.update_data(tools, data.get("tool_history", []))
        self.voice_tab.update_data(data.get("voice", {}))
        self.automation_tab.update_data(data.get("workflows", []), tools)
        self.settings_tab.update_data(data.get("config", {}))

        if not self._history_loaded:
            self._history_loaded = True
            for msg in data.get("chat_history", []):
                self.chat_view.add_bubble(msg.get("content", ""), msg.get("role") == "user")

        activity = data.get("activity", [])
        if activity:
            lines = [
                f"[{a.get('timestamp', '')}] {a.get('node', '')}: {a.get('message', '')}"
                for a in activity[:10]
            ]
            self.activity_feed.setText("\n\n".join(lines))

    # ----------------------------
    # Window Drag
    # ----------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._old_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self._old_pos:
            delta = event.globalPosition().toPoint() - self._old_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self._old_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self._old_pos = None

    # ----------------------------
    # Chat & Voice Logic
    # ----------------------------
    def handle_overview_send(self, text: str):
        self.switch_tab(1)
        self.handle_send(text)

    def handle_send(self, text: str):
        self.chat_view.add_bubble(text, True)
        self.current_ai_bubble = self.chat_view.add_bubble("", False)
        self.radial_hub.pulse_node("CONVERSATION")
        self.ws_worker.send_message(
            {"type": "chat", "text": text, "session_id": self._current_session_id}
        )

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
        self.switch_tab(1)
        self.chat_view.add_bubble(text, True)
        self.current_ai_bubble = self.chat_view.add_bubble("", False)

    def on_status_changed(self, state: str):
        self.status_bar.set_status(state)
        self.voice_tab.set_status(state)
        self.radial_hub.set_core_state(state)
        self.top_status_pill.setText(f"● {state.upper()}")
        if state == "Retrying Connection":
            self.top_status_pill.setStyleSheet("color: #F97316; font-family: 'SF Mono', monospace; font-size: 11px;")
        elif state == "Error":
            self.top_status_pill.setStyleSheet("color: #EF4444; font-family: 'SF Mono', monospace; font-size: 11px;")
        else:
            self.top_status_pill.setStyleSheet("color: #56D9E8; font-family: 'SF Mono', monospace; font-size: 11px;")
        glow = 0.9 if state in ("Processing", "Speaking", "Recording") else 0.5
        self.side_insignia.set_glow(glow)
        self.top_insignia.set_glow(glow)

    def on_connected(self):
        self._is_connected = True
        self.connection_overlay.hide()
        self.on_status_changed("Idle")
        self.fetch_snapshot()

    def on_disconnected(self):
        self._is_connected = False
        self.connection_overlay.setGeometry(self.workspace_frame.rect())
        self.connection_overlay.show()
        self.connection_overlay.raise_()
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
        self._clock_timer.stop()
        self._snapshot_timer.stop()
        self.ws_worker.stop()
        if not self.ws_worker.wait(400):
            self.ws_worker.terminate()
        for w in list(self._active_api_workers):
            w.wait(200)
        event.accept()
        QApplication.quit()
