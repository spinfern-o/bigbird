"""Saving and opening PhotoForge projects in the user's phrame.tech account (Supabase).

Projects are stored per user: the file in the private "projects" storage bucket under a
folder named after the user id, and a row in the "projects" table. Supabase's row-level
security means a signed-in user can only ever see their own.

Only the public anon key is used here (it's meant to ship inside apps); everything is
authorized by the user's own login token.
"""
import base64
import datetime
import io
import json
import time
import urllib.error
import urllib.request
import uuid

SUPABASE_URL = "https://nxmnoduohwbnelgjupfw.supabase.co"
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im54bW5vZHVvaHdibmVs"
    "Z2p1cGZ3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODk4NDI4NjQsImV4cCI6MjEwNTQxODg2NH0."
    "eOn1bj8aXi9I5E27Vop-oDKHb425MNiXBI6kxfrTN_s")
BUCKET = "projects"
MAX_UPLOAD = 50 * 1024 * 1024   # Supabase free tier limit per file


class CloudError(Exception):
    pass


def _request(method, url, data=None, headers=None, timeout=120):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(body).get("message") or json.loads(body).get("error") or body
        except ValueError:
            msg = body
        if e.code in (401, 403):
            raise CloudError("Your sign-in has expired. Please log in again.") from None
        raise CloudError(f"{msg} (HTTP {e.code})") from None
    except (urllib.error.URLError, OSError) as e:
        raise CloudError("Can't reach phrame.tech. Check your internet connection.\n"
                         f"({getattr(e, 'reason', e)})") from None


class Api:
    """Talks to the account's cloud storage using the signed-in user's token."""

    def __init__(self, auth):
        self.auth = auth

    # ------------------------------------------------------------------ session
    def _token(self):
        if not self.auth.is_logged_in:
            raise CloudError("Please log in first.")
        session = self.auth.session
        expires = int(session.get("expires_at") or 0)
        if expires and expires - time.time() < 120:
            self._refresh(session)
            session = self.auth.session
        return session["access_token"]

    def _refresh(self, session):
        body = json.dumps({"refresh_token": session.get("refresh_token", "")}).encode()
        data = _request("POST", f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token", body,
                        {"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
                        timeout=30)
        new = json.loads(data)
        self.auth.update_session(access_token=new["access_token"],
                                 refresh_token=new.get("refresh_token", ""),
                                 expires_at=str(new.get("expires_at", "")),
                                 email=(new.get("user") or {}).get("email", session.get("email")))

    def user_id(self):
        """The signed-in user's id, read from their token."""
        payload = self._token().split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))["sub"]

    def _headers(self, extra=None):
        h = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {self._token()}"}
        h.update(extra or {})
        return h

    # ------------------------------------------------------------------ projects
    def list_projects(self):
        url = (f"{SUPABASE_URL}/rest/v1/projects?select=id,name,file_path,thumb_path,size_bytes,"
               "width,height,updated_at&order=updated_at.desc")
        return json.loads(_request("GET", url, headers=self._headers()))

    def _upload_file(self, path, data, content_type):
        url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}"
        _request("POST", url, data,
                 self._headers({"Content-Type": content_type, "x-upsert": "true",
                                "Content-Length": str(len(data))}))

    def save_project(self, name, project_bytes, thumb_png, width, height, project_id=None):
        """Upload a .pforge file (and its thumbnail) and add or update its row."""
        if len(project_bytes) > MAX_UPLOAD:
            raise CloudError(
                f"This project is {len(project_bytes) / 1048576:.0f} MB, and the cloud limit is "
                f"{MAX_UPLOAD // 1048576} MB per project.\n\nTip: flatten layers "
                "(Image → Flatten) or resize the image, then try again.")
        uid = self.user_id()
        key = project_id or str(uuid.uuid4())
        file_path = f"{uid}/{key}.pforge"
        thumb_path = f"{uid}/{key}.jpg"
        self._upload_file(file_path, project_bytes, "application/octet-stream")
        if thumb_png:
            self._upload_file(thumb_path, thumb_png, "image/jpeg")
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        row = {"name": name, "file_path": file_path, "thumb_path": thumb_path,
               "size_bytes": len(project_bytes), "width": width, "height": height,
               "updated_at": now}
        headers = self._headers({"Content-Type": "application/json",
                                 "Prefer": "return=representation"})
        if project_id:
            url = f"{SUPABASE_URL}/rest/v1/projects?id=eq.{project_id}"
            out = _request("PATCH", url, json.dumps(row).encode(), headers)
        else:
            row["id"] = key
            out = _request("POST", f"{SUPABASE_URL}/rest/v1/projects", json.dumps(row).encode(),
                           headers)
        result = json.loads(out)
        return result[0] if isinstance(result, list) and result else {"id": key, **row}

    def download_project(self, file_path):
        url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{file_path}"
        return _request("GET", url, headers=self._headers())

    def download_thumb(self, thumb_path):
        try:
            return self.download_project(thumb_path)
        except CloudError:
            return None

    def delete_project(self, row):
        _request("DELETE", f"{SUPABASE_URL}/rest/v1/projects?id=eq.{row['id']}",
                 headers=self._headers())
        for path in (row.get("file_path"), row.get("thumb_path")):
            if path:
                try:
                    _request("DELETE", f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}",
                             headers=self._headers())
                except CloudError:
                    pass


def project_bytes(doc):
    """Serialize a document to .pforge bytes (same format as a local project file)."""
    from . import imageio
    buf = io.BytesIO()
    imageio.save_project(doc, buf)
    return buf.getvalue()


def thumbnail_jpeg(doc, size=320):
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
