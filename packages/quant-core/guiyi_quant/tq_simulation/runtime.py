"""Single-owner runtime files. Config/status contain no authentication secrets."""

from contextlib import contextmanager
from pathlib import Path
import os
import json
import fcntl
import stat
import tempfile


def directory():
    return Path.home() / "Library/Application Support/GuiyiQuant/tqkq-simulation"


def private_folder(path):
    path = Path(path)
    if path.exists():
        if (
            path.is_symlink()
            or not path.is_dir()
            or path.stat().st_uid != os.getuid()
            or stat.S_IMODE(path.stat().st_mode) != 0o700
        ):
            raise ValueError("TQ_PRIVATE_DIRECTORY_REQUIRED")
    else:
        path.mkdir(mode=0o700)
    return path


def write_private(path, payload):
    path = Path(path)
    if path.parent.resolve(strict=True) != path.parent or path.is_symlink():
        raise ValueError("TQ_PRIVATE_PATH_REQUIRED")
    if path.exists() and (
        not path.is_file()
        or path.stat().st_uid != os.getuid()
        or path.stat().st_mode & 0o077
    ):
        raise ValueError("TQ_PRIVATE_PATH_REQUIRED")
    raw = json.dumps(payload, sort_keys=True, allow_nan=False).encode()
    fd, name = tempfile.mkstemp(prefix=".tq-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        d = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(d)
        finally:
            os.close(d)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_private(path, *, limit=32 * 1024 * 1024):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_mode & 0o077
            or before.st_nlink != 1
            or before.st_size > limit
        ):
            raise ValueError("TQ_PRIVATE_FILE_REQUIRED")
        raw = b""
        while len(raw) <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - len(raw)))
            if not chunk:
                break
            raw += chunk
        after = os.fstat(fd)
        named = path.lstat()
        if (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_mtime_ns,
            after.st_size,
        ) or (named.st_dev, named.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("TQ_PRIVATE_FILE_DRIFT")
        return json.loads(raw)
    finally:
        os.close(fd)


@contextmanager
def owner_lock(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        s = os.fstat(fd)
        if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
            raise ValueError("TQ_OWNER_LOCK_INVALID")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)
