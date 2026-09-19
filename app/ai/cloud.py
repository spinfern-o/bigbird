"""Talk to the PhotoForge GPU server (e.g. on an NVIDIA Brev cloud GPU).

Also decides, per the user's AI Settings, whether heavy AI runs locally or in the cloud.
"""
import io
import json
import urllib.error
import urllib.request

import cv2
import numpy as np
from PySide6.QtCore import QSettings

from . import tasks

# The team's Brev GPU instance. Names don't change when it's stopped/started; only if it's
# deleted and recreated under another name would this need updating.
BREV_INSTANCE = "bigbird-gpu-dev"

UPLOAD_MAX = 2048   # the models work at ~1024 px, so bigger uploads only waste time


class CloudError(Exception):
    pass


# --------------------------------------------------------------------------- settings

def _settings():
    return QSettings("PhotoForge", "PhotoForge")


def get_settings():
    s = _settings()
    return {"mode": s.value("ai/mode", "local"),
            "url": s.value("ai/url", "http://localhost:8765"),
            "token": s.value("ai/token", ""),
            "instance": BREV_INSTANCE}


def set_value(key, value):
    _settings().setValue(key, value)


def save_settings(mode, url, token):
    s = _settings()
    s.setValue("ai/mode", mode)
    s.setValue("ai/url", url.rstrip("/"))
    s.setValue("ai/token", token)


_state = {"connected": False}
_listeners = []


def prefers_cloud():
    """The user chose the cloud GPU in AI Settings (it may not be connected right now)."""
    return get_settings()["mode"] == "cloud"


def set_connected(value):
    _state["connected"] = bool(value)


def is_connected():
    return _state["connected"]


def on_connection_lost(callback):
    _listeners.append(callback)


def use_cloud():
    """Run heavy AI in the cloud now? Only when chosen *and* connected; otherwise locally."""
    return prefers_cloud() and _state["connected"]


def where():
    return "your NVIDIA cloud GPU" if use_cloud() else None


# --------------------------------------------------------------------------- client

class Client:
    def __init__(self, url=None, token=None, timeout=120, notify=True):
        s = get_settings()
        self.url = (url or s["url"]).rstrip("/")
        self.token = token if token is not None else s["token"]
        self.timeout = timeout
        self.notify = notify  # tell listeners if an established connection drops

    def _request(self, path, body=None):
        req = urllib.request.Request(
            self.url + path, data=body, method="POST" if body is not None else "GET",
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/octet-stream"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("error", str(e))
            except Exception:
                msg = str(e)
            if e.code == 401:
                msg = "The access token doesn't match the server's PHOTOFORGE_TOKEN."
            raise CloudError(msg) from None
        except (urllib.error.URLError, OSError) as e:
            if self.notify and _state["connected"]:
                _state["connected"] = False
                for cb in list(_listeners):
                    cb()
            raise CloudError(
                f"Can't reach the cloud GPU at {self.url} ({getattr(e, 'reason', e)}).\n\n"
                "Check that your Brev GPU instance is running, then click Try Connecting Again "
                "in AI → AI Settings.") from None

    def _post(self, path, **arrays):
        buf = io.BytesIO()
        np.savez_compressed(buf, **arrays)
        with np.load(io.BytesIO(self._request(path, buf.getvalue())), allow_pickle=False) as z:
            return {k: z[k] for k in z.files}

    def health(self):
        return json.loads(self._request("/health"))

    # ---- tasks
    def remove_background(self, rgba):
        h, w = rgba.shape[:2]
        small = _shrink(rgba[..., :3], UPLOAD_MAX)
        mask = self._post("/remove_background", image=small)["mask"]
        return cv2.resize(mask, (w, h), interpolation=cv2.INTER_LINEAR)

    def sam_image(self, rgba):
        return CloudSam(self, rgba)


class CloudSam:
    """Same interface as tasks.SamImage, but the model runs on the cloud GPU."""

    def __init__(self, client, rgba):
        self.client = client
        self.h, self.w = rgba.shape[:2]
        small = _shrink(rgba[..., :3], 1024)   # SAM analyses the photo at 1024x1024 anyway
        self.sw, self.sh = small.shape[1], small.shape[0]
        self.session = str(client._post("/sam/encode", image=small)["session"])

    def decode(self, points, labels):
        pts = np.array(points, np.float32) * [self.sw / self.w, self.sh / self.h]
        r = self.client._post("/sam/decode", session=np.array(self.session), points=pts,
                              labels=np.array(labels, np.int64))
        return r["scores"], r["logits"].astype(np.float32)


def _shrink(rgb, max_side):
    h, w = rgb.shape[:2]
    f = min(1.0, max_side / max(h, w))
    if f >= 1.0:
        return np.ascontiguousarray(rgb)
    return cv2.resize(rgb, (max(1, int(w * f)), max(1, int(h * f))), interpolation=cv2.INTER_AREA)


# --------------------------------------------------------------------------- dispatch

def remove_background(rgba):
    return Client().remove_background(rgba) if use_cloud() else tasks.remove_background(rgba)


def sam_image(rgba):
    return Client().sam_image(rgba) if use_cloud() else tasks.SamImage(rgba)


def models_needed(keys):
    """Local runs need the models downloaded; cloud runs don't."""
    return [] if use_cloud() else keys
