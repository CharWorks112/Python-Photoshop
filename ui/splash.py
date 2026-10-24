"""Splash screen with a REAL progress bar driven by real startup steps."""
from PyQt5.QtWidgets import QSplashScreen, QProgressBar, QWidget, QVBoxLayout, QLabel
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt


class ProgressSplash(QSplashScreen):
    def __init__(self, pixmap: QPixmap):
        super().__init__(pixmap, Qt.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.FramelessWindowHint, True)

        # embed a progress bar + status text as the mask widget (so it paints on splash)
        w = QWidget(self)
        v = QVBoxLayout(w)
        v.setContentsMargins(18, 0, 18, 14)
        v.addStretch()

        self.status_label = QLabel("Loading…")
        self.status_label.setStyleSheet("color:#e0e0e0; background:transparent; font-size:11px;")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setStyleSheet(
            "QProgressBar{background:rgba(255,255,255,0.12); border:none; border-radius:3px;}"
            "QProgressBar::chunk{background:#1f6feb; border-radius:3px;}"
        )

        v.addWidget(self.status_label)
        v.addWidget(self.bar)

        w.setGeometry(pixmap.rect())
        w.setStyleSheet("background:transparent;")

    def step(self, pct: int, message: str) -> None:
        self.bar.setValue(max(0, min(100, pct)))
        self.status_label.setText(message)
        # force repaint now — otherwise QSplashScreen only repaints on event loop turns
        self.repaint()
        from PyQt5.QtWidgets import QApplication
        QApplication.processEvents()
