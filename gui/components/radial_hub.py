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
    hover_anim: float = 0.0
    rect: QRectF = field(default_factory=QRectF)


class RadialHubWidget(QWidget):
    """Calm 60 FPS native QPainter 3D-projected hub with all 9 subsystem nodes."""

    node_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(620, 440)

        self._raw_state = "Idle"
        self._core_state = "Online"
        self._accent = QColor(STATE_COLORS["Idle"])
        self._display_accent = QColor(STATE_COLORS["Idle"])
        self._yaw = 0.0
        self._pitch = 0.18
        self._idle_phase = 0.0
        self._orbit_angle = 0.0
        self._pulse_phase = 0.0
        self._hovered_key = None

        # 3D Fibonacci neural sphere
        self._sphere_nodes = []
        n_nodes = 40
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
                if d2 < 0.38:
                    self._sphere_edges.append((i, j))

        self._ring_specs = [
            {"tilt_x": 0.48, "tilt_z": 0.25, "r": 0.84},
            {"tilt_x": -0.58, "tilt_z": 0.52, "r": 1.02},
        ]

        rng = random.Random(7)
        self._particles = [
            {
                "angle": rng.uniform(0, 2 * math.pi),
                "dist": rng.uniform(0.45, 1.25),
                "speed": rng.uniform(0.002, 0.005) * (1 if i % 2 == 0 else -1),
                "size": rng.uniform(1.2, 2.2),
                "alpha": rng.randint(45, 115),
            }
            for i in range(24)
        ]

        # 9 evenly spaced nodes matching MainWindow sidebar indices
        self.nodes = [
            HubNode("CONVERSATION", "Conversation", "Chat & Stream", 1, -90),
            HubNode("VSPOTIFY", "VSpotify", "Visualizer & Audio", 3, -50),
            HubNode("JEE", "JEE Tutor", "Reasoning & PYQs", 4, -10),
            HubNode("TOOLS", "Tools", "Actions & Files", 8, 30),
            HubNode("MODELS", "AI Models", "Local Ollama", 9, 70),
            HubNode("SETTINGS", "Settings", "Preferences", 10, 110),
            HubNode("AUTOMATION", "Automation", "Workflows", 6, 150),
            HubNode("VOICE", "Voice", "Speech & Wake", 5, 190),
            HubNode("MEMORY", "Memory", "Notes & Chats", 2, -135),
        ]

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_core_state(self, state: str):
        self._raw_state = state
        mapping = {
            "Idle": "Online",
            "Listening": "Listening",
            "Recording": "Recording",
            "Processing": "Thinking",
            "Speaking": "Speaking",
            "Retrying Connection": "Reconnecting",
            "Error": "Error",
        }
        self._core_state = mapping.get(state, state)
        self._accent = QColor(STATE_COLORS.get(state, "#6EA8FE"))
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
        mult = 2.1 if self._raw_state == "Processing" else (1.4 if active else 1.0)
        self._yaw = (self._yaw + 0.0065 * mult) % (2 * math.pi)
        self._idle_phase = (self._idle_phase + 0.032 * mult) % (2 * math.pi)
        self._orbit_angle = (self._orbit_angle + 0.35 * mult) % 360.0
        self._pulse_phase = (self._pulse_phase + 0.014 * mult) % 1.0

        r = self._display_accent.red() + (self._accent.red() - self._display_accent.red()) * 0.12
        g = self._display_accent.green() + (self._accent.green() - self._display_accent.green()) * 0.12
        b = self._display_accent.blue() + (self._accent.blue() - self._display_accent.blue()) * 0.12
        self._display_accent = QColor(int(r), int(g), int(b))

        for p in self._particles:
            p["angle"] = (p["angle"] + p["speed"] * mult) % (2 * math.pi)

        for n in self.nodes:
            if n.activity_heat > 0.0:
                n.activity_heat = max(0.0, n.activity_heat - 0.018)
            target_h = 1.0 if self._hovered_key == n.key else 0.0
            n.hover_anim += (target_h - n.hover_anim) * 0.22
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
        c = self._display_accent.lighter(lighten) if lighten != 100 else QColor(self._display_accent)
        c.setAlpha(max(0, min(255, alpha)))
        return c

    def paintEvent(self, event):
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
            painter.setRenderHint(QPainter.Antialiasing)

            w, h = self.width(), self.height()
            cx, cy = w / 2.0, h / 2.0
            scale = max(0.72, min(1.25, min(w / 780.0, h / 520.0)))
            sphere_r = 112.0 * scale
            active_pulse = self._raw_state in ("Processing", "Listening", "Recording", "Speaking")

            # 1. Soft Ambient Glow
            bg_grad = QRadialGradient(cx, cy, max(w, h) * 0.48)
            bg_grad.setColorAt(0.0, self._tint(52, 105))
            bg_grad.setColorAt(0.45, self._tint(14, 85))
            bg_grad.setColorAt(1.0, QColor(16, 17, 20, 0))
            painter.fillRect(0, 0, w, h, bg_grad)

            # 2. Subtle Ambient Particles
            painter.setPen(Qt.NoPen)
            for p in self._particles:
                px = cx + math.cos(p["angle"]) * p["dist"] * sphere_r * 1.4
                py = cy + math.sin(p["angle"]) * p["dist"] * sphere_r * 1.15
                painter.setBrush(self._tint(p["alpha"], 120))
                painter.drawEllipse(QPointF(px, py), p["size"], p["size"])

            # 3. 2 Clean Orbital Rings
            for idx, spec in enumerate(self._ring_specs):
                r_norm = spec["r"]
                tilt_x = spec["tilt_x"] + math.sin(self._idle_phase * 0.5 + idx) * 0.06
                tilt_z = spec["tilt_z"] + self._yaw * (0.55 if idx % 2 == 0 else -0.45)
                cos_tx, sin_tx = math.cos(tilt_x), math.sin(tilt_x)
                cos_tz, sin_tz = math.cos(tilt_z), math.sin(tilt_z)

                pts = []
                segs = 48
                for k in range(segs + 1):
                    a = (2 * math.pi * k) / segs
                    lx, ly, lz = math.cos(a) * r_norm, math.sin(a) * r_norm, 0.0
                    y1 = ly * cos_tx - lz * sin_tx
                    z1 = ly * sin_tx + lz * cos_tx
                    x2 = lx * cos_tz - y1 * sin_tz
                    y2 = lx * sin_tz + y1 * cos_tz
                    sx, sy, _ = self._project(x2, y2, z1, cx, cy, sphere_r)
                    pts.append(QPointF(sx, sy))

                painter.setPen(QPen(self._tint(65 if idx == 0 else 42, 115), 1.1))
                for k in range(segs):
                    painter.drawLine(pts[k], pts[k + 1])

            # 4. 3D-Projected Neural Sphere
            projected = [self._project(x, y, z, cx, cy, sphere_r) for (x, y, z) in self._sphere_nodes]

            for i, j in self._sphere_edges:
                x1, y1, z1 = projected[i]
                x2, y2, z2 = projected[j]
                depth = (z1 + z2) * 0.5
                alpha = int(max(18, min(110, 52 + depth * 42)))
                painter.setPen(QPen(self._tint(alpha, 115), 1.0))
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

            painter.setPen(Qt.NoPen)
            for sx, sy, rz in projected:
                alpha = int(max(65, min(215, 135 + rz * 70)))
                r_dot = 2.2 if rz > 0 else 1.4
                painter.setBrush(self._tint(alpha, 130))
                painter.drawEllipse(QPointF(sx, sy), r_dot, r_dot)

            # 5. Connected Module Nodes (9 evenly arranged around hub)
            rx = min(w * 0.39, 315 * scale)
            ry = min(h * 0.38, 205 * scale)
            node_w = 144 * scale
            node_h = 52 * scale

            for idx, node in enumerate(self.nodes):
                rad = math.radians(node.angle_deg)
                nx = cx + math.cos(rad) * rx
                ny = cy + math.sin(rad) * ry
                lift = node.hover_anim * 2.5
                node.rect = QRectF(nx - node_w / 2, ny - node_h / 2 - lift, node_w, node_h)

                heat = max(node.activity_heat, node.hover_anim * 0.85)
                start_r = sphere_r * 0.96
                sx = cx + math.cos(rad) * start_r
                sy = cy + math.sin(rad) * start_r
                ctrl_x = sx + (nx - sx) * 0.5

                path = QPainterPath()
                path.moveTo(sx, sy)
                path.cubicTo(ctrl_x, sy, ctrl_x, ny - lift, nx, ny - lift)

                line_alpha = int(38 + 150 * heat)
                painter.setPen(QPen(self._tint(line_alpha, 120), 1.35 if heat > 0.1 else 0.9))
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(path)

                if heat > 0.05 or active_pulse:
                    t = (self._pulse_phase + idx * 0.13) % 1.0
                    pt = path.pointAtPercent(t)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(self._tint(210 if heat > 0.1 else 100, 140))
                    painter.drawEllipse(pt, 2.3, 2.3)

            # 6. Central Core Emblem & State
            breath = 1.0 + 0.018 * math.sin(self._idle_phase)
            core_r = 56 * scale * breath
            painter.setBrush(QColor(19, 20, 24, 240))
            painter.setPen(QPen(self._tint(150, 120), 1.3))
            painter.drawEllipse(QPointF(cx, cy), core_r, core_r)

            glow_val = 0.92 if active_pulse else (0.58 + 0.12 * math.sin(self._idle_phase))
            draw_creed_insignia(
                painter,
                cx,
                cy - 9 * scale,
                42 * scale * breath,
                glow_val,
                accent_color=self._display_accent.name(),
            )

            painter.setPen(self._tint(230, 125))
            painter.setFont(QFont("SF Pro Text", max(8, int(8.5 * scale)), QFont.DemiBold))
            painter.drawText(
                QRectF(cx - 52 * scale, cy + 18 * scale, 104 * scale, 16 * scale),
                Qt.AlignCenter,
                f"● {self._core_state}",
            )

            # 7. Draw Clean Studio Cards
            for node in self.nodes:
                self._draw_node_card(painter, node, scale)
        finally:
            painter.end()

    def _draw_node_card(self, painter: QPainter, node: HubNode, scale: float):
        r = node.rect
        heat = max(node.activity_heat, node.hover_anim * 0.9)

        bg = QColor(
            int(24 + 8 * node.hover_anim),
            int(26 + 8 * node.hover_anim),
            int(32 + 10 * node.hover_anim),
            245,
        )
        border_c = QColor(255, 255, 255, int(18 + 26 * node.hover_anim))
        if heat > 0.15:
            border_c = self._tint(int(85 + 135 * heat), 115)

        painter.setBrush(bg)
        painter.setPen(QPen(border_c, 1.2 if heat > 0.15 else 1.0))
        painter.drawRoundedRect(r, 10.0 * scale, 10.0 * scale)

        painter.setPen(QColor("#F3F4F6"))
        t_font = QFont("SF Pro Text", max(9, int(9.5 * scale)), QFont.DemiBold)
        painter.setFont(t_font)
        painter.drawText(
            QRectF(r.left() + 13, r.top() + 6, r.width() - 20, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            node.title,
        )

        painter.setPen(QColor("#9CA3AF") if heat < 0.2 else self._tint(230, 125))
        painter.setFont(QFont("SF Pro Text", max(8, int(8 * scale))))
        painter.drawText(
            QRectF(r.left() + 13, r.top() + 25, r.width() - 20, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            node.subtitle,
        )
