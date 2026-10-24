"""ImageShape — image on a shape layer. Effects are stored (not baked)
so they can be edited via double-click later."""
from PyQt5.QtGui import QImage, QPainter, QColor, QRadialGradient, QBrush
from PyQt5.QtCore import Qt, QRectF
from pathlib import Path
import tempfile

from core.shape_layer import ShapeObject
from core import imagemagick


class ImageShape(ShapeObject):
    def __init__(self, x: float, y: float, source_path: str,
                 scale: float = 1.0, rotation: float = 0.0,
                 effects: dict | None = None,
                 pixel_override: QImage | None = None,
                 glow_radius: int = 0,
                 glow_color: QColor | None = None):
        super().__init__(x, y)
        self.source_path = source_path
        self.scale = scale
        self.rotation = rotation
        self.effects = dict(effects or {})
        # Optional baked-in pixels from the sub-editor; if present,
        # these *replace* the (source + effects) pipeline.
        self.pixel_override = pixel_override
        self.glow_radius = glow_radius
        self.glow_color = QColor(glow_color) if glow_color else None
        self._cached_image: QImage | None = None
        self._cache_key = None

    # ---------- image pipeline ----------
    def _build_image(self) -> QImage:
        # cache key includes override identity so edits invalidate naturally
        key = (
            self.source_path,
            tuple(sorted(self.effects.items())),
            id(self.pixel_override) if self.pixel_override is not None else None,
        )
        if self._cache_key == key and self._cached_image is not None:
            return self._cached_image

        try:
            fx = self.effects
            has_effects = any([
                fx.get("grayscale"), fx.get("sepia"),
                fx.get("blur", 0), fx.get("sharpen", 0),
                fx.get("brightness", 0), fx.get("contrast", 0),
                fx.get("hue", 0),
            ])

            if self.pixel_override is not None:
                # Edited pixels are the "source". If effects exist,
                # write to a temp PNG and pipe through ImageMagick.
                if not has_effects:
                    img = self.pixel_override
                else:
                    import tempfile
                    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
                    if not self.pixel_override.save(tmp, "PNG"):
                        raise IOError(f"Could not write override to {tmp}")
                    png = imagemagick.apply_effects(tmp, fx)
                    img = QImage(png)
            else:
                png = imagemagick.load_any_image(self.source_path)
                if has_effects:
                    png = imagemagick.apply_effects(png, fx)
                img = QImage(png)
        except Exception:
            img = QImage()

        self._cached_image = img
        self._cache_key = key
        return img

    @property
    def image(self) -> QImage:
        return self._build_image()

    def invalidate_cache(self):
        self._cache_key = None
        self._cached_image = None

    # ---------- render ----------
    def rendered_size(self):
        img = self.image
        return (img.width() * self.scale, img.height() * self.scale)

    def render(self, painter: QPainter):
        img = self.image
        if img.isNull():
            return

        w, h = self.rendered_size()
        scaled = img.scaled(int(w), int(h),
                            Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

        painter.save()
        painter.translate(self.x, self.y)
        if self.rotation:
            painter.rotate(self.rotation)

        if self.glow_radius > 0 and self.glow_color is not None:
            from core.glow import blurred_silhouette
            halo = blurred_silhouette(scaled, self.glow_radius, self.glow_color)
            if not halo.isNull():
                margin = max(4, self.glow_radius * 2)
                painter.drawImage(-margin, -margin, halo)

        painter.drawImage(0, 0, scaled)
        painter.restore()

    def bounds(self) -> QRectF:
        w, h = self.rendered_size()
        return QRectF(self.x, self.y, w, h)

    # ---------- persistence ----------
    def to_dict(self):
        return {
            "type": "image",
            "x": self.x, "y": self.y,
            "source": self.source_path,
            "scale": self.scale,
            "rotation": self.rotation,
            "effects": self.effects,
            "glow_radius": self.glow_radius,
            "glow_color": self.glow_color.name(QColor.HexArgb)
                          if self.glow_color else None,
        }

    @classmethod
    def from_dict(cls, data, project_dir: Path):
        path = Path(data.get("source", ""))
        if not path.is_absolute():
            path = project_dir / path
        gc = QColor(data["glow_color"]) if data.get("glow_color") else None
        return cls(data["x"], data["y"], str(path),
                   data.get("scale", 1.0), data.get("rotation", 0.0),
                   data.get("effects", {}),
                   pixel_override=None,
                   glow_radius=data.get("glow_radius", 0),
                   glow_color=gc)

    def to_wire(self) -> dict:
        """Like to_dict but embeds the current rendered pixels as base64 PNG,
        so peers don't need the original source file."""
        import base64
        from PyQt5.QtCore import QBuffer, QIODevice
        d = self.to_dict()
        img = self.image
        if not img.isNull():
            buf = QBuffer(); buf.open(QIODevice.WriteOnly)
            img.save(buf, "PNG")
            d["_pixels"] = base64.b64encode(bytes(buf.data())).decode("ascii")
        return d

    @classmethod
    def from_wire(cls, d: dict, project_dir=None) -> "ImageShape":
        """Rehydrate from a wire dict — uses embedded pixels if present."""
        import base64
        from PyQt5.QtGui import QImage
        from pathlib import Path

        px = d.get("_pixels")
        if px:
            raw = base64.b64decode(px)
            img = QImage()
            img.loadFromData(raw, "PNG")
        else:
            # fallback to file path
            src = Path(d.get("source", ""))
            if project_dir and not src.is_absolute():
                src = project_dir / src
            img = QImage(str(src)) if src.is_file() else QImage()

        shape = cls(d["x"], d["y"],
                    d.get("source", "<embedded>"),
                    scale=d.get("scale", 1.0),
                    rotation=d.get("rotation", 0.0),
                    effects=d.get("effects", {}),
                    pixel_override=img if not img.isNull() else None)
        return shape
