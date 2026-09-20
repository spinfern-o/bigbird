"""Tests for the AI backend interface. No network, no NVIDIA key, no account.

Run:  python app/ai/test_base.py
"""
import base64
import io
import json
import os
import sys
import urllib.error

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.ai import base  # noqa: E402


class FakeAuth:
    def __init__(self, token=None):
        self.access_token = token


def png_b64(rgba):
    """Encode like a server would: BGR(A) on the wire."""
    conv = cv2.COLOR_RGBA2BGRA if rgba.shape[2] == 4 else cv2.COLOR_RGB2BGR
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgba, conv))
    assert ok
    return base64.b64encode(buf.tobytes()).decode()


class Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


results = []


def check(name, cond, detail=""):
    results.append(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{('  ' + detail) if detail else ''}")


# ---------------------------------------------------------------- gatekeeping
img = np.full((64, 48, 4), 255, np.uint8)

try:
    base.CloudBackend(FakeAuth(None)).run(base.DESCRIBE_EDIT, img, prompt="sunset")
    check("guest (no token) is refused", False)
except base.AIError as e:
    check("guest (no token) is refused", "Sign in" in str(e), f"-> {e}")

try:
    base.CloudBackend(FakeAuth("tok")).run(base.DESCRIBE_EDIT, img, prompt="   ")
    check("empty prompt is refused", False)
except base.AIError as e:
    check("empty prompt is refused", "Describe" in str(e), f"-> {e}")

try:
    base.CloudBackend(FakeAuth("tok")).run(base.REMOVE_BACKGROUND, img, prompt="x")
    check("local-only task refused by cloud backend", False)
except base.AIError:
    check("local-only task refused by cloud backend", True)

try:
    base.LocalBackend().run(base.DESCRIBE_EDIT, img)
    check("cloud-only task refused by local backend", False)
except base.AIError as e:
    check("cloud-only task refused by local backend", "Sign in" in str(e), f"-> {e}")


# -------------------------------------------------------------------- notice
check("cloud notice shown for remote task", base.cloud_notice(base.DESCRIBE_EDIT) is not None)
check("no notice for local task", base.cloud_notice(base.REMOVE_BACKGROUND) is None)
check("notice names the destination", "NVIDIA" in (base.cloud_notice(base.DESCRIBE_EDIT) or ""))


# ------------------------------------------------------------------- routing
check("remote task routes to cloud", base.pick_backend(base.DESCRIBE_EDIT, FakeAuth("t")).is_cloud)
check("local task stays local", not base.pick_backend(base.REMOVE_BACKGROUND, FakeAuth("t")).is_cloud)
check("prefer_cloud honoured",
      base.pick_backend(base.REMOVE_BACKGROUND, FakeAuth("t"), prefer_cloud=True).is_cloud)


# --------------------------------------------------- round trip + colour + size
# A photo with distinct channels: if RGB/BGR gets swapped anywhere, this fails.
src = np.zeros((300, 200, 4), np.uint8)
src[..., 0], src[..., 1], src[..., 2], src[..., 3] = 200, 100, 50, 255

captured = {}


def fake_urlopen(req, timeout=None):
    captured["body"] = json.loads(req.data)
    captured["auth"] = req.headers.get("Authorization")
    # Echo the image straight back, as a perfect model would.
    return Resp({"image": captured["body"]["image"]})


base.urllib.request.urlopen = fake_urlopen
out = base.CloudBackend(FakeAuth("tok-123")).run(base.DESCRIBE_EDIT, src, prompt="make it sunset")

check("sends bearer token", captured["auth"] == "Bearer tok-123")
check("result restored to original size", out.shape[:2] == src.shape[:2],
      f"{out.shape[:2]} vs {src.shape[:2]}")
check("colour preserved through round trip (no BGR swap)",
      tuple(out[0, 0][:3]) == (200, 100, 50), f"got {tuple(out[0, 0][:3])}, want (200, 100, 50)")


# ----------------------------------------------------------------- downscaling
# Random noise, not flat colour: PNG can't compress it, so this is the worst
# case a real photo could produce rather than a trivially-passing test.
rng = np.random.default_rng(0)
big = rng.integers(0, 256, (4000, 3000, 4), dtype=np.uint8)
base.CloudBackend(FakeAuth("tok")).run(base.DESCRIBE_EDIT, big, prompt="x")
sent = base.np.frombuffer(base.base64.b64decode(captured["body"]["image"]), np.uint8)
decoded = cv2.imdecode(sent, cv2.IMREAD_UNCHANGED)
check("large photo downscaled before upload",
      max(decoded.shape[:2]) == base.CLOUD_MAX_EDGE, f"max edge {max(decoded.shape[:2])}")
payload_mb = len(json.dumps(captured["body"])) / 1e6
check("payload stays under Vercel's 4.5 MB cap", payload_mb < 4.0, f"{payload_mb:.2f} MB")

small = np.full((80, 60, 4), 7, np.uint8)
base.CloudBackend(FakeAuth("tok")).run(base.DESCRIBE_EDIT, small, prompt="x")
d2 = cv2.imdecode(np.frombuffer(base64.b64decode(captured["body"]["image"]), np.uint8),
                  cv2.IMREAD_UNCHANGED)
check("small photo not upscaled", d2.shape[:2] == (80, 60), f"{d2.shape[:2]}")

mask = np.zeros((80, 60), np.uint8)
mask[20:50, 10:40] = 255
base.CloudBackend(FakeAuth("tok")).run(base.DESCRIBE_EDIT, small, mask=mask, prompt="edit selection")
mask_wire = cv2.imdecode(
    np.frombuffer(base64.b64decode(captured["body"]["mask"]), np.uint8),
    cv2.IMREAD_UNCHANGED,
)
check("2-D selection mask encodes successfully", mask_wire.shape[:2] == mask.shape)


# ------------------------------------------------------------- error surfacing
def raise_http(code, payload):
    def f(req, timeout=None):
        raise urllib.error.HTTPError(
            "u", code, "err", {}, io.BytesIO(json.dumps(payload).encode()))
    return f


base.urllib.request.urlopen = raise_http(429, {"error": "Cloud AI is busy right now."})
try:
    base.CloudBackend(FakeAuth("tok")).run(base.DESCRIBE_EDIT, img, prompt="x")
    check("endpoint's own message reaches the user", False)
except base.AIError as e:
    check("endpoint's own message reaches the user", "busy" in str(e), f"-> {e}")


def raise_url(req, timeout=None):
    raise urllib.error.URLError("offline")


base.urllib.request.urlopen = raise_url
try:
    base.CloudBackend(FakeAuth("tok")).run(base.DESCRIBE_EDIT, img, prompt="x")
    check("offline gives a plain-English message", False)
except base.AIError as e:
    check("offline gives a plain-English message", "internet" in str(e), f"-> {e}")

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
