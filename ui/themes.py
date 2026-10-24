"""Theme palettes — applied as a QApplication stylesheet.
Each palette uses the standard Fusion naming so a single template works for all."""
from PyQt5.QtWidgets import QApplication


PALETTES = {
    "Dark": {
        "bg":       "#2b2b2b",
        "surface":  "#3a3a3a",
        "panel":    "#333333",
        "text":     "#e6e6e6",
        "text_dim": "#a0a0a0",
        "border":   "#4a4a4a",
        "accent":   "#1f6feb",
        "accent_text": "#ffffff",
        "canvas":   "#2b2b2b",
    },
    "Light": {
        "bg":       "#f0f0f0",
        "surface":  "#ffffff",
        "panel":    "#f5f5f5",
        "text":     "#1a1a1a",
        "text_dim": "#666666",
        "border":   "#c8c8c8",
        "accent":   "#1f6feb",
        "accent_text": "#ffffff",
        "canvas":   "#d8d8d8",
    },
    "Black": {
        "bg":       "#000000",
        "surface":  "#111111",
        "panel":    "#0a0a0a",
        "text":     "#f0f0f0",
        "text_dim": "#888888",
        "border":   "#222222",
        "accent":   "#ff2d55",
        "accent_text": "#ffffff",
        "canvas":   "#0f0f0f",
    },
    "Red": {
        "bg":       "#2b1414",
        "surface":  "#3b1a1a",
        "panel":    "#331717",
        "text":     "#ffe8e8",
        "text_dim": "#c89090",
        "border":   "#5a2020",
        "accent":   "#ff4040",
        "accent_text": "#ffffff",
        "canvas":   "#2b1414",
    },
    "Orange": {
        "bg":       "#2b1e0f",
        "surface":  "#3b2714",
        "panel":    "#33220f",
        "text":     "#fff1e0",
        "text_dim": "#c89a70",
        "border":   "#5a3a1a",
        "accent":   "#ff9020",
        "accent_text": "#1a1a1a",
        "canvas":   "#2b1e0f",
    },
    "Gold": {
        "bg":       "#1f1a0f",
        "surface":  "#2b2416",
        "panel":    "#26200f",
        "text":     "#fff4c8",
        "text_dim": "#c8a878",
        "border":   "#4a3a1a",
        "accent":   "#d4af37",
        "accent_text": "#1a1a1a",
        "canvas":   "#1f1a0f",
    },
}


def build_stylesheet(name: str) -> str:
    p = PALETTES.get(name, PALETTES["Dark"])
    return f"""
    QMainWindow, QDialog {{
        background-color: {p['bg']};
        color: {p['text']};
    }}
    QWidget {{
        background-color: {p['bg']};
        color: {p['text']};
    }}
    QMenuBar {{
        background-color: {p['surface']};
        color: {p['text']};
    }}
    QMenuBar::item:selected {{
        background-color: {p['accent']};
        color: {p['accent_text']};
    }}
    QMenu {{
        background-color: {p['surface']};
        color: {p['text']};
        border: 1px solid {p['border']};
    }}
    QMenu::item:selected {{
        background-color: {p['accent']};
        color: {p['accent_text']};
    }}
    QDockWidget {{
        color: {p['text']};
        titlebar-close-icon: none;
    }}
    QDockWidget::title {{
        background-color: {p['panel']};
        color: {p['text']};
        padding: 4px;
        border-bottom: 1px solid {p['border']};
    }}
    QPushButton {{
        background-color: {p['surface']};
        color: {p['text']};
        border: 1px solid {p['border']};
        padding: 4px 10px;
        border-radius: 3px;
    }}
    QPushButton:hover {{
        background-color: {p['accent']};
        color: {p['accent_text']};
    }}
    QPushButton:checked {{
        background-color: {p['accent']};
        color: {p['accent_text']};
        border-color: {p['accent']};
    }}
    QPushButton:pressed {{
        background-color: {p['border']};
    }}
    QLineEdit, QSpinBox, QComboBox, QLabel {{
        background-color: {p['surface']};
        color: {p['text']};
        border: 1px solid {p['border']};
        padding: 2px 4px;
        border-radius: 2px;
    }}
    QLabel {{
        background-color: transparent;
        border: none;
    }}
    QComboBox::drop-down {{
        border: none;
    }}
    QSlider::groove:horizontal {{
        background: {p['border']};
        height: 6px;
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {p['accent']};
        width: 14px;
        margin: -4px 0;
        border-radius: 7px;
    }}
    QListWidget {{
        background-color: {p['surface']};
        color: {p['text']};
        border: 1px solid {p['border']};
    }}
    QListWidget::item:selected {{
        background-color: {p['accent']};
        color: {p['accent_text']};
    }}
    QTabWidget::pane {{
        border: 1px solid {p['border']};
        background: {p['bg']};
    }}
    QTabBar::tab {{
        background: {p['panel']};
        color: {p['text']};
        padding: 6px 14px;
        border: 1px solid {p['border']};
        border-bottom: none;
    }}
    QTabBar::tab:selected {{
        background: {p['accent']};
        color: {p['accent_text']};
    }}
    QStatusBar {{
        background-color: {p['surface']};
        color: {p['text_dim']};
    }}
    QScrollBar:vertical, QScrollBar:horizontal {{
        background: {p['panel']};
        border: none;
    }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
        background: {p['border']};
        border-radius: 4px;
        min-height: 20px;
        min-width: 20px;
    }}
    QScrollBar::handle:hover {{
        background: {p['accent']};
    }}
    QCheckBox {{
        color: {p['text']};
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        background: {p['panel']};
        border: none;
    }}
    QMessageBox {{
        background-color: {p['bg']};
    }}
    """


def apply_theme(name: str) -> None:
    """Apply a theme to the running QApplication."""
    app = QApplication.instance()
    if app is None:
        return
    app.setStyleSheet(build_stylesheet(name))
    # also tell canvases to update their background
    for w in app.topLevelWidgets():
        try:
            if hasattr(w, "apply_canvas_theme"):
                w.apply_canvas_theme(name)
        except Exception:
            pass
