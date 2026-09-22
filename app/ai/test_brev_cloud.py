"""Regression tests for the optional Brev accelerator.

Run from the repository root:
    python app/ai/test_brev_cloud.py

No Brev account, network access, or NVIDIA key is required.
"""
import io
import json
import os
import sys
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# This is deliberately imported before PhotoForge's object-selector module.  The old
# app/ai/select.py filename shadowed Python's stdlib select module when tests were run
# directly from app/ai.
import select as stdlib_select  # noqa: E402

from app.ai import cloud, connection  # noqa: E402


class _Resp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def main():
    check("stdlib select is not shadowed", callable(stdlib_select.select))

    small = np.zeros((100, 200, 3), np.uint8)
    same = cloud._shrink(small, 300)
    check("small image is not resized", same.shape == (100, 200, 3))

    big = np.zeros((2000, 1000, 3), np.uint8)
    shrunk = cloud._shrink(big, 1000)
    check("large image respects max edge", shrunk.shape[:2] == (1000, 500))

    client = cloud.Client(url="http://127.0.0.1:8765/", token="abc", notify=False)
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        return _Resp(json.dumps({"ok": True, "device": "test"}).encode())

    with patch("app.ai.cloud.urllib.request.urlopen", fake_urlopen):
        health = client.health()
    check("health endpoint requested", seen["url"].endswith("/health"))
    check("bearer token attached", seen["auth"] == "Bearer abc")
    check("health JSON decoded", health["ok"] is True)

    forward = connection._Forward()
    with patch("app.ai.connection._tunnel_cmd", return_value=None):
        try:
            forward.start("bigbird-gpu-dev", 8765)
            raised = False
        except RuntimeError as e:
            raised = "Brev connection tools" in str(e)
    check("missing Brev tools fail clearly", raised)

    rgba = np.zeros((100, 200, 4), np.uint8)
    calls = []

    class FakeClient:
        def _post(self, path, **arrays):
            calls.append((path, arrays))
            if path == "/sam/encode":
                return {"session": np.array("session-1")}
            return {
                "scores": np.array([0.1, 0.9, 0.2], np.float32),
                "logits": np.zeros((3, 256, 256), np.float16),
            }

    sam = cloud.CloudSam(FakeClient(), rgba)
    sam.decode([(100, 50)], [1])
    check("SAM encode uses Brev endpoint", calls[0][0] == "/sam/encode")
    check("SAM decode uses Brev endpoint", calls[1][0] == "/sam/decode")
    point = calls[1][1]["points"][0]
    check("SAM coordinates scale to upload", np.allclose(point, [100.0, 50.0]))

    # ---- `brev ls` only ever lists the ACTIVE org, so the message has to say which one.
    def fake_ls(text):
        connection._brev_cmd = lambda args: ["brev"] + args
        connection._run = lambda args, timeout=30: (0, text)

    real_cmd, real_run = connection._brev_cmd, connection._run
    try:
        fake_ls("You have 1 instances in Org my-org\n"
                " NAME    STATUS   BUILD      SHELL  ID   MACHINE    GPU\n"
                " gpu-a   RUNNING  COMPLETED  READY  aaa  g5.xlarge  A10G")
        instances, org = connection.list_instances()
        check("instances parsed from brev ls", instances == [("gpu-a", "RUNNING")])
        check("active org reported", org == "my-org")

        fake_ls("You have 0 instances in Org other-org")
        instances, org = connection.list_instances()
        check("empty org still reports its name", instances == [] and org == "other-org")

        fake_ls("Error: you must login first. Run brev login")
        check("signed-out CLI is reported as signed out",
              "login" in str(connection.list_instances()).lower()
              and "isn't logged in" in str(connection.list_instances()))
    finally:
        connection._brev_cmd, connection._run = real_cmd, real_run

    print("All Brev accelerator regression tests passed.")


if __name__ == "__main__":
    main()
