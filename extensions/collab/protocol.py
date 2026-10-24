"""Wire protocol for collab sessions — newline-delimited JSON + PNG snapshots."""
import base64
import json
import socket

from PyQt5.QtCore import QBuffer, QIODevice
from PyQt5.QtGui import QImage


TCP_PORT = 51000
UDP_PORT = 51001
MAGIC = "PYPHOTOSHOP_COLLAB_V2"


# ---------- message framing ----------
def encode(msg: dict) -> bytes:
    return (json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")


def decode_line(line: bytes) -> dict | None:
    try:
        return json.loads(line.decode("utf-8"))
    except Exception:
        return None


# ---------- image helpers ----------
def image_to_b64(img: QImage) -> str:
    buf = QBuffer(); buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return base64.b64encode(bytes(buf.data())).decode("ascii")


def b64_to_image(data: str) -> QImage | None:
    try:
        raw = base64.b64decode(data)
    except Exception:
        return None
    img = QImage()
    img.loadFromData(raw, "PNG")
    return img if not img.isNull() else None


# ---------- UDP discovery ----------
def _get_subnet_broadcasts() -> list[str]:
    """Best-effort: return broadcast addresses for local IPv4 interfaces."""
    import socket as _s
    result = {"255.255.255.255"}
    try:
        hostname = _s.gethostname()
        try:
            infos = _s.getaddrinfo(hostname, None, _s.AF_INET)
            for info in infos:
                ip = info[4][0]
                if not ip.startswith("127."):
                    parts = ip.rsplit(".", 1)[0]
                    result.add(f"{parts}.255")
        except Exception:
            pass
        # also try to hit the default gateway to discover our subnet
        try:
            probe = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
            probe.connect(("8.8.8.8", 80))
            local_ip = probe.getsockname()[0]
            probe.close()
            parts = local_ip.rsplit(".", 1)[0]
            result.add(f"{parts}.255")
        except Exception:
            pass
    except Exception:
        pass
    return list(result)


def _get_subnet_broadcasts() -> list[str]:
    """Return broadcast addresses for all local IPv4 interfaces."""
    import socket as _s
    targets = {"255.255.255.255", "127.0.0.1"}   # all-ones + loopback
    try:
        hostname = _s.gethostname()
        for info in _s.getaddrinfo(hostname, None, _s.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                parts = ip.rsplit(".", 1)[0]
                targets.add(f"{parts}.255")
        # also probe the default route
        probe = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        local_ip = probe.getsockname()[0]
        probe.close()
        parts = local_ip.rsplit(".", 1)[0]
        targets.add(f"{parts}.255")
    except Exception:
        pass
    return list(targets)


def broadcast_discovery(sock, project_name, thumbnail_b64="", peers=0):
    msg = {"magic": MAGIC, "name": project_name,
           "port": TCP_PORT, "peers": peers, "thumb": thumbnail_b64}
    data = json.dumps(msg).encode("utf-8")
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except Exception:
        pass
    for addr in _get_subnet_broadcasts():
        try:
            sock.sendto(data, (addr, UDP_PORT))
        except Exception:
            pass

def parse_discovery(data: bytes) -> dict | None:
    try:
        msg = json.loads(data.decode("utf-8"))
        return msg if msg.get("magic") == MAGIC else None
    except Exception:
        return None


# ---------- structure messages ----------
# All messages carry {"type": "<verb>", ...}. Host broadcasts to all peers;
# clients apply them locally without re-broadcasting.
#
#   layer_add      {"index": int, "layer": layer_dict}
#   layer_del      {"index": int}
#   layer_reorder  {"old": int, "new": int}
#   layer_visible  {"index": int, "visible": bool}
#   layer_opacity  {"index": int, "opacity": float}
#   layer_rasterize{"index": int, "pixels": b64_png}
#   shape_add      {"layer": int, "shape": shape_dict}
#   shape_edit     {"layer": int, "index": int, "shape": shape_dict}
#   shape_delete   {"layer": int, "index": int}
#   stroke         {"layer": int, "data": b64_png}
#   cursor         {"name": str, "x": int, "y": int}
#   publish        {"name": str, "data": b64_png}
#   welcome        {"name": str, "width": int, "height": int,
#                   "layers": [layer_dict, ...]}

def layer_to_wire(layer, folder=None) -> dict:
    """Serialize a layer to a plain dict. Pixel layers carry their PNG;
    shape layers carry the shape list."""
    import base64
    from PyQt5.QtCore import QBuffer, QIODevice

    d = {
        "kind": "pixel" if hasattr(layer, "image") else "shape",
        "name": getattr(layer, "name", "Layer"),
        "visible": getattr(layer, "visible", True),
        "opacity": getattr(layer, "opacity", 1.0),
    }
    if d["kind"] == "pixel":
        buf = QBuffer(); buf.open(QIODevice.WriteOnly)
        layer.image.save(buf, "PNG")
        d["data"] = base64.b64encode(bytes(buf.data())).decode("ascii")
    else:
        d["width"] = getattr(layer, "width", 0)
        d["height"] = getattr(layer, "height", 0)
        d["shapes"] = [s.to_dict() for s in layer.shapes]
    return d


def layer_from_wire(d: dict):
    """Reconstruct a PixelLayer or ShapeLayer from wire dict."""
    import base64
    from PyQt5.QtGui import QImage

    name = d.get("name", "Layer")
    visible = d.get("visible", True)
    opacity = d.get("opacity", 1.0)

    if d["kind"] == "pixel":
        from core.layer import PixelLayer
        layer = PixelLayer(name, 1, 1, fill="transparent")
        raw = base64.b64decode(d.get("data", ""))
        img = QImage()
        img.loadFromData(raw, "PNG")
        if not img.isNull():
            layer.image = img.convertToFormat(QImage.Format_ARGB32)
        layer.visible = visible
        layer.opacity = opacity
        return layer

    # shape layer
    from core.shape_layer import ShapeLayer
    from core.image_shape import ImageShape
    from core.shape_objects import RectShape, EllipseShape
    from pathlib import Path

    layer = ShapeLayer(name, d.get("width", 1), d.get("height", 1))
    layer.visible = visible
    layer.opacity = opacity
    for sd in d.get("shapes", []):
        t = sd.get("type")
        if t == "image":
            layer.shapes.append(ImageShape.from_dict(sd, Path(".")))
        elif t == "rect":
            layer.shapes.append(RectShape.from_dict(sd, Path(".")))
        elif t == "ellipse":
            layer.shapes.append(EllipseShape.from_dict(sd, Path(".")))
        elif t == "text":
            # TextShape.from_dict logic
            from PyQt5.QtGui import QFont, QColor
            from core.shape_layer import TextShape
            f = QFont(sd["font"]["family"], sd["font"]["size"])
            f.setBold(sd["font"].get("bold", False))
            f.setItalic(sd["font"].get("italic", False))
            gc = QColor(sd["glow_color"]) if sd.get("glow_color") else None
            layer.shapes.append(TextShape(sd["x"], sd["y"], sd["text"], f,
                                          QColor(sd["color"]),
                                          sd.get("glow_radius", 0), gc))
    return layer
