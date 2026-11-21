# gui/components/tabs.py

import json
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from components.voice_indicator import VoiceIndicator


def _make_header(title: str, subtitle: str = "", sys_tag: str = "", accent: str = "#67E8F9") -> QWidget:
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 6)
    lay.setSpacing(2)
    if sys_tag:
        tag = QLabel(sys_tag)
        tag.setStyleSheet(
            f"color: {accent}; font-family: 'Menlo', monospace; font-size: 10px; font-weight: 700; letter-spacing: 1px;"
        )
        lay.addWidget(tag)
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
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        layout.addWidget(
            _make_header(
                "Knowledge Architecture",
                "Structured conversation index, tagged memory store, and scheduled reminders",
                "CREED / SYS-02 • KNOWLEDGE ENGINE",
                "#5EEAD4",
            )
        )

        # Two-column Knowledge Architecture
        cols = QHBoxLayout()
        cols.setSpacing(16)

        # Left column: Conversations Index + Reminders
        left_col = QVBoxLayout()
        left_col.setSpacing(8)
        convo_top = QHBoxLayout()
        convo_hdr = QLabel("CONVERSATION INDEX")
        convo_hdr.setObjectName("section_header")
        new_chat_btn = QPushButton("+ NEW")
        new_chat_btn.setObjectName("primary_btn")
        new_chat_btn.clicked.connect(self.new_conversation_requested.emit)
        convo_top.addWidget(convo_hdr)
        convo_top.addStretch()
        convo_top.addWidget(new_chat_btn)
        left_col.addLayout(convo_top)

        convo_scroll = QScrollArea()
        convo_scroll.setWidgetResizable(True)
        convo_scroll.setObjectName("chat_area")
        self.convo_container = QWidget()
        self.convo_layout = QVBoxLayout(self.convo_container)
        self.convo_layout.setSpacing(6)
        self.convo_layout.addStretch()
        convo_scroll.setWidget(self.convo_container)
        left_col.addWidget(convo_scroll, 2)

        rem_hdr = QLabel("ACTIVE REMINDERS")
        rem_hdr.setObjectName("section_header")
        left_col.addWidget(rem_hdr)
        self.reminders_label = QLabel("No active reminders.")
        self.reminders_label.setObjectName("meta_label")
        self.reminders_label.setWordWrap(True)
        left_col.addWidget(self.reminders_label)

        # Right column: Searchable Knowledge Store
        right_col = QVBoxLayout()
        right_col.setSpacing(8)
        notes_hdr = QLabel("MEMORY STORE")
        notes_hdr.setObjectName("section_header")
        right_col.addWidget(notes_hdr)

        controls = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter memories by keyword or tag...")
        self.search_input.textChanged.connect(self._render_notes)

        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("Tag")
        self.tag_input.setFixedWidth(105)

        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("Add knowledge entry...")

        add_btn = QPushButton("+ STORE")
        add_btn.setObjectName("primary_btn")
        add_btn.clicked.connect(self._handle_add)

        controls.addWidget(self.search_input, 2)
        controls.addWidget(self.tag_input, 1)
        controls.addWidget(self.note_input, 2)
        controls.addWidget(add_btn)
        right_col.addLayout(controls)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("chat_area")
        self.notes_container = QWidget()
        self.notes_layout = QVBoxLayout(self.notes_container)
        self.notes_layout.setSpacing(8)
        self.notes_layout.addStretch()
        scroll.setWidget(self.notes_container)
        right_col.addWidget(scroll, 1)

        cols.addLayout(left_col, 2)
        cols.addLayout(right_col, 3)
        layout.addLayout(cols, 1)

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
        top.addWidget(_make_header("Systems", "Connected hardware and local services"))
        top.addStretch()
        refresh_btn = QPushButton("REFRESH")
        refresh_btn.setObjectName("secondary_btn")
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        top.addWidget(refresh_btn)
        layout.addLayout(top)

        self.grid = QGridLayout()
        self.grid.setSpacing(12)
        layout.addLayout(self.grid)

        perf_hdr = QLabel("PIPELINE OBSERVABILITY // p50 • p95 • p99")
        perf_hdr.setObjectName("section_header")
        layout.addWidget(perf_hdr)

        self.perf_card = QFrame()
        self.perf_card.setObjectName("panel_card")
        p_lay = QVBoxLayout(self.perf_card)
        p_lay.setContentsMargins(14, 10, 14, 10)
        p_lay.setSpacing(6)

        turn_row = QHBoxLayout()
        turn_lbl = QLabel("INSPECT TURN TIMELINE")
        turn_lbl.setObjectName("section_header")
        self.turn_selector = QComboBox()
        self.turn_selector.setStyleSheet(
            "background-color: #10151B; border: 1px solid #22303F; border-radius: 6px; padding: 4px 8px; color: #E6EDF2; font-family: 'Menlo', monospace; font-size: 11px;"
        )
        self.turn_selector.currentIndexChanged.connect(self._render_selected_turn)
        turn_row.addWidget(turn_lbl)
        turn_row.addWidget(self.turn_selector, 1)
        p_lay.addLayout(turn_row)

        self.perf_label = QLabel("Collecting pipeline latency samples...")
        self.perf_label.setObjectName("meta_label")
        self.perf_label.setWordWrap(True)
        p_lay.addWidget(self.perf_label)

        self.timeline_label = QLabel("Select a turn to inspect overlapping stage intervals.")
        self.timeline_label.setStyleSheet("color: #93C5FD; font-family: 'Menlo', monospace; font-size: 11px;")
        self.timeline_label.setWordWrap(True)
        p_lay.addWidget(self.timeline_label)
        layout.addWidget(self.perf_card)
        layout.addStretch()

    def update_data(self, systems: list, latency: dict = None, router: dict = None):
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
            state_lbl.setStyleSheet(f"color: {color}; font-family: 'Menlo', monospace; font-size: 11px;")

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

        if latency:
            stages = latency.get("stages", {})
            counts = latency.get("path_counts", {})
            tts_backend = latency.get("tts_backend") or "unknown"
            tts_metric_type = latency.get("tts_metric_type") or "unmeasured"
            r_info = router or {}
            lines = [
                f"Active Route: {r_info.get('path', 'instant').upper()} ({r_info.get('model', '--')})  |  "
                f"TTS: {tts_backend} ({tts_metric_type})  |  "
                f"Counts: Instant {counts.get('instant', 0)} • Intelligent {counts.get('intelligent', 0)} • Background {counts.get('background', 0)}"
            ]
            for key, label in (
                ("vad_ms", "VAD"),
                ("stt_partial_ms", "Partial STT"),
                ("stt_final_ms", "Final STT"),
                ("classifier_ms", "Classifier"),
                ("memory_retrieval_ms", "Memory Retrieval"),
                ("llm_ttft_ms", "LLM TTFT"),
                ("llm_tok_s", "Throughput (tok/s)"),
                ("tts_dispatch_ms", "TTS Dispatch (say)"),
                ("tts_output_submit_ms", "TTS Output Submit (piper)"),
                ("e2e_dispatch_ms", "E2E Dispatch (say)"),
                ("e2e_output_submit_ms", "E2E Output Submit (piper)"),
                ("barge_in_ms", "Barge-In"),
            ):
                s = stages.get(key, {})
                if s.get("count", 0) > 0:
                    unit = "" if key == "llm_tok_s" else "ms"
                    mtype = f" [{s['metric_type']}]" if s.get("metric_type") else ""
                    lines.append(
                        f"{label:<24} last={s['last']}{unit}  p50={s['p50']}{unit}  p95={s['p95']}{unit}  p99={s['p99']}{unit}{mtype}"
                    )
            self.perf_label.setText("\n".join(lines))
            self._recent_turns = latency.get("recent_turns", [])
            if not self.turn_selector.view().isVisible():
                current_tid = self.turn_selector.currentData()
                target_ids = [t.get("turn_id", "") for t in self._recent_turns if t.get("turn_id")]
                existing_ids = [self.turn_selector.itemData(i) for i in range(self.turn_selector.count())]
                if target_ids != existing_ids:
                    self.turn_selector.blockSignals(True)
                    self.turn_selector.clear()
                    for t in self._recent_turns:
                        tid = t.get("turn_id", "")
                        if tid:
                            self.turn_selector.addItem(f"TURN #{tid} ({t.get('path', '')} • {t.get('model', '')})", tid)
                    if current_tid in target_ids:
                        self.turn_selector.setCurrentIndex(target_ids.index(current_tid))
                    self.turn_selector.blockSignals(False)
            self._render_selected_turn()

    def _render_selected_turn(self):
        turns = getattr(self, "_recent_turns", [])
        tid = self.turn_selector.currentData()
        if not turns or not tid:
            self.timeline_label.setText("No turn timelines recorded yet.")
            return
        turn = next((t for t in turns if t.get("turn_id") == tid), None)
        if not turn:
            return
        timeline = turn.get("timeline", [])
        out = [f"TURN #{tid}  (intervals may overlap; TOTAL is wall-clock span)"]
        for idx, iv in enumerate(timeline):
            branch = "└──" if idx == len(timeline) - 1 else "├──"
            out.append(
                f"{branch} {iv['stage']:<18} {iv['duration_ms']:>6.1f} ms  [{iv['start_ms']}..{iv['end_ms']} ms]"
            )
        self.timeline_label.setText("\n".join(out))


class ToolsTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        layout.addWidget(_make_header("Tools", "Capabilities available to CREED and recent runs"))

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

        layout.addWidget(_make_header("Voice", "Microphone activity, wake word, and speech engines"))

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
                "Automation",
                "Multi-step workflows and background reminders",
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


MODEL_CATALOG = [
    ("qwen2.5-coder:7b", "4.7 GB", "Coding, tool calling & scripts (Fast)"),
    ("qwen3:8b", "5.2 GB", "General reasoning, math & logic (Fast)"),
    ("deepseek-r1:8b", "4.9 GB", "Step-by-step reasoning & JEE prep"),
    ("qwen2.5:14b", "9.0 GB", "Heavy coding & deep reasoning (16 GB)"),
    ("llama3.1:8b", "4.9 GB", "General assistant & conversation"),
    ("gemma2:9b", "5.4 GB", "Balanced writing & analysis"),
]

_TABLE_STYLE = (
    "QTableWidget { background-color: #10151B; border: 1px solid #22303F; border-radius: 6px; "
    "gridline-color: #1B2531; color: #E6EDF2; font-size: 11px; }"
    "QHeaderView::section { background-color: #151C24; color: #8BAFBE; border: none; "
    "border-bottom: 1px solid #22303F; padding: 6px; font-family: 'SF Mono', monospace; "
    "font-size: 10px; font-weight: bold; }"
    "QTableWidget::item { padding: 4px 6px; }"
)


class ModelsTab(QWidget):
    select_model_requested = Signal(str)
    pull_model_requested = Signal(str)
    delete_model_requested = Signal(str)
    refresh_requested = Signal()

    def __init__(self):
        super().__init__()
        self._installed_names = set()
        self._active_model = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.addWidget(
            _make_header(
                "AI Models",
                "Switch active model or pull local weights via Ollama",
            )
        )
        top.addStretch()
        refresh_btn = QPushButton("REFRESH")
        refresh_btn.setObjectName("secondary_btn")
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        top.addWidget(refresh_btn)
        layout.addLayout(top)

        # Quick Switch Dropdown Bar
        switch_card = QFrame()
        switch_card.setObjectName("panel_card")
        sw_lay = QHBoxLayout(switch_card)
        sw_lay.setContentsMargins(12, 8, 12, 8)
        sw_lay.setSpacing(8)

        sw_lbl = QLabel("ACTIVE MODEL")
        sw_lbl.setObjectName("section_header")
        self.model_combo = QComboBox()
        self.model_combo.setStyleSheet(
            "background-color: #10151B; border: 1px solid #22303F; border-radius: 6px; padding: 6px 10px; color: #E6EDF2; font-family: 'SF Mono', monospace; font-size: 11px;"
        )
        switch_btn = QPushButton("ACTIVATE")
        switch_btn.setObjectName("primary_btn")
        switch_btn.clicked.connect(self._activate_combo)

        sw_lay.addWidget(sw_lbl)
        sw_lay.addWidget(self.model_combo, 1)
        sw_lay.addWidget(switch_btn)
        layout.addWidget(switch_card)

        # Installed Models Table
        inst_hdr = QLabel("INSTALLED OLLAMA MODELS")
        inst_hdr.setObjectName("section_header")
        layout.addWidget(inst_hdr)

        self.installed_table = QTableWidget(0, 6)
        self.installed_table.setHorizontalHeaderLabels(
            ["MODEL", "PARAMS", "QUANT", "SIZE", "STATUS", "ACTION"]
        )
        self.installed_table.setStyleSheet(_TABLE_STYLE)
        self.installed_table.verticalHeader().setVisible(False)
        self.installed_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.installed_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.installed_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        hdr = self.installed_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3, 4):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.Fixed)
        self.installed_table.setColumnWidth(5, 130)
        self.installed_table.setMinimumHeight(140)
        layout.addWidget(self.installed_table, 1)

        # Pull / Download Table + Custom Pull
        cat_hdr = QLabel("DOWNLOAD / PULL MODELS")
        cat_hdr.setObjectName("section_header")
        layout.addWidget(cat_hdr)

        pull_row = QHBoxLayout()
        self.custom_pull_input = QLineEdit()
        self.custom_pull_input.setPlaceholderText("Pull any Ollama tag (e.g. mistral:7b, qwen2.5-coder:14b)...")
        pull_btn = QPushButton("↓ PULL MODEL")
        pull_btn.setObjectName("primary_btn")
        pull_btn.clicked.connect(self._pull_custom)
        pull_row.addWidget(self.custom_pull_input, 1)
        pull_row.addWidget(pull_btn)
        layout.addLayout(pull_row)

        self.pull_status_label = QLabel("Ready.")
        self.pull_status_label.setObjectName("meta_label")
        layout.addWidget(self.pull_status_label)

        self.catalog_table = QTableWidget(len(MODEL_CATALOG), 4)
        self.catalog_table.setHorizontalHeaderLabels(
            ["MODEL", "SIZE", "BEST FOR", "ACTION"]
        )
        self.catalog_table.setStyleSheet(_TABLE_STYLE)
        self.catalog_table.verticalHeader().setVisible(False)
        self.catalog_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.catalog_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.catalog_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        chdr = self.catalog_table.horizontalHeader()
        chdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        chdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        chdr.setSectionResizeMode(2, QHeaderView.Stretch)
        chdr.setSectionResizeMode(3, QHeaderView.Fixed)
        self.catalog_table.setColumnWidth(3, 110)
        self.catalog_table.setMinimumHeight(170)
        layout.addWidget(self.catalog_table, 1)

    def _activate_combo(self):
        model = self.model_combo.currentText().strip()
        if model:
            self.select_model_requested.emit(model)

    def _pull_custom(self):
        model = self.custom_pull_input.text().strip()
        if model:
            self.pull_model_requested.emit(model)
            self.custom_pull_input.clear()

    def update_data(self, active_model: str, models: list, pull_info: dict, ollama_online: bool):
        self._active_model = active_model or ""
        self._installed_names = {m.get("name", "") for m in models}

        # Update dropdown without clobbering user interaction
        if not self.model_combo.view().isVisible():
            current_items = [self.model_combo.itemText(i) for i in range(self.model_combo.count())]
            target_items = [m.get("name", "") for m in models if m.get("name")]
            if active_model and active_model not in target_items:
                target_items.insert(0, active_model)
            if current_items != target_items:
                self.model_combo.clear()
                self.model_combo.addItems(target_items)
            idx = self.model_combo.findText(active_model)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)

        # Installed Models Table
        self.installed_table.setRowCount(len(models))
        for row, m in enumerate(models):
            name = m.get("name", "")
            is_active = name == active_model
            self.installed_table.setRowHeight(row, 34)
            self.installed_table.setItem(row, 0, QTableWidgetItem(name))
            self.installed_table.setItem(row, 1, QTableWidgetItem(str(m.get("parameter_size", "—"))))
            self.installed_table.setItem(row, 2, QTableWidgetItem(str(m.get("quantization", "—"))))
            self.installed_table.setItem(row, 3, QTableWidgetItem(f"{m.get('size_gb', 0.0)} GB"))

            status_item = QTableWidgetItem("● ACTIVE" if is_active else "READY")
            status_item.setForeground(Qt.green if is_active else Qt.cyan)
            self.installed_table.setItem(row, 4, status_item)

            action_box = QWidget()
            h = QHBoxLayout(action_box)
            h.setContentsMargins(4, 2, 4, 2)
            h.setSpacing(4)

            use_btn = QPushButton("ACTIVE" if is_active else "USE")
            use_btn.setObjectName("primary_btn" if not is_active else "secondary_btn")
            use_btn.setEnabled(not is_active)
            use_btn.clicked.connect(lambda checked=False, n=name: self.select_model_requested.emit(n))

            del_btn = QPushButton("✕")
            del_btn.setObjectName("secondary_btn")
            del_btn.setFixedWidth(28)
            del_btn.setEnabled(not is_active)
            del_btn.clicked.connect(lambda checked=False, n=name: self.delete_model_requested.emit(n))

            h.addWidget(use_btn)
            h.addWidget(del_btn)
            self.installed_table.setCellWidget(row, 5, action_box)

        # Pull status label
        if not ollama_online:
            self.pull_status_label.setText("Ollama is offline. Run 'ollama serve' to list or pull models.")
            self.pull_status_label.setStyleSheet("color: #EF4444; font-size: 11px;")
        elif pull_info.get("active"):
            self.pull_status_label.setText(
                f"Pulling {pull_info.get('model')}: {pull_info.get('status')} ({pull_info.get('percent', 0)}%)"
            )
            self.pull_status_label.setStyleSheet("color: #56D9E8; font-size: 11px;")
        elif pull_info.get("error"):
            self.pull_status_label.setText(f"Pull failed: {pull_info.get('error')}")
            self.pull_status_label.setStyleSheet("color: #EF4444; font-size: 11px;")
        elif pull_info.get("status") not in ("", "idle"):
            self.pull_status_label.setText(str(pull_info.get("status")))
            self.pull_status_label.setStyleSheet("color: #22C55E; font-size: 11px;")
        else:
            self.pull_status_label.setText("Ready to pull from Ollama library.")
            self.pull_status_label.setStyleSheet("color: #65727F; font-size: 11px;")

        # Catalog Table
        for row, (name, size_str, desc) in enumerate(MODEL_CATALOG):
            self.catalog_table.setRowHeight(row, 34)
            self.catalog_table.setItem(row, 0, QTableWidgetItem(name))
            self.catalog_table.setItem(row, 1, QTableWidgetItem(size_str))
            self.catalog_table.setItem(row, 2, QTableWidgetItem(desc))

            installed = name in self._installed_names
            btn = QPushButton("INSTALLED" if installed else "INSTALL")
            btn.setObjectName("secondary_btn" if installed else "primary_btn")
            btn.setEnabled(not installed and ollama_online and not pull_info.get("active"))
            btn.clicked.connect(lambda checked=False, n=name: self.pull_model_requested.emit(n))

            wrap = QWidget()
            hl = QHBoxLayout(wrap)
            hl.setContentsMargins(4, 2, 4, 2)
            hl.addWidget(btn)
            self.catalog_table.setCellWidget(row, 3, wrap)


class SettingsTab(QWidget):
    save_requested = Signal(dict)
    restart_gui_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        layout.addWidget(_make_header("Settings", "Environment preferences stored in .env"))

        form = QFrame()
        form.setObjectName("panel_card")
        g = QGridLayout(form)
        g.setContentsMargins(14, 14, 14, 14)
        g.setSpacing(10)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setStyleSheet(
            "background-color: #10151B; border: 1px solid #22303F; border-radius: 6px; padding: 6px 10px; color: #E6EDF2;"
        )
        self.endpoint_input = QLineEdit()
        self.voice_input = QLineEdit()
        self.rate_input = QLineEdit()
        self.adb_input = QLineEdit()
        self.porcupine_status = QLabel("Not configured")
        self.porcupine_status.setObjectName("meta_label")

        rows = [
            ("Ollama Model", self.model_combo),
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

        btn_row = QHBoxLayout()
        save_btn = QPushButton("SAVE TO .ENV")
        save_btn.setObjectName("primary_btn")
        save_btn.clicked.connect(self._emit_save)

        restart_btn = QPushButton("↻ REFRESH / RESTART GUI")
        restart_btn.setObjectName("secondary_btn")
        restart_btn.clicked.connect(self.restart_gui_requested.emit)

        btn_row.addWidget(save_btn)
        btn_row.addWidget(restart_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()

    def update_data(self, cfg: dict, models: list = None):
        if not self.model_combo.hasFocus() and not self.model_combo.view().isVisible():
            model_names = [m.get("name", "") for m in (models or []) if m.get("name")]
            active = cfg.get("ollama_model", "")
            if active and active not in model_names:
                model_names.insert(0, active)
            existing = [self.model_combo.itemText(i) for i in range(self.model_combo.count())]
            if existing != model_names and model_names:
                self.model_combo.clear()
                self.model_combo.addItems(model_names)
            self.model_combo.setCurrentText(active)
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
                "ollama_model": self.model_combo.currentText().strip(),
                "ollama_endpoint": self.endpoint_input.text().strip(),
                "macos_tts_voice": self.voice_input.text().strip(),
                "macos_tts_rate": self.rate_input.text().strip(),
                "phone_adb_target": self.adb_input.text().strip(),
            }
        )
