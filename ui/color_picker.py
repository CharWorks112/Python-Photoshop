"""Modern color picker — SV square + hue strip + alpha strip + hex field."""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QDialogButtonBox, QPushButton, QWidget, QColorDialog,
    QSizePolicy, QSpinBox, QFormLayout
)
from PyQt5.QtGui import (
    QColor, QPainter, QPixmap, QLinearGradient, QBrush, QPen,
    QImage, QPolygon, QRegion, QIntValidator
)
from PyQt5.QtCore import Qt, QPoint, QRect, pyqtSignal, QSize, QTimer
from ui._autosize import AutoSizeMixin


# ---------------------------------------------------------------- helpers
def _checker_pixmap(w: int, h: int, cell: int = 8) -> QPixmap:
    pm = QPixmap(w, h)
    p = QPainter(pm)
    p.fillRect(0, 0, w, h, QColor("#bbb"))
    p.setBrush(QColor("#666"))
    p.setPen(Qt.NoPen)
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            if ((x // cell) + (y // cell)) % 2 == 0:
                p.drawRect(x, y, cell, cell)
    p.end()
    return pm


# ---------------------------------------------------------------- widgets
class SVSquare(QWidget):
    """The big 2D saturation/value picker."""
    changed = pyqtSignal(int, int)   # sat, val (0..255)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(220, 220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._hue = 0
        self._sat = 0
        self._val = 255
        self._bg: QPixmap | None = None
        self._bg_size = QSize(0, 0)

    def set_hue(self, hue: int):
        self._hue = max(0, min(359, hue))
        self._bg = None
        self.update()

    def set_color(self, sat: int, val: int):
        self._sat = max(0, min(255, sat))
        self._val = max(0, min(255, val))
        self.update()

    def _rebuild_bg(self):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        img = QImage(w, h, QImage.Format_ARGB32)
        base = QColor.fromHsv(self._hue, 255, 255).rgb()
        # draw row by row for accuracy
        for y in range(h):
            v = int(255 * (1 - y / max(1, h - 1)))
            for_x_row = None
            for x in range(w):
                s = int(255 * (x / max(1, w - 1)))
                img.setPixelColor(x, y, QColor.fromHsv(self._hue, s, v))
        self._bg = QPixmap.fromImage(img)
        self._bg_size = QSize(w, h)

    def paintEvent(self, _):
        if self._bg is None or self._bg_size != self.size():
            self._rebuild_bg()
        p = QPainter(self)
        p.drawPixmap(0, 0, self._bg)
        # crosshair
        w, h = self.width(), self.height()
        cx = int(self._sat / 255 * (w - 1))
        cy = int((1 - self._val / 255) * (h - 1))
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 200), 2))
        p.drawEllipse(QPoint(cx, cy), 6, 6)
        p.setPen(QPen(QColor(255, 255, 255, 220), 1))
        p.drawEllipse(QPoint(cx, cy), 7, 7)
        p.end()

    def mousePressEvent(self, e):
        self._pick(e.pos())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._pick(e.pos())

    def _pick(self, pos: QPoint):
        w, h = max(1, self.width() - 1), max(1, self.height() - 1)
        self._sat = max(0, min(255, int(pos.x() / w * 255)))
        self._val = max(0, min(255, int((1 - pos.y() / h) * 255)))
        self.changed.emit(self._sat, self._val)
        self.update()


class HueStrip(QWidget):
    changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(24)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._hue = 0

    def set_hue(self, h: int):
        self._hue = max(0, min(359, h))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        grad = QLinearGradient(0, 0, 0, self.height())
        for i in range(7):
            grad.setColorAt(i / 6, QColor.fromHsv(int(i / 6 * 359), 255, 255))
        p.fillRect(self.rect(), grad)
        y = int(self._hue / 359 * (self.height() - 1))
        p.setPen(QPen(Qt.white, 2)); p.drawLine(0, y, self.width(), y)
        p.setPen(QPen(Qt.black, 1)); p.drawLine(0, y + 1, self.width(), y + 1)
        p.end()

    def mousePressEvent(self, e):
        self._pick(e.pos())
    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._pick(e.pos())

    def _pick(self, pos: QPoint):
        self._hue = max(0, min(359, int(pos.y() / max(1, self.height() - 1) * 359)))
        self.changed.emit(self._hue)
        self.update()


class AlphaStrip(QWidget):
    changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._color = QColor("red")
        self._alpha = 255

    def set_color(self, c: QColor):
        self._color = QColor(c); self.update()

    def set_alpha(self, a: int):
        self._alpha = max(0, min(255, a)); self.update()

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        self.setStyleSheet("")  # no-op
        p = QPainter(self)
        p.drawPixmap(0, 0, _checker_pixmap(w, h, 8))
        grad = QLinearGradient(0, 0, w, 0)
        c0 = QColor(self._color); c0.setAlpha(0)
        c1 = QColor(self._color); c1.setAlpha(255)
        grad.setColorAt(0, c0); grad.setColorAt(1, c1)
        p.fillRect(self.rect(), grad)
        x = int(self._alpha / 255 * (w - 1))
        p.setPen(QPen(Qt.white, 2)); p.drawLine(x, 0, x, h)
        p.setPen(QPen(Qt.black, 1)); p.drawLine(x + 1, 0, x + 1, h)
        p.end()

    def mousePressEvent(self, e):
        self._pick(e.pos())
    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._pick(e.pos())

    def _pick(self, pos: QPoint):
        self._alpha = max(0, min(255, int(pos.x() / max(1, self.width() - 1) * 255)))
        self.changed.emit(self._alpha)
        self.update()


class Swatch(QWidget):
    """Preview swatch that draws a checker + current color."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self._color = QColor("black")

    def set_color(self, c: QColor):
        self._color = QColor(c); self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.drawPixmap(0, 0, _checker_pixmap(self.width(), self.height(), 8))
        p.fillRect(self.rect(), self._color)
        p.setPen(QColor("#555")); p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.end()


# ---------------------------------------------------------------- dialog
class ColorPickerDialog(QDialog, AutoSizeMixin):
    """Full picker: SV square + hue + alpha + hex + RGBA spinboxes."""
    def __init__(self, initial: QColor | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Color")
        self.setMinimumSize(380, 420)
        self._color = QColor(initial or QColor("black"))
        if not self._color.isValid():
            self._color = QColor("black")

        # ---- widgets ----
        self.sv = SVSquare()
        self.hue = HueStrip()
        self.alpha = AlphaStrip()
        self.swatch = Swatch()

        self.hex_edit = QLineEdit()
        self.hex_edit.setMaxLength(9)      # #RRGGBBAA
        self.hex_edit.setPlaceholderText("#RRGGBB or #RRGGBBAA")
        self.hex_edit.setStyleSheet("font-family: monospace; font-size: 14px;")
        self.hex_edit.editingFinished.connect(self._on_hex_entered)

        self.spins = {}
        for key in ("R", "G", "B", "A"):
            sp = QSpinBox()
            sp.setRange(0, 255)
            sp.valueChanged.connect(self._on_spin_changed)
            self.spins[key] = sp

        native_btn = QPushButton("System Picker…")
        native_btn.clicked.connect(self._open_native)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        # ---- layout ----
        top = QHBoxLayout()
        top.addWidget(self.sv, 1)
        top.addWidget(self.hue)

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(QLabel("A"))
        bottom_row.addWidget(self.alpha, 1)

        grid = QGridLayout()
        grid.addWidget(QLabel("Hex"), 0, 0)
        grid.addWidget(self.hex_edit, 0, 1, 1, 3)
        for i, key in enumerate(("R", "G", "B", "A")):
            grid.addWidget(QLabel(key), 1, i)
            grid.addWidget(self.spins[key], 2, i)

        v = QVBoxLayout(self)
        v.addLayout(top, 1)
        v.addLayout(bottom_row)
        v.addWidget(self.swatch)
        v.addLayout(grid)
        btn_row = QHBoxLayout()
        btn_row.addWidget(native_btn)
        btn_row.addWidget(buttons)
        v.addLayout(btn_row)

        # ---- wire signals ----
        self.sv.changed.connect(self._on_sv_changed)
        self.hue.changed.connect(self._on_hue_changed)
        self.alpha.changed.connect(self._on_alpha_changed)

        self._load_from_color(self._color)
        QTimer.singleShot(0, lambda: self.auto_size(min_w=400, min_h=460))

    # ---- setters ----
    def _load_from_color(self, c: QColor):
        """Set all widgets from `c` without feedback loops."""
        h, s, v, a = c.hue(), c.saturation(), c.value(), c.alpha()
        if h < 0:
            h = 0
        for w in (self.sv, self.hue, self.alpha, self.swatch):
            w.blockSignals(True)
        for sp in self.spins.values():
            sp.blockSignals(True)
        self.hex_edit.blockSignals(True)

        self.sv.set_hue(h); self.sv.set_color(s, v)
        self.hue.set_hue(h)
        self.alpha.set_color(c); self.alpha.set_alpha(a)
        self.swatch.set_color(c)

        self.spins["R"].setValue(c.red())
        self.spins["G"].setValue(c.green())
        self.spins["B"].setValue(c.blue())
        self.spins["A"].setValue(a)
        self.hex_edit.setText(c.name(QColor.HexArgb).upper().replace("0X", "#"))

        for w in (self.sv, self.hue, self.alpha, self.swatch):
            w.blockSignals(False)
        for sp in self.spins.values():
            sp.blockSignals(False)
        self.hex_edit.blockSignals(False)

        self._color = QColor(c)

    def _sync_from_hsva(self):
        c = QColor.fromHsv(self.hue._hue, self.sv._sat, self.sv._val, self.alpha._alpha)
        self._color = c
        # update swatch, alpha gradient, spins, hex — all silently
        for w in (self.swatch, self.alpha):
            w.blockSignals(True)
        for sp in self.spins.values():
            sp.blockSignals(True)
        self.hex_edit.blockSignals(True)

        self.swatch.set_color(c)
        self.alpha.set_color(QColor.fromHsv(self.hue._hue, self.sv._sat, self.sv._val, 255))
        self.spins["R"].setValue(c.red())
        self.spins["G"].setValue(c.green())
        self.spins["B"].setValue(c.blue())
        self.spins["A"].setValue(c.alpha())
        self.hex_edit.setText(c.name(QColor.HexArgb).upper().replace("0X", "#"))

        for w in (self.swatch, self.alpha):
            w.blockSignals(False)
        for sp in self.spins.values():
            sp.blockSignals(False)
        self.hex_edit.blockSignals(False)

    # ---- handlers ----
    def _on_hue_changed(self, h: int):
        self.sv.set_hue(h)
        self._sync_from_hsva()

    def _on_sv_changed(self, s: int, v: int):
        self._sync_from_hsva()

    def _on_alpha_changed(self, a: int):
        self._sync_from_hsva()

    def _on_spin_changed(self, *_):
        c = QColor(self.spins["R"].value(), self.spins["G"].value(),
                   self.spins["B"].value(), self.spins["A"].value())
        self._load_from_color(c)

    def _on_hex_entered(self):
        text = self.hex_edit.text().strip()
        if not text.startswith("#"):
            text = "#" + text
        # pad to 7 or 9 chars
        if len(text) == 4:                      # #RGB
            text = "#" + "".join(ch * 2 for ch in text[1:])
        if len(text) == 7:                      # #RRGGBB
            pass
        elif len(text) == 9:                    # #RRGGBBAA
            pass
        else:
            # restore old
            self.hex_edit.setText(self._color.name(QColor.HexArgb).upper().replace("0X", "#"))
            return
        c = QColor(text)
        if not c.isValid():
            self.hex_edit.setText(self._color.name(QColor.HexArgb).upper().replace("0X", "#"))
            return
        self._load_from_color(c)

    def _open_native(self):
        c = QColorDialog.getColor(self._color, self, "Pick Color",
                                  QColorDialog.ShowAlphaChannel)
        if c.isValid():
            self._load_from_color(c)

    def color(self) -> QColor:
        return self._color
