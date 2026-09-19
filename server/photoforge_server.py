"""PhotoForge GPU server: runs the heavy AI models on a cloud GPU (e.g. NVIDIA Brev).

The desktop app sends images here instead of running the models itself. Requests and
responses are numpy .npz files; every request must carry the access token.

Run on the GPU machine (from the repository root):

    export PHOTOFORGE_TOKEN="choose-a-long-random-secret"
    python -m server.photoforge_server --port 8765

Then from your PC:  brev port-forward <instance-name> --port 8765:8765
"""
import argparse
import hmac
import io
import json
import os
import sys
import threading
import time
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:  # pip-installed CUDA/cuDNN libraries (onnxruntime-gpu[cuda,cudnn]) must be preloaded
    import onnxruntime as _ort
    if hasattr(_ort, "preload_dlls"):
        _ort.preload_dlls()
except Exception:
    pass

from app.ai import models, tasks  # noqa: E402

MAX_BODY = 200 * 1024 * 1024
TOKEN = os.environ.get("PHOTOFORGE_TOKEN", "")
_sam_sessions = OrderedDict()   # session id -> SamImage (image analysed once, many clicks)
_sam_lock = threading.Lock()
MAX_SAM_SESSIONS = 8


def _npz(**arrays):
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)
    return buf.getvalue()


def _load(body):
    with np.load(io.BytesIO(body), allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


# --------------------------------------------------------------------------- endpoints

def ep_health(_):
    import onnxruntime as ort
    gpu = models.device_name()
    return {"ok": True, "device": gpu, "providers": ort.get_available_providers(),
            "models": {k: models.is_downloaded(k) for k in models.MODELS}}


def ep_remove_background(req):
    return {"mask": tasks.remove_background(req["image"])}


def ep_sam_encode(req):
    sam = tasks.SamImage(req["image"])
    sid = uuid.uuid4().hex
    with _sam_lock:
        _sam_sessions[sid] = sam
        while len(_sam_sessions) > MAX_SAM_SESSIONS:
            _sam_sessions.popitem(last=False)
    return {"session": np.array(sid)}


def ep_sam_decode(req):
    sid = str(req["session"])
    with _sam_lock:
        sam = _sam_sessions.get(sid)
        if sam is not None:
            _sam_sessions.move_to_end(sid)
    if sam is None:
        raise KeyError("unknown or expired selection session")
    scores, logits = sam.decode(req["points"].tolist(), req["labels"].tolist())
    return {"scores": scores.astype(np.float32), "logits": logits.astype(np.float16)}


def ep_fill(req):
    return {"image": tasks.lama_fill(req["image"], req["mask"])}


ROUTES = {"/remove_background": ("birefnet_lite", ep_remove_background),
          "/sam/encode": ("sam2", ep_sam_encode),
          "/sam/decode": ("sam2", ep_sam_decode),
          "/fill": ("lama", ep_fill)}


class Handler(BaseHTTPRequestHandler):
    server_version = "PhotoForgeGPU/1"

    def _authorized(self):
        given = self.headers.get("Authorization", "")
        return bool(TOKEN) and hmac.compare_digest(given.encode(), f"Bearer {TOKEN}".encode())

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code, msg):
        self._send(code, json.dumps({"error": msg}).encode(), "application/json")

    def do_GET(self):
        if not self._authorized():
            return self._error(401, "missing or wrong access token")
        if self.path != "/health":
            return self._error(404, "not found")
        self._send(200, json.dumps(ep_health(None)).encode(), "application/json")

    def do_POST(self):
        if not self._authorized():
            return self._error(401, "missing or wrong access token")
        route = ROUTES.get(self.path)
        if route is None:
            return self._error(404, "not found")
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self._error(413, "request too large or empty")
        key, fn = route
        try:
            if not models.is_downloaded(key):
                models.download(key)
            t = time.time()
            out = fn(_load(self.rfile.read(length)))
            self.log_message("%s done in %.2fs", self.path, time.time() - t)
            self._send(200, _npz(**out), "application/octet-stream")
        except KeyError as e:
            self._error(410, str(e))
        except Exception as e:  # report failures to the app instead of dropping the connection
            self._error(500, f"{type(e).__name__}: {e}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1",
                    help="127.0.0.1 (default) is reachable through `brev port-forward` / SSH "
                         "tunnels only, which is what you want.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--preload", action="store_true", help="download all models at startup")
    args = ap.parse_args()
    if not TOKEN:
        sys.exit("Set PHOTOFORGE_TOKEN to a long random secret first (the app sends it with "
                 "every request).")
    if args.preload:
        for k in models.MODELS:
            if not models.is_downloaded(k):
                print("downloading", models.MODELS[k].name, "...")
                models.download(k)
    print(f"PhotoForge GPU server on http://{args.host}:{args.port}  ({models.device_name()})")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
