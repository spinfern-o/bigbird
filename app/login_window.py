"""Startup login gate for PhotoForge.

The editor is not shown until the user either continues an existing saved
session or completes the browser-based login flow. Clicking Log in always opens
the system default browser (Safari, Chrome, Edge, etc.) through AuthManager.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import theme


class LoginWindow(QDialog):
    """The first window shown when PhotoForge starts."""

    def __init__(self, auth, parent: QWidget | None = None):
        super().__init__(parent)
        self.auth = auth

        self.setWindowTitle("PhotoForge — Log in")
        self.setModal(True)
        self.setFixedSize(440, 330)

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
        logo_row = QHBoxLayout()
        logo_row.addStretch(1)
        logo_row.addWidget(logo)
        logo_row.addStretch(1)
        root.addLayout(logo_row)
        root.addSpacing(18)

        title = QLabel("PhotoForge")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:25px;font-weight:600;")
        root.addWidget(title)

        self.subtitle = QLabel()
        self.subtitle.setAlignment(Qt.AlignCenter)
        self.subtitle.setWordWrap(True)
        self.subtitle.setStyleSheet("color:#8a8a92;font-size:13px;")
        root.addWidget(self.subtitle)
        root.addSpacing(26)

        self.login_btn = QPushButton()
        self.login_btn.setDefault(True)
        self.login_btn.setMinimumHeight(42)
        self.login_btn.setCursor(Qt.PointingHandCursor)
        self.login_btn.setToolTip(
            "Open PhotoForge sign-in in your default web browser."
        )
        self.login_btn.setStyleSheet(
            f"QPushButton{{background:{theme.ACCENT};color:#fff;border:none;"
            "border-radius:7px;font-size:14px;font-weight:600;}"
            "QPushButton:hover{background:#3a8bea;}"
        )
        self.login_btn.clicked.connect(self._on_login)
        root.addWidget(self.login_btn)
        root.addSpacing(14)

        self.status = QLabel()
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#8a8a92;font-size:12px;")
        root.addWidget(self.status)
        root.addStretch(1)

        self.auth.authChanged.connect(self._on_auth_changed)
        self._refresh()

    def _refresh(self):
        if self.auth.is_logged_in:
            email = self.auth.email or "your account"
            self.subtitle.setText(f"Signed in as {email}")
            self.login_btn.setText("Continue to PhotoForge")
            self.status.setText(
                "PhotoForge will still show this account screen first each time the app opens."
            )
        else:
            self.subtitle.setText("Log in to continue to the editor.")
            self.login_btn.setText("Log in")
            self.status.setText(
                "Log in opens in your default browser. If you create an account there, "
                "close the browser tab, return here, and click Log in again."
            )

    def _on_login(self):
        if self.auth.is_logged_in:
            self.accept()
            return

        # Keep the button enabled. If the user follows the Create account link
        # in the browser, they need to be able to return here and click Log in
        # again. AuthManager reuses the same loopback callback safely.
        self.login_btn.setText("Open login again")
        self.status.setText(
            "Finish signing in in your browser. If you just created an account, "
            "close that tab and click Open login again."
        )
        self.auth.login()

    def _on_auth_changed(self, logged_in: bool):
        if logged_in:
            self.accept()

    def reject(self):
        # Closing the login window exits startup instead of silently opening the editor.
        super().reject()
