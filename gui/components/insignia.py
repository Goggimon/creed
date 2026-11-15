# gui/components/insignia.py

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget


def draw_creed_insignia(
    painter: QPainter,
    cx: float,
    cy: float,
    size: float,
    glow_intensity: float = 0.5,
):
    """Draw the geometric winged CREED insignia centered at (cx, cy)."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)

    s = size / 100.0
    cyan = QColor("#56D9E8")
    ice = QColor("#8BAFBE")
    bright = QColor("#E6EDF2")

    edge_color = QColor(cyan)
    edge_color.setAlpha(int(160 + 95 * min(1.0, glow_intensity)))
    pen = QPen(edge_color, max(1.2, 1.8 * s))
    pen.setJoinStyle(Qt.MiterJoin)

    grad = QLinearGradient(cx, cy - 45 * s, cx, cy + 48 * s)
    c_top = QColor("#56D9E8")
    c_top.setAlpha(int(170 + 70 * glow_intensity))
    c_bot = QColor("#152936")
    c_bot.setAlpha(220)
    grad.setColorAt(0.0, c_top)
    grad.setColorAt(1.0, c_bot)

    # Center spear / core blade
    center_blade = QPolygonF([
        QPointF(cx, cy - 42 * s),
        QPointF(cx + 10 * s, cy - 26 * s),
        QPointF(cx + 5 * s, cy + 42 * s),
        QPointF(cx, cy + 48 * s),
        QPointF(cx - 5 * s, cy + 42 * s),
        QPointF(cx - 10 * s, cy - 26 * s),
    ])

    # Left inner wing
    left_inner = QPolygonF([
        QPointF(cx - 14 * s, cy - 24 * s),
        QPointF(cx - 34 * s, cy - 36 * s),
        QPointF(cx - 22 * s, cy - 8 * s),
        QPointF(cx - 10 * s, cy + 30 * s),
        QPointF(cx - 8 * s, cy + 8 * s),
    ])

    # Right inner wing
    right_inner = QPolygonF([
        QPointF(cx + 14 * s, cy - 24 * s),
        QPointF(cx + 34 * s, cy - 36 * s),
        QPointF(cx + 22 * s, cy - 8 * s),
        QPointF(cx + 10 * s, cy + 30 * s),
        QPointF(cx + 8 * s, cy + 8 * s),
    ])

    # Left outer fin
    left_outer = QPolygonF([
        QPointF(cx - 46 * s, cy - 42 * s),
        QPointF(cx - 24 * s, cy - 20 * s),
        QPointF(cx - 16 * s, cy + 16 * s),
        QPointF(cx - 32 * s, cy - 10 * s),
    ])

    # Right outer fin
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

    # Subtle inner highlight line on center core
    highlight = QPen(QColor(bright.red(), bright.green(), bright.blue(), 140), max(1.0, 1.2 * s))
    painter.setPen(highlight)
    painter.drawLine(QPointF(cx, cy - 34 * s), QPointF(cx, cy + 32 * s))

    # Faint side chevron accents
    ice_pen = QPen(QColor(ice.red(), ice.green(), ice.blue(), 110), max(0.8, 1.0 * s))
    painter.setPen(ice_pen)
    painter.drawLine(QPointF(cx - 40 * s, cy - 38 * s), QPointF(cx - 18 * s, cy - 14 * s))
    painter.drawLine(QPointF(cx + 40 * s, cy - 38 * s), QPointF(cx + 18 * s, cy - 14 * s))

    painter.restore()


class CreedInsigniaWidget(QWidget):
    def __init__(self, size: int = 64, parent=None):
        super().__init__(parent)
        self._icon_size = size
        self._glow = 0.5
        self.setFixedSize(size + 12, size + 12)

    def set_glow(self, value: float):
        self._glow = max(0.1, min(1.0, value))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        draw_creed_insignia(
            painter, self.width() / 2.0, self.height() / 2.0, self._icon_size, self._glow
        )
