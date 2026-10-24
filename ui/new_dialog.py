"""'New Document' dialog — mirrors Photoshop's Ctrl+N dialog."""
from ui._autosize import AutoSizeMixin
from PyQt5.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QSpinBox,
    QComboBox, QDialogButtonBox, QVBoxLayout
)


PRESETS = {
    "Custom":          (800, 600),
    "Default Photoshop Size": (1920, 1080),
    "Web 1280x720":    (1280, 720),
    "Instagram Square":(1080, 1080),
    "A4 (300 dpi)":    (2480, 3508),
}

BACKGROUNDS = ["white", "black", "transparent"]


class NewDocumentDialog(QDialog, AutoSizeMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Document")
        self.setMinimumWidth(360)

        self.name_edit = QLineEdit("Untitled-1")
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(PRESETS.keys())
        self.width_spin = QSpinBox();  self.width_spin.setRange(1, 20000);  self.width_spin.setValue(800)
        self.height_spin = QSpinBox(); self.height_spin.setRange(1, 20000); self.height_spin.setValue(600)
        self.bg_combo = QComboBox()
        self.bg_combo.addItems(BACKGROUNDS)

        form = QFormLayout()
        form.addRow("Name:", self.name_edit)
        form.addRow("Preset:", self.preset_combo)
        form.addRow("Width (px):", self.width_spin)
        form.addRow("Height (px):", self.height_spin)
        form.addRow("Background:", self.bg_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self.preset_combo.currentTextChanged.connect(self._apply_preset)
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, lambda: self.auto_size(min_w=380, min_h=280))

    def _apply_preset(self, name: str) -> None:
        w, h = PRESETS[name]
        self.width_spin.setValue(w)
        self.height_spin.setValue(h)

    def values(self) -> dict:
        return {
            "name": self.name_edit.text().strip() or "Untitled",
            "width": self.width_spin.value(),
            "height": self.height_spin.value(),
            "background": self.bg_combo.currentText(),
        }
