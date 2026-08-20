from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
NOTIFICATION_CONFIG_ENV = "GUIYI_ALERT_NOTIFICATION_CONFIG_PATH"


def test_alert_launchd_render_only_is_default_closed_and_has_one_config_path(
    tmp_path: Path,
) -> None:
    repo = _copy_fixture(tmp_path / "repo")
    home, fake_bin = _fake_runtime(tmp_path)

    _run(repo, home, fake_bin, "--render-only")

    assert not (repo / ".run/alert-runtime-enabled").exists()
    rendered = repo / ".run/launchd/com.guiyi.quant-alert.plist"
    with rendered.open("rb") as handle:
        payload = plistlib.load(handle)
    assert payload["ProgramArguments"][-1] == "alert"
    assert payload["EnvironmentVariables"][NOTIFICATION_CONFIG_ENV] == ""
    assert not any("OPENCLAW" in key or "CLAWBOT" in key for key in payload["EnvironmentVariables"])


def test_market_and_alert_confirmation_modes_write_only_their_own_marker(
    tmp_path: Path,
) -> None:
    market_repo = _copy_fixture(tmp_path / "market-repo")
    home, fake_bin = _fake_runtime(tmp_path / "market")
    _run(market_repo, home, fake_bin, "--confirm-market-runtime")
    assert (market_repo / ".run/market-runtime-enabled").read_text() == "enabled\n"
    assert not (market_repo / ".run/alert-runtime-enabled").exists()

    alert_repo = _copy_fixture(tmp_path / "alert-repo")
    alert_home, alert_bin = _fake_runtime(tmp_path / "alert")
    config = _notification_config(tmp_path / "private")
    env = {NOTIFICATION_CONFIG_ENV: str(config)}
    _run(alert_repo, alert_home, alert_bin, "--confirm-load", extra_env=env)
    (alert_home / "launchctl-calls.log").unlink()

    result = _run(
        alert_repo,
        alert_home,
        alert_bin,
        "--confirm-alert-runtime",
        extra_env=env,
    )

    assert (alert_repo / ".run/alert-runtime-enabled").read_text() == "enabled\n"
    assert not (alert_repo / ".run/market-runtime-enabled").exists()
    assert "mode=--confirm-alert-runtime services=1" in result.stdout
    agent_dir = alert_home / "Library/LaunchAgents"
    with (agent_dir / "com.guiyi.quant-api.plist").open("rb") as handle:
        managed_api = plistlib.load(handle)
    with (agent_dir / "com.guiyi.quant-alert.plist").open("rb") as handle:
        managed_alert = plistlib.load(handle)
    assert managed_api["EnvironmentVariables"][NOTIFICATION_CONFIG_ENV] == str(config)
    assert managed_alert["EnvironmentVariables"][NOTIFICATION_CONFIG_ENV] == str(config)


def test_alert_confirmation_rejects_installed_api_path_mismatch_without_mutation(
    tmp_path: Path,
) -> None:
    repo = _copy_fixture(tmp_path / "repo")
    home, fake_bin = _fake_runtime(tmp_path)
    old_config = _notification_config(tmp_path / "old")
    new_config = _notification_config(tmp_path / "new")
    _run(
        repo,
        home,
        fake_bin,
        "--confirm-load",
        extra_env={NOTIFICATION_CONFIG_ENV: str(old_config)},
    )
    calls = home / "launchctl-calls.log"
    calls.unlink()

    result = subprocess.run(
        [str(repo / "scripts/ops/macos/install-local-services.sh"), "--confirm-alert-runtime"],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
            "GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD": "1",
            NOTIFICATION_CONFIG_ENV: str(new_config),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "installed API notification paths do not match" in result.stderr
    assert not (repo / ".run/alert-runtime-enabled").exists()
    assert not calls.exists()


def test_run_local_service_preserves_launcher_config_over_runtime_env(
    tmp_path: Path,
) -> None:
    repo = _copy_fixture(tmp_path / "repo")
    python = repo / "services/quant-api/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        f"#!/bin/sh\nprintf '{NOTIFICATION_CONFIG_ENV}=%s\\n' \"${NOTIFICATION_CONFIG_ENV}\"\n",
        encoding="utf-8",
    )
    python.chmod(0o700)
    runtime_env = tmp_path / "project.env"
    runtime_env.write_text(
        "POSTGRES_PASSWORD=test-only\n"
        f"{NOTIFICATION_CONFIG_ENV}=/runtime/config.json\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(repo / "scripts/ops/macos/run-local-service.sh"), "api"],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "GUIYI_PROJECT_ROOT": str(repo),
            "GUIYI_RUNTIME_ENV": str(runtime_env),
            NOTIFICATION_CONFIG_ENV: "/launcher/config.json",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        f"{NOTIFICATION_CONFIG_ENV}=/launcher/config.json"
    )


@pytest.mark.parametrize(
    "malicious_path",
    ("/fixture/<key>injected</key>", "/fixture/|g", "/fixture/back\\slash"),
)
def test_render_rejects_alert_path_injection(
    tmp_path: Path,
    malicious_path: str,
) -> None:
    repo = _copy_fixture(tmp_path / "repo")
    home, fake_bin = _fake_runtime(tmp_path)
    result = subprocess.run(
        [str(repo / "scripts/ops/macos/install-local-services.sh"), "--render-only"],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
            NOTIFICATION_CONFIG_ENV: malicious_path,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "invalid alert notification path" in result.stderr


def test_alert_confirmation_rejects_unsafe_config_permissions(
    tmp_path: Path,
) -> None:
    repo = _copy_fixture(tmp_path / "repo")
    home, fake_bin = _fake_runtime(tmp_path)
    config = _notification_config(tmp_path / "private")
    config.chmod(0o644)

    result = _run(
        repo,
        home,
        fake_bin,
        "--confirm-alert-runtime",
        extra_env={NOTIFICATION_CONFIG_ENV: str(config)},
        check=False,
    )

    assert result.returncode == 1
    assert "alert notification config not ready" in result.stderr


def _copy_fixture(destination: Path) -> Path:
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


def _notification_config(parent: Path) -> Path:
    parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    parent.chmod(0o700)
    path = parent / "notification.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "transport": "pushplus",
                "transport_config": {
                    "message_token": "0123456789abcdef0123456789abcdef",
                    "htdy_topic": "fixture-topic",
                },
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def _fake_runtime(root: Path) -> tuple[Path, Path]:
    home = root / "home"
    fake_bin = root / "bin"
    fake_bin.mkdir(parents=True)
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
    return home, fake_bin


def _run(
    repo: Path,
    home: Path,
    fake_bin: Path,
    mode: str,
    *,
    extra_env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(repo / "scripts/ops/macos/install-local-services.sh"), mode],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
            "GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD": "1",
            **(extra_env or {}),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    if check:
        assert result.returncode == 0, result.stderr
    return result
