"""Export a project (or a single layer) using ImageMagick for encoding only."""
from pathlib import Path
from core import imagemagick
from core.layer import merge_layers


FORMATS = {
    "PNG":  {"ext": "png",  "lossy": False},
    "JPEG": {"ext": "jpg",  "lossy": True},
    "WEBP": {"ext": "webp", "lossy": True},
}


def export_project(project, out_path: Path, fmt: str, quality: int = 90) -> Path:
    """Composite in-memory → write temp PNG → ImageMagick converts/compresses."""
    # Compose from the *live* layer images (never touches disk / stale PNGs)
    merged = merge_layers(project.layers, project.width, project.height,
                          background=project.background)

    tmp_png = out_path.with_suffix(".flat.tmp.png")
    tmp_png.parent.mkdir(parents=True, exist_ok=True)
    if not merged.save(str(tmp_png), "PNG"):
        raise IOError(f"Could not write temp PNG to {tmp_png}")

    ext = FORMATS[fmt]["ext"]
    if out_path.suffix.lower() != f".{ext}":
        out_path = out_path.with_suffix(f".{ext}")

    if FORMATS[fmt]["lossy"]:
        imagemagick._run([
            imagemagick._bin(), str(tmp_png),
            "-background", "white", "-alpha", "remove", "-alpha", "off",
            "-quality", str(quality),
            str(out_path),
        ])
    else:
        imagemagick._run([imagemagick._bin(), str(tmp_png), str(out_path)])

    tmp_png.unlink(missing_ok=True)
    return out_path
