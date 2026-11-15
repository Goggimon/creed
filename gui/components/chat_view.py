# gui/components/chat_view.py

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class ChatBubble(QFrame):
    def __init__(self, text: str, is_user: bool = False):
        super().__init__()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)

        bubble = QFrame()
        bubble.setObjectName("user_msg" if is_user else "ai_msg")
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(14, 10, 14, 10)
        bubble_layout.setSpacing(4)

        role_lbl = QLabel("OPERATOR" if is_user else "CREED // CORE")
        role_lbl.setObjectName("msg_role_user" if is_user else "msg_role_ai")
        bubble_layout.addWidget(role_lbl)

        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.label.setObjectName("msg_body")
        bubble_layout.addWidget(self.label)

        if is_user:
            layout.addStretch(1)
            layout.addWidget(bubble, 4)
        else:
            layout.addWidget(bubble, 5)
            layout.addStretch(1)

        self.bubble = bubble

    def append_text(self, text: str):
        self.label.setText(self.label.text() + text)


class ChatView(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setObjectName("chat_area")

        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setSpacing(10)
        self.chat_layout.setContentsMargins(8, 8, 8, 8)
        self.chat_layout.addStretch()
        self.setWidget(self.chat_container)

    def clear_bubbles(self):
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def add_bubble(self, text: str, is_user: bool = False) -> ChatBubble:
        bubble = ChatBubble(text, is_user)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        self.scroll_to_bottom()
        return bubble

    def add_tool_badge(self, text: str):
        lbl = QLabel(f"⚙  {text}")
        lbl.setObjectName("tool_badge")
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, lbl)
        self.scroll_to_bottom()

    def scroll_to_bottom(self):
        QTimer.singleShot(15, self._apply_scroll)

    def _apply_scroll(self):
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
