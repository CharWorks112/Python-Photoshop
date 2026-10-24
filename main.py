import sys
from pathlib import Path

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtCore import Qt, QTimer

from ui.main_window import MainWindow
from ui.themes import apply_theme
from ui.splash import ProgressSplash
from core import imagemagick, sounds
from core.settings import get_settings


ASSETS = Path(__file__).resolve().parent / "assets"


def main() -> int:
    app = QApplication(sys.argv)

    # --- settings + theme first (cheap) ---
    settings = get_settings()
    apply_theme(settings.get("theme"))

    # --- app icon ---
    icon_path = ASSETS / "app_icon.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    # --- splash ---
    splash = None
    splash_path = ASSETS / "splash.png"
    if splash_path.is_file():
        splash = ProgressSplash(QPixmap(str(splash_path)))
        splash.show()
        app.processEvents()

    def report(pct, msg):
        if splash:
            splash.step(pct, msg)

    # ================= REAL STARTUP STEPS =================
    report(5, "Loading settings…")
    _ = settings.as_dict()

    report(15, "Checking ImageMagick…")
    if not imagemagick.is_available():
        report(15, "ImageMagick missing — import disabled")

    report(30, "Synthesizing sounds…")
    engine = sounds.get_engine()          # builds / caches WAVs if needed
    sounds.debug_list()

    report(60, "Preparing audio backend…")
    engine.set_enabled(settings.get("sounds_enabled"))
    sounds.set_master_volume(settings.get("sounds_volume"))

    report(75, "Scanning project folders…")
    try:
        from core.project import PROJECTS_DIR
        projects = list(PROJECTS_DIR.glob("*/project.json"))
    except Exception:
        projects = []

    report(85, "Building interface…")
    win = MainWindow()

    # Restore session if launched by updater after an update
    if "--restore-session" in sys.argv:
        from core import session_backup
        try:
            if session_backup.load_session(win):
                win.statusBar().showMessage("Session restored after update")
        except Exception as e:
            print(f"[main] session restore failed: {e}")
    if not imagemagick.is_available():
        win.statusBar().showMessage(
            "⚠ ImageMagick not found — effects and image import will fail.")

    report(95, "Ready.")
    # ======================================================

    def finish():
        win.show()
        if splash:
            splash.finish(win)
        sounds.play("startup")
        QTimer.singleShot(150, win._scan_crash_recovery)

    # keep the splash up long enough to read — but not artificial
    QTimer.singleShot(400, finish)

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
