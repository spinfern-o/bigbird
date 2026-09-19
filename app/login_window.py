"""The first screen PhotoForge shows: sign in, or continue as a guest.

Sign-in itself happens in the browser (see ``app/auth.py``); this window only
starts that flow and waits for it to come back. The important part for the
rest of the app is what the two buttons mean for your work:

  * **Sign in** — PhotoForge remembers your recent files, last folder and
    window layout between sessions (``app/state.PersistentStore``).
  * **Continue as guest** — everything works, but nothing is written to disk
    (``app/state.EphemeralStore``). Signing in later brings this session's
    state along with you.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import theme


class LoginWindow(QDialog):
    """Shown before the editor opens. Accepted = go ahead and start the app."""

    def __init__(self, auth, parent: QWidget | None = None):
        super().__init__(parent)
        self.auth = auth
        self.chose_guest = False

        self.setWindowTitle("Welcome to PhotoForge")
        self.setModal(True)
        self.setFixedSize(460, 392)

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 36, 40, 32)
        root.setSpacing(0)

        logo = QLabel("P")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedSize(52, 52)
        logo.setStyleSheet(
            f"background:{theme.ACCENT};color:#fff;border-radius:11px;"
            "font-size:24px;font-weight:600;"
        )
        badge = QHBoxLayout()
        badge.addStretch(1)
        badge.addWidget(logo)
        badge.addStretch(1)
        root.addLayout(badge)
        root.addSpacing(18)

        title = QLabel("PhotoForge")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:26px;font-weight:600;")
        root.addWidget(title)

        tagline = QLabel("Edit your photos like a pro — no experience needed.")
        tagline.setAlignment(Qt.AlignCenter)
        tagline.setWordWrap(True)
        tagline.setStyleSheet("color:#8a8a92;font-size:13px;")
        root.addWidget(tagline)
        root.addSpacing(28)

        self.sign_in_btn = QPushButton("Sign in")
        self.sign_in_btn.setDefault(True)
        self.sign_in_btn.setMinimumHeight(40)
        self.sign_in_btn.setCursor(Qt.PointingHandCursor)
        self.sign_in_btn.setToolTip(
            "Opens your web browser to sign in. PhotoForge will then remember "
            "your recent files and window layout."
        )
        self.sign_in_btn.setStyleSheet(
            f"QPushButton{{background:{theme.ACCENT};color:#fff;border:none;"
            "border-radius:7px;font-size:14px;font-weight:600;}"
            "QPushButton:hover{background:#3a8bea;}"
            "QPushButton:disabled{background:#3a3a42;color:#8a8a92;}"
        )
        self.sign_in_btn.clicked.connect(self._on_sign_in)
        root.addWidget(self.sign_in_btn)
        root.addSpacing(10)

        self.guest_btn = QPushButton("Continue as guest")
        self.guest_btn.setMinimumHeight(40)
        self.guest_btn.setCursor(Qt.PointingHandCursor)
        self.guest_btn.setToolTip(
            "Use PhotoForge without an account. Your photos still open and "
            "save normally, but recent files and window layout are forgotten "
            "when you quit."
        )
        self.guest_btn.clicked.connect(self._on_guest)
        root.addWidget(self.guest_btn)
        root.addSpacing(18)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#34343a;")
        root.addWidget(line)
        root.addSpacing(14)

        self.status = QLabel(
            "Guests can do everything — signing in just lets PhotoForge "
            "remember your recent files and layout next time."
        )
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#8a8a92;font-size:12px;line-height:1.5;")
        root.addWidget(self.status)
        root.addStretch(1)

        auth.authChanged.connect(self._on_auth_changed)

    # ------------------------------------------------------------------ slots
    def _on_sign_in(self):
        self.sign_in_btn.setEnabled(False)
        self.sign_in_btn.setText("Waiting for your browser…")
        self.status.setText(
            "Finish signing in using the page that just opened in your browser, "
            "then come back here. You can still continue as a guest instead."
        )
        self.auth.login()

    def _on_guest(self):
        self.chose_guest = True
        self.auth.continue_as_guest()
        self.accept()

    def _on_auth_changed(self, logged_in):
        if logged_in:
            self.accept()

    def reject(self):
        # Closing this window (Esc / red button) means "I don't want to open
        # PhotoForge", not "continue anonymously" — main.py exits on reject.
        super().reject()
