"""Thin wrapper around the ImageMagick CLI."""
import subprocess
import shutil


def is_available() -> bool:
    return shutil.which("magick") is not None or shutil.which("convert") is not None


def _bin() -> str:
    return "magick" if shutil.which("magick") else "convert"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def create_blank(path: str, width: int, height: int, color: str = "white") -> str:
    if color == "transparent":
        color = "none"
    _run([_bin(), "-size", f"{width}x{height}", f"xc:{color}", path])
    return path


def apply_filter(src: str, dst: str, filter_args: list[str]) -> str:
    _run([_bin(), src, *filter_args, dst])
    return dst


def get_info(path: str) -> str:
    return _run([_bin(), "identify", path]).stdout


def load_any_image(src_path: str, max_dim: int = 4000) -> str:
    """Convert any ImageMagick-supported format (SVG, TIFF, HEIC…) to a temp PNG.
    Returns the temp PNG path."""
    import tempfile
    out = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
    _run([_bin(), str(src_path), "-resize", f"{max_dim}x{max_dim}>", out])
    return out


def apply_effects(src_path: str, effects: dict) -> str:
    """Apply {grayscale, sepia, blur, sharpen, brightness, contrast, hue}
    and return a temp PNG path."""
    import tempfile
    out = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name

    cmd = [_bin(), str(src_path)]
    if effects.get("grayscale"):
        cmd += ["-colorspace", "Gray"]
    if effects.get("sepia"):
        cmd += ["-sepia-tone", "80%"]
    if effects.get("blur", 0) > 0:
        cmd += ["-blur", f"0x{effects['blur']}"]
    if effects.get("sharpen", 0) > 0:
        cmd += ["-sharpen", f"0x{effects['sharpen']}"]
    if effects.get("brightness", 0) != 0:
        cmd += ["-brightness-contrast", f"{effects['brightness']}x0"]
    if effects.get("contrast", 0) != 0:
        cmd += ["-brightness-contrast", f"0x{effects['contrast']}"]
    hue = effects.get("hue", 0)
    if hue:
        # ImageMagick's modulate expects hue % where 100 = no shift,
        # and wraps around. Convert degrees → %.
        pct = 100 + (hue / 360.0) * 100.0
        cmd += ["-modulate", f"100,100,{pct:.2f}"]
    cmd.append(out)
    _run(cmd)
    return out
