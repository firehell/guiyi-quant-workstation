from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ai" / "install_codex_profiles.sh"
PROFILE_DIR = REPO_ROOT / "config" / "codex" / "profiles"
PROFILE_NAMES = [
    "guiyi-fast.config.toml",
    "guiyi-standard.config.toml",
    "guiyi-deep.config.toml",
    "guiyi-critical.config.toml",
]
SENSITIVE_PATTERN = re.compile(
    r"(api[_-]?key|token|password|secret|license|cookie|credential|auth[_-]?token|webhook)",
    re.IGNORECASE,
)


def run_installer(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CODEX_HOME"] = str(tmp_path / "codex-home")
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_dry_run_does_not_write_files(tmp_path: Path) -> None:
    result = run_installer(tmp_path, "--dry-run")

    assert result.returncode == 0
    assert "[DRY-RUN] would install: guiyi-fast.config.toml" in result.stdout
    assert not (tmp_path / "codex-home").exists()


def test_temporary_codex_home_install_succeeds(tmp_path: Path) -> None:
    result = run_installer(tmp_path)

    assert result.returncode == 0
    for name in PROFILE_NAMES:
        installed = tmp_path / "codex-home" / name
        assert installed.read_text(encoding="utf-8") == (PROFILE_DIR / name).read_text(
            encoding="utf-8"
        )


def test_default_install_refuses_to_overwrite(tmp_path: Path) -> None:
    first = run_installer(tmp_path)
    second = run_installer(tmp_path)

    assert first.returncode == 0
    assert second.returncode == 5
    assert "exists, refusing to overwrite: guiyi-fast.config.toml" in second.stderr


def test_backup_and_install_backs_up_existing_files(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    existing = codex_home / "guiyi-fast.config.toml"
    existing.write_text('model = "old-model"\n', encoding="utf-8")

    result = run_installer(tmp_path, "--backup-and-install")

    assert result.returncode == 0
    backups = list(codex_home.glob("guiyi-fast.config.toml.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == 'model = "old-model"\n'
    assert existing.read_text(encoding="utf-8") == (
        PROFILE_DIR / "guiyi-fast.config.toml"
    ).read_text(encoding="utf-8")


def test_verify_checks_installed_files(tmp_path: Path) -> None:
    install = run_installer(tmp_path)
    verify = run_installer(tmp_path, "--verify")

    assert install.returncode == 0
    assert verify.returncode == 0
    assert "[OK] verified: guiyi-critical.config.toml" in verify.stdout


def test_verify_fails_when_profile_is_missing(tmp_path: Path) -> None:
    verify = run_installer(tmp_path, "--verify")

    assert verify.returncode != 0
    assert "[FAIL] not installed: guiyi-fast.config.toml" in verify.stdout


def test_profiles_and_installer_do_not_contain_secret_fields() -> None:
    checked_files = [SCRIPT, *PROFILE_DIR.glob("*.config.toml")]

    assert {path.name for path in checked_files if path.suffix == ".toml"} == set(PROFILE_NAMES)
    for path in checked_files:
        text = path.read_text(encoding="utf-8")
        assert SENSITIVE_PATTERN.search(text) is None, path
