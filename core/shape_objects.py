"""Geometric shape objects (rect, ellipse) with solid OR gradient fill, editable stroke."""
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient
)
from PyQt5.QtCore import Qt, QRectF, QPointF
from core.shape_layer import ShapeObject


def _brush_for_shape(shape) -> "QBrush":
    """Build a QBrush honoring gradient settings, or a solid color."""
    grad = getattr(shape, "gradient", None)
    if grad and grad.get("enabled"):
        c1 = QColor(grad.get("c1", "#ffffff"))
        c2 = QColor(grad.get("c2", "#000000"))
        angle = grad.get("angle", 0)  # degrees
        rect = QRectF(shape.x, shape.y, shape.w, shape.h)
        # map angle → start/end points along rect
        import math
        rad = math.radians(angle)
        cx, cy = rect.center().x(), rect.center().y()
        half = max(rect.width(), rect.height()) / 2
        dx = math.cos(rad) * half
        dy = math.sin(rad) * half
        lg = QLinearGradient(cx - dx, cy - dy, cx + dx, cy + dy)
        lg.setColorAt(0.0, c1)
        lg.setColorAt(1.0, c2)
        return QBrush(lg)
    if getattr(shape, "fill", None) is not None:
        return QBrush(QColor(shape.fill))
    return QBrush(Qt.NoBrush)


class _BaseShape(ShapeObject):
    """Shared code for rect / ellipse — fill + stroke + gradient + resize."""
    def __init__(self, x, y, w, h, fill, stroke, stroke_width=2,
                 gradient: dict | None = None):
        super().__init__(x, y)
        self.w, self.h = w, h
        self.fill = QColor(fill) if fill else None
        self.stroke = QColor(stroke) if stroke else None
        self.stroke_width = stroke_width
        self.gradient = gradient or {}

    def set_bounds(self, x: float, y: float, w: float, h: float):
        self.x = x; self.y = y
        self.w = max(1.0, w); self.h = max(1.0, h)

    def bounds(self) -> QRectF:
        return QRectF(self.x, self.y, self.w, self.h)

    def _apply_pen_brush(self, p: QPainter):
        p.setBrush(_brush_for_shape(self))
        if self.stroke is not None and self.stroke_width > 0:
            p.setPen(QPen(self.stroke, self.stroke_width))
        else:
            p.setPen(Qt.NoPen)

    def to_dict(self):
        return {
            "x": self.x, "y": self.y, "w": self.w, "h": self.h,
            "fill": self.fill.name(QColor.HexArgb) if self.fill else None,
            "stroke": self.stroke.name(QColor.HexArgb) if self.stroke else None,
            "stroke_width": self.stroke_width,
            "gradient": self.gradient,
        }

    @classmethod
    def _parse_common(cls, d):
        fill = QColor(d["fill"]) if d.get("fill") else None
        stroke = QColor(d["stroke"]) if d.get("stroke") else None
        return dict(
            x=d["x"], y=d["y"], w=d["w"], h=d["h"],
            fill=fill, stroke=stroke,
            stroke_width=d.get("stroke_width", 2),
            gradient=d.get("gradient", {}),
        )


class RectShape(_BaseShape):
    def render(self, p: QPainter):
        p.save()
        self._apply_pen_brush(p)
        p.drawRect(QRectF(self.x, self.y, self.w, self.h))
        p.restore()

    def to_dict(self):
        d = super().to_dict(); d["type"] = "rect"; return d

    @classmethod
    def from_dict(cls, d, project_dir):
        return cls(**cls._parse_common(d))


class EllipseShape(_BaseShape):
    def render(self, p: QPainter):
        p.save()
        self._apply_pen_brush(p)
        p.drawEllipse(QRectF(self.x, self.y, self.w, self.h))
        p.restore()

    def to_dict(self):
        d = super().to_dict(); d["type"] = "ellipse"; return d

    @classmethod
    def from_dict(cls, d, project_dir):
        return cls(**cls._parse_common(d))
