"""Shape Properties — edit fill, gradient, stroke, position, size."""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QCheckBox, QPushButton, QSpinBox, QComboBox, QLabel,
    QDialogButtonBox, QColorDialog, QWidget, QScrollArea, QFrame
)
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt, QTimer
from ui._autosize import AutoSizeMixin
from ui.color_picker import ColorPickerDialog


class ShapePropertiesDialog(QDialog, AutoSizeMixin):
    def __init__(self, shape, parent=None):
        super().__init__(parent)
        self.shape = shape
        self.setWindowTitle(f"Shape Properties — {type(shape).__name__}")

        # ---- position / size ----
        self.x_spin = QSpinBox(); self.x_spin.setRange(-10000, 10000); self.x_spin.setValue(int(shape.x))
        self.y_spin = QSpinBox(); self.y_spin.setRange(-10000, 10000); self.y_spin.setValue(int(shape.y))
        self.w_spin = QSpinBox(); self.w_spin.setRange(1, 10000); self.w_spin.setValue(int(getattr(shape, 'w', 100)))
        self.h_spin = QSpinBox(); self.h_spin.setRange(1, 10000); self.h_spin.setValue(int(getattr(shape, 'h', 100)))
        geo = QGroupBox("Position && Size")
        gf = QFormLayout(geo)
        gf.addRow("X:", self.x_spin)
        gf.addRow("Y:", self.y_spin)
        gf.addRow("Width:", self.w_spin)
        gf.addRow("Height:", self.h_spin)

        # ---- fill (solid) ----
        self.fill_check = QCheckBox("Solid fill")
        self.fill_check.setChecked(shape.fill is not None)
        self.fill_btn = QPushButton("Color…")
        self._fill_color = QColor(shape.fill) if shape.fill else QColor("#808080")
        self.fill_btn.clicked.connect(self._pick_fill)
        self._update_fill_btn()
        fill_row = QHBoxLayout()
        fill_row.addWidget(self.fill_check)
        fill_row.addWidget(self.fill_btn)
        fill_row.addStretch()
        fill_wrap = QWidget(); fill_wrap.setLayout(fill_row)

        # ---- gradient ----
        grad = getattr(shape, "gradient", {}) or {}
        self.grad_check = QCheckBox("Gradient fill")
        self.grad_check.setChecked(bool(grad.get("enabled")))
        self._c1 = QColor(grad.get("c1", "#ffffff"))
        self._c2 = QColor(grad.get("c2", "#000000"))
        self.c1_btn = QPushButton("Start color…"); self.c1_btn.clicked.connect(lambda: self._pick_grad("c1"))
        self.c2_btn = QPushButton("End color…");   self.c2_btn.clicked.connect(lambda: self._pick_grad("c2"))
        self.angle_spin = QSpinBox(); self.angle_spin.setRange(0, 359); self.angle_spin.setValue(int(grad.get("angle", 0)))
        self.angle_spin.setSuffix("°")
        self._update_grad_btns()

        grad_box = QGroupBox("Gradient")
        gform = QFormLayout(grad_box)
        gform.addRow(self.grad_check)
        gform.addRow(self.c1_btn)
        gform.addRow(self.c2_btn)
        gform.addRow("Angle:", self.angle_spin)

        # ---- stroke ----
        self.stroke_check = QCheckBox("Stroke")
        self.stroke_check.setChecked(shape.stroke is not None)
        self.stroke_btn = QPushButton("Color…")
        self._stroke_color = QColor(shape.stroke) if shape.stroke else QColor("#000000")
        self.stroke_btn.clicked.connect(self._pick_stroke)
        self._update_stroke_btn()
        self.stroke_w_spin = QSpinBox(); self.stroke_w_spin.setRange(0, 100)
        self.stroke_w_spin.setValue(getattr(shape, "stroke_width", 2))

        stroke_box = QGroupBox("Stroke")
        sform = QFormLayout(stroke_box)
        srow = QHBoxLayout()
        srow.addWidget(self.stroke_check); srow.addWidget(self.stroke_btn); srow.addStretch()
        sw = QWidget(); sw.setLayout(srow)
        sform.addRow(sw)
        sform.addRow("Width:", self.stroke_w_spin)

        # ---- main layout ----
        body = QWidget()
        v = QVBoxLayout(body)
        v.addWidget(geo)
        v.addWidget(fill_wrap)
        v.addWidget(grad_box)
        v.addWidget(stroke_box)
        v.addStretch()

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(body)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        outer = QVBoxLayout(self)
        outer.addWidget(scroll, 1)
        outer.addWidget(buttons)

        QTimer.singleShot(0, lambda: self.auto_size(min_w=420, min_h=460))

    # ---- pickers ----
    def _pick_fill(self):
        c = self._pick(self._fill_color)
        if c is not None:
            self._fill_color = c
            self._update_fill_btn()

    def _pick_stroke(self):
        c = self._pick(self._stroke_color)
        if c is not None:
            self._stroke_color = c
            self._update_stroke_btn()

    def _pick_grad(self, which):
        cur = self._c1 if which == "c1" else self._c2
        c = self._pick(cur)
        if c is None:
            return
        if which == "c1":
            self._c1 = c
        else:
            self._c2 = c
        self._update_grad_btns()

    def _pick(self, initial):
        dlg = ColorPickerDialog(initial, self)
        if dlg.exec_() == dlg.Accepted:
            return dlg.color()
        return None

    def _update_fill_btn(self):
        c = self._fill_color
        self.fill_btn.setStyleSheet(
            f"background-color:{c.name()};"
            f"color:{'white' if c.lightness() < 128 else 'black'};"
        )
        self.fill_btn.setText(c.name())

    def _update_stroke_btn(self):
        c = self._stroke_color
        self.stroke_btn.setStyleSheet(
            f"background-color:{c.name()};"
            f"color:{'white' if c.lightness() < 128 else 'black'};"
        )
        self.stroke_btn.setText(c.name())

    def _update_grad_btns(self):
        for btn, c in ((self.c1_btn, self._c1), (self.c2_btn, self._c2)):
            btn.setStyleSheet(
                f"background-color:{c.name()};"
                f"color:{'white' if c.lightness() < 128 else 'black'};"
            )
            btn.setText(c.name())

    # ---- apply ----
    def apply_to_shape(self):
        from core.commands import EditShapeCommand
        from core.shape_objects import RectShape, EllipseShape

        s = self.shape
        fill = self._fill_color if self.fill_check.isChecked() else None
        stroke = self._stroke_color if self.stroke_check.isChecked() else None
        gradient = {
            "enabled": self.grad_check.isChecked(),
            "c1": self._c1.name(),
            "c2": self._c2.name(),
            "angle": self.angle_spin.value(),
        }
        # rebuild shape with new values
        if isinstance(s, RectShape):
            new = RectShape(self.x_spin.value(), self.y_spin.value(),
                            self.w_spin.value(), self.h_spin.value(),
                            fill, stroke, self.stroke_w_spin.value(), gradient)
        elif isinstance(s, EllipseShape):
            new = EllipseShape(self.x_spin.value(), self.y_spin.value(),
                               self.w_spin.value(), self.h_spin.value(),
                               fill, stroke, self.stroke_w_spin.value(), gradient)
        else:
            return None
        return new
