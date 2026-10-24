"""ShapeLayer — holds vector-ish objects (text, rectangles) that render on demand."""
from PyQt5.QtGui import QImage, QPainter, QColor, QFont, QPolygonF, QPen, QBrush
from PyQt5.QtCore import Qt, QPointF, QRectF


class ShapeObject:
    """Base — anything renderable at an (x, y) offset."""
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y

    def render(self, painter: QPainter): ...
    def translate(self, dx: float, dy: float):
        self.x += dx; self.y += dy
    def bounds(self) -> QRectF: ...


class TextShape(ShapeObject):
    def __init__(self, x, y, text, font: QFont, color: QColor,
                 glow_radius: int = 0, glow_color: QColor | None = None):
        super().__init__(x, y)
        self.text = text
        self.font = QFont(font)
        self.color = QColor(color)
        self.glow_radius = glow_radius
        self.glow_color = QColor(glow_color) if glow_color else None

    def _draw_content(self, painter: QPainter):
        painter.setFont(self.font)
        painter.setPen(self.color)
        if '\n' in self.text:
            # multi-line: draw using drawText with a bounding rect
            from PyQt5.QtGui import QFontMetricsF
            fm = QFontMetricsF(self.font)
            line_h = fm.height()
            lines = self.text.split('\n')
            for i, line in enumerate(lines):
                painter.drawText(int(self.x), int(self.y + i * line_h), line)
        else:
            painter.drawText(int(self.x), int(self.y), self.text)

    def _content_image(self) -> "QImage":
        """Rasterize just the text into a QImage for glow blurring."""
        from PyQt5.QtGui import QImage, QFontMetricsF
        fm = QFontMetricsF(self.font)
        w = max(1, int(fm.horizontalAdvance(self.text)) + 4)
        h = max(1, int(fm.height()) + 4)
        img = QImage(w, h, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.setFont(self.font)
        p.setPen(self.color)
        p.drawText(int(2), int(fm.ascent() + 2), self.text)
        p.end()
        return img

    def render(self, painter: QPainter):
        if self.glow_radius > 0 and self.glow_color is not None:
            from core.glow import blurred_silhouette
            content = self._content_image()
            halo = blurred_silhouette(content, self.glow_radius, self.glow_color)
            if not halo.isNull():
                margin = max(4, self.glow_radius * 2)
                from PyQt5.QtGui import QFontMetricsF
                fm = QFontMetricsF(self.font)
                base_x = self.x - 2 - margin
                base_y = self.y - fm.ascent() - 2 - margin
                painter.drawImage(int(base_x), int(base_y), halo)
        self._draw_content(painter)

    def bounds(self) -> QRectF:
        from PyQt5.QtGui import QFontMetricsF
        fm = QFontMetricsF(self.font)
        r = fm.boundingRect(self.text)
        return QRectF(self.x, self.y - r.height() + fm.descent(), r.width(), r.height())

    def to_dict(self):
        """Serialize for wire + persistence."""
        return {
            "type": "text",
            "x": self.x, "y": self.y,
            "text": self.text,
            "font": {
                "family": self.font.family(),
                "size": self.font.pointSize(),
                "bold": self.font.bold(),
                "italic": self.font.italic(),
            },
            "color": self.color.name(QColor.HexArgb),
            "glow_radius": self.glow_radius,
            "glow_color": self.glow_color.name(QColor.HexArgb)
                          if self.glow_color else None,
        }

    @classmethod
    def from_dict(cls, d, project_dir=None):
        from PyQt5.QtGui import QFont, QColor
        f = QFont(d["font"]["family"], d["font"]["size"])
        f.setBold(d["font"].get("bold", False))
        f.setItalic(d["font"].get("italic", False))
        gc = QColor(d["glow_color"]) if d.get("glow_color") else None
        return cls(d["x"], d["y"], d["text"], f, QColor(d["color"]),
                   d.get("glow_radius", 0), gc)


class ShapeLayer:
    """Layer backed by a list of ShapeObjects; pixels are regenerated on render."""
    def __init__(self, name: str, width: int, height: int):
        self.name = name
        self.visible = True
        self.opacity = 1.0
        self.width = width
        self.height = height
        self.shapes: list[ShapeObject] = []

    def add(self, shape: ShapeObject):
        self.shapes.append(shape)

    def render_to_image(self) -> QImage:
        img = QImage(self.width, self.height, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        for s in self.shapes:
            s.render(p)
        p.end()
        return img

    def translate_all(self, dx, dy):
        for s in self.shapes:
            s.translate(dx, dy)

    def hit_test(self, pt: QPointF) -> ShapeObject | None:
        for s in reversed(self.shapes):
            if s.bounds().contains(pt):
                return s
        return None

    # -- persistence --
    def to_dict(self, pixel_filename):
        from core.image_shape import ImageShape
        shapes = []
        for s in self.shapes:
            if isinstance(s, TextShape):
                shapes.append({
                    "type": "text",
                    "x": s.x, "y": s.y,
                    "text": s.text,
                    "font": {
                        "family": s.font.family(),
                        "size": s.font.pointSize(),
                        "bold": s.font.bold(),
                        "italic": s.font.italic(),
                    },
                    "color": s.color.name(QColor.HexArgb),
                    "glow_radius": s.glow_radius,
                    "glow_color": s.glow_color.name(QColor.HexArgb)
                                  if s.glow_color else None,
                })
            elif isinstance(s, ImageShape):
                shapes.append(s.to_dict())
            else:
                # rect / ellipse — they have to_dict
                try:
                    shapes.append(s.to_dict())
                except Exception:
                    pass
        return {"name": self.name, "visible": self.visible,
                "opacity": self.opacity, "kind": "shape",
                "pixels": pixel_filename, "shapes": shapes}

    @classmethod
    def from_dict(cls, data, project_dir, width, height):
        layer = cls(data["name"], width, height)
        layer.visible = data.get("visible", True)
        layer.opacity = data.get("opacity", 1.0)
        from core.image_shape import ImageShape
        for s in data.get("shapes", []):
            if s["type"] == "text3d":
                layer.add(Text3DShape.from_dict(s, project_dir))
            elif s["type"] == "text":
                f = QFont(s["font"]["family"], s["font"]["size"])
                f.setBold(s["font"].get("bold", False))
                f.setItalic(s["font"].get("italic", False))
                gc = QColor(s["glow_color"]) if s.get("glow_color") else None
                layer.add(TextShape(s["x"], s["y"], s["text"], f,
                                    QColor(s["color"]),
                                    s.get("glow_radius", 0), gc))
            elif s["type"] == "image":
                layer.add(ImageShape.from_dict(s, project_dir))
            elif s["type"] in ("rect", "ellipse"):
                from core.shape_objects import RectShape, EllipseShape
                klass = RectShape if s["type"] == "rect" else EllipseShape
                layer.add(klass.from_dict(s, project_dir))
        return layer

    def rasterize(self) -> "QImage":
        """Return this shape layer rendered to a QImage (for rasterize/erase)."""
        return self.render_to_image()


class Text3DShape(TextShape):
    """Text with 3D extrusion. Renders layered copies + shadow + highlight."""

    def __init__(self, x, y, text, font, color,
                 glow_radius=0, glow_color=None,
                 depth: int = 8,
                 extrusion_color: QColor | None = None,
                 light_angle: int = 45,
                 shadow_offset: int = 6):
        super().__init__(x, y, text, font, color, glow_radius, glow_color)
        self.depth = depth
        self.extrusion_color = QColor(extrusion_color) if extrusion_color else QColor(0, 0, 0)
        self.light_angle = light_angle
        self.shadow_offset = shadow_offset

    # ---- render helpers ----
    def _extrusion_vector(self):
        """Return (dx, dy) per depth step based on light angle."""
        import math
        rad = math.radians(self.light_angle)
        return -math.cos(rad), -math.sin(rad)

    def render(self, painter: QPainter):
        import math
        from PyQt5.QtGui import QFontMetricsF, QPen

        # glow first (if any)
        if self.glow_radius > 0 and self.glow_color is not None:
            try:
                from core.glow import blurred_silhouette
                content = self._content_image()
                halo = blurred_silhouette(content, self.glow_radius, self.glow_color)
                if not halo.isNull():
                    from PyQt5.QtGui import QFontMetricsF
                    fm = QFontMetricsF(self.font)
                    margin = max(4, self.glow_radius * 2)
                    base_x = self.x - 2 - margin
                    base_y = self.y - fm.ascent() - 2 - margin
                    painter.drawImage(int(base_x), int(base_y), halo)
            except Exception:
                pass

        dx_unit, dy_unit = self._extrusion_vector()

        # 1) drop shadow
        if self.shadow_offset > 0:
            shadow_color = QColor(0, 0, 0, 90)
            painter.save()
            painter.setFont(self.font)
            painter.setPen(shadow_color)
            ox = int(self.x + self.shadow_offset)
            oy = int(self.y + self.shadow_offset)
            lines = self.text.split("\n")
            fm = QFontMetricsF(self.font)
            line_h = fm.height()
            for i, line in enumerate(lines):
                painter.drawText(ox, oy + int(i * line_h), line)
            painter.restore()

        # 2) extrusion layers (back to front)
        extrusion_shade = QColor(self.extrusion_color)
        for step in range(self.depth, 0, -1):
            # darken further away
            shade = 0.4 + 0.6 * (1 - step / max(1, self.depth))
            c = QColor(
                int(extrusion_shade.red() * shade),
                int(extrusion_shade.green() * shade),
                int(extrusion_shade.blue() * shade),
                extrusion_shade.alpha(),
            )
            painter.save()
            painter.setFont(self.font)
            painter.setPen(c)
            ox = int(self.x + dx_unit * step)
            oy = int(self.y + dy_unit * step)
            lines = self.text.split("\n")
            fm = QFontMetricsF(self.font)
            line_h = fm.height()
            for i, line in enumerate(lines):
                painter.drawText(ox, oy + int(i * line_h), line)
            painter.restore()

        # 3) top face (front color)
        painter.save()
        painter.setFont(self.font)
        painter.setPen(self.color)
        lines = self.text.split("\n")
        fm = QFontMetricsF(self.font)
        line_h = fm.height()
        for i, line in enumerate(lines):
            painter.drawText(int(self.x), int(self.y + i * line_h), line)
        painter.restore()

    # ---- persistence ----
    def to_dict(self):
        d = super().to_dict()
        d.update({
            "type": "text3d",
            "depth": self.depth,
            "extrusion_color": self.extrusion_color.name(QColor.HexArgb),
            "light_angle": self.light_angle,
            "shadow_offset": self.shadow_offset,
        })
        return d

    @classmethod
    def from_dict(cls, d, project_dir=None):
        from PyQt5.QtGui import QFont, QColor
        f = QFont(d["font"]["family"], d["font"]["size"])
        f.setBold(d["font"].get("bold", False))
        f.setItalic(d["font"].get("italic", False))
        gc = QColor(d["glow_color"]) if d.get("glow_color") else None
        ec = QColor(d["extrusion_color"]) if d.get("extrusion_color") else None
        return cls(d["x"], d["y"], d["text"], f, QColor(d["color"]),
                   d.get("glow_radius", 0), gc,
                   d.get("depth", 8),
                   ec,
                   d.get("light_angle", 45),
                   d.get("shadow_offset", 6))

    def to_wire(self):
        return self.to_dict()

    @classmethod
    def from_wire(cls, d, project_dir=None):
        return cls.from_dict(d, project_dir)
