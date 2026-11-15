import math
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


from components.status_bar import STATE_COLORS


class VoiceIndicator(QWidget):
    """Real-activity circular audio visualizer for CREED's voice pipeline."""

    STATE_COLORS = STATE_COLORS

    def __init__(self, diameter: int = 160):
        super().__init__()
        self._diameter = diameter
        self.setMinimumSize(diameter + 40, diameter + 56)
        self._state = "Idle"
        self._audio_level = 0.0
        self._phase = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setAlignment(Qt.AlignBottom | Qt.AlignHCenter)

        self.label = QLabel("IDLE")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

        self._timer = QTimer(self)
        self._timer.setInterval(45)
        self._timer.timeout.connect(self._tick)

    def set_status(self, state: str):
        self._state = state
        self.label.setText(state.upper())
        if state in ("Listening", "Recording", "Processing", "Speaking"):
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self._audio_level = 0.0
            self._phase = 0.0
        self.update()

    def set_audio_level(self, level: float):
        # Smoothly tracks real RMS microphone amplitude when active
        self._audio_level = max(0.0, min(1.0, level))
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.12) % (2 * math.pi)
        if self._state not in ("Listening", "Recording"):
            self._audio_level = 0.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        color = QColor(self.STATE_COLORS.get(self._state, "#65727F"))
        cx = self.width() / 2.0
        cy = (self.height() - 24) / 2.0
        base_r = self._diameter * 0.28

        # Subtle outer orbital guide
        guide_pen = QPen(QColor(86, 217, 232, 35), 1.0)
        painter.setPen(guide_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(int(cx - base_r * 1.45), int(cy - base_r * 1.45), int(base_r * 2.9), int(base_r * 2.9))

        # Active energy ring (driven by real RMS audio level for Listening/Recording)
        if self._state in ("Listening", "Recording"):
            dynamic_r = base_r + (self._audio_level * base_r * 0.7)
        elif self._state in ("Processing", "Speaking"):
            dynamic_r = base_r + (0.15 + 0.1 * math.sin(self._phase)) * base_r
        else:
            dynamic_r = base_r

        ring_color = QColor(color)
        ring_color.setAlpha(150)
        painter.setPen(QPen(ring_color, 2.0))
        painter.drawEllipse(
            int(cx - dynamic_r),
            int(cy - dynamic_r),
            int(dynamic_r * 2),
            int(dynamic_r * 2),
        )

        # Core dot
        painter.setPen(Qt.NoPen)
        core_color = QColor(color)
        core_color.setAlpha(210)
        painter.setBrush(core_color)
        core_r = base_r * 0.45
        painter.drawEllipse(
            int(cx - core_r),
            int(cy - core_r),
            int(core_r * 2),
            int(core_r * 2),
        )
