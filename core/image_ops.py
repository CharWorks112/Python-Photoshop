"""Reusable image operations — called by main window, Image menu, and sub-editor.
All operate on a QImage and return a new QImage."""
from pathlib import Path
import tempfile
from PyQt5.QtGui import QImage

from core import imagemagick


def _roundtrip(img: QImage, im_args: list[str]) -> QImage:
    """Write QImage → PNG → ImageMagick (with args) → read back."""
    src = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
    dst = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
    if not img.save(src, "PNG"):
        raise IOError("Could not save temp PNG for effects")
    try:
        imagemagick._run([imagemagick._bin(), src, *im_args, dst])
        out = QImage(dst)
        return out.convertToFormat(QImage.Format_ARGB32)
    finally:
        try: Path(src).unlink(missing_ok=True)
        except Exception: pass
        try: Path(dst).unlink(missing_ok=True)
        except Exception: pass


def hue_shift(img: QImage, degrees: int) -> QImage:
    if degrees == 0:
        return img.copy()
    pct = 100 + (degrees / 360.0) * 100.0
    return _roundtrip(img, ["-modulate", f"100,100,{pct:.2f}"])


def grayscale(img: QImage) -> QImage:
    return _roundtrip(img, ["-colorspace", "Gray"])


def sepia(img: QImage) -> QImage:
    return _roundtrip(img, ["-sepia-tone", "80%"])


def blur(img: QImage, radius: int) -> QImage:
    if radius <= 0:
        return img.copy()
    return _roundtrip(img, ["-blur", f"0x{radius}"])


def sharpen(img: QImage, radius: int) -> QImage:
    if radius <= 0:
        return img.copy()
    return _roundtrip(img, ["-sharpen", f"0x{radius}"])


def adjust_brightness_contrast(img: QImage, brightness: int = 0, contrast: int = 0) -> QImage:
    if brightness == 0 and contrast == 0:
        return img.copy()
    return _roundtrip(img, ["-brightness-contrast", f"{brightness}x{contrast}"])


def remove_background(img: QImage) -> QImage:
    """Try rembg first (AI segmentation); fall back to ImageMagick fuzz transparency."""
    # 1. Try rembg
    try:
        import numpy as np
        from rembg import remove
        from PyQt5.QtCore import QBuffer, QIODevice
        buf_in = QBuffer(); buf_in.open(QIODevice.WriteOnly)
        img.save(buf_in, "PNG")
        result_bytes = remove(bytes(buf_in.data()))
        out = QImage()
        out.loadFromData(result_bytes, "PNG")
        if not out.isNull():
            return out.convertToFormat(QImage.Format_ARGB32)
    except Exception:
        pass

    # 2. Fallback — ImageMagick: make near-white pixels transparent
    try:
        return _roundtrip(img, [
            "-fuzz", "12%",
            "-transparent", "white",
        ])
    except Exception:
        return img.copy()


def has_rembg() -> bool:
    try:
        import rembg  # noqa
        return True
    except Exception:
        return False
