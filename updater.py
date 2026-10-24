"""Updater + supervisor — polls GitHub via raw CDN (no rate limit),
every 5 seconds, logs each check, hot-updates without losing session."""

import hashlib
import json
import socket
import subprocess
import sys
import time
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
MANIFEST_URL  = f"{RAW_BASE}/.updater_manifest.json"   # generated file listing all file hashes

ROOT          = Path(__file__).resolve().parent
STATE_FILE    = ROOT / ".updater_state.json"
MANIFEST_FILE = ROOT / ".updater_manifest.local.json"
NOTIFY_PORT   = 51002
POLL_INTERVAL = 5

# Files we always fetch fresh
MANAGED_FILES = [
    "main.py", "updater.py", "requirements.txt",
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


def fetch(url) -> bytes | None:
    """Fetch a URL; return None on 404."""
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


def poll_and_update() -> int:
    """Check every MANAGED_FILES file against GitHub raw. Returns number updated."""
    state = load_state()
    n = 0

    for rel in MANAGED_FILES:
        url = f"{RAW_BASE}/{rel}"
        content = fetch(url)
        if content is None:
            continue  # file doesn't exist upstream — skip

        h = hashlib.sha256(content).hexdigest()
        if state.get(rel) == h:
            continue  # unchanged

        local = ROOT / rel
        try:
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(content)
            state[rel] = h
            n += 1
            print(f"[updater]   updated: {rel}")
        except Exception as e:
            print(f"[updater]   FAILED {rel}: {e}")

    save_state(state)
    return n


class AppSupervisor:
    def __init__(self):
        self.proc = None
        self.restore_session = False

    def start(self):
        args = [sys.executable, str(ROOT / "main.py")]
        if self.restore_session:
            args.append("--restore-session")
            self.restore_session = False
        print(f"[updater] Launching: {' '.join(args)}")
        self.proc = subprocess.Popen(args, cwd=str(ROOT))

    def request_update(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(("127.0.0.1", NOTIFY_PORT))
            s.sendall(b"UPDATE\n")
            s.close()
            print("[updater] Sent UPDATE signal to app")
        except Exception as e:
            print(f"[updater] Signal failed: {e} — force killing app")
            try:
                self.proc.kill()
            except Exception:
                pass


def main() -> int:
    print(f"[updater] Supervisor starting at {datetime.datetime.now().strftime('%H:%M:%S')}")
    print(f"[updater] Dir: {ROOT}")
    print(f"[updater] Poll interval: {POLL_INTERVAL}s (no GitHub API — raw CDN only, no rate limit)")

    if not (ROOT / "main.py").is_file():
        print("[updater] ❌ main.py missing — this installer requires an existing install")
        print("[updater] Manual install:")
        print("[updater]   git clone https://github.com/CharWorks112/Python-Photoshop.git")
        return 1

    missing = check_dependencies()
    if missing:
        print(f"[updater] Installing missing: {', '.join(missing)}")
        install_dependencies(missing)

    print("[updater] Initial sync…")
    n = poll_and_update()
    print(f"[updater] ✅ {n} file(s) updated at startup")

    sup = AppSupervisor()
    sup.start()
    last_check = time.time()

    while True:
        time.sleep(1)

        if sup.proc is None or sup.proc.poll() is not None:
            print("[updater] App closed. Supervisor exiting.")
            return 0

        if time.time() - last_check < POLL_INTERVAL:
            continue
        last_check = time.time()

        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[updater] 🔍 Checking for updates… {stamp}")

        n = poll_and_update()

        if n == 0:
            print(f"[updater] ✅ No updates")
            continue

        print(f"[updater] 🎉 {n} update(s) applied")
        sup.request_update()

        start = time.time()
        while sup.proc.poll() is None and time.time() - start < 30:
            time.sleep(0.5)

        if sup.proc.poll() is None:
            print("[updater] App didn't close — force killing")
            try:
                sup.proc.kill()
            except Exception:
                pass
            sup.proc.wait()

        sup.restore_session = True
        sup.start()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[updater] Interrupted")
        sys.exit(0)
