# gui/components/chat_view.py

import html
import re
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

_LATEX_SYMBOLS = {
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
    r"\Delta": "Δ", r"\epsilon": "ε", r"\varepsilon": "ε", r"\zeta": "ζ",
    r"\eta": "η", r"\theta": "θ", r"\Theta": "Θ", r"\lambda": "λ",
    r"\Lambda": "Λ", r"\mu": "μ", r"\nu": "ν", r"\xi": "ξ",
    r"\pi": "π", r"\Pi": "Π", r"\rho": "ρ", r"\sigma": "σ",
    r"\Sigma": "Σ", r"\tau": "τ", r"\phi": "φ", r"\Phi": "Φ",
    r"\chi": "χ", r"\psi": "ψ", r"\omega": "ω", r"\Omega": "Ω",
    r"\infty": "∞", r"\approx": "≈", r"\neq": "≠", r"\ne": "≠",
    r"\leq": "≤", r"\le": "≤", r"\geq": "≥", r"\ge": "≥",
    r"\pm": "±", r"\mp": "∓", r"\times": "×", r"\cdot": "·",
    r"\div": "÷", r"\rightarrow": "→", r"\to": "→", r"\Rightarrow": "⇒",
    r"\leftarrow": "←", r"\leftrightarrow": "↔", r"\int": "∫",
    r"\sum": "∑", r"\prod": "∏", r"\partial": "∂", r"\nabla": "∇",
    r"\propto": "∝", r"\equiv": "≡", r"\degree": "°", r"\circ": "°",
}


def _latex_expr_to_html(expr: str, display: bool = False) -> str:
    s = html.escape(expr.strip())
    for cmd, uni in _LATEX_SYMBOLS.items():
        s = s.replace(cmd, uni)

    # \sqrt{x} -> √(x)
    s = re.sub(r"\\sqrt\{([^{}]+)\}", r"√(\1)", s)
    # \text{...} / \mathrm{...} -> plain
    s = re.sub(r"\\(?:text|mathrm|mathbf)\{([^{}]+)\}", r"\1", s)

    # \frac{a}{b} -> stacked HTML table for display math, or styled inline fraction
    for _ in range(3):
        if display:
            s = re.sub(
                r"\\frac\{([^{}]+)\}\{([^{}]+)\}",
                r"<table style='display:inline-table; vertical-align:middle; border-collapse:collapse; margin:0 3px;'>"
                r"<tr><td style='border-bottom:1px solid #D4D4D8; text-align:center; padding:0 4px; font-size:12px;'>\1</td></tr>"
                r"<tr><td style='text-align:center; padding:0 4px; font-size:12px;'>\2</td></tr></table>",
                s,
            )
        else:
            s = re.sub(
                r"\\frac\{([^{}]+)\}\{([^{}]+)\}",
                r"<span>(\1)/(\2)</span>",
                s,
            )

    # Superscripts ^{...} / ^x and subscripts _{...} / _x
    s = re.sub(r"\^\{([^{}]+)\}", r"<sup>\1</sup>", s)
    s = re.sub(r"\^([A-Za-z0-9+\-])", r"<sup>\1</sup>", s)
    s = re.sub(r"_\{([^{}]+)\}", r"<sub>\1</sub>", s)
    s = re.sub(r"_([A-Za-z0-9+\-])", r"<sub>\1</sub>", s)
    s = s.replace(r"\,", " ").replace(r"\;", " ").replace(r"\left", "").replace(r"\right", "")

    if display:
        return (
            f"<div style='background:#121318; border:1px solid rgba(255,255,255,0.08); "
            f"border-radius:8px; padding:10px 14px; margin:8px 0; text-align:center; "
            f"font-family:Georgia,\"Times New Roman\",serif; font-size:14px; color:#E5E7EB;'>{s}</div>"
        )
    return (
        f"<span style='font-family:Georgia,\"Times New Roman\",serif; "
        f"color:#E5E7EB; background:rgba(255,255,255,0.04); padding:1px 4px; border-radius:4px;'>{s}</span>"
    )


def _markdown_to_html(raw: str) -> str:
    """Convert Markdown and LaTeX math blocks into styled HTML."""
    parts = re.split(r"(```[a-zA-Z0-9_-]*\n[\s\S]*?```)", raw)
    rendered = []

    for part in parts:
        if part.startswith("```") and part.endswith("```"):
            inner = part[3:-3]
            if "\n" in inner:
                lang, code = inner.split("\n", 1)
                lang = lang.strip()
            else:
                lang, code = "", inner
            escaped_code = html.escape(code.rstrip("\n"))
            header = (
                f"<div style='color:#9CA3AF; font-size:10px; margin-bottom:5px; "
                f"font-weight:600;'>{html.escape(lang or 'code')}</div>"
            )
            rendered.append(
                f"<div style='background:#0E0F12; border:1px solid rgba(255,255,255,0.08); "
                f"border-radius:8px; padding:10px 12px; margin:6px 0;'>"
                f"{header}"
                f"<pre style='margin:0; font-family:\"SF Mono\",Menlo,monospace; "
                f"font-size:12px; color:#93C5FD; white-space:pre-wrap;'>{escaped_code}</pre>"
                f"</div>"
            )
        else:
            # Extract display math ($$...$$ and \[...\]) and inline math ($...$ and \(...\))
            tokens = re.split(r"(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$[^$\n]+?\$)", part)
            out = []
            for tok in tokens:
                if (tok.startswith("$$") and tok.endswith("$$")) or (tok.startswith(r"\[") and tok.endswith(r"\]")):
                    out.append(_latex_expr_to_html(tok[2:-2], display=True))
                elif tok.startswith(r"\(") and tok.endswith(r"\)"):
                    out.append(_latex_expr_to_html(tok[2:-2], display=False))
                elif tok.startswith("$") and tok.endswith("$") and len(tok) > 2:
                    out.append(_latex_expr_to_html(tok[1:-1], display=False))
                else:
                    esc = html.escape(tok)
                    esc = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc)
                    esc = re.sub(
                        r"`([^`\n]+)`",
                        r"<code style='background:#0E0F12; color:#93C5FD; padding:1px 5px; "
                        r"border-radius:4px; font-family:\"SF Mono\",Menlo,monospace; font-size:11.5px;'>\1</code>",
                        esc,
                    )
                    esc = esc.replace("\n", "<br>")
                    out.append(esc)
            rendered.append("".join(out))

    return "".join(rendered)


class ChatBubble(QFrame):
    def __init__(self, text: str, is_user: bool = False):
        super().__init__()
        self._raw_text = text

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)

        bubble = QFrame()
        bubble.setObjectName("user_msg" if is_user else "ai_msg")
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(14, 10, 14, 10)
        bubble_layout.setSpacing(4)

        role_lbl = QLabel("You" if is_user else "CREED")
        role_lbl.setObjectName("msg_role_user" if is_user else "msg_role_ai")
        bubble_layout.addWidget(role_lbl)

        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.RichText)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.label.setObjectName("msg_body")
        self._refresh_text()
        bubble_layout.addWidget(self.label)

        if is_user:
            layout.addStretch(1)
            layout.addWidget(bubble, 4)
        else:
            layout.addWidget(bubble, 5)
            layout.addStretch(1)

        self.bubble = bubble

    def _refresh_text(self):
        self.label.setText(_markdown_to_html(self._raw_text))

    def append_text(self, text: str):
        self._raw_text += text
        self._refresh_text()


class ChatView(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setObjectName("chat_area")
        self._scroll_anim = None

        self.chat_container = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setSpacing(10)
        self.chat_layout.setContentsMargins(8, 8, 8, 8)
        self.chat_layout.addStretch()
        self.setWidget(self.chat_container)

    def clear_bubbles(self):
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def add_bubble(self, text: str, is_user: bool = False) -> ChatBubble:
        bubble = ChatBubble(text, is_user)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        self.scroll_to_bottom()
        return bubble

    def add_tool_badge(self, text: str):
        lbl = QLabel(f"⚙  {text}")
        lbl.setObjectName("tool_badge")
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, lbl)
        self.scroll_to_bottom()

    def scroll_to_bottom(self):
        QTimer.singleShot(15, self._apply_scroll)

    def _apply_scroll(self):
        scrollbar = self.verticalScrollBar()
        target = scrollbar.maximum()
        if scrollbar.value() == target:
            return
        self._scroll_anim = QPropertyAnimation(scrollbar, b"value", self)
        self._scroll_anim.setDuration(140)
        self._scroll_anim.setStartValue(scrollbar.value())
        self._scroll_anim.setEndValue(target)
        self._scroll_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._scroll_anim.start()
