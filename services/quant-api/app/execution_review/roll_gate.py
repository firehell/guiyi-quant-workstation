"""Fail-closed reader for the independent Execution Review roll Gate."""

from __future__ import annotations

import os
from pathlib import Path
import stat

from app.core.env import PROJECT_ROOT


def execution_review_roll_marker_state(
    project_root: Path = PROJECT_ROOT,
) -> str:
    """Return enabled only for the exact private regular-file marker."""
    marker_parent = project_root / ".run"
    marker_name = "execution-review-roll-enabled"
    parent_descriptor: int | None = None
    try:
        parent_descriptor = os.open(
            marker_parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        _validate_parent(os.fstat(parent_descriptor))
        initial = os.stat(
            marker_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        _validate_marker(initial)
        descriptor = os.open(
            marker_name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_descriptor,
        )
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            _validate_marker(opened)
            if (initial.st_dev, initial.st_ino) != (opened.st_dev, opened.st_ino):
                return "invalid"
            return "enabled" if stream.read() == b"enabled\n" else "invalid"
    except FileNotFoundError:
        return "disabled"
    except (OSError, ValueError):
        return "invalid"
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def _validate_parent(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError


def _validate_marker(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError
