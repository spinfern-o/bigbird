"""PhotoForge — a beginner-friendly photo editor. Run: python main.py [photo]"""
import ctypes
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import theme
from app.auth import AuthManager
from app.main_window import MainWindow


class LoginGate(QWidget):
    """First screen shown by the desktop app before the editor opens."""

    def __init__(self, on_authenticated):
        super().__init__()
        self._on_authenticated = on_authenticated
        self.auth = AuthManager(self)
        self.auth.authChanged.connect(self._auth_changed)

        self.setWindowTitle("PhotoForge")
        self.setFixedSize(420, 300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 42, 48, 42)
        layout.setSpacing(14)

        mark = QLabel("P")
        mark.setObjectName("loginMark")
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(52, 52)

        title = QLabel("PhotoForge")
        title.setObjectName("loginTitle")
        title.setAlignment(Qt.AlignCenter)

        subtitle = QLabel("Sign in to continue to the editor.")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)

        self.login_btn = QPushButton()
        self.login_btn.setObjectName("accent")
        self.login_btn.setMinimumHeight(42)
        self.login_btn.clicked.connect(self._login_clicked)

        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)

        layout.addWidget(mark, 0, Qt.AlignHCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)
        layout.addWidget(self.login_btn)
        layout.addWidget(self.status)

        self._refresh()

    def _refresh(self):
        if self.auth.is_logged_in:
            email = self.auth.email or "your account"
            self.login_btn.setText(f"Continue as {email}")
            self.status.setText("Your previous sign-in is still active.")
        else:
            self.login_btn.setText("Log in")
            self.status.setText("Log in opens your default web browser.")

    def _login_clicked(self):
        if self.auth.is_logged_in:
            self._on_authenticated()
            return
        self.status.setText(
            "Opening your browser. Sign in there, then return to PhotoForge."
        )
        self.auth.login()

    def _auth_changed(self, logged_in):
        self._refresh()
        if logged_in:
            self.status.setText("Signed in. Opening PhotoForge…")
            self._on_authenticated()


def main():
    if sys.platform == "win32":
        # Give the app its own taskbar entry/icon grouping instead of python.exe's.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PhotoForge.Editor")

    app = QApplication(sys.argv)
    app.setApplicationName("PhotoForge")
    theme.apply(app)

    windows = {}

    def open_editor():
        if "editor" in windows:
            return
        gate = windows.get("gate")
        if gate is not None:
            gate.hide()

        editor = MainWindow()
        windows["editor"] = editor
        if len(sys.argv) > 1:
            editor.load_path(sys.argv[1])
        editor.show()

    gate = LoginGate(open_editor)
    windows["gate"] = gate
    gate.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
