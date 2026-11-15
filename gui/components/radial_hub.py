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
    """JARVIS/FRIDAY-inspired holographic CREED nucleus with radial visualizer and orbiting projectiles."""

    node_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(620, 440)

        self._core_state = "ONLINE"
        self._idle_phase = 0.0
        self._particle_phase = 0.0
        self._orbit_angle = 0.0
        self._vis_phase = 0.0
        self._hovered_key = None

        # Deterministic ambient holographic dust particles
        rng = random.Random(42)
        self._ambient_dots = [
            {
                "angle": rng.uniform(0, 2 * math.pi),
                "dist": rng.uniform(0.22, 0.92),
                "speed": rng.uniform(0.002, 0.007) * (1 if i % 2 == 0 else -1),
                "size": rng.uniform(1.1, 2.5),
                "alpha": rng.randint(55, 165),
            }
            for i in range(44)
        ]

        # 3D-inclined orbital rings with fast-moving projectiles
        self._projectiles = [
            {"tilt_deg": 24, "rot_deg": -18, "rx": 128, "ry": 46, "phase": 0.0, "speed": 0.042, "color": "#56D9E8"},
            {"tilt_deg": -28, "rot_deg": 26, "rx": 134, "ry": 50, "phase": 2.1, "speed": -0.036, "color": "#E6EDF2"},
            {"tilt_deg": 8, "rot_deg": 62, "rx": 118, "ry": 40, "phase": 4.2, "speed": 0.052, "color": "#56D9E8"},
            {"tilt_deg": -12, "rot_deg": -58, "rx": 142, "ry": 54, "phase": 1.3, "speed": -0.029, "color": "#8BAFBE"},
        ]

        self.nodes = [
            HubNode("CONVERSATION", "CONVERSATION", "Chat • Stream • Ask", 1, -90, "ACTIVE"),
            HubNode("SYSTEMS", "SYSTEMS", "Mac • BT • ADB", 3, -30, "ACTIVE"),
            HubNode("TOOLS", "TOOLS", "Execute • Integrate", 4, 20, "ACTIVE"),
            HubNode("SETTINGS", "SETTINGS", "Configure • Env", 7, 65, "ACTIVE"),
            HubNode("AUTOMATION", "AUTOMATION", "Workflows • Tasks", 6, 125, "ACTIVE"),
            HubNode("VOICE", "VOICE", "STT • TTS • Wake", 5, 180, "STANDBY"),
            HubNode("MEMORY", "MEMORY", "SQLite • Chats", 2, -145, "ACTIVE"),
        ]

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_core_state(self, state: str):
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
        if state in ("Listening", "Recording", "Speaking"):
            self.pulse_node("VOICE")
        elif state == "Processing":
            self.pulse_node("CONVERSATION")
        self.update()

    def update_node_status(self, key: str, status: str):
        for n in self.nodes:
            if n.key == key:
                n.status = status
                break
        self.update()

    def pulse_node(self, key: str):
        for n in self.nodes:
            if n.key == key.upper():
                n.activity_heat = 1.0
        self.update()

    def _tick(self):
        active = self._core_state in ("PROCESSING", "SPEAKING", "RECORDING", "LISTENING")
        self._idle_phase = (self._idle_phase + (0.07 if active else 0.032)) % (2 * math.pi)
        self._vis_phase = (self._vis_phase + (0.14 if active else 0.055)) % (2 * math.pi)
        self._particle_phase = (self._particle_phase + (0.022 if active else 0.012)) % 1.0
        self._orbit_angle = (self._orbit_angle + (0.95 if active else 0.25)) % 360.0

        mult = 1.65 if active else 1.0
        for p in self._projectiles:
            p["phase"] = (p["phase"] + p["speed"] * mult) % (2 * math.pi)

        for d in self._ambient_dots:
            d["angle"] = (d["angle"] + d["speed"] * mult) % (2 * math.pi)

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

    def _draw_tech_background(self, painter: QPainter, w: int, h: int, cx: float, cy: float, scale: float):
        # Deep holographic atmospheric gradient
        bg_grad = QRadialGradient(cx, cy, max(w, h) * 0.62)
        bg_grad.setColorAt(0.0, QColor(20, 56, 70, 125))
        bg_grad.setColorAt(0.42, QColor(11, 24, 34, 80))
        bg_grad.setColorAt(1.0, QColor(8, 11, 15, 0))
        painter.fillRect(0, 0, w, h, bg_grad)

        # Fine Swiss architectural grid
        step = 34
        painter.setPen(QPen(QColor(86, 217, 232, 13), 1.0))
        for x in range(int(cx % step), w, step):
            painter.drawLine(x, 0, x, h)
        for y in range(int(cy % step), h, step):
            painter.drawLine(0, y, w, y)

        # Primary crosshairs
        painter.setPen(QPen(QColor(86, 217, 232, 26), 1.0))
        painter.drawLine(QPointF(16, cy), QPointF(w - 16, cy))
        painter.drawLine(QPointF(cx, 16), QPointF(cx, h - 16))

        # Floating ambient holographic dots
        max_r = min(w, h) * 0.48
        painter.setPen(Qt.NoPen)
        for d in self._ambient_dots:
            px = cx + math.cos(d["angle"]) * d["dist"] * max_r
            py = cy + math.sin(d["angle"]) * d["dist"] * max_r * 0.78
            painter.setBrush(QColor(86, 217, 232, d["alpha"]))
            painter.drawEllipse(QPointF(px, py), d["size"], d["size"])

        # Corner HUD reticle brackets
        bracket_len = 20
        margin = 10
        painter.setPen(QPen(QColor(86, 217, 232, 85), 1.4))
        for bx, by, dx, dy in (
            (margin, margin, 1, 1),
            (w - margin, margin, -1, 1),
            (margin, h - margin, 1, -1),
            (w - margin, h - margin, -1, -1),
        ):
            painter.drawLine(bx, by, bx + dx * bracket_len, by)
            painter.drawLine(bx, by, bx, by + dy * bracket_len)

        # Degree tick marks around outer ring
        tick_r = 218 * scale
        painter.setPen(QPen(QColor(86, 217, 232, 48), 1.0))
        for deg in range(0, 360, 8):
            rad = math.radians(deg)
            inner = tick_r - (8 if deg % 24 == 0 else 3)
            painter.drawLine(
                QPointF(cx + math.cos(rad) * inner, cy + math.sin(rad) * inner),
                QPointF(cx + math.cos(rad) * tick_r, cy + math.sin(rad) * tick_r),
            )

    def _draw_nucleus_visualizer(self, painter: QPainter, cx: float, cy: float, scale: float):
        active = self._core_state in ("PROCESSING", "SPEAKING", "RECORDING", "LISTENING")

        # 1. Circular 64-bar radial music/voice visualizer around the core
        bars = 64
        base_r = 95 * scale
        for i in range(bars):
            theta = (2 * math.pi * i) / bars
            wave = (
                0.55 * math.sin(self._vis_phase * 2.0 + i * 0.35)
                + 0.45 * math.cos(self._vis_phase * 1.3 - i * 0.22)
            )
            mag = (8.0 + 18.0 * abs(wave)) if active else (4.0 + 7.5 * abs(wave))
            mag *= scale

            x1 = cx + math.cos(theta) * base_r
            y1 = cy + math.sin(theta) * base_r
            x2 = cx + math.cos(theta) * (base_r + mag)
            y2 = cy + math.sin(theta) * (base_r + mag)

            alpha = int(165 + 80 * abs(wave)) if active else int(75 + 60 * abs(wave))
            pen_w = 2.0 if i % 2 == 0 else 1.2
            painter.setPen(QPen(QColor(86, 217, 232, alpha), pen_w))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # 2. 3D-projected inclined elliptical orbits + revolving projectiles with comet trails
        for p in self._projectiles:
            rx = p["rx"] * scale
            ry = p["ry"] * scale
            rot = math.radians(p["rot_deg"])
            cos_r, sin_r = math.cos(rot), math.sin(rot)

            # Faint orbital ellipse path
            painter.save()
            painter.translate(cx, cy)
            painter.rotate(p["rot_deg"])
            painter.setPen(QPen(QColor(86, 217, 232, 34), 1.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(0, 0), rx, ry)
            painter.restore()

            # Comet trail (7 trailing dots)
            base_c = QColor(p["color"])
            for tail in range(7, 0, -1):
                t_angle = p["phase"] - (0.09 * tail if p["speed"] > 0 else -0.09 * tail)
                lx = math.cos(t_angle) * rx
                ly = math.sin(t_angle) * ry
                px = cx + lx * cos_r - ly * sin_r
                py = cy + lx * sin_r + ly * cos_r
                c = QColor(base_c)
                c.setAlpha(int(180 * (1.0 - tail / 8.0)))
                painter.setPen(Qt.NoPen)
                painter.setBrush(c)
                r_dot = max(1.0, 2.8 * (1.0 - tail / 9.0))
                painter.drawEllipse(QPointF(px, py), r_dot, r_dot)

            # Projectile head
            lx = math.cos(p["phase"]) * rx
            ly = math.sin(p["phase"]) * ry
            hx = cx + lx * cos_r - ly * sin_r
            hy = cy + lx * sin_r + ly * cos_r
            glow_c = QColor(base_c)
            glow_c.setAlpha(90)
            painter.setBrush(glow_c)
            painter.drawEllipse(QPointF(hx, hy), 6.2, 6.2)
            painter.setBrush(base_c)
            painter.drawEllipse(QPointF(hx, hy), 3.0, 3.0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        cx = w / 2.0
        cy = h / 2.0
        scale = max(0.7, min(1.3, min(w / 760.0, h / 500.0)))

        # 1. Tech HUD Background + Ambient Holographic Particles
        self._draw_tech_background(painter, w, h, cx, cy, scale)

        # 2. Concentric orbital rings & counter-rotating segmented arcs
        for r, alpha in ((128 * scale, 55), (176 * scale, 32), (242 * scale, 18)):
            ring_pen = QPen(QColor(86, 217, 232, alpha), 1.0)
            if r > 200 * scale:
                ring_pen.setStyle(Qt.DashLine)
            painter.setPen(ring_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), r, r)

        arc1_r = 114 * scale
        arc1_rect = QRectF(cx - arc1_r, cy - arc1_r, arc1_r * 2, arc1_r * 2)
        painter.setPen(QPen(QColor(86, 217, 232, 135), 1.8))
        for start in (0, 120, 240):
            painter.drawArc(arc1_rect, int((start + self._orbit_angle) * 16), 52 * 16)

        arc2_r = 136 * scale
        arc2_rect = QRectF(cx - arc2_r, cy - arc2_r, arc2_r * 2, arc2_r * 2)
        painter.setPen(QPen(QColor(139, 175, 190, 85), 1.2))
        for start in (45, 225):
            painter.drawArc(arc2_rect, int((start - self._orbit_angle * 0.7) * 16), 68 * 16)

        # 3. Radial Music/Voice Visualizer & Orbiting Nucleus Projectiles
        self._draw_nucleus_visualizer(painter, cx, cy, scale)

        # 4. Node positions & Neural Pathways
        rx = min(w * 0.37, 295 * scale)
        ry = min(h * 0.36, 190 * scale)
        node_w = 158 * scale
        node_h = 62 * scale

        for idx, node in enumerate(self.nodes):
            rad = math.radians(node.angle_deg)
            nx = cx + math.cos(rad) * rx
            ny = cy + math.sin(rad) * ry
            node.rect = QRectF(nx - node_w / 2, ny - node_h / 2, node_w, node_h)

            is_hot = node.activity_heat > 0.05 or self._hovered_key == node.key
            heat = max(node.activity_heat, 0.85 if self._hovered_key == node.key else 0.0)

            start_r = 95 * scale
            sx = cx + math.cos(rad) * start_r
            sy = cy + math.sin(rad) * start_r
            mid_x = sx + (nx - sx) * 0.45

            path = QPainterPath()
            path.moveTo(sx, sy)
            path.lineTo(mid_x, sy)
            path.lineTo(mid_x, ny)
            path.lineTo(nx, ny)

            line_alpha = int(60 + 175 * heat)
            painter.setPen(QPen(QColor(86, 217, 232, line_alpha), 1.7 if is_hot else 1.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(86, 217, 232, int(140 + 115 * heat)))
            painter.drawEllipse(QPointF(sx, sy), 2.5, 2.5)

            if is_hot or self._core_state != "ERROR":
                t1 = (self._particle_phase + idx * 0.17) % 1.0
                pt1 = path.pointAtPercent(t1)
                painter.setBrush(QColor(86, 217, 232, 235 if is_hot else 110))
                painter.drawEllipse(pt1, 2.8 if is_hot else 1.8, 2.8 if is_hot else 1.8)

        # 5. Central CREED Core Circle + Insignia
        idle_glow = 0.48 + 0.2 * math.sin(self._idle_phase)
        if self._core_state in ("PROCESSING", "SPEAKING", "RECORDING", "LISTENING"):
            idle_glow = 0.96

        core_r = 90 * scale
        painter.setBrush(QColor(9, 14, 20, 240))
        painter.setPen(QPen(QColor(86, 217, 232, int(130 + 115 * idle_glow)), 2.0))
        painter.drawEllipse(QPointF(cx, cy), core_r, core_r)

        draw_creed_insignia(painter, cx, cy - 18 * scale, 54 * scale, idle_glow)

        painter.setPen(QColor("#E6EDF2"))
        title_font = QFont("SF Pro Display", int(12 * scale), QFont.Bold)
        title_font.setLetterSpacing(QFont.AbsoluteSpacing, 3.0)
        painter.setFont(title_font)
        painter.drawText(
            QRectF(cx - 70 * scale, cy + 12 * scale, 140 * scale, 22 * scale),
            Qt.AlignCenter,
            "CREED",
        )

        sub_font = QFont("SF Mono", max(8, int(8 * scale)))
        painter.setFont(sub_font)
        if self._core_state == "RETRYING":
            state_color = "#F97316"
        elif self._core_state == "ERROR":
            state_color = "#EF4444"
        else:
            state_color = "#56D9E8"
        painter.setPen(QColor(state_color))
        painter.drawText(
            QRectF(cx - 70 * scale, cy + 32 * scale, 140 * scale, 18 * scale),
            Qt.AlignCenter,
            f"● {self._core_state}",
        )

        # 6. Draw Node Cards
        for node in self.nodes:
            self._draw_node_card(painter, node, scale)

        # 7. Hover info strip
        if self._hovered_key:
            for n in self.nodes:
                if n.key == self._hovered_key:
                    info_rect = QRectF(18, 14, 340, 26)
                    painter.setBrush(QColor(16, 21, 27, 230))
                    painter.setPen(QPen(QColor(86, 217, 232, 130), 1.0))
                    painter.drawRoundedRect(info_rect, 4, 4)
                    painter.setPen(QColor("#E6EDF2"))
                    painter.setFont(QFont("SF Mono", 9))
                    painter.drawText(
                        info_rect.adjusted(10, 0, -10, 0),
                        Qt.AlignVCenter | Qt.AlignLeft,
                        f"{n.title} // {n.status} — Click to open workspace",
                    )
                    break

    def _draw_node_card(self, painter: QPainter, node: HubNode, scale: float):
        r = node.rect
        is_hovered = self._hovered_key == node.key
        heat = max(node.activity_heat, 0.8 if is_hovered else 0.0)

        cut = 9.0 * scale
        poly = QPainterPath()
        poly.moveTo(r.left() + cut, r.top())
        poly.lineTo(r.right(), r.top())
        poly.lineTo(r.right(), r.bottom() - cut)
        poly.lineTo(r.right() - cut, r.bottom())
        poly.lineTo(r.left(), r.bottom())
        poly.lineTo(r.left(), r.top() + cut)
        poly.closeSubpath()

        bg = QColor(21, 28, 36, 240) if is_hovered else QColor(14, 19, 25, 230)
        border_alpha = int(75 + 170 * heat)
        painter.setBrush(bg)
        painter.setPen(QPen(QColor(86, 217, 232, border_alpha), 1.3 if is_hovered else 1.0))
        painter.drawPath(poly)

        painter.setPen(QColor("#E6EDF2"))
        t_font = QFont("SF Pro Display", max(9, int(9.5 * scale)), QFont.DemiBold)
        t_font.setLetterSpacing(QFont.AbsoluteSpacing, 0.8)
        painter.setFont(t_font)
        painter.drawText(
            QRectF(r.left() + 12, r.top() + 7, r.width() - 20, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            node.title,
        )

        status_colors = {
            "ACTIVE": "#22C55E",
            "ONLINE": "#22C55E",
            "STANDBY": "#8BAFBE",
            "IDLE": "#F59E0B",
            "PROCESSING": "#56D9E8",
            "OFFLINE": "#EF4444",
        }
        dot_color = status_colors.get(node.status.upper(), "#56D9E8")
        painter.setPen(QColor(dot_color))
        painter.setFont(QFont("SF Mono", max(8, int(8 * scale))))
        painter.drawText(
            QRectF(r.left() + 12, r.top() + 24, r.width() - 20, 14),
            Qt.AlignLeft | Qt.AlignVCenter,
            f"● {node.status}",
        )

        painter.setPen(QColor("#65727F"))
        painter.setFont(QFont("SF Pro Display", max(8, int(8 * scale))))
        painter.drawText(
            QRectF(r.left() + 12, r.top() + 39, r.width() - 20, 15),
            Qt.AlignLeft | Qt.AlignVCenter,
            node.subtitle,
        )
