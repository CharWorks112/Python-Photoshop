"""Updater + installer — checks GitHub, installs if missing, updates if stale,
then launches main.py."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("[updater] 'requests' not installed. Installing...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

# ---------- config ----------
GITHUB_OWNER = "CharWorks112"
GITHUB_REPO  = "Python-Photoshop"
GITHUB_BRANCH = "main"
API_BASE     = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
RAW_BASE     = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}"
ARCHIVE_URL  = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/archive/refs/heads/{GITHUB_BRANCH}.zip"

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / ".updater_state.json"

# Files/folders the updater itself ignores
SKIP_DIRS = {".git", "__pycache__", "docs", "venv", ".venv", ".idea", ".vscode"}
SKIP_FILES = {".gitignore", "updater.py", ".updater_state.json", "screenshot.png"}
SKIP_EXTS = {".pyc", ".wav", ".log"}

REQUIRED_MODULES = ["PyQt5", "numpy", "zeroconf", "requests"]


# ---------- helpers ----------
def load_state() -> dict:
    if STATE_FILE.is_file():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def should_skip(path: str) -> bool:
    parts = Path(path).parts
    if any(p in SKIP_DIRS for p in parts):
        return True
    if Path(path).name in SKIP_FILES:
        return True
    if Path(path).suffix in SKIP_EXTS:
        return True
    return False


def is_app_installed() -> bool:
    """Check if this is a real install (main.py + ui/ + core/ present)."""
    return (ROOT / "main.py").is_file() and \
           (ROOT / "ui").is_dir() and \
           (ROOT / "core").is_dir()


def check_dependencies() -> list[str]:
    """Return list of missing Python modules."""
    missing = []
    for mod in REQUIRED_MODULES:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    return missing


def install_dependencies(missing: list[str]) -> None:
    """pip install any missing modules."""
    if not missing:
        return
    print(f"[updater] Installing missing Python packages: {', '.join(missing)}")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", *missing]
        )
    except subprocess.CalledProcessError as e:
        print(f"[updater] pip install failed: {e}")
        print("[updater] You may need to install them manually.")


def list_remote_files() -> list[dict]:
    """Return [{path, sha, download_url}] for every blob in the branch."""
    files = []
    stack = [""]
    while stack:
        subdir = stack.pop()
        url = f"{API_BASE}/contents/{subdir}" if subdir else f"{API_BASE}/contents"
        r = requests.get(url, timeout=20,
                         headers={"User-Agent": "python-photoshop-updater"})
        if r.status_code == 404:
            continue
        r.raise_for_status()
        for item in r.json():
            if item["type"] == "file":
                files.append({
                    "path": item["path"],
                    "sha": item["sha"],
                    "download_url": item["download_url"],
                })
            elif item["type"] == "dir":
                stack.append(item["path"])
    return files


def download_file(url: str) -> bytes:
    r = requests.get(url, timeout=30,
                     headers={"User-Agent": "python-photoshop-updater"})
    r.raise_for_status()
    return r.content


# ---------- install from scratch ----------
def install_full_app() -> bool:
    """Download the whole repo when the app isn't present locally."""
    print("[updater] App not found — installing full repository…")
    try:
        r = requests.get(ARCHIVE_URL, timeout=60,
                         headers={"User-Agent": "python-photoshop-updater"},
                         stream=True)
        r.raise_for_status()
        tmp_zip = ROOT / "_repo.zip"
        with open(tmp_zip, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

        # Extract
        import zipfile
        with zipfile.ZipFile(tmp_zip) as zf:
            zf.extractall(ROOT)

        # Move the extracted root folder's contents up into ROOT
        extracted_root = next(
            (d for d in ROOT.iterdir()
             if d.is_dir() and d.name.endswith(GITHUB_BRANCH)),
            None
        )
        if extracted_root:
            for child in extracted_root.iterdir():
                dest = ROOT / child.name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                shutil.move(str(child), str(dest))
            extracted_root.rmdir()

        tmp_zip.unlink(missing_ok=True)
        print("[updater] ✅ Full repository installed.")
        return True
    except Exception as e:
        print(f"[updater] ❌ Install failed: {e}")
        return False


# ---------- incremental update ----------
def update_files() -> int:
    """Download files whose git SHA differs from cached state."""
    try:
        remote_files = list_remote_files()
    except Exception as e:
        print(f"[updater] Could not reach GitHub ({e}). Launching as-is.")
        return 0

    state = load_state()
    remote_shas = {f["path"]: f["sha"] for f in remote_files}

    updated = 0
    for f in remote_files:
        rel = f["path"]
        if should_skip(rel):
            continue
        local = ROOT / rel
        local_sha = state.get(rel)

        if not local.is_file() or local_sha != f["sha"]:
            try:
                data = download_file(f["download_url"])
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(data)
                state[rel] = f["sha"]
                updated += 1
                print(f"[updater]   updated: {rel}")
            except Exception as e:
                print(f"[updater]   FAILED {rel}: {e}")

    # Detect files removed upstream
    local_files = {
        str(p.relative_to(ROOT)).replace(os.sep, "/")
        for p in ROOT.rglob("*") if p.is_file()
    }
    for rel in local_files:
        if should_skip(rel):
            continue
        if rel not in remote_shas and state.get(rel):
            try:
                (ROOT / rel).unlink()
                state.pop(rel, None)
                updated += 1
                print(f"[updater]   removed: {rel}")
            except Exception:
                pass

    save_state(state)
    return updated


# ---------- launch ----------
def launch_app() -> int:
    if not (ROOT / "main.py").is_file():
        print("[updater] ❌ main.py not found. Cannot launch.")
        return 1
    print("[updater] Launching main.py…")
    try:
        subprocess.check_call([sys.executable, str(ROOT / "main.py")])
        return 0
    except subprocess.CalledProcessError as e:
        print(f"[updater] App exited with code {e.returncode}")
        return e.returncode


# ---------- main flow ----------
def main() -> int:
    print("[updater] Python Photoshop updater")
    print(f"[updater] Location: {ROOT}")

    # 1. Is the app installed?
    if not is_app_installed():
        print("[updater] No existing installation detected.")
        if not install_full_app():
            return 1

    # 2. Install missing dependencies
    missing = check_dependencies()
    if missing:
        install_dependencies(missing)
        # Re-check after install attempt
        still_missing = check_dependencies()
        if still_missing:
            print(f"[updater] ⚠ Still missing: {', '.join(still_missing)}")
            print("[updater] Attempting to launch anyway…")

    # 3. Incremental update
    print("[updater] Checking for updates…")
    updated = update_files()
    if updated:
        print(f"[updater] ✅ {updated} file(s) updated.")
    else:
        print("[updater] ✅ Already up to date.")

    # 4. Launch
    return launch_app()


if __name__ == "__main__":
    sys.exit(main())
