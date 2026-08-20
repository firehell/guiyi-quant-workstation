"""Launchd packaging contracts for the local Market Runtime activation marker."""

from __future__ import annotations

import json
from pathlib import Path
import os
import plistlib
import shutil
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
OPENCLAW_VERSION = "OpenClaw 2026.7.1-2 (0790d9f)"
OPENCLAW_WEIXIN_VERSION = "2.4.6"
CLAWBOT_PATH_ENV_NAMES = (
    "GUIYI_OPENCLAW_BIN",
    "GUIYI_OPENCLAW_NODE_BIN",
    "GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT",
    "GUIYI_OPENCLAW_STATE_DIR",
    "GUIYI_OPENCLAW_CONFIG_PATH",
    "GUIYI_ALERT_CLAWBOT_RECIPIENTS_PATH",
)


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


def test_confirm_install_retires_legacy_launch_agents(tmp_path: Path) -> None:
    """正式加载必须收口旧 develop recovery/worker，避免形成第二套 Runtime。"""
    repo = _copy_launchd_fixture(tmp_path / "repo")
    home = tmp_path / "home"
    agent_dir = home / "Library" / "LaunchAgents"
    agent_dir.mkdir(parents=True)
    retired_labels = (
        "com.guiyi.quant-web-recovery",
        "com.guiyi.quant-worker-signals",
        "com.guiyi.quant-worker-signals-recovery",
        "com.guiyi.quant-api-recovery-single",
    )
    for label in retired_labels:
        (agent_dir / f"{label}.plist").write_text("legacy\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_launchctl = fake_bin / "launchctl"
    fake_launchctl.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$HOME/launchctl-calls.log\"\n"
        "case \"${1:-}\" in\n"
        "  bootstrap|enable|kickstart) exit 0 ;;\n"
        "  print|bootout) exit 1 ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_launchctl.chmod(0o755)

    _run_installer(repo, home, fake_bin, "--render-only")
    assert all((agent_dir / f"{label}.plist").exists() for label in retired_labels)

    _run_installer(repo, home, fake_bin, "--confirm-load")

    assert all(not (agent_dir / f"{label}.plist").exists() for label in retired_labels)
    calls = (home / "launchctl-calls.log").read_text(encoding="utf-8")
    for label in retired_labels:
        assert f"bootout gui/{os.getuid()}/{label}" in calls


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
    assert "alert.notification_channel=wecom" in result.stdout
    assert "external.openclaw" not in result.stdout
    assert "alert.notification_owner_alias" not in result.stdout
    assert "overall=passed" in result.stdout
    assert not calls.exists()


def test_local_status_reports_clawbot_from_supervised_runtime(tmp_path: Path) -> None:
    repo, home, fake_bin, calls = _status_fixture(
        tmp_path,
        runtime_channel="clawbot",
        alert_enabled=False,
        clawbot_state="ready",
    )

    result = _run_status(repo, home, fake_bin)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "alert.notification_channel=clawbot-openclaw-weixin" in result.stdout
    assert "alert.notification_recipient_count=1" in result.stdout
    assert "external.openclaw.status=ready" in result.stdout
    assert f"external.openclaw.version={OPENCLAW_VERSION}" in result.stdout
    assert "external.openclaw_weixin.status=ready" in result.stdout
    assert f"external.openclaw_weixin.version={OPENCLAW_WEIXIN_VERSION}" in result.stdout
    assert "external.clawbot_recipients_config=ready" in result.stdout
    assert "overall=passed" in result.stdout
    assert not calls.exists()


def test_local_status_uses_manifest_module_paths_without_private_path_knowledge(
    tmp_path: Path,
) -> None:
    repo, home, fake_bin, calls = _status_fixture(
        tmp_path,
        runtime_channel="clawbot",
        alert_enabled=False,
        clawbot_state="ready",
        custom_plugin_modules=True,
    )

    result = _run_status(repo, home, fake_bin)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "external.openclaw_weixin.status=ready" in result.stdout
    assert "overall=passed" in result.stdout
    assert not calls.exists()


def test_local_status_fails_closed_for_ambiguous_active_alert_runtime(
    tmp_path: Path,
) -> None:
    for runtime_channel in ("ambiguous", "courier", "none"):
        repo, home, fake_bin, calls = _status_fixture(
            tmp_path / runtime_channel,
            runtime_channel=runtime_channel,
        )

        result = _run_status(repo, home, fake_bin)

        assert result.returncode == 1
        assert "alert.notification_channel=unknown" in result.stdout
        assert "overall=failed" in result.stdout
        assert not calls.exists()


def test_local_status_fails_closed_when_clawbot_plists_disagree(tmp_path: Path) -> None:
    repo, home, fake_bin, calls = _status_fixture(
        tmp_path,
        runtime_channel="clawbot",
        alert_enabled=False,
        clawbot_state="ready",
        api_path_mismatch=True,
    )

    result = _run_status(repo, home, fake_bin)

    assert result.returncode == 1
    assert "external.openclaw.status=invalid" in result.stdout
    assert "overall=failed" in result.stdout
    assert not calls.exists()


def test_local_status_fails_closed_when_loaded_clawbot_paths_are_stale(
    tmp_path: Path,
) -> None:
    repo, home, fake_bin, calls = _status_fixture(
        tmp_path,
        runtime_channel="clawbot",
        alert_enabled=False,
        clawbot_state="ready",
        loaded_alert_path_mismatch=True,
    )

    result = _run_status(repo, home, fake_bin)

    assert result.returncode == 1
    assert "external.openclaw.status=invalid" in result.stdout
    assert "overall=failed" in result.stdout
    assert not calls.exists()


def test_local_status_fails_for_active_clawbot_with_invalid_dependency(
    tmp_path: Path,
) -> None:
    repo, home, fake_bin, calls = _status_fixture(
        tmp_path,
        runtime_channel="clawbot",
        clawbot_state="invalid",
    )

    result = _run_status(repo, home, fake_bin)

    assert result.returncode == 1
    assert "alert.notification_channel=clawbot-openclaw-weixin" in result.stdout
    assert "external.openclaw.status=invalid" in result.stdout
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
        "deploy/clawbot",
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
    return result


def _status_fixture(
    tmp_path: Path,
    *,
    runtime_channel: str = "wecom",
    alert_enabled: bool = True,
    clawbot_state: str = "missing",
    missing_after_market: bool = False,
    missing_alert: bool = False,
    mismatched_web_root: bool = False,
    mismatched_loaded_commit: bool = False,
    api_path_mismatch: bool = False,
    loaded_alert_path_mismatch: bool = False,
    custom_plugin_modules: bool = False,
) -> tuple[Path, Path, Path, Path]:
    repo = _copy_launchd_fixture(tmp_path / "runtime")
    alerts = repo / "services/quant-api/app/alerts"
    alerts.mkdir(parents=True)
    if runtime_channel in {"wecom", "ambiguous"}:
        (alerts / "wecom.py").write_text("# legacy fixture\n", encoding="utf-8")
    if runtime_channel in {"clawbot", "ambiguous"}:
        (alerts / "clawbot.py").write_text("# clawbot fixture\n", encoding="utf-8")
    if runtime_channel == "courier":
        (alerts / "wechat_courier.py").write_text("# retired fixture\n", encoding="utf-8")
    plugin_modules = (
        {
            "accounts": "compiled/account-entry.js",
            "inbound": "compiled/context-entry.js",
            "send": "compiled/send-entry.js",
        }
        if custom_plugin_modules
        else None
    )
    clawbot_paths = _status_clawbot_paths(
        tmp_path / "external-clawbot",
        state=clawbot_state,
        plugin_modules=plugin_modules,
    )
    if custom_plugin_modules:
        manifest = repo / "deploy/clawbot/versions.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["plugin_modules"] = plugin_modules
        manifest.write_text(json.dumps(payload), encoding="utf-8")
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
        label_clawbot_paths = dict(clawbot_paths)
        if label == "com.guiyi.quant-api" and api_path_mismatch and label_clawbot_paths:
            label_clawbot_paths["GUIYI_OPENCLAW_CONFIG_PATH"] += ".stale"
        with (agent_dir / f"{label}.plist").open("wb") as handle:
            plistlib.dump(
                {
                    "Label": label,
                    "EnvironmentVariables": {
                        "GUIYI_PROJECT_ROOT": project_root,
                        "GUIYI_RUNTIME_COMMIT": checkout_commit,
                        **(
                            label_clawbot_paths
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
    if clawbot_paths:
        loaded_lines = []
        for key in CLAWBOT_PATH_ENV_NAMES:
            value = clawbot_paths[key]
            if loaded_alert_path_mismatch and key == "GUIYI_OPENCLAW_CONFIG_PATH":
                value += ".stale"
            loaded_lines.append(
                f'if [ "$label" = "com.guiyi.quant-alert" ]; then echo "{key} => {value}"; fi\n'
            )
            loaded_lines.append(
                f'if [ "$label" = "com.guiyi.quant-api" ]; then echo "{key} => {clawbot_paths[key]}"; fi\n'
            )
        original = fake_launchctl.read_text(encoding="utf-8")
        fake_launchctl.write_text(original + "".join(loaded_lines), encoding="utf-8")
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


def _status_clawbot_paths(
    root: Path,
    *,
    state: str,
    plugin_modules: dict[str, str] | None = None,
) -> dict[str, str]:
    if state == "missing":
        return {}
    plugin = root / "plugin"
    state_dir = root / "state"
    owner_dir = root / "recipients"
    plugin.mkdir(parents=True)
    state_dir.mkdir()
    owner_dir.mkdir(mode=0o700)
    owner_dir.chmod(0o700)
    openclaw = root / "openclaw"
    node = root / "node"
    openclaw.write_text(f"#!/bin/sh\nprintf '%s\\n' '{OPENCLAW_VERSION}'\n", encoding="utf-8")
    node.write_text("#!/bin/sh\nprintf '%s\\n' 'v24.15.0'\n", encoding="utf-8")
    openclaw.chmod(0o700)
    node.chmod(0o700)
    config = state_dir / "openclaw.json"
    config.write_text("{}\n", encoding="utf-8")
    recipients = owner_dir / "recipients.json"
    recipients.write_text(
        '{"schema_version":2,"channel":"openclaw-weixin",'
        '"account_id":"private-account","active_recipients":'
        '[{"alias":"owner","target_user_id":"private-owner@im.wechat"}],'
        '"retired_aliases":[]}\n',
        encoding="utf-8",
    )
    recipients.chmod(0o600)
    (plugin / "package.json").write_text(
        f'{{"version":"{OPENCLAW_WEIXIN_VERSION}"}}\n', encoding="utf-8"
    )
    module_paths = plugin_modules or {
        "accounts": "dist/src/auth/accounts.js",
        "inbound": "dist/src/messaging/inbound.js",
        "send": "dist/src/messaging/send.js",
    }
    for relative in module_paths.values():
        module = plugin / relative
        module.parent.mkdir(parents=True, exist_ok=True)
        module.write_text("export {};\n", encoding="utf-8")
    if state == "invalid":
        openclaw.write_text("#!/bin/sh\nprintf 'wrong\\n'\n", encoding="utf-8")
    return {
        "GUIYI_OPENCLAW_BIN": str(openclaw),
        "GUIYI_OPENCLAW_NODE_BIN": str(node),
        "GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT": str(plugin),
        "GUIYI_OPENCLAW_STATE_DIR": str(state_dir),
        "GUIYI_OPENCLAW_CONFIG_PATH": str(config),
        "GUIYI_ALERT_CLAWBOT_RECIPIENTS_PATH": str(recipients),
    }
