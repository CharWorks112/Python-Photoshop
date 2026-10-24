"""Updater — downloads every managed file from GitHub on launch. No SHA, no state."""
import datetime, subprocess, sys, time
from pathlib import Path

try:
    import requests
except ImportError:
    import urllib.request, urllib.error
    class _Resp:
        def __init__(self, data, status=200):
            self.content = data; self.status_code = status
        def raise_for_status(self):
            if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")
    class requests:
        @staticmethod
        def get(url, timeout=30, headers=None, stream=False):
            req = urllib.request.Request(url, headers=headers or {})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return _Resp(r.read(), r.status)
            except urllib.error.HTTPError as e:
                return _Resp(b"", e.code)

RAW_BASE = "https://raw.githubusercontent.com/CharWorks112/Python-Photoshop/main"
ROOT = Path(__file__).resolve().parent

MANAGED_FILES = [
    "example.txt", "main.py", "updater.py", "requirements.txt",
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

def fetch(url):
    sep = "&" if "?" in url else "?"
    url = f"{url}{sep}cb={int(time.time() * 1000)}"
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "pp-updater",
                                                    "Cache-Control": "no-cache"})
        if r.status_code == 404: return None
        r.raise_for_status()
        return r.content
    except Exception:
        return None

def check_dependencies():
    missing = []
    for mod in ["PyQt5", "numpy", "zeroconf"]:
        try: __import__(mod)
        except ImportError: missing.append(mod)
    return missing

def install_dependencies(missing):
    if not missing: return
    import shutil
    pacman_map = {"PyQt5": "python-pyqt5", "numpy": "python-numpy", "zeroconf": "python-zeroconf"}
    apt_map    = {"PyQt5": "python3-pyqt5", "numpy": "python3-numpy", "zeroconf": "python3-zeroconf"}
    if shutil.which("pacman"):
        try:
            subprocess.check_call(["sudo", "pacman", "-S", "--noconfirm",
                                   *[pacman_map.get(m, m) for m in missing]])
            return
        except Exception: pass
    if shutil.which("apt"):
        try:
            subprocess.check_call(["sudo", "apt", "install", "-y",
                                   *[apt_map.get(m, m) for m in missing]])
            return
        except Exception: pass
    subprocess.check_call([sys.executable, "-m", "pip", "install",
                           "--break-system-packages", *missing])

def download_all():
    ok = same = failed = 0
    print(f"[updater] Downloading {len(MANAGED_FILES)} files from GitHub…")
    for rel in MANAGED_FILES:
        content = fetch(f"{RAW_BASE}/{rel}")
        if content is None:
            failed += 1
            print(f"[updater]   ✗ {rel} (404)")
            continue
        local = ROOT / rel
        try:
            local.parent.mkdir(parents=True, exist_ok=True)
            if local.is_file() and local.read_bytes() == content:
                same += 1
                continue
            local.write_bytes(content)
            ok += 1
            print(f"[updater]   ↓ {rel}")
        except Exception as e:
            failed += 1
            print(f"[updater]   ✗ {rel} (write: {e})")
    return ok, same, failed

def main():
    print(f"[updater] Python Photoshop updater — {datetime.datetime.now().strftime('%H:%M:%S')}")
    print(f"[updater] Dir: {ROOT}")

    if not (ROOT / "main.py").is_file():
        print("[updater] ❌ main.py missing.")
        return 1

    missing = check_dependencies()
    if missing:
        print(f"[updater] Installing: {', '.join(missing)}")
        install_dependencies(missing)

    ok, same, failed = download_all()
    print(f"[updater] ✅ Downloaded {ok}, unchanged {same}, failed {failed}")

    print("[updater] Launching main.py…")
    try:
        return subprocess.call([sys.executable, str(ROOT / "main.py")], cwd=str(ROOT))
    except KeyboardInterrupt:
        return 0

if __name__ == "__main__":
    sys.exit(main())
