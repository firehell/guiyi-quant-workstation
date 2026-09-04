"""Repository-level hygiene contracts for the converged develop baseline."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _tracked_paths(pathspec: str) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "ls-files", pathspec],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line for line in result.stdout.splitlines() if line)


def test_local_browser_capture_directory_is_not_tracked_and_is_ignored() -> None:
    assert _tracked_paths(".playwright-cli/**") == ()

    ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".playwright-cli/probe.json"],
        cwd=ROOT,
        check=False,
    )
    assert ignored.returncode == 0


def test_newow_screenshot_distribution_owner_decision_is_explicit() -> None:
    readme = (
        ROOT / "docs/research/newow-v3.2.82/README.md"
    ).read_text(encoding="utf-8")
    assert "DISTRIBUTION_APPROVED_BY_OWNER" in readme
    assert "不构成法律意见" in readme

    screenshots = _tracked_paths("docs/research/newow-v3.2.82/screenshots/**")
    assert screenshots
    assert all(
        Path(relative).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        for relative in screenshots
    )
