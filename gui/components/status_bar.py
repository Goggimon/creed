# gui/components/status_bar.py

import math
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

STATE_COLORS = {
    "Idle": "#6EA8FE",
    "Listening": "#38BDF8",
    "Recording": "#F59E0B",
    "Processing": "#818CF8",
    "Speaking": "#34D399",
    "Retrying Connection": "#FB923C",
    "Error": "#F87171",
    "Stopped": "#FBBF24",
}


class NeuralLinkBar(QWidget):
    """Smooth 30fps pill visualizer matching the active system state color."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(26)
        self._phase = 0.0
        self._active = False
        self._color = QColor("#6EA8FE")
        self._amp_smooth = 0.25
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_active(self, active: bool, color: str = "#6EA8FE"):
        self._active = active
        self._color = QColor(color)

    def _tick(self):
        target_amp = 1.0 if self._active else 0.35
        self._amp_smooth += (target_amp - self._amp_smooth) * 0.14
        step = 0.18 if self._active else 0.055
        self._phase = (self._phase + step) % (2 * math.pi)
        self.update()

    def paintEvent(self, event):
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            bars = 18
            spacing = max(4, self.width() // bars)
            bar_w = max(2.5, spacing - 3.5)
            h = self.height() - 4

            for i in range(bars):
                wave = 0.5 + 0.5 * math.sin(self._phase + i * 0.52)
                amp = (0.18 + 0.82 * wave) * self._amp_smooth
                bh = max(3.0, h * amp)
                x = i * spacing + 2.0
                y = self.height() - bh - 2.0
                c = QColor(self._color)
                c.setAlpha(int(105 + 115 * self._amp_smooth))
                painter.setBrush(c)
                painter.drawRoundedRect(QRectF(x, y, bar_w, bh), 1.5, 1.5)
        finally:
            painter.end()


class StatusBar(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("systems_panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)

        header = QLabel("SYSTEM STATUS")
        header.setObjectName("section_header")
        layout.addWidget(header)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(9, 9)
        self.system_state = QLabel("IDLE")
        self.system_state.setObjectName("status_value")
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.system_state)
        status_row.addStretch()
        layout.addLayout(status_row)

        # Explicit Uvicorn & Ollama health rows
        self.uvicorn_label = QLabel("Uvicorn   ● Checking")
        self.uvicorn_label.setStyleSheet("font-family: 'SF Mono', monospace; font-size: 10.5px; color: #8E95A2;")
        self.ollama_label = QLabel("Ollama    ● Checking")
        self.ollama_label.setStyleSheet("font-family: 'SF Mono', monospace; font-size: 10.5px; color: #8E95A2;")
        layout.addWidget(self.uvicorn_label)
        layout.addWidget(self.ollama_label)

        self.model_label = QLabel("Model: qwen2.5:7b")
        self.model_label.setObjectName("meta_label")
        layout.addWidget(self.model_label)

        self.subsystems_label = QLabel("Core: Online  •  Voice: Ready")
        self.subsystems_label.setObjectName("meta_label")
        self.subsystems_label.setWordWrap(True)
        layout.addWidget(self.subsystems_label)

        link_hdr = QLabel("ACTIVITY SIGNAL")
        link_hdr.setObjectName("section_header")
        layout.addWidget(link_hdr)

        self.neural_bar = NeuralLinkBar()
        layout.addWidget(self.neural_bar)

        self.set_status("Idle")

    def set_status(self, state: str):
        color = STATE_COLORS.get(state, "#8E95A2")
        self.system_state.setText(state)
        self.system_state.setStyleSheet(
            f"color: {color}; font-family: 'SF Mono', monospace; font-size: 12px; font-weight: 600;"
        )
        self.status_dot.setStyleSheet(f"background-color: {color}; border-radius: 4px;")
        self.neural_bar.set_active(
            state in ("Listening", "Recording", "Processing", "Speaking"), color=color
        )
        if state == "Retrying Connection":
            self.set_services_offline()

    def set_services_offline(self):
        self.uvicorn_label.setText("Uvicorn   ● Offline")
        self.uvicorn_label.setStyleSheet("font-family: 'SF Mono', monospace; font-size: 10.5px; color: #F87171;")
        self.ollama_label.setText("Ollama    ● Unknown")
        self.ollama_label.setStyleSheet("font-family: 'SF Mono', monospace; font-size: 10.5px; color: #FBBF24;")

    def update_snapshot(self, snapshot: dict):
        self.uvicorn_label.setText("Uvicorn   ● Online")
        self.uvicorn_label.setStyleSheet("font-family: 'SF Mono', monospace; font-size: 10.5px; color: #34D399;")

        ollama_ok = snapshot.get("ollama_online", False)
        ollama_detail = snapshot.get("ollama_detail", "")
        if ollama_ok:
            self.ollama_label.setText("Ollama    ● Online")
            self.ollama_label.setStyleSheet("font-family: 'SF Mono', monospace; font-size: 10.5px; color: #34D399;")
        else:
            self.ollama_label.setText(f"Ollama    ● Offline ({ollama_detail or 'not running'})")
            self.ollama_label.setStyleSheet("font-family: 'SF Mono', monospace; font-size: 10.5px; color: #F87171;")

        model = snapshot.get("model", "unknown")
        self.model_label.setText(f"Model: {model}")
        systems = snapshot.get("systems", [])
        online = sum(1 for s in systems if s.get("state") in ("Online", "Configured"))
        self.subsystems_label.setText(
            f"{online}/{len(systems)} Systems Ready  •  {len(snapshot.get('tools', []))} Tools"
        )
