"""Regression tests for PhotoForge cloud-project API.

Run from the repository root:
    python app/test_cloud_projects.py

No network access or real Supabase account is used.
"""
from __future__ import annotations

import base64
import json
import time
import uuid

from app import cloud_projects as cp


UID = "11111111-2222-3333-4444-555555555555"
PROJECT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def token_for(uid=UID):
    payload = base64.urlsafe_b64encode(json.dumps({"sub": uid}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class FakeAuth:
    def __init__(self, logged_in=True, expires_at=None):
        self.is_logged_in = logged_in
        self._session = {
            "access_token": token_for(),
            "refresh_token": "refresh-1",
            "expires_at": str(expires_at or int(time.time()) + 3600),
            "email": "person@example.com",
        }

    @property
    def session(self):
        return dict(self._session)

    def update_session(self, **fields):
        self._session.update({k: v for k, v in fields.items() if v not in (None, "")})


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def main():
    original_request = cp._request
    original_limit = cp.MAX_UPLOAD
    try:
        auth = FakeAuth()
        api = cp.Api(auth)
        calls = []

        def fake_request(method, url, data=None, headers=None, timeout=120):
            calls.append((method, url, data, headers or {}))
            if "/rest/v1/projects" in url and method in ("POST", "PATCH"):
                row = json.loads(data)
                return json.dumps([{**row, "id": PROJECT_ID}]).encode()
            if "/rest/v1/projects" in url and method == "GET":
                return b"[]"
            return b"{}"

        cp._request = fake_request

        api.list_projects()
        method, url, _, headers = calls[-1]
        check("list uses authenticated REST request", method == "GET" and "Authorization" in headers)
        check("list explicitly filters by user", f"user_id=eq.{UID}" in url)

        calls.clear()
        row = api.save_project("Demo", b"project", b"jpeg", 800, 600)
        check("new cloud project returns id", row["id"] == PROJECT_ID)
        upload_urls = [u for m, u, *_ in calls if "/storage/v1/object/projects/" in u and m == "POST"]
        check("project and thumbnail are uploaded", len(upload_urls) == 2)
        check("uploads stay inside user folder", all(f"/{UID}/" in u for u in upload_urls))
        meta_call = next(c for c in calls if "/rest/v1/projects" in c[1] and c[0] == "POST")
        metadata = json.loads(meta_call[2])
        check("metadata records authenticated user", metadata["user_id"] == UID)

        calls.clear()
        api.save_project("Demo 2", b"updated", b"jpeg", 900, 700, PROJECT_ID)
        check("repeat save updates existing row", any(m == "PATCH" for m, *_ in calls))
        check(
            "update is scoped to user and project",
            any(f"id=eq.{PROJECT_ID}" in u and f"user_id=eq.{UID}" in u for m, u, *_ in calls if m == "PATCH"),
        )

        calls.clear()
        api.download_project(f"{UID}/{PROJECT_ID}.pforge")
        download = calls[-1]
        check(
            "private download uses authenticated Storage route",
            "/storage/v1/object/authenticated/projects/" in download[1],
        )

        calls.clear()
        api.delete_project({
            "id": PROJECT_ID,
            "file_path": f"{UID}/{PROJECT_ID}.pforge",
            "thumb_path": f"{UID}/{PROJECT_ID}.jpg",
        })
        deletes = [c for c in calls if c[0] == "DELETE"]
        check("delete removes metadata and both objects", len(deletes) == 3)

        cp.MAX_UPLOAD = 3
        try:
            api.save_project("Too big", b"1234", None, 10, 10)
            blocked = False
        except cp.CloudError:
            blocked = True
        check("oversized projects are blocked before upload", blocked)

        signed_out = cp.Api(FakeAuth(logged_in=False))
        try:
            signed_out.list_projects()
            refused = False
        except cp.CloudError:
            refused = True
        check("signed-out users are refused", refused)

        refresh_auth = FakeAuth(expires_at=int(time.time()) + 5)
        refresh_api = cp.Api(refresh_auth)
        refresh_calls = []

        def fake_refresh(method, url, data=None, headers=None, timeout=120):
            refresh_calls.append((method, url))
            if "/auth/v1/token" in url:
                return json.dumps({
                    "access_token": token_for(),
                    "refresh_token": "refresh-2",
                    "expires_in": 3600,
                    "user": {"email": "person@example.com"},
                }).encode()
            if "/rest/v1/projects" in url:
                return b"[]"
            return b"{}"

        cp._request = fake_refresh
        refresh_api.list_projects()
        check("near-expiry access token is refreshed", any("/auth/v1/token" in u for _, u in refresh_calls))
        check("rotated refresh token is persisted", refresh_auth.session["refresh_token"] == "refresh-2")

        print("All cloud-project regression tests passed.")
    finally:
        cp._request = original_request
        cp.MAX_UPLOAD = original_limit


if __name__ == "__main__":
    main()
