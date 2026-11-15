# gui/components/input_bar.py

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QWidget


class CommandTextEdit(QPlainTextEdit):
    """Multi-line command input: Enter submits, Shift+Enter inserts a newline."""

    submitted = Signal()

    def __init__(self, placeholder: str = ""):
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.setFixedHeight(38)
        self.textChanged.connect(self._adjust_height)

    def _adjust_height(self):
        doc_height = int(self.document().size().height())
        line_h = self.fontMetrics().lineSpacing()
        target = max(38, min(104, doc_height * line_h + 16))
        if self.height() != target:
            self.setFixedHeight(target)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.submitted.emit()
            return
        super().keyPressEvent(event)


class InputBar(QWidget):
    submitted = Signal(str)
    voice_clicked = Signal()
    stop_clicked = Signal()

    def __init__(self, placeholder: str = "Ask CREED anything..."):
        super().__init__()
        self.setObjectName("input_bar_container")

        bottom_layout = QHBoxLayout(self)
        bottom_layout.setContentsMargins(0, 6, 0, 0)
        bottom_layout.setSpacing(8)
        bottom_layout.setAlignment(Qt.AlignBottom)

        self.input_field = CommandTextEdit(placeholder)
        self.input_field.submitted.connect(self.handle_submit)

        self.voice_btn = QPushButton("🎙")
        self.voice_btn.setObjectName("secondary_btn")
        self.voice_btn.setFixedSize(40, 38)
        self.voice_btn.setToolTip("Toggle voice listening")
        self.voice_btn.clicked.connect(self.voice_clicked.emit)

        self.stop_btn = QPushButton("⏹")
        self.stop_btn.setObjectName("secondary_btn")
        self.stop_btn.setFixedSize(40, 38)
        self.stop_btn.setToolTip("Stop current generation / speech")
        self.stop_btn.clicked.connect(self.stop_clicked.emit)

        self.send_btn = QPushButton("▶")
        self.send_btn.setObjectName("primary_btn")
        self.send_btn.setFixedSize(48, 38)
        self.send_btn.setToolTip("Send command (Enter; Shift+Enter for new line)")
        self.send_btn.clicked.connect(self.handle_submit)

        bottom_layout.addWidget(self.input_field, 1)
        bottom_layout.addWidget(self.voice_btn)
        bottom_layout.addWidget(self.stop_btn)
        bottom_layout.addWidget(self.send_btn)

    def handle_submit(self):
        text = self.input_field.toPlainText().strip()
        if text:
            self.submitted.emit(text)
            self.input_field.clear()
            self.input_field.setFixedHeight(38)
