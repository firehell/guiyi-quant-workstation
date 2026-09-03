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
    _market_preflight_ready(market_repo)
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


def test_alert_confirmation_writes_activation_marker_before_service_start(
    tmp_path: Path,
) -> None:
    repo = _copy_fixture(tmp_path / "repo")
    home, fake_bin = _fake_runtime(tmp_path)
    config = _notification_config(tmp_path / "private")
    env = {NOTIFICATION_CONFIG_ENV: str(config)}
    _run(repo, home, fake_bin, "--confirm-load", extra_env=env)

    result = _run(
        repo,
        home,
        fake_bin,
        "--confirm-alert-runtime",
        extra_env={**env, "GUIYI_FAKE_REQUIRE_ALERT_MARKER": "1"},
    )

    assert result.returncode == 0
    assert (repo / ".run/alert-runtime-enabled").read_text() == "enabled\n"


def test_failed_alert_start_restores_absent_activation_marker(
    tmp_path: Path,
) -> None:
    repo = _copy_fixture(tmp_path / "repo")
    home, fake_bin = _fake_runtime(tmp_path)
    config = _notification_config(tmp_path / "private")
    env = {NOTIFICATION_CONFIG_ENV: str(config)}
    _run(repo, home, fake_bin, "--confirm-load", extra_env=env)

    result = _run(
        repo,
        home,
        fake_bin,
        "--confirm-alert-runtime",
        extra_env={**env, "GUIYI_FAKE_FAIL_ALERT_BOOTSTRAP": "1"},
        check=False,
    )

    assert result.returncode == 1
    assert not (repo / ".run/alert-runtime-enabled").exists()


def test_failed_alert_start_restores_existing_activation_marker_content(
    tmp_path: Path,
) -> None:
    repo = _copy_fixture(tmp_path / "repo")
    home, fake_bin = _fake_runtime(tmp_path)
    config = _notification_config(tmp_path / "private")
    env = {NOTIFICATION_CONFIG_ENV: str(config)}
    _run(repo, home, fake_bin, "--confirm-load", extra_env=env)
    marker = repo / ".run/alert-runtime-enabled"
    marker.write_text("previous-state\n", encoding="utf-8")
    marker.chmod(0o600)

    result = _run(
        repo,
        home,
        fake_bin,
        "--confirm-alert-runtime",
        extra_env={**env, "GUIYI_FAKE_FAIL_ALERT_BOOTSTRAP": "1"},
        check=False,
    )

    assert result.returncode == 1
    assert marker.read_text() == "previous-state\n"


def test_failed_alert_marker_chmod_stops_before_launchd_and_restores_absence(
    tmp_path: Path,
) -> None:
    repo = _copy_fixture(tmp_path / "repo")
    home, fake_bin = _fake_runtime(tmp_path)
    config = _notification_config(tmp_path / "private")
    env = {NOTIFICATION_CONFIG_ENV: str(config)}
    _run(repo, home, fake_bin, "--confirm-load", extra_env=env)
    calls = home / "launchctl-calls.log"
    calls.unlink()

    result = _run(
        repo,
        home,
        fake_bin,
        "--confirm-alert-runtime",
        extra_env={**env, "GUIYI_FAKE_FAIL_MARKER_CHMOD": "1"},
        check=False,
    )

    assert result.returncode == 1
    assert not (repo / ".run/alert-runtime-enabled").exists()
    assert not calls.exists()


def test_failed_alert_enable_boots_out_started_service_before_marker_rollback(
    tmp_path: Path,
) -> None:
    repo = _copy_fixture(tmp_path / "repo")
    home, fake_bin = _fake_runtime(tmp_path)
    config = _notification_config(tmp_path / "private")
    env = {NOTIFICATION_CONFIG_ENV: str(config)}
    _run(repo, home, fake_bin, "--confirm-load", extra_env=env)
    calls = home / "launchctl-calls.log"
    calls.unlink()

    result = _run(
        repo,
        home,
        fake_bin,
        "--confirm-alert-runtime",
        extra_env={**env, "GUIYI_FAKE_FAIL_ALERT_ENABLE": "1"},
        check=False,
    )

    assert result.returncode == 1
    assert not (repo / ".run/alert-runtime-enabled").exists()
    recorded = calls.read_text().splitlines()
    failed_enable = next(
        index
        for index, call in enumerate(recorded)
        if call.startswith("enable ") and "com.guiyi.quant-alert" in call
    )
    cleanup_bootout = next(
        index
        for index, call in enumerate(recorded[failed_enable + 1 :], failed_enable + 1)
        if call.startswith("bootout ") and "com.guiyi.quant-alert" in call
    )
    assert cleanup_bootout > failed_enable


def test_failed_alert_stop_retains_enabled_marker_instead_of_restoring_backup(
    tmp_path: Path,
) -> None:
    repo = _copy_fixture(tmp_path / "repo")
    home, fake_bin = _fake_runtime(tmp_path)
    config = _notification_config(tmp_path / "private")
    env = {NOTIFICATION_CONFIG_ENV: str(config)}
    _run(repo, home, fake_bin, "--confirm-load", extra_env=env)
    marker = repo / ".run/alert-runtime-enabled"
    marker.write_text("previous-state\n", encoding="utf-8")
    marker.chmod(0o600)

    result = _run(
        repo,
        home,
        fake_bin,
        "--confirm-alert-runtime",
        extra_env={
            **env,
            "GUIYI_FAKE_FAIL_ALERT_ENABLE": "1",
            "GUIYI_FAKE_STOP_REMAINS_LOADED": "1",
        },
        check=False,
    )

    assert result.returncode == 1
    assert marker.read_text() == "enabled\n"
    assert "failed attempt remains loaded; activation marker retained" in result.stderr


def test_failed_second_market_label_boots_out_every_touched_service(
    tmp_path: Path,
) -> None:
    repo = _copy_fixture(tmp_path / "repo")
    _market_preflight_ready(repo)
    home, fake_bin = _fake_runtime(tmp_path)

    result = _run(
        repo,
        home,
        fake_bin,
        "--confirm-market-runtime",
        extra_env={"GUIYI_FAKE_FAIL_AFTER_MARKET_ENABLE": "1"},
        check=False,
    )

    assert result.returncode == 1
    assert not (repo / ".run/market-runtime-enabled").exists()
    recorded = (home / "launchctl-calls.log").read_text().splitlines()
    failed_enable = next(
        index
        for index, call in enumerate(recorded)
        if call.startswith("enable ") and "com.guiyi.quant-after-market" in call
    )
    cleanup = recorded[failed_enable + 1 :]
    cleanup_bootouts = [call for call in cleanup if call.startswith("bootout ")]
    assert [call.rsplit("/", 1)[-1] for call in cleanup_bootouts] == [
        "com.guiyi.quant-after-market",
        "com.guiyi.quant-live",
    ]


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


def _market_preflight_ready(repo: Path) -> None:
    (repo / ".env").write_text("POSTGRES_PASSWORD=fixture-only\n", encoding="utf-8")
    python = repo / "services/quant-api/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' '{\"schema_version\":1,\"command\":\"runtime.market-promotion-preflight\",\"status\":\"passed\",\"reason\":\"non_trading_interval\",\"trading_day\":null,\"operational_count\":0,\"snapshot_count\":0}'\n",
        encoding="utf-8",
    )
    python.chmod(0o700)


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
        'state_dir="$HOME/fake-launchctl-state"\n'
        'alert_state="$state_dir/com.guiyi.quant-alert"\n'
        'mkdir -p "$state_dir"\n'
        'case "$*" in *com.guiyi.quant-alert.plist*)\n'
        '  if [ "${GUIYI_FAKE_REQUIRE_ALERT_MARKER:-0}" = "1" ] && [ ! -f "$PWD/.run/alert-runtime-enabled" ]; then exit 9; fi\n'
        '  if [ "${GUIYI_FAKE_FAIL_ALERT_BOOTSTRAP:-0}" = "1" ]; then exit 8; fi\n'
        'esac\n'
        'if [ "${1:-}" = "bootstrap" ]; then\n'
        '  case "$*" in *com.guiyi.quant-alert.plist*) touch "$alert_state" ;; esac\n'
        'fi\n'
        'if [ "${1:-}" = "bootout" ]; then\n'
        '  case "$*" in *com.guiyi.quant-alert*)\n'
        '    if [ -f "$alert_state" ] && [ "${GUIYI_FAKE_STOP_REMAINS_LOADED:-0}" = "1" ]; then exit 8; fi\n'
        '    rm -f "$alert_state"\n'
        '    exit 0\n'
        '  esac\n'
        'fi\n'
        'if [ "${1:-}" = "print" ] && [ "${2:-}" = "gui/$UID" ]; then echo "domain = gui/$UID"; exit 0; fi\n'
        'if [ "${1:-}" = "print" ]; then\n'
        '  case "$*" in *com.guiyi.quant-alert*) [ -f "$alert_state" ] && exit 0 ;; esac\n'
        'fi\n'
        'if [ "${1:-}" = "enable" ] && [ "${GUIYI_FAKE_FAIL_ALERT_ENABLE:-0}" = "1" ]; then\n'
        '  case "$*" in *com.guiyi.quant-alert*) exit 8 ;; esac\n'
        'fi\n'
        'if [ "${1:-}" = "enable" ] && [ "${GUIYI_FAKE_FAIL_AFTER_MARKET_ENABLE:-0}" = "1" ]; then\n'
        '  case "$*" in *com.guiyi.quant-after-market*) exit 8 ;; esac\n'
        'fi\n'
        'case "${1:-}" in bootstrap|enable|kickstart) exit 0 ;; print) echo "Could not find service" >&2; exit 1 ;; bootout) exit 1 ;; *) exit 2 ;; esac\n',
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
    chmod = fake_bin / "chmod"
    chmod.write_text(
        "#!/bin/sh\n"
        'case "${2:-}" in *alert-runtime-enabled.tmp.*)\n'
        '  if [ "${GUIYI_FAKE_FAIL_MARKER_CHMOD:-0}" = "1" ]; then exit 7; fi\n'
        'esac\n'
        'exec /bin/chmod "$@"\n',
        encoding="utf-8",
    )
    chmod.chmod(0o755)
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
