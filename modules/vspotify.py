# modules/vspotify.py

from core.event_bus import event_bus

VALID_VISUALIZERS = {
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
}

VALID_HUDS = {"cinema", "minimal", "centered", "hidden"}
VALID_BACKGROUNDS = {"album-blur", "pure-black", "gradient"}


async def dispatch_vspotify_command(action: str, params: dict = None) -> str:
    payload = {"action": action, "params": params or {}}
    await event_bus.publish("vspotify_command", payload)
    await event_bus.publish("node_pulse", "VSPOTIFY")
    return f"Sent VSpotify command '{action}' ({params or {}})."


def register_tools(registry):
    async def _playback(action: str) -> str:
        act = action.strip().lower()
        if act not in ("play_pause", "next", "prev", "demo_synth", "toggle_fullscreen", "toggle_drawer"):
            return f"Unsupported VSpotify playback action: {action}"
        return await dispatch_vspotify_command("playback", {"cmd": act})

    async def _set_visualizer(name: str) -> str:
        viz = name.strip().lower()
        if viz == "wave":
            viz = "waveform"
        elif viz == "concert":
            viz = "mirror"
        if viz not in VALID_VISUALIZERS:
            return f"Unknown visualizer '{name}'. Choose from: {', '.join(sorted(VALID_VISUALIZERS))}."
        return await dispatch_vspotify_command("set_visualizer", {"viz": viz})

    async def _set_hud(layout: str) -> str:
        hud = layout.strip().lower()
        if hud not in VALID_HUDS:
            return f"Unknown HUD '{layout}'. Choose from: cinema, minimal, centered, hidden."
        return await dispatch_vspotify_command("set_hud", {"hud": hud})

    async def _customize(
        bg_style: str = "",
        accent_color: str = "",
        auto_color: str = "",
        glow: float = -1,
        sensitivity: float = -1,
        bass: float = -1,
        mids: float = -1,
        treble: float = -1,
    ) -> str:
        params = {}
        if bg_style and bg_style.strip().lower() in VALID_BACKGROUNDS:
            params["bg_style"] = bg_style.strip().lower()
        if accent_color and accent_color.strip().startswith("#"):
            params["accent_color"] = accent_color.strip()
        if auto_color.lower() in ("true", "false"):
            params["auto_color"] = auto_color.lower() == "true"
        if glow >= 0:
            params["glow"] = max(0, min(40, int(glow)))
        if sensitivity > 0:
            params["sensitivity"] = max(0.4, min(2.5, float(sensitivity)))
        if bass >= 0:
            params["bass"] = max(0.0, min(2.5, float(bass)))
        if mids >= 0:
            params["mids"] = max(0.0, min(2.5, float(mids)))
        if treble >= 0:
            params["treble"] = max(0.0, min(2.5, float(treble)))
        if not params:
            return "No valid customization parameters provided."
        return await dispatch_vspotify_command("customize", params)

    async def _open_tab() -> str:
        return await dispatch_vspotify_command("open_tab", {})

    registry.register(
        name="vspotify_playback",
        description="Control VSpotify playback and UI actions (play_pause, next, prev, demo_synth, toggle_fullscreen, toggle_drawer).",
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "One of: play_pause, next, prev, demo_synth, toggle_fullscreen, toggle_drawer",
                }
            },
            "required": ["action"],
        },
        handler=_playback,
    )

    registry.register(
        name="vspotify_set_visualizer",
        description="Switch the active VSpotify audio visualizer (bars, radial, waveform, particles, horizon, matrix, milkdrop, plasma, lasers, mirror).",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Visualizer name"}
            },
            "required": ["name"],
        },
        handler=_set_visualizer,
    )

    registry.register(
        name="vspotify_set_hud",
        description="Switch the VSpotify HUD layout (cinema, minimal, centered, hidden).",
        parameters={
            "type": "object",
            "properties": {
                "layout": {"type": "string", "description": "HUD layout name"}
            },
            "required": ["layout"],
        },
        handler=_set_hud,
    )

    registry.register(
        name="vspotify_customize",
        description="Customize VSpotify visual theme, background, glow, sensitivity, or EQ bands (bass, mids, treble).",
        parameters={
            "type": "object",
            "properties": {
                "bg_style": {"type": "string", "description": "album-blur, pure-black, or gradient"},
                "accent_color": {"type": "string", "description": "Hex color e.g. #6EA8FE"},
                "auto_color": {"type": "string", "description": "'true' or 'false'"},
                "glow": {"type": "number", "description": "Glow 0-40"},
                "sensitivity": {"type": "number", "description": "Sensitivity 0.4-2.5"},
                "bass": {"type": "number", "description": "Bass EQ 0.0-2.5"},
                "mids": {"type": "number", "description": "Mids EQ 0.0-2.5"},
                "treble": {"type": "number", "description": "Treble EQ 0.0-2.5"},
            },
        },
        handler=_customize,
    )

    registry.register(
        name="vspotify_open_tab",
        description="Switch CREED's main interface directly to the embedded VSpotify player tab.",
        parameters={"type": "object", "properties": {}},
        handler=_open_tab,
    )
