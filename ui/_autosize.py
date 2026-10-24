"""Mixin: make a QDialog auto-fit its content while staying usable on small screens."""
from PyQt5.QtCore import QTimer, QSize
from PyQt5.QtWidgets import QApplication


class AutoSizeMixin:
    def auto_size(self, min_w: int = 320, min_h: int = 200,
                  max_frac: float = 0.92):
        """Shrink-wrap to content, clamp to available screen, respect minimums."""
        scr = QApplication.primaryScreen()
        avail = scr.availableGeometry() if scr else None
        sh = self.sizeHint()
        wanted_w = max(min_w, sh.width())
        wanted_h = max(min_h, sh.height())

        if avail is not None:
            max_w = int(avail.width() * max_frac)
            max_h = int(avail.height() * max_frac)
            wanted_w = min(wanted_w, max_w)
            wanted_h = min(wanted_h, max_h)

        self.resize(QSize(wanted_w, wanted_h))
        # center on parent if any
        parent = self.parent()
        if parent is not None:
            pg = parent.window().frameGeometry() if hasattr(parent, "window") else None
            if pg is not None and pg.isValid():
                x = pg.x() + (pg.width() - wanted_w) // 2
                y = pg.y() + (pg.height() - wanted_h) // 2
                self.move(max(avail.x(), x) if avail else x,
                          max(avail.y(), y) if avail else y)
