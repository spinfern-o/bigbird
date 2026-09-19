"""Automatic connection to the PhotoForge GPU server on NVIDIA Brev.

When the app starts in cloud mode it checks the server, and if needed asks Brev whether
the instance is running and opens an SSH tunnel to it in the background (through WSL on
Windows, where the Brev CLI lives). If the GPU is off, heavy AI simply runs locally.
"""
import io
import os
import re
import secrets
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from . import cloud, server_files

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


class _TokenMismatch(Exception):
    pass


def _healthy(timeout=3):
    try:
        return cloud.Client(timeout=timeout, notify=False).health()
    except cloud.CloudError as e:
        if "access token" in str(e):
            raise _TokenMismatch() from None
        return None


# --------------------------------------------------------------------------- Brev instances

def list_instances():
    """[(name, STATUS)] of the logged-in Brev account, or a string explaining the problem."""
    if _brev_cmd(["ls"]) is None:
        return "The Brev CLI wasn't found. Install it inside Ubuntu (WSL) and run `brev login`."
    code, out = _run(["ls"])
    if code is None:
        return "Couldn't run the Brev CLI. Open Ubuntu and check that `brev ls` works."
    if "logged out" in out.lower() or "log in" in out.lower():
        return "Brev isn't logged in. Open Ubuntu and run `brev login` once."
    found = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] != "NAME" and parts[1].isupper() and parts[1].isalpha():
            found.append((parts[0], parts[1]))
    return found


def instance_status(name):
    found = list_instances()
    if isinstance(found, str):
        return None
    return dict(found).get(name, "NOT_FOUND")


def start_instance(name):
    code, out = _run(["start", name], timeout=900)
    return code == 0


def stop_instance(name):
    code, out = _run(["stop", name], timeout=120)
    return code == 0


# --------------------------------------------------------------------------- setting up the GPU

_SSH_CMD_OPTS = ("-T -o BatchMode=yes -o ControlMaster=no -o ControlPath=none "
                 "-o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 "
                 "-o ServerAliveInterval=30")


def _ssh_argv(name, remote):
    if shutil.which("brev") and shutil.which("ssh"):
        return [shutil.which("ssh")] + _SSH_CMD_OPTS.split() + [name, remote]
    wsl = shutil.which("wsl")
    if not wsl:
        return None
    script = (f'export PATH="$HOME/.local/bin:$PATH"; '
              f"exec ssh {_SSH_CMD_OPTS} {shlex.quote(name)} {shlex.quote(remote)}")
    return [wsl, "-e", "bash", "-lc", script]


def _ssh(name, remote, data=b"", timeout=120, on_line=None):
    """Run a command on the GPU machine. Returns (exit code, last output lines)."""
    argv = _ssh_argv(name, remote)
    if argv is None:
        return None, "no ssh"
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, creationflags=_NO_WINDOW)
    lines = []

    def feed():
        try:
            proc.stdin.write(data)
            proc.stdin.close()
        except OSError:
            pass

    threading.Thread(target=feed, daemon=True).start()
    deadline = time.time() + timeout
    for raw in iter(proc.stdout.readline, b""):
        line = raw.decode("utf-8", "replace").strip()
        if line:
            lines.append(line)
            del lines[:-30]
            if on_line:
                on_line(line)
        if time.time() > deadline:
            proc.kill()
            return None, "timed out"
    proc.wait()
    return proc.returncode, "\n".join(lines[-6:])


def _reachable_by_ssh(name):
    """Make sure SSH to the instance works, refreshing Brev's SSH settings once if not."""
    code, _ = _ssh(name, "true", timeout=60)
    if code == 0:
        return True
    _run(["refresh"], timeout=60)
    code, _ = _ssh(name, "true", timeout=60)
    return code == 0


def deploy(name, token, progress):
    """Copy PhotoForge's AI server to the GPU, install it (first time: GPU software and
    models) and make it start at boot with this app's token. Returns (ok, detail)."""
    progress("Setting up your GPU: connecting…")
    if not _reachable_by_ssh(name):
        return False, "Couldn't open an SSH connection to the GPU."
    progress("Setting up your GPU: copying PhotoForge's AI server…")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel in server_files.FILES:
            data = server_files.read(rel)
            info = tarfile.TarInfo(rel)
            info.size = len(data)
            info.mode = 0o755 if rel.endswith(".sh") else 0o644
            tar.addfile(info, io.BytesIO(data))
    code, out = _ssh(name, "mkdir -p ~/photoforge-server && tar xzf - -C ~/photoforge-server",
                     buf.getvalue(), timeout=180)
    if code != 0:
        return False, out
    progress("Setting up your GPU: installing GPU software (first time takes about 5 minutes)…")

    def on_line(line):
        if "Downloading AI models" in line:
            progress("Setting up your GPU: downloading AI models (first time only)…")
        elif "ONNX Runtime providers" in line:
            progress("Setting up your GPU: starting the AI server…")

    script = ("set -e\ncd ~/photoforge-server\nbash server/setup.sh\n"
              f"export PHOTOFORGE_TOKEN={shlex.quote(token)}\nbash server/install_service.sh\n")
    code, out = _ssh(name, "bash -s", script.encode(), timeout=1800, on_line=on_line)
    return code == 0, out


# --------------------------------------------------------------------------- connecting

def _ensure_token():
    s = cloud.get_settings()
    if not s["token"]:
        cloud.set_value("ai/token", secrets.token_urlsafe(32))
    return cloud.get_settings()["token"]


def connect_blocking(progress=lambda msg: None):
    """Connect to the GPU, starting/setting it up if needed. Returns (ok, message).
    Runs on a worker thread; progress(msg) reports what it's doing."""
    s = cloud.get_settings()
    token = _ensure_token()
    local_version = server_files.version()
    try:
        info = _healthy()
        mismatch = False
    except _TokenMismatch:
        info, mismatch = None, True
    if info and info.get("version") == local_version:
        return True, _ok(info)

    port = urlparse(s["url"]).port or 8765
    name = s["instance"]
    if name and not info and not mismatch:
        # Fast path: the GPU is known, so just open the tunnel and check.
        progress("Connecting to your GPU…")
        _forward.start(name, port)
        info, mismatch = _poll_health(10)
        if info and info.get("version") == local_version:
            return True, _ok(info)

    # Which Brev instance? Use the saved one, or find it automatically.
    found = list_instances()
    if isinstance(found, str):
        return False, found
    statuses = dict(found)
    if not name or name not in statuses:
        if len(found) == 1:
            name = found[0][0]
            cloud.set_value("ai/brev_instance", name)
        elif not found:
            return False, ("Your Brev account has no GPU instances yet. Create one at "
                           "brev.nvidia.com (any NVIDIA GPU).")
        else:
            return False, ("Your Brev account has several instances. Choose one in AI "
                           "Settings: " + ", ".join(n for n, _ in found))
    status = statuses.get(name, "NOT_FOUND")

    if status != "RUNNING":
        if not s["autostart"]:
            return False, (f"Your GPU '{name}' is {status.lower()}, so AI runs on this computer. "
                           "Click Start GPU in AI Settings to use it.")
        progress(f"Starting your GPU '{name}' (1–3 minutes)…")
        start_instance(name)
        deadline = time.time() + 900
        while time.time() < deadline and instance_status(name) != "RUNNING":
            time.sleep(10)
        if instance_status(name) != "RUNNING":
            return False, f"Your GPU '{name}' didn't start. Check it at brev.nvidia.com."

    if not info and not mismatch:
        progress("Connecting to your GPU…")
        if _forward.failed() or _forward.proc is None or _forward.started != (name, port):
            _forward.start(name, port)
        info, mismatch = _poll_health(20)
        if info and info.get("version") == local_version:
            return True, _ok(info)

    # The server is missing, outdated, or has a different token: (re)install it.
    ok, detail = deploy(name, token, progress)
    if not ok:
        return False, "Setting up your GPU failed.\nDetails: " + (detail or "unknown error")
    progress("Connecting to your GPU…")
    if _forward.failed() or _forward.proc is None:
        _forward.start(name, port)
    deadline = time.time() + 60
    while time.time() < deadline:
        time.sleep(2)
        try:
            info = _healthy()
        except _TokenMismatch:
            info = None
        if info:
            return True, _ok(info)
        if _forward.failed():
            _forward.start(name, port)
    return False, "Your GPU was set up, but the AI server didn't answer yet. Try again in a minute."


def _poll_health(seconds):
    """Wait for the server through the tunnel. Returns (info or None, token_mismatch)."""
    deadline = time.time() + seconds
    while time.time() < deadline and not _forward.failed():
        time.sleep(1)
        try:
            info = _healthy()
        except _TokenMismatch:
            return None, True
        if info:
            return info, False
    return None, False


def _ok(info):
    return f"Connected: {info.get('device', 'GPU')} on your Brev instance"


# --------------------------------------------------------------------------- Qt wrapper

class _Signals(QObject):
    done = Signal(bool, str)
    progress = Signal(str)


class _Job(QRunnable):
    def __init__(self, fn, signals):
        super().__init__()
        self.fn, self.signals = fn, signals

    def run(self):
        def progress(msg):
            try:
                self.signals.progress.emit(msg)
            except RuntimeError:
                pass
        try:
            ok, msg = self.fn(progress)
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
        self._signals.progress.connect(lambda m: self._set("connecting", m))
        cloud.on_connection_lost(self._lost)

    def _set(self, state, message):
        self.state, self.message = state, message
        cloud.set_connected(state == "connected")
        self.changed.emit(state, message)

    def _run(self, fn, first_message):
        if self._busy:
            return
        self._busy = True
        self._set("connecting", first_message)
        QThreadPool.globalInstance().start(_Job(fn, self._signals))

    def start(self):
        """Connect if cloud mode is chosen (called at startup, after Save, or on retry)."""
        if not cloud.prefers_cloud():
            self.stop()
            return
        self._run(connect_blocking, "Connecting to your NVIDIA GPU…")

    retry = start

    def start_gpu(self):
        """Turn the Brev instance on, then connect (and set it up if needed)."""
        def job(progress):
            s = cloud.get_settings()
            found = list_instances()
            if isinstance(found, str):
                return False, found
            name = s["instance"] or (found[0][0] if len(found) == 1 else "")
            if not name:
                return False, "Choose your Brev instance in AI Settings first."
            cloud.set_value("ai/brev_instance", name)
            if dict(found).get(name) != "RUNNING":
                progress(f"Starting your GPU '{name}' (1–3 minutes)…")
                start_instance(name)
            return connect_blocking(progress)
        self._run(job, "Starting your GPU…")

    def stop_gpu(self, wait=False):
        """Turn the Brev instance off (it bills by the hour while running)."""
        name = cloud.get_settings()["instance"]
        _forward.stop()
        if not name:
            return

        def job(progress):
            ok = stop_instance(name)
            return False, (f"Your GPU '{name}' is stopped (no hourly charges). AI runs on this "
                           "computer." if ok else f"Couldn't stop '{name}'. Check brev.nvidia.com.")
        if wait:
            stop_instance(name)
        else:
            self._run(job, f"Stopping your GPU '{name}'…")

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
