"""Account sign-in for the PhotoForge desktop app.

Uses the standard native-app "loopback redirect" flow:

  1. Start a tiny HTTP server bound to 127.0.0.1 on an ephemeral port.
  2. Open the account web page in the user's default browser (Safari on macOS),
     passing that loopback URL plus a random ``state`` value.
  3. The web page signs the user in (Supabase) and redirects back to the
     loopback URL with the session tokens as query parameters.
  4. This module validates ``state``, stores the session locally, and notifies
     the UI via the ``authChanged`` Qt signal.

The web page lives in ``web/`` and is deployed separately. Production defaults
to ``https://www.phrame.tech``; set ``BIGBIRD_WEB_URL`` to override it (for
example, ``http://localhost:3000`` during local web development).
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from PySide6.QtCore import QObject, QUrl, Signal

# Where the account web page is hosted. Override in production, e.g.
#   export BIGBIRD_WEB_URL="http://localhost:3000"  # local web development
DEFAULT_WEB_URL = "https://www.phrame.tech"

# Abandon a pending sign-in if the browser never comes back.
LOGIN_TIMEOUT_SECONDS = 300

_SESSION_PATH = Path.home() / ".photoforge" / "session.json"


def _secure_write_json(path: Path, data) -> None:
    """Atomically write JSON using a user-only temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".session-", suffix=".tmp")
    try:
        # mkstemp creates a private file; keep the explicit chmod for platforms
        # that support POSIX permissions.
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


_SUCCESS_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>PhotoForge</title>
<style>
  body{{background:#1b1b1e;color:#e8e8ec;font-family:-apple-system,Segoe UI,sans-serif;
       display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}}
  .card{{background:#252528;border:1px solid #34343a;border-radius:10px;padding:32px 40px;text-align:center;max-width:360px}}
  h1{{font-size:18px;margin:0 0 8px}} p{{color:#8a8a92;font-size:14px;line-height:1.5;margin:0}}
  .dot{{width:40px;height:40px;border-radius:8px;background:#2f7fe0;color:#fff;display:flex;
        align-items:center;justify-content:center;font-weight:600;margin:0 auto 16px}}
</style></head>
<body><div class="card"><div class="dot">P</div>
<h1>{title}</h1><p>{body}</p></div></body></html>"""


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (Qt/http naming)
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        ok, message = self.server.auth_manager._handle_callback(params)  # type: ignore[attr-defined]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if ok:
            html = _SUCCESS_HTML.format(
                title="You're signed in",
                body="You can close this tab and return to PhotoForge.",
            )
        else:
            html = _SUCCESS_HTML.format(title="Sign-in failed", body=message)
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, *args):  # silence default stderr logging
        pass


class AuthManager(QObject):
    """Owns the desktop sign-in flow and the persisted session."""

    # Emitted with True when signed in, False when signed out.
    authChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._session: dict | None = None
        self._server: HTTPServer | None = None
        self._state: str | None = None
        self._timeout_timer: threading.Timer | None = None
        self._load_saved()

    # ---------------------------------------------------------------- session
    @property
    def is_logged_in(self) -> bool:
        return self._session is not None

    @property
    def email(self) -> str | None:
        return (self._session or {}).get("email")

    @property
    def access_token(self) -> str | None:
        """The token cloud features send to prove who's asking (app/ai/base.py)."""
        return (self._session or {}).get("access_token")

    @property
    def session(self) -> dict:
        """A copy of the current session for authenticated cloud features."""
        return dict(self._session or {})

    def update_session(self, **fields):
        """Persist refreshed Supabase session fields without exposing internal state."""
        if self._session is None:
            return
        self._session.update({k: v for k, v in fields.items() if v not in (None, "")})
        self._session["saved_at"] = int(time.time())
        self._save()

    def _load_saved(self):
        try:
            if _SESSION_PATH.exists():
                data = json.loads(_SESSION_PATH.read_text())
                if data.get("access_token") and data.get("refresh_token"):
                    expires_at = data.get("expires_at")
                    try:
                        expired = bool(expires_at) and float(expires_at) <= time.time()
                    except (TypeError, ValueError):
                        expired = False
                    if expired:
                        try:
                            _SESSION_PATH.unlink()
                        except OSError:
                            pass
                    else:
                        self._session = data
        except (OSError, ValueError):
            self._session = None

    def _save(self):
        try:
            _secure_write_json(_SESSION_PATH, self._session or {})
        except OSError:
            pass

    # ------------------------------------------------------------------ login
    def login(self):
        """Start the loopback server and open the browser sign-in page."""
        if self._server is not None:
            # A sign-in is already in progress; re-open the browser tab.
            self._open_browser()
            return

        self._state = secrets.token_urlsafe(24)
        self._server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
        self._server.auth_manager = self  # type: ignore[attr-defined]

        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()

        self._timeout_timer = threading.Timer(LOGIN_TIMEOUT_SECONDS, self._cancel_login)
        self._timeout_timer.daemon = True
        self._timeout_timer.start()

        self._open_browser()

    def _redirect_uri(self) -> str:
        port = self._server.server_address[1]  # type: ignore[union-attr]
        return f"http://127.0.0.1:{port}/callback"

    def _login_url(self) -> str:
        base = os.environ.get("BIGBIRD_WEB_URL", DEFAULT_WEB_URL).rstrip("/")
        query = urlencode({"redirect_uri": self._redirect_uri(), "state": self._state})
        return f"{base}/desktop-login?{query}"

    def _open_browser(self):
        # Imported lazily so the sign-in logic can be used/tested without the
        # Qt GUI stack (QtGui pulls in OpenGL libraries).
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(self._login_url()))

    def _cancel_login(self):
        """Timeout expired without a callback; tear the server down quietly."""
        self._shutdown_server()

    def _shutdown_server(self):
        if self._timeout_timer is not None:
            self._timeout_timer.cancel()
            self._timeout_timer = None
        server, self._server = self._server, None
        self._state = None
        if server is not None:
            threading.Thread(target=server.shutdown, daemon=True).start()

    def _handle_callback(self, params: dict) -> tuple[bool, str]:
        """Called from the HTTP server thread when the browser redirects back."""
        if not self._state or not secrets.compare_digest(params.get("state", ""), self._state):
            self._shutdown_server()
            return False, "This sign-in request has expired. Please try again from PhotoForge."

        access_token = params.get("access_token")
        refresh_token = params.get("refresh_token")
        if not access_token or not refresh_token:
            self._shutdown_server()
            return False, "No session was returned. Please try again."

        self._session = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": params.get("expires_at", ""),
            "email": params.get("email", ""),
            "saved_at": int(time.time()),
        }
        self._save()
        self._shutdown_server()
        # Qt delivers this queued to the main thread since AuthManager lives there.
        self.authChanged.emit(True)
        return True, ""

    # ----------------------------------------------------------------- logout
    def logout(self):
        self._session = None
        try:
            if _SESSION_PATH.exists():
                _SESSION_PATH.unlink()
        except OSError:
            pass
        self.authChanged.emit(False)
