"""Client — UDP discovery listener, TCP dial, paint surface."""
import socket
import threading
import time
import json
from PyQt5.QtWidgets import (
    QMainWindow, QLabel, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QInputDialog, QMessageBox
)
from PyQt5.QtCore import QTimer, pyqtSignal, QObject, Qt

from collab_test.paint_widget import PaintWidget
from collab_test.protocol import TCP_PORT, UDP_PORT, encode, decode_line, parse_discovery


class _Bridge(QObject):
    connected = pyqtSignal(str, int, int)   # host_name, w, h
    disconnected = pyqtSignal(str)
    remoteStroke = pyqtSignal(object)
    remoteCursor = pyqtSignal(str, int, int)
    published = pyqtSignal(str)


class ClientWindow(QMainWindow):
    def __init__(self, my_name="guest"):
        super().__init__()
        self.my_name = my_name or "guest"
        self.setWindowTitle(f"Collab Client — {self.my_name}")

        self.paint = PaintWidget()
        self.paint.strokeReady.connect(self._on_local_stroke)
        self.paint.cursorMoved.connect(self._on_local_cursor)

        self.sock: socket.socket | None = None
        self.read_thread: threading.Thread | None = None
        self.host_addr = None

        self.bridge = _Bridge()
        self.bridge.connected.connect(self._on_connected)
        self.bridge.disconnected.connect(self._on_disconnected)
        self.bridge.remoteStroke.connect(self.paint.apply_remote_image)
        self.bridge.remoteCursor.connect(self.paint.set_remote_cursor)
        self.bridge.published.connect(self._on_published)

        # UI
        top = QHBoxLayout()
        self.status = QLabel("Searching for host …")
        top.addWidget(self.status)
        top.addStretch()

        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.addLayout(top)
        v.addWidget(self.paint)
        self.setCentralWidget(wrap)

        self.resize(960, 680)

        # --- start UDP discovery ---
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.udp.bind(("", UDP_PORT))
        except OSError as e:
            QMessageBox.critical(self, "Discovery error",
                                 f"Could not bind UDP {UDP_PORT}: {e}")
            return
        threading.Thread(target=self._discovery_loop, daemon=True).start()

    # ---------------- discovery ----------------
    def _discovery_loop(self):
        while True:
            try:
                data, addr = self.udp.recvfrom(2048)
            except OSError:
                return
            info = parse_discovery(data)
            if info is None:
                continue
            host_ip = addr[0]
            host_name = info.get("name", "Host")
            port = int(info.get("port", TCP_PORT))
            # connect once
            if self.sock is None and self.host_addr is None:
                self.host_addr = (host_ip, port)
                self.bridge.connected.emit(host_name, 0, 0)  # 0,0 = placeholder until welcome
                self._connect(host_ip, port)

    # ---------------- TCP connect ----------------
    def _connect(self, host_ip, port):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((host_ip, port))
            self.sock = s
            # send hello
            s.sendall(encode({"type": "hello", "name": self.my_name}))
            threading.Thread(target=self._read_loop, daemon=True).start()
        except Exception as e:
            self.sock = None
            self.host_addr = None
            self.status.setText(f"Connect failed: {e}")

    def _read_loop(self):
        try:
            f = self.sock.makefile("r", encoding="utf-8", newline="\n")
            for line in f:
                msg = decode_line(line.encode("utf-8"))
                if not msg:
                    continue
                t = msg.get("type")
                if t == "welcome":
                    self.bridge.connected.emit(
                        msg.get("name", "Host"),
                        int(msg.get("width", 0)),
                        int(msg.get("height", 0)))
                elif t == "stroke":
                    img = self._decode_image(msg)
                    if img is not None:
                        self.bridge.remoteStroke.emit(img)
                elif t == "cursor":
                    self.bridge.remoteCursor.emit(
                        str(msg.get("name", "?")),
                        int(msg.get("x", 0)),
                        int(msg.get("y", 0)))
                elif t == "publish":
                    self.bridge.published.emit(str(msg.get("name", "project")))
                elif t == "bye":
                    break
        except Exception as e:
            print(f"[client] read error: {e}")
        finally:
            self.bridge.disconnected.emit("Host closed connection")
            try: self.sock.close()
            except Exception: pass
            self.sock = None
            self.host_addr = None

    # ---------------- event handlers ----------------
    def _on_connected(self, host_name, w, h):
        self.status.setText(f"Connected to {host_name}")

    def _on_disconnected(self, why):
        self.status.setText(f"Disconnected: {why}")

    def _on_local_stroke(self, img):
        if self.sock is None:
            return
        import base64
        from PyQt5.QtCore import QBuffer, QIODevice
        buf = QBuffer(); buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        b64 = base64.b64encode(bytes(buf.data())).decode("ascii")
        try:
            self.sock.sendall(encode({"type": "stroke", "data": b64}))
        except Exception:
            pass

    def _on_local_cursor(self, x, y):
        if self.sock is None:
            return
        try:
            self.sock.sendall(encode({"type": "cursor", "name": self.my_name,
                                      "x": x, "y": y}))
        except Exception:
            pass
        self.paint.set_remote_cursor(self.my_name, x, y, "#20c040")

    def _decode_image(self, msg):
        import base64
        from PyQt5.QtGui import QImage
        try:
            raw = base64.b64decode(msg.get("data", ""))
            img = QImage()
            img.loadFromData(raw, "PNG")
            return img if not img.isNull() else None
        except Exception:
            return None

    def _on_published(self, name):
        # save a local copy of what we see
        from pathlib import Path
        target = Path.home() / "Downloads" / f"{name}_collab.png"
        target.parent.mkdir(exist_ok=True)
        self.paint.image.save(str(target), "PNG")
        self.status.setText(f"Host published → saved {target}")

    def closeEvent(self, e):
        try:
            if self.sock:
                self.sock.sendall(encode({"type": "bye"}))
                self.sock.close()
        except Exception:
            pass
        super().closeEvent(e)
