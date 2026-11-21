# gui/components/radial_hub.py

import math
import time
from dataclasses import dataclass, field
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget


@dataclass
class SpatialAnchor:
    key: str
    sys_id: str
    title: str
    subtitle: str
    accent: str
    tab_index: int
    nx: float  # Normalized x (0..1)
    ny: float  # Normalized y (0..1)
    align_right: bool = False
    activity_heat: float = 0.0
    hover_anim: float = 0.0
    rect: QRectF = field(default_factory=QRectF)


# Precomputed state palettes: (core_primary, core_secondary, glow_color, label)
CORE_STATE_THEMES = {
    "Idle": ("#67E8F9", "#A78BFA", "#38BDF8", "DORMANT // READY"),
    "Listening": ("#6EE7B7", "#38BDF8", "#34D399", "ATTENTIVE // LISTENING"),
    "Recording": ("#FDBA74", "#F472B6", "#FB923C", "AUDIO CAPTURE"),
    "Processing": ("#FCD34D", "#FB923C", "#F59E0B", "COMPUTING // FAST PATH"),
    "Reasoning": ("#C084FC", "#F472B6", "#A78BFA", "DEEP REASONING // ACTIVE"),
    "Speaking": ("#5EEAD4", "#818CF8", "#2DD4BF", "VOICE SYNTHESIS"),
    "Interrupted": ("#6EE7B7", "#FDBA74", "#34D399", "BARGE-IN // INTERRUPTED"),
    "Retrying Connection": ("#94A3B8", "#475569", "#64748B", "OFFLINE // RETRYING"),
    "Error": ("#FDA4AF", "#F43F5E", "#FB7185", "SYSTEM FAULT"),
}


class RadialHubWidget(QWidget):
    """Pre-rendered holographic undulating dot-mesh intelligence field (NO logo, NO orbital rings)."""

    node_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(620, 420)

        self._raw_state = "Idle"
        self._frame_idx = 0.0
        self._pulse_phase = 0.0
        self._audio_level = 0.0
        self._hovered_key = None
        self._last_t = time.monotonic()

        self._sprite_size = 380
        self._sprite_cache: dict[str, list[QPixmap]] = {}
        self._bg_cache = None
        self._bg_size = (0, 0)

        # Precompute base spherical-lattice coordinates (42 latitude x 48 longitude = 2,016 structured dots)
        self._lattice = []
        n_lat, n_lon = 36, 46
        for i in range(1, n_lat):
            phi = (i / n_lat) * math.pi  # 0..pi
            sp, cp = math.sin(phi), math.cos(phi)
            for j in range(n_lon):
                theta = (j / n_lon) * 2.0 * math.pi
                self._lattice.append((phi, theta, sp, cp, math.sin(theta), math.cos(theta)))

        # Asymmetric Swiss-Grid spatial anchors around the central intelligence field
        self.nodes = [
            SpatialAnchor("CONVERSATION", "01", "Intelligence", "Direct Dialogue", "#67E8F9", 1, 0.14, 0.28),
            SpatialAnchor("MEMORY", "02", "Knowledge", "Memory Graph", "#5EEAD4", 2, 0.16, 0.72),
            SpatialAnchor("AUTOMATION", "03", "Task Ops", "Execution Flow", "#FBBF24", 3, 0.86, 0.28, align_right=True),
            SpatialAnchor("SYSTEMS", "04", "Machine", "macOS Host", "#FB923C", 4, 0.86, 0.56, align_right=True),
            SpatialAnchor("MODELS", "06", "AI Models", "Local Weights", "#93C5FD", 6, 0.74, 0.84, align_right=True),
        ]

        self._title_font = QFont("SF Pro Display", 12, QFont.DemiBold)
        self._sub_font = QFont("Menlo", 8.5)
        self._id_font = QFont("Menlo", 8, QFont.Bold)
        self._hud_font = QFont("Menlo", 8.5, QFont.Bold)

        # Pre-render the default Idle sequence immediately so playback is instant
        self._ensure_state_sprites("Idle")

        self._timer = QTimer(self)
        self._timer.setInterval(12)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._last_t = time.monotonic()
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._timer.isActive():
            self._timer.stop()

    def set_audio_level(self, level: float):
        self._audio_level = max(0.0, min(1.0, float(level)))

    def set_core_state(self, state: str):
        self._raw_state = state if state in CORE_STATE_THEMES else "Idle"
        self._ensure_state_sprites(self._raw_state)
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

    def _ensure_state_sprites(self, state: str):
        if state in self._sprite_cache:
            return
        c1_hex, c2_hex, glow_hex, _ = CORE_STATE_THEMES.get(state, CORE_STATE_THEMES["Idle"])
        c1, c2, cg = QColor(c1_hex), QColor(c2_hex), QColor(glow_hex)
        sz = self._sprite_size
        cx = cy = sz / 2.0
        n_frames = 72
        frames = []

        # State-specific harmonic wave amplitude & speed
        amp = 0.24 if state in ("Processing", "Recording") else (0.19 if state in ("Listening", "Speaking") else 0.14)
        if state == "Retrying Connection":
            amp = 0.05

        for f in range(n_frames):
            t = (f / n_frames) * 2.0 * math.pi
            pix = QPixmap(sz, sz)
            pix.fill(Qt.transparent)
            p = QPainter()
            if not p.begin(pix):
                frames.append(pix)
                continue
            try:
                p.setRenderHint(QPainter.Antialiasing)

                # Subtle volumetric backing (no circular border!)
                rad_g = QRadialGradient(cx, cy, sz * 0.44)
                ga = QColor(cg); ga.setAlpha(34 if state != "Retrying Connection" else 14)
                rad_g.setColorAt(0.0, ga)
                rad_g.setColorAt(0.65, QColor(cg.red(), cg.green(), cg.blue(), 8))
                rad_g.setColorAt(1.0, QColor(0, 0, 0, 0))
                p.fillRect(0, 0, sz, sz, rad_g)

                yaw = t * 0.5
                pitch = 0.35 + 0.12 * math.sin(t)
                cy_a, sy_a = math.cos(yaw), math.sin(yaw)
                cp_a, sp_a = math.cos(pitch), math.sin(pitch)

                pts = []
                base_r = sz * 0.33
                for phi, theta, sp, cp, st, ct in self._lattice:
                    # Organic undulating wave deformation (like reference Image 1)
                    deform = (
                        1.0
                        + amp * math.sin(3.0 * phi + 2.0 * theta - t)
                        + (amp * 0.55) * math.cos(4.0 * theta - 2.0 * phi + t)
                    )
                    x = sp * ct * deform
                    y = cp * deform
                    z = sp * st * deform

                    rx = x * cy_a + z * sy_a
                    rz = -x * sy_a + z * cy_a
                    ry = y * cp_a - rz * sp_a
                    rz2 = y * sp_a + rz * cp_a

                    persp = 3.1 / (3.1 - rz2 * 0.72)
                    sx = cx + rx * base_r * persp
                    sy = cy + ry * base_r * persp
                    pts.append((rz2, sx, sy, persp, (y + 1.0) * 0.5))

                pts.sort(key=lambda item: item[0])
                p.setPen(Qt.NoPen)

                # Blend between c1 (top/cyan/gold) and c2 (bottom/violet/coral) by depth & latitude
                for rz2, sx, sy, persp, lat_t in pts:
                    depth = max(0.0, min(1.0, (rz2 + 1.2) / 2.4))
                    r = int(c1.red() * (1 - lat_t) + c2.red() * lat_t)
                    g = int(c1.green() * (1 - lat_t) + c2.green() * lat_t)
                    b = int(c1.blue() * (1 - lat_t) + c2.blue() * lat_t)
                    alpha = int((35 + 215 * (depth ** 1.4)) * (0.45 if state == "Retrying Connection" else 1.0))
                    p.setBrush(QColor(r, g, b, alpha))
                    dot_r = (0.85 + 1.45 * depth) * persp
                    p.drawEllipse(QPointF(sx, sy), dot_r, dot_r)
            finally:
                p.end()
            frames.append(pix)
        self._sprite_cache[state] = frames

    def _tick(self):
        now = time.monotonic()
        dt = min(0.05, max(0.001, now - self._last_t))
        self._last_t = now

        if self._raw_state == "Retrying Connection":
            fps = 8.0
        elif self._raw_state in ("Processing", "Recording"):
            fps = 44.0
        elif self._raw_state in ("Listening", "Speaking"):
            fps = 32.0 + self._audio_level * 18.0
        else:
            fps = 24.0

        frames = self._sprite_cache.get(self._raw_state) or self._sprite_cache["Idle"]
        self._frame_idx = (self._frame_idx + dt * fps) % len(frames)
        self._pulse_phase = (self._pulse_phase + dt * 0.55) % 1.0
        self._audio_level *= max(0.0, 1.0 - dt * 7.0)

        for n in self.nodes:
            if n.activity_heat > 0.0:
                n.activity_heat = max(0.0, n.activity_heat - dt * 1.1)
            target_h = 1.0 if self._hovered_key == n.key else 0.0
            n.hover_anim += (target_h - n.hover_anim) * min(1.0, dt * 14.0)
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

    def _build_bg_cache(self, w: int, h: int) -> QPixmap:
        pix = QPixmap(w, h)
        pix.fill(QColor("#07080C"))
        p = QPainter()
        if not p.begin(pix):
            return pix
        try:
            p.setRenderHint(QPainter.Antialiasing)
            # Subtle architectural radial depth
            g = QRadialGradient(w * 0.5, h * 0.48, max(w, h) * 0.6)
            g.setColorAt(0.0, QColor(18, 22, 36, 95))
            g.setColorAt(1.0, QColor(7, 8, 12, 0))
            p.fillRect(0, 0, w, h, g)

            # Fine editorial Swiss hairline guides
            p.setPen(QPen(QColor(255, 255, 255, 10), 1.0))
            p.drawLine(QPointF(w * 0.29, 28), QPointF(w * 0.29, h - 28))
            p.drawLine(QPointF(w * 0.71, 28), QPointF(w * 0.71, h - 28))
            p.drawLine(QPointF(28, h * 0.50), QPointF(w - 28, h * 0.50))
        finally:
            p.end()
        return pix

    def paintEvent(self, event):
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            w, h = self.width(), self.height()

            if self._bg_cache is None or self._bg_size != (w, h):
                self._bg_cache = self._build_bg_cache(w, h)
                self._bg_size = (w, h)
            painter.drawPixmap(0, 0, self._bg_cache)

            cx, cy = w * 0.5, h * 0.48
            scale = max(0.75, min(1.25, min(w / 880.0, h / 540.0)))

            # 1. Precomputed Spatial Signal Conduits to Asymmetric Subsystem Anchors
            for idx, node in enumerate(self.nodes):
                ax = node.nx * w
                ay = node.ny * h
                anchor_w, anchor_h = 166 * scale, 48 * scale
                node.rect = QRectF(ax - anchor_w / 2, ay - anchor_h / 2, anchor_w, anchor_h)

                nc = QColor(node.accent)
                heat = max(node.activity_heat, node.hover_anim)

                # Connect from edge of dot-mesh field to inner edge of spatial anchor
                edge_x = ax + (anchor_w / 2 if not node.align_right else -anchor_w / 2)
                mid_x = cx + (edge_x - cx) * 0.55

                path = QPainterPath()
                path.moveTo(cx, cy)
                path.lineTo(mid_x, ay)
                path.lineTo(edge_x, ay)

                lc = QColor(nc); lc.setAlpha(int(34 + 175 * heat))
                painter.setPen(QPen(lc, 1.5 if heat > 0.1 else 0.9))
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(path)

                # Junction dot & travelling pulse
                painter.setPen(Qt.NoPen)
                jc = QColor(nc); jc.setAlpha(int(110 + 145 * heat))
                painter.setBrush(jc)
                painter.drawEllipse(QPointF(mid_x, ay), 2.2, 2.2)

                if heat > 0.05 or idx % 2 == 0:
                    t = (self._pulse_phase + idx * 0.14) % 1.0
                    pt = path.pointAtPercent(t)
                    pc = QColor(nc); pc.setAlpha(235 if heat > 0.1 else 120)
                    painter.setBrush(pc)
                    painter.drawEllipse(pt, 2.5 if heat > 0.1 else 1.7, 2.5 if heat > 0.1 else 1.7)

            # 2. Blit Pre-Rendered Holographic Dot-Mesh Core Frame (NO LOGO, NO RINGS)
            frames = self._sprite_cache.get(self._raw_state) or self._sprite_cache["Idle"]
            frame = frames[int(self._frame_idx) % len(frames)]
            draw_sz = self._sprite_size * scale * (1.0 + 0.08 * self._audio_level)
            painter.drawPixmap(
                QRectF(cx - draw_sz / 2.0, cy - draw_sz / 2.0, draw_sz, draw_sz),
                frame,
                QRectF(0, 0, self._sprite_size, self._sprite_size),
            )

            # Minimal state typography beneath field
            _, _, glow_hex, state_lbl = CORE_STATE_THEMES.get(self._raw_state, CORE_STATE_THEMES["Idle"])
            sc = QColor(glow_hex); sc.setAlpha(220)
            painter.setPen(sc)
            painter.setFont(self._hud_font)
            painter.drawText(
                QRectF(cx - 140, cy + draw_sz * 0.44, 280, 18),
                Qt.AlignCenter,
                state_lbl,
            )

            # 3. Draw Asymmetric Spatial Subsystem Anchors (Minimal Architectural Marks, NOT Dashboard Cards)
            for node in self.nodes:
                self._draw_anchor(painter, node, scale)
        finally:
            painter.end()

    def _draw_anchor(self, painter: QPainter, node: SpatialAnchor, scale: float):
        r = node.rect
        nc = QColor(node.accent)
        heat = max(node.activity_heat, node.hover_anim)

        # Translucent smoky architectural plate with left/right edge rule (NOT a rounded box card!)
        bg = QColor(14, 16, 24, int(150 + 75 * heat))
        painter.fillRect(r, bg)

        rule_x = r.right() - 2 if node.align_right else r.left()
        rc = QColor(nc); rc.setAlpha(int(140 + 115 * heat))
        painter.fillRect(QRectF(rule_x, r.top(), 2.5, r.height()), rc)

        align = Qt.AlignRight if node.align_right else Qt.AlignLeft
        pad_l = 10 if not node.align_right else 8
        pad_r = 12 if node.align_right else 8

        painter.setPen(rc)
        painter.setFont(self._id_font)
        painter.drawText(
            QRectF(r.left() + pad_l, r.top() + 4, r.width() - pad_l - pad_r, 12),
            align | Qt.AlignVCenter,
            f"SYS // {node.sys_id}",
        )

        painter.setPen(QColor("#F8FAFC"))
        painter.setFont(self._title_font)
        painter.drawText(
            QRectF(r.left() + pad_l, r.top() + 15, r.width() - pad_l - pad_r, 18),
            align | Qt.AlignVCenter,
            node.title,
        )

        painter.setPen(QColor("#94A3B8") if heat < 0.2 else rc)
        painter.setFont(self._sub_font)
        painter.drawText(
            QRectF(r.left() + pad_l, r.top() + 32, r.width() - pad_l - pad_r, 14),
            align | Qt.AlignVCenter,
            node.subtitle,
        )
