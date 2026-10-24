"""Export dialog — format + quality."""
from PyQt5.QtWidgets import (
    QDialog, QFormLayout, QComboBox, QSpinBox, QDialogButtonBox,
    QVBoxLayout, QLabel
)
from core.export import FORMATS
from ui._autosize import AutoSizeMixin


class ExportDialog(QDialog, AutoSizeMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export As")
        self.setMinimumWidth(320)

        self.fmt_combo = QComboBox()
        self.fmt_combo.addItems(FORMATS.keys())
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(90)

        form = QFormLayout()
        form.addRow("Format:", self.fmt_combo)
        form.addRow("Quality:", self.quality_spin)

        self.hint = QLabel("Quality applies to JPEG / WebP only.")
        self.hint.setStyleSheet("color:#888; font-size:11px;")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.hint)
        layout.addWidget(buttons)

        self.fmt_combo.currentTextChanged.connect(self._sync)
        self._sync(self.fmt_combo.currentText())
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, lambda: self.auto_size(min_w=340, min_h=220))

    def _sync(self, fmt: str):
        lossy = FORMATS[fmt]["lossy"]
        self.quality_spin.setEnabled(lossy)

    def values(self) -> dict:
        return {
            "format": self.fmt_combo.currentText(),
            "quality": self.quality_spin.value(),
        }
