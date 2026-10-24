"""Host — TCP server, UDP broadcaster, one canvas."""
import socket
import threading
import time
import json
from PyQt5.QtWidgets import QMainWindow, QLabel, QWidget, QVBoxLayout, QHBoxLayout, QPushButton
from PyQt5.QtCore import QTimer, pyqtSignal, QObject, Qt

from collab_test.paint_widget import PaintWidget
from collab_test.protocol import (
    TCP_PORT, UDP_PORT, encode, decode_line, broadcast_discovery
)


class _Bridge(QObject):
    """Cross-thread signal emitter — client sockets live on worker threads."""
    peerConnected = pyqtSignal(str)
    peerDisconnected = pyqtSignal(str)
    remoteStroke = pyqtSignal(object)     # QImage
    remoteCursor = pyqtSignal(str, int, int)


class HostWindow(QMainWindow):
    def __init__(self, project_name="Host Canvas"):
        super().__init__()
        self.setWindowTitle(f"Collab Host — {project_name}")
        self.project_name = project_name

        self.paint = PaintWidget()
        self.paint.strokeReady.connect(self._on_local_stroke)
        self.paint.cursorMoved.connect(self._on_local_cursor)

        # peers: sock -> {"name": str, "thread": Thread}
        self.peers: dict[socket.socket, dict] = {}
        self.peers_lock = threading.Lock()

        self.bridge = _Bridge()
        self.bridge.peerConnected.connect(self._log)
        self.bridge.peerDisconnected.connect(self._log)
        self.bridge.remoteStroke.connect(self.paint.apply_remote_image)
        self.bridge.remoteCursor.connect(self._apply_remote_cursor)

        # UI
        top = QHBoxLayout()
        self.status = QLabel(f"Listening on {TCP_PORT} …")
        top.addWidget(self.status)
        top.addStretch()

        self.publish_btn = QPushButton("Publish")
        self.publish_btn.clicked.connect(self._publish)
        top.addWidget(self.publish_btn)

        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.addLayout(top)
        v.addWidget(self.paint)
        self.setCentralWidget(wrap)

        self.resize(960, 680)

        # --- TCP server ---
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("0.0.0.0", TCP_PORT))
        self.server.listen(8)
        threading.Thread(target=self._accept_loop, daemon=True).start()

        # --- UDP discovery beacon ---
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.discovery_timer = QTimer(self)
        self.discovery_timer.timeout.connect(
            lambda: broadcast_discovery(self.project_name, self.udp))
        self.discovery_timer.start(2000)
        broadcast_discovery(self.project_name, self.udp)

    # ---------------- logging ----------------
    def _log(self, msg: str):
        self.status.setText(msg)
        print(f"[host] {msg}")

    # ---------------- accept loop ----------------
    def _accept_loop(self):
        while True:
            try:
                conn, addr = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._peer_loop, args=(conn, addr),
                             daemon=True).start()

    # ---------------- per-peer loop ----------------
    def _peer_loop(self, conn: socket.socket, addr):
        name = f"peer-{addr[1]}"
        try:
            # first message must be {"type":"hello","name":...}
            f = conn.makefile("r", encoding="utf-8", newline="\n")
            hello = decode_line(f.readline().encode("utf-8"))
            if not hello or hello.get("type") != "hello":
                conn.close()
                return
            name = str(hello.get("name", name))[:32] or name
            with self.peers_lock:
                self.peers[conn] = {"name": name, "f": f}
            self.bridge.peerConnected.emit(f"{name} connected from {addr[0]}")

            # send welcome + current image
            self._send(conn, {
                "type": "welcome",
                "name": self.project_name,
                "width": self.paint.image.width(),
                "height": self.paint.image.height(),
            })
            self._send_image(conn, self.paint.image)

            # read loop
            for line in f:
                msg = decode_line(line.encode("utf-8"))
                if not msg:
                    continue
                self._handle_peer_message(conn, name, msg)
        except Exception as e:
            print(f"[host] peer loop error: {e}")
        finally:
            with self.peers_lock:
                self.peers.pop(conn, None)
            try: conn.close()
            except Exception: pass
            self.bridge.peerDisconnected.emit(f"{name} disconnected")

    def _handle_peer_message(self, sender: socket.socket, name: str, msg: dict):
        t = msg.get("type")
        if t == "stroke":
            img = self._decode_image(msg)
            if img is not None:
                self.paint.apply_remote_image(img)
                self._broadcast_image(img, exclude=sender)
        elif t == "cursor":
            x, y = int(msg.get("x", 0)), int(msg.get("y", 0))
            self.paint.set_remote_cursor(name, x, y)
            self._broadcast({"type": "cursor", "name": name, "x": x, "y": y},
                            exclude=sender)

    # ---------------- local event forwarding ----------------
    def _on_local_stroke(self, img):
        self._broadcast_image(img)

    def _on_local_cursor(self, x, y):
        self._broadcast({"type": "cursor", "name": "host", "x": x, "y": y})
        self.paint.set_remote_cursor("host", x, y, "#3060ff")

    def _apply_remote_cursor(self, name, x, y):
        self.paint.set_remote_cursor(name, x, y)

    # ---------------- wire helpers ----------------
    def _send(self, conn: socket.socket, msg: dict):
        try:
            conn.sendall(encode(msg))
        except Exception:
            pass

    def _send_image(self, conn: socket.socket, img):
        import base64, io
        from PyQt5.QtCore import QBuffer, QIODevice
        buf = QBuffer(); buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        b64 = base64.b64encode(bytes(buf.data())).decode("ascii")
        self._send(conn, {"type": "stroke", "data": b64})

    def _decode_image(self, msg: dict):
        import base64
        from PyQt5.QtGui import QImage
        try:
            raw = base64.b64decode(msg.get("data", ""))
            img = QImage()
            img.loadFromData(raw, "PNG")
            return img if not img.isNull() else None
        except Exception:
            return None

    def _broadcast(self, msg: dict, exclude=None):
        payload = encode(msg)
        with self.peers_lock:
            for conn in list(self.peers.keys()):
                if conn is exclude:
                    continue
                try:
                    conn.sendall(payload)
                except Exception:
                    pass

    def _broadcast_image(self, img, exclude=None):
        import base64
        from PyQt5.QtCore import QBuffer, QIODevice
        buf = QBuffer(); buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        b64 = base64.b64encode(bytes(buf.data())).decode("ascii")
        self._broadcast({"type": "stroke", "data": b64}, exclude=exclude)

    # ---------------- publish ----------------
    def _publish(self):
        self._broadcast({"type": "publish", "name": self.project_name,
                         "width": self.paint.image.width(),
                         "height": self.paint.image.height()})
        self._log("Published to all clients.")

    def closeEvent(self, e):
        self.discovery_timer.stop()
        self._broadcast({"type": "bye"})
        try: self.server.close()
        except Exception: pass
        for conn in list(self.peers.keys()):
            try: conn.close()
            except Exception: pass
        super().closeEvent(e)
