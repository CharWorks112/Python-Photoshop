"""Writes a compact snapshot of open tabs to disk for update-time restore."""
import json
import base64
from pathlib import Path

BACKUP_PATH = Path.home() / ".python_photoshop_session.json"


def save_session(main_window) -> bool:
    """Serialize every open tab into BACKUP_PATH."""
    try:
        tabs = []
        for i in range(main_window.tabs.count()):
            canvas = main_window.tabs.widget(i)
            if canvas.project is None:
                continue
            proj = canvas.project
            layers = []
            for layer in proj.layers:
                if hasattr(layer, "image"):
                    from PyQt5.QtCore import QBuffer, QIODevice
                    buf = QBuffer(); buf.open(QIODevice.WriteOnly)
                    layer.image.save(buf, "PNG")
                    b64 = base64.b64encode(bytes(buf.data())).decode("ascii")
                    layers.append({
                        "kind": "pixel",
                        "name": layer.name,
                        "visible": layer.visible,
                        "opacity": layer.opacity,
                        "data": b64,
                    })
                elif hasattr(layer, "shapes"):
                    layers.append({
                        "kind": "shape",
                        "name": layer.name,
                        "visible": layer.visible,
                        "opacity": layer.opacity,
                        "width": layer.width,
                        "height": layer.height,
                        "shapes": [s.to_dict() for s in layer.shapes],
                    })
            tabs.append({
                "name": proj.name,
                "width": proj.width,
                "height": proj.height,
                "background": proj.background,
                "layers": layers,
                "active_index": i,
            })

        data = {
            "tabs": tabs,
            "active_tab": main_window.tabs.currentIndex(),
            "brush_radius": main_window._brush_radius,
            "fill_tolerance": main_window._fill_tolerance,
            "theme": main_window._theme_name,
        }
        BACKUP_PATH.write_text(json.dumps(data, indent=2))
        return True
    except Exception as e:
        print(f"[session_backup] save failed: {e}")
        return False


def load_session(main_window) -> bool:
    """Restore open tabs from BACKUP_PATH (called with --restore-session)."""
    if not BACKUP_PATH.is_file():
        return False
    try:
        data = json.loads(BACKUP_PATH.read_text())
    except Exception as e:
        print(f"[session_backup] load failed: {e}")
        return False

    from core.project import Project
    from core.layer import PixelLayer
    from core.shape_layer import ShapeLayer
    from PyQt5.QtGui import QImage

    for tab in data.get("tabs", []):
        proj = Project(name=tab["name"], width=tab["width"],
                       height=tab["height"], background=tab["background"])
        layers = []
        for l in tab["layers"]:
            if l["kind"] == "pixel":
                px = PixelLayer(l["name"], tab["width"], tab["height"],
                                fill="transparent")
                raw = base64.b64decode(l["data"])
                img = QImage(); img.loadFromData(raw, "PNG")
                if not img.isNull():
                    px.image = img.convertToFormat(QImage.Format_ARGB32)
                px.visible = l["visible"]; px.opacity = l["opacity"]
                layers.append(px)
            elif l["kind"] == "shape":
                sl = ShapeLayer(l["name"], l["width"], l["height"])
                sl.visible = l["visible"]; sl.opacity = l["opacity"]
                for sd in l["shapes"]:
                    t = sd.get("type")
                    if t == "text":
                        from core.shape_layer import TextShape
                        from PyQt5.QtGui import QFont, QColor
                        f = QFont(sd["font"]["family"], sd["font"]["size"])
                        gc = QColor(sd["glow_color"]) if sd.get("glow_color") else None
                        sl.shapes.append(TextShape(sd["x"], sd["y"], sd["text"],
                                                   f, QColor(sd["color"]),
                                                   sd.get("glow_radius", 0), gc))
                    elif t == "image":
                        from core.image_shape import ImageShape
                        sl.shapes.append(ImageShape.from_wire(sd))
                    elif t == "rect":
                        from core.shape_objects import RectShape
                        sl.shapes.append(RectShape.from_dict(sd, None))
                    elif t == "ellipse":
                        from core.shape_objects import EllipseShape
                        sl.shapes.append(EllipseShape.from_dict(sd, None))
                layers.append(sl)
        proj.layers = layers

        canvas = main_window._new_canvas()
        main_window._add_tab(proj.name, canvas)
        main_window._bind_project_to_canvas(proj, canvas)

    # Activate the last-used tab
    idx = data.get("active_tab", 0)
    if 0 <= idx < main_window.tabs.count():
        main_window.tabs.setCurrentIndex(idx)

    # Delete the backup after a successful restore
    try: BACKUP_PATH.unlink()
    except Exception: pass
    return True
