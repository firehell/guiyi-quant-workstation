from __future__ import annotations

from pathlib import Path
import os
import plistlib
import shutil
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]


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
    assert payload["EnvironmentVariables"]["GUIYI_WECHAT_COURIER_ROOT"] == ""
    assert payload["EnvironmentVariables"]["GUIYI_ALERT_WECHAT_GROUP_PATH"] == ""


def test_market_and_alert_confirmation_modes_write_only_their_own_marker(tmp_path: Path) -> None:
    market_repo = _copy_fixture(tmp_path / "market-repo")
    home, fake_bin = _fake_runtime(tmp_path / "market")
    _run(market_repo, home, fake_bin, "--confirm-market-runtime")
    assert (market_repo / ".run/market-runtime-enabled").read_text() == "enabled\n"
    assert not (market_repo / ".run/alert-runtime-enabled").exists()

    alert_repo = _copy_fixture(tmp_path / "alert-repo")
    alert_home, alert_bin = _fake_runtime(tmp_path / "alert")
    result = _run(
        alert_repo,
        alert_home,
        alert_bin,
        "--confirm-alert-runtime",
        extra_env={
            "GUIYI_WECHAT_COURIER_ROOT": "/Volumes/fixture/courier",
            "GUIYI_ALERT_WECHAT_GROUP_PATH": "/Volumes/fixture/secrets/group.json",
        },
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
    assert (
        alert_payload["EnvironmentVariables"]["GUIYI_WECHAT_COURIER_ROOT"]
        == "/Volumes/fixture/courier"
    )
    assert (
        alert_payload["EnvironmentVariables"]["GUIYI_ALERT_WECHAT_GROUP_PATH"]
        == "/Volumes/fixture/secrets/group.json"
    )


def test_run_local_service_has_dedicated_alert_cli_branch() -> None:
    source = (REPO_ROOT / "scripts/ops/macos/run-local-service.sh").read_text(encoding="utf-8")
    assert "alert)" in source
    assert "runtime alert" in source


def test_render_rejects_alert_path_xml_injection(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path / "repo")
    home, fake_bin = _fake_runtime(tmp_path)
    result = subprocess.run(
        [str(repo / "scripts/ops/macos/install-local-services.sh"), "--render-only"],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
            "GUIYI_WECHAT_COURIER_ROOT": "/Volumes/fixture/<key>injected</key>",
            "GUIYI_ALERT_WECHAT_GROUP_PATH": "/Volumes/fixture/group.json",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "invalid alert notification path" in result.stderr


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
