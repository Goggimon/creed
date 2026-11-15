# gui/components/tabs.py

import json
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from components.voice_indicator import VoiceIndicator


def _make_header(title: str, subtitle: str = "") -> QWidget:
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 6)
    lay.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("tab_title")
    lay.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("meta_label")
        lay.addWidget(s)
    return box


class MemoryTab(QWidget):
    add_note_requested = Signal(str, str)
    delete_note_requested = Signal(int)
    conversation_selected = Signal(str, str)
    new_conversation_requested = Signal()
    delete_conversation_requested = Signal(str)
    refresh_requested = Signal()

    def __init__(self):
        super().__init__()
        self._notes = []
        self._reminders = []
        self._conversations = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        layout.addWidget(
            _make_header(
                "MEMORY // CONVERSATIONS & KNOWLEDGE STORE",
                "Switch between saved conversations, persistent notes, and scheduled reminders",
            )
        )

        # Conversations Switcher Section
        convo_top = QHBoxLayout()
        convo_hdr = QLabel("SAVED CONVERSATIONS")
        convo_hdr.setObjectName("section_header")
        new_chat_btn = QPushButton("+ NEW CHAT")
        new_chat_btn.setObjectName("primary_btn")
        new_chat_btn.clicked.connect(self.new_conversation_requested.emit)
        convo_top.addWidget(convo_hdr)
        convo_top.addStretch()
        convo_top.addWidget(new_chat_btn)
        layout.addLayout(convo_top)

        convo_scroll = QScrollArea()
        convo_scroll.setWidgetResizable(True)
        convo_scroll.setObjectName("chat_area")
        convo_scroll.setFixedHeight(155)
        self.convo_container = QWidget()
        self.convo_layout = QVBoxLayout(self.convo_container)
        self.convo_layout.setSpacing(6)
        self.convo_layout.addStretch()
        convo_scroll.setWidget(self.convo_container)
        layout.addWidget(convo_scroll)

        # Notes Section
        notes_hdr = QLabel("PERSISTENT NOTES")
        notes_hdr.setObjectName("section_header")
        layout.addWidget(notes_hdr)

        controls = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter memories by keyword or tag...")
        self.search_input.textChanged.connect(self._render_notes)

        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("Tag (e.g. physics)")
        self.tag_input.setFixedWidth(130)

        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("New memory note...")

        add_btn = QPushButton("+ SAVE")
        add_btn.setObjectName("primary_btn")
        add_btn.clicked.connect(self._handle_add)

        controls.addWidget(self.search_input, 2)
        controls.addWidget(self.tag_input, 1)
        controls.addWidget(self.note_input, 2)
        controls.addWidget(add_btn)
        layout.addLayout(controls)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("chat_area")
        self.notes_container = QWidget()
        self.notes_layout = QVBoxLayout(self.notes_container)
        self.notes_layout.setSpacing(8)
        self.notes_layout.addStretch()
        scroll.setWidget(self.notes_container)
        layout.addWidget(scroll, 2)

        rem_hdr = QLabel("SCHEDULED REMINDERS")
        rem_hdr.setObjectName("section_header")
        layout.addWidget(rem_hdr)

        self.reminders_label = QLabel("No active reminders.")
        self.reminders_label.setObjectName("meta_label")
        self.reminders_label.setWordWrap(True)
        layout.addWidget(self.reminders_label)

    def _handle_add(self):
        note = self.note_input.text().strip()
        tag = self.tag_input.text().strip() or "general"
        if note:
            self.add_note_requested.emit(tag, note)
            self.note_input.clear()

    def update_data(self, memory_data: dict, conversations: list = None):
        self._notes = memory_data.get("notes", [])
        self._reminders = memory_data.get("reminders", [])
        if conversations is not None:
            self._conversations = conversations
            self._render_conversations()
        self._render_notes()
        if self._reminders:
            lines = [f"• [{r['time'][11:19]}] {r['message']}" for r in self._reminders]
            self.reminders_label.setText("\n".join(lines))
        else:
            self.reminders_label.setText("No active reminders.")

    def _render_conversations(self):
        while self.convo_layout.count() > 1:
            item = self.convo_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for c in self._conversations:
            card = QFrame()
            card.setObjectName("panel_card")
            row = QHBoxLayout(card)
            row.setContentsMargins(10, 6, 10, 6)

            sid = c.get("id", "default")
            title = c.get("title", "Conversation")
            cnt = c.get("message_count", 0)
            updated = (c.get("updated_at") or "")[:16].replace("T", " ")

            info = QVBoxLayout()
            t_lbl = QLabel(f"{title}")
            t_lbl.setObjectName("accent_label")
            m_lbl = QLabel(f"{cnt} messages  •  {updated}")
            m_lbl.setObjectName("meta_label")
            info.addWidget(t_lbl)
            info.addWidget(m_lbl)

            open_btn = QPushButton("OPEN ▸")
            open_btn.setObjectName("secondary_btn")
            open_btn.clicked.connect(
                lambda checked=False, s=sid, t=title: self.conversation_selected.emit(s, t)
            )

            del_btn = QPushButton("✕")
            del_btn.setObjectName("secondary_btn")
            del_btn.setFixedSize(26, 26)
            del_btn.clicked.connect(
                lambda checked=False, s=sid: self.delete_conversation_requested.emit(s)
            )

            row.addLayout(info, 1)
            row.addWidget(open_btn)
            row.addWidget(del_btn)
            self.convo_layout.insertWidget(self.convo_layout.count() - 1, card)

    def _render_notes(self):
        while self.notes_layout.count() > 1:
            item = self.notes_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        q = self.search_input.text().strip().lower()
        filtered = [
            n for n in self._notes
            if not q or q in n.get("tag", "").lower() or q in n.get("note", "").lower()
        ]

        if not filtered:
            empty = QLabel("No matching memories stored.")
            empty.setObjectName("meta_label")
            self.notes_layout.insertWidget(0, empty)
            return

        for n in filtered:
            card = QFrame()
            card.setObjectName("panel_card")
            row = QHBoxLayout(card)
            row.setContentsMargins(12, 8, 12, 8)

            text_col = QVBoxLayout()
            tag_lbl = QLabel(f"[{n['tag'].upper()}]  •  {n.get('timestamp', '')[:19]}")
            tag_lbl.setObjectName("accent_label")
            body_lbl = QLabel(n["note"])
            body_lbl.setWordWrap(True)
            text_col.addWidget(tag_lbl)
            text_col.addWidget(body_lbl)

            del_btn = QPushButton("✕")
            del_btn.setObjectName("secondary_btn")
            del_btn.setFixedSize(28, 28)
            del_btn.clicked.connect(lambda checked=False, nid=n["id"]: self.delete_note_requested.emit(nid))

            row.addLayout(text_col, 1)
            row.addWidget(del_btn)
            self.notes_layout.insertWidget(self.notes_layout.count() - 1, card)


class SystemsTab(QWidget):
    refresh_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.addWidget(_make_header("SYSTEMS // CONNECTED ARCHITECTURE", "Real-time operational state of local and remote nodes"))
        top.addStretch()
        refresh_btn = QPushButton("REFRESH")
        refresh_btn.setObjectName("secondary_btn")
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        top.addWidget(refresh_btn)
        layout.addLayout(top)

        self.grid = QGridLayout()
        self.grid.setSpacing(12)
        layout.addLayout(self.grid)
        layout.addStretch()

    def update_data(self, systems: list):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for idx, sys_info in enumerate(systems):
            card = QFrame()
            card.setObjectName("panel_card")
            v = QVBoxLayout(card)
            v.setContentsMargins(14, 12, 14, 12)
            v.setSpacing(6)

            name = QLabel(sys_info.get("name", "System").upper())
            name.setObjectName("section_header")

            state = sys_info.get("state", "Unknown")
            state_lbl = QLabel(f"● {state.upper()}")
            color = "#22C55E" if state in ("Online", "Configured") else "#F59E0B"
            state_lbl.setStyleSheet(f"color: {color}; font-family: 'SF Mono', monospace; font-size: 11px;")

            desc = QLabel(sys_info.get("description", ""))
            desc.setWordWrap(True)
            desc.setObjectName("meta_label")

            detail = QLabel(sys_info.get("detail", ""))
            detail.setObjectName("accent_label")
            detail.setWordWrap(True)

            v.addWidget(name)
            v.addWidget(state_lbl)
            v.addWidget(desc)
            v.addWidget(detail)
            self.grid.addWidget(card, idx // 2, idx % 2)


class ToolsTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        layout.addWidget(_make_header("TOOLS // REGISTERED CAPABILITIES", "Live tool schemas exposed to Ollama and recent execution log"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("chat_area")
        self.container = QWidget()
        self.tools_layout = QVBoxLayout(self.container)
        self.tools_layout.setSpacing(8)
        self.tools_layout.addStretch()
        scroll.setWidget(self.container)
        layout.addWidget(scroll, 2)

        hist_hdr = QLabel("RECENT TOOL EXECUTIONS")
        hist_hdr.setObjectName("section_header")
        layout.addWidget(hist_hdr)

        self.history_label = QLabel("No tool executions recorded in this session.")
        self.history_label.setObjectName("meta_label")
        self.history_label.setWordWrap(True)
        layout.addWidget(self.history_label, 1)

    def update_data(self, tools: list, history: list):
        while self.tools_layout.count() > 1:
            item = self.tools_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for t in tools:
            card = QFrame()
            card.setObjectName("panel_card")
            v = QVBoxLayout(card)
            v.setContentsMargins(12, 8, 12, 8)
            v.setSpacing(3)

            name_lbl = QLabel(t.get("name", ""))
            name_lbl.setObjectName("accent_label")
            desc_lbl = QLabel(t.get("description", ""))
            desc_lbl.setWordWrap(True)
            desc_lbl.setObjectName("meta_label")
            v.addWidget(name_lbl)
            v.addWidget(desc_lbl)
            self.tools_layout.insertWidget(self.tools_layout.count() - 1, card)

        if history:
            lines = [
                f"[{h.get('timestamp', '')}] {h.get('name', '')} -> {h.get('result', '')[:120]}"
                for h in history[:8]
            ]
            self.history_label.setText("\n".join(lines))
        else:
            self.history_label.setText("No tool executions recorded in this session.")


class VoiceTab(QWidget):
    voice_toggle_requested = Signal()
    stop_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        layout.addWidget(_make_header("VOICE // AUDIO & SPEECH PIPELINE", "Real microphone RMS activity, STT, TTS, and Wake-Word status"))

        self.visualizer = VoiceIndicator(diameter=190)
        layout.addWidget(self.visualizer, alignment=Qt.AlignCenter)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.listen_btn = QPushButton("TOGGLE MIC")
        self.listen_btn.setObjectName("primary_btn")
        self.listen_btn.clicked.connect(self.voice_toggle_requested.emit)
        self.stop_btn = QPushButton("STOP AUDIO")
        self.stop_btn.setObjectName("secondary_btn")
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        btn_row.addWidget(self.listen_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.info_card = QFrame()
        self.info_card.setObjectName("panel_card")
        info_lay = QVBoxLayout(self.info_card)
        info_lay.setContentsMargins(14, 12, 14, 12)
        self.details_label = QLabel("Loading voice telemetry...")
        self.details_label.setObjectName("meta_label")
        self.details_label.setWordWrap(True)
        info_lay.addWidget(self.details_label)
        layout.addWidget(self.info_card)
        layout.addStretch()

    def set_status(self, state: str):
        self.visualizer.set_status(state)

    def set_audio_level(self, level: float):
        self.visualizer.set_audio_level(level)

    def update_data(self, voice_data: dict):
        text = (
            f"Wake Word ('{voice_data.get('wake_keyword', 'creed')}'): {voice_data.get('wake_word', 'Unknown')}\n"
            f"STT Engine: {voice_data.get('stt_backend', 'loading')} ({voice_data.get('stt_model', '')})\n"
            f"TTS Engine: {voice_data.get('tts_backend', 'none')} (voice: {voice_data.get('tts_voice', '')})"
        )
        self.details_label.setText(text)


class AutomationTab(QWidget):
    run_workflow_requested = Signal(int)
    create_workflow_requested = Signal(str, str, list)
    delete_workflow_requested = Signal(int)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        layout.addWidget(
            _make_header(
                "AUTOMATION // CUSTOM WORKFLOWS",
                "Run multi-step device workflows or schedule background tasks",
            )
        )

        # Reminder Watcher Banner
        watcher = QFrame()
        watcher.setObjectName("panel_card")
        w_lay = QHBoxLayout(watcher)
        w_lay.setContentsMargins(12, 8, 12, 8)
        w_lay.addWidget(QLabel("SQLITE REMINDER WATCHER"))
        w_lay.addStretch()
        w_state = QLabel("● ACTIVE (10s poll)")
        w_state.setStyleSheet("color: #22C55E; font-family: 'SF Mono', monospace; font-size: 11px;")
        w_lay.addWidget(w_state)
        layout.addWidget(watcher)

        # Create Custom Workflow Bar
        create_hdr = QLabel("CREATE CUSTOM WORKFLOW")
        create_hdr.setObjectName("section_header")
        layout.addWidget(create_hdr)

        form_row = QHBoxLayout()
        self.wf_name = QLineEdit()
        self.wf_name.setPlaceholderText("Workflow name (e.g. Coding Mode)")
        self.wf_tool = QComboBox()
        self.wf_tool.setStyleSheet(
            "background-color: #10151B; border: 1px solid #22303F; border-radius: 6px; padding: 6px; color: #E6EDF2;"
        )
        self.wf_args = QLineEdit()
        self.wf_args.setPlaceholderText('Args JSON (e.g. {"app_name": "Visual Studio Code"})')
        add_wf_btn = QPushButton("+ ADD")
        add_wf_btn.setObjectName("primary_btn")
        add_wf_btn.clicked.connect(self._handle_create)

        form_row.addWidget(self.wf_name, 2)
        form_row.addWidget(self.wf_tool, 2)
        form_row.addWidget(self.wf_args, 3)
        form_row.addWidget(add_wf_btn)
        layout.addLayout(form_row)

        # Saved Workflows List
        list_hdr = QLabel("SAVED WORKFLOWS")
        list_hdr.setObjectName("section_header")
        layout.addWidget(list_hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("chat_area")
        self.wf_container = QWidget()
        self.wf_layout = QVBoxLayout(self.wf_container)
        self.wf_layout.setSpacing(8)
        self.wf_layout.addStretch()
        scroll.setWidget(self.wf_container)
        layout.addWidget(scroll, 1)

    def _handle_create(self):
        name = self.wf_name.text().strip()
        tool = self.wf_tool.currentText().strip()
        raw_args = self.wf_args.text().strip() or "{}"
        if not name or not tool:
            return
        try:
            args = json.loads(raw_args)
            if not isinstance(args, dict):
                args = {}
        except Exception:
            args = {}
        self.create_workflow_requested.emit(
            name,
            f"Runs {tool}",
            [{"tool": tool, "args": args}],
        )
        self.wf_name.clear()
        self.wf_args.clear()

    def update_data(self, workflows: list, tools: list = None):
        if tools and self.wf_tool.count() == 0:
            for t in tools:
                self.wf_tool.addItem(t.get("name", ""))

        while self.wf_layout.count() > 1:
            item = self.wf_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for wf in workflows:
            card = QFrame()
            card.setObjectName("panel_card")
            row = QHBoxLayout(card)
            row.setContentsMargins(12, 10, 12, 10)

            info = QVBoxLayout()
            t_lbl = QLabel(wf.get("name", "").upper())
            t_lbl.setObjectName("accent_label")
            steps_desc = ", ".join(s.get("tool", "") for s in wf.get("steps", []))
            d_lbl = QLabel(f"{wf.get('description', '')}  [{steps_desc}]")
            d_lbl.setObjectName("meta_label")
            d_lbl.setWordWrap(True)
            info.addWidget(t_lbl)
            info.addWidget(d_lbl)

            run_btn = QPushButton("▶ RUN")
            run_btn.setObjectName("primary_btn")
            run_btn.clicked.connect(
                lambda checked=False, wid=wf["id"]: self.run_workflow_requested.emit(wid)
            )

            del_btn = QPushButton("✕")
            del_btn.setObjectName("secondary_btn")
            del_btn.setFixedSize(28, 28)
            del_btn.clicked.connect(
                lambda checked=False, wid=wf["id"]: self.delete_workflow_requested.emit(wid)
            )

            row.addLayout(info, 1)
            row.addWidget(run_btn)
            row.addWidget(del_btn)
            self.wf_layout.insertWidget(self.wf_layout.count() - 1, card)


class SettingsTab(QWidget):
    save_requested = Signal(dict)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        layout.addWidget(_make_header("SETTINGS // ENVIRONMENT CONFIGURATION", "Reads from and writes to .env"))

        form = QFrame()
        form.setObjectName("panel_card")
        g = QGridLayout(form)
        g.setContentsMargins(14, 14, 14, 14)
        g.setSpacing(10)

        self.model_input = QLineEdit()
        self.endpoint_input = QLineEdit()
        self.voice_input = QLineEdit()
        self.rate_input = QLineEdit()
        self.adb_input = QLineEdit()
        self.porcupine_status = QLabel("Not configured")
        self.porcupine_status.setObjectName("meta_label")

        rows = [
            ("Ollama Model", self.model_input),
            ("Ollama Endpoint", self.endpoint_input),
            ("macOS TTS Voice", self.voice_input),
            ("TTS Rate (WPM)", self.rate_input),
            ("Phone ADB Target (IP:Port)", self.adb_input),
            ("Porcupine Wake Key", self.porcupine_status),
        ]
        for idx, (label, widget) in enumerate(rows):
            lbl = QLabel(label)
            lbl.setObjectName("section_header")
            g.addWidget(lbl, idx, 0)
            g.addWidget(widget, idx, 1)

        layout.addWidget(form)

        save_btn = QPushButton("SAVE TO .ENV")
        save_btn.setObjectName("primary_btn")
        save_btn.clicked.connect(self._emit_save)
        layout.addWidget(save_btn, alignment=Qt.AlignLeft)
        layout.addStretch()

    def update_data(self, cfg: dict):
        if not self.model_input.hasFocus():
            self.model_input.setText(cfg.get("ollama_model", ""))
        if not self.endpoint_input.hasFocus():
            self.endpoint_input.setText(cfg.get("ollama_endpoint", ""))
        if not self.voice_input.hasFocus():
            self.voice_input.setText(cfg.get("macos_tts_voice", ""))
        if not self.rate_input.hasFocus():
            self.rate_input.setText(str(cfg.get("macos_tts_rate", 190)))
        if not self.adb_input.hasFocus():
            self.adb_input.setText(cfg.get("phone_adb_target", ""))
        self.porcupine_status.setText(
            "Configured in .env" if cfg.get("porcupine_configured") else "Not set in .env"
        )

    def _emit_save(self):
        self.save_requested.emit(
            {
                "ollama_model": self.model_input.text().strip(),
                "ollama_endpoint": self.endpoint_input.text().strip(),
                "macos_tts_voice": self.voice_input.text().strip(),
                "macos_tts_rate": self.rate_input.text().strip(),
                "phone_adb_target": self.adb_input.text().strip(),
            }
        )
