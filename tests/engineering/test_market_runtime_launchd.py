"""Launchd packaging contracts for the local Market Runtime activation marker."""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_install_modes_only_confirm_market_runtime_persists_activation_marker(tmp_path: Path) -> None:
    """Render/base install stay disabled; explicit market activation creates the fixed marker."""
    repo = _copy_launchd_fixture(tmp_path / "repo")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_launchctl = fake_bin / "launchctl"
    fake_launchctl.write_text(
        "#!/bin/sh\n"
        "case \"${1:-}\" in\n"
        "  bootstrap|enable|kickstart) exit 0 ;;\n"
        "  print|bootout) exit 1 ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_launchctl.chmod(0o755)
    marker = repo / ".run" / "market-runtime-enabled"

    _run_installer(repo, home, fake_bin, "--render-only")
    assert not marker.exists()

    _run_installer(repo, home, fake_bin, "--confirm-load")
    assert not marker.exists()

    _run_installer(repo, home, fake_bin, "--confirm-market-runtime")
    assert marker.read_text(encoding="utf-8") == "enabled\n"


def _copy_launchd_fixture(destination: Path) -> Path:
    """Copy only installer inputs so mode tests cannot affect the real workstation."""
    for relative in (
        "deploy/launchd",
        "scripts/ops/macos/install-local-services.sh",
        "scripts/ops/macos/run-local-service.sh",
        "scripts/ops/macos/rotate-local-service-logs.sh",
    ):
        source = REPO_ROOT / relative
        target = destination / relative
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return destination


def _run_installer(repo: Path, home: Path, fake_bin: Path, mode: str) -> None:
    environment = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
    }
    result = subprocess.run(
        [str(repo / "scripts/ops/macos/install-local-services.sh"), mode],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
