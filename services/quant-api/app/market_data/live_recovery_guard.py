"""Local serialization of recovery, Alert Event/send and after-market maintenance.

Kernel-owned locks have no time lease that can expire during a database commit.
Files are bounded by product plus one after-market lock and are never unlinked.
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
def recovery_guard(symbol: str, *, root: Path | None = None, wait: bool = False, legacy_root: bool = False) -> Iterator[None]:
    if re.fullmatch(r"[a-z]{1,2}", symbol) is None:
        raise ValueError("LIVE_RECOVERY_GUARD_UNSAFE")
    with _file_guard(f"{symbol}.lock", root=root, wait=wait, legacy_root=legacy_root):
        yield


@contextmanager
def after_market_recovery_guard(*, root: Path | None = None, wait: bool = False, legacy_root: bool = False) -> Iterator[None]:
    """Captured recovery takes this before its symbol guard; after-market holds it for the job."""
    with _file_guard("after-market.lock", root=root, wait=wait, legacy_root=legacy_root):
        yield


def guard_directory(*, root: Path | None = None, legacy_root: bool = False) -> Path:
    """Shared across service releases; only topology bootstrap probes old inodes."""
    if legacy_root:
        if root is None:
            raise ValueError('LIVE_RECOVERY_GUARD_UNSAFE')
        return root
    from app.runtime_bindings import read_bindings
    from app.runtime_handover import runtime_directory
    if os.environ.get('GUIYI_RUNTIME_HANDOVER_ENABLED') == '1' or read_bindings() is not None:
        return runtime_directory() / 'live-recovery-guards'
    return root if root is not None else PROJECT_ROOT / '.run' / 'live-recovery-guards'


@contextmanager
def _file_guard(name: str, *, root: Path | None, wait: bool, legacy_root: bool = False) -> Iterator[None]:
    directory = guard_directory(root=root, legacy_root=legacy_root)
    if root is None or directory != root:
        parent = directory.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("LIVE_RECOVERY_GUARD_UNSAFE")
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError("LIVE_RECOVERY_GUARD_UNSAFE")
    try:
        fd = os.open(directory / name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise ValueError("LIVE_RECOVERY_GUARD_UNSAFE") from None
    acquired = False
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError("LIVE_RECOVERY_GUARD_UNSAFE")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            raise RuntimeError("LIVE_RECOVERY_BUSY") from None
        acquired = True
        yield
    finally:
        try:
            if acquired:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            # Do not retry close: an error may follow actual closure/FD reuse.
            os.close(fd)
