"""Project model — represents an open document with per-layer PNGs on disk."""
from dataclasses import dataclass, field
from pathlib import Path
import json
import time
import re

from core import imagemagick


PROJECTS_DIR = Path(__file__).resolve().parent.parent / "docs"
PROJECTS_DIR.mkdir(exist_ok=True)


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return s or "Untitled"


@dataclass
class Project:
    name: str
    width: int
    height: int
    background: str = "white"
    created: float = field(default_factory=time.time)
    layers: list = field(default_factory=list)
    image_path: str | None = None

    @property
    def slug(self) -> str:
        return _slug(self.name)

    @property
    def project_dir(self) -> Path:
        return PROJECTS_DIR / self.slug

    @property
    def meta_path(self) -> Path:
        return self.project_dir / "project.json"

    @property
    def canvas_path(self) -> Path:
        return self.project_dir / "canvas.png"

    # ---------- create ----------
    def create_on_disk(self) -> Path:
        self.project_dir.mkdir(parents=True, exist_ok=True)
        imagemagick.create_blank(str(self.canvas_path), self.width, self.height, self.background)
        self.image_path = str(self.canvas_path)
        self.save_meta()
        return self.project_dir

    # ---------- save ----------
    def save_meta(self) -> None:
        from core.layer import merge_layers

        layer_dicts = []
        for i, layer in enumerate(self.layers):
            fname = f"layer_{i:02d}.png"
            layer.save_pixels(self.project_dir / fname)
            layer_dicts.append(layer.to_dict(fname))

        data = {
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "background": self.background,
            "created": self.created,
            "image_path": str(self.canvas_path),
            "layers": layer_dicts,
        }
        self.meta_path.write_text(json.dumps(data, indent=2))

        # Flattened preview — written from live QImage, no ImageMagick round-trip
        merged = merge_layers(self.layers, self.width, self.height, self.background)
        if not merged.save(str(self.canvas_path), "PNG"):
            raise IOError(f"Failed to write preview {self.canvas_path}")

    # ---------- load ----------
    @classmethod
    def load(cls, project_dir: Path) -> "Project":
        data = json.loads((project_dir / "project.json").read_text())
        layers_meta = data.pop("layers", [])
        p = cls(**data)

        from core.layer import PixelLayer
        p.layers = [
            PixelLayer.from_dict(m, project_dir, p.width, p.height)
            for m in layers_meta
        ]
        return p
