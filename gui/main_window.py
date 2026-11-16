# gui/main_window.py

import os
import sys
from datetime import datetime
import httpx
from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QRadialGradient
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

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineView = None
from worker import WebSocketWorker
from components.chat_view import ChatView
from components.input_bar import InputBar
from components.insignia import CreedInsigniaWidget
from components.radial_hub import RadialHubWidget
from components.status_bar import STATE_COLORS, StatusBar
from components.tabs import (
    AutomationTab,
    MemoryTab,
    ModelsTab,
    SettingsTab,
    SystemsTab,
    ToolsTab,
    VoiceTab,
)
from components.vspotify_tab import VSpotifyTab
from components.jee_tab import JEETutorTab


class TechWorkspaceFrame(QFrame):
    """Clean studio workspace container with subtle top-center ambient glow."""

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            w, h = self.width(), self.height()

            grad = QRadialGradient(w * 0.5, h * 0.25, max(w, h) * 0.6)
            grad.setColorAt(0.0, QColor(96, 165, 250, 14))
            grad.setColorAt(1.0, QColor(16, 17, 20, 0))
            painter.fillRect(0, 0, w, h, grad)
        finally:
            painter.end()


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
        req_timeout = 95.0 if self.tag == "jee_test" else 10.0
        try:
            with httpx.Client(timeout=req_timeout) as client:
                resp = client.request(self.method, f"{base}{self.path}", json=self.payload)
                resp.raise_for_status()
                data = resp.json()
                self.response_ready.emit(self.tag, data)
                if self.tag not in ("snapshot", "load_convo", "jee_test"):
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
        self._active_chat_target = "default"

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
        self.version_label = QLabel("v3.0.0")
        self.version_label.setObjectName("meta_label")
        self.top_status_pill = QLabel("● Connecting")
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
        brand_sub = QLabel("Local Mac Agent")
        brand_sub.setObjectName("meta_label")
        brand_sub.setAlignment(Qt.AlignCenter)
        brand_box.addWidget(self.side_insignia, alignment=Qt.AlignCenter)
        brand_box.addWidget(brand_title)
        brand_box.addWidget(brand_sub)
        side_layout.addLayout(brand_box)
        side_layout.addSpacing(12)

        self.nav_buttons = []
        nav_items = [
            ("Overview", 0),
            ("Conversation", 1),
            ("Memory", 2),
            ("VSpotify", 3),
            ("JEE Tutor", 4),
            ("Voice", 5),
            ("Automation", 6),
            ("Systems", 7),
            ("Tools", 8),
            ("AI Models", 9),
            ("Settings", 10),
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
        up_hdr = QLabel("Uptime")
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
        self._stack_slide = QPropertyAnimation(self.stack, b"pos", self)
        self._stack_slide.setDuration(190)
        self._stack_slide.setEasingCurve(QEasingCurve.OutCubic)
        ws_layout.addWidget(self.stack)

        self.connection_overlay = ConnectionOverlay(self.workspace_frame)

        # Tab 0: Overview (Native 60 FPS 3D-Projected Sphere + Command Bar)
        overview_page = QWidget()
        ov_lay = QVBoxLayout(overview_page)
        ov_lay.setContentsMargins(12, 10, 12, 10)
        ov_lay.setSpacing(6)

        ov_hdr = QLabel("Intelligence Hub")
        ov_hdr.setObjectName("section_header")

        self.web_visualizer = None
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

        self.models_tab = ModelsTab()
        self.models_tab.select_model_requested.connect(self.select_model)
        self.models_tab.pull_model_requested.connect(self.pull_model)
        self.models_tab.delete_model_requested.connect(self.delete_model)
        self.models_tab.refresh_requested.connect(self.fetch_snapshot)

        self.settings_tab = SettingsTab()
        self.settings_tab.save_requested.connect(self.save_settings)
        self.settings_tab.restart_gui_requested.connect(self.restart_gui)

        self.vspotify_tab = VSpotifyTab()

        self.jee_tab = JEETutorTab()
        self.jee_tab.jee_prompt_submitted.connect(self.handle_jee_send)
        self.jee_tab.voice_requested.connect(self.handle_voice_toggle)
        self.jee_tab.stop_requested.connect(self.stop_generation)
        self.jee_tab.add_flashcard_requested.connect(self.add_jee_flashcard)
        self.jee_tab.toggle_flashcard_requested.connect(self.toggle_jee_flashcard)
        self.jee_tab.delete_flashcard_requested.connect(self.delete_jee_flashcard)
        self.jee_tab.generate_test_requested.connect(self.generate_jee_test)
        self.jee_tab.submit_test_requested.connect(self.submit_jee_test)

        for page in (
            overview_page,
            conv_page,
            self.memory_tab,
            self.vspotify_tab,
            self.jee_tab,
            self.voice_tab,
            self.automation_tab,
            self.systems_tab,
            self.tools_tab,
            self.models_tab,
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
            self._stack_slide.stop()
            self._stack_slide.setStartValue(QPoint(0, 10))
            self._stack_slide.setEndValue(QPoint(0, 0))
            self._stack_slide.start()
        for idx, btn in enumerate(self.nav_buttons):
            btn.setProperty("active", "true" if idx == index else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if index == 3 and self._is_connected:
            self.vspotify_tab.ensure_loaded()
        if index in (2, 3, 4, 5, 6, 7, 8, 9, 10) and self._is_connected:
            self.fetch_snapshot()

    def _on_visualizer_title(self, title: str):
        if title.startswith("CREED_TAB:"):
            try:
                tab_idx = int(title.split(":")[1])
                self.switch_tab(tab_idx)
            except (IndexError, ValueError):
                pass

    def toggle_right_panel(self):
        self._right_collapsed = not self._right_collapsed
        self.collapse_right_btn.setText("PANEL ◂" if self._right_collapsed else "PANEL ▸")
        self._panel_anim = QPropertyAnimation(self.right_panel, b"maximumWidth", self)
        self._panel_anim.setDuration(240)
        self._panel_anim.setEasingCurve(QEasingCurve.OutCubic)
        if self._right_collapsed:
            self._panel_anim.setStartValue(self.right_panel.width())
            self._panel_anim.setEndValue(0)
            self._panel_anim.finished.connect(lambda: self.right_panel.setVisible(False))
        else:
            self.right_panel.setVisible(True)
            self._panel_anim.setStartValue(0)
            self._panel_anim.setEndValue(290)
        self._panel_anim.start()
        QTimer.singleShot(250, lambda: self.connection_overlay.setGeometry(self.workspace_frame.rect()))

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
        elif tag == "jee_test":
            self.jee_tab.load_generated_test(data)

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

    def select_model(self, model: str):
        self._run_api("POST", "/api/models/select", {"model": model}, tag="mutate")

    def pull_model(self, model: str):
        self._snapshot_timer.setInterval(1200)
        self._run_api("POST", "/api/models/pull", {"model": model}, tag="mutate")

    def delete_model(self, model: str):
        self._run_api("POST", "/api/models/delete", {"model": model}, tag="mutate")

    def add_jee_flashcard(self, subject: str, chapter: str, front: str, back: str):
        self._run_api(
            "POST",
            "/api/jee/flashcards",
            {"subject": subject, "chapter": chapter, "front": front, "back": back},
            tag="mutate",
        )

    def toggle_jee_flashcard(self, card_id: int):
        self._run_api("POST", f"/api/jee/flashcards/{card_id}/toggle", tag="mutate")

    def delete_jee_flashcard(self, card_id: int):
        self._run_api("DELETE", f"/api/jee/flashcards/{card_id}", tag="mutate")

    def generate_jee_test(self, subject: str, chapter: str, difficulty: str, count: int):
        self._run_api(
            "POST",
            "/api/jee/test/generate",
            {"subject": subject, "chapter": chapter, "difficulty": difficulty, "count": count},
            tag="jee_test",
        )

    def submit_jee_test(self, subject: str, difficulty: str, score: int, total: int):
        self._run_api(
            "POST",
            "/api/jee/test/submit",
            {"subject": subject, "difficulty": difficulty, "score": score, "total": total},
            tag="mutate",
        )

    def on_snapshot_received(self, data: dict):
        self.version_label.setText(f"v{data.get('version', '3.0.0')}")
        self._uptime_seconds = int(data.get("uptime_seconds", self._uptime_seconds))
        self.uptime_value.setText(self._format_uptime(self._uptime_seconds))

        tools = data.get("tools", [])
        ollama_models = data.get("ollama_models", [])
        pull_info = data.get("model_pull", {})
        if pull_info.get("active"):
            if self._snapshot_timer.interval() != 1200:
                self._snapshot_timer.setInterval(1200)
        elif self._snapshot_timer.interval() != 5000:
            self._snapshot_timer.setInterval(5000)

        self.status_bar.update_snapshot(data)
        self.memory_tab.update_data(data.get("memory", {}), data.get("conversations", []))
        self.systems_tab.update_data(data.get("systems", []))
        self.tools_tab.update_data(tools, data.get("tool_history", []))
        self.voice_tab.update_data(data.get("voice", {}))
        self.automation_tab.update_data(data.get("workflows", []), tools)
        self.models_tab.update_data(
            data.get("model", ""),
            ollama_models,
            pull_info,
            data.get("ollama_online", False),
        )
        self.settings_tab.update_data(data.get("config", {}), ollama_models)
        self.jee_tab.update_data(data)

        for cmd in data.get("vspotify_commands", []):
            act = cmd.get("action", "")
            if act == "open_tab":
                self.switch_tab(3)
            elif act:
                self.vspotify_tab.execute_command(act, cmd.get("params", {}))

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

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            if pos.y() <= self.title_bar.height() + 14:
                self.toggle_fullscreen()

    def mouseReleaseEvent(self, event):
        self._old_pos = None

    # ----------------------------
    # Chat & Voice Logic
    # ----------------------------
    def handle_overview_send(self, text: str):
        # Stay on the Overview Intelligence Hub while logging the chat in Conversation
        self.handle_send(text)

    def handle_send(self, text: str):
        self._active_chat_target = "default"
        self.chat_view.add_bubble(text, True)
        self.current_ai_bubble = self.chat_view.add_bubble("", False)
        if self.radial_hub:
            self.radial_hub.pulse_node("CONVERSATION")
        self.ws_worker.send_message(
            {"type": "chat", "text": text, "session_id": self._current_session_id}
        )

    def handle_jee_send(self, text: str):
        self._active_chat_target = "jee"
        self.ws_worker.send_message(
            {"type": "chat", "text": text, "session_id": "jee-tutor", "mode": "jee"}
        )

    def handle_voice_toggle(self):
        if self.radial_hub:
            self.radial_hub.pulse_node("VOICE")
        self.ws_worker.send_message({"type": "voice_toggle"})

    def stop_generation(self):
        self.ws_worker.send_message({"type": "stop"})

    def append_token(self, token: str):
        if self._active_chat_target == "jee":
            self.jee_tab.append_token(token)
            return
        if self.current_ai_bubble is None:
            self.current_ai_bubble = self.chat_view.add_bubble("", False)
        self.current_ai_bubble.append_text(token)
        self.chat_view.scroll_to_bottom()

    def on_response_done(self):
        if self._active_chat_target == "jee":
            self.jee_tab.finish_turn()
        self.current_ai_bubble = None
        self.fetch_snapshot()

    def handle_transcription(self, text: str):
        # Stay on the current hub/tab; record transcription in Conversation
        self.chat_view.add_bubble(text, True)
        self.current_ai_bubble = self.chat_view.add_bubble("", False)

    def restart_gui(self):
        import subprocess
        from pathlib import Path

        app_path = Path(__file__).resolve().parent / "app.py"
        subprocess.Popen([sys.executable, str(app_path)], start_new_session=True)
        self.close()

    def on_status_changed(self, state: str):
        color = STATE_COLORS.get(state, "#56D9E8")
        self.status_bar.set_status(state)
        self.voice_tab.set_status(state)
        if self.radial_hub:
            self.radial_hub.set_core_state(state)
        self.top_status_pill.setText(f"● {state.upper()}")
        self.top_status_pill.setStyleSheet(
            f"color: {color}; font-family: 'SF Mono', monospace; font-size: 11px;"
        )
        glow = 0.95 if state in ("Processing", "Speaking", "Recording", "Listening") else 0.6
        self.side_insignia.set_glow(glow)
        self.side_insignia.set_accent(color)
        self.top_insignia.set_glow(glow)
        self.top_insignia.set_accent(color)

    def on_connected(self):
        self._is_connected = True
        self.connection_overlay.hide()
        self.on_status_changed("Idle")
        if self.web_visualizer is not None:
            self.web_visualizer.setUrl(QUrl("http://localhost:8000/visualizer"))
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
        self.ws_worker.wait(300)
        for w in list(self._active_api_workers):
            w.wait(200)
        event.accept()
        QApplication.quit()
        os._exit(0)
