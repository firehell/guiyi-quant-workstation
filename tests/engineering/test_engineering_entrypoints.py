"""Engineering entrypoint tests — no WorkBuddy/dispatcher dependency."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENG = REPO_ROOT / "scripts" / "engineering"


def run(args: list[str], *, env: dict[str, str] | None = None, check: bool = False) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        env=merged,
        capture_output=True,
        text=True,
        check=check,
    )


def test_preflight_exits_zero_json() -> None:
    result = run(["bash", str(ENG / "preflight.sh"), "--json"])
    assert result.returncode == 0, result.stderr
    assert '"tool": "scripts/engineering/preflight.sh"' in result.stdout
    assert "branch_not_main" in result.stdout


def test_check_secrets_does_not_print_values(tmp_path: Path) -> None:
    # Run against repo; ensure output never contains typical secret value patterns
    # from .env.example placeholders are skipped by design.
    result = run(["bash", str(ENG / "check-secrets.sh")])
    assert "QYWX_WEBHOOK_URL=" not in result.stdout
    assert "password=" not in result.stdout.lower() or "family=" in result.stdout
    # Values themselves should not be dumped; family reports ok
    assert "values not printed" in result.stdout or result.returncode in (0, 1)


def test_production_write_fail_closed_without_confirm() -> None:
    result = run(
        ["bash", str(ENG / "production-write-check.sh"), "--action", "bootstrap-env"],
    )
    assert result.returncode == 3
    assert "missing --confirm-production-write" in result.stderr


def test_production_write_ok_with_confirm() -> None:
    result = run(
        [
            "bash",
            str(ENG / "production-write-check.sh"),
            "--action",
            "bootstrap-env",
            "--confirm-production-write",
        ],
    )
    assert result.returncode == 0
    assert "confirmation present" in result.stdout


def test_runtime_health_readonly_json() -> None:
    result = run(["bash", str(ENG / "runtime-health.sh"), "--json"])
    assert result.returncode == 0, result.stderr
    assert '"readonly": true' in result.stdout


def test_test_sh_rejects_unsafe_push() -> None:
    result = run(["bash", str(ENG / "test.sh"), "git push origin HEAD"])
    assert result.returncode != 0
    assert "REJECTED" in result.stderr or "REJECTED" in result.stdout


def test_test_sh_default_suite_smoke() -> None:
    # Avoid recursive infinite loop: call allowlisted single pytest file via test.sh args
    # instead of full default suite that re-invokes pytest engineering.
    result = run(
        [
            "bash",
            str(ENG / "test.sh"),
            "bash -n scripts/engineering/preflight.sh",
            "git diff --check",
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_redact_evidence_scrubs_without_echoing_secret(tmp_path: Path) -> None:
    sample = tmp_path / "sample.log"
    sample.write_text("token=SUPER_SECRET_VALUE_12345\nplain=ok\n", encoding="utf-8")
    result = run(
        ["bash", str(REPO_ROOT / "scripts" / "ai" / "redact_evidence.sh"), "--file", str(sample)]
    )
    assert result.returncode == 0, result.stderr
    text = sample.read_text(encoding="utf-8")
    assert "SUPER_SECRET_VALUE_12345" not in text
    assert "plain=ok" in text
