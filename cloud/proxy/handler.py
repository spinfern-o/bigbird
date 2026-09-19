"""Cloud AI proxy for PhotoForge (roadmap A6).

Why this exists
---------------
The NVIDIA API key must never ship inside the desktop app. A key bundled with
PyInstaller is readable with ``strings``; once extracted it can be spent by
anyone and cannot be revoked without shipping an update to every user. So the
desktop app never sees the key. It calls *this* endpoint with the Supabase
access token it already has from signing in (``app/auth.py``), and the key
stays in AWS Secrets Manager where only this function can read it.

Request flow
------------
  desktop app  --(Bearer <supabase access_token>)-->  API Gateway
                                                          |
                                                       Lambda (this)
                                          1. verify the token with Supabase
                                          2. check today's quota in DynamoDB
                                          3. read the NVIDIA key from Secrets Manager
                                          4. call NVIDIA NIM
                                                          |
                                                    edited image back

Anonymous callers are rejected outright, so "Continue as guest" users cannot
spend your NVIDIA credits.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

import boto3

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SECRET_ARN = os.environ["NVIDIA_SECRET_ARN"]
QUOTA_TABLE = os.environ.get("QUOTA_TABLE", "")
DAILY_QUOTA = int(os.environ.get("DAILY_QUOTA", "25"))

# Full NIM URL, e.g. https://ai.api.nvidia.com/v1/genai/<vendor>/<model>.
# Kept in config rather than hardcoded because NIM model paths change; confirm
# the current one on build.nvidia.com for the model you deploy.
NIM_ENDPOINT = os.environ["NIM_ENDPOINT"]
NIM_TIMEOUT = int(os.environ.get("NIM_TIMEOUT", "120"))

# Reject oversized uploads before spending a NIM call on them.
MAX_IMAGE_BYTES = int(os.environ.get("MAX_IMAGE_BYTES", str(12 * 1024 * 1024)))

_secrets = boto3.client("secretsmanager")
_dynamo = boto3.resource("dynamodb") if QUOTA_TABLE else None

# Cached across warm invocations so a burst of edits doesn't re-fetch the
# secret every time. Lambda recycles the sandbox periodically, which is what
# picks up a rotated key.
_cached_key: str | None = None


_KEY_PATTERN = re.compile(r"nvapi-[A-Za-z0-9_\-]+")


def _scrub(text: str) -> str:
    """Strip anything key-shaped before it reaches CloudWatch.

    NVIDIA's auth errors quote the offending key back at you, so logging the
    raw response body would copy the key into log storage -- a place with
    different access controls than Secrets Manager, and one people grep freely.
    """
    return _KEY_PATTERN.sub("nvapi-<redacted>", text)


class ProxyError(Exception):
    """An error with an HTTP status we're happy to show the user."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# --------------------------------------------------------------------- auth
def verify_user(auth_header: str | None) -> str:
    """Return the Supabase user id for a valid token, else raise.

    Asks Supabase directly rather than verifying a JWT signature locally. That
    costs one fast round-trip but means this function needs no JWT secret of
    its own — one less credential to store and rotate — and it honours tokens
    revoked server-side, which local signature checks cannot.
    """
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise ProxyError(401, "Sign in to PhotoForge to use cloud AI features.")
    token = auth_header.split(" ", 1)[1].strip()

    req = urllib.request.Request(
        f"{SUPABASE_URL}/auth/v1/user",
        headers={"Authorization": f"Bearer {token}", "apikey": token},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            user = json.loads(resp.read())
    except urllib.error.HTTPError:
        raise ProxyError(401, "Your sign-in has expired. Please sign in again.")
    except urllib.error.URLError:
        raise ProxyError(503, "Could not verify your account right now. Try again shortly.")

    user_id = user.get("id")
    if not user_id:
        raise ProxyError(401, "Your sign-in has expired. Please sign in again.")
    return user_id


# -------------------------------------------------------------------- quota
def check_quota(user_id: str) -> None:
    """Count one cloud edit against today's allowance for this user.

    A leaked key is one failure mode; a signed-in user looping a script is
    another, and only this guards against the second. Skipped when no table is
    configured so the stack can run without DynamoDB during development.
    """
    if _dynamo is None:
        return
    table = _dynamo.Table(QUOTA_TABLE)
    day = time.strftime("%Y-%m-%d", time.gmtime())
    try:
        result = table.update_item(
            Key={"user_id": user_id, "day": day},
            UpdateExpression="ADD #c :one SET #e = if_not_exists(#e, :exp)",
            ExpressionAttributeNames={"#c": "count", "#e": "expires_at"},
            ExpressionAttributeValues={":one": 1, ":exp": int(time.time()) + 7 * 86400},
            ReturnValues="UPDATED_NEW",
        )
    except Exception:
        # Never let the quota bookkeeping break an otherwise valid request.
        return
    if int(result["Attributes"]["count"]) > DAILY_QUOTA:
        raise ProxyError(
            429,
            f"You've used all {DAILY_QUOTA} cloud edits for today. "
            "Local AI features still work, and your allowance resets tomorrow.",
        )


# ------------------------------------------------------------------ secrets
def nvidia_key() -> str:
    global _cached_key
    if _cached_key is None:
        raw = _secrets.get_secret_value(SecretId=SECRET_ARN)["SecretString"]
        try:
            _cached_key = json.loads(raw)["api_key"]
        except (ValueError, KeyError):
            _cached_key = raw.strip()  # plain-string secret
    return _cached_key


# ---------------------------------------------------------------------- NIM
def call_nim(payload: dict) -> dict:
    req = urllib.request.Request(
        NIM_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {nvidia_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=NIM_TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = _scrub(e.read().decode("utf-8", "replace")[:400])
        if e.code in (401, 403):
            # Our key, not the user's problem -- don't leak the reason to them.
            print(f"NVIDIA rejected our credentials: {e.code} {body}")
            raise ProxyError(502, "Cloud AI is unavailable right now. Please try again later.")
        if e.code == 429:
            raise ProxyError(429, "Cloud AI is busy right now. Please try again in a moment.")
        print(f"NVIDIA error {e.code}: {body}")
        raise ProxyError(502, "The cloud AI service could not complete that edit.")
    except urllib.error.URLError:
        raise ProxyError(504, "The cloud AI service timed out. Please try again.")


# ------------------------------------------------------------------ handler
def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    try:
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        user_id = verify_user(headers.get("authorization"))

        raw_body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            raw_body = base64.b64decode(raw_body).decode()
        body = json.loads(raw_body)

        image_b64 = body.get("image")
        if not image_b64:
            raise ProxyError(400, "No image was sent.")
        if len(image_b64) > MAX_IMAGE_BYTES:
            raise ProxyError(413, "That photo is too large for cloud editing.")
        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            raise ProxyError(400, "Describe the edit you want.")

        check_quota(user_id)

        result = call_nim({
            "prompt": prompt,
            "image": image_b64,
            # Optional selection mask: only this area gets regenerated (A6).
            **({"mask": body["mask"]} if body.get("mask") else {}),
        })
        return _response(200, {"result": result})

    except ProxyError as e:
        return _response(e.status, {"error": e.message})
    except Exception as e:  # noqa: BLE001 - never surface a stack trace
        print(f"Unhandled proxy error: {type(e).__name__}: {e}")
        return _response(500, {"error": "Something went wrong. Please try again."})
