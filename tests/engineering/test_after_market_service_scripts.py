from __future__ import annotations

from pathlib import Path
import os
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_after_market_has_dedicated_runner_and_installer() -> None:
    runner = REPO_ROOT / "scripts" / "run-after-market-scheduler.sh"
    installer = REPO_ROOT / "scripts" / "install-after-market-scheduler.sh"

    assert runner.is_file()
    assert installer.is_file()
    runner_text = runner.read_text(encoding="utf-8")
    installer_text = installer.read_text(encoding="utf-8")
    assert "project.env" in runner_text
    assert ".env" not in runner_text.replace("project.env", "")
    for mode in ("--render-only", "--confirm-load", "--bootout", "--disable"):
        assert mode in installer_text


def test_shared_service_scripts_do_not_manage_after_market_scheduler() -> None:
    runner = (REPO_ROOT / "scripts" / "run-local-service.sh").read_text(encoding="utf-8")
    installer = (REPO_ROOT / "scripts" / "install-local-services.sh").read_text(encoding="utf-8")

    assert "after-market-scheduler" not in runner
    assert "com.guiyi.quant-after-market-scheduler" not in installer


def test_after_market_launchd_template_uses_dedicated_runner() -> None:
    template = (
        REPO_ROOT / "deploy" / "launchd" / "com.guiyi.quant-after-market-scheduler.plist.template"
    ).read_text(encoding="utf-8")

    assert "run-after-market-scheduler.sh" in template
    assert "run-local-service.sh" not in template


def _run_python_service_runner(tmp_path: Path, runner_name: str, service: str) -> subprocess.CompletedProcess[str]:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    approval = tmp_path / "approval.json"
    approval.write_text("{}\n", encoding="utf-8")
    runtime_env = runtime / "project.env"
    runtime_env.write_text(
        "POSTGRES_PASSWORD=test-only\n"
        "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=true\n"
        f"GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET={approval}\n"
        f"GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH={'a' * 64}\n",
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text('#!/bin/sh\nprintf "%s\\n" "$PYTHONPATH"\n', encoding="utf-8")
    uv.chmod(0o755)
    return subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / runner_name), service],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "GUIYI_PROJECT_ROOT": str(REPO_ROOT),
            "GUIYI_RUNTIME_DIR": str(runtime),
            "GUIYI_RUNTIME_ENV": str(runtime_env),
        },
        capture_output=True,
        text=True,
    )


def test_shared_python_service_runner_exports_quant_core_path(tmp_path) -> None:
    result = _run_python_service_runner(tmp_path, "run-local-service.sh", "api")

    assert result.returncode == 0, result.stderr
    assert str(REPO_ROOT / "packages" / "quant-core") in result.stdout.strip().split(os.pathsep)


def test_after_market_runner_exports_quant_core_path(tmp_path) -> None:
    result = _run_python_service_runner(tmp_path, "run-after-market-scheduler.sh", "")

    assert result.returncode == 0, result.stderr
    assert str(REPO_ROOT / "packages" / "quant-core") in result.stdout.strip().split(os.pathsep)


def _run_installer(tmp_path: Path, mode: str) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    runtime_env = runtime / "project.env"
    runtime_env.write_text(
        "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=true\nUNCHANGED_SECRET=do-not-print-or-change\n",
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    launch_log = tmp_path / "launchctl.log"
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >>"{launch_log}"\n', encoding="utf-8")
    launchctl.chmod(0o755)
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GUIYI_RUNTIME_DIR": str(runtime),
        "GUIYI_RUNTIME_ENV": str(runtime_env),
        "GUIYI_LAUNCH_AGENT_DIR": str(tmp_path / "agents"),
        "GUIYI_LOG_DIR": str(tmp_path / "logs"),
    }
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "install-after-market-scheduler.sh"), mode],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    return result, runtime_env, launch_log


def test_bootout_only_stops_after_market_label_and_preserves_enable_flag(tmp_path) -> None:
    result, runtime_env, launch_log = _run_installer(tmp_path, "--bootout")

    assert result.returncode == 0, result.stderr
    assert runtime_env.read_text(encoding="utf-8") == (
        "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=true\nUNCHANGED_SECRET=do-not-print-or-change\n"
    )
    assert launch_log.read_text(encoding="utf-8").splitlines() == [
        f"bootout gui/{os.getuid()}/com.guiyi.quant-after-market-scheduler"
    ]
    assert "do-not-print-or-change" not in result.stdout + result.stderr


def test_disable_only_stops_after_market_label_and_atomically_closes_flag(tmp_path) -> None:
    result, runtime_env, launch_log = _run_installer(tmp_path, "--disable")

    assert result.returncode == 0, result.stderr
    assert runtime_env.read_text(encoding="utf-8") == (
        "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=false\nUNCHANGED_SECRET=do-not-print-or-change\n"
    )
    assert launch_log.read_text(encoding="utf-8").splitlines() == [
        f"bootout gui/{os.getuid()}/com.guiyi.quant-after-market-scheduler"
    ]
    assert "do-not-print-or-change" not in result.stdout + result.stderr


def test_enable_configuration_atomically_updates_only_three_keys(tmp_path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    runtime_env = runtime / "project.env"
    runtime_env.write_text(
        "UNCHANGED_SECRET=do-not-print-or-change\nGUIYI_AFTER_MARKET_AUTOMATION_ENABLED=false\n",
        encoding="utf-8",
    )
    packet = tmp_path / "enable.json"
    packet.write_text("{}\n", encoding="utf-8")
    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "scripts" / "configure-after-market-automation.sh"),
            "--enable",
            "--approval-packet",
            str(packet),
            "--approval-hash",
            "a" * 64,
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "GUIYI_RUNTIME_DIR": str(runtime), "GUIYI_RUNTIME_ENV": str(runtime_env)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    configured = runtime_env.read_text(encoding="utf-8")
    assert "UNCHANGED_SECRET=do-not-print-or-change" in configured
    assert "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=true" in configured
    assert f"GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET={packet}" in configured
    assert f"GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH={'a' * 64}" in configured
    assert "do-not-print-or-change" not in result.stdout + result.stderr
