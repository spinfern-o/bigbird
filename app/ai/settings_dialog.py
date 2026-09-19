"""AI Settings: run heavy AI on this computer or on your NVIDIA Brev cloud GPU."""
import secrets

from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
                               QVBoxLayout)

from . import cloud

HELP = (
    "<b>How the cloud GPU works</b><ol>"
    "<li>On <a href='https://brev.nvidia.com' style='color:#6cb4ff'>brev.nvidia.com</a>, create a GPU environment "
    "(any NVIDIA GPU works; an L4 or T4 is plenty).</li>"
    "<li>In its terminal: clone this repository and run <code>bash server/setup.sh</code>, "
    "then start the server with the access token below (see <code>server/README.md</code>)."
    "</li>"
    "<li>Here: enter the instance name and click <b>Connect</b> (needs the Brev CLI and "
    "<code>brev login</code> once), then <b>Test Connection</b>.</li></ol>"
    "Brev bills by the hour while the instance runs, so <b>stop it</b> in the Brev console "
    "when you're done editing.")


class AISettingsDialog(QDialog):
    def __init__(self, parent, forwarder):
        super().__init__(parent)
        self.setWindowTitle("AI Settings")
        self.setMinimumWidth(580)
        self.setMinimumHeight(500)
        self.forwarder = forwarder
        s = cloud.get_settings()
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel("<b>Where should heavy AI run?</b> (background removal, object "
                             "selection, filling removed areas)"))
        self.local = QRadioButton("This computer: free and private, works offline")
        self.remote = QRadioButton("My NVIDIA cloud GPU (Brev): fast on any laptop, and "
                                   "enables Fill Removed Area")
        group = QButtonGroup(self)
        group.addButton(self.local)
        group.addButton(self.remote)
        (self.remote if s["mode"] == "cloud" else self.local).setChecked(True)
        lay.addWidget(self.local)
        lay.addWidget(self.remote)

        form = QFormLayout()
        self.instance = QLineEdit(s["instance"])
        self.instance.setPlaceholderText("your Brev instance name, e.g. photoforge-gpu")
        row = QHBoxLayout()
        row.addWidget(self.instance)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setToolTip("Runs `brev port-forward <instance> --port 8765:8765` so the "
                                    "app can reach the server securely.")
        self.connect_btn.clicked.connect(self._connect)
        row.addWidget(self.connect_btn)
        form.addRow("Brev instance", row)
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
        copy.setToolTip("Copy the token so you can set PHOTOFORGE_TOKEN on the server")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.token.text()))
        row.addWidget(gen)
        row.addWidget(copy)
        form.addRow("Access token", row)
        lay.addLayout(form)

        row = QHBoxLayout()
        test = QPushButton("Test Connection")
        test.clicked.connect(self._test)
        row.addWidget(test)
        self.status = QLabel()
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        lay.addLayout(row)

        help_lbl = QLabel(HELP)
        help_lbl.setWordWrap(True)
        help_lbl.setOpenExternalLinks(True)
        help_lbl.setObjectName("hintLabel")
        lay.addWidget(help_lbl)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._update_connect_state()

    def _new_token(self):
        self.token.setEchoMode(QLineEdit.Normal)
        self.token.setText(secrets.token_urlsafe(32))

    def _update_connect_state(self):
        running = self.forwarder.running()
        self.connect_btn.setText("Disconnect" if running else "Connect")
        if running:
            self.status.setText(f"Connected to Brev instance '{self.forwarder.instance}'.")

    def _connect(self):
        if self.forwarder.running():
            self.forwarder.stop()
            self.status.setText("Disconnected.")
            self._update_connect_state()
            return
        if not cloud.brev_cli():
            self.status.setText("The Brev CLI isn't installed. Install it from "
                                "docs.nvidia.com/brev, run `brev login`, then try again.")
            return
        name = self.instance.text().strip()
        if not name:
            self.status.setText("Enter your Brev instance name first.")
            return
        err = self.forwarder.start(name)
        self.status.setText(err or f"Connecting to '{name}'… then click Test Connection.")
        self._update_connect_state()

    def _test(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            info = cloud.Client(self.url.text(), self.token.text(), timeout=15).health()
            self.status.setText(f"✓ Connected: server is running on {info['device']}.")
        except cloud.CloudError as e:
            self.status.setText(f"✗ {e}")
        finally:
            QApplication.restoreOverrideCursor()

    def _save(self):
        cloud.save_settings("cloud" if self.remote.isChecked() else "local", self.url.text(),
                            self.token.text(), self.instance.text().strip())
        self.accept()


class BrevForwarder:
    """Keeps `brev port-forward` running in the background while the app is open."""

    def __init__(self, parent):
        self.proc = QProcess(parent)
        self.instance = None

    def running(self):
        return self.proc.state() != QProcess.NotRunning

    def start(self, instance, port=8765):
        self.instance = instance
        self.proc.start(cloud.brev_cli(), ["port-forward", instance, "--port", f"{port}:{port}"])
        if not self.proc.waitForStarted(5000):
            return "Couldn't start the Brev CLI."
        return None

    def stop(self):
        if self.running():
            self.proc.kill()
            self.proc.waitForFinished(3000)
