"""Image import / edit dialog — live preview, effects, hue, scale."""
from pathlib import Path

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QSpinBox, QCheckBox, QDialogButtonBox, QFileDialog, QGroupBox,
    QFormLayout, QWidget, QSlider, QScrollArea, QFrame
)
from ui._autosize import AutoSizeMixin
from PyQt5.QtGui import QImage, QPixmap, QColor
from PyQt5.QtCore import Qt, QTimer, QSize

from core import imagemagick
from ui.sub_image_editor import SubImageEditor


PREVIEW_SIZE = QSize(380, 260)


class ImageImportDialog(QDialog, AutoSizeMixin):
    """Used both for *import* and *edit*. If `existing` is provided,
    fields start populated and Import becomes 'Apply'."""

    def __init__(self, parent=None, existing: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Edit Image" if existing else "Import Image")
        self.setMinimumWidth(520)
        self._source_path: str | None = existing.get("source") if existing else None
        self._pixel_override: QImage | None = None
        if existing and existing.get("pixel_override") is not None:
            self._pixel_override = existing["pixel_override"]

        # ---------- file row ----------
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("Choose an image file…")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        file_row = QHBoxLayout()
        file_row.addWidget(self.path_edit, 1)
        file_row.addWidget(browse)

        # ---------- preview ----------
        self.preview = QLabel("Preview\n(click to edit)")
        self.preview.setFixedSize(PREVIEW_SIZE)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet(
            "background:#1e1e1e; color:#aaa; border:1px solid #444;"
        )
        self.preview.setCursor(Qt.PointingHandCursor)
        self.preview.mousePressEvent = self._on_preview_clicked

        # ---------- transform ----------
        self.scale_spin = QSpinBox(); self.scale_spin.setRange(1, 1000); self.scale_spin.setValue(100)
        self.scale_spin.setSuffix(" %")
        self.rotate_spin = QSpinBox(); self.rotate_spin.setRange(-180, 180); self.rotate_spin.setSuffix(" °")

        # ---------- effects ----------
        self.grayscale = QCheckBox("Grayscale")
        self.sepia = QCheckBox("Sepia")
        self.blur_spin = QSpinBox(); self.blur_spin.setRange(0, 20); self.blur_spin.setSuffix(" px")
        self.sharpen_spin = QSpinBox(); self.sharpen_spin.setRange(0, 20); self.sharpen_spin.setSuffix(" px")
        self.brightness_spin = QSpinBox(); self.brightness_spin.setRange(-100, 100)
        self.contrast_spin = QSpinBox(); self.contrast_spin.setRange(-100, 100)

        # ---------- hue rotation ----------
        self.hue_slider = QSlider(Qt.Horizontal)
        self.hue_slider.setRange(-180, 180); self.hue_slider.setValue(0)
        self.hue_spin = QSpinBox(); self.hue_spin.setRange(-180, 180); self.hue_spin.setSuffix(" °")
        self.hue_slider.valueChanged.connect(self.hue_spin.setValue)
        self.hue_spin.valueChanged.connect(self.hue_slider.setValue)
        hue_row = QHBoxLayout()
        hue_row.addWidget(QLabel("Hue shift"))
        hue_row.addWidget(self.hue_slider, 1)
        hue_row.addWidget(self.hue_spin)

        # ---------- layout ----------
        size_group = QGroupBox("Size && Transform")
        size_form = QFormLayout(size_group)
        size_form.addRow("Scale:", self.scale_spin)
        size_form.addRow("Rotate:", self.rotate_spin)

        fx_group = QGroupBox("Effects")
        fx_form = QFormLayout(fx_group)
        fx_form.addRow(self.grayscale)
        fx_form.addRow(self.sepia)
        fx_form.addRow("Blur:", self.blur_spin)
        fx_form.addRow("Sharpen:", self.sharpen_spin)
        fx_form.addRow("Brightness:", self.brightness_spin)
        fx_form.addRow("Contrast:", self.contrast_spin)
        fx_form.addRow(hue_row)

        left = QVBoxLayout()
        left.addWidget(QLabel("Image file:"))
        left.addLayout(file_row)
        left.addWidget(size_group)
        left.addWidget(fx_group)

        body = QHBoxLayout()
        body.addLayout(left, 1)
        body.addWidget(self.preview)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Apply" if existing else "Import")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        # wrap body (not buttons) in a scroll area
        body_widget = QWidget(); body_widget.setLayout(body)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(body_widget)

        v = QVBoxLayout(self)
        v.addWidget(scroll, 1)
        v.addWidget(buttons)

        # ---------- debounce timer ----------
        self._timer = QTimer(self); self._timer.setSingleShot(True); self._timer.setInterval(180)
        self._timer.timeout.connect(self._update_preview)

        for w in (self.grayscale, self.sepia):
            w.stateChanged.connect(self._schedule_preview)
        for w in (self.blur_spin, self.sharpen_spin, self.brightness_spin,
                  self.contrast_spin, self.hue_spin):
            w.valueChanged.connect(self._schedule_preview)

        # ---------- seed from existing ----------
        # ensure the dialog auto-fits
        QTimer.singleShot(0, lambda: self.auto_size(min_w=560, min_h=480))

        if existing:
            self.path_edit.setText(self._source_path or "")
            fx = existing.get("effects", {})
            self.grayscale.setChecked(fx.get("grayscale", False))
            self.sepia.setChecked(fx.get("sepia", False))
            self.blur_spin.setValue(fx.get("blur", 0))
            self.sharpen_spin.setValue(fx.get("sharpen", 0))
            self.brightness_spin.setValue(fx.get("brightness", 0))
            self.contrast_spin.setValue(fx.get("contrast", 0))
            self.hue_spin.setValue(fx.get("hue", 0))
            self.scale_spin.setValue(int(existing.get("scale", 1.0) * 100))
            self.rotate_spin.setValue(int(existing.get("rotation", 0)))
            self._schedule_preview()

    # ---------- file picker ----------
    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tif *.tiff *.svg *.heic *.avif);;All Files (*)"
        )
        if path:
            self._source_path = path
            self._pixel_override = None
            self.path_edit.setText(path)
            self._schedule_preview()

    # ---------- preview ----------
    def _schedule_preview(self, *_):
        self._timer.start()

    def _clear_override(self, *_):
        self._pixel_override = None

    def _update_preview(self):
        # edited pixels take priority
        if self._pixel_override is not None:
            pix = QPixmap.fromImage(self._pixel_override).scaled(
                PREVIEW_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.preview.setPixmap(pix)
            return

        if not self._source_path:
            self.preview.setText("Choose a file to preview")
            return

        # Build a small preview by scaling to fit inside PREVIEW_SIZE
        try:
            png = imagemagick.load_any_image(self._source_path, max_dim=600)
            fx = self.values()["effects"]
            if any([fx.get("grayscale"), fx.get("sepia"),
                    fx.get("blur", 0), fx.get("sharpen", 0),
                    fx.get("brightness", 0), fx.get("contrast", 0),
                    fx.get("hue", 0)]):
                png = imagemagick.apply_effects(png, fx)
            img = QImage(png)
            if img.isNull():
                self.preview.setText("(could not render)")
                return
            pix = QPixmap.fromImage(img).scaled(PREVIEW_SIZE, Qt.KeepAspectRatio,
                                                Qt.SmoothTransformation)
            self.preview.setPixmap(pix)
        except Exception as e:
            self.preview.setText(f"(error)\n{e}")

    # ---------- click-to-edit ----------
    def _on_preview_clicked(self, _event):
        # Build the base image (source + current effects)
        if self._pixel_override is not None:
            base = self._pixel_override
        else:
            if not self._source_path:
                return
            try:
                png = imagemagick.load_any_image(self._source_path, max_dim=4000)
                fx = self.values()["effects"]
                if any([fx.get("grayscale"), fx.get("sepia"),
                        fx.get("blur", 0), fx.get("sharpen", 0),
                        fx.get("brightness", 0), fx.get("contrast", 0),
                        fx.get("hue", 0)]):
                    png = imagemagick.apply_effects(png, fx)
                base = QImage(png)
            except Exception:
                return

        if base.isNull():
            return

        dlg = SubImageEditor(base, self)
        if dlg.exec_() == dlg.Accepted:
            self._pixel_override = dlg.result_image()
            self._update_preview()

    # ---------- accept ----------
    def _on_accept(self):
        if not self._source_path:
            self.path_edit.setPlaceholderText("⚠ Please choose a file first")
            return
        self.accept()

    # ---------- values ----------
    def values(self) -> dict:
        return {
            "path": self._source_path,
            "pixel_override": self._pixel_override,
            "scale": self.scale_spin.value() / 100.0,
            "rotation": float(self.rotate_spin.value()),
            "effects": {
                "grayscale": self.grayscale.isChecked(),
                "sepia": self.sepia.isChecked(),
                "blur": self.blur_spin.value(),
                "sharpen": self.sharpen_spin.value(),
                "brightness": self.brightness_spin.value(),
                "contrast": self.contrast_spin.value(),
                "hue": self.hue_spin.value(),
            },
        }
