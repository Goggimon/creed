# gui/components/insignia.py

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget


def draw_creed_insignia(
    painter: QPainter,
    cx: float,
    cy: float,
    size: float,
    glow_intensity: float = 0.65,
    accent_color: str = "#6EA8FE",
):
    """Draw the geometric winged CREED insignia centered at (cx, cy) with dynamic state tint."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)

    s = size / 100.0
    primary = QColor(accent_color)
    secondary = primary.lighter(130)
    bottom = primary.darker(320)
    bright = QColor("#F0F6FA")

    edge_color = QColor(primary)
    edge_color.setAlpha(int(180 + 75 * min(1.0, glow_intensity)))
    pen = QPen(edge_color, max(1.3, 1.9 * s))
    pen.setJoinStyle(Qt.MiterJoin)

    grad = QLinearGradient(cx, cy - 45 * s, cx, cy + 48 * s)
    c_top = QColor(primary)
    c_top.setAlpha(int(195 + 60 * min(1.0, glow_intensity)))
    c_bot = QColor(bottom)
    c_bot.setAlpha(235)
    grad.setColorAt(0.0, c_top)
    grad.setColorAt(1.0, c_bot)

    center_blade = QPolygonF([
        QPointF(cx, cy - 42 * s),
        QPointF(cx + 10 * s, cy - 26 * s),
        QPointF(cx + 5 * s, cy + 42 * s),
        QPointF(cx, cy + 48 * s),
        QPointF(cx - 5 * s, cy + 42 * s),
        QPointF(cx - 10 * s, cy - 26 * s),
    ])

    left_inner = QPolygonF([
        QPointF(cx - 14 * s, cy - 24 * s),
        QPointF(cx - 34 * s, cy - 36 * s),
        QPointF(cx - 22 * s, cy - 8 * s),
        QPointF(cx - 10 * s, cy + 30 * s),
        QPointF(cx - 8 * s, cy + 8 * s),
    ])

    right_inner = QPolygonF([
        QPointF(cx + 14 * s, cy - 24 * s),
        QPointF(cx + 34 * s, cy - 36 * s),
        QPointF(cx + 22 * s, cy - 8 * s),
        QPointF(cx + 10 * s, cy + 30 * s),
        QPointF(cx + 8 * s, cy + 8 * s),
    ])

    left_outer = QPolygonF([
        QPointF(cx - 46 * s, cy - 42 * s),
        QPointF(cx - 24 * s, cy - 20 * s),
        QPointF(cx - 16 * s, cy + 16 * s),
        QPointF(cx - 32 * s, cy - 10 * s),
    ])

    right_outer = QPolygonF([
        QPointF(cx + 46 * s, cy - 42 * s),
        QPointF(cx + 24 * s, cy - 20 * s),
        QPointF(cx + 16 * s, cy + 16 * s),
        QPointF(cx + 32 * s, cy - 10 * s),
    ])

    painter.setPen(pen)
    painter.setBrush(grad)
    for poly in (left_outer, right_outer, left_inner, right_inner, center_blade):
        painter.drawPolygon(poly)

    highlight = QPen(QColor(bright.red(), bright.green(), bright.blue(), 165), max(1.0, 1.3 * s))
    painter.setPen(highlight)
    painter.drawLine(QPointF(cx, cy - 34 * s), QPointF(cx, cy + 32 * s))

    sec_pen = QPen(QColor(secondary.red(), secondary.green(), secondary.blue(), 130), max(0.9, 1.1 * s))
    painter.setPen(sec_pen)
    painter.drawLine(QPointF(cx - 40 * s, cy - 38 * s), QPointF(cx - 18 * s, cy - 14 * s))
    painter.drawLine(QPointF(cx + 40 * s, cy - 38 * s), QPointF(cx + 18 * s, cy - 14 * s))

    painter.restore()


class CreedInsigniaWidget(QWidget):
    def __init__(self, size: int = 64, accent_color: str = "#56D9E8", parent=None):
        super().__init__(parent)
        self._icon_size = size
        self._glow = 0.65
        self._accent = accent_color
        self.setFixedSize(size + 12, size + 12)

    def set_glow(self, value: float):
        self._glow = max(0.1, min(1.0, value))
        self.update()

    def set_accent(self, color: str):
        self._accent = color
        self.update()

    def paintEvent(self, event):
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
            draw_creed_insignia(
                painter,
                self.width() / 2.0,
                self.height() / 2.0,
                self._icon_size,
                self._glow,
                accent_color=self._accent,
            )
        finally:
            painter.end()
