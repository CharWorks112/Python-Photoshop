"""Wire protocol — newline-delimited JSON over TCP.
UDP discovery is plain JSON datagrams."""
import json
import socket

TCP_PORT = 51000
UDP_PORT = 51001
MAGIC = "PYPHOTOSHOP_COLLAB_V1"


def encode(msg: dict) -> bytes:
    """JSON + newline. Safe for framing."""
    return (json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")


def decode_line(line: bytes):
    """Return dict or None if invalid."""
    try:
        return json.loads(line.decode("utf-8"))
    except Exception:
        return None


def broadcast_discovery(project_name: str, sender_socket: socket.socket):
    """Host calls this every ~2s."""
    msg = {"magic": MAGIC, "name": project_name, "port": TCP_PORT}
    data = json.dumps(msg).encode("utf-8")
    try:
        sender_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sender_socket.sendto(data, ("255.255.255.255", UDP_PORT))
        # also broadcast to the local subnet explicitly — some kernels
        # ignore the all-ones broadcast on certain interfaces
    except Exception:
        pass


def parse_discovery(data: bytes):
    try:
        msg = json.loads(data.decode("utf-8"))
        if msg.get("magic") != MAGIC:
            return None
        return msg
    except Exception:
        return None
