"""Cloud project storage for signed-in PhotoForge users.

Project metadata lives in Supabase Postgres and the .pforge file + thumbnail live
in the private projects Storage bucket. RLS policies in the Supabase migration
restrict both rows and object paths to the authenticated user.
"""
from __future__ import annotations

import base64
import datetime
import io
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import quote

# The anon/publishable key is intentionally public client configuration. It does
# not bypass RLS. Environment variables make local/staging projects easy to use.
SUPABASE_URL = os.environ.get(
    "PHOTOFORGE_SUPABASE_URL",
    "https://nxmnoduohwbnelgjupfw.supabase.co",
).rstrip("/")
SUPABASE_ANON_KEY = os.environ.get(
    "PHOTOFORGE_SUPABASE_ANON_KEY",
    (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJpc3MiOiJIUzI1NiIsInJlZiI6Im54bW5vZHVvaHdibmVsZ2p1cGZ3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODk4NDI4NjQsImV4cCI6MjEwNTQxODg2NH0."
        "eOn1bj8aXi9I5E27Vop-oDKHb425MNiXBI6kxfrTN_s"
    ),
)
BUCKET = "projects"
MAX_UPLOAD = 50 * 1024 * 1024


class CloudError(Exception):
    """A user-facing cloud-project error."""


def _request(method, url, data=None, headers=None, timeout=120):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(body)
            msg = payload.get("message") or payload.get("error_description") or payload.get("error") or body
        except (ValueError, TypeError):
            msg = body
        if exc.code in (401, 403):
            raise CloudError("Your sign-in has expired or no longer has access. Please log in again.") from None
        raise CloudError(f"{msg or 'Cloud request failed'} (HTTP {exc.code})") from None
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise CloudError(f"Can't reach PhotoForge cloud storage. Check your internet connection.\n({reason})") from None


class Api:
    """Supabase REST/Storage client authorized with the user's desktop session."""

    def __init__(self, auth):
        self.auth = auth

    def _token(self):
        if not self.auth.is_logged_in:
            raise CloudError("Please log in first.")

        session = self.auth.session
        token = session.get("access_token")
        if not token:
            raise CloudError("Your sign-in is incomplete. Please log in again.")

        expires = int(float(session.get("expires_at") or 0))
        if expires and expires - time.time() < 120:
            self._refresh(session)
            session = self.auth.session
            token = session.get("access_token")
        if not token:
            raise CloudError("Your sign-in could not be refreshed. Please log in again.")
        return token

    def _refresh(self, session):
        refresh_token = session.get("refresh_token")
        if not refresh_token:
            raise CloudError("Your sign-in has expired. Please log in again.")

        body = json.dumps({"refresh_token": refresh_token}).encode()
        data = _request(
            "POST",
            f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
            body,
            {"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
            timeout=30,
        )
        new = json.loads(data)
        expires_at = new.get("expires_at")
        if not expires_at and new.get("expires_in"):
            expires_at = int(time.time()) + int(new["expires_in"])
        self.auth.update_session(
            access_token=new.get("access_token"),
            refresh_token=new.get("refresh_token") or refresh_token,
            expires_at=str(expires_at or ""),
            email=(new.get("user") or {}).get("email") or session.get("email"),
        )

    def user_id(self):
        """Return the UUID in the authenticated JWT sub claim.

        RLS still validates the token server-side; this value only chooses the
        user's Storage folder and adds an explicit REST filter.
        """
        token = self._token()
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            sub = json.loads(base64.urlsafe_b64decode(payload.encode()))["sub"]
            return str(uuid.UUID(str(sub)))
        except (IndexError, KeyError, ValueError, TypeError, json.JSONDecodeError):
            raise CloudError("Your saved sign-in is invalid. Please log in again.") from None

    def _headers(self, extra=None):
        headers = {
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {self._token()}",
        }
        headers.update(extra or {})
        return headers

    def list_projects(self):
        uid = quote(self.user_id(), safe="")
        url = (
            f"{SUPABASE_URL}/rest/v1/projects"
            f"?select=id,name,file_path,thumb_path,size_bytes,width,height,updated_at"
            f"&user_id=eq.{uid}&order=updated_at.desc"
        )
        return json.loads(_request("GET", url, headers=self._headers()))

    @staticmethod
    def _object_path(path):
        return quote(path, safe="/")

    def _upload_file(self, path, data, content_type):
        encoded = self._object_path(path)
        url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{encoded}"
        _request(
            "POST",
            url,
            data,
            self._headers({
                "Content-Type": content_type,
                "x-upsert": "true",
                "Content-Length": str(len(data)),
            }),
        )

    def download_project(self, file_path):
        encoded = self._object_path(file_path)
        url = f"{SUPABASE_URL}/storage/v1/object/authenticated/{BUCKET}/{encoded}"
        return _request("GET", url, headers=self._headers())

    def download_thumb(self, thumb_path):
        try:
            return self.download_project(thumb_path)
        except CloudError:
            return None

    def _delete_file(self, path):
        encoded = self._object_path(path)
        url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{encoded}"
        _request("DELETE", url, headers=self._headers())

    def save_project(self, name, project_bytes, thumb_jpeg, width, height, project_id=None):
        """Upload a .pforge file/thumbnail and create or update its metadata row."""
        if len(project_bytes) > MAX_UPLOAD:
            raise CloudError(
                f"This project is {len(project_bytes) / 1048576:.0f} MB, and the cloud limit is "
                f"{MAX_UPLOAD // 1048576} MB per project.\n\n"
                "Flatten layers or resize the image, then try again."
            )

        uid = self.user_id()
        key = str(uuid.UUID(str(project_id))) if project_id else str(uuid.uuid4())
        file_path = f"{uid}/{key}.pforge"
        thumb_path = f"{uid}/{key}.jpg"

        self._upload_file(file_path, project_bytes, "application/octet-stream")
        if thumb_jpeg:
            self._upload_file(thumb_path, thumb_jpeg, "image/jpeg")

        row = {
            "user_id": uid,
            "name": name,
            "file_path": file_path,
            "thumb_path": thumb_path,
            "size_bytes": len(project_bytes),
            "width": int(width),
            "height": int(height),
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        headers = self._headers({
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        })

        if project_id:
            url = f"{SUPABASE_URL}/rest/v1/projects?id=eq.{key}&user_id=eq.{uid}"
            out = _request("PATCH", url, json.dumps(row).encode(), headers)
        else:
            row["id"] = key
            out = _request(
                "POST",
                f"{SUPABASE_URL}/rest/v1/projects",
                json.dumps(row).encode(),
                headers,
            )

        result = json.loads(out) if out else []
        return result[0] if isinstance(result, list) and result else {"id": key, **row}

    def delete_project(self, row):
        uid = self.user_id()
        project_id = str(uuid.UUID(str(row["id"])))
        _request(
            "DELETE",
            f"{SUPABASE_URL}/rest/v1/projects?id=eq.{project_id}&user_id=eq.{uid}",
            headers=self._headers(),
        )
        for path in (row.get("file_path"), row.get("thumb_path")):
            if path:
                self._delete_file(path)


def project_bytes(doc):
    """Serialize a document to in-memory .pforge bytes."""
    from . import imageio

    buf = io.BytesIO()
    imageio.save_project(doc, buf)
    return buf.getvalue()


def thumbnail_jpeg(doc, size=320):
    """Return a small JPEG preview of the current rendered project."""
    from PIL import Image
    from . import imageio

    small = imageio.thumbnail(doc.render_final(), size)
    im = Image.fromarray(small)
    if im.mode == "RGBA":
        bg = Image.new("RGB", im.size, (32, 32, 36))
        bg.paste(im, mask=im.getchannel("A"))
        im = bg
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return buf.getvalue()
