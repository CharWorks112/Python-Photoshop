"""Pixel layer — wraps a QImage and its metadata."""
from pathlib import Path
from PyQt5.QtGui import QImage, QPainter, QColor
from PyQt5.QtCore import Qt


class PixelLayer:
    def __init__(self, name: str, width: int, height: int,
                 fill: str | None = "white"):
        self.name = name
        self.visible = True
        self.opacity = 1.0
        self.image = QImage(width, height, QImage.Format_ARGB32)
        if fill == "transparent":
            self.image.fill(Qt.transparent)
        else:
            self.image.fill(QColor(fill or "white"))

    # ---------- painting ----------
    def paint_dab(self, x: int, y: int, radius: int, color: QColor) -> None:
        if not self.visible:
            return
        p = QPainter(self.image)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(x - radius, y - radius, radius * 2, radius * 2)
        p.end()

    def clone_image(self) -> QImage:
        return self.image.copy()

    def restore(self, image: QImage) -> None:
        self.image = image

    # ---------- persistence ----------
    def to_dict(self, pixel_filename: str) -> dict:
        return {
            "name": self.name,
            "visible": self.visible,
            "opacity": self.opacity,
            "pixels": pixel_filename,
        }

    def save_pixels(self, path: Path) -> None:
        ok = self.image.save(str(path), "PNG")
        if not ok:
            raise IOError(f"Failed to write {path}")

    @classmethod
    def from_dict(cls, data: dict, project_dir: Path, width: int, height: int) -> "PixelLayer":
        layer = cls(data["name"], width, height, fill="transparent")
        layer.visible = data.get("visible", True)
        layer.opacity = data.get("opacity", 1.0)
        px = project_dir / data.get("pixels", "")
        if px.is_file():
            img = QImage(str(px))
            if not img.isNull():
                layer.image = img.convertToFormat(QImage.Format_ARGB32)
        return layer


def merge_layers(layers, width: int, height: int, background: str = "transparent") -> QImage:
    """Composite visible layers (bottom→top) into a single QImage.
    Supports both PixelLayer (has .image) and ShapeLayer (has .render_to_image())."""
    out = QImage(width, height, QImage.Format_ARGB32)
    if background == "transparent":
        out.fill(Qt.transparent)
    else:
        out.fill(QColor(background or "white"))
    p = QPainter(out)
    for layer in layers:
        if layer.visible:
            p.setOpacity(layer.opacity)
            if hasattr(layer, "render_to_image"):
                p.drawImage(0, 0, layer.render_to_image())
            else:
                p.drawImage(0, 0, layer.image)
    p.end()
    return out
