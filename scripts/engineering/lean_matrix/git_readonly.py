"""The single fixed, local, read-only Git observation permitted by AI-TEAM-004."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from .errors import LeanMatrixError


BASE_REF = "origin/develop"
BASE_REVISION = "origin/develop^{commit}"
GIT_COMMAND = (
    "git", "-c", "core.fsmonitor=false", "rev-parse", "--verify", BASE_REVISION,
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
Runner = Callable[..., subprocess.CompletedProcess[str]]


def resolve_base_sha(repo_root: Path, *, runner: Runner = subprocess.run) -> str:
    """Resolve only local ``origin/develop`` without fetch, fallback, or Git writes."""
    environment = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")
        if key in os.environ
    }
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        result = runner(
            list(GIT_COMMAND),
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            env=environment,
        )
    except OSError as exc:
        raise LeanMatrixError("git_unavailable", "git executable is unavailable") from exc
    if result.returncode != 0:
        raise LeanMatrixError("base_ref_unavailable", f"local {BASE_REF} commit is unavailable")
    lines = result.stdout.splitlines()
    if len(lines) != 1 or not SHA_RE.fullmatch(lines[0]):
        raise LeanMatrixError("invalid_base_sha", f"local {BASE_REF} did not resolve to one 40-hex commit")
    return lines[0]
