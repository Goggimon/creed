# gui/components/jee_tab.py

import re
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from components.chat_view import ChatView
from components.input_bar import InputBar

try:
    from PySide6.QtSvgWidgets import QSvgWidget
except ImportError:
    QSvgWidget = None


class JEETutorTab(QWidget):
    """Dedicated JEE Main & Advanced Tutor with auto-reasoning model, SVG diagrams, Flashcards, Custom Tests & 5-Yr PYQ Vault."""

    jee_prompt_submitted = Signal(str)
    voice_requested = Signal()
    stop_requested = Signal()
    add_flashcard_requested = Signal(str, str, str, str)
    toggle_flashcard_requested = Signal(int)
    delete_flashcard_requested = Signal(int)
    generate_test_requested = Signal(str, str, str, int)
    submit_test_requested = Signal(str, str, int, int)

    def __init__(self):
        super().__init__()
        self._flashcards = []
        self._card_index = 0
        self._card_flipped = False
        self._questions = []
        self._question_groups = []
        self._test_seconds = 0
        self._test_timer = QTimer(self)
        self._test_timer.setInterval(1000)
        self._test_timer.timeout.connect(self._tick_test_timer)
        self._current_bubble = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # Header + Auto-Model Badge
        top = QHBoxLayout()
        hdr_box = QVBoxLayout()
        hdr_box.setSpacing(2)
        title = QLabel("JEE Tutor")
        title.setObjectName("tab_title")
        sub = QLabel("Auto-switches to your strongest local reasoning model for derivations, diagrams & tests")
        sub.setObjectName("meta_label")
        hdr_box.addWidget(title)
        hdr_box.addWidget(sub)

        self.model_badge = QLabel("Reasoning Model: auto")
        self.model_badge.setObjectName("accent_label")

        top.addLayout(hdr_box)
        top.addStretch()
        top.addWidget(self.model_badge)
        layout.addLayout(top)

        # Sub-navigation Pills
        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)
        self._sub_btns = []
        for idx, label in enumerate(["Tutor & Diagrams", "Flashcards", "Custom Test", "5-Yr PYQ Vault"]):
            btn = QPushButton(label)
            btn.setObjectName("primary_btn" if idx == 0 else "secondary_btn")
            btn.clicked.connect(lambda checked=False, i=idx: self._switch_sub(i))
            nav_row.addWidget(btn)
            self._sub_btns.append(btn)
        nav_row.addStretch()
        layout.addLayout(nav_row)

        self.sub_stack = QStackedWidget()
        layout.addWidget(self.sub_stack, 1)

        self.sub_stack.addWidget(self._build_tutor_page())
        self.sub_stack.addWidget(self._build_flashcards_page())
        self.sub_stack.addWidget(self._build_test_page())
        self.sub_stack.addWidget(self._build_vault_page())

    def _switch_sub(self, index: int):
        self.sub_stack.setCurrentIndex(index)
        for i, b in enumerate(self._sub_btns):
            b.setObjectName("primary_btn" if i == index else "secondary_btn")
            b.style().unpolish(b)
            b.style().polish(b)

    # 1. Tutor & SVG Diagram Page
    def _build_tutor_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(8)

        split = QHBoxLayout()
        split.setSpacing(10)

        self.chat_view = ChatView()
        split.addWidget(self.chat_view, 3)

        self.diagram_card = QFrame()
        self.diagram_card.setObjectName("panel_card")
        self.diagram_card.setMinimumWidth(280)
        d_lay = QVBoxLayout(self.diagram_card)
        d_lay.setContentsMargins(12, 10, 12, 10)
        d_hdr = QLabel("DIAGRAM PREVIEW")
        d_hdr.setObjectName("section_header")
        d_lay.addWidget(d_hdr)

        if QSvgWidget is not None:
            self.svg_widget = QSvgWidget()
            self.svg_widget.setMinimumHeight(220)
            d_lay.addWidget(self.svg_widget, 1)
        else:
            self.svg_widget = None

        self.diagram_hint = QLabel(
            "Ask for a free-body diagram, circuit, ray diagram, or graph to render it here."
        )
        self.diagram_hint.setObjectName("meta_label")
        self.diagram_hint.setWordWrap(True)
        d_lay.addWidget(self.diagram_hint)
        split.addWidget(self.diagram_card, 2)

        lay.addLayout(split, 1)

        self.tutor_status_label = QLabel("Ready — auto-switches to your reasoning model")
        self.tutor_status_label.setObjectName("meta_label")
        lay.addWidget(self.tutor_status_label)

        self.input_bar = InputBar("Ask a JEE Physics, Chemistry, or Maths question (or request a diagram)...")
        self.input_bar.submitted.connect(self._send_jee_prompt)
        self.input_bar.voice_clicked.connect(self.voice_requested.emit)
        self.input_bar.stop_clicked.connect(self.stop_requested.emit)
        lay.addWidget(self.input_bar)
        self._tutor_model_name = "reasoning model"
        self._tutor_tokens = 0
        self._tutor_elapsed = 0
        self._tutor_timer = QTimer(self)
        self._tutor_timer.setInterval(1000)
        self._tutor_timer.timeout.connect(self._tick_tutor_timer)
        return page

    def _tick_tutor_timer(self):
        self._tutor_elapsed += 1
        self.tutor_status_label.setText(
            f"Working ({self._tutor_model_name}) • {self._tutor_tokens} chunks • {self._tutor_elapsed}s"
        )

    def _send_jee_prompt(self, text: str):
        self.chat_view.add_bubble(text, True)
        self._current_bubble = self.chat_view.add_bubble("", False)
        self._tutor_tokens = 0
        self._tutor_elapsed = 0
        self._tutor_timer.start()
        self.tutor_status_label.setText(f"Sending to {self._tutor_model_name}...")
        self.jee_prompt_submitted.emit(text)

    def append_token(self, token: str):
        if self._current_bubble is None:
            self._current_bubble = self.chat_view.add_bubble("", False)
        self._tutor_tokens += 1
        self._current_bubble.append_text(token)
        self.chat_view.scroll_to_bottom()
        self._try_render_svg(self._current_bubble._raw_text)

    def finish_turn(self):
        self._tutor_timer.stop()
        self.tutor_status_label.setText(
            f"Completed ({self._tutor_model_name}) • {self._tutor_tokens} chunks in {self._tutor_elapsed}s"
        )
        if self._current_bubble is not None:
            self._try_render_svg(self._current_bubble._raw_text)
        self._current_bubble = None

    def _try_render_svg(self, text: str):
        if self.svg_widget is None:
            return
        match = re.search(r"```svg\s*([\s\S]*?<svg[\s\S]*?</svg>)\s*```", text, re.IGNORECASE)
        if not match:
            match = re.search(r"(<svg[\s\S]*?</svg>)", text, re.IGNORECASE)
        if match:
            svg_bytes = match.group(1).strip().encode("utf-8")
            self.svg_widget.load(svg_bytes)
            self.diagram_hint.setText("Rendered live SVG diagram from JEE Tutor.")

    # 2. Flashcards Page
    def _build_flashcards_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(10)

        top = QHBoxLayout()
        self.fc_filter = QComboBox()
        self.fc_filter.addItems(["All", "Physics", "Chemistry", "Maths"])
        self.fc_filter.setStyleSheet(
            "background-color: #15171D; border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; padding: 5px 10px;"
        )
        self.fc_filter.currentTextChanged.connect(lambda: self._render_card())
        self.fc_counter = QLabel("0 / 0")
        self.fc_counter.setObjectName("meta_label")
        top.addWidget(QLabel("Subject:"))
        top.addWidget(self.fc_filter)
        top.addStretch()
        top.addWidget(self.fc_counter)
        lay.addLayout(top)

        self.card_frame = QFrame()
        self.card_frame.setObjectName("panel_card")
        self.card_frame.setMinimumHeight(180)
        cf_lay = QVBoxLayout(self.card_frame)
        cf_lay.setContentsMargins(20, 18, 20, 18)
        cf_lay.setAlignment(Qt.AlignCenter)

        self.card_meta = QLabel("PHYSICS • MODERN PHYSICS")
        self.card_meta.setObjectName("accent_label")
        self.card_meta.setAlignment(Qt.AlignCenter)
        self.card_text = QLabel("No flashcards yet.")
        self.card_text.setWordWrap(True)
        self.card_text.setAlignment(Qt.AlignCenter)
        self.card_text.setStyleSheet("font-size: 15px; font-weight: 500; padding: 12px;")
        cf_lay.addWidget(self.card_meta)
        cf_lay.addWidget(self.card_text)
        lay.addWidget(self.card_frame)

        ctrl = QHBoxLayout()
        prev_btn = QPushButton("◂ Prev")
        prev_btn.setObjectName("secondary_btn")
        prev_btn.clicked.connect(lambda: self._step_card(-1))
        flip_btn = QPushButton("Flip Card")
        flip_btn.setObjectName("primary_btn")
        flip_btn.clicked.connect(self._flip_card)
        next_btn = QPushButton("Next ▸")
        next_btn.setObjectName("secondary_btn")
        next_btn.clicked.connect(lambda: self._step_card(1))
        self.master_btn = QPushButton("Mark Mastered")
        self.master_btn.setObjectName("secondary_btn")
        self.master_btn.clicked.connect(self._toggle_mastered)
        del_btn = QPushButton("Delete")
        del_btn.setObjectName("secondary_btn")
        del_btn.clicked.connect(self._delete_card)

        for b in (prev_btn, flip_btn, next_btn, self.master_btn, del_btn):
            ctrl.addWidget(b)
        lay.addLayout(ctrl)

        # Add Card Bar
        add_row = QHBoxLayout()
        self.add_subj = QComboBox()
        self.add_subj.addItems(["Physics", "Chemistry", "Maths"])
        self.add_subj.setStyleSheet(self.fc_filter.styleSheet())
        self.add_chap = QLineEdit()
        self.add_chap.setPlaceholderText("Chapter")
        self.add_front = QLineEdit()
        self.add_front.setPlaceholderText("Front (Question / Formula name)")
        self.add_back = QLineEdit()
        self.add_back.setPlaceholderText("Back (Formula / Solution / Trap)")
        add_btn = QPushButton("+ Add")
        add_btn.setObjectName("primary_btn")
        add_btn.clicked.connect(self._create_card)
        add_row.addWidget(self.add_subj)
        add_row.addWidget(self.add_chap, 1)
        add_row.addWidget(self.add_front, 2)
        add_row.addWidget(self.add_back, 2)
        add_row.addWidget(add_btn)
        lay.addLayout(add_row)
        lay.addStretch()
        return page

    def _filtered_cards(self) -> list[dict]:
        subj = self.fc_filter.currentText()
        if subj == "All":
            return self._flashcards
        return [c for c in self._flashcards if c.get("subject", "").lower() == subj.lower()]

    def _render_card(self):
        cards = self._filtered_cards()
        if not cards:
            self.fc_counter.setText("0 / 0")
            self.card_meta.setText("EMPTY")
            self.card_text.setText("Add a flashcard below to start reviewing.")
            return
        self._card_index %= len(cards)
        c = cards[self._card_index]
        mastered = bool(c.get("mastered"))
        status = " • MASTERED" if mastered else ""
        self.fc_counter.setText(f"{self._card_index + 1} / {len(cards)}")
        self.card_meta.setText(f"{c.get('subject', '').upper()} • {c.get('chapter', '').upper()}{status}")
        self.card_text.setText(c.get("back", "") if self._card_flipped else c.get("front", ""))
        self.master_btn.setText("Unmark Mastered" if mastered else "Mark Mastered")

    def _flip_card(self):
        self._card_flipped = not self._card_flipped
        self._render_card()

    def _step_card(self, delta: int):
        self._card_index += delta
        self._card_flipped = False
        self._render_card()

    def _toggle_mastered(self):
        cards = self._filtered_cards()
        if cards:
            self.toggle_flashcard_requested.emit(cards[self._card_index]["id"])

    def _delete_card(self):
        cards = self._filtered_cards()
        if cards:
            self.delete_flashcard_requested.emit(cards[self._card_index]["id"])

    def _create_card(self):
        f, b = self.add_front.text().strip(), self.add_back.text().strip()
        if f and b:
            self.add_flashcard_requested.emit(
                self.add_subj.currentText(),
                self.add_chap.text().strip() or "General",
                f,
                b,
            )
            self.add_front.clear()
            self.add_back.clear()

    # 3. Custom Test Page
    def _build_test_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(8)

        cfg_row = QHBoxLayout()
        self.test_subj = QComboBox()
        self.test_subj.addItems(["Physics", "Chemistry", "Mathematics", "Mixed PCM"])
        self.test_subj.setStyleSheet(
            "background-color: #15171D; border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; padding: 5px 10px;"
        )
        self.test_diff = QComboBox()
        self.test_diff.addItems(["JEE Main", "JEE Advanced"])
        self.test_diff.setStyleSheet(self.test_subj.styleSheet())
        self.test_count = QComboBox()
        self.test_count.addItems(["5", "10", "15"])
        self.test_count.setStyleSheet(self.test_subj.styleSheet())
        self.test_chap = QLineEdit()
        self.test_chap.setPlaceholderText("Optional chapter (e.g. Ray Optics)")
        gen_btn = QPushButton("Generate Test")
        gen_btn.setObjectName("primary_btn")
        gen_btn.clicked.connect(self._request_test)
        self.test_timer_lbl = QLabel("00:00")
        self.test_timer_lbl.setObjectName("accent_label")

        cfg_row.addWidget(self.test_subj)
        cfg_row.addWidget(self.test_diff)
        cfg_row.addWidget(self.test_count)
        cfg_row.addWidget(self.test_chap, 1)
        cfg_row.addWidget(gen_btn)
        cfg_row.addWidget(self.test_timer_lbl)
        lay.addLayout(cfg_row)

        self.test_status = QLabel("Configure a custom test and click Generate Test.")
        self.test_status.setObjectName("meta_label")
        lay.addWidget(self.test_status)

        self.test_progress = QProgressBar()
        self.test_progress.setRange(0, 0)
        self.test_progress.hide()
        lay.addWidget(self.test_progress)
        self._gen_elapsed = 0
        self._gen_timer = QTimer(self)
        self._gen_timer.setInterval(1000)
        self._gen_timer.timeout.connect(self._tick_gen_timer)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("chat_area")
        self.test_container = QWidget()
        self.test_layout = QVBoxLayout(self.test_container)
        self.test_layout.setSpacing(10)
        self.test_layout.addStretch()
        scroll.setWidget(self.test_container)
        lay.addWidget(scroll, 1)

        foot = QHBoxLayout()
        self.submit_test_btn = QPushButton("Submit & Grade")
        self.submit_test_btn.setObjectName("primary_btn")
        self.submit_test_btn.setEnabled(False)
        self.submit_test_btn.clicked.connect(self._grade_test)
        self.test_history_lbl = QLabel("Recent tests: none")
        self.test_history_lbl.setObjectName("meta_label")
        foot.addWidget(self.submit_test_btn)
        foot.addSpacing(12)
        foot.addWidget(self.test_history_lbl, 1)
        lay.addLayout(foot)
        return page

    def _request_test(self):
        self._gen_elapsed = 0
        self.test_progress.show()
        self._gen_timer.start()
        self.test_status.setText(
            f"Step 1/3: Sending prompt to {self._tutor_model_name} for {self.test_count.currentText()} {self.test_diff.currentText()} questions..."
        )
        self.submit_test_btn.setEnabled(False)
        self.generate_test_requested.emit(
            self.test_subj.currentText(),
            self.test_chap.text().strip(),
            self.test_diff.currentText(),
            int(self.test_count.currentText()),
        )

    def _tick_gen_timer(self):
        self._gen_elapsed += 1
        step = "Step 2/3: Reasoning & writing MCQs" if self._gen_elapsed < 10 else "Step 2/3: Finalizing solutions & JSON"
        self.test_status.setText(f"{step} ({self._tutor_model_name}) • {self._gen_elapsed}s elapsed...")

    def _tick_test_timer(self):
        self._test_seconds += 1
        m, s = divmod(self._test_seconds, 60)
        self.test_timer_lbl.setText(f"{m:02d}:{s:02d}")

    def load_generated_test(self, data: dict):
        self._gen_timer.stop()
        self.test_progress.hide()
        while self.test_layout.count() > 1:
            item = self.test_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._questions = data.get("questions", [])
        self._question_groups = []
        self._test_seconds = 0
        self._test_timer.start()
        self.test_status.setText(
            f"Step 3/3: Ready — {len(self._questions)} Qs generated by {data.get('model', '')} in {self._gen_elapsed}s"
        )
        self.submit_test_btn.setEnabled(bool(self._questions))

        for idx, q in enumerate(self._questions):
            card = QFrame()
            card.setObjectName("panel_card")
            v = QVBoxLayout(card)
            v.setContentsMargins(12, 10, 12, 10)
            v.setSpacing(6)
            qlbl = QLabel(f"Q{idx + 1}. {q.get('question', '')}")
            qlbl.setWordWrap(True)
            qlbl.setStyleSheet("font-weight: 600; font-size: 12.5px;")
            v.addWidget(qlbl)

            grp = QButtonGroup(card)
            for oi, opt in enumerate(q.get("options", [])):
                rb = QRadioButton(f"{chr(65 + oi)}. {opt}")
                grp.addButton(rb, oi)
                v.addWidget(rb)
            exp_lbl = QLabel("")
            exp_lbl.setObjectName("meta_label")
            exp_lbl.setWordWrap(True)
            exp_lbl.hide()
            v.addWidget(exp_lbl)
            self._question_groups.append((grp, exp_lbl))
            self.test_layout.insertWidget(self.test_layout.count() - 1, card)

    def _grade_test(self):
        self._test_timer.stop()
        score = 0
        for q, (grp, exp_lbl) in zip(self._questions, self._question_groups):
            chosen = grp.checkedId()
            ans = int(q.get("answer_index", 0))
            correct = chosen == ans
            if correct:
                score += 1
            prefix = "✓ Correct" if correct else f"✗ Answer: {chr(65 + ans)}"
            exp_lbl.setText(f"{prefix} — {q.get('explanation', '')}")
            exp_lbl.setStyleSheet(
                f"color: {'#34D399' if correct else '#F87171'}; font-size: 11px;"
            )
            exp_lbl.show()
        total = len(self._questions)
        self.test_status.setText(f"Score: {score} / {total} ({int(score * 100 / max(1, total))}%)")
        self.submit_test_btn.setEnabled(False)
        self.submit_test_requested.emit(
            self.test_subj.currentText(),
            self.test_diff.currentText(),
            score,
            total,
        )

    # 4. 5-Year PYQ Vault Page
    def _build_vault_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(8)

        f_row = QHBoxLayout()
        self.vault_subj = QComboBox()
        self.vault_subj.addItems(["All", "Physics", "Chemistry", "Mathematics"])
        self.vault_subj.setStyleSheet(
            "background-color: #15171D; border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; padding: 5px 10px;"
        )
        self.vault_subj.currentTextChanged.connect(lambda: self._render_vault())
        ask_btn = QPushButton("Practice Selected Chapter in Tutor")
        ask_btn.setObjectName("primary_btn")
        ask_btn.clicked.connect(self._practice_selected_chapter)
        f_row.addWidget(QLabel("Subject:"))
        f_row.addWidget(self.vault_subj)
        f_row.addStretch()
        f_row.addWidget(ask_btn)
        lay.addLayout(f_row)

        self.vault_table = QTableWidget(0, 5)
        self.vault_table.setHorizontalHeaderLabels(
            ["SUBJECT", "CHAPTER", "5-YR WEIGHTAGE", "AVG Qs", "ROI & KEY PYQ PATTERNS"]
        )
        self.vault_table.setStyleSheet(
            "QTableWidget { background-color: #101216; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; "
            "gridline-color: rgba(255,255,255,0.05); color: #ECEEF2; font-size: 11px; }"
            "QHeaderView::section { background-color: #15171D; color: #8E95A2; border: none; "
            "border-bottom: 1px solid rgba(255,255,255,0.08); padding: 6px; font-size: 10px; font-weight: 600; }"
        )
        self.vault_table.verticalHeader().setVisible(False)
        self.vault_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.vault_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hdr = self.vault_table.horizontalHeader()
        for col in (0, 1, 2, 3):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.Stretch)
        lay.addWidget(self.vault_table, 1)
        self._vault_data = []
        return page

    def _render_vault(self):
        subj = self.vault_subj.currentText()
        rows = [
            r for r in self._vault_data
            if subj == "All" or r.get("subject", "").lower() == subj.lower()
        ]
        self.vault_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.vault_table.setRowHeight(i, 44)
            self.vault_table.setItem(i, 0, QTableWidgetItem(r.get("subject", "")))
            self.vault_table.setItem(i, 1, QTableWidgetItem(r.get("chapter", "")))
            self.vault_table.setItem(i, 2, QTableWidgetItem(r.get("weightage", "")))
            self.vault_table.setItem(i, 3, QTableWidgetItem(r.get("avg_qs", "")))
            self.vault_table.setItem(
                i, 4, QTableWidgetItem(f"[{r.get('roi', '')}] {r.get('key_patterns', '')}")
            )

    def _practice_selected_chapter(self):
        row = self.vault_table.currentRow()
        if row < 0:
            return
        chap = self.vault_table.item(row, 1).text()
        subj = self.vault_table.item(row, 0).text()
        self._switch_sub(0)
        self._send_jee_prompt(
            f"Give me a quick high-yield 5-year PYQ summary and 1 tough JEE Main practice problem for {subj} - {chap}, with a diagram if applicable."
        )

    def update_data(self, snapshot: dict):
        self._tutor_model_name = snapshot.get("jee_model", "auto")
        self.model_badge.setText(f"Reasoning Model: {self._tutor_model_name}")
        self._flashcards = snapshot.get("jee_flashcards", [])
        self._render_card()

        tests = snapshot.get("jee_tests", [])
        if tests:
            latest = tests[0]
            self.test_history_lbl.setText(
                f"Last: {latest['subject']} ({latest['difficulty']}) {latest['score']}/{latest['total']}"
            )

        vault = snapshot.get("pyq_vault", [])
        if vault and vault != self._vault_data:
            self._vault_data = vault
            self._render_vault()
