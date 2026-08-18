from __future__ import annotations

from pathlib import Path
import os
import plistlib
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_roll_confirmation_writes_only_exact_private_marker(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path / "repo")
    home, fake_bin, calls = _fake_runtime(tmp_path)

    result = _run_installer(
        repo,
        home,
        fake_bin,
        "--confirm-execution-review-roll",
    )

    marker = repo / ".run/execution-review-roll-enabled"
    assert result.returncode == 0, result.stderr
    assert marker.read_bytes() == b"enabled\n"
    assert marker.stat().st_mode & 0o777 == 0o600
    assert "execution_review_roll=enabled" in result.stdout
    assert not (repo / ".run/launchd").exists()
    assert not calls.exists()
    assert not (repo / ".run/market-runtime-enabled").exists()
    assert not (repo / ".run/alert-runtime-enabled").exists()


@pytest.mark.parametrize(
    "mode",
    (
        "--render-only",
        "--confirm-load",
        "--confirm-market-runtime",
        "--confirm-alert-runtime",
    ),
)
def test_other_install_modes_never_create_roll_marker(
    tmp_path: Path,
    mode: str,
) -> None:
    repo = _copy_fixture(tmp_path / mode.removeprefix("--"))
    home, fake_bin, _calls = _fake_runtime(tmp_path / f"runtime-{mode.removeprefix('--')}")

    if mode == "--confirm-alert-runtime":
        prerequisite = _run_installer(repo, home, fake_bin, "--confirm-load")
        assert prerequisite.returncode == 0, prerequisite.stderr

    result = _run_installer(repo, home, fake_bin, mode)

    assert result.returncode == 0, result.stderr
    assert not (repo / ".run/execution-review-roll-enabled").exists()


def test_status_missing_roll_marker_is_disabled_without_failure(tmp_path: Path) -> None:
    repo, home, fake_bin = _status_fixture(tmp_path / "missing")

    result = _run_status(repo, home, fake_bin)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "execution_review_roll=disabled" in result.stdout
    assert "overall=passed" in result.stdout


def test_status_accepts_only_exact_enabled_marker_with_mode_0600(
    tmp_path: Path,
) -> None:
    repo, home, fake_bin = _status_fixture(tmp_path / "enabled")
    marker = repo / ".run/execution-review-roll-enabled"
    marker.write_bytes(b"enabled\n")
    marker.chmod(0o600)

    result = _run_status(repo, home, fake_bin)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "execution_review_roll=enabled" in result.stdout
    assert "overall=passed" in result.stdout


@pytest.mark.parametrize("invalid", ("content", "permission", "type"))
def test_status_invalid_roll_marker_records_overall_failure(
    tmp_path: Path,
    invalid: str,
) -> None:
    repo, home, fake_bin = _status_fixture(tmp_path / invalid)
    marker = repo / ".run/execution-review-roll-enabled"
    if invalid == "type":
        marker.mkdir()
    else:
        marker.write_bytes(b"invalid\n" if invalid == "content" else b"enabled\n")
        marker.chmod(0o600 if invalid == "content" else 0o644)

    result = _run_status(repo, home, fake_bin)

    assert result.returncode == 1
    assert "execution_review_roll=invalid" in result.stdout
    assert "overall=failed" in result.stdout


def _copy_fixture(destination: Path) -> Path:
    for relative in (
        "deploy/launchd",
        "scripts/ops/macos/install-local-services.sh",
        "scripts/ops/macos/local-services-status.sh",
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


def _fake_runtime(root: Path) -> tuple[Path, Path, Path]:
    home = root / "home"
    fake_bin = root / "bin"
    fake_bin.mkdir(parents=True)
    calls = home / "launchctl-calls.log"
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$HOME/launchctl-calls.log"\n'
        'case "${1:-}" in bootstrap|enable|kickstart) exit 0 ;; print|bootout) exit 1 ;; *) exit 2 ;; esac\n',
        encoding="utf-8",
    )
    launchctl.chmod(0o755)
    git = fake_bin / "git"
    git.write_text(
        "#!/bin/sh\n"
        'if [ "${1:-}" = "-C" ] && [ "${3:-}" = "rev-parse" ] && [ "${4:-}" = "HEAD" ]; then\n'
        "  printf '1111111111111111111111111111111111111111\\n'\n"
        "  exit 0\n"
        "fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    return home, fake_bin, calls


def _run_installer(
    repo: Path,
    home: Path,
    fake_bin: Path,
    mode: str,
) -> subprocess.CompletedProcess[str]:
    clawbot_paths = _clawbot_paths(repo.parent / "clawbot-fixture")
    return subprocess.run(
        [str(repo / "scripts/ops/macos/install-local-services.sh"), mode],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
            "GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD": "1",
            **clawbot_paths,
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _clawbot_paths(root: Path) -> dict[str, str]:
    plugin = root / "plugin"
    state = root / "state"
    owner_parent = root / "owner"
    for directory in (plugin, state, owner_parent):
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        directory.chmod(0o700)
    openclaw = root / "openclaw"
    node = root / "node"
    for executable in (openclaw, node):
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o700)
    config = state / "openclaw.json"
    config.write_text("{}\n", encoding="utf-8")
    owner = owner_parent / "owner.json"
    owner.write_text("{}\n", encoding="utf-8")
    owner.chmod(0o600)
    return {
        "GUIYI_OPENCLAW_BIN": str(openclaw),
        "GUIYI_OPENCLAW_NODE_BIN": str(node),
        "GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT": str(plugin),
        "GUIYI_OPENCLAW_STATE_DIR": str(state),
        "GUIYI_OPENCLAW_CONFIG_PATH": str(config),
        "GUIYI_ALERT_CLAWBOT_OWNER_PATH": str(owner),
    }


def _status_fixture(root: Path) -> tuple[Path, Path, Path]:
    repo = _copy_fixture(root / "runtime")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / ".gitignore").write_text(".run/\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "checkout", "--detach", "-q"], cwd=repo, check=True)
    (repo / ".run").mkdir()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    home = root / "home"
    agent_dir = home / "Library/LaunchAgents"
    agent_dir.mkdir(parents=True)
    for label in (
        "com.guiyi.quant-api",
        "com.guiyi.quant-web",
        "com.guiyi.quant-live",
        "com.guiyi.quant-after-market",
        "com.guiyi.quant-alert",
    ):
        with (agent_dir / f"{label}.plist").open("wb") as handle:
            plistlib.dump(
                {
                    "Label": label,
                    "EnvironmentVariables": {
                        "GUIYI_PROJECT_ROOT": str(repo.resolve()),
                        "GUIYI_RUNTIME_COMMIT": commit,
                    },
                },
                handle,
            )

    fake_bin = root / "bin"
    fake_bin.mkdir()
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        'if [ "${1:-}" != "print" ]; then exit 90; fi\n'
        f'echo "state = running"\n'
        f'echo "GUIYI_PROJECT_ROOT => {repo.resolve()}"\n'
        f'echo "GUIYI_RUNTIME_COMMIT => {commit}"\n',
        encoding="utf-8",
    )
    launchctl.chmod(0o755)
    curl = fake_bin / "curl"
    curl.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  *api/runtime/health*) echo \'{"status":"ok","readonly":true}\' ;;\n'
        "  *) echo 200 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    return repo, home, fake_bin


def _run_status(
    repo: Path,
    home: Path,
    fake_bin: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repo / "scripts/ops/macos/local-services-status.sh")],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
        },
        capture_output=True,
        text=True,
        check=False,
    )
