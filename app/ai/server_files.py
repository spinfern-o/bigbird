"""Which files make up the PhotoForge GPU server, and a version fingerprint of them.

The desktop app copies exactly these files to the GPU machine, and the server reports the
same fingerprint in /health, so the app can tell when the GPU needs updating.
(No Qt imports: the server imports this too.)
"""
import hashlib
import os

FILES = (
    "app/__init__.py",
    "app/ai/__init__.py",
    "app/ai/models.py",
    "app/ai/tasks.py",
    "app/ai/server_files.py",
    "server/__init__.py",
    "server/photoforge_server.py",
    "server/requirements.txt",
    "server/setup.sh",
    "server/install_service.sh",
    "server/start.sh",
)


def root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def read(rel, base=None):
    """File contents with Windows line endings normalized (scripts must be LF on Linux)."""
    with open(os.path.join(base or root(), *rel.split("/")), "rb") as f:
        return f.read().replace(b"\r\n", b"\n")


def version(base=None):
    h = hashlib.sha256()
    for rel in FILES:
        h.update(rel.encode() + b"\0" + read(rel, base) + b"\0")
    return h.hexdigest()[:16]
