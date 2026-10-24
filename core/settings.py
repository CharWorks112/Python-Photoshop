"""Persistent settings — JSON in ~/.config/python_photoshop/settings.json."""
from pathlib import Path
import json
import copy


CONFIG_DIR = Path.home() / ".config" / "python_photoshop"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = CONFIG_DIR / "settings.json"


DEFAULTS = {
    "theme": "Dark",
    "sounds_enabled": True,
    "sounds_volume": 0.6,
    "drawing_sound_enabled": True,
    "drawing_sound_sensitivity": 1.0,   # multiplier on speed → volume
    "autosave_interval_seconds": 30,
    "default_brush_radius": 12,
    "default_fill_tolerance": 24,
    "default_document_background": "white",
}


class Settings:
    def __init__(self):
        self._data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self):
        try:
            if CONFIG_PATH.is_file():
                stored = json.loads(CONFIG_PATH.read_text())
                for k, v in stored.items():
                    if k in DEFAULTS:
                        self._data[k] = v
        except Exception:
            pass

    def save(self):
        try:
            CONFIG_PATH.write_text(json.dumps(self._data, indent=2))
        except Exception:
            pass

    def get(self, key, default=None):
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value):
        self._data[key] = value

    def as_dict(self):
        return dict(self._data)


# ---- singleton ----
_instance: Settings | None = None


def get_settings() -> Settings:
    global _instance
    if _instance is None:
        _instance = Settings()
    return _instance
