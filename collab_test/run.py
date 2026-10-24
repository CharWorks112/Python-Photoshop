"""Standalone collab test — run on two machines on the same LAN."""
import sys
from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QPushButton, QLabel,
    QLineEdit, QHBoxLayout, QMessageBox
)

from collab_test.host_window import HostWindow
from collab_test.client_window import ClientWindow


class LobbyDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Collab Paint — Lobby")
        self.setMinimumWidth(340)

        self.name_edit = QLineEdit("Player")
        host_btn = QPushButton("Host a New Canvas")
        join_btn = QPushButton("Join a Session")
        host_btn.clicked.connect(self._host)
        join_btn.clicked.connect(self._join)

        v = QVBoxLayout(self)
        v.addWidget(QLabel("Your name:"))
        v.addWidget(self.name_edit)
        v.addSpacing(12)
        v.addWidget(host_btn)
        v.addWidget(join_btn)

        self.mode = None
        self.name = "Player"

    def _host(self):
        self.mode = "host"
        self.name = self.name_edit.text().strip() or "Host"
        self.accept()

    def _join(self):
        self.mode = "client"
        self.name = self.name_edit.text().strip() or "Guest"
        self.accept()


def main():
    app = QApplication(sys.argv)
    dlg = LobbyDialog()
    if dlg.exec_() != dlg.Accepted:
        return 0

    if dlg.mode == "host":
        win = HostWindow(project_name=f"{dlg.name}'s Canvas")
        win.show()
    else:
        win = ClientWindow(my_name=dlg.name)
        win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
