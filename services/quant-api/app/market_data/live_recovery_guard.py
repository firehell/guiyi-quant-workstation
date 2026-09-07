"""Local single-workstation serialization of recovery and Alert Event/send.

Kernel-owned locks have no time lease that can expire during a database commit.
Files are bounded by product and never unlinked while processes may hold them.
"""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
import fcntl
import os
from pathlib import Path
import re
import stat

from app.core.env import PROJECT_ROOT


@contextmanager
def recovery_guard(symbol: str, *, root: Path | None = None, wait: bool = False) -> Iterator[None]:
    if re.fullmatch(r"[a-z]{1,2}", symbol) is None:
        raise ValueError("LIVE_RECOVERY_GUARD_UNSAFE")
    directory = root if root is not None else PROJECT_ROOT / ".run" / "live-recovery-guards"
    if root is None:
        parent = directory.parent
        parent.mkdir(mode=0o700, exist_ok=True)
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("LIVE_RECOVERY_GUARD_UNSAFE")
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError("LIVE_RECOVERY_GUARD_UNSAFE")
    try:
        fd = os.open(directory / f"{symbol}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise ValueError("LIVE_RECOVERY_GUARD_UNSAFE") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError("LIVE_RECOVERY_GUARD_UNSAFE")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            raise RuntimeError("LIVE_RECOVERY_BUSY") from None
        yield
    finally:
        os.close(fd)
