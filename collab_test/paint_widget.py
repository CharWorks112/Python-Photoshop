"""Minimal shared paint surface — one QImage, brush + eraser, cursor overlay."""
from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QPainter, QImage, QColor, QPen, QBrush, QPolygonF
from PyQt5.QtCore import Qt, QPoint, QPointF, pyqtSignal
import time


class PaintWidget(QWidget):
    """Shared canvas. Emits strokeReady after each mouse release
    (host + client both emit; network layer decides who forwards to whom)."""
    strokeReady = pyqtSignal(QImage)         # full layer snapshot
    cursorMoved = pyqtSignal(int, int)       # local cursor position

    CANVAS_W = 900
    CANVAS_H = 600

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(self.CANVAS_W, self.CANVAS_H)
        self.image = QImage(self.CANVAS_W, self.CANVAS_H, QImage.Format_ARGB32)
        self.image.fill(QColor("white"))

        self.brush_color = QColor("black")
        self.brush_radius = 6
        self.eraser = False

        # stroke state
        self._drawing = False
        self._last: QPoint | None = None
        self._has_changes = False

        # remote cursors: name -> (x, y, color, last_seen)
        self._remote_cursors: dict[str, tuple] = {}

        self._last_emit = 0.0
        self.setMouseTracking(True)

    # ---------------- painting ----------------
    def _dab(self, pt: QPoint):
        p = QPainter(self.image)
        p.setRenderHint(QPainter.Antialiasing, True)
        if self.eraser:
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.setBrush(Qt.transparent)
        else:
            p.setBrush(self.brush_color)
        p.setPen(Qt.NoPen)
        r = self.brush_radius
        p.drawEllipse(pt.x() - r, pt.y() - r, r * 2, r * 2)
        p.end()
        self._has_changes = True

    def _stroke_segment(self, a: QPoint, b: QPoint):
        dx, dy = b.x() - a.x(), b.y() - a.y()
        dist = (dx * dx + dy * dy) ** 0.5
        steps = max(1, int(dist / max(1, self.brush_radius // 2)))
        for i in range(steps + 1):
            t = i / steps
            self._dab(QPoint(int(a.x() + dx * t), int(a.y() + dy * t)))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drawing = True
            self._last = e.pos()
            self._dab(self._last)
            self.update()

    def mouseMoveEvent(self, e):
        # always emit cursor
        self.cursorMoved.emit(e.pos().x(), e.pos().y())
        if self._drawing and self._last is not None:
            self._stroke_segment(self._last, e.pos())
            self._last = e.pos()
            self.update()

    def mouseReleaseEvent(self, e):
        if self._drawing:
            self._drawing = False
            self._last = None
            if self._has_changes:
                self._has_changes = False
                self.strokeReady.emit(self.image.copy())
            self.update()

    # ---------------- external updates ----------------
    def apply_remote_image(self, img: QImage):
        """Called when we receive a snapshot from the peer."""
        if img.size() != self.image.size():
            img = img.scaled(self.image.size(), Qt.IgnoreAspectRatio,
                             Qt.SmoothTransformation)
        self.image = img.convertToFormat(QImage.Format_ARGB32)
        self.update()

    def set_remote_cursor(self, name: str, x: int, y: int, color: str | None = None):
        c = QColor(color) if color else QColor("#ff4040")
        self._remote_cursors[name] = (x, y, c, time.time())
        self.update()

    def clear_remote_cursor(self, name: str):
        self._remote_cursors.pop(name, None)
        self.update()

    # ---------------- paint ----------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.drawImage(0, 0, self.image)

        # remote cursors
        now = time.time()
        for name, (x, y, color, ts) in list(self._remote_cursors.items()):
            if now - ts > 5.0:   # hide stale cursors after 5s
                continue
            p.setBrush(QBrush(color))
            p.setPen(QPen(QColor(0, 0, 0, 180), 1))
            poly = QPolygonF([
                QPointF(x, y),
                QPointF(x + 12, y + 4),
                QPointF(x + 6, y + 6),
                QPointF(x + 8, y + 12),
            ])
            p.drawPolygon(poly)
            p.setPen(QPen(QColor("white"), 1))
            p.drawText(x + 14, y + 12, name)
