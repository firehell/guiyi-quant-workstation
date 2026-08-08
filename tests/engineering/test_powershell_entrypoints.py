"""Subprocess contracts for PowerShell 7 engineering entrypoints.

Tests that require pwsh are skipped when PowerShell 7 is unavailable so that
non-Windows hosts can still assert script presence and static contracts.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENG = ROOT / "scripts" / "engineering"
PWSH = shutil.which("pwsh")


def _run_pwsh(script: str, args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    assert PWSH is not None
    command = [PWSH, "-NoProfile", "-File", str(ENG / script), *args]
    return subprocess.run(
        command,
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


@pytest.mark.parametrize(
    "name",
    ["preflight.ps1", "validate.ps1", "secret-scan.ps1", "release-tag.ps1"],
)
def test_powershell_entrypoints_exist(name: str) -> None:
    path = ENG / name
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "Invoke-Expression" not in text
    assert "#Requires -Version 7.0" in text


def test_validate_rejects_missing_profile_without_pwsh_contract() -> None:
    text = (ENG / "validate.ps1").read_text(encoding="utf-8")
    assert "ValidateSet('Engineering'" in text or 'ValidateSet("Engineering"' in text
    assert "exit 2" in text


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 (pwsh) is unavailable")
def test_preflight_json_allows_develop() -> None:
    result = _run_pwsh("preflight.ps1", ["-Json"])
    assert result.returncode in {0, 1}
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["tool"] == "scripts/engineering/preflight.ps1"
    assert payload["operation"] == "preflight"
    branch = next(check for check in payload["checks"] if check["name"] == "branch")
    assert branch["status"] in {"passed", "warn"}
    if "develop" in branch["detail"]:
        assert branch["status"] == "passed"


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 (pwsh) is unavailable")
def test_validate_rejects_unknown_profile() -> None:
    result = _run_pwsh("validate.ps1", ["-Profile", "NotAProfile"])
    assert result.returncode == 2


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 (pwsh) is unavailable")
def test_validate_rejects_escaping_test_path(tmp_path: Path) -> None:
    result = _run_pwsh(
        "validate.ps1",
        ["-Profile", "Engineering", "-TestPath", "../outside.py"],
    )
    assert result.returncode == 2


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 (pwsh) is unavailable")
def test_secret_scan_detects_dummy_without_disclosing_value(tmp_path: Path) -> None:
    fixture = tmp_path / "dummy_secret.txt"
    secret_value = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    fixture.write_text(f"token = {secret_value}\n", encoding="utf-8")
    # Copy fixture into repo-contained temp under tests path is awkward; scan absolute path
    # is rejected unless under repo. Write under repo tmp probe instead.
    probe = ROOT / ".engineering_secret_scan_probe.txt"
    try:
        probe.write_text(f"API_KEY = \"{secret_value}\"\n", encoding="utf-8")
        result = _run_pwsh("secret-scan.ps1", ["-Path", probe.name, "-Json"])
        assert result.returncode == 1
        assert secret_value not in result.stdout
        assert secret_value not in result.stderr
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["status"] == "failed"
        assert any("github_pat" in check["detail"] or "secret_assignment" in check["detail"] for check in payload["checks"])
    finally:
        if probe.exists():
            probe.unlink()


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 (pwsh) is unavailable")
def test_secret_scan_rejects_path_escape() -> None:
    result = _run_pwsh("secret-scan.ps1", ["-Path", "..\\..\\Windows\\system.ini"])
    assert result.returncode == 2


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 (pwsh) is unavailable")
def test_release_tag_whatif_does_not_authorize_and_announces_target(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    bare = tmp_path / "remote.git"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "develop"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=repo, check=True)
    subprocess.run(["git", "push", "-u", "origin", "develop"], cwd=repo, check=True, capture_output=True)
    # Create main on remote for FF publishing.
    subprocess.run(["git", "branch", "main"], cwd=repo, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True, capture_output=True)

    script = ENG / "release-tag.ps1"
    # Copy is unnecessary; run with -File from ENG but cwd=repo by invoking pwsh -Command carefully.
    # Use -File with absolute script and set location inside script via git -C from script dir —
    # release-tag discovers root from script location, so run from a copy in the temp repo.
    target_script = repo / "release-tag.ps1"
    target_script.write_text(script.read_text(encoding="utf-8"), encoding="utf-8")
    result = subprocess.run(
        [PWSH, "-NoProfile", "-File", str(target_script),
         "-Operation", "PublishBranch", "-Remote", "origin",
         "-SourceRef", "develop", "-TargetBranch", "main", "-WhatIf", "-Json"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["mode"] == "dry_run"
    assert payload["status"] == "ok"
    assert "scope" in payload
    # Ensure remote still has only the initial commit published via earlier push; WhatIf must not push.
    remote_main = subprocess.run(
        ["git", "--git-dir", str(bare), "rev-parse", "main"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    local_develop = subprocess.run(
        ["git", "rev-parse", "develop"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert remote_main == local_develop


@pytest.mark.skipif(PWSH is None, reason="PowerShell 7 (pwsh) is unavailable")
def test_release_tag_rejects_conflicting_tag(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "develop"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "tag", "-a", "v9.9.9", "-m", "exists"], cwd=repo, check=True)
    target_script = repo / "release-tag.ps1"
    target_script.write_text((ENG / "release-tag.ps1").read_text(encoding="utf-8"), encoding="utf-8")
    result = subprocess.run(
        [PWSH, "-NoProfile", "-File", str(target_script),
         "-Operation", "PublishTag", "-Remote", "origin",
         "-SourceRef", "develop", "-TagName", "v9.9.9", "-Message", "nope", "-WhatIf", "-Json"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["status"] == "blocked"
