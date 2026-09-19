"""AI Settings: run heavy AI on this computer or on your NVIDIA Brev cloud GPU."""
import secrets

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QRadioButton, QVBoxLayout)

from . import cloud

HELP = (
    "<b>How it works</b><br>When PhotoForge opens, it connects to your GPU automatically if "
    "it's running (it opens <code>brev port-forward</code> in the background). If the GPU is "
    "off, heavy AI runs on this computer. Start the GPU later? Click <b>Try Connecting "
    "Again</b>.<br><br>First-time setup of the GPU is in <code>server/README.md</code>. "
    "Brev bills by the hour while the instance runs, so <b>stop it</b> when you're done "
    "(<code>brev stop &lt;name&gt;</code>).")

STATE_ICON = {"connected": "✓", "connecting": "…", "offline": "✗", "local": "•"}


class AISettingsDialog(QDialog):
    def __init__(self, parent, connection):
        super().__init__(parent)
        self.setWindowTitle("AI Settings")
        self.setMinimumWidth(580)
        self.conn = connection
        s = cloud.get_settings()
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel("<b>Where should heavy AI run?</b> (background removal, object "
                             "selection, filling removed areas)"))
        self.local = QRadioButton("This computer: free and private, works offline")
        self.remote = QRadioButton("My NVIDIA cloud GPU (Brev) when it's on: fast on any "
                                   "laptop, and enables Fill Removed Area")
        group = QButtonGroup(self)
        group.addButton(self.local)
        group.addButton(self.remote)
        (self.remote if s["mode"] == "cloud" else self.local).setChecked(True)
        lay.addWidget(self.local)
        lay.addWidget(self.remote)

        form = QFormLayout()
        self.instance = QLineEdit(s["instance"])
        self.instance.setPlaceholderText("your Brev instance name (see `brev ls`)")
        form.addRow("Brev instance", self.instance)
        self.url = QLineEdit(s["url"])
        form.addRow("Server address", self.url)
        self.token = QLineEdit(s["token"])
        self.token.setEchoMode(QLineEdit.Password)
        row = QHBoxLayout()
        row.addWidget(self.token)
        gen = QPushButton("New")
        gen.setToolTip("Create a new random access token")
        gen.clicked.connect(self._new_token)
        copy = QPushButton("Copy")
        copy.setToolTip("Copy the token so you can set it on the GPU server")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.token.text()))
        row.addWidget(gen)
        row.addWidget(copy)
        form.addRow("Access token", row)
        lay.addLayout(form)

        row = QHBoxLayout()
        self.retry_btn = QPushButton("Try Connecting Again")
        self.retry_btn.setToolTip("Connect to your GPU now (e.g. after starting it in Brev)")
        self.retry_btn.clicked.connect(self._retry)
        row.addWidget(self.retry_btn)
        self.status = QLabel()
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        lay.addLayout(row)

        help_lbl = QLabel(HELP)
        help_lbl.setWordWrap(True)
        help_lbl.setObjectName("hintLabel")
        lay.addWidget(help_lbl)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self.conn.changed.connect(self._show_state)
        self._show_state(self.conn.state, self.conn.message)

    def _show_state(self, state, message):
        self.status.setText(f"{STATE_ICON.get(state, '')} {message}")
        self.retry_btn.setEnabled(state != "connecting")

    def _new_token(self):
        self.token.setEchoMode(QLineEdit.Normal)
        self.token.setText(secrets.token_urlsafe(32))

    def _store(self):
        cloud.save_settings("cloud" if self.remote.isChecked() else "local", self.url.text(),
                            self.token.text(), self.instance.text().strip())

    def _retry(self):
        if not self.remote.isChecked():
            self.remote.setChecked(True)
        self._store()
        self.conn.retry()

    def _save(self):
        self._store()
        if cloud.prefers_cloud():
            if self.conn.state != "connected":
                self.conn.retry()
        else:
            self.conn.stop()
        self.accept()

    def done(self, result):
        try:
            self.conn.changed.disconnect(self._show_state)
        except (RuntimeError, TypeError):
            pass
        super().done(result)
