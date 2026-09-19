"""Talk to the PhotoForge GPU server (e.g. on an NVIDIA Brev cloud GPU).

Also decides, per the user's AI Settings, whether heavy AI runs locally or in the cloud.
"""
import io
import json
import shutil
import urllib.error
import urllib.request

import cv2
import numpy as np
from PySide6.QtCore import QSettings

from . import tasks

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
            "instance": s.value("ai/brev_instance", "")}


def save_settings(mode, url, token, instance):
    s = _settings()
    s.setValue("ai/mode", mode)
    s.setValue("ai/url", url.rstrip("/"))
    s.setValue("ai/token", token)
    s.setValue("ai/brev_instance", instance)


def use_cloud():
    return get_settings()["mode"] == "cloud"


def where():
    return "NVIDIA cloud GPU" if use_cloud() else None


def brev_cli():
    return shutil.which("brev")


# --------------------------------------------------------------------------- client

class Client:
    def __init__(self, url=None, token=None, timeout=120):
        s = get_settings()
        self.url = (url or s["url"]).rstrip("/")
        self.token = token if token is not None else s["token"]
        self.timeout = timeout

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
            raise CloudError(
                f"Can't reach the cloud GPU at {self.url} ({getattr(e, 'reason', e)}).\n\n"
                "Check that the Brev instance is running, the PhotoForge server is started on "
                "it, and `brev port-forward` is connected (AI → AI Settings → Connect).") from None

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

    def fill(self, rgb, mask):
        """Fill the masked area of a full-size RGB image; only a crop around it is uploaded.
        Returns (filled RGB, soft blend mask). The area is grown a little first: leftover
        edge pixels of a removed object would otherwise be "continued" into the fill."""
        h, w = mask.shape
        grow = int(max(6, 0.012 * np.hypot(h, w)))
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1))
        hole = cv2.dilate(((mask > 20) * 255).astype(np.uint8), k)
        x0, y0, x1, y1 = tasks.fill_box(hole)
        filled = self._post("/fill", image=np.ascontiguousarray(rgb[y0:y1, x0:x1]),
                            mask=np.ascontiguousarray(hole[y0:y1, x0:x1]))["image"]
        out = rgb.copy()
        out[y0:y1, x0:x1] = filled
        soft = np.maximum(cv2.GaussianBlur(hole, (0, 0), grow / 3), mask)
        return out, soft


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
