"""Modal sub-editor for image pixels — full toolbar, same UX as main window."""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QUndoStack,
    QSpinBox, QColorDialog, QWidget
)
from PyQt5.QtGui import QImage, QColor
from PyQt5.QtCore import Qt

from ui.color_picker import ColorPickerDialog
from ui._autosize import AutoSizeMixin


class SubImageEditor(QDialog, AutoSizeMixin):
    def __init__(self, source: QImage, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Image")
        self.resize(1000, 720)
        self._source = source

        # -------- deferred imports break the cycle --------
        from ui.canvas import (Canvas, TOOL_BRUSH, TOOL_PENCIL, TOOL_ERASER,
                               TOOL_LASSO, TOOL_BUCKET, TOOL_GRAB)
        from ui.canvas import (Canvas, TOOL_BRUSH, TOOL_PENCIL, TOOL_ERASER,
                               TOOL_LASSO, TOOL_BUCKET, TOOL_GRAB,
                               TOOL_BLUR, TOOL_PICKER, TOOL_3D_BRUSH)
        self._TOOLS = {
            "Grab":   TOOL_GRAB,
            "Brush":  TOOL_BRUSH,
            "Pencil": TOOL_PENCIL,
            "Eraser": TOOL_ERASER,
            "Lasso":  TOOL_LASSO,
            "Bucket": TOOL_BUCKET,
            "Blur":   TOOL_BLUR,
            "Picker": TOOL_PICKER,
            "3D Brush": TOOL_3D_BRUSH,
        }

        # -------- in-memory project --------
        from core.project import Project
        from core.layer import PixelLayer
        self.project = Project(name="__sub__", width=source.width(),
                               height=source.height(), background="transparent")
        layer = PixelLayer("Image", source.width(), source.height(),
                           fill="transparent")
        layer.image = source.convertToFormat(QImage.Format_ARGB32)
        self.project.layers = [layer]

        self.undo_stack = QUndoStack(self)
        self.canvas = Canvas(self.undo_stack)
        self.canvas.set_project(self.project)
        self.canvas.on_color_picked = lambda c: self._update_color_btn()

        # -------- top toolbar --------
        tool_bar = QHBoxLayout()
        self._tool_btns = {}
        for label, tool in self._TOOLS.items():
            b = QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, t=tool: self._set_tool(t))
            self._tool_btns[tool] = b
            tool_bar.addWidget(b)
        self._tool_btns[self._TOOLS["Brush"]].setChecked(True)

        tool_bar.addSpacing(12)

        # color swatch button
        self.color_btn = QPushButton("Color")
        self.color_btn.setFixedSize(90, 28)
        self.color_btn.clicked.connect(self._pick_color)
        self._update_color_btn()
        tool_bar.addWidget(self.color_btn)

        # size
        tool_bar.addWidget(QLabel("Size"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(1, 200)
        self.size_spin.setValue(self.canvas.brush_radius)
        self.size_spin.valueChanged.connect(
            lambda v: setattr(self.canvas, "brush_radius", v))
        tool_bar.addWidget(self.size_spin)

        # tolerance
        tool_bar.addWidget(QLabel("Tol"))
        self.tol_spin = QSpinBox()
        self.tol_spin.setRange(0, 255)
        self.tol_spin.setValue(self.canvas.fill_tolerance)
        self.tol_spin.valueChanged.connect(
            lambda v: setattr(self.canvas, "fill_tolerance", v))
        tool_bar.addWidget(self.tol_spin)

        tool_bar.addStretch()

        # undo/redo
        undo_btn = QPushButton("Undo"); undo_btn.clicked.connect(self.undo_stack.undo)
        redo_btn = QPushButton("Redo"); redo_btn.clicked.connect(self.undo_stack.redo)
        tool_bar.addWidget(undo_btn); tool_bar.addWidget(redo_btn)

        tool_bar.addSpacing(12)

        # done/cancel
        done_btn = QPushButton("Done"); done_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel"); cancel_btn.clicked.connect(self.reject)
        tool_bar.addWidget(done_btn); tool_bar.addWidget(cancel_btn)

        # ---------- Image-ops bar ----------
        ops_bar = QHBoxLayout()
        ops_bar.addWidget(QLabel("Whole image:"))
        for label, fn in (
            ("Grayscale", lambda: self._op_simple("grayscale")),
            ("Sepia",     lambda: self._op_simple("sepia")),
            ("Hue…",      self._op_hue),
            ("Blur…",     self._op_blur),
            ("Remove BG", self._op_remove_bg),
        ):
            b = QPushButton(label)
            b.clicked.connect(fn)
            ops_bar.addWidget(b)
        ops_bar.addStretch()

        from PyQt5.QtWidgets import QScrollArea, QFrame
        tool_row_widget = QWidget(); tool_row_widget.setLayout(tool_bar)
        tool_scroll = QScrollArea(); tool_scroll.setWidgetResizable(True)
        tool_scroll.setFrameShape(QFrame.NoFrame)
        tool_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        tool_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tool_scroll.setFixedHeight(64)
        tool_scroll.setWidget(tool_row_widget)

        ops_row_widget = QWidget(); ops_row_widget.setLayout(ops_bar)
        ops_scroll = QScrollArea(); ops_scroll.setWidgetResizable(True)
        ops_scroll.setFrameShape(QFrame.NoFrame)
        ops_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        ops_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ops_scroll.setFixedHeight(44)
        ops_scroll.setWidget(ops_row_widget)

        v = QVBoxLayout(self)
        v.addWidget(tool_scroll)
        v.addWidget(ops_scroll)
        v.addWidget(self.canvas, 1)

        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, lambda: self.auto_size(min_w=900, min_h=560))

    def _set_tool(self, tool):
        self.canvas.set_tool(tool)
        for t, b in self._tool_btns.items():
            b.setChecked(t == tool)

    def _pick_color(self):
        dlg = ColorPickerDialog(self.canvas.brush_color, self)
        if dlg.exec_() == dlg.Accepted:
            self.canvas.brush_color = dlg.color()
            self._update_color_btn()

    def _update_color_btn(self):
        c = self.canvas.brush_color
        self.color_btn.setStyleSheet(
            f"background-color:{c.name()};"
            f"color:{'white' if c.lightness() < 128 else 'black'};"
        )
        self.color_btn.setText(f"{c.name()} a={c.alpha()}")

    def _layer(self):
        return self.project.layers[0]

    def _swap_image(self, new_img, label="Effect"):
        from core.commands import FillCommand
        layer = self._layer()
        before = layer.clone_image()
        layer.image = new_img
        self.undo_stack.push(FillCommand(layer, before, new_img,
                                         on_change=self.canvas.refresh,
                                         text=label))
        self.canvas.refresh()

    def _op_simple(self, kind: str):
        from core import image_ops
        layer = self._layer()
        if kind == "grayscale":
            self._swap_image(image_ops.grayscale(layer.image), "Grayscale")
        elif kind == "sepia":
            self._swap_image(image_ops.sepia(layer.image), "Sepia")

    def _op_hue(self):
        from PyQt5.QtWidgets import QInputDialog
        from core import image_ops
        v, ok = QInputDialog.getInt(self, "Hue Shift", "Degrees (-180..180):",
                                    0, -180, 180)
        if not ok:
            return
        self._swap_image(image_ops.hue_shift(self._layer().image, v), "Hue Shift")

    def _op_blur(self):
        from PyQt5.QtWidgets import QInputDialog
        from core import image_ops
        v, ok = QInputDialog.getInt(self, "Blur", "Radius (px):", 3, 0, 40)
        if not ok:
            return
        self._swap_image(image_ops.blur(self._layer().image, v), "Blur")

    def _op_remove_bg(self):
        from core import image_ops
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import Qt
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._swap_image(image_ops.remove_background(self._layer().image),
                             "Remove Background")
        finally:
            QApplication.restoreOverrideCursor()

    def result_image(self) -> QImage:
        return self.project.layers[0].image.copy()
