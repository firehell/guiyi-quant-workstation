"""Behavioral tests for the repository-local secret scanner."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SCANNER = ROOT / "scripts" / "engineering" / "secret_scan.py"


def test_default_scan_reports_location_without_secret_value(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    secret = "ghp_" + "A" * 24
    (repo / "probe.txt").write_text(f"token={secret}\n", encoding="utf-8")
    subprocess.run(["git", "add", "probe.txt"], cwd=repo, check=True)

    result = _run(repo, "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["findings"] == [
        {"path": "probe.txt", "line": 1, "family": "github_pat"}
    ]
    assert secret not in result.stdout
    assert secret not in result.stderr


def test_explicit_path_warn_only_scans_untracked_file(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    secret = "github_pat_" + "B" * 24
    (repo / "untracked.txt").write_text(secret, encoding="utf-8")

    result = _run(repo, "untracked.txt", "--warn-only", "--json")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "warning"
    assert payload["findings"][0]["family"] == "github_fine_grained"
    assert secret not in result.stdout


def test_generated_api_documentation_cache_is_not_scanned(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    cached = repo / ".agents/skills/example/cache/api_docs/reference.md"
    cached.parent.mkdir(parents=True)
    cached.write_text(
        'client(password="' + "cached-document-value-12345" + '")\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)

    result = _run(repo, "--json")

    assert result.returncode == 0
    assert json.loads(result.stdout)["findings"] == []


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)

    result = _run(repo, "../outside.txt", "--json")

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "invalid"
    assert "outside.txt" not in result.stdout


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


def _run(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    assert SCANNER.exists(), "secret_scan.py must be the single engineering entrypoint"
    return subprocess.run(
        [sys.executable, str(SCANNER), *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
