"""Flood fill for QImage.
Uses NumPy for speed when available, falls back to scanline.
"""
from PyQt5.QtGui import QImage, QColor

try:
    import numpy as np
    _HAVE_NUMPY = True
except Exception:
    _HAVE_NUMPY = False


def _qimage_to_rgba(image: QImage):
    """Return (numpy HxWx4 uint8 array, detach_buffer copy)."""
    img = image.convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    ptr = img.constBits()
    ptr.setsize(img.byteCount())
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, w, 4)).copy()
    return arr


def _rgba_to_qimage(arr, image: QImage):
    h, w, _ = arr.shape
    img = QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
    image.swap(img)


def flood_fill(image: QImage, x: int, y: int, color: QColor, tolerance: int = 24) -> bool:
    if image.isNull():
        return False
    w, h = image.width(), image.height()
    if not (0 <= x < w and 0 <= y < h):
        return False

    if not _HAVE_NUMPY:
        return _flood_fill_python(image, x, y, color, tolerance)

    arr = _qimage_to_rgba(image)
    target = arr[y, x].astype(np.int32)
    fill = np.array([color.blue(), color.green(), color.red(), color.alpha()],
                    dtype=np.uint8)
    # note: Format_RGBA8888 stores bytes as (r,g,b,a) on little-endian? Actually it's R,G,B,A order.
    fill = np.array([color.red(), color.green(), color.blue(), color.alpha()],
                    dtype=np.uint8)

    if np.array_equal(target, fill.astype(np.int32)):
        return False

    tol2 = tolerance * tolerance * 3
    diff = arr.astype(np.int32) - target
    dist2 = (diff[..., 0] ** 2 + diff[..., 1] ** 2
             + diff[..., 2] ** 2 + diff[..., 3] ** 2)
    mask = dist2 <= tol2

    # BFS flood fill on the boolean mask — vectorized in NumPy where possible
    visited = np.zeros((h, w), dtype=bool)
    stack = [(x, y)]
    while stack:
        cx, cy = stack.pop()
        if visited[cy, cx] or not mask[cy, cx]:
            continue
        # expand horizontally from (cx, cy)
        left = cx
        while left > 0 and mask[cy, left - 1] and not visited[cy, left - 1]:
            left -= 1
        right = cx
        while right < w - 1 and mask[cy, right + 1] and not visited[cy, right + 1]:
            right += 1
        visited[cy, left:right + 1] = True
        if cy > 0:
            row = mask[cy - 1, left:right + 1] & ~visited[cy - 1, left:right + 1]
            xs = np.where(row)[0]
            for xx in xs:
                stack.append((left + int(xx), cy - 1))
        if cy < h - 1:
            row = mask[cy + 1, left:right + 1] & ~visited[cy + 1, left:right + 1]
            xs = np.where(row)[0]
            for xx in xs:
                stack.append((left + int(xx), cy + 1))

    if not visited.any():
        return False

    arr[visited] = fill
    _rgba_to_qimage(arr, image)
    return True


def _flood_fill_python(image: QImage, x, y, color, tolerance) -> bool:
    w, h = image.width(), image.height()
    img = image.convertToFormat(QImage.Format_ARGB32)
    target = img.pixelColor(x, y)
    fill = QColor(color)
    if (target.red() == fill.red() and target.green() == fill.green()
            and target.blue() == fill.blue() and target.alpha() == fill.alpha()):
        return False
    tol2 = tolerance * tolerance * 3
    def matches(c):
        dr = c.red() - target.red(); dg = c.green() - target.green()
        db = c.blue() - target.blue(); da = c.alpha() - target.alpha()
        return dr * dr + dg * dg + db * db + da * da <= tol2
    visited = bytearray(w * h)
    stack = [(x, y)]
    filled = 0
    while stack:
        cx, cy = stack.pop()
        if not (0 <= cx < w and 0 <= cy < h):
            continue
        idx = cy * w + cx
        if visited[idx]:
            continue
        visited[idx] = 1
        if not matches(img.pixelColor(cx, cy)):
            continue
        img.setPixelColor(cx, cy, fill); filled += 1
        stack.extend(((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)))
    if filled:
        for yy in range(h):
            for xx in range(w):
                if visited[yy * w + xx]:
                    image.setPixelColor(xx, yy, fill)
        return True
    return False
