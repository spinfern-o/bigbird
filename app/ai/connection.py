"""Automatic connection to the PhotoForge GPU server on NVIDIA Brev.

When the app starts in cloud mode it checks the server, and if needed asks Brev whether
the instance is running and opens an SSH tunnel to it in the background (through WSL on
Windows, where the Brev CLI lives). If the GPU is off, heavy AI simply runs locally.
"""
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from . import cloud

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# --------------------------------------------------------------------------- Brev CLI

def _brev_cmd(args):
    """The command line to run `brev <args>`: natively if installed, else inside WSL."""
    native = shutil.which("brev")
    if native:
        return [native] + args
    wsl = shutil.which("wsl")
    if wsl:
        inner = 'export PATH="$HOME/.local/bin:$PATH"; exec brev ' + " ".join(map(shlex.quote, args))
        return [wsl, "-e", "bash", "-lc", inner]
    return None


def _run(args, timeout=30):
    cmd = _brev_cmd(args)
    if cmd is None:
        return None, ""
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
                           creationflags=_NO_WINDOW)
    except (subprocess.TimeoutExpired, OSError):
        return None, ""
    out = (r.stdout + r.stderr).decode("utf-8", "replace").replace("\x00", "")
    return r.returncode, re.sub(r"\x1b\[[0-9;]*m", "", out)


def instance_status(name):
    """'RUNNING', 'STOPPED', ... or None if Brev can't be asked (not installed/logged in)."""
    code, out = _run(["ls"])
    if code is None:
        return None
    if "logged out" in out.lower() or "log in" in out.lower():
        return "LOGGED_OUT"
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == name:
            return parts[1].upper()
    return "NOT_FOUND"


# --------------------------------------------------------------------------- port-forward

_SSH_OPTS = ("-N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 "
             "-o ControlMaster=no -o ControlPath=none -o BatchMode=yes "
             "-o StrictHostKeyChecking=accept-new")


def _tunnel_cmd(name, port):
    """A long-running SSH tunnel to the instance, using the SSH setup the Brev CLI wrote.

    (`brev port-forward` hands its tunnel to a background process and exits, and processes
    left behind by `wsl.exe` are torn down when it returns, so the app runs the tunnel
    itself. It lives exactly as long as this process.)"""
    spec = f"-L {port}:127.0.0.1:{port}"
    host = shlex.quote(name)
    if shutil.which("brev") and shutil.which("ssh"):
        return [shutil.which("ssh")] + _SSH_OPTS.split() + spec.split() + [name]
    wsl = shutil.which("wsl")
    if not wsl:
        return None
    # If Brev's SSH settings are stale, refresh them once and retry.
    script = (f'export PATH="$HOME/.local/bin:$PATH"; '
              f"ssh {_SSH_OPTS} {spec} {host} || "
              f"{{ brev refresh >/dev/null 2>&1; exec ssh {_SSH_OPTS} {spec} {host}; }}")
    return [wsl, "-e", "bash", "-lc", script]


class _Forward:
    """The SSH tunnel from this PC's localhost:<port> to the GPU server."""

    def __init__(self):
        self.proc = None
        self.started = None   # (instance, port) if this app opened a tunnel
        self.log = os.path.join(tempfile.gettempdir(), "photoforge-brev-forward.log")

    def failed(self):
        """The tunnel process ended (it should keep running while connected)."""
        return self.proc is not None and self.proc.poll() is not None

    def start(self, name, port):
        self.stop()
        self._close_tunnels(name, port)  # a stale tunnel from earlier would block the port
        self.started = (name, port)
        cmd = _tunnel_cmd(name, port)
        with open(self.log, "wb") as f:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=f,
                                         stderr=subprocess.STDOUT, creationflags=_NO_WINDOW)

    def tail(self):
        """Brev's last meaningful output line (without spinner and color codes)."""
        try:
            with open(self.log, "rb") as f:
                text = f.read()[-2000:].decode("utf-8", "replace")
        except OSError:
            return ""
        text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text).replace("\r", "\n")
        lines = [l.strip() for l in text.splitlines() if l.strip() and "waiting for" not in l]
        return lines[-1] if lines else ""

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                pass
        self.proc = None
        if self.started:
            self._close_tunnels(*self.started)
            self.started = None

    @staticmethod
    def _close_tunnels(name, port):
        """Close tunnels for this port, on the shared SSH connection and standalone ones."""
        wsl = shutil.which("wsl")
        if shutil.which("brev") or not wsl:
            return
        spec = f"{port}:127.0.0.1:{port}"
        script = (f"ssh -O cancel -L {spec} {shlex.quote(name)} 2>/dev/null; "
                  f"pkill -f {shlex.quote('ssh -T -L ' + spec)} 2>/dev/null; "
                  f"pkill -f {shlex.quote(f'-L {port}:127.0.0.1:{port} ' + name)} 2>/dev/null; "
                  f"pkill -f {shlex.quote('brev port-forward ' + name)} 2>/dev/null; true")
        try:
            subprocess.run([wsl, "-e", "bash", "-c", script], timeout=15, capture_output=True,
                           creationflags=_NO_WINDOW)
        except (subprocess.TimeoutExpired, OSError):
            pass


_forward = _Forward()


TOKEN_MSG = ("Reached your GPU, but the access token doesn't match. Copy the token from AI "
             "Settings and run `bash server/install_service.sh` on the GPU with it.")


class _TokenMismatch(Exception):
    pass


def _healthy(timeout=3):
    try:
        return cloud.Client(timeout=timeout, notify=False).health()
    except cloud.CloudError as e:
        if "access token" in str(e):
            raise _TokenMismatch() from None
        return None


def connect_blocking():
    """Try to connect. Returns (ok, message). Safe to call from a worker thread."""
    try:
        return _connect()
    except _TokenMismatch:
        return False, TOKEN_MSG


def _connect():
    s = cloud.get_settings()
    info = _healthy()
    if info:
        return True, f"Connected: {info.get('device', 'GPU')} on your Brev instance"
    name = s["instance"]
    if not name:
        return False, "The server isn't reachable, and no Brev instance name is set."
    if _brev_cmd(["ls"]) is None:
        return False, "The Brev CLI wasn't found (install it inside Ubuntu/WSL)."
    status = instance_status(name)
    if status is None:
        return False, "Couldn't run the Brev CLI. Open Ubuntu and check `brev ls` works."
    if status == "LOGGED_OUT":
        return False, "Brev isn't logged in. Run `brev login` in Ubuntu."
    if status == "NOT_FOUND":
        return False, f"No Brev instance named '{name}' (check the name in AI Settings)."
    if status != "RUNNING":
        return False, f"Your GPU '{name}' is {status.lower()}. Using this computer instead."
    port = urlparse(s["url"]).port or 8765
    _forward.start(name, port)
    deadline = time.time() + 40
    while time.time() < deadline:
        time.sleep(1.0)
        info = _healthy(timeout=3)
        if info:
            return True, f"Connected: {info.get('device', 'GPU')} on your Brev instance"
        if _forward.failed():
            break
    detail = _forward.tail()
    return False, ("Your GPU is on, but the PhotoForge server on it didn't answer. Run "
                   "`bash server/install_service.sh` on the GPU once (see server/README.md)."
                   + (f"\nBrev said: {detail}" if detail else ""))


# --------------------------------------------------------------------------- Qt wrapper

class _Signals(QObject):
    done = Signal(bool, str)


class _Job(QRunnable):
    def __init__(self, fn, signals):
        super().__init__()
        self.fn, self.signals = fn, signals

    def run(self):
        try:
            ok, msg = self.fn()
        except Exception as e:
            ok, msg = False, f"{type(e).__name__}: {e}"
        try:
            self.signals.done.emit(ok, msg)
        except RuntimeError:
            pass


class CloudConnection(QObject):
    """Keeps track of the cloud GPU connection for the UI.
    state: "local" (cloud not chosen), "connecting", "connected" or "offline"."""
    changed = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state, self.message = "local", "Heavy AI runs on this computer."
        self._busy = False
        self._signals = _Signals()
        self._signals.done.connect(self._done)
        cloud.on_connection_lost(self._lost)

    def _set(self, state, message):
        self.state, self.message = state, message
        cloud.set_connected(state == "connected")
        self.changed.emit(state, message)

    def start(self):
        """Connect if cloud mode is chosen (called at startup, after Save, or on retry)."""
        if not cloud.prefers_cloud():
            self.stop()
            return
        if self._busy:
            return
        self._busy = True
        self._set("connecting", "Connecting to your NVIDIA GPU…")
        QThreadPool.globalInstance().start(_Job(connect_blocking, self._signals))

    retry = start

    def _done(self, ok, message):
        self._busy = False
        if not cloud.prefers_cloud():
            return
        self._set("connected" if ok else "offline", message)

    def _lost(self):
        # Called from a worker thread when a request can't reach the server.
        self._signals.done.emit(False, "Lost the connection to your NVIDIA GPU. Using this "
                                       "computer until you reconnect (AI → AI Settings).")

    def stop(self):
        _forward.stop()
        if self.state != "local":
            self._set("local", "Heavy AI runs on this computer.")
