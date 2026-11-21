# gui/components/command_palette.py

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)


COMMANDS = [
    ("00  Overview Hub", "tab", 0),
    ("01  Intelligence (Conversation)", "tab", 1),
    ("02  Memory & Knowledge Engine", "tab", 2),
    ("03  Task & Automation Engine", "tab", 3),
    ("04  Machine Control (macOS)", "tab", 4),
    ("05  Tools Registry", "tab", 5),
    ("06  AI Models Registry", "tab", 6),
    ("07  System Configuration", "tab", 7),
]


class CommandPalette(QDialog):
    """Apple Spotlight / Siri-style floating Cmd+K command interface."""

    tab_requested = Signal(int)
    prompt_requested = Signal(str)
    voice_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(640, 340)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 20)

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background-color: rgba(15, 18, 28, 244); "
            "border: 1px solid rgba(103, 232, 249, 0.45); border-radius: 16px; }"
        )
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 180))
        card.setGraphicsEffect(shadow)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        top_row = QHBoxLayout()
        hdr = QLabel("CREED  •  SPOTLIGHT COMMAND")
        hdr.setStyleSheet(
            "color: #67E8F9; font-family: 'Menlo', monospace; font-size: 10px; font-weight: 700; letter-spacing: 1.1px; border: none;"
        )
        esc_lbl = QLabel("ESC")
        esc_lbl.setStyleSheet(
            "color: #64748B; font-family: 'Menlo', monospace; font-size: 9.5px; border: none;"
        )
        top_row.addWidget(hdr)
        top_row.addStretch()
        top_row.addWidget(esc_lbl)
        lay.addLayout(top_row)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask CREED anything, run a tool, or jump to a subsystem...")
        self.input.setStyleSheet(
            "QLineEdit { background: rgba(7, 8, 12, 210); border: 1px solid rgba(255,255,255,0.12); "
            "border-radius: 10px; padding: 10px 14px; font-size: 14px; color: #F8FAFC; }"
            "QLineEdit:focus { border: 1px solid #67E8F9; }"
        )
        self.input.textChanged.connect(self._filter)
        self.input.returnPressed.connect(self._execute)

        mic_btn = QPushButton("🎙")
        mic_btn.setFixedSize(40, 40)
        mic_btn.setToolTip("Speak command (Siri-style)")
        mic_btn.setStyleSheet(
            "QPushButton { background: rgba(103, 232, 249, 0.14); border: 1px solid rgba(103, 232, 249, 0.45); "
            "border-radius: 20px; font-size: 15px; }"
            "QPushButton:hover { background: rgba(103, 232, 249, 0.28); }"
        )
        mic_btn.clicked.connect(self._trigger_voice)

        input_row.addWidget(self.input, 1)
        input_row.addWidget(mic_btn)
        lay.addLayout(input_row)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "QListWidget { background: rgba(8, 10, 16, 190); border: 1px solid rgba(255,255,255,0.06); "
            "border-radius: 10px; padding: 5px; font-family: 'Menlo', monospace; font-size: 11.5px; }"
            "QListWidget::item { padding: 7px 10px; border-radius: 6px; color: #CBD5E1; }"
            "QListWidget::item:selected { background: rgba(103, 232, 249, 0.18); color: #F8FAFC; }"
        )
        self.list_widget.itemDoubleClicked.connect(lambda _: self._execute())
        lay.addWidget(self.list_widget, 1)

        outer.addWidget(card)
        self._filter("")

    def show_centered(self):
        if self.parent():
            pg = self.parent().geometry()
            self.move(
                pg.x() + (pg.width() - self.width()) // 2,
                pg.y() + 86,
            )
        self.input.clear()
        self._filter("")
        self.show()
        self.input.setFocus()

    def _trigger_voice(self):
        self.close()
        self.voice_requested.emit()

    def _filter(self, text: str):
        q = text.strip().lower()
        self.list_widget.clear()
        if q:
            prompt_item = QListWidgetItem(f"▸ Ask CREED: \"{text.strip()}\"")
            prompt_item.setData(Qt.UserRole, ("prompt", text.strip()))
            self.list_widget.addItem(prompt_item)
        for label, kind, target in COMMANDS:
            if not q or q in label.lower():
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, (kind, target))
                self.list_widget.addItem(item)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def _execute(self):
        item = self.list_widget.currentItem()
        if not item:
            txt = self.input.text().strip()
            if txt:
                self.prompt_requested.emit(txt)
            self.close()
            return
        kind, target = item.data(Qt.UserRole)
        self.close()
        if kind == "tab":
            self.tab_requested.emit(int(target))
        elif kind == "prompt":
            self.prompt_requested.emit(str(target))
