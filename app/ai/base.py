"""One interface over the two places AI work can happen (roadmap A2).

    LocalBackend   ONNX Runtime on this computer. Free, private, no account.
    CloudBackend   NVIDIA NIM, reached through our own web endpoint.

Both answer the same call::

    backend.run(task, image, mask=None, prompt="") -> image

Why the cloud path goes through our own endpoint
------------------------------------------------
The NVIDIA key is never in this app. A key shipped inside PhotoForge is
readable with ``strings`` on the PyInstaller bundle; once extracted anyone can
spend the credits and it cannot be revoked without updating every user. So the
app sends the Supabase access token it already has from signing in
(``app/auth.py``) to ``web/app/api/edit/route.ts``, and that endpoint -- which
does hold the key -- talks to NVIDIA.

Consequences worth knowing:
  * Cloud features require being signed in. Guests get a clear message.
  * Photos sent to the cloud leave the user's computer, so callers must show
    the notice A2 requires before the first cloud call. See ``cloud_notice()``.
"""

import base64
import json
import os
import urllib.error
import urllib.request

import cv2
import numpy as np

from . import tasks

# Where our proxy lives. Override for local development:
#   export PHOTOFORGE_CLOUD_URL="http://localhost:3000/api/edit"
DEFAULT_CLOUD_URL = "https://phrame.tech/api/edit"

# Generative models work at roughly 1 megapixel, and Vercel caps function
# request bodies at 4.5 MB. Downscaling to this before sending keeps a base64
# PNG around 1.4 MB and loses nothing the model would have used anyway.
CLOUD_MAX_EDGE = 1024

CLOUD_TIMEOUT_SECONDS = 120

# Tasks. Local ones run here; REMOTE_TASKS must go to the cloud.
REMOVE_BACKGROUND = "remove_background"
DESCRIBE_EDIT = "describe_edit"      # A6: "make it sunset", generative fill
REMOTE_TASKS = frozenset({DESCRIBE_EDIT})


class AIError(Exception):
    """A failure with a message that is safe and useful to show the user."""


def cloud_notice(task):
    """The warning to show before a photo leaves the user's computer (A2).

    Returns None for tasks that run locally, so callers can use it as the
    condition for showing a confirmation dialog.
    """
    if task not in REMOTE_TASKS:
        return None
    return ("This feature sends your photo to NVIDIA's servers to be edited.\n\n"
            "Everything else in PhotoForge runs on your own computer. Your photo "
            "is used only to produce this edit.\n\nSend it?")


# --------------------------------------------------------------------- local
class LocalBackend:
    """Runs on this computer via ONNX Runtime. No account, nothing uploaded."""

    is_cloud = False

    def run(self, task, image, mask=None, prompt=""):
        if task == REMOVE_BACKGROUND:
            return tasks.remove_background(image)
        raise AIError(
            "That feature isn't available on this computer. "
            "Sign in to use the cloud version."
        )


# --------------------------------------------------------------------- cloud
class CloudBackend:
    """Reaches NVIDIA through our own endpoint, which holds the API key."""

    is_cloud = True

    def __init__(self, auth, url=None):
        self.auth = auth
        self.url = (url or os.environ.get("PHOTOFORGE_CLOUD_URL", DEFAULT_CLOUD_URL)).rstrip("/")

    # ------------------------------------------------------------- encoding
    @staticmethod
    def _encode(rgba):
        """Downscale to CLOUD_MAX_EDGE and return (base64 PNG, original h, w)."""
        h, w = rgba.shape[:2]
        scale = min(1.0, CLOUD_MAX_EDGE / max(h, w))
        if scale < 1.0:
            rgba = cv2.resize(rgba, (max(1, int(w * scale)), max(1, int(h * scale))),
                              interpolation=cv2.INTER_AREA)
        # cv2 encodes BGR(A); our arrays are RGB(A).
        bgr = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA if rgba.shape[2] == 4 else cv2.COLOR_RGB2BGR)
        ok, buf = cv2.imencode(".png", bgr)
        if not ok:
            raise AIError("That photo could not be prepared for cloud editing.")
        return base64.b64encode(buf.tobytes()).decode(), h, w

    @staticmethod
    def _decode(b64, h, w):
        """Decode the returned PNG and scale it back to the original size."""
        try:
            raw = np.frombuffer(base64.b64decode(b64), np.uint8)
            img = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
        except (ValueError, TypeError):
            img = None
        if img is None:
            raise AIError("The cloud AI service returned an image we couldn't read.")
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGBA)
        elif img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGBA)
        else:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
        if img.shape[:2] != (h, w):
            img = cv2.resize(img, (w, h), interpolation=cv2.INTER_LANCZOS4)
        return img

    # ------------------------------------------------------------------ run
    def run(self, task, image, mask=None, prompt=""):
        if task not in REMOTE_TASKS:
            raise AIError("That feature doesn't run in the cloud.")

        token = getattr(self.auth, "access_token", None)
        if not token:
            raise AIError("Sign in to your PhotoForge account to use cloud AI features.")
        if not prompt.strip():
            raise AIError("Describe the edit you'd like.")

        payload_image, h, w = self._encode(image)
        payload = {"prompt": prompt.strip(), "image": payload_image}
        if mask is not None:
            payload["mask"], _, _ = self._encode(mask)

        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=CLOUD_TIMEOUT_SECONDS) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise AIError(self._error_message(e))
        except urllib.error.URLError:
            raise AIError("Couldn't reach the cloud AI service. Check your internet connection.")
        except ValueError:
            raise AIError("The cloud AI service sent back something unexpected.")

        result = body.get("image")
        if not result:
            raise AIError("The cloud AI service didn't return an edited photo.")
        return self._decode(result, h, w)

    @staticmethod
    def _error_message(e):
        """Prefer the endpoint's own wording -- it is already user-facing."""
        try:
            message = json.loads(e.read()).get("error")
        except Exception:
            message = None
        if message:
            return message
        if e.code == 401:
            return "Your sign-in has expired. Please sign in again."
        return "The cloud AI service couldn't complete that edit. Please try again."


# ------------------------------------------------------------------ routing
def pick_backend(task, auth, prefer_cloud=False):
    """Choose where a task should run.

    Tasks in REMOTE_TASKS have no local implementation and always go to the
    cloud. Everything else stays local unless the user asked otherwise in AI
    Settings -- local is free, private and usually faster.
    """
    if task in REMOTE_TASKS or prefer_cloud:
        return CloudBackend(auth)
    return LocalBackend()
