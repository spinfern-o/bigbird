"""The app's "memory": small bits of state that outlive a single edit.

Recent files, the last folder you browsed, window size and position. Not your
photos or projects — those are saved explicitly through File > Save.

There are two backends, and which one you get depends on how you started the
app (see ``app/login_window.py``):

  * :class:`PersistentStore` — signed in. State is written to
    ``~/.photoforge/state.json`` and is there next time you open PhotoForge.
  * :class:`EphemeralStore` — "Continue as guest". State lives in memory only
    and disappears when the app closes; nothing touches the disk.

If a guest signs in mid-session, :func:`promote` copies everything the guest
did into the persistent store, so signing in never loses your place.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

APP_DIR = Path.home() / ".photoforge"
_STATE_PATH = APP_DIR / "state.json"

# Keys the app currently remembers. Add new ones here so there's one list to
# read; the stores themselves don't care what you put in them.
RECENT_FILES = "recent_files"
LAST_FOLDER = "last_folder"
WINDOW_GEOMETRY = "window_geometry"

MAX_RECENT = 10


def ensure_app_dir() -> Path:
    """Create ``~/.photoforge`` owned by this user only (0700)."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(APP_DIR, 0o700)
    except OSError:
        pass
    return APP_DIR


def secure_write_json(path: Path, data) -> None:
    """Write JSON so the file is never briefly world-readable.

    ``Path.write_text`` creates the file using the process umask (commonly
    0644) and only then can you chmod it. For anything holding tokens that
    window is long enough to matter, so create the file 0600 from the start
    and swap it into place atomically.
    """
    ensure_app_dir()
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class StateStore:
    """Common behaviour for both backends."""

    def __init__(self, data: dict | None = None):
        self._data: dict = dict(data or {})

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value) -> None:
        self._data[key] = value
        self.flush()

    def as_dict(self) -> dict:
        return dict(self._data)

    def flush(self) -> None:
        """Persist if this backend persists. The base store does not."""

    # ------------------------------------------------------------- recents
    def add_recent_file(self, path) -> None:
        path = str(path)
        recents = [p for p in self.get(RECENT_FILES, []) if p != path]
        recents.insert(0, path)
        self.set(RECENT_FILES, recents[:MAX_RECENT])


class EphemeralStore(StateStore):
    """Guest mode. Remembers things for this session, writes nothing to disk."""

    is_persistent = False


class PersistentStore(StateStore):
    """Signed in. Backed by ``~/.photoforge/state.json``."""

    is_persistent = True

    def __init__(self):
        super().__init__(self._load())

    @staticmethod
    def _load() -> dict:
        try:
            if _STATE_PATH.exists():
                data = json.loads(_STATE_PATH.read_text())
                if isinstance(data, dict):
                    return data
        except (OSError, ValueError):
            pass
        return {}

    def flush(self) -> None:
        try:
            secure_write_json(_STATE_PATH, self._data)
        except OSError:
            # Losing "recent files" must never take the app down with it.
            pass


def promote(guest: StateStore) -> PersistentStore:
    """Carry a guest session's state into the signed-in store.

    Called when someone picks "Continue as guest", does some work, then signs
    in. Anything they did as a guest is merged in; existing saved state wins
    only where the guest set nothing.
    """
    store = PersistentStore()
    merged = store.as_dict()
    merged.update(guest.as_dict())
    store._data = merged
    store.flush()
    return store
