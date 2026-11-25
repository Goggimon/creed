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

    def __init__(self, placeholder: str = "Ask CREED anything...", enable_cloud_consent: bool = False):
        super().__init__()
        self.setObjectName("input_bar_container")
        self._enable_cloud_consent = bool(enable_cloud_consent)

        bottom_layout = QHBoxLayout(self)
        bottom_layout.setContentsMargins(0, 6, 0, 0)
        bottom_layout.setSpacing(8)
        bottom_layout.setAlignment(Qt.AlignBottom)

        self.input_field = CommandTextEdit(placeholder)
        self.input_field.submitted.connect(self.handle_submit)

        self.cloud_consent_btn = None
        if self._enable_cloud_consent:
            self.cloud_consent_btn = QPushButton("☁ CONSENT: OFF")
            self.cloud_consent_btn.setObjectName("secondary_btn")
            self.cloud_consent_btn.setCheckable(True)
            self.cloud_consent_btn.setChecked(False)
            self.cloud_consent_btn.setFixedHeight(38)
            self.cloud_consent_btn.setToolTip(
                "Allow private context to be sent to cloud for THIS SINGLE TURN only (resets after send)."
            )
            self.cloud_consent_btn.toggled.connect(self._sync_consent_label)

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
        if self.cloud_consent_btn is not None:
            bottom_layout.addWidget(self.cloud_consent_btn)
        bottom_layout.addWidget(self.voice_btn)
        bottom_layout.addWidget(self.stop_btn)
        bottom_layout.addWidget(self.send_btn)

    def _sync_consent_label(self, checked: bool):
        if self.cloud_consent_btn is None:
            return
        if checked:
            self.cloud_consent_btn.setText("☁ CONSENT: ON (1-TURN)")
            self.cloud_consent_btn.setStyleSheet(
                "color: #F59E0B; border: 1px solid #F59E0B; font-family: 'Menlo', monospace; font-size: 10.5px; font-weight: 700; padding: 0 8px;"
            )
        else:
            self.cloud_consent_btn.setText("☁ CONSENT: OFF")
            self.cloud_consent_btn.setStyleSheet("")

    def is_cloud_consent_enabled(self) -> bool:
        return bool(self.cloud_consent_btn is not None and self.cloud_consent_btn.isChecked())

    def reset_cloud_consent(self) -> None:
        if self.cloud_consent_btn is not None:
            self.cloud_consent_btn.setChecked(False)
            self._sync_consent_label(False)

    def consume_cloud_consent(self) -> bool:
        allowed = self.is_cloud_consent_enabled()
        self.reset_cloud_consent()
        return allowed

    def handle_submit(self):
        text = self.input_field.toPlainText().strip()
        if text:
            self.submitted.emit(text)
            self.input_field.clear()
            self.input_field.setFixedHeight(38)
