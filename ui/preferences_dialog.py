"""Preferences — the single place for all settings."""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QGroupBox, QComboBox,
    QCheckBox, QSlider, QSpinBox, QDialogButtonBox, QLabel, QWidget,
    QHBoxLayout, QScrollArea, QFrame
)
from PyQt5.QtCore import Qt, QTimer
from ui._autosize import AutoSizeMixin
from ui.themes import PALETTES
from core.settings import get_settings
from core import sounds


class PreferencesDialog(QDialog, AutoSizeMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.settings = get_settings()

        # ---------- Appearance ----------
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(PALETTES.keys())
        self.theme_combo.setCurrentText(self.settings.get("theme"))
        appear = QGroupBox("Appearance")
        ap = QFormLayout(appear)
        ap.addRow("Theme:", self.theme_combo)

        # ---------- Sound ----------
        self.sounds_enabled = QCheckBox("Enable sounds")
        self.sounds_enabled.setChecked(self.settings.get("sounds_enabled"))

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(int(self.settings.get("sounds_volume") * 100))
        self.volume_label = QLabel(f"{self.volume_slider.value()}%")
        self.volume_slider.valueChanged.connect(
            lambda v: self.volume_label.setText(f"{v}%")
        )

        self.drawing_sound = QCheckBox("Continuous drawing sound")
        self.drawing_sound.setChecked(self.settings.get("drawing_sound_enabled"))

        self.drawing_sens = QSlider(Qt.Horizontal)
        self.drawing_sens.setRange(10, 300)   # 0.1 .. 3.0
        self.drawing_sens.setValue(int(self.settings.get("drawing_sound_sensitivity") * 100))
        self.drawing_sens_label = QLabel(f"{self.drawing_sens.value() / 100:.1f}×")
        self.drawing_sens.valueChanged.connect(
            lambda v: self.drawing_sens_label.setText(f"{v / 100:.1f}×")
        )

        sound_box = QGroupBox("Sound")
        snd = QFormLayout(sound_box)
        snd.addRow(self.sounds_enabled)
        vol_row = QHBoxLayout()
        vol_row.addWidget(self.volume_slider); vol_row.addWidget(self.volume_label)
        vol_wrap = QWidget(); vol_wrap.setLayout(vol_row)
        snd.addRow("Volume:", vol_wrap)
        snd.addRow(self.drawing_sound)
        sens_row = QHBoxLayout()
        sens_row.addWidget(self.drawing_sens); sens_row.addWidget(self.drawing_sens_label)
        sens_wrap = QWidget(); sens_wrap.setLayout(sens_row)
        snd.addRow("Draw sensitivity:", sens_wrap)

        # ---------- Editing defaults ----------
        self.brush_radius = QSpinBox(); self.brush_radius.setRange(1, 200)
        self.brush_radius.setValue(self.settings.get("default_brush_radius"))

        self.fill_tol = QSpinBox(); self.fill_tol.setRange(0, 255)
        self.fill_tol.setValue(self.settings.get("default_fill_tolerance"))

        self.bg_combo = QComboBox()
        self.bg_combo.addItems(["white", "black", "transparent"])
        self.bg_combo.setCurrentText(self.settings.get("default_document_background"))

        edit_box = QGroupBox("Editing Defaults")
        ed = QFormLayout(edit_box)
        ed.addRow("Brush size:", self.brush_radius)
        ed.addRow("Bucket tolerance:", self.fill_tol)
        ed.addRow("New document bg:", self.bg_combo)

        # ---------- Files / autosave ----------
        self.autosave_spin = QSpinBox()
        self.autosave_spin.setRange(5, 600)
        self.autosave_spin.setSuffix(" s")
        self.autosave_spin.setValue(self.settings.get("autosave_interval_seconds"))

        files_box = QGroupBox("Files")
        fl = QFormLayout(files_box)
        fl.addRow("Autosave interval:", self.autosave_spin)

        # ---------- buttons ----------
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self._restore)

        # ---------- layout with scroll ----------
        body = QWidget()
        v = QVBoxLayout(body)
        v.addWidget(appear)
        v.addWidget(sound_box)
        v.addWidget(edit_box)
        v.addWidget(files_box)
        v.addStretch()

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(body)

        outer = QVBoxLayout(self)
        outer.addWidget(scroll, 1)
        outer.addWidget(buttons)

        # preview sound on volume slider release
        self.volume_slider.sliderReleased.connect(self._preview)

        QTimer.singleShot(0, lambda: self.auto_size(min_w=480, min_h=440))

    def _preview(self):
        if self.sounds_enabled.isChecked():
            sounds.set_master_volume(self.volume_slider.value() / 100)
            sounds.play("brush")

    def _restore(self):
        from core.settings import DEFAULTS
        self.theme_combo.setCurrentText(DEFAULTS["theme"])
        self.sounds_enabled.setChecked(DEFAULTS["sounds_enabled"])
        self.volume_slider.setValue(int(DEFAULTS["sounds_volume"] * 100))
        self.drawing_sound.setChecked(DEFAULTS["drawing_sound_enabled"])
        self.drawing_sens.setValue(int(DEFAULTS["drawing_sound_sensitivity"] * 100))
        self.brush_radius.setValue(DEFAULTS["default_brush_radius"])
        self.fill_tol.setValue(DEFAULTS["default_fill_tolerance"])
        self.bg_combo.setCurrentText(DEFAULTS["default_document_background"])
        self.autosave_spin.setValue(DEFAULTS["autosave_interval_seconds"])

    def _on_ok(self):
        self.settings.set("theme", self.theme_combo.currentText())
        self.settings.set("sounds_enabled", self.sounds_enabled.isChecked())
        self.settings.set("sounds_volume", self.volume_slider.value() / 100)
        self.settings.set("drawing_sound_enabled", self.drawing_sound.isChecked())
        self.settings.set("drawing_sound_sensitivity", self.drawing_sens.value() / 100)
        self.settings.set("default_brush_radius", self.brush_radius.value())
        self.settings.set("default_fill_tolerance", self.fill_tol.value())
        self.settings.set("default_document_background", self.bg_combo.currentText())
        self.settings.set("autosave_interval_seconds", self.autosave_spin.value())
        self.settings.save()
        self.accept()

    def apply_to(self, main_window) -> None:
        """Push all persisted values into the live app."""
        s = self.settings
        main_window._set_theme(s.get("theme"))
        sounds.get_engine().set_enabled(s.get("sounds_enabled"))
        sounds.set_master_volume(s.get("sounds_volume"))
        for i in range(main_window.tabs.count()):
            c = main_window.tabs.widget(i)
            c.drawing_sound_enabled = s.get("drawing_sound_enabled")
            c.drawing_sound_sensitivity = s.get("drawing_sound_sensitivity")
        # autosave interval
        try:
            main_window._autosave_timer.setInterval(
                int(s.get("autosave_interval_seconds")) * 1000)
        except Exception:
            pass
        # defaults for the tools dock
        main_window._brush_radius = s.get("default_brush_radius")
        main_window._fill_tolerance = s.get("default_fill_tolerance")
        main_window.size_spin.setValue(main_window._brush_radius)
        main_window.tolerance_spin.setValue(main_window._fill_tolerance)
