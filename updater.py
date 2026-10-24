"""Updater + supervisor — runs main.py, polls GitHub every 15s, and
performs hot updates without losing session state.

Flow:
  1. Ensure app installed + deps present
  2. Launch main.py as a child process
  3. Poll GitHub every 15 seconds
  4. If updates found → notify running app via local socket
  5. App saves session, exits → we download updates → restart with --restore-session
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import requests
except ImportError:
    # Swap for urllib if requests isn't there — no pip needed
    import urllib.request, urllib.error, json as _json

    class _Resp:
        def __init__(self, data, status=200):
            self.content = data
            self.status_code = status
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")
        def json(self):
            return _json.loads(self.content)
        def iter_content(self, chunk_size=8192):
            for i in range(0, len(self.content), chunk_size):
                yield self.content[i:i+chunk_size]

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
API_BASE      = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
RAW_BASE      = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}"
ARCHIVE_URL   = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/archive/refs/heads/{GITHUB_BRANCH}.zip"

ROOT        = Path(__file__).resolve().parent
STATE_FILE  = ROOT / ".updater_state.json"
NOTIFY_PORT = 51002   # local socket for signalling the app

SKIP_DIRS  = {".git", "__pycache__", "docs", "venv", ".venv", ".idea", ".vscode"}
SKIP_FILES = {".gitignore", "updater.py", ".updater_state.json", "screenshot.png"}
SKIP_EXTS  = {".pyc", ".wav", ".log"}

REQUIRED_MODULES = ["PyQt5", "numpy", "zeroconf"]
POLL_INTERVAL = 15   # seconds


# ---------------- helpers ----------------
def load_state() -> dict:
    if STATE_FILE.is_file():
        try: return json.loads(STATE_FILE.read_text())
        except Exception: pass
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def should_skip(path: str) -> bool:
    parts = Path(path).parts
    if any(p in SKIP_DIRS for p in parts): return True
    if Path(path).name in SKIP_FILES: return True
    if Path(path).suffix in SKIP_EXTS: return True
    return False


def is_app_installed() -> bool:
    return (ROOT / "main.py").is_file() and (ROOT / "ui").is_dir() and (ROOT / "core").is_dir()


def check_dependencies() -> list[str]:
    missing = []
    for mod in REQUIRED_MODULES:
        try: __import__(mod)
        except ImportError: missing.append(mod)
    return missing


def install_dependencies(missing):
    if not missing: return
    import shutil
    pacman_map = {"PyQt5": "python-pyqt5", "numpy": "python-numpy", "zeroconf": "python-zeroconf"}
    apt_map    = {"PyQt5": "python3-pyqt5", "numpy": "python3-numpy", "zeroconf": "python3-zeroconf"}
    if shutil.which("pacman"):
        pkgs = [pacman_map.get(m, m) for m in missing]
        try:
            subprocess.check_call(["sudo", "pacman", "-S", "--noconfirm", *pkgs])
            return
        except Exception: pass
    if shutil.which("apt"):
        pkgs = [apt_map.get(m, m) for m in missing]
        try:
            subprocess.check_call(["sudo", "apt", "install", "-y", *pkgs])
            return
        except Exception: pass
    subprocess.check_call([sys.executable, "-m", "pip", "install",
                           "--break-system-packages", *missing])


def list_remote_files():
    files = []
    stack = [""]
    while stack:
        subdir = stack.pop()
        url = f"{API_BASE}/contents/{subdir}" if subdir else f"{API_BASE}/contents"
        r = requests.get(url, timeout=20, headers={"User-Agent": "python-photoshop-updater"})
        if r.status_code == 404: continue
        r.raise_for_status()
        for item in r.json():
            if item["type"] == "file":
                files.append({"path": item["path"], "sha": item["sha"],
                              "download_url": item["download_url"]})
            elif item["type"] == "dir":
                stack.append(item["path"])
    return files


def download(url: str) -> bytes:
    r = requests.get(url, timeout=30, headers={"User-Agent": "python-photoshop-updater"})
    r.raise_for_status()
    return r.content


# ---------------- install / update ----------------
def install_full_app() -> bool:
    print("[updater] App not found — installing full repository…")
    try:
        r = requests.get(ARCHIVE_URL, timeout=60, stream=True,
                         headers={"User-Agent": "python-photoshop-updater"})
        r.raise_for_status()
        tmp = ROOT / "_repo.zip"
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(8192): f.write(chunk)
        import zipfile
        with zipfile.ZipFile(tmp) as zf:
            zf.extractall(ROOT)
        extracted = next((d for d in ROOT.iterdir()
                          if d.is_dir() and d.name.endswith(GITHUB_BRANCH)), None)
        if extracted:
            import shutil as _sh
            for child in extracted.iterdir():
                dest = ROOT / child.name
                if dest.exists():
                    if dest.is_dir(): _sh.rmtree(dest)
                    else: dest.unlink()
                _sh.move(str(child), str(dest))
            extracted.rmdir()
        tmp.unlink(missing_ok=True)
        print("[updater] ✅ Full install complete")
        return True
    except Exception as e:
        print(f"[updater] ❌ Install failed: {e}")
        return False


def update_files() -> int:
    """Download files whose SHA differs. Returns count."""
    try:
        remote = list_remote_files()
    except Exception as e:
        print(f"[updater] GitHub unreachable: {e}")
        return 0

    state = load_state()
    updated = 0
    for f in remote:
        if should_skip(f["path"]): continue
        local = ROOT / f["path"]
        if not local.is_file() or state.get(f["path"]) != f["sha"]:
            try:
                data = download(f["download_url"])
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(data)
                state[f["path"]] = f["sha"]
                updated += 1
                print(f"[updater]   updated: {f['path']}")
            except Exception as e:
                print(f"[updater]   FAILED {f['path']}: {e}")
    save_state(state)
    return updated


# ---------------- app process supervisor ----------------
class AppSupervisor:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.restore_session = False

    def start(self):
        args = [sys.executable, str(ROOT / "main.py")]
        if self.restore_session:
            args.append("--restore-session")
            self.restore_session = False
        print(f"[updater] Launching: {' '.join(args)}")
        self.proc = subprocess.Popen(args, cwd=str(ROOT))

    def wait(self) -> int:
        if self.proc is None: return 1
        return self.proc.wait()

    def request_update(self):
        """Signal the running app to close for update."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(("127.0.0.1", NOTIFY_PORT))
            s.sendall(b"UPDATE\n")
            s.close()
            print("[updater] Sent UPDATE signal to app")
        except Exception as e:
            print(f"[updater] Could not signal app: {e} (will force kill)")
            try: self.proc.kill()
            except Exception: pass


# ---------------- main loop ----------------
def main() -> int:
    print("[updater] Python Photoshop supervisor starting…")

    if not is_app_installed():
        print("[updater] No existing installation detected.")
        if not install_full_app(): return 1

    missing = check_dependencies()
    if missing: install_dependencies(missing)

    # Initial sync before launch
    print("[updater] Initial sync…")
    n = update_files()
    print(f"[updater] ✅ {n} file(s) updated on initial sync")

    sup = AppSupervisor()
    sup.start()

    last_check = time.time()
    while True:
        # Check every 15 s while app is running
        time.sleep(1)
        if sup.proc is None or sup.proc.poll() is not None:
            # App exited on its own → user quit. Do NOT relaunch.
            print("[updater] App exited. Shutting down supervisor.")
            return 0

        if time.time() - last_check < POLL_INTERVAL:
            continue
        last_check = time.time()

        try:
            remote = list_remote_files()
        except Exception:
            continue  # network hiccup; try again next cycle

        state = load_state()
        diffs = [f for f in remote
                 if not should_skip(f["path"])
                 and state.get(f["path"]) != f["sha"]]

        if not diffs:
            continue

        print(f"[updater] 🎉 {len(diffs)} update(s) found — notifying app")
        sup.request_update()

        # Wait for app to close (max 30 s)
        start = time.time()
        while sup.proc.poll() is None and time.time() - start < 30:
            time.sleep(0.5)

        if sup.proc.poll() is None:
            print("[updater] App didn't close in 30s — force kill")
            try: sup.proc.kill()
            except Exception: pass
            sup.proc.wait()

        # Download updates
        print("[updater] Downloading updates…")
        n = update_files()
        print(f"[updater] ✅ {n} file(s) updated")

        # Relaunch with session restore
        sup.restore_session = True
        sup.start()
        print("[updater] App relaunched with --restore-session")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[updater] Interrupted")
        sys.exit(0)
