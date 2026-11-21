# intelligence/complexity_classifier.py

import re
import time
from dataclasses import dataclass

_GREETING_ONLY = re.compile(
    r"^(?:hi|hello|hey|thanks|thank you|ok|okay|yes|no|bye|good morning|good night)[!.\s]*$",
    re.IGNORECASE,
)

_SIMPLE_COMMAND = re.compile(
    r"^(?:stop|pause|play|next|previous|skip|mute|unmute|"
    r"what time|what's the time|open \w+|close \w+|"
    r"turn (?:on|off)|volume (?:up|down)|set volume)\b",
    re.IGNORECASE,
)

_REASONING_MARKERS = re.compile(
    r"\b(?:explain|why|how does|how do|compare|contrast|derive|prove|analyze|analyse|"
    r"design|architect|debug|optimize|refactor|strategy|trade-?off|"
    r"integral|derivative|differential|thermodynamics|equilibrium|kinetics|"
    r"circuit|quantum|algorithm|complexity|jee|calculus|electrochemistry)\b",
    re.IGNORECASE,
)

_BACKGROUND_MARKERS = re.compile(
    r"\b(?:research|audit|write a (?:script|program|file)|create a (?:file|project|workflow)|"
    r"search my files|find all|scan|summarize everything|build a|run python|execute script|"
    r"in the background|background task|as a task)\b",
    re.IGNORECASE,
)


@dataclass
class ClassificationResult:
    path: str  # "instant" | "intelligent" | "background"
    reason: str
    latency_ms: float
    needs_tools: bool = False
    allow_background_tools: bool = False


def classify_complexity(text: str, mode: str = "default") -> ClassificationResult:
    t0 = time.monotonic()
    clean = (text or "").strip()

    if not clean or len(clean) < 2:
        return ClassificationResult(
            path="instant",
            reason="Empty or noise transcript",
            latency_ms=(time.monotonic() - t0) * 1000.0,
            needs_tools=False,
            allow_background_tools=False,
        )

    if mode == "jee":
        return ClassificationResult(
            path="intelligent",
            reason="JEE scientific workstation mode",
            latency_ms=(time.monotonic() - t0) * 1000.0,
            needs_tools=False,
            allow_background_tools=False,
        )

    if _BACKGROUND_MARKERS.search(clean):
        return ClassificationResult(
            path="background",
            reason="Multi-step tool/file/research directive",
            latency_ms=(time.monotonic() - t0) * 1000.0,
            needs_tools=True,
            allow_background_tools=True,
        )

    if _REASONING_MARKERS.search(clean) or ("?" in clean and len(clean.split()) >= 8):
        return ClassificationResult(
            path="intelligent",
            reason="Complex reasoning, planning, or explanation",
            latency_ms=(time.monotonic() - t0) * 1000.0,
            needs_tools=True,
            allow_background_tools=True,
        )

    if _GREETING_ONLY.match(clean):
        return ClassificationResult(
            path="instant",
            reason="Simple greeting or acknowledgement",
            latency_ms=(time.monotonic() - t0) * 1000.0,
            needs_tools=False,
            allow_background_tools=False,
        )

    if _SIMPLE_COMMAND.search(clean):
        return ClassificationResult(
            path="instant",
            reason="Direct device/media command",
            latency_ms=(time.monotonic() - t0) * 1000.0,
            needs_tools=True,
            allow_background_tools=False,
        )

    return ClassificationResult(
        path="instant",
        reason="Short conversational turn",
        latency_ms=(time.monotonic() - t0) * 1000.0,
        needs_tools=False,
        allow_background_tools=False,
    )
