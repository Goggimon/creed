# gui/components/input_bar.py

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class CommandTextEdit(QPlainTextEdit):
    """Multi-line command input: Enter submits, Shift+Enter inserts a newline."""

    submitted = Signal()

    def __init__(self, placeholder: str = ""):
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.setFixedHeight(38)
        self.textChanged.connect(self._adjust_height)

    def _adjust_height(self):
        doc_height = int(self.document().size().height())
        line_h = self.fontMetrics().lineSpacing()
        target = max(38, min(104, doc_height * line_h + 16))
        if self.height() != target:
            self.setFixedHeight(target)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.submitted.emit()
            return
        super().keyPressEvent(event)


class InputBar(QWidget):
    submitted = Signal(str)
    voice_clicked = Signal()
    stop_clicked = Signal()

    def __init__(self, placeholder: str = "Ask CREED anything...", enable_cloud_consent: bool = False):
        super().__init__()
        self.setObjectName("input_bar_container")
        self._enable_cloud_consent = bool(enable_cloud_consent)
        self._provider_catalog: dict = {}
        self._installed_models: list[str] = []
        self._default_cloud_model: str = "llama-3.1-8b-instant"

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 4, 0, 0)
        outer_layout.setSpacing(4)

        self.provider_combo = None
        self.model_combo = None
        self.cloud_consent_btn = None

        if self._enable_cloud_consent:
            controls_row = QHBoxLayout()
            controls_row.setContentsMargins(0, 0, 0, 0)
            controls_row.setSpacing(8)

            self.provider_combo = QComboBox()
            self.provider_combo.setMinimumWidth(145)
            self.provider_combo.setFixedHeight(28)
            self.provider_combo.addItem("Provider: Auto", "")
            self.provider_combo.setToolTip("Select provider for upcoming turns (Auto uses ModelRouter)")
            self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)

            self.model_combo = QComboBox()
            self.model_combo.setEditable(True)
            self.model_combo.setMinimumWidth(190)
            self.model_combo.setFixedHeight(28)
            self.model_combo.addItem("Model: Auto", "")
            self.model_combo.setToolTip("Select model for upcoming turns (Auto uses provider default)")

            self.cloud_consent_btn = QPushButton("☁ CONSENT: OFF")
            self.cloud_consent_btn.setObjectName("secondary_btn")
            self.cloud_consent_btn.setCheckable(True)
            self.cloud_consent_btn.setChecked(False)
            self.cloud_consent_btn.setFixedHeight(28)
            self.cloud_consent_btn.setToolTip(
                "Allow private context to be sent to cloud for THIS SINGLE TURN only (resets after send)."
            )
            self.cloud_consent_btn.toggled.connect(self._sync_consent_label)

            controls_row.addWidget(self.provider_combo)
            controls_row.addWidget(self.model_combo, 1)
            controls_row.addWidget(self.cloud_consent_btn)
            outer_layout.addLayout(controls_row)

        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 2, 0, 0)
        bottom_layout.setSpacing(8)
        bottom_layout.setAlignment(Qt.AlignBottom)

        self.input_field = CommandTextEdit(placeholder)
        self.input_field.submitted.connect(self.handle_submit)

        self.voice_btn = QPushButton("🎙")
        self.voice_btn.setObjectName("secondary_btn")
        self.voice_btn.setFixedSize(40, 38)
        self.voice_btn.setToolTip("Toggle voice listening")
        self.voice_btn.clicked.connect(self.voice_clicked.emit)

        self.stop_btn = QPushButton("⏹")
        self.stop_btn.setObjectName("secondary_btn")
        self.stop_btn.setFixedSize(40, 38)
        self.stop_btn.setToolTip("Stop current generation / speech")
        self.stop_btn.clicked.connect(self.stop_clicked.emit)

        self.send_btn = QPushButton("▶")
        self.send_btn.setObjectName("primary_btn")
        self.send_btn.setFixedSize(48, 38)
        self.send_btn.setToolTip("Send command (Enter; Shift+Enter for new line)")
        self.send_btn.clicked.connect(self.handle_submit)

        bottom_layout.addWidget(self.input_field, 1)
        bottom_layout.addWidget(self.voice_btn)
        bottom_layout.addWidget(self.stop_btn)
        bottom_layout.addWidget(self.send_btn)
        outer_layout.addLayout(bottom_layout)

    def _on_provider_changed(self):
        if self.model_combo is None:
            return
        self._refresh_model_items(preserve_current=False)

    def _refresh_model_items(self, preserve_current: bool = True):
        if self.model_combo is None or self.model_combo.view().isVisible():
            return
        prev_data = self.model_combo.currentData() if preserve_current else ""
        prev_text = self.model_combo.currentText().strip() if preserve_current else ""

        selected_prov = self.provider_combo.currentData() if self.provider_combo is not None else ""
        models: list[str] = []
        if selected_prov:
            for tier_key in ("local", "cloud"):
                for p in self._provider_catalog.get(tier_key, []):
                    if p.get("name") == selected_prov:
                        if tier_key == "local":
                            models.extend(self._installed_models)
                        elif self._default_cloud_model:
                            models.append(self._default_cloud_model)
                        dmod = p.get("default_model")
                        if dmod and dmod not in models:
                            models.append(dmod)
        else:
            models.extend(self._installed_models)
            if self._default_cloud_model and self._default_cloud_model not in models:
                models.append(self._default_cloud_model)

        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItem("Model: Auto", "")
        for m in models:
            if m:
                self.model_combo.addItem(m, m)
        if preserve_current and prev_data:
            idx = self.model_combo.findData(prev_data)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
            elif prev_text and prev_text != "Model: Auto":
                self.model_combo.setCurrentText(prev_text)
        self.model_combo.blockSignals(False)

    def update_routing_options(
        self,
        provider_catalog: dict | None,
        installed_models: list | None = None,
        cloud_model: str = "",
    ) -> None:
        self._provider_catalog = dict(provider_catalog or {})
        self._installed_models = [
            m.get("name", "") if isinstance(m, dict) else str(m)
            for m in (installed_models or [])
            if (m.get("name", "") if isinstance(m, dict) else str(m))
        ]
        if cloud_model:
            self._default_cloud_model = cloud_model

        if self.provider_combo is not None and not self.provider_combo.view().isVisible():
            prev_prov = self.provider_combo.currentData() or ""
            entries: list[tuple[str, str]] = [("Provider: Auto", "")]
            for p in self._provider_catalog.get("local", []):
                name = p.get("name", "")
                if name:
                    entries.append((f"Local: {name}", name))
            for p in self._provider_catalog.get("cloud", []):
                name = p.get("name", "")
                if name:
                    entries.append((f"Cloud: {name}", name))

            current_entries = [
                (self.provider_combo.itemText(i), self.provider_combo.itemData(i))
                for i in range(self.provider_combo.count())
            ]
            if current_entries != entries:
                self.provider_combo.blockSignals(True)
                self.provider_combo.clear()
                for label, val in entries:
                    self.provider_combo.addItem(label, val)
                idx = self.provider_combo.findData(prev_prov)
                if idx >= 0:
                    self.provider_combo.setCurrentIndex(idx)
                self.provider_combo.blockSignals(False)

        self._refresh_model_items(preserve_current=True)

    def get_routing_selection(self) -> tuple[str | None, str | None]:
        sel_provider = None
        if self.provider_combo is not None:
            pval = (self.provider_combo.currentData() or "").strip()
            if pval:
                sel_provider = pval

        sel_model = None
        if self.model_combo is not None:
            mdata = self.model_combo.currentData()
            mtext = self.model_combo.currentText().strip()
            if mdata:
                sel_model = str(mdata).strip()
            elif mtext and mtext != "Model: Auto":
                sel_model = mtext
        return sel_provider, sel_model

    def _sync_consent_label(self, checked: bool):
        if self.cloud_consent_btn is None:
            return
        if checked:
            self.cloud_consent_btn.setText("☁ CONSENT: ON (1-TURN)")
            self.cloud_consent_btn.setStyleSheet(
                "color: #F59E0B; border: 1px solid #F59E0B; font-family: 'Menlo', monospace; font-size: 10.5px; font-weight: 700; padding: 0 8px;"
            )
        else:
            self.cloud_consent_btn.setText("☁ CONSENT: OFF")
            self.cloud_consent_btn.setStyleSheet("")

    def is_cloud_consent_enabled(self) -> bool:
        return bool(self.cloud_consent_btn is not None and self.cloud_consent_btn.isChecked())

    def reset_cloud_consent(self) -> None:
        if self.cloud_consent_btn is not None:
            self.cloud_consent_btn.setChecked(False)
            self._sync_consent_label(False)

    def consume_cloud_consent(self) -> bool:
        allowed = self.is_cloud_consent_enabled()
        self.reset_cloud_consent()
        return allowed

    def handle_submit(self):
        text = self.input_field.toPlainText().strip()
        if text:
            self.submitted.emit(text)
            self.input_field.clear()
            self.input_field.setFixedHeight(38)
