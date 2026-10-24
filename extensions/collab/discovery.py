"""Zeroconf-based service discovery — robust mDNS, no raw UDP broadcast."""
import socket
import threading
from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser, ServiceStateChange


SERVICE_TYPE = "_pyphotoshop._tcp.local."


class CollabDiscovery:
    """Handles both publishing (host) and browsing (client) via Zeroconf."""

    def __init__(self, on_found=None, on_lost=None):
        self.zc = Zeroconf()
        self.on_found = on_found
        self.on_lost = on_lost
        self._browser = None
        self._info = None

    # ---------------- HOST ----------------
    def publish(self, project_name: str, port: int, thumbnail_b64: str = "",
                peers: int = 0):
        """Register this host on the network."""
        # Encode metadata into the service properties
        props = {
            b"name": project_name.encode("utf-8"),
            b"peers": str(peers).encode("utf-8"),
            b"thumb": (thumbnail_b64 or "").encode("utf-8"),
        }
        # Get our local IP — Zeroconf needs a real address
        local_ip = self._get_local_ip()
        self._info = ServiceInfo(
            SERVICE_TYPE,
            f"{project_name}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(local_ip)],
            port=port,
            properties=props,
            server=f"pyphotoshop-{local_ip.replace('.', '-')}.local.",
        )
        self.zc.register_service(self._info)
        print(f"[discovery] published '{project_name}' at {local_ip}:{port}")

    def unpublish(self):
        if self._info:
            try:
                self.zc.unregister_service(self._info)
            except Exception:
                pass
            self._info = None

    @staticmethod
    def _get_local_ip() -> str:
        """Find the primary LAN IP (not 127.0.0.1)."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
        finally:
            s.close()

    # ---------------- CLIENT ----------------
    def browse(self):
        """Start browsing for hosts. Calls on_found(info_dict, ip) when seen."""
        self._browser = ServiceBrowser(
            self.zc, SERVICE_TYPE, handlers=[self._on_state_change])

    def _on_state_change(self, zeroconf, service_type, name, state_change):
        if state_change is not ServiceStateChange.Added:
            return
        info = self.zc.get_service_info(service_type, name)
        if not info or not info.addresses:
            return
        ip = socket.inet_ntoa(info.addresses[0])
        props = {}
        for k, v in info.properties.items():
            try:
                kk = k.decode() if isinstance(k, bytes) else str(k)
                vv = (v.decode() if isinstance(v, bytes) else str(v)) if v is not None else ""
                props[kk] = vv
            except Exception:
                continue

        host_info = {
            "name": props.get("name", name.split(".")[0]),
            "peers": int(props.get("peers", 0)),
            "thumb": props.get("thumb", ""),
            "port": info.port,
        }
        if self.on_found:
            self.on_found(host_info, ip)

    def close(self):
        self.unpublish()
        try:
            self.zc.close()
        except Exception:
            pass
