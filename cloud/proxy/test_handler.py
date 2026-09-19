"""Test the proxy's gatekeeping without AWS or a network."""
import json, sys, types, urllib.error, io

# --- stub boto3 before importing the handler ---
boto3 = types.ModuleType("boto3")
class _Secrets:
    def get_secret_value(self, SecretId): return {"SecretString": json.dumps({"api_key":"nvapi-test"})}
boto3.client = lambda *a, **k: _Secrets()
boto3.resource = lambda *a, **k: None
sys.modules["boto3"] = boto3

import os
os.environ.update(SUPABASE_URL="https://proj.supabase.co", NVIDIA_SECRET_ARN="arn:aws:x",
                  NIM_ENDPOINT="https://ai.api.nvidia.com/v1/genai/v/m", QUOTA_TABLE="")
sys.path.insert(0, "/Users/larrywang/projects/bigbird/cloud/proxy")
import handler

VALID = "good-token"
def fake_urlopen(req, timeout=None):
    url = req.full_url
    if "/auth/v1/user" in url:
        if req.headers.get("Authorization") == f"Bearer {VALID}":
            return io.BytesIO(json.dumps({"id":"user-123","email":"a@b.c"}).encode())
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)
    return io.BytesIO(json.dumps({"artifacts":[{"base64":"RURJVEVE"}]}).encode())
class _CM:
    def __init__(self, f): self.f = f
    def __enter__(self): return self.f
    def __exit__(self, *a): return False
handler.urllib.request.urlopen = lambda req, timeout=None: _CM(fake_urlopen(req, timeout))

def call(headers, body):
    r = handler.lambda_handler({"headers": headers, "body": json.dumps(body)}, None)
    return r["statusCode"], json.loads(r["body"])

IMG = "aGVsbG8="
cases = [
    ("guest / no Authorization header", {},                                    {"image":IMG,"prompt":"sunset"}, 401),
    ("wrong auth scheme",               {"Authorization":"Basic abc"},         {"image":IMG,"prompt":"sunset"}, 401),
    ("expired / invalid token",         {"Authorization":"Bearer stale"},      {"image":IMG,"prompt":"sunset"}, 401),
    ("signed in, no image",             {"Authorization":f"Bearer {VALID}"},   {"prompt":"sunset"},             400),
    ("signed in, empty prompt",         {"Authorization":f"Bearer {VALID}"},   {"image":IMG,"prompt":"  "},     400),
    ("signed in, valid request",        {"Authorization":f"Bearer {VALID}"},   {"image":IMG,"prompt":"sunset"}, 200),
    ("header case-insensitivity",       {"authorization":f"Bearer {VALID}"},   {"image":IMG,"prompt":"sunset"}, 200),
]
fails = 0
for name, hdrs, body, want in cases:
    got, payload = call(hdrs, body)
    ok = got == want
    fails += not ok
    msg = payload.get("error", "(success)")
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:34s} -> {got} (want {want})  {msg[:52]}")

# oversized
handler.MAX_IMAGE_BYTES = 4
got, payload = call({"Authorization": f"Bearer {VALID}"}, {"image": IMG, "prompt": "x"})
ok = got == 413; fails += not ok
print(f"  [{'PASS' if ok else 'FAIL'}] {'oversized image':34s} -> {got} (want 413)  {payload.get('error','')[:52]}")

# NVIDIA credential failure must not leak to the user
handler.MAX_IMAGE_BYTES = 99999
def nim_401(req, timeout=None):
    if "/auth/v1/user" in req.full_url: return fake_urlopen(req, timeout)
    raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b"invalid api key nvapi-SECRET"))
handler.urllib.request.urlopen = lambda req, timeout=None: _CM(nim_401(req, timeout))
got, payload = call({"Authorization": f"Bearer {VALID}"}, {"image": IMG, "prompt": "x"})
leaked = "nvapi" in json.dumps(payload)
ok = got == 502 and not leaked; fails += not ok
print(f"  [{'PASS' if ok else 'FAIL'}] {'NVIDIA 403 not leaked to client':34s} -> {got} (want 502)  leaked_key={leaked}")

print("\nFAILURES:", fails)
sys.exit(1 if fails else 0)
