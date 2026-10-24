"""CollabSession — single object that handles host OR client role.
Main window connects its signals; the session sends/receives over TCP and
discovers via UDP (client-only)."""
import socket
import threading
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QImage

from extensions.collab.discovery import CollabDiscovery
from extensions.collab.protocol import (
    TCP_PORT, UDP_PORT, encode, decode_line,
    image_to_b64, b64_to_image, broadcast_discovery, parse_discovery,
)


class CollabSession(QObject):
    # ---- signals the main window listens to ----
    connected       = pyqtSignal(str)                    # peer name
    disconnected    = pyqtSignal(str)                    # reason
    remoteImage     = pyqtSignal(object)                 # QImage snapshot
    remoteCursor    = pyqtSignal(str, int, int)          # name, x, y
    published       = pyqtSignal(str, object)            # name, QImage
    hostFound       = pyqtSignal(str, str)               # host_name, ip
    statusMessage   = pyqtSignal(str)
    structureMessage = pyqtSignal(dict)
    chatReceived    = pyqtSignal(str, str)   # name, text

    def __init__(self, role: str, my_name: str, project_name: str,
                 width: int, height: int, parent=None):
        super().__init__(parent)
        assert role in ("host", "client")
        self.role = role
        self.my_name = my_name
        self.project_name = project_name
        self.width, self.height = width, height

        self.sock: socket.socket | None = None
        self.peers: dict[socket.socket, str] = {}
        self.lock = threading.Lock()
        self.host_image_provider = None    # callable -> QImage (host only)
        self.server: socket.socket | None = None
        self.udp: socket.socket | None = None
        self._stop = threading.Event()

    # ================================================================ host
    def start_host(self):
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind(("0.0.0.0", TCP_PORT))
            self.server.listen(8)
        except OSError as e:
            self.statusMessage.emit(f"Host error: {e}")
            return

        # Zeroconf discovery (robust, handles all interfaces)
        self._discovery = CollabDiscovery()
        self._discovery.publish(self.project_name, TCP_PORT)


        # immediate burst — 3 quick beacons so a listening client connects fast
        def _burst():
            import time as _t
            for _ in range(3):
                try:
                    thumb_b64 = ""
                    if self.host_image_provider is not None:
                        img = self.host_image_provider()
                        if img is not None and not img.isNull():
                            from PyQt5.QtCore import QBuffer, QIODevice
                            import base64
                            t = img.scaledToWidth(96, 1)
                            buf = QBuffer(); buf.open(QIODevice.WriteOnly)
                            t.save(buf, "PNG")
                            thumb_b64 = base64.b64encode(bytes(buf.data())).decode("ascii")
                    with self.lock:
                        n_peers = len(self.peers)
                except Exception:
                    pass
                _t.sleep(0.1)
        threading.Thread(target=_burst, daemon=True).start()


        threading.Thread(target=self._host_accept_loop, daemon=True).start()
        self.statusMessage.emit(f"Hosting '{self.project_name}' on port {TCP_PORT}")

    def _host_accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, addr = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._host_peer_loop,
                             args=(conn, addr), daemon=True).start()

    def _host_peer_loop(self, conn, addr):
        name = f"peer-{addr[1]}"
        try:
            f = conn.makefile("r", encoding="utf-8", newline="\n")
            hello = decode_line(f.readline().encode("utf-8"))
            if not hello or hello.get("type") != "hello":
                return
            name = str(hello.get("name", name))[:32] or name
            with self.lock:
                self.peers[conn] = name
            self.connected.emit(f"{name} ({addr[0]})")
            conn.sendall(encode({
                "type": "welcome",
                "name": self.project_name,
                "width": self.width,
                "height": self.height,
            }))

            # send the current canvas immediately so the client is in sync
            if self.host_image_provider is not None:
                try:
                    img = self.host_image_provider()
                    if img is not None and not img.isNull():
                        conn.sendall(encode({"type": "stroke",
                                             "data": image_to_b64(img)}))
                except Exception as e:
                    print(f"[host] initial image send failed: {e}")

            for line in f:
                msg = decode_line(line.encode("utf-8"))
                if not msg:
                    continue
                self._handle_peer_message(conn, name, msg)
        except Exception as e:
            print(f"[host] peer error: {e}")
        finally:
            with self.lock:
                self.peers.pop(conn, None)
            try: conn.close()
            except Exception: pass
            self.disconnected.emit(f"{name} left")

    # ================================================================ client
    def start_client(self, host_ip: str | None = None):
        """Client mode. If host_ip is provided, connect immediately;
        otherwise browse via Zeroconf."""
        if host_ip:
            self._client_connect(host_ip)
            return
        self._discovery = CollabDiscovery(
            on_found=lambda info, ip: self.hostFound.emit(info["name"], ip))
        self._discovery.browse()
        self.statusMessage.emit("Searching for hosts …")

    def _client_discovery_loop(self):
        found_once = False
        while not self._stop.is_set():
            try:
                data, addr = self.udp.recvfrom(2048)
            except OSError:
                return
            info = parse_discovery(data)
            if info is None:
                continue
            host_name = info.get("name", "Host")
            host_ip = addr[0]
            self.hostFound.emit(host_name, host_ip)
            if not found_once and self.sock is None:
                found_once = True
                self._client_connect(host_ip)

    def _client_connect(self, host_ip):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((host_ip, TCP_PORT))
            self.sock = s
            s.sendall(encode({"type": "hello", "name": self.my_name}))
            threading.Thread(target=self._client_read_loop, daemon=True).start()
        except Exception as e:
            self.sock = None
            self.statusMessage.emit(f"Connect failed: {e}")

    def _client_read_loop(self):
        try:
            f = self.sock.makefile("r", encoding="utf-8", newline="\n")
            for line in f:
                msg = decode_line(line.encode("utf-8"))
                if not msg:
                    continue
                t = msg.get("type")
                if t == "welcome":
                    self.width = int(msg.get("width", self.width))
                    self.height = int(msg.get("height", self.height))
                    self._welcome_layers = msg.get("layers", [])
                    self.connected.emit(f"{msg.get('name', 'Host')} (host)")
                elif t == "stroke":
                    img = b64_to_image(msg.get("data", ""))
                    if img is not None:
                        self.remoteImage.emit((img, int(msg.get("layer", 0))))
                elif t == "cursor":
                    self.remoteCursor.emit(
                        str(msg.get("name", "?")),
                        int(msg.get("x", 0)),
                        int(msg.get("y", 0)))
                elif t == "chat":
                    self.chatReceived.emit(str(msg.get("name", "?")),
                                           str(msg.get("text", "")))
                elif t in ("layer_add", "layer_del", "layer_reorder",
                           "layer_visible", "layer_opacity", "layer_rasterize",
                           "shape_add", "shape_edit", "shape_delete"):
                    self.structureMessage.emit(msg)
                elif t == "publish":
                    img = b64_to_image(msg.get("data", ""))
                    if img is not None:
                        self.published.emit(str(msg.get("name", "project")), img)
                elif t == "bye":
                    break
        except Exception as e:
            print(f"[client] read error: {e}")
        finally:
            try: self.sock.close()
            except Exception: pass
            self.sock = None
            self.disconnected.emit("Host closed connection")

    # ================================================================ shared
    def _handle_peer_message(self, sender, name, msg):
        t = msg.get("type")

        # ---------- chat: relay + deliver locally ----------
        if t == "chat":
            chat_name = str(msg.get("name", name))
            text = str(msg.get("text", ""))[:1000]
            self.chatReceived.emit(chat_name, text)
            self._broadcast({"type": "chat", "name": chat_name, "text": text},
                            exclude=sender)
            return

        # ---------- stroke ----------
        if t == "stroke":
            img = b64_to_image(msg.get("data", ""))
            if img is not None:
                layer_idx = int(msg.get("layer", 0))
                self.remoteImage.emit((img, layer_idx))
                self._broadcast({"type": "stroke",
                                 "layer": layer_idx,
                                 "data": msg.get("data", "")},
                                exclude=sender)
            return

        # ---------- cursor ----------
        if t == "cursor":
            x, y = int(msg.get("x", 0)), int(msg.get("y", 0))
            self.remoteCursor.emit(name, x, y)
            self._broadcast({"type": "cursor", "name": name, "x": x, "y": y},
                            exclude=sender)
            return

        # ---------- structure: apply on host + relay to all other peers ----------
        if t in ("layer_add", "layer_del", "layer_reorder", "layer_visible",
                 "layer_opacity", "layer_rasterize",
                 "shape_add", "shape_edit", "shape_delete"):
            # host applies it to its own model so host's view stays in sync
            self.structureMessage.emit(msg)
            # and relays to all other peers so *everyone* sees it
            self._broadcast(msg, exclude=sender)
            return

    def send_stroke(self, img):
        """Send a full-canvas snapshot. Guarded so a None or empty image
        never crashes the host, and self-echoes are impossible."""
        if img is None:
            return
        try:
            if img.isNull():
                return
        except Exception:
            pass

        # dedupe consecutive identical sends (5 ms window)
        import hashlib, time
        try:
            from PyQt5.QtCore import QBuffer, QIODevice
            buf = QBuffer(); buf.open(QIODevice.WriteOnly)
            img.save(buf, "PNG")
            data_bytes = bytes(buf.data())
            h = hashlib.md5(data_bytes).hexdigest()
        except Exception:
            return

        now = time.time()
        if getattr(self, "_last_stroke_hash", None) == h and \
                now - getattr(self, "_last_stroke_ts", 0) < 0.05:
            return
        self._last_stroke_hash = h
        self._last_stroke_ts = now

        data = {"type": "stroke",
                "layer": getattr(self, "_active_layer_index", 0),
                "data": image_to_b64(img)}
        if self.role == "host":
            self._broadcast(data)
        else:
            self._send_to_host(data)

    def send_cursor(self, x: int, y: int):
        data = {"type": "cursor", "name": self.my_name, "x": x, "y": y}
        if self.role == "host":
            self._broadcast(data)
        else:
            self._send_to_host(data)

    def publish(self, img: QImage, name: str):
        data = {"type": "publish", "name": name,
                "data": image_to_b64(img)}
        self._broadcast(data)

    def close(self):
        """Cleanly tear down the session — stop threads, close sockets, publish cleanup."""
        self._stop.set()

        # Zeroconf unpublish (host) or browse stop (client)
        try:
            if getattr(self, "_discovery", None) is not None:
                self._discovery.close()
        except Exception:
            pass

        # Say bye to peers (host) or host (client)
        try:
            if self.role == "host":
                self._broadcast({"type": "bye"})
            elif self.sock is not None:
                try:
                    self.sock.sendall(encode({"type": "bye"}))
                except Exception:
                    pass
        except Exception:
            pass

        # Close all peer connections
        with self.lock:
            for conn in list(self.peers.keys()):
                try:
                    conn.close()
                except Exception:
                    pass
            self.peers.clear()

        # Close server socket
        try:
            if getattr(self, "server", None) is not None:
                self.server.close()
        except Exception:
            pass

        # Close client socket
        try:
            if getattr(self, "sock", None) is not None:
                self.sock.close()
                self.sock = None
        except Exception:
            pass

    # ---------- wire helpers ----------
    def _send_to_host(self, msg):
        if self.sock is None:
            return
        try:
            self.sock.sendall(encode(msg))
        except (BrokenPipeError, ConnectionResetError, OSError):
            try: self.sock.close()
            except Exception: pass
            self.sock = None
            self.disconnected.emit("Host connection lost")
        except Exception:
            pass

    def _broadcast(self, msg, exclude=None):
        payload = encode(msg)
        dead = []
        with self.lock:
            for conn in list(self.peers.keys()):
                if conn is exclude:
                    continue
                try:
                    conn.sendall(payload)
                except Exception:
                    dead.append(conn)
            for conn in dead:
                self.peers.pop(conn, None)
                try: conn.close()
                except Exception: pass

    def _broadcast_image(self, img, exclude=None):
        self._broadcast({"type": "stroke", "data": image_to_b64(img)},
                        exclude=exclude)


    # ---------------- structure broadcasts (host → all clients) ----------------
    def broadcast_structure(self, msg: dict):
        """Only meaningful on the host — sends a structural update to peers."""
        if self.role != "host":
            return
        self._broadcast(msg)

    def welcome_with_project(self, conn, project):
        """Send the full project state to a newly connected peer."""
        from extensions.collab.protocol import layer_to_wire
        layers = [layer_to_wire(l) for l in project.layers]
        conn.sendall(encode({
            "type": "welcome",
            "name": self.project_name,
            "width": project.width,
            "height": project.height,
            "layers": layers,
        }))


    def send_chat(self, text: str):
        """Broadcast a chat message."""
        msg = {"type": "chat", "name": self.my_name, "text": text[:1000]}
        if self.role == "host":
            self._broadcast(msg)
        else:
            self._send_to_host(msg)
