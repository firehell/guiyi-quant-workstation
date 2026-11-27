"""Bounded reads of explicitly registered local research results."""
import os
import stat
from pathlib import Path

MAX_BYTES = 128 * 1024 * 1024


class ResultFileError(ValueError):
    """A research result file is unavailable or unsafe."""


def safe_result_root(root: Path) -> Path:
    root = Path(root)
    if not root.is_absolute():
        raise ResultFileError("RESULT_ROOT_UNSAFE")
    # Inspect each component without resolving it: resolve() would conceal a link.
    for component in reversed((root, *root.parents)):
        try:
            mode = component.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ResultFileError("RESULT_ROOT_UNSAFE") from exc
        if not stat.S_ISDIR(mode):
            raise ResultFileError("RESULT_ROOT_UNSAFE")
    return root


def read_result_file(path: Path) -> bytes:
    if path.is_symlink():
        raise ResultFileError("RESULT_PATH_UNSAFE")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    except (OSError, ValueError) as exc:
        raise ResultFileError("RESULT_UNAVAILABLE") from exc
    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ResultFileError("RESULT_PATH_UNSAFE")
        if file_stat.st_size > MAX_BYTES:
            raise ResultFileError("RESULT_TOO_LARGE")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            return stream.read(MAX_BYTES + 1)
    finally:
        os.close(fd)
