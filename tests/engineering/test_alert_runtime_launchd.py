from __future__ import annotations

from pathlib import Path
import os
import plistlib
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CLAWBOT_ENV_NAMES = (
    "GUIYI_OPENCLAW_BIN",
    "GUIYI_OPENCLAW_NODE_BIN",
    "GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT",
    "GUIYI_OPENCLAW_STATE_DIR",
    "GUIYI_OPENCLAW_CONFIG_PATH",
    "GUIYI_ALERT_CLAWBOT_OWNER_PATH",
)


def test_alert_launchd_render_only_is_default_closed_and_has_runtime_contract(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path / "repo")
    home, fake_bin = _fake_runtime(tmp_path)

    _run(repo, home, fake_bin, "--render-only")

    marker = repo / ".run" / "alert-runtime-enabled"
    assert not marker.exists()
    rendered = repo / ".run/launchd/com.guiyi.quant-alert.plist"
    with rendered.open("rb") as handle:
        payload = plistlib.load(handle)
    assert payload["Label"] == "com.guiyi.quant-alert"
    assert payload["ProgramArguments"][-1] == "alert"
    assert payload["ProgramArguments"][-2].endswith("run-local-service.sh")
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] is True
    assert payload["ThrottleInterval"] == 10
    assert (
        payload["EnvironmentVariables"]["GUIYI_RUNTIME_COMMIT"]
        == "1111111111111111111111111111111111111111"
    )
    assert {key: payload["EnvironmentVariables"][key] for key in CLAWBOT_ENV_NAMES} == {
        key: "" for key in CLAWBOT_ENV_NAMES
    }


def test_market_and_alert_confirmation_modes_write_only_their_own_marker(tmp_path: Path) -> None:
    market_repo = _copy_fixture(tmp_path / "market-repo")
    home, fake_bin = _fake_runtime(tmp_path / "market")
    _run(market_repo, home, fake_bin, "--confirm-market-runtime")
    assert (market_repo / ".run/market-runtime-enabled").read_text() == "enabled\n"
    assert not (market_repo / ".run/alert-runtime-enabled").exists()

    alert_repo = _copy_fixture(tmp_path / "alert-repo")
    alert_home, alert_bin = _fake_runtime(tmp_path / "alert")
    approved_paths = _clawbot_paths(tmp_path / "clawbot")
    _run(
        alert_repo,
        alert_home,
        alert_bin,
        "--confirm-load",
        extra_env=approved_paths,
    )
    (alert_home / "launchctl-calls.log").unlink()
    result = _run(
        alert_repo,
        alert_home,
        alert_bin,
        "--confirm-alert-runtime",
        extra_env=approved_paths,
    )
    assert (alert_repo / ".run/alert-runtime-enabled").read_text() == "enabled\n"
    assert not (alert_repo / ".run/market-runtime-enabled").exists()
    assert "mode=--confirm-alert-runtime services=1" in result.stdout
    calls = (alert_home / "launchctl-calls.log").read_text(encoding="utf-8")
    assert "com.guiyi.quant-alert" in calls
    assert all(
        "com.guiyi.quant-" not in line or "com.guiyi.quant-alert" in line
        for line in calls.splitlines()
    )
    rendered = alert_repo / ".run/launchd/com.guiyi.quant-alert.plist"
    with rendered.open("rb") as handle:
        alert_payload = plistlib.load(handle)
    api_rendered = alert_repo / ".run/launchd/com.guiyi.quant-api.plist"
    with api_rendered.open("rb") as handle:
        api_payload = plistlib.load(handle)
    for key in CLAWBOT_ENV_NAMES:
        assert alert_payload["EnvironmentVariables"][key] == approved_paths[key]
        assert api_payload["EnvironmentVariables"][key] == alert_payload[
            "EnvironmentVariables"
        ][key]
    agent_dir = alert_home / "Library/LaunchAgents"
    with (agent_dir / "com.guiyi.quant-api.plist").open("rb") as handle:
        managed_api = plistlib.load(handle)
    with (agent_dir / "com.guiyi.quant-alert.plist").open("rb") as handle:
        managed_alert = plistlib.load(handle)
    for key in approved_paths:
        assert managed_api["EnvironmentVariables"][key] == managed_alert[
            "EnvironmentVariables"
        ][key]


def test_alert_confirmation_rejects_installed_api_path_mismatch_without_mutation(
    tmp_path: Path,
) -> None:
    repo = _copy_fixture(tmp_path / "repo")
    home, fake_bin = _fake_runtime(tmp_path)
    _run(
        repo,
        home,
        fake_bin,
        "--confirm-load",
        extra_env=_clawbot_paths(tmp_path / "old-clawbot"),
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
            **_clawbot_paths(tmp_path / "new-clawbot"),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "installed API notification paths do not match" in result.stderr
    assert not (repo / ".run/alert-runtime-enabled").exists()
    assert not calls.exists()


def test_run_local_service_has_dedicated_alert_cli_branch() -> None:
    source = (REPO_ROOT / "scripts/ops/macos/run-local-service.sh").read_text(encoding="utf-8")
    assert "alert)" in source
    assert "runtime alert" in source


def test_run_local_service_preserves_launcher_clawbot_paths_over_runtime_env(
    tmp_path: Path,
) -> None:
    repo = _copy_fixture(tmp_path / "repo")
    python = repo / "services/quant-api/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\n"
        + "".join(f"printf '{key}=%s\\n' \"${key}\"\n" for key in CLAWBOT_ENV_NAMES),
        encoding="utf-8",
    )
    python.chmod(0o700)
    runtime_env = tmp_path / "project.env"
    runtime_values = {key: f"/runtime-env/{index}" for index, key in enumerate(CLAWBOT_ENV_NAMES)}
    launcher_values = {key: f"/launcher/{index}" for index, key in enumerate(CLAWBOT_ENV_NAMES)}
    runtime_env.write_text(
        "POSTGRES_PASSWORD=test-only\n"
        + "".join(f"{key}={value}\n" for key, value in runtime_values.items()),
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
            **launcher_values,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        f"{key}={launcher_values[key]}" for key in CLAWBOT_ENV_NAMES
    ]


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
            **{
                **{key: f"/fixture/{index}" for index, key in enumerate(CLAWBOT_ENV_NAMES)},
                "GUIYI_OPENCLAW_BIN": malicious_path,
            },
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "invalid alert notification path" in result.stderr


def test_alert_confirmation_rejects_path_escape_before_render(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path / "repo")
    home, fake_bin = _fake_runtime(tmp_path)
    result = subprocess.run(
        [str(repo / "scripts/ops/macos/install-local-services.sh"), "--confirm-alert-runtime"],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
            "GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD": "1",
            **{
                **_clawbot_paths(tmp_path / "clawbot"),
                "GUIYI_OPENCLAW_BIN": "/private/tmp/../tmp/openclaw",
            },
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "alert notification paths not configured" in result.stderr
    assert not (repo / ".run/alert-runtime-enabled").exists()


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


def _clawbot_paths(root: Path) -> dict[str, str]:
    plugin = root / "plugin"
    state = root / "state"
    private = root / "private"
    for directory in (plugin, state, private):
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        directory.chmod(0o700)
    openclaw = root / "openclaw"
    node = root / "node"
    for executable in (openclaw, node):
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o700)
    config = state / "openclaw.json"
    config.write_text("{}\n", encoding="utf-8")
    owner = private / "owner.json"
    owner.write_text("{}\n", encoding="utf-8")
    owner.chmod(0o600)
    return dict(
        zip(
            CLAWBOT_ENV_NAMES,
            map(str, (openclaw, node, plugin, state, config, owner)),
            strict=True,
        )
    )


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
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(repo / "scripts/ops/macos/install-local-services.sh"), mode],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
            **(extra_env or {}),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result
