from __future__ import annotations

from pathlib import Path
import os
import subprocess

import pytest


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


def test_web_runner_uses_installed_vite_without_pnpm_dependency_mutation() -> None:
    runner = (REPO_ROOT / "scripts" / "run-local-service.sh").read_text(encoding="utf-8")

    assert 'node_modules/vite/bin/vite.js" preview' in runner
    assert 'pnpm --dir "$PROJECT_ROOT/apps/quant-web" preview' not in runner


def test_after_market_launchd_template_uses_dedicated_runner() -> None:
    template = (
        REPO_ROOT / "deploy" / "launchd" / "com.guiyi.quant-after-market-scheduler.plist.template"
    ).read_text(encoding="utf-8")

    assert "run-after-market-scheduler.sh" in template
    assert "run-local-service.sh" not in template


def _run_python_service_runner(
    tmp_path: Path,
    runner_name: str,
    service: str,
    *,
    create_python: bool = True,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    project_root = tmp_path / "project"
    python_bin = project_root / "services" / "quant-api" / ".venv" / "bin" / "python"
    python_bin.parent.mkdir(parents=True)
    (project_root / "packages" / "quant-core").mkdir(parents=True)
    if create_python:
        python_bin.write_text(
            '#!/bin/sh\nprintf "EXECUTABLE=python\\nARGV=%s\\nPYTHONPATH=%s\\nREDIS_URL=%s\\n" '
            '"$*" "$PYTHONPATH" "$REDIS_URL"\n',
            encoding="utf-8",
        )
        python_bin.chmod(0o755)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    approval = tmp_path / "approval.json"
    approval.write_text("{}\n", encoding="utf-8")
    runtime_env = runtime / "project.env"
    runtime_env.write_text(
        "POSTGRES_PASSWORD=test-only\n"
        "GUIYI_LIVE_RUNTIME_ENABLED=true\n"
        "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=true\n"
        f"GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET={approval}\n"
        f"GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH={'a' * 64}\n",
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text(
        '#!/bin/sh\nprintf "EXECUTABLE=uv\\nARGV=%s\\nPYTHONPATH=%s\\nREDIS_URL=%s\\n" '
        '"$*" "$PYTHONPATH" "$REDIS_URL"\n',
        encoding="utf-8",
    )
    uv.chmod(0o755)
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / runner_name), service],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "GUIYI_PROJECT_ROOT": str(project_root),
            "GUIYI_RUNTIME_DIR": str(runtime),
            "GUIYI_RUNTIME_ENV": str(runtime_env),
        },
        capture_output=True,
        text=True,
    )
    return result, project_root


def test_shared_python_service_runner_exports_quant_core_path(tmp_path) -> None:
    result, project_root = _run_python_service_runner(tmp_path, "run-local-service.sh", "api")

    assert result.returncode == 0, result.stderr
    assert str(project_root / "packages" / "quant-core") in result.stdout


def test_after_market_runner_exports_quant_core_path(tmp_path) -> None:
    result, project_root = _run_python_service_runner(tmp_path, "run-after-market-scheduler.sh", "")

    assert result.returncode == 0, result.stderr
    assert str(project_root / "packages" / "quant-core") in result.stdout


@pytest.mark.parametrize(
    ("service", "expected_args"),
    [
        ("api", "-m uvicorn app.main:app"),
        ("worker-backtests", "-m app.worker backtests"),
        ("worker-signals", "-m app.worker signals"),
        ("scheduler", "-m app.runtime_scheduler --run --confirm-live-write"),
    ],
)
def test_shared_python_services_exec_the_runtime_venv_interpreter(
    tmp_path: Path,
    service: str,
    expected_args: str,
) -> None:
    result, _ = _run_python_service_runner(tmp_path, "run-local-service.sh", service)

    assert result.returncode == 0, result.stderr
    assert "EXECUTABLE=python" in result.stdout
    assert "EXECUTABLE=uv" not in result.stdout
    assert f"ARGV={expected_args}" in result.stdout


def test_after_market_service_execs_the_runtime_venv_interpreter(tmp_path: Path) -> None:
    result, _ = _run_python_service_runner(tmp_path, "run-after-market-scheduler.sh", "")

    assert result.returncode == 0, result.stderr
    assert "EXECUTABLE=python" in result.stdout
    assert "EXECUTABLE=uv" not in result.stdout
    assert "ARGV=-m app.after_market_scheduler --run" in result.stdout


@pytest.mark.parametrize(
    ("runner_name", "service", "error_text"),
    [
        ("run-local-service.sh", "api", "runtime python unavailable"),
        ("run-after-market-scheduler.sh", "", "runtime_python_unavailable"),
    ],
)
def test_python_service_runners_fail_closed_without_runtime_interpreter(
    tmp_path: Path,
    runner_name: str,
    service: str,
    error_text: str,
) -> None:
    result, _ = _run_python_service_runner(
        tmp_path,
        runner_name,
        service,
        create_python=False,
    )

    assert result.returncode == 78
    assert error_text in result.stderr
    assert "EXECUTABLE=uv" not in result.stdout


def test_after_market_runner_normalizes_local_redis_url_from_runtime_password(tmp_path) -> None:
    project_root = tmp_path / "project"
    python_bin = project_root / "services" / "quant-api" / ".venv" / "bin" / "python"
    python_bin.parent.mkdir(parents=True)
    (project_root / "packages" / "quant-core").mkdir(parents=True)
    python_bin.write_text('#!/bin/sh\nprintf "%s\\n" "$REDIS_URL"\n', encoding="utf-8")
    python_bin.chmod(0o755)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    approval = tmp_path / "approval.json"
    approval.write_text("{}\n", encoding="utf-8")
    runtime_env = runtime / "project.env"
    runtime_env.write_text(
        "POSTGRES_PASSWORD=test-only\n"
        "REDIS_URL=redis://127.0.0.1:6379/0\n"
        "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=true\n"
        f"GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET={approval}\n"
        f"GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH={'a' * 64}\n",
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    uv.write_text('#!/bin/sh\nprintf "%s\\n" "$REDIS_URL"\n', encoding="utf-8")
    uv.chmod(0o755)

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "run-after-market-scheduler.sh")],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "GUIYI_PROJECT_ROOT": str(project_root),
            "GUIYI_RUNTIME_DIR": str(runtime),
            "GUIYI_RUNTIME_ENV": str(runtime_env),
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "redis://:test-only@127.0.0.1:6379/0"


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
