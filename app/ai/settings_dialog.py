"""AI Settings: run heavy AI on this computer or on your NVIDIA Brev cloud GPU."""
import secrets

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
                               QVBoxLayout)

from . import cloud

HELP = (
    "<b>It's automatic.</b> When PhotoForge opens and your GPU is on, it connects by itself. "
    "The first time, it also sets up the GPU for you (about 5 minutes). If the GPU is off, "
    "heavy AI runs on this computer.<br><br>"
    "Needs the Brev CLI in Ubuntu (WSL) and <code>brev login</code> once. Brev bills by the "
    "hour while the GPU is on, so stop it when you're done.")

STATE_ICON = {"connected": "✓", "connecting": "…", "offline": "✗", "local": "•"}


class AISettingsDialog(QDialog):
    def __init__(self, parent, connection):
        super().__init__(parent)
        self.setWindowTitle("AI Settings")
        self.setMinimumWidth(600)
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

        # status + actions
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        self.retry_btn = QPushButton("Try Connecting Again")
        self.retry_btn.setToolTip("Connect to your GPU now (and set it up if needed)")
        self.retry_btn.clicked.connect(self._retry)
        self.start_btn = QPushButton("▶ Start GPU")
        self.start_btn.setToolTip("Turn your Brev GPU on (billed by the hour) and connect")
        self.start_btn.clicked.connect(self._start_gpu)
        self.stop_btn = QPushButton("■ Stop GPU")
        self.stop_btn.setToolTip("Turn your Brev GPU off so it stops billing")
        self.stop_btn.clicked.connect(lambda: self.conn.stop_gpu())
        for b in (self.retry_btn, self.start_btn, self.stop_btn):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        self.autostart = QCheckBox("Start my GPU automatically when PhotoForge opens "
                                   "(billed by the hour)")
        self.autostart.setChecked(s["autostart"])
        self.autostop = QCheckBox("Stop my GPU when I close PhotoForge (recommended if only "
                                  "you use it)")
        self.autostop.setChecked(s["autostop"])
        lay.addWidget(self.autostart)
        lay.addWidget(self.autostop)

        # advanced (filled in automatically)
        adv = QLabel("<b>Advanced</b> (filled in automatically)")
        adv.setObjectName("hintLabel")
        lay.addWidget(adv)
        form = QFormLayout()
        self.instance = QLineEdit(s["instance"])
        self.instance.setPlaceholderText("found automatically")
        form.addRow("Brev instance", self.instance)
        self.url = QLineEdit(s["url"])
        form.addRow("Server address", self.url)
        self.token = QLineEdit(s["token"])
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("created automatically")
        row = QHBoxLayout()
        row.addWidget(self.token)
        gen = QPushButton("New")
        gen.setToolTip("Make a new access token (the GPU is updated to it automatically)")
        gen.clicked.connect(self._new_token)
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.token.text()))
        row.addWidget(gen)
        row.addWidget(copy)
        form.addRow("Access token", row)
        lay.addLayout(form)

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
        busy = state == "connecting"
        for b in (self.retry_btn, self.start_btn, self.stop_btn):
            b.setEnabled(not busy)
        # the instance name may have been found automatically
        found = cloud.get_settings()["instance"]
        if found and not self.instance.text():
            self.instance.setText(found)
        if not self.token.text():
            self.token.setText(cloud.get_settings()["token"])

    def _new_token(self):
        self.token.setEchoMode(QLineEdit.Normal)
        self.token.setText(secrets.token_urlsafe(32))

    def _store(self, cloud_mode=None):
        if cloud_mode:
            self.remote.setChecked(True)
        cloud.save_settings("cloud" if self.remote.isChecked() else "local", self.url.text(),
                            self.token.text(), self.instance.text().strip())
        cloud.set_value("ai/autostart", self.autostart.isChecked())
        cloud.set_value("ai/autostop", self.autostop.isChecked())

    def _retry(self):
        self._store(cloud_mode=True)
        self.conn.retry()

    def _start_gpu(self):
        self._store(cloud_mode=True)
        self.conn.start_gpu()

    def _save(self):
        self._store()
        if cloud.prefers_cloud():
            if self.conn.state not in ("connected", "connecting"):
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
