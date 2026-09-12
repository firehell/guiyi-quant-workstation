"""Launchd packaging contracts for the local Market Runtime activation marker."""

from __future__ import annotations

from pathlib import Path
import json
import os
import plistlib
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
NOTIFICATION_CONFIG_ENV = "GUIYI_ALERT_NOTIFICATION_CONFIG_PATH"


def test_weekly_render_is_saturday_and_install_only_loads_weekly_without_shared_launcher_write(tmp_path):
    repo = _copy_launchd_fixture(tmp_path / "repo")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        '[ "$1" = print ] && [ "$2" = "gui/$UID" ] && exit 0\n'
        '[ "$1" = print ] && { printf \'Could not find service "%s" in domain for user gui: %s\\n\' "${2##*/}" "$UID" >&2; exit 113; }\n'
        'printf "%s\\n" "$*" >> "$HOME/calls"\n'
        "exit 0\n"
    )
    launchctl.chmod(0o755)
    _run_installer(repo, home, fake_bin, "--render-only")
    rendered = repo / ".run/launchd/com.guiyi.quant-weekly-audit.plist"
    payload = plistlib.loads(rendered.read_bytes())
    assert payload["StartCalendarInterval"] == {"Weekday": 6, "Hour": 9, "Minute": 0}
    assert not payload.get("RunAtLoad") and not payload.get("KeepAlive")
    assert payload["ProgramArguments"][-1] == "weekly-audit"
    assert not (home / "calls").exists()
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    api = agents / "com.guiyi.quant-api.plist"
    api.write_bytes(plistlib.dumps({"EnvironmentVariables": {
        "GUIYI_PROJECT_ROOT": str(repo), "GUIYI_RUNTIME_COMMIT": "1" * 40}}))
    shared = home / "Library/Application Support/GuiyiQuant/run-local-service.sh"
    shared.parent.mkdir(parents=True)
    shared.write_text("original shared launcher")
    _run_installer(repo, home, fake_bin, "--confirm-weekly-audit")
    assert shared.read_text() == "original shared launcher"
    calls = (home / "calls").read_text().splitlines()
    assert all("quant-weekly-audit" in call for call in calls)
    assert not any("kickstart" in call for call in calls)
    assert not (repo / ".run/market-runtime-enabled").exists()


def test_weekly_install_rejects_different_runtime_identity_before_launchctl(tmp_path):
    repo = _copy_launchd_fixture(tmp_path / "repo")
    home, fake_bin = tmp_path / "home", tmp_path / "bin"
    fake_bin.mkdir()
    _run_installer(repo, home, fake_bin, "--render-only")
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    (agents / "com.guiyi.quant-api.plist").write_bytes(plistlib.dumps({"EnvironmentVariables": {
        "GUIYI_PROJECT_ROOT": "/different/runtime", "GUIYI_RUNTIME_COMMIT": "1" * 40}}))
    result = _run_installer_result(repo, home, fake_bin, "--confirm-weekly-audit")
    assert result.returncode != 0
    assert "weekly audit runtime identity mismatch" in result.stderr
    assert not (agents / "com.guiyi.quant-weekly-audit.plist").exists()


def test_preflight_delegates_status_authority_to_the_single_python_process(
    tmp_path: Path,
) -> None:
    repo = _copy_launchd_fixture(tmp_path / "candidate")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$HOME/shell-launchctl-calls"\n'
        'echo "permission denied" >&2\n'
        "exit 77\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)
    python = repo / "services/quant-api/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\n"
        '[ -z "${GUIYI_AFTER_MARKET_STATUS_PATH:-}" ] || exit 91\n'
        "printf '%s\\n' '{\"schema_version\":1,\"command\":\"runtime.market-promotion-preflight\",\"status\":\"passed\",\"reason\":\"non_trading_interval\",\"trading_day\":null,\"operational_count\":0,\"snapshot_count\":0}'\n",
        encoding="utf-8",
    )
    python.chmod(0o700)

    result = subprocess.run(
        [str(repo / "scripts/ops/macos/run-local-service.sh"), "market-runtime-preflight"],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
            "GUIYI_PROJECT_ROOT": str(repo),
            "GUIYI_RUNTIME_ENV": str(tmp_path / "missing.env"),
            "POSTGRES_PASSWORD": "fixture",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["reason"] == "non_trading_interval"
    assert not (home / "shell-launchctl-calls").exists()


def test_install_modes_only_confirm_market_runtime_persists_activation_marker(tmp_path: Path) -> None:
    """Render/base install stay disabled; explicit market activation creates the fixed marker."""
    repo = _copy_launchd_fixture(tmp_path / "repo")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_launchctl = fake_bin / "launchctl"
    fake_launchctl.write_text(
        "#!/bin/sh\n"
        'if [ "${1:-}" = "print" ]; then\n'
        '  [ "${2:-}" = "gui/$UID" ] && { echo "domain = gui/$UID"; exit 0; }\n'
        '  printf \'Could not find service "%s" in domain for user gui: %s\\n\' "${2##*/}" "$UID" >&2; exit 113\n'
        "fi\n"
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

    base_result = _run_installer(repo, home, fake_bin, "--confirm-load")
    assert not marker.exists()
    assert (
        "[install-local-services] loaded=true mode=--confirm-load services=3"
        in base_result.stdout
    )

    runtime_result = _run_installer(repo, home, fake_bin, "--confirm-market-runtime")
    assert marker.read_text(encoding="utf-8") == "enabled\n"
    assert (
        "[install-local-services] loaded=true mode=--confirm-market-runtime services=2"
        in runtime_result.stdout
    )


def test_blocked_market_preflight_leaves_marker_plists_and_launchctl_untouched(
    tmp_path: Path,
) -> None:
    """A promotion block must happen before any activation-side mutation."""
    repo = _copy_launchd_fixture(tmp_path / "repo")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    python = repo / "services/quant-api/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' '{\"schema_version\":1,\"command\":\"runtime.market-promotion-preflight\",\"status\":\"blocked\",\"reason\":\"MARKET_RUNTIME_PROMOTION_LIVE_SNAPSHOT_REQUIRED\",\"trading_day\":\"2026-09-03\",\"operational_count\":2,\"snapshot_count\":0}'\n"
        "exit 1\n",
        encoding="utf-8",
    )
    python.chmod(0o700)
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        'if [ "${1:-}" = "print" ]; then\n'
        '  [ "${2:-}" = "gui/$UID" ] && { echo "domain = gui/$UID"; exit 0; }\n'
        '  printf \'Could not find service "%s" in domain for user gui: %s\\n\' "${2##*/}" "$UID" >&2; exit 113\n'
        "fi\n"
        "printf '%s\\n' \"$*\" >> \"$HOME/launchctl-calls.log\"\n"
        "exit 90\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)

    result = _run_installer_result(repo, home, fake_bin, "--confirm-market-runtime")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "MARKET_RUNTIME_PROMOTION_LIVE_SNAPSHOT_REQUIRED" in result.stdout
    assert not (repo / ".run/market-runtime-enabled").exists()
    assert not (home / "Library/LaunchAgents").exists()
    assert not (home / "launchctl-calls.log").exists()


def test_market_preflight_missing_runtime_python_has_bounded_json_contract(
    tmp_path: Path,
) -> None:
    repo = _copy_launchd_fixture(tmp_path / "repo")
    result = subprocess.run(
        [str(repo / "scripts/ops/macos/run-local-service.sh"), "market-runtime-preflight"],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "GUIYI_PROJECT_ROOT": str(repo),
            "GUIYI_RUNTIME_ENV": str(tmp_path / "missing.env"),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "schema_version": 1,
        "command": "runtime.market-promotion-preflight",
        "status": "blocked",
        "reason": "MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE",
        "trading_day": None,
        "operational_count": 0,
        "snapshot_count": 0,
    }


def test_market_preflight_loads_runtime_env_without_disclosing_it(tmp_path: Path) -> None:
    repo = _copy_launchd_fixture(tmp_path / "repo")
    home = tmp_path / "home"
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text("POSTGRES_PASSWORD=test-only-secret\n", encoding="utf-8")
    python = repo / "services/quant-api/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\n"
        '[ "$POSTGRES_PASSWORD" = "test-only-secret" ] || exit 91\n'
        "printf '%s\\n' '{\"schema_version\":1,\"command\":\"runtime.market-promotion-preflight\",\"status\":\"passed\",\"reason\":\"non_trading_interval\",\"trading_day\":null,\"operational_count\":0,\"snapshot_count\":0}'\n",
        encoding="utf-8",
    )
    python.chmod(0o700)

    result = subprocess.run(
        [str(repo / "scripts/ops/macos/run-local-service.sh"), "market-runtime-preflight"],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(home),
            "GUIYI_PROJECT_ROOT": str(repo),
            "GUIYI_RUNTIME_ENV": str(runtime_env),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout)["status"] == "passed"
    assert "test-only-secret" not in result.stdout + result.stderr


def test_market_preflight_source_cannot_override_python_status_authority_or_arguments(
    tmp_path: Path,
) -> None:
    repo = _copy_launchd_fixture(tmp_path / "candidate")
    supervised = tmp_path / "supervised"
    (supervised / ".run").mkdir(parents=True)
    status_path = supervised / ".run/after-market-status.json"
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text(
        "POSTGRES_PASSWORD=fixture\n"
        f"HOME={tmp_path}/runtime-env-home\n"
        f"controlled_status_path={repo}/.run/after-market-status.json\n"
        f"GUIYI_AFTER_MARKET_STATUS_PATH={repo}/.run/after-market-status.json\n"
        "GUIYI_EXPECTED_AFTER_MARKET_STATUS_SHA256=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
        "set -- source-overrode-arguments\n",
        encoding="utf-8",
    )
    python = repo / "services/quant-api/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\n"
        '[ -z "${GUIYI_AFTER_MARKET_STATUS_PATH:-}" ] || exit 91\n'
        '[ "$*" = "-m app.market_data.runtime_promotion" ] || exit 92\n'
        f'[ "$HOME" = "{tmp_path / "home"}" ] || exit 93\n'
        f'[ "$GUIYI_EXPECTED_AFTER_MARKET_STATUS_SHA256" = "{"a" * 64}" ] || exit 94\n'
        "touch \"$(dirname \"$0\")/python-was-run\"\n"
        "printf '%s\\n' '{\"schema_version\":1,\"command\":\"runtime.market-promotion-preflight\",\"status\":\"passed\",\"reason\":\"non_trading_interval\",\"trading_day\":null,\"operational_count\":0,\"snapshot_count\":0}'\n",
        encoding="utf-8",
    )
    python.chmod(0o700)

    result = subprocess.run(
        [str(repo / "scripts/ops/macos/run-local-service.sh"), "market-runtime-preflight"],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "GUIYI_PROJECT_ROOT": str(repo),
            "GUIYI_RUNTIME_ENV": str(runtime_env),
            "GUIYI_AFTER_MARKET_STATUS_PATH": str(status_path),
            "GUIYI_EXPECTED_AFTER_MARKET_STATUS_SHA256": "a" * 64,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout)["reason"] == "non_trading_interval"
    assert (python.parent / "python-was-run").exists()
    assert str(repo) not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "contents",
    [
        'POSTGRES_PASSWORD="${MISSING_RUNTIME_VALUE:?missing}"\n',
        "exit 7\n",
        "false\n",
        "if then\n",
    ],
)
def test_market_preflight_env_source_failure_has_one_bounded_json_line(
    tmp_path: Path, contents: str
) -> None:
    repo = _copy_launchd_fixture(tmp_path / "repo")
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text(contents, encoding="utf-8")
    python = repo / "services/quant-api/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' '{\"schema_version\":1,\"command\":\"runtime.market-promotion-preflight\",\"status\":\"passed\",\"reason\":\"non_trading_interval\",\"trading_day\":null,\"operational_count\":0,\"snapshot_count\":0}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    python.chmod(0o700)

    result = subprocess.run(
        [str(repo / "scripts/ops/macos/run-local-service.sh"), "market-runtime-preflight"],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "GUIYI_PROJECT_ROOT": str(repo),
            "GUIYI_RUNTIME_ENV": str(runtime_env),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stderr == ""
    assert result.stdout.count("\n") == 1
    assert json.loads(result.stdout)["reason"] == "MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE"
    assert "MISSING_RUNTIME_VALUE" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("payload", "exit_code"),
    [
        (
            '{"schema_version":1,"command":"runtime.market-promotion-preflight","status":"passed","reason":"snapshot_ready","trading_day":"2026-09-03","operational_count":2,"snapshot_count":2,"extra":"synthetic-secret"}',
            0,
        ),
        (
            '{"schema_version":1,"command":"runtime.market-promotion-preflight","status":"passed","reason":"unknown","trading_day":"2026-09-03","operational_count":2,"snapshot_count":2}',
            0,
        ),
        (
            '{"schema_version":1,"command":"runtime.market-promotion-preflight","status":"blocked","reason":"MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE","trading_day":null,"operational_count":0,"snapshot_count":0} synthetic-secret',
            1,
        ),
    ],
)
def test_market_preflight_rejects_noncanonical_child_payload_without_echoing_it(
    tmp_path: Path, payload: str, exit_code: int
) -> None:
    repo = _copy_launchd_fixture(tmp_path / "repo")
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text("POSTGRES_PASSWORD=fixture\n", encoding="utf-8")
    python = repo / "services/quant-api/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' '{payload}'\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    python.chmod(0o700)

    result = subprocess.run(
        [str(repo / "scripts/ops/macos/run-local-service.sh"), "market-runtime-preflight"],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "GUIYI_PROJECT_ROOT": str(repo),
            "GUIYI_RUNTIME_ENV": str(runtime_env),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stderr == ""
    assert result.stdout.count("\n") == 1
    assert json.loads(result.stdout)["reason"] == "MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE"
    assert "synthetic-secret" not in result.stdout + result.stderr


def test_market_preflight_runs_once_before_any_activation_mutation(
    tmp_path: Path,
) -> None:
    repo = _copy_launchd_fixture(tmp_path / "repo")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    python = repo / "services/quant-api/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\n"
        'count_file="$(dirname "$0")/preflight-count"\n'
        'count=0; [ -f "$count_file" ] && count="$(cat "$count_file")"\n'
        'count=$((count + 1)); printf "%s" "$count" > "$count_file"\n'
        'if [ "$count" -eq 1 ]; then\n'
        "  printf '%s\\n' '{\"schema_version\":1,\"command\":\"runtime.market-promotion-preflight\",\"status\":\"passed\",\"reason\":\"snapshot_ready\",\"trading_day\":\"2026-09-03\",\"operational_count\":2,\"snapshot_count\":2}'\n"
        "  exit 0\n"
        "fi\n"
        "printf '%s\\n' '{\"schema_version\":1,\"command\":\"runtime.market-promotion-preflight\",\"status\":\"blocked\",\"reason\":\"MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE\",\"trading_day\":\"2026-09-03\",\"operational_count\":2,\"snapshot_count\":2}'\n"
        "exit 1\n",
        encoding="utf-8",
    )
    python.chmod(0o700)
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        'if [ "${1:-}" = "print" ]; then\n'
        '  [ "${2:-}" = "gui/$UID" ] && { echo "domain = gui/$UID"; exit 0; }\n'
        '  printf \'Could not find service "%s" in domain for user gui: %s\\n\' "${2##*/}" "$UID" >&2; exit 113\n'
        "fi\n"
        "case \"${1:-}\" in\n"
        "  bootstrap|enable|kickstart) exit 0 ;;\n"
        "  print|bootout) exit 1 ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)

    result = _run_installer_result(repo, home, fake_bin, "--confirm-market-runtime")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (python.parent / "preflight-count").read_text(encoding="utf-8") == "1"
    assert (repo / ".run/market-runtime-enabled").exists()
    assert list((home / "Library/LaunchAgents").glob("*.plist"))


def test_market_runtime_launch_agents_use_project_root_as_working_directory(
    tmp_path: Path,
) -> None:
    """RQData initialization must not scan the launchd user's home directory."""
    repo = _copy_launchd_fixture(tmp_path / "repo")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    _run_installer(repo, home, fake_bin, "--render-only")

    for label in ("com.guiyi.quant-live", "com.guiyi.quant-after-market"):
        rendered = repo / ".run" / "launchd" / f"{label}.plist"
        with rendered.open("rb") as handle:
            payload = plistlib.load(handle)
        assert isinstance(payload, dict)
        assert payload["WorkingDirectory"] == str(repo.resolve())


def test_market_install_establishes_new_after_market_owner_before_live(
    tmp_path: Path,
) -> None:
    repo = _copy_launchd_fixture(tmp_path / "repo")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        'if [ "${1:-}" = "print" ]; then\n'
        '  [ "${2:-}" = "gui/$UID" ] && { echo "domain = gui/$UID"; exit 0; }\n'
        '  printf \'Could not find service "%s" in domain for user gui: %s\\n\' "${2##*/}" "$UID" >&2; exit 113\n'
        "fi\n"
        'printf "%s\\n" "$*" >> "$HOME/launchctl-calls"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)

    result = _run_installer_result(repo, home, fake_bin, "--confirm-market-runtime")

    assert result.returncode == 0, result.stdout + result.stderr
    bootstraps = [
        Path(line.split()[-1]).name
        for line in (home / "launchctl-calls").read_text(encoding="utf-8").splitlines()
        if line.startswith("bootstrap ")
    ]
    assert bootstraps == [
        "com.guiyi.quant-after-market.plist",
        "com.guiyi.quant-live.plist",
    ]


def test_market_install_delegates_state_to_python_authority(
    tmp_path: Path,
) -> None:
    repo = _copy_launchd_fixture(tmp_path / "repo")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        'if [ "${1:-}" = "print" ]; then\n'
        '  echo "unexpected shell-side state read" >&2\n'
        "  exit 77\n"
        "fi\n"
        'printf "%s\\n" "$*" >> "$HOME/launchctl-mutations"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)

    result = _run_installer_result(repo, home, fake_bin, "--confirm-market-runtime")

    assert result.returncode == 0, result.stdout + result.stderr
    calls = (home / "authority-state-calls").read_text(encoding="utf-8").splitlines()
    assert calls[:2] == [
        "com.guiyi.quant-after-market",
        "com.guiyi.quant-live",
    ]


def test_market_install_rejects_unknown_state_from_python_authority(
    tmp_path: Path,
) -> None:
    repo = _copy_launchd_fixture(tmp_path / "repo")
    home = tmp_path / "home"
    authority_state = home / "authority-state"
    authority_state.mkdir(parents=True)
    (authority_state / "com.guiyi.quant-after-market").write_text(
        "unknown\n", encoding="utf-8"
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        'if [ "${1:-}" = print ]; then exit 77; fi\n'
        'printf "%s\\n" "$*" >> "$HOME/mutation-calls"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)

    result = _run_installer_result(repo, home, fake_bin, "--confirm-market-runtime")

    assert result.returncode == 1
    assert "market install preimage launchd state unknown" in result.stderr
    assert not (home / "mutation-calls").exists()


def test_partial_market_install_stops_candidate_and_restores_previous_authority(
    tmp_path: Path,
) -> None:
    repo = _copy_launchd_fixture(tmp_path / "repo")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sleep = fake_bin / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    sleep.chmod(0o755)
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        'command="${1:-}"\n'
        'target="${2:-}"\n'
        'label="${target##*/}"\n'
        'state_dir="$HOME/launchd-state"\n'
        'mkdir -p "$state_dir"\n'
        'if [ "$command" = "print" ] && [ "$target" = "gui/$UID" ]; then exit 0; fi\n'
        'if [ "$command" = "print" ]; then\n'
        '  [ -f "$state_dir/$label" ] && exit 0\n'
        '  printf \'Could not find service "%s" in domain for user gui: %s\\n\' "$label" "$UID" >&2; exit 113\n'
        "fi\n"
        'printf "%s\\n" "$*" >> "$HOME/launchctl-calls"\n'
        'if [ "$command" = "bootout" ]; then rm -f "$state_dir/$label"; exit 0; fi\n'
        'if [ "$command" = "bootstrap" ]; then\n'
        '  plist="${3:-}"; label="${plist##*/}"; label="${label%.plist}"\n'
        '  [ "$label" = "com.guiyi.quant-live" ] && exit 81\n'
        '  touch "$state_dir/$label"; exit 0\n'
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)

    result = _run_installer_result(repo, home, fake_bin, "--confirm-market-runtime")

    assert result.returncode == 1
    assert "partial market install is blocked" in result.stderr
    assert "previous market authority restored" in result.stderr
    assert "separate preflight and install intent required" in result.stderr
    assert not (repo / ".run/market-runtime-enabled").exists()
    state_dir = home / "launchd-state"
    assert not (state_dir / "com.guiyi.quant-after-market").exists()
    assert not (state_dir / "com.guiyi.quant-live").exists()


def test_partial_market_cleanup_launchctl_error_retains_marker_as_unknown(
    tmp_path: Path,
) -> None:
    repo = _copy_launchd_fixture(tmp_path / "repo")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sleep = fake_bin / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    sleep.chmod(0o755)
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        'if [ -f "$HOME/cleanup-started" ]; then\n'
        '  label="${2##*/}"; mkdir -p "$HOME/authority-state"\n'
        '  printf \'unknown\\n\' > "$HOME/authority-state/$label"\n'
        '  echo "permission denied" >&2; exit 77\n'
        "fi\n"
        'if [ "${1:-}" = "print" ] && [ "${2:-}" = "gui/$UID" ]; then exit 0; fi\n'
        'if [ "${1:-}" = "print" ]; then printf \'Could not find service "%s" in domain for user gui: %s\\n\' "${2##*/}" "$UID" >&2; exit 113; fi\n'
        'if [ "${1:-}" = "enable" ]; then\n'
        '  case "${2:-}" in *com.guiyi.quant-live) touch "$HOME/cleanup-started"; exit 81 ;; esac\n'
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)

    result = _run_installer_result(repo, home, fake_bin, "--confirm-market-runtime")

    assert result.returncode == 1
    assert "cleanup state unknown" in result.stderr
    assert "activation marker retained" in result.stderr
    assert (repo / ".run/market-runtime-enabled").read_text() == "enabled\n"


def test_partial_market_install_restores_authority_for_next_preflight(
    tmp_path: Path,
) -> None:
    repo = _copy_launchd_fixture(tmp_path / "candidate")
    old_root = tmp_path / "old-runtime"
    old_root.mkdir()
    home = tmp_path / "home"
    agent_dir = home / "Library/LaunchAgents"
    agent_dir.mkdir(parents=True)
    runtime_dir = home / "Library/Application Support/GuiyiQuant"
    runtime_dir.mkdir(parents=True)
    shared = runtime_dir / "run-local-service.sh"
    shared.write_text("old shared launcher\n", encoding="utf-8")
    rotator = runtime_dir / "rotate-local-service-logs.sh"
    rotator.write_text("old log rotator\n", encoding="utf-8")
    old_plists: dict[str, bytes] = {}
    for label in ("com.guiyi.quant-after-market", "com.guiyi.quant-live"):
        payload = plistlib.dumps(
            {
                "Label": label,
                "EnvironmentVariables": {"GUIYI_PROJECT_ROOT": str(old_root)},
            }
        )
        old_plists[label] = payload
        (agent_dir / f"{label}.plist").write_bytes(payload)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sleep = fake_bin / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    sleep.chmod(0o755)
    state_dir = home / "launchd-state"
    state_dir.mkdir()
    (state_dir / "com.guiyi.quant-live").touch()
    (home / "fail-live-once").touch()
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        'command="${1:-}"; target="${2:-}"; label="${target##*/}"\n'
        'state_dir="$HOME/launchd-state"\n'
        'if [ "$command" = print ] && [ "$target" = "gui/$UID" ]; then exit 0; fi\n'
        'if [ "$command" = print ]; then\n'
        '  [ -f "$state_dir/$label" ] && exit 0\n'
        '  printf \'Could not find service "%s" in domain for user gui: %s\\n\' "$label" "$UID" >&2; exit 113\n'
        "fi\n"
        'if [ "$command" = bootout ]; then rm -f "$state_dir/$label"; exit 0; fi\n'
        'if [ "$command" = bootstrap ]; then\n'
        '  label="${3##*/}"; label="${label%.plist}"; touch "$state_dir/$label"; exit 0\n'
        "fi\n"
        'if [ "$command" = enable ]; then\n'
        '  case "$target" in *com.guiyi.quant-live)\n'
        '    if [ -f "$HOME/fail-live-once" ]; then rm -f "$HOME/fail-live-once"; exit 81; fi ;;\n'
        '  esac\n'
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)
    python = repo / "services/quant-api/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = -m ] && [ "$2" = app.market_data.runtime_status_authority ]; then\n'
        '  [ "$3" = verify-restored-loaded-service ] || exit 96\n'
        '  [ "$4" = com.guiyi.quant-live ] || exit 97\n'
        f'  grep -q "{old_root}" "$HOME/Library/LaunchAgents/com.guiyi.quant-live.plist" || exit 92\n'
        '  grep -q "old shared launcher" "$HOME/Library/Application Support/GuiyiQuant/run-local-service.sh" || exit 93\n'
        '  [ -f "$HOME/launchd-state/com.guiyi.quant-live" ] || exit 94\n'
        '  printf "%s\\n" "$4" > "$HOME/restore-readback"\n'
        "  exit 0\n"
        "fi\n"
        'count_file="$(dirname "$0")/preflight-count"\n'
        'count=0; [ -f "$count_file" ] && count="$(cat "$count_file")"\n'
        'count=$((count + 1)); printf "%s" "$count" > "$count_file"\n'
        'if [ "$count" = 2 ]; then\n'
        f'  grep -q "{old_root}" "$HOME/Library/LaunchAgents/com.guiyi.quant-after-market.plist" || exit 91\n'
        f'  grep -q "{old_root}" "$HOME/Library/LaunchAgents/com.guiyi.quant-live.plist" || exit 92\n'
        '  grep -q "old shared launcher" "$HOME/Library/Application Support/GuiyiQuant/run-local-service.sh" || exit 93\n'
        '  [ -f "$HOME/launchd-state/com.guiyi.quant-live" ] || exit 94\n'
        '  [ ! -f "$HOME/launchd-state/com.guiyi.quant-after-market" ] || exit 95\n'
        "fi\n"
        "printf '%s\\n' '{\"schema_version\":1,\"command\":\"runtime.market-promotion-preflight\",\"status\":\"passed\",\"reason\":\"non_trading_interval\",\"trading_day\":null,\"operational_count\":0,\"snapshot_count\":0}'\n",
        encoding="utf-8",
    )
    python.chmod(0o700)

    first = _run_installer_result(repo, home, fake_bin, "--confirm-market-runtime")

    assert first.returncode == 1
    assert "previous market authority restored" in first.stderr
    assert shared.read_text() == "old shared launcher\n"
    assert rotator.read_text() == "old log rotator\n"
    for label, contents in old_plists.items():
        assert (agent_dir / f"{label}.plist").read_bytes() == contents
    assert (state_dir / "com.guiyi.quant-live").exists()
    assert not (state_dir / "com.guiyi.quant-after-market").exists()
    assert (home / "restore-readback").read_text() == "com.guiyi.quant-live\n"

    second = _run_installer_result(repo, home, fake_bin, "--confirm-market-runtime")

    assert second.returncode == 0, second.stdout + second.stderr
    assert (python.parent / "preflight-count").read_text() == "2"


def test_partial_market_restore_process_readback_unknown_retains_marker(
    tmp_path: Path,
) -> None:
    repo = _copy_launchd_fixture(tmp_path / "candidate")
    home = tmp_path / "home"
    agent_dir = home / "Library/LaunchAgents"
    agent_dir.mkdir(parents=True)
    old_root = tmp_path / "old-runtime"
    old_root.mkdir()
    for label in ("com.guiyi.quant-after-market", "com.guiyi.quant-live"):
        (agent_dir / f"{label}.plist").write_bytes(
            plistlib.dumps(
                {
                    "Label": label,
                    "EnvironmentVariables": {"GUIYI_PROJECT_ROOT": str(old_root)},
                }
            )
        )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sleep = fake_bin / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    sleep.chmod(0o755)
    state_dir = home / "launchd-state"
    state_dir.mkdir()
    (state_dir / "com.guiyi.quant-live").touch()
    (home / "fail-live-once").touch()
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        'command="${1:-}"; target="${2:-}"; label="${target##*/}"\n'
        'if [ "$command" = print ] && [ "$target" = "gui/$UID" ]; then exit 0; fi\n'
        'if [ "$command" = print ]; then\n'
        '  [ -f "$HOME/launchd-state/$label" ] && exit 0\n'
        '  printf \'Could not find service "%s" in domain for user gui: %s\\n\' "$label" "$UID" >&2; exit 113\n'
        "fi\n"
        'if [ "$command" = bootout ]; then rm -f "$HOME/launchd-state/$label"; exit 0; fi\n'
        'if [ "$command" = bootstrap ]; then\n'
        '  label="${3##*/}"; label="${label%.plist}"; touch "$HOME/launchd-state/$label"; exit 0\n'
        "fi\n"
        'if [ "$command" = enable ]; then\n'
        '  case "$target" in *com.guiyi.quant-live)\n'
        '    if [ -f "$HOME/fail-live-once" ]; then rm -f "$HOME/fail-live-once"; exit 81; fi ;;\n'
        "  esac\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)
    python = repo / "services/quant-api/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = -m ] && [ "$2" = app.market_data.runtime_status_authority ]; then\n'
        '  [ "$3" = verify-restored-loaded-service ] || exit 96\n'
        '  [ "$4" = com.guiyi.quant-live ] || exit 97\n'
        "  exit 88\n"
        "fi\n"
        "printf '%s\\n' '{\"schema_version\":1,\"command\":\"runtime.market-promotion-preflight\",\"status\":\"passed\",\"reason\":\"non_trading_interval\",\"trading_day\":null,\"operational_count\":0,\"snapshot_count\":0}'\n",
        encoding="utf-8",
    )
    python.chmod(0o700)

    result = _run_installer_result(repo, home, fake_bin, "--confirm-market-runtime")

    assert result.returncode == 1
    assert "market authority restore unknown; activation marker retained" in result.stderr
    assert "previous market authority restored" not in result.stderr
    assert (repo / ".run/market-runtime-enabled").read_text() == "enabled\n"
    assert (state_dir / "com.guiyi.quant-live").exists()
    assert not (state_dir / "com.guiyi.quant-after-market").exists()


def test_preload_mutation_failure_restores_market_authority_preimage(
    tmp_path: Path,
) -> None:
    repo = _copy_launchd_fixture(tmp_path / "candidate")
    home = tmp_path / "home"
    agent_dir = home / "Library/LaunchAgents"
    runtime_dir = home / "Library/Application Support/GuiyiQuant"
    agent_dir.mkdir(parents=True)
    runtime_dir.mkdir(parents=True)
    shared = runtime_dir / "run-local-service.sh"
    rotator = runtime_dir / "rotate-local-service-logs.sh"
    shared.write_text("old shared launcher\n", encoding="utf-8")
    rotator.write_text("old rotator\n", encoding="utf-8")
    old_plists = {}
    for label in ("com.guiyi.quant-after-market", "com.guiyi.quant-live"):
        content = plistlib.dumps({"Label": label, "old": True})
        old_plists[label] = content
        (agent_dir / f"{label}.plist").write_bytes(content)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state_dir = home / "launchd-state"
    state_dir.mkdir()
    (state_dir / "com.guiyi.quant-live").touch()
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        'command="${1:-}"; target="${2:-}"; label="${target##*/}"\n'
        'if [ "$command" = print ] && [ "$target" = "gui/$UID" ]; then exit 0; fi\n'
        'if [ "$command" = print ]; then\n'
        '  [ -f "$HOME/launchd-state/$label" ] && exit 0\n'
        '  printf \'Could not find service "%s" in domain for user gui: %s\\n\' "$label" "$UID" >&2; exit 113\n'
        "fi\n"
        'if [ "$command" = bootout ]; then rm -f "$HOME/launchd-state/$label"; exit 0; fi\n'
        'if [ "$command" = bootstrap ]; then\n'
        '  label="${3##*/}"; label="${label%.plist}"; touch "$HOME/launchd-state/$label"; exit 0\n'
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)
    chmod = fake_bin / "chmod"
    chmod.write_text(
        "#!/bin/sh\n"
        'case "${2:-}" in *GuiyiQuant/run-local-service.sh) exit 91 ;; esac\n'
        'exec /bin/chmod "$@"\n',
        encoding="utf-8",
    )
    chmod.chmod(0o755)

    result = _run_installer_result(repo, home, fake_bin, "--confirm-market-runtime")

    assert result.returncode == 1
    assert "previous market authority restored" in result.stderr
    assert shared.read_text(encoding="utf-8") == "old shared launcher\n"
    assert rotator.read_text(encoding="utf-8") == "old rotator\n"
    for label, content in old_plists.items():
        assert (agent_dir / f"{label}.plist").read_bytes() == content
    assert (state_dir / "com.guiyi.quant-live").exists()
    assert not (state_dir / "com.guiyi.quant-after-market").exists()
    assert not (repo / ".run/market-runtime-enabled").exists()


def test_post_commit_preimage_cleanup_unknown_reports_committed_success_no_retry(
    tmp_path: Path,
) -> None:
    repo = _copy_launchd_fixture(tmp_path / "candidate")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state_dir = home / "launchd-state"
    state_dir.mkdir(parents=True)
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/sh\n"
        'command="${1:-}"; target="${2:-}"; label="${target##*/}"\n'
        'if [ "$command" = print ] && [ "$target" = "gui/$UID" ]; then exit 0; fi\n'
        'if [ "$command" = print ]; then\n'
        '  [ -f "$HOME/launchd-state/$label" ] && exit 0\n'
        '  printf \'Could not find service "%s" in domain for user gui: %s\\n\' "$label" "$UID" >&2; exit 113\n'
        "fi\n"
        'if [ "$command" = bootout ]; then rm -f "$HOME/launchd-state/$label"; exit 0; fi\n'
        'if [ "$command" = bootstrap ]; then\n'
        '  label="${3##*/}"; label="${label%.plist}"; touch "$HOME/launchd-state/$label"; exit 0\n'
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)
    rm = fake_bin / "rm"
    rm.write_text(
        "#!/bin/sh\n"
        'case "${2:-}" in *market-install-preimage.*/0) exit 92 ;; esac\n'
        'exec /bin/rm "$@"\n',
        encoding="utf-8",
    )
    rm.chmod(0o755)

    result = _run_installer_result(repo, home, fake_bin, "--confirm-market-runtime")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "installation committed; post-commit cleanup unknown; do not retry" in result.stderr
    assert "cleanup=unknown retry_safe=false" in result.stdout
    assert (repo / ".run/market-runtime-enabled").read_text() == "enabled\n"
    for label in ("com.guiyi.quant-after-market", "com.guiyi.quant-live"):
        assert (state_dir / label).exists()
        payload = plistlib.loads((home / "Library/LaunchAgents" / f"{label}.plist").read_bytes())
        assert payload["EnvironmentVariables"]["GUIYI_PROJECT_ROOT"] == str(repo)


def test_after_market_launch_agent_runs_after_next_session_metadata_is_ready(
    tmp_path: Path,
) -> None:
    repo = _copy_launchd_fixture(tmp_path / "repo")
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    _run_installer(repo, home, fake_bin, "--render-only")

    rendered = repo / ".run/launchd/com.guiyi.quant-after-market.plist"
    with rendered.open("rb") as handle:
        payload = plistlib.load(handle)
    assert payload["StartCalendarInterval"] == {"Hour": 18, "Minute": 5}


def test_runtime_service_entrypoint_treats_retired_workers_as_unknown(tmp_path: Path) -> None:
    """已退役 worker 不再保留兼容 mode，并由未知服务分支统一 fail-closed。"""
    repo = _copy_launchd_fixture(tmp_path / "repo")
    environment = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "GUIYI_PROJECT_ROOT": str(repo),
        "GUIYI_RUNTIME_ENV": str(tmp_path / "missing.env"),
        "POSTGRES_PASSWORD": "test-only",
    }

    for service in ("worker-signals", "worker-notifications"):
        result = subprocess.run(
            [str(repo / "scripts/ops/macos/run-local-service.sh"), service],
            cwd=repo,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 2
        assert result.stderr == f"[run-local-service] unknown service: {service}\n"


def test_runtime_services_launch_the_thin_internal_module(tmp_path: Path) -> None:
    """The real launcher must not route Runtime through the full public CLI graph."""
    repo = _copy_launchd_fixture(tmp_path / "repo")
    python = repo / "services/quant-api/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text('#!/bin/sh\nprintf \'%s\\n\' "$*"\n', encoding="utf-8")
    python.chmod(0o700)
    environment = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "GUIYI_PROJECT_ROOT": str(repo),
        "GUIYI_RUNTIME_ENV": str(tmp_path / "missing.env"),
        "POSTGRES_PASSWORD": "test-only",
    }

    for service in ("live", "alert", "after-market", "weekly-audit"):
        result = subprocess.run(
            [str(repo / "scripts/ops/macos/run-local-service.sh"), service],
            cwd=repo,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"-m app.runtime_entry {service}"


def test_local_status_is_read_only_and_accepts_idle_after_market(tmp_path: Path) -> None:
    repo, home, fake_bin, calls = _status_fixture(tmp_path)

    result = _run_status(repo, home, fake_bin)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[local-services-status] readonly=true" in result.stdout
    assert f"supervised_runtime_root={repo.resolve()}" in result.stdout
    assert "runtime_checkout_detached=true" in result.stdout
    assert "runtime_checkout_clean=true" in result.stdout
    assert "com.guiyi.quant-after-market loaded state=not_running" in result.stdout
    assert "com.guiyi.quant-alert loaded state=running" in result.stdout
    assert "loaded_commit=" in result.stdout
    assert "alert.notification_channel=pushplus" in result.stdout
    assert "external.pushplus_config=ready" in result.stdout
    assert "alert.notification_audience_count=2" in result.stdout
    assert "external.openclaw" not in result.stdout
    assert "overall=passed" in result.stdout
    assert not calls.exists()


def test_status_shows_safe_after_market_progress_and_independent_weekly_summary(tmp_path):
    repo, home, fake_bin, calls = _status_fixture(tmp_path)
    payload = {"status": "ok", "readonly": True, "components": {
        "after_market": {"current_run": {"stage": "reading", "attempt": 1, "current_symbol": "jm",
            "counters": {"reading": {"completed": 7}}, "untrusted": "credential-do-not-show"}},
        "weekly_audit": {"status": "stale", "through": "2026-08-21", "finding_count": 0}}}
    (fake_bin / "curl").write_text('#!/bin/sh\ncase "$*" in\n*api/runtime/health*) printf \'%s\\n\' \' '
        + json.dumps(payload) + "' ;;\n*) echo 200 ;;\nesac\n")
    result = _run_status(repo, home, fake_bin)
    assert "after_market stage=reading attempt=1 symbol=jm completed_operations=7" in result.stdout
    assert "weekly_audit status=stale through=2026-08-21 findings=0" in result.stdout
    assert "credential-do-not-show" not in result.stdout + result.stderr
    assert "overall=passed" in result.stdout
    assert not calls.exists()


def test_local_status_fails_closed_for_ambiguous_active_alert_runtime(
    tmp_path: Path,
) -> None:
    repo, home, fake_bin, calls = _status_fixture(
        tmp_path,
        runtime_channel="none",
    )

    result = _run_status(repo, home, fake_bin)

    assert result.returncode == 1
    assert "alert.notification_channel=unknown" in result.stdout
    assert "overall=failed" in result.stdout
    assert not calls.exists()


def test_local_status_fails_closed_when_notification_plists_disagree(tmp_path: Path) -> None:
    repo, home, fake_bin, calls = _status_fixture(
        tmp_path,
        api_path_mismatch=True,
    )

    result = _run_status(repo, home, fake_bin)

    assert result.returncode == 1
    assert "external.pushplus_config=invalid" in result.stdout
    assert "overall=failed" in result.stdout
    assert not calls.exists()


def test_local_status_fails_closed_when_loaded_notification_path_is_stale(
    tmp_path: Path,
) -> None:
    repo, home, fake_bin, calls = _status_fixture(
        tmp_path,
        loaded_alert_path_mismatch=True,
    )

    result = _run_status(repo, home, fake_bin)

    assert result.returncode == 1
    assert "external.pushplus_config=invalid" in result.stdout
    assert "overall=failed" in result.stdout
    assert not calls.exists()


def test_local_status_fails_for_invalid_pushplus_config(
    tmp_path: Path,
) -> None:
    repo, home, fake_bin, calls = _status_fixture(
        tmp_path,
        notification_config_valid=False,
    )

    result = _run_status(repo, home, fake_bin)

    assert result.returncode == 1
    assert "alert.notification_channel=pushplus" in result.stdout
    assert "external.pushplus_config=invalid" in result.stdout
    assert "overall=failed" in result.stdout
    assert not calls.exists()


def test_local_status_requires_market_labels_when_marker_is_enabled(tmp_path: Path) -> None:
    repo, home, fake_bin, calls = _status_fixture(tmp_path, missing_after_market=True)

    result = _run_status(repo, home, fake_bin)

    assert result.returncode == 1
    assert "com.guiyi.quant-after-market missing" in result.stdout
    assert "overall=failed" in result.stdout
    assert not calls.exists()


def test_local_status_rejects_launch_agents_from_different_roots(tmp_path: Path) -> None:
    repo, home, fake_bin, calls = _status_fixture(tmp_path, mismatched_web_root=True)

    result = _run_status(repo, home, fake_bin)

    assert result.returncode == 1
    assert "com.guiyi.quant-web root_mismatch" in result.stdout
    assert "overall=failed" in result.stdout
    assert not calls.exists()


def test_local_status_requires_alert_label_when_alert_marker_is_enabled(
    tmp_path: Path,
) -> None:
    repo, home, fake_bin, calls = _status_fixture(tmp_path, missing_alert=True)

    result = _run_status(repo, home, fake_bin)

    assert result.returncode == 1
    assert "com.guiyi.quant-alert missing" in result.stdout
    assert "overall=failed" in result.stdout
    assert not calls.exists()


def test_local_status_rejects_loaded_process_commit_mismatch(tmp_path: Path) -> None:
    repo, home, fake_bin, calls = _status_fixture(
        tmp_path,
        mismatched_loaded_commit=True,
    )

    result = _run_status(repo, home, fake_bin)

    assert result.returncode == 1
    assert "com.guiyi.quant-alert commit_mismatch" in result.stdout
    assert "overall=failed" in result.stdout
    assert not calls.exists()


def _copy_launchd_fixture(destination: Path) -> Path:
    """Copy only installer inputs so mode tests cannot affect the real workstation."""
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


def _run_installer(
    repo: Path, home: Path, fake_bin: Path, mode: str
) -> subprocess.CompletedProcess[str]:
    fake_git = fake_bin / "git"
    if not fake_git.exists():
        fake_git.write_text(
            "#!/bin/sh\n"
            'if [ "${1:-}" = "-C" ] && [ "${3:-}" = "rev-parse" ] && [ "${4:-}" = "HEAD" ]; then\n'
            "  printf '1111111111111111111111111111111111111111\\n'\n"
            "  exit 0\n"
            "fi\n"
            "exit 2\n",
            encoding="utf-8",
        )
        fake_git.chmod(0o755)
    result = _run_installer_result(repo, home, fake_bin, mode)
    assert result.returncode == 0, result.stderr
    return result


def _run_installer_result(
    repo: Path, home: Path, fake_bin: Path, mode: str
) -> subprocess.CompletedProcess[str]:
    fake_git = fake_bin / "git"
    if not fake_git.exists():
        fake_git.write_text(
            "#!/bin/sh\n"
            'if [ "${1:-}" = "-C" ] && [ "${3:-}" = "rev-parse" ] && [ "${4:-}" = "HEAD" ]; then\n'
            "  printf '1111111111111111111111111111111111111111\\n'\n"
            "  exit 0\n"
            "fi\n"
            "exit 2\n",
            encoding="utf-8",
        )
        fake_git.chmod(0o755)
    python = repo / "services/quant-api/.venv/bin/python"
    if not python.exists():
        python.parent.mkdir(parents=True)
        python.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' '{\"schema_version\":1,\"command\":\"runtime.market-promotion-preflight\",\"status\":\"passed\",\"reason\":\"non_trading_interval\",\"trading_day\":null,\"operational_count\":0,\"snapshot_count\":0}'\n",
            encoding="utf-8",
        )
        python.chmod(0o700)
    behavior = python.with_name("python-test-behavior")
    if not behavior.exists():
        shutil.copy2(python, behavior)
        python.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = -m ] && [ "$2" = app.market_data.runtime_status_authority ] '
            '&& [ "$3" = launchd-service-state ]; then\n'
            '  label="$4"\n'
            '  printf "%s\\n" "$label" >> "$HOME/authority-state-calls"\n'
            '  state_file="$HOME/authority-state/$label"\n'
            '  if [ -f "$state_file" ]; then state="$(/bin/cat "$state_file")"\n'
            '  elif [ -f "$HOME/launchd-state/$label" ]; then state=loaded\n'
            "  else state=absent\n"
            "  fi\n"
            '  case "$state" in loaded|absent) printf \'%s\\n\' "$state" ;; *) exit 1 ;; esac\n'
            "  exit 0\n"
            "fi\n"
            'exec "$(dirname "$0")/python-test-behavior" "$@"\n',
            encoding="utf-8",
        )
        python.chmod(0o700)
    environment = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
        "POSTGRES_PASSWORD": "test-only",
    }
    return subprocess.run(
        [str(repo / "scripts/ops/macos/install-local-services.sh"), mode],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _status_fixture(
    tmp_path: Path,
    *,
    runtime_channel: str = "pushplus",
    alert_enabled: bool = True,
    notification_config_valid: bool = True,
    missing_after_market: bool = False,
    missing_alert: bool = False,
    mismatched_web_root: bool = False,
    mismatched_loaded_commit: bool = False,
    api_path_mismatch: bool = False,
    loaded_alert_path_mismatch: bool = False,
) -> tuple[Path, Path, Path, Path]:
    repo = _copy_launchd_fixture(tmp_path / "runtime")
    alerts = repo / "services/quant-api/app/alerts"
    alerts.mkdir(parents=True)
    if runtime_channel == "pushplus":
        (alerts / "pushplus.py").write_text("# pushplus fixture\n", encoding="utf-8")
    notification_path = _status_notification_config(
        tmp_path / "external-notification",
        valid=notification_config_valid,
    )
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
    (repo / ".run/market-runtime-enabled").write_text("enabled\n", encoding="utf-8")
    if alert_enabled:
        (repo / ".run/alert-runtime-enabled").write_text("enabled\n", encoding="utf-8")
    checkout_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    home = tmp_path / "home"
    agent_dir = home / "Library/LaunchAgents"
    agent_dir.mkdir(parents=True)
    for label in (
        "com.guiyi.quant-api",
        "com.guiyi.quant-web",
        "com.guiyi.quant-live",
        "com.guiyi.quant-after-market",
        "com.guiyi.quant-alert",
    ):
        if label == "com.guiyi.quant-alert" and missing_alert:
            continue
        project_root = (
            str((tmp_path / "different-runtime").resolve())
            if label == "com.guiyi.quant-web" and mismatched_web_root
            else str(repo.resolve())
        )
        label_notification_path = str(notification_path)
        if label == "com.guiyi.quant-api" and api_path_mismatch:
            label_notification_path += ".stale"
        with (agent_dir / f"{label}.plist").open("wb") as handle:
            plistlib.dump(
                {
                    "Label": label,
                    "EnvironmentVariables": {
                        "GUIYI_PROJECT_ROOT": project_root,
                        "GUIYI_RUNTIME_COMMIT": checkout_commit,
                        **(
                            {NOTIFICATION_CONFIG_ENV: label_notification_path}
                            if label in {"com.guiyi.quant-api", "com.guiyi.quant-alert"}
                            else {}
                        ),
                    },
                },
                handle,
            )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = home / "mutation-calls.log"
    fake_launchctl = fake_bin / "launchctl"
    missing_clause = (
        'if [ "$label" = "com.guiyi.quant-after-market" ]; then exit 1; fi\n'
        if missing_after_market
        else ""
    )
    missing_alert_clause = (
        'if [ "$label" = "com.guiyi.quant-alert" ]; then exit 1; fi\n'
        if missing_alert
        else ""
    )
    mismatch_clause = (
        'if [ "$label" = "com.guiyi.quant-alert" ]; then loaded_commit=0000000000000000000000000000000000000000; fi\n'
        if mismatched_loaded_commit
        else ""
    )
    fake_launchctl.write_text(
        "#!/bin/sh\n"
        'if [ "${1:-}" != "print" ]; then printf "%s\\n" "$*" >> "$HOME/mutation-calls.log"; exit 90; fi\n'
        'label="${2##*/}"\n'
        + missing_clause
        + missing_alert_clause
        + f'loaded_commit="{checkout_commit}"\n'
        + mismatch_clause
        + 'if [ "$label" = "com.guiyi.quant-after-market" ]; then echo "state = not running"; else echo "state = running"; fi\n'
        + f'echo "GUIYI_PROJECT_ROOT => {repo.resolve()}"\n'
        + 'echo "GUIYI_RUNTIME_COMMIT => $loaded_commit"\n',
        encoding="utf-8",
    )
    loaded_alert_value = str(notification_path)
    if loaded_alert_path_mismatch:
        loaded_alert_value += ".stale"
    original = fake_launchctl.read_text(encoding="utf-8")
    fake_launchctl.write_text(
        original
        + f'if [ "$label" = "com.guiyi.quant-alert" ]; then echo "{NOTIFICATION_CONFIG_ENV} => {loaded_alert_value}"; fi\n'
        + f'if [ "$label" = "com.guiyi.quant-api" ]; then echo "{NOTIFICATION_CONFIG_ENV} => {notification_path}"; fi\n',
        encoding="utf-8",
    )
    fake_launchctl.chmod(0o755)
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  *api/runtime/health*) echo \'{"status":"ok","readonly":true}\' ;;\n'
        "  *) echo 200 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    return repo, home, fake_bin, calls


def _run_status(
    repo: Path,
    home: Path,
    fake_bin: Path,
) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
    }
    return subprocess.run(
        [str(repo / "scripts/ops/macos/local-services-status.sh")],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _status_notification_config(root: Path, *, valid: bool) -> Path:
    root.mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    config = root / "notification.json"
    config.write_text(
        (
            '{"schema_version":1,"transport":"pushplus","transport_config":'
            '{"message_token":"0123456789abcdef0123456789abcdef",'
            '"htdy_topic":"fixture-topic"}}\n'
            if valid
            else '{}\n'
        ),
        encoding="utf-8",
    )
    config.chmod(0o600)
    return config
