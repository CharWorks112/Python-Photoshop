"""Crash recovery — write a shadow copy of open projects to .autosave.* files."""
from pathlib import Path
import json
import os
import atexit


LOCK_SUFFIX = ".lock"
AUTOSAVE_META = "autosave.json"


def lock_file(project_dir: Path) -> Path:
    return project_dir / f".session{LOCK_SUFFIX}"


def has_crash(project_dir: Path) -> bool:
    """True if the lock exists but the project wasn't cleaned up."""
    return lock_file(project_dir).is_file()


def mark_open(project_dir: Path) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    lock_file(project_dir).write_text(str(os.getpid()))


def mark_clean(project_dir: Path) -> None:
    lf = lock_file(project_dir)
    if lf.is_file():
        try:
            lf.unlink()
        except Exception:
            pass


def autosave_project(project) -> None:
    """Snapshot every layer's pixels to `<project>/autosave/` and metadata."""
    if project is None:
        return
    from core.layer import merge_layers

    folder = project.project_dir / "autosave"
    folder.mkdir(parents=True, exist_ok=True)

    layers_meta = []
    for i, layer in enumerate(project.layers):
        if hasattr(layer, "image"):
            fn = f"layer_{i:02d}.png"
            layer.image.save(str(folder / fn), "PNG")
            layers_meta.append({
                "kind": "pixel",
                "name": layer.name,
                "visible": layer.visible,
                "opacity": layer.opacity,
                "pixels": fn,
            })
        elif hasattr(layer, "shapes"):
            # shape layers persist via their own to_dict; write a synthetic PNG
            fn = f"layer_{i:02d}.png"
            layer.render_to_image().save(str(folder / fn), "PNG")
            d = layer.to_dict(fn)
            d["kind"] = "shape"
            layers_meta.append(d)

    meta = {
        "name": project.name,
        "width": project.width,
        "height": project.height,
        "background": project.background,
        "layers": layers_meta,
    }
    (folder / AUTOSAVE_META).write_text(json.dumps(meta, indent=2))


def load_autosave(project_dir: Path):
    """Return a list of layer descriptors if autosave exists."""
    folder = project_dir / "autosave"
    meta_path = folder / AUTOSAVE_META
    if not meta_path.is_file():
        return None
    try:
        return json.loads(meta_path.read_text()), folder
    except Exception:
        return None
