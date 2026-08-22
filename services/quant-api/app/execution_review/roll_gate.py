"""Fail-closed reader for the independent Execution Review roll Gate."""

from __future__ import annotations

from pathlib import Path
import stat

from app.core.env import PROJECT_ROOT


def execution_review_roll_marker_state(
    project_root: Path = PROJECT_ROOT,
) -> str:
    """Return enabled only for the exact private regular-file marker."""
    marker = project_root / ".run/execution-review-roll-enabled"
    try:
        metadata = marker.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            return "invalid"
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            return "invalid"
        return "enabled" if marker.read_bytes() == b"enabled\n" else "invalid"
    except FileNotFoundError:
        return "disabled"
    except OSError:
        return "invalid"
