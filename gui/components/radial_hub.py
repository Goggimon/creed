# gui/components/radial_hub.py

import math
import random
from dataclasses import dataclass, field
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget
from components.insignia import draw_creed_insignia
from components.status_bar import STATE_COLORS


@dataclass
class HubNode:
    key: str
    title: str
    subtitle: str
    tab_index: int
    angle_deg: float
    status: str = "ACTIVE"
    activity_heat: float = 0.0
    rect: QRectF = field(default_factory=QRectF)


class RadialHubWidget(QWidget):
    """High-clarity 60 FPS native QPainter 3D-projected holographic core with dynamic state colors."""

    node_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(620, 440)

        self._raw_state = "Idle"
        self._core_state = "ONLINE"
        self._accent = QColor(STATE_COLORS["Idle"])
        self._yaw = 0.0
        self._pitch = 0.18
        self._idle_phase = 0.0
        self._vis_phase = 0.0
        self._orbit_angle = 0.0
        self._pulse_phase = 0.0
        self._hovered_key = None

        # Precompute 3D Fibonacci neural sphere nodes & edges
        self._sphere_nodes = []
        n_nodes = 48
        golden_angle = math.pi * (3.0 - math.sqrt(5.0))
        for i in range(n_nodes):
            y = 1.0 - (i / (n_nodes - 1)) * 2.0
            r = math.sqrt(max(0.0, 1.0 - y * y))
            theta = golden_angle * i
            self._sphere_nodes.append((math.cos(theta) * r, y, math.sin(theta) * r))

        self._sphere_edges = []
        for i in range(n_nodes):
            x1, y1, z1 = self._sphere_nodes[i]
            for j in range(i + 1, n_nodes):
                x2, y2, z2 = self._sphere_nodes[j]
                d2 = (x1 - x2) ** 2 + (y1 - y2) ** 2 + (z1 - z2) ** 2
                if d2 < 0.34:
                    self._sphere_edges.append((i, j))

        self._ring_specs = [
            {"tilt_x": 0.48, "tilt_z": 0.25, "r": 0.78},
            {"tilt_x": -0.62, "tilt_z": 0.55, "r": 0.90},
            {"tilt_x": 0.95, "tilt_z": -0.35, "r": 1.02},
            {"tilt_x": -0.25, "tilt_z": -0.82, "r": 1.12},
        ]

        rng = random.Random(7)
        self._particles = [
            {
                "angle": rng.uniform(0, 2 * math.pi),
                "dist": rng.uniform(0.35, 1.25),
                "speed": rng.uniform(0.003, 0.008) * (1 if i % 2 == 0 else -1),
                "size": rng.uniform(1.3, 2.6),
                "alpha": rng.randint(80, 185),
            }
            for i in range(40)
        ]

        self.nodes = [
            HubNode("CONVERSATION", "CONVERSATION", "Chat • Stream", 1, -90, "ACTIVE"),
            HubNode("SYSTEMS", "SYSTEMS", "Mac • BT • ADB", 3, -30, "ACTIVE"),
            HubNode("TOOLS", "TOOLS", "Execute • API", 4, 20, "ACTIVE"),
            HubNode("SETTINGS", "SETTINGS", "Config • Env", 7, 65, "ACTIVE"),
            HubNode("AUTOMATION", "AUTOMATION", "Workflows", 6, 125, "ACTIVE"),
            HubNode("VOICE", "VOICE", "STT • TTS", 5, 180, "STANDBY"),
            HubNode("MEMORY", "MEMORY", "SQLite • Chats", 2, -145, "ACTIVE"),
        ]

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_core_state(self, state: str):
        self._raw_state = state
        mapping = {
            "Idle": "ONLINE",
            "Listening": "LISTENING",
            "Recording": "RECORDING",
            "Processing": "PROCESSING",
            "Speaking": "SPEAKING",
            "Retrying Connection": "RETRYING",
            "Error": "ERROR",
        }
        self._core_state = mapping.get(state, state.upper())
        self._accent = QColor(STATE_COLORS.get(state, "#56D9E8"))
        if state in ("Listening", "Recording", "Speaking"):
            self.pulse_node("VOICE")
        elif state == "Processing":
            self.pulse_node("CONVERSATION")
        self.update()

    def pulse_node(self, key: str):
        for n in self.nodes:
            if n.key == key.upper():
                n.activity_heat = 1.0
        self.update()

    def _tick(self):
        active = self._raw_state in ("Processing", "Speaking", "Recording", "Listening")
        mult = 2.4 if self._raw_state == "Processing" else (1.55 if active else 1.0)
        self._yaw = (self._yaw + 0.008 * mult) % (2 * math.pi)
        self._idle_phase = (self._idle_phase + 0.04 * mult) % (2 * math.pi)
        self._vis_phase = (self._vis_phase + 0.09 * mult) % (2 * math.pi)
        self._orbit_angle = (self._orbit_angle + 0.45 * mult) % 360.0
        self._pulse_phase = (self._pulse_phase + 0.016 * mult) % 1.0

        for p in self._particles:
            p["angle"] = (p["angle"] + p["speed"] * mult) % (2 * math.pi)

        for n in self.nodes:
            if n.activity_heat > 0.0:
                n.activity_heat = max(0.0, n.activity_heat - 0.02)
        self.update()

    def mouseMoveEvent(self, event):
        pos = event.position()
        hovered = None
        for n in self.nodes:
            if n.rect.contains(pos):
                hovered = n.key
                break
        if hovered != self._hovered_key:
            self._hovered_key = hovered
            self.setCursor(Qt.PointingHandCursor if hovered else Qt.ArrowCursor)
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position()
            for n in self.nodes:
                if n.rect.contains(pos):
                    self.node_clicked.emit(n.tab_index)
                    return

    def _project(self, x: float, y: float, z: float, cx: float, cy: float, radius: float):
        cos_y, sin_y = math.cos(self._yaw), math.sin(self._yaw)
        cos_p, sin_p = math.cos(self._pitch), math.sin(self._pitch)

        rx = x * cos_y + z * sin_y
        rz = -x * sin_y + z * cos_y
        ry = y * cos_p - rz * sin_p
        rz2 = y * sin_p + rz * cos_p

        perspective = 2.8 / (2.8 - rz2 * 0.65)
        sx = cx + rx * radius * perspective
        sy = cy + ry * radius * perspective
        return sx, sy, rz2

    def _tint(self, alpha: int, lighten: int = 100) -> QColor:
        c = self._accent.lighter(lighten) if lighten != 100 else QColor(self._accent)
        c.setAlpha(max(0, min(255, alpha)))
        return c

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        scale = max(0.72, min(1.28, min(w / 760.0, h / 500.0)))
        sphere_r = 126.0 * scale
        active_pulse = self._raw_state in ("Processing", "Listening", "Recording", "Speaking")

        # 1. Brighter Radial Atmospheric Glow matching active status color
        bg_grad = QRadialGradient(cx, cy, max(w, h) * 0.56)
        bg_grad.setColorAt(0.0, self._tint(115, 110))
        bg_grad.setColorAt(0.35, self._tint(45, 70))
        bg_grad.setColorAt(1.0, QColor(8, 11, 15, 0))
        painter.fillRect(0, 0, w, h, bg_grad)

        # Swiss Micro-Grid & Crosshairs
        step = 36
        painter.setPen(QPen(self._tint(18), 1.0))
        for x in range(int(cx % step), w, step):
            painter.drawLine(x, 0, x, h)
        for y in range(int(cy % step), h, step):
            painter.drawLine(0, y, w, y)

        painter.setPen(QPen(self._tint(36), 1.0))
        painter.drawLine(QPointF(16, cy), QPointF(w - 16, cy))
        painter.drawLine(QPointF(cx, 16), QPointF(cx, h - 16))

        # Corner HUD reticle brackets
        bracket_len = 18
        margin = 10
        painter.setPen(QPen(self._tint(115), 1.5))
        for bx, by, dx, dy in (
            (margin, margin, 1, 1),
            (w - margin, margin, -1, 1),
            (margin, h - margin, 1, -1),
            (w - margin, h - margin, -1, -1),
        ):
            painter.drawLine(bx, by, bx + dx * bracket_len, by)
            painter.drawLine(bx, by, bx, by + dy * bracket_len)

        # 2. Floating Bokeh Particles
        painter.setPen(Qt.NoPen)
        for p in self._particles:
            px = cx + math.cos(p["angle"]) * p["dist"] * sphere_r * 1.45
            py = cy + math.sin(p["angle"]) * p["dist"] * sphere_r * 1.15
            painter.setBrush(self._tint(p["alpha"], 130))
            painter.drawEllipse(QPointF(px, py), p["size"], p["size"])

        # 3. Segmented Rotating HUD Arcs & Degree Ticks
        arc1_r = 108 * scale
        painter.setPen(QPen(self._tint(160, 120), 1.8))
        for start in (0, 120, 240):
            painter.drawArc(
                QRectF(cx - arc1_r, cy - arc1_r, arc1_r * 2, arc1_r * 2),
                int((start + self._orbit_angle) * 16),
                52 * 16,
            )

        tick_r = 166 * scale
        painter.setPen(QPen(self._tint(75), 1.0))
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inner = tick_r - (7 if deg % 30 == 0 else 3)
            painter.drawLine(
                QPointF(cx + math.cos(rad) * inner, cy + math.sin(rad) * inner),
                QPointF(cx + math.cos(rad) * tick_r, cy + math.sin(rad) * tick_r),
            )

        # 4. 3D-Projected Orbital Rings
        for idx, spec in enumerate(self._ring_specs):
            r_norm = spec["r"]
            tilt_x = spec["tilt_x"] + math.sin(self._idle_phase * 0.5 + idx) * 0.08
            tilt_z = spec["tilt_z"] + self._yaw * (0.6 if idx % 2 == 0 else -0.5)
            cos_tx, sin_tx = math.cos(tilt_x), math.sin(tilt_x)
            cos_tz, sin_tz = math.cos(tilt_z), math.sin(tilt_z)

            pts = []
            segs = 44
            for k in range(segs + 1):
                a = (2 * math.pi * k) / segs
                lx, ly, lz = math.cos(a) * r_norm, math.sin(a) * r_norm, 0.0
                y1 = ly * cos_tx - lz * sin_tx
                z1 = ly * sin_tx + lz * cos_tx
                x2 = lx * cos_tz - y1 * sin_tz
                y2 = lx * sin_tz + y1 * cos_tz
                sx, sy, _ = self._project(x2, y2, z1, cx, cy, sphere_r)
                pts.append(QPointF(sx, sy))

            ring_alpha = 115 if idx % 2 == 0 else 78
            painter.setPen(QPen(self._tint(ring_alpha, 115), 1.25))
            for k in range(segs):
                painter.drawLine(pts[k], pts[k + 1])

        # 5. 3D-Projected Neural Sphere (Nodes + Circuit Edges + Radial Beams)
        projected = [self._project(x, y, z, cx, cy, sphere_r) for (x, y, z) in self._sphere_nodes]

        beam_alpha = 68 if active_pulse else 34
        painter.setPen(QPen(self._tint(beam_alpha, 120), 1.0))
        for sx, sy, rz in projected[::2]:
            if rz > -0.45:
                ix = cx + (sx - cx) * 0.36
                iy = cy + (sy - cy) * 0.36
                painter.drawLine(QPointF(sx, sy), QPointF(ix, iy))

        for i, j in self._sphere_edges:
            x1, y1, z1 = projected[i]
            x2, y2, z2 = projected[j]
            depth = (z1 + z2) * 0.5
            alpha = int(max(28, min(145, 78 + depth * 55)))
            painter.setPen(QPen(self._tint(alpha, 115), 1.15))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        painter.setPen(Qt.NoPen)
        for sx, sy, rz in projected:
            alpha = int(max(85, min(245, 165 + rz * 80)))
            r_dot = 2.6 if rz > 0 else 1.7
            painter.setBrush(self._tint(alpha, 145))
            painter.drawEllipse(QPointF(sx, sy), r_dot, r_dot)

        # 6. 56-Bar Radial Spectrum Visualizer Around Central Core Ring
        bars = 56
        vis_r = 66 * scale
        for i in range(bars):
            theta = (2 * math.pi * i) / bars
            wave = (
                0.55 * math.sin(self._vis_phase * 2.0 + i * 0.35)
                + 0.45 * math.cos(self._vis_phase * 1.3 - i * 0.22)
            )
            mag = (6.0 + 14.0 * abs(wave)) if active_pulse else (3.5 + 6.5 * abs(wave))
            mag *= scale
            x1 = cx + math.cos(theta) * vis_r
            y1 = cy + math.sin(theta) * vis_r
            x2 = cx + math.cos(theta) * (vis_r + mag)
            y2 = cy + math.sin(theta) * (vis_r + mag)
            alpha = int(175 + 75 * abs(wave)) if active_pulse else int(110 + 65 * abs(wave))
            painter.setPen(QPen(self._tint(alpha, 125), 1.7))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # 7. Connected Module Nodes & Pathways
        rx = min(w * 0.38, 305 * scale)
        ry = min(h * 0.37, 195 * scale)
        node_w = 152 * scale
        node_h = 58 * scale

        for idx, node in enumerate(self.nodes):
            rad = math.radians(node.angle_deg)
            nx = cx + math.cos(rad) * rx
            ny = cy + math.sin(rad) * ry
            node.rect = QRectF(nx - node_w / 2, ny - node_h / 2, node_w, node_h)

            is_hot = node.activity_heat > 0.05 or self._hovered_key == node.key
            heat = max(node.activity_heat, 0.85 if self._hovered_key == node.key else 0.0)

            start_r = sphere_r * 0.96
            sx = cx + math.cos(rad) * start_r
            sy = cy + math.sin(rad) * start_r
            mid_x = sx + (nx - sx) * 0.45

            path = QPainterPath()
            path.moveTo(sx, sy)
            path.lineTo(mid_x, sy)
            path.lineTo(mid_x, ny)
            path.lineTo(nx, ny)

            line_alpha = int(75 + 170 * heat)
            painter.setPen(QPen(self._tint(line_alpha, 120), 1.6 if is_hot else 1.1))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

            if is_hot or self._raw_state != "Error":
                t = (self._pulse_phase + idx * 0.17) % 1.0
                pt = path.pointAtPercent(t)
                painter.setPen(Qt.NoPen)
                painter.setBrush(self._tint(240 if is_hot else 145, 145))
                painter.drawEllipse(pt, 2.7 if is_hot else 1.9, 2.7 if is_hot else 1.9)

        # 8. Stationary Front-Facing CREED Symbol & Core Status Label
        breath = 1.0 + 0.022 * math.sin(self._idle_phase)
        core_r = 62 * scale * breath
        painter.setBrush(QColor(10, 14, 19, 232))
        painter.setPen(QPen(self._tint(210, 120), 1.8))
        painter.drawEllipse(QPointF(cx, cy), core_r, core_r)

        glow_val = 0.95 if active_pulse else (0.65 + 0.15 * math.sin(self._idle_phase))
        draw_creed_insignia(
            painter,
            cx,
            cy - 10 * scale,
            46 * scale * breath,
            glow_val,
            accent_color=self._accent.name(),
        )

        painter.setPen(self._tint(245, 130))
        painter.setFont(QFont("SF Mono", max(7, int(7.5 * scale)), QFont.Bold))
        painter.drawText(
            QRectF(cx - 56 * scale, cy + 20 * scale, 112 * scale, 16 * scale),
            Qt.AlignCenter,
            f"● {self._core_state}",
        )

        # 9. Draw Module Cards
        for node in self.nodes:
            self._draw_node_card(painter, node, scale)

    def _draw_node_card(self, painter: QPainter, node: HubNode, scale: float):
        r = node.rect
        is_hovered = self._hovered_key == node.key
        heat = max(node.activity_heat, 0.8 if is_hovered else 0.0)

        cut = 8.0 * scale
        poly = QPainterPath()
        poly.moveTo(r.left() + cut, r.top())
        poly.lineTo(r.right(), r.top())
        poly.lineTo(r.right(), r.bottom() - cut)
        poly.lineTo(r.right() - cut, r.bottom())
        poly.lineTo(r.left(), r.bottom())
        poly.lineTo(r.left(), r.top() + cut)
        poly.closeSubpath()

        bg = QColor(20, 27, 36, 242) if is_hovered else QColor(13, 18, 24, 232)
        border_alpha = int(95 + 155 * heat)
        painter.setBrush(bg)
        painter.setPen(QPen(self._tint(border_alpha, 115), 1.4 if is_hovered else 1.0))
        painter.drawPath(poly)

        painter.setPen(QColor("#F2F7FA"))
        t_font = QFont("SF Pro Display", max(9, int(9.5 * scale)), QFont.DemiBold)
        t_font.setLetterSpacing(QFont.AbsoluteSpacing, 0.8)
        painter.setFont(t_font)
        painter.drawText(
            QRectF(r.left() + 12, r.top() + 7, r.width() - 20, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            node.title,
        )

        painter.setPen(self._tint(220, 125))
        painter.setFont(QFont("SF Mono", max(8, int(8 * scale))))
        painter.drawText(
            QRectF(r.left() + 12, r.top() + 27, r.width() - 20, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            f"● {node.subtitle}",
        )
