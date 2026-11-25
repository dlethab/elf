"""File storage for uploaded media. Files are stored under random keys OUTSIDE any web-served
folder and are never executed or served directly: every download goes through the access-checking
/media route. Local disk is used now; an S3-compatible backend can implement the same three methods."""
import os
import re
import secrets
from pathlib import Path

_KEY = re.compile(r"^[A-Za-z0-9_-]{24,64}$")


def new_key():
    return secrets.token_urlsafe(24)          # 32 URL-safe characters; unguessable


class LocalStorage:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def _path(self, key):
        if not _KEY.match(key or ""):
            raise ValueError("invalid storage key")
        return self.root / key[:2] / key

    def put(self, key, data):
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        os.replace(tmp, path)                  # atomic: a half-written file is never visible

    def put_stream(self, key, stream):
        """Copy a file-like object to storage in chunks (large audio and video never sit in memory)."""
        import shutil
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        stream.seek(0)
        with open(tmp, "wb") as f:
            shutil.copyfileobj(stream, f, 1024 * 1024)
        os.replace(tmp, path)

    def path(self, key):
        """Filesystem path of a stored file (local storage only), for streaming with range requests."""
        return self._path(key)

    def get(self, key):
        return self._path(key).read_bytes()

    def exists(self, key):
        return self._path(key).exists()

    def delete(self, key):
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            pass


def from_config(config):
    return LocalStorage(config["MEDIA_ROOT"])
