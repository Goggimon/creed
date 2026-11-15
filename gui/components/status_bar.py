# gui/components/status_bar.py

import math
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class NeuralLinkBar(QWidget):
    """Subtle animated telemetry bar reflecting system activity."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(28)
        self._phase = 0.0
        self._active = False
        self._timer = QTimer(self)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_active(self, active: bool):
        self._active = active

    def _tick(self):
        step = 0.35 if self._active else 0.1
        self._phase = (self._phase + step) % (2 * math.pi)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bars = 18
        spacing = max(4, self.width() // bars)
        bar_w = max(2, spacing - 3)
        h = self.height() - 4

        for i in range(bars):
            wave = 0.5 + 0.5 * math.sin(self._phase + i * 0.55)
            amp = 0.35 + 0.65 * wave if self._active else 0.18 + 0.28 * wave
            bh = max(3, int(h * amp))
            x = i * spacing + 2
            y = self.height() - bh - 2
            alpha = 200 if self._active else 95
            painter.fillRect(x, y, bar_w, bh, QColor(86, 217, 232, alpha))


class StatusBar(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("systems_panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QLabel("SYSTEM STATUS")
        header.setObjectName("section_header")
        layout.addWidget(header)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(10, 10)
        self.system_state = QLabel("Idle")
        self.system_state.setObjectName("status_value")
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.system_state)
        status_row.addStretch()
        layout.addLayout(status_row)

        self.model_label = QLabel("MODEL: Ollama • qwen2.5:7b")
        self.model_label.setObjectName("meta_label")
        layout.addWidget(self.model_label)

        self.subsystems_label = QLabel("Core: Online  |  Voice: Ready")
        self.subsystems_label.setObjectName("meta_label")
        self.subsystems_label.setWordWrap(True)
        layout.addWidget(self.subsystems_label)

        link_hdr = QLabel("NEURAL LINK")
        link_hdr.setObjectName("section_header")
        layout.addWidget(link_hdr)

        self.neural_bar = NeuralLinkBar()
        layout.addWidget(self.neural_bar)

        self.set_status("Idle")

    def set_status(self, state: str):
        self.system_state.setText(state.upper())
        color_map = {
            "Idle": "#22C55E",
            "Listening": "#56D9E8",
            "Recording": "#F59E0B",
            "Processing": "#56D9E8",
            "Speaking": "#22C55E",
            "Retrying Connection": "#F97316",
            "Error": "#EF4444",
            "Stopped": "#EAB308",
        }
        color = color_map.get(state, "#65727F")
        self.status_dot.setStyleSheet(f"background-color: {color}; border-radius: 5px;")
        self.neural_bar.set_active(state in ("Listening", "Recording", "Processing", "Speaking"))

    def update_snapshot(self, snapshot: dict):
        model = snapshot.get("model", "unknown")
        self.model_label.setText(f"MODEL: Ollama • {model}")
        systems = snapshot.get("systems", [])
        online = sum(1 for s in systems if s.get("state") in ("Online", "Configured"))
        self.subsystems_label.setText(
            f"Systems: {online}/{len(systems)} Ready  |  Tools: {len(snapshot.get('tools', []))}"
        )
