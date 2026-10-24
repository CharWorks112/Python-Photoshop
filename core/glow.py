"""Glow rendering helpers: soft blurred copy of an image/shape."""
from PyQt5.QtGui import QImage, QPainter, QColor
from PyQt5.QtCore import Qt


def blurred_silhouette(src: QImage, radius: int, color: QColor) -> QImage:
    """Return a blurred, tinted copy of `src` sized to fit with margin."""
    if src.isNull() or radius <= 0:
        return QImage()

    margin = max(4, radius * 2)
    w, h = src.width() + margin * 2, src.height() + margin * 2

    # 1) silhouette — take alpha channel of `src` as mask, fill with `color`
    sil = QImage(w, h, QImage.Format_ARGB32)
    sil.fill(Qt.transparent)
    p = QPainter(sil)
    p.drawImage(margin, margin, src)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(sil.rect(), color)
    p.end()

    # 2) cheap blur: downscale 4×, upscale back, twice for smoothness
    small = sil.scaled(max(1, w // 4), max(1, h // 4),
                       Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    blurred = small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    small2 = blurred.scaled(max(1, w // 6), max(1, h // 6),
                            Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    blurred = small2.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    # scale blur pass by radius
    if radius > 6:
        for _ in range(min(3, radius // 6)):
            small = blurred.scaled(max(1, w // 5), max(1, h // 5),
                                   Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            blurred = small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    return blurred
