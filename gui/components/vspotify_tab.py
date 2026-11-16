# gui/components/vspotify_tab.py

import json
import webbrowser
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineView = None


VISUALIZERS = [
    "bars",
    "radial",
    "waveform",
    "particles",
    "horizon",
    "matrix",
    "milkdrop",
    "plasma",
    "lasers",
    "mirror",
]


class VSpotifyTab(QWidget):
    """Embedded VSpotify studio player with live AI/voice command execution."""

    command_requested = Signal(str, dict)

    def __init__(self):
        super().__init__()
        self._loaded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Studio Control Strip
        top = QFrame()
        top.setObjectName("panel_card")
        t_lay = QHBoxLayout(top)
        t_lay.setContentsMargins(12, 8, 12, 8)
        t_lay.setSpacing(8)

        title = QLabel("VSpotify")
        title.setObjectName("tab_title")

        self.viz_combo = QComboBox()
        self.viz_combo.addItems([v.title() for v in VISUALIZERS])
        self.viz_combo.setStyleSheet(
            "background-color: #101216; border: 1px solid rgba(255,255,255,0.08); "
            "border-radius: 6px; padding: 5px 8px; color: #ECEEF2; font-size: 11px;"
        )
        self.viz_combo.currentTextChanged.connect(
            lambda v: self.execute_command("set_visualizer", {"viz": v.lower()})
        )

        self.hud_combo = QComboBox()
        self.hud_combo.addItems(["Cinema", "Minimal", "Centered", "Hidden"])
        self.hud_combo.setStyleSheet(self.viz_combo.styleSheet())
        self.hud_combo.currentTextChanged.connect(
            lambda h: self.execute_command("set_hud", {"hud": h.lower()})
        )

        prev_btn = QPushButton("⏮")
        prev_btn.setObjectName("secondary_btn")
        prev_btn.setFixedWidth(34)
        prev_btn.clicked.connect(lambda: self.execute_command("playback", {"cmd": "prev"}))

        play_btn = QPushButton("⏯")
        play_btn.setObjectName("primary_btn")
        play_btn.setFixedWidth(38)
        play_btn.clicked.connect(lambda: self.execute_command("playback", {"cmd": "play_pause"}))

        next_btn = QPushButton("⏭")
        next_btn.setObjectName("secondary_btn")
        next_btn.setFixedWidth(34)
        next_btn.clicked.connect(lambda: self.execute_command("playback", {"cmd": "next"}))

        synth_btn = QPushButton("Synth Beat")
        synth_btn.setObjectName("secondary_btn")
        synth_btn.clicked.connect(lambda: self.execute_command("playback", {"cmd": "demo_synth"}))

        browser_btn = QPushButton("Open in Browser ↗")
        browser_btn.setObjectName("secondary_btn")
        browser_btn.clicked.connect(lambda: webbrowser.open("https://goggimon.github.io/VSpotify/"))

        t_lay.addWidget(title)
        t_lay.addSpacing(8)
        t_lay.addWidget(QLabel("Visualizer"))
        t_lay.addWidget(self.viz_combo)
        t_lay.addWidget(QLabel("HUD"))
        t_lay.addWidget(self.hud_combo)
        t_lay.addStretch()
        t_lay.addWidget(prev_btn)
        t_lay.addWidget(play_btn)
        t_lay.addWidget(next_btn)
        t_lay.addWidget(synth_btn)
        t_lay.addWidget(browser_btn)
        layout.addWidget(top)

        if QWebEngineView is not None:
            self.webview = QWebEngineView()
            self.webview.setStyleSheet("background: #0E0F12; border-radius: 10px;")
            layout.addWidget(self.webview, 1)
        else:
            self.webview = None
            fallback = QFrame()
            fallback.setObjectName("panel_card")
            fl = QVBoxLayout(fallback)
            fl.setAlignment(Qt.AlignCenter)
            msg = QLabel(
                "PySide6-WebEngine is not installed in this environment.\n"
                "Click 'Open in Browser ↗' above to launch VSpotify at https://goggimon.github.io/VSpotify/."
            )
            msg.setObjectName("meta_label")
            msg.setAlignment(Qt.AlignCenter)
            fl.addWidget(msg)
            layout.addWidget(fallback, 1)

    def ensure_loaded(self):
        if self.webview is not None and not self._loaded:
            self._loaded = True
            self.webview.setUrl(QUrl("https://goggimon.github.io/VSpotify/"))

    def execute_command(self, action: str, params: dict = None):
        params = params or {}
        if self.webview is None:
            return
        self.ensure_loaded()

        js = ""
        if action == "playback":
            cmd = params.get("cmd", "")
            btn_map = {
                "play_pause": "btn-play",
                "next": "btn-next",
                "prev": "btn-prev",
                "demo_synth": "btn-demo-synth",
                "toggle_fullscreen": "btn-fullscreen",
                "toggle_drawer": "btn-toggle-drawer",
            }
            el_id = btn_map.get(cmd)
            if el_id:
                js = f"document.getElementById('{el_id}')?.click();"
        elif action == "set_visualizer":
            viz = params.get("viz", "bars")
            js = f"document.querySelector(\".viz-chip[data-viz='{viz}']\")?.click();"
        elif action == "set_hud":
            hud = params.get("hud", "cinema")
            js = f"document.querySelector(\"#hud-selector .seg-btn[data-hud='{hud}']\")?.click();"
        elif action == "customize":
            statements = []
            if "bg_style" in params:
                v = json.dumps(params["bg_style"])
                statements.append(
                    f"(() => {{ const el = document.getElementById('opt-bg-style'); if(el){{ el.value={v}; el.dispatchEvent(new Event('change')); }} }})();"
                )
            if "accent_color" in params:
                v = json.dumps(params["accent_color"])
                statements.append(
                    f"(() => {{ const el = document.getElementById('opt-accent-color'); if(el){{ el.value={v}; el.dispatchEvent(new Event('input')); }} }})();"
                )
            if "auto_color" in params:
                b = "true" if params["auto_color"] else "false"
                statements.append(
                    f"(() => {{ const el = document.getElementById('opt-auto-color'); if(el){{ el.checked={b}; el.dispatchEvent(new Event('change')); }} }})();"
                )
            slider_map = {
                "glow": "opt-glow",
                "sensitivity": "opt-sensitivity",
                "bass": "eq-bass",
                "mids": "eq-mids",
                "treble": "eq-treble",
            }
            for key, el_id in slider_map.items():
                if key in params:
                    v = json.dumps(str(params[key]))
                    statements.append(
                        f"(() => {{ const el = document.getElementById('{el_id}'); if(el){{ el.value={v}; el.dispatchEvent(new Event('input')); }} }})();"
                    )
            js = "\n".join(statements)

        if js:
            self.webview.page().runJavaScript(js)
