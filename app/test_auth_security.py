"""Regression tests for desktop auth persistence.

Run from the repository root:
    python app/test_auth_security.py
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from app import auth


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def main():
    app = QCoreApplication.instance() or QCoreApplication([])
    original_path = auth._SESSION_PATH

    with tempfile.TemporaryDirectory() as tmp:
        auth._SESSION_PATH = Path(tmp) / ".photoforge" / "session.json"

        manager = auth.AuthManager()
        manager._session = {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_at": "9999999999",
            "email": "person@example.com",
        }
        manager._save()

        check("session file written", auth._SESSION_PATH.exists())
        saved = json.loads(auth._SESSION_PATH.read_text())
        check("session JSON round-trips", saved["access_token"] == "access")

        if os.name != "nt":
            mode = auth._SESSION_PATH.stat().st_mode & 0o777
            parent_mode = auth._SESSION_PATH.parent.stat().st_mode & 0o777
            check("session file is user-only", mode == 0o600)
            check("session directory is user-only", parent_mode == 0o700)

        wrong = auth.AuthManager()
        wrong._state = "expected-state"
        ok, _ = wrong._handle_callback({
            "state": "wrong-state",
            "access_token": "a",
            "refresh_token": "r",
        })
        check("wrong callback state is rejected", not ok)

        right = auth.AuthManager()
        right._state = "expected-state"
        ok, _ = right._handle_callback({
            "state": "expected-state",
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_at": "9999999999",
            "email": "person@example.com",
        })
        check("matching callback state succeeds", ok)
        check("successful callback persists session", auth._SESSION_PATH.exists())

        auth._secure_write_json(auth._SESSION_PATH, {
            "access_token": "expired-access",
            "refresh_token": "expired-refresh",
            "expires_at": "1",
            "email": "old@example.com",
        })
        expired = auth.AuthManager()
        check("expired saved session is rejected", not expired.is_logged_in)
        check("expired saved session file is removed", not auth._SESSION_PATH.exists())

    auth._SESSION_PATH = original_path
    print("All auth-security regression tests passed.")


if __name__ == "__main__":
    main()
