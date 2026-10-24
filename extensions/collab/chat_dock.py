"""Chat panel — send/receive messages during a collab session."""
from PyQt5.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QLineEdit, QPushButton, QLabel
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QTextCursor


class ChatDock(QDockWidget):
    """Dockable chat panel — main_window owns sending/receiving through session."""
    messageSubmitted = pyqtSignal(str)   # text (no name — main_window adds it)

    def __init__(self, parent=None):
        super().__init__("Chat", parent)
        self.setObjectName("ChatDock")
        self.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet(
            "background:#1e1e1e; color:#ddd; border:none; font-size:12px;"
        )

        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a message…")
        self.input.returnPressed.connect(self._submit)

        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self._submit)

        row = QHBoxLayout()
        row.addWidget(self.input, 1)
        row.addWidget(send_btn)

        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        v.addWidget(self.log, 1)
        v.addLayout(row)
        self.setWidget(w)

    def _submit(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.messageSubmitted.emit(text)

    def append_message(self, name: str, text: str, color: str = "#e0e0e0"):
        """Add a message on its own line. Uses a fresh QTextBlock per message
        so nothing ever concatenates on one line."""
        from PyQt5.QtGui import QTextCharFormat, QTextBlockFormat
        from PyQt5.QtCore import Qt

        safe_name = (name or "?").replace("<", "&lt;").replace(">", "&gt;")
        safe_text = (text or "").replace("<", "&lt;").replace(">", "&gt;")

        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.End)

        # if not at the beginning of a fresh block, insert a line break first
        if not cursor.atBlockStart() or cursor.position() > 0:
            cursor.insertBlock()
        block_fmt = QTextBlockFormat()
        block_fmt.setBottomMargin(4)
        cursor.setBlockFormat(block_fmt)

        name_fmt = QTextCharFormat()
        name_fmt.setForeground(QColor(color))
        name_fmt.setFontWeight(75)   # bold
        cursor.insertText(f"{safe_name}: ", name_fmt)

        text_fmt = QTextCharFormat()
        text_fmt.setForeground(QColor("#e0e0e0"))
        cursor.insertText(safe_text, text_fmt)

        self.log.setTextCursor(cursor)
        self.log.verticalScrollBar().setValue(
            self.log.verticalScrollBar().maximum())
