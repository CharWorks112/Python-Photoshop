"""Updater — checks GitHub once on launch, downloads any changed files, then
runs main.py. No background polling, no supervisor.

Usage:
    python updater.py             # check for updates, then launch
    python updater.py --no-update # skip check, launch immediately
"""

import hashlib
import json
import subprocess
import sys
import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    import urllib.request, urllib.error

    class _Resp:
        def __init__(self, data, status=200):
            self.content = data
            self.status_code = status
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    class requests:
        @staticmethod
        def get(url, timeout=30, headers=None, stream=False):
            req = urllib.request.Request(url, headers=headers or {})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return _Resp(r.read(), r.status)
            except urllib.error.HTTPError as e:
                return _Resp(b"", e.code)


GITHUB_OWNER  = "CharWorks112"
GITHUB_REPO   = "Python-Photoshop"
GITHUB_BRANCH = "main"
RAW_BASE      = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}"

ROOT       = Path(__file__).resolve().parent
STATE_FILE = ROOT / ".updater_state.json"

MANAGED_FILES = [
    "example.txt",
    "main.py",
    "updater.py",
    "requirements.txt",
    "core/layer.py", "core/project.py", "core/shape_layer.py",
    "core/image_shape.py", "core/shape_objects.py", "core/sounds.py",
    "core/imagemagick.py", "core/export.py", "core/fill.py",
    "core/commands.py", "core/settings.py", "core/glow.py",
    "core/session_backup.py", "core/autosave.py",
    "ui/main_window.py", "ui/canvas.py", "ui/color_picker.py",
    "ui/new_dialog.py", "ui/export_dialog.py", "ui/themes.py",
    "ui/preferences_dialog.py", "ui/_autosize.py", "ui/splash.py",
    "ui/image_import_dialog.py", "ui/sub_image_editor.py",
    "ui/shape_properties_dialog.py",
    "extensions/collab/session.py", "extensions/collab/protocol.py",
    "extensions/collab/discovery.py", "extensions/collab/lobby.py",
    "extensions/collab/chat_dock.py",
]

REQUIRED_MODULES = ["PyQt5", "numpy", "zeroconf"]


def load_state():
    if STATE_FILE.is_file():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def fetch(url):
    """Fetch URL → bytes, or None on 404/error."""
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "pp-updater"})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content
    except Exception:
        return None


def check_dependencies():
    missing = []
    for mod in REQUIRED_MODULES:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    return missing


def install_dependencies(missing):
    if not missing:
        return
    import shutil
    pacman_map = {"PyQt5": "python-pyqt5", "numpy": "python-numpy", "zeroconf": "python-zeroconf"}
    apt_map    = {"PyQt5": "python3-pyqt5", "numpy": "python3-numpy", "zeroconf": "python3-zeroconf"}
    if shutil.which("pacman"):
        pkgs = [pacman_map.get(m, m) for m in missing]
        try:
            subprocess.check_call(["sudo", "pacman", "-S", "--noconfirm", *pkgs])
            return
        except Exception:
            pass
    if shutil.which("apt"):
        pkgs = [apt_map.get(m, m) for m in missing]
        try:
            subprocess.check_call(["sudo", "apt", "install", "-y", *pkgs])
            return
        except Exception:
            pass
    subprocess.check_call([sys.executable, "-m", "pip", "install",
                           "--break-system-packages", *missing])


def sync_files():
    """Fetch every managed file. Returns count of updated files."""
    state = load_state()
    n = 0
    for rel in MANAGED_FILES:
        content = fetch(f"{RAW_BASE}/{rel}")
        if content is None:
            continue
        h = hashlib.sha256(content).hexdigest()
        if state.get(rel) == h:
            continue
        try:
            local = ROOT / rel
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(content)
            state[rel] = h
            n += 1
            print(f"[updater]   updated: {rel}")
        except Exception as e:
            print(f"[updater]   FAILED {rel}: {e}")
    save_state(state)
    return n


def main():
    no_update = "--no-update" in sys.argv

    print(f"[updater] Python Photoshop updater — {datetime.datetime.now().strftime('%H:%M:%S')}")
    print(f"[updater] Dir: {ROOT}")

    if not (ROOT / "main.py").is_file():
        print("[updater] ❌ main.py missing.")
        print("[updater] Manual install:")
        print("[updater]   git clone https://github.com/CharWorks112/Python-Photoshop.git")
        return 1

    missing = check_dependencies()
    if missing:
        print(f"[updater] Installing missing: {', '.join(missing)}")
        install_dependencies(missing)

    if not no_update:
        print("[updater] Checking GitHub for updates…")
        try:
            n = sync_files()
            print(f"[updater] ✅ {n} file(s) updated" if n else "[updater] ✅ Already up to date")
        except Exception as e:
            print(f"[updater] ⚠ Update check failed: {e}")
            print("[updater] Launching with current files anyway…")
    else:
        print("[updater] Skipping update (--no-update)")

    print("[updater] Launching main.py…")
    try:
        return subprocess.call([sys.executable, str(ROOT / "main.py")], cwd=str(ROOT))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
