"""Collab lobby — pick Host, or pick a Join target from discovered servers."""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QListWidget, QListWidgetItem, QStackedWidget, QWidget
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
import socket
import threading
import json

from extensions.collab.protocol import UDP_PORT, TCP_PORT, parse_discovery


class _Discovery(QObject):
    """Background UDP listener that reports (name, ip) tuples."""
    hostSeen = pyqtSignal(dict, str)   # info, ip


class CollabLobby(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Collab Paint")
        self.setMinimumSize(520, 480)

        self.mode = None
        self.name = ""
        self.selected_ip = None
        self.selected_host_name = None

        # ---------------- stage 1: mode pick ----------------
        stage1 = QWidget()
        v1 = QVBoxLayout(stage1)
        v1.addWidget(QLabel("<h2>Collab Paint</h2>"))
        hint = QLabel("Host a session or join one on your network.")
        hint.setStyleSheet("color:#888;")
        v1.addWidget(hint)
        v1.addSpacing(10)
        v1.addWidget(QLabel("Your display name:"))
        self.name_edit = QLineEdit("Player")
        v1.addWidget(self.name_edit)
        v1.addSpacing(20)

        host_btn = QPushButton("🎨  Host a Session")
        host_btn.setFixedHeight(40)
        host_btn.clicked.connect(self._host)

        join_btn = QPushButton("🔍  Join a Session")
        join_btn.setFixedHeight(40)
        join_btn.clicked.connect(self._goto_join)

        v1.addWidget(host_btn)
        v1.addWidget(join_btn)
        v1.addStretch()
        v1.addWidget(QLabel("<i>Note: collab auto-flattens to a single layer per entry.</i>"))

        # ---------------- stage 2: server list ----------------
        stage2 = QWidget()
        v2 = QVBoxLayout(stage2)
        v2.addWidget(QLabel("<h2>Available Sessions</h2>"))
        self.status_label = QLabel("Searching …")
        self.status_label.setStyleSheet("color:#888;")
        v2.addWidget(self.status_label)

        self.server_list = QListWidget()
        self.server_list.itemDoubleClicked.connect(self._join_selected)
        v2.addWidget(self.server_list, 1)

        row = QHBoxLayout()
        back_btn = QPushButton("← Back")
        back_btn.clicked.connect(self._goto_mode)
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.clicked.connect(self._clear_and_restart_discovery)
        join_selected_btn = QPushButton("Join Selected →")
        join_selected_btn.clicked.connect(self._join_selected)

        row.addWidget(back_btn)
        row.addWidget(refresh_btn)
        row.addStretch()
        row.addWidget(join_selected_btn)
        v2.addLayout(row)

        # ---------------- switch ----------------
        self.stack = QStackedWidget()
        self.stack.addWidget(stage1)
        self.stack.addWidget(stage2)
        outer = QVBoxLayout(self)
        outer.addWidget(self.stack)

        # discovery
        self._discovery = _Discovery()
        self._discovery.hostSeen.connect(self._on_host_seen)
        self._udp = None
        self._discovery_thread = None
        self._stop = threading.Event()
        from PyQt5.QtCore import QTimer
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._anim_tick)
        self._anim_dots = 0

    # ---------------- mode selection ----------------
    def _host(self):
        self.mode = "host"
        self.name = self.name_edit.text().strip() or "Host"
        self.accept()

    def _goto_join(self):
        self.name = self.name_edit.text().strip() or "Guest"
        self.stack.setCurrentIndex(1)
        self._start_discovery()

    def _goto_mode(self):
        self.stack.setCurrentIndex(0)

    # ---------------- discovery ----------------
    def _clear_and_restart_discovery(self):
        self.server_list.clear()
        self._stop_discovery()
        self._start_discovery()

    def _anim_tick(self):
        self._anim_dots = (self._anim_dots + 1) % 4
        dots = '.' * self._anim_dots
        if self.server_list.count() == 0:
            self.status_label.setText(f'Searching for hosts{dots}')
        else:
            self.status_label.setText(
                f'Found {self.server_list.count()} session(s). '
                f'Double-click to join.')

    def _start_discovery(self):
        from extensions.collab.discovery import CollabDiscovery
        self._stop.clear()
        self.status_label.setText("Searching for hosts …")

        def _on_found(info, ip):
            # must marshal back to the Qt thread
            from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
            QMetaObject.invokeMethod(
                self, "_handle_host_found", Qt.QueuedConnection,
                Q_ARG(dict, info), Q_ARG(str, ip))

        self._discovery = CollabDiscovery(on_found=_on_found)
        self._discovery.browse()

    @__import__('PyQt5.QtCore', fromlist=['pyqtSlot']).pyqtSlot(dict, str)
    def _handle_host_found(self, info, ip):
        self._on_host_seen(info, ip)

    def _stop_discovery(self):
        self._stop.set()
        try:
            if getattr(self, "_discovery", None) is not None:
                self._discovery.close()
                self._discovery = None
        except Exception:
            pass

    def _on_host_seen(self, info: dict, ip: str):
        """info carries name, peers, thumb."""
        name = info.get("name", "Host")
        peers = int(info.get("peers", 0))
        thumb_b64 = info.get("thumb", "")

        # dedupe by ip
        for i in range(self.server_list.count()):
            item = self.server_list.item(i)
            if item.data(Qt.UserRole) == ip:
                item.setText(f"{name}\n{peers} peer(s) · {ip}")
                if thumb_b64:
                    self._set_item_thumb(item, thumb_b64)
                return

        item = QListWidgetItem(f"{name}\n{peers} peer(s) · {ip}")
        item.setData(Qt.UserRole, ip)
        item.setData(Qt.UserRole + 1, name)
        item.setData(Qt.UserRole + 2, peers)
        item.setSizeHint(__import__("PyQt5.QtCore", fromlist=["QSize"]).QSize(0, 72))
        if thumb_b64:
            self._set_item_thumb(item, thumb_b64)
        self.server_list.addItem(item)
        self.status_label.setText(
            f"Found {self.server_list.count()} session(s). Double-click to join.")

    def _set_item_thumb(self, item, thumb_b64):
        try:
            import base64
            from PyQt5.QtGui import QPixmap, QIcon
            raw = base64.b64decode(thumb_b64)
            pix = QPixmap()
            pix.loadFromData(raw, "PNG")
            if not pix.isNull():
                item.setIcon(QIcon(pix))
                self.server_list.setIconSize(
                    __import__("PyQt5.QtCore", fromlist=["QSize"]).QSize(96, 64))
        except Exception:
            pass

    # ---------------- join ----------------
    def _join_selected(self):
        item = self.server_list.currentItem()
        if item is None:
            self.status_label.setText("Select a session first.")
            return
        self.mode = "client"
        self.name = self.name_edit.text().strip() or "Guest"
        self.selected_ip = item.data(Qt.UserRole)
        self.selected_host_name = item.data(Qt.UserRole + 1)
        self._stop_discovery()
        self.accept()

    # ---------------- cleanup ----------------
    def closeEvent(self, e):
        self._stop_discovery()
        super().closeEvent(e)

    def reject(self):
        self._stop_discovery()
        super().reject()
