from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import plistlib

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "jm_eod_automation_gate.py"
SPEC = importlib.util.spec_from_file_location("jm_eod_automation_gate_cli", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _api_runner_facts(tmp_path: Path, runtime_root: Path) -> dict[str, object]:
    destination = (tmp_path / "runtime-support" / "run-local-service.sh").resolve()
    plist_path = (tmp_path / "agents" / "com.guiyi.quant-api.plist").resolve()
    return {
        "source_relative_path": "scripts/run-local-service.sh",
        "source_sha256": "a" * 64,
        "destination_path": str(destination),
        "destination_sha256": "b" * 64,
        "launchd_plist_path": str(plist_path),
        "launchd_plist_sha256": "c" * 64,
        "launchd_label": "com.guiyi.quant-api",
        "launchd_program_arguments": ["/bin/bash", str(destination), "api"],
        "launchd_project_root": str(runtime_root.resolve()),
    }


def test_enable_packet_writer_is_create_only(tmp_path) -> None:
    path = tmp_path / "approval.json"
    MODULE._write_create_only(path, {"packet_hash": "a" * 64})

    assert json.loads(path.read_text(encoding="utf-8"))["packet_hash"] == "a" * 64
    with pytest.raises(FileExistsError, match="approval_packet_already_exists"):
        MODULE._write_create_only(path, {"packet_hash": "b" * 64})


def test_prepare_failure_redacts_unrecognized_exception_detail() -> None:
    assert MODULE._safe_error_type(RuntimeError("password=do-not-print")) == "RuntimeError"
    assert MODULE._safe_error_type(RuntimeError("tracked_worktree_not_clean")) == "tracked_worktree_not_clean"


def test_prepare_git_identity_does_not_bind_branch(monkeypatch, tmp_path) -> None:
    responses = {
        ("status", "--porcelain=v1", "--untracked-files=no"): "",
        ("rev-parse", "HEAD"): "1" * 40,
        ("branch", "--show-current"): "codex/s6-07-eod-automation",
    }

    class Result:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    monkeypatch.setattr(
        MODULE.subprocess,
        "run",
        lambda command, **kwargs: Result(responses[tuple(command[1:])]),
    )

    assert MODULE._git_identity(tmp_path) == {
        "commit": "1" * 40,
        "tracked_status_sha256": MODULE.EMPTY_SHA256,
    }


def test_runtime_tree_policy_rejects_untracked_code_and_bytecode_before_execution(monkeypatch, tmp_path) -> None:
    responses = {
        ("status", "--porcelain=v1", "--untracked-files=no"): "",
        (
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            "services",
            "packages",
            "scripts",
            "deploy",
        ): "services/quant-api/app/rogue.py",
        (
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "--",
            "services",
            "packages",
            "scripts",
            "deploy",
        ): "services/quant-api/.venv/bin/python\npackages/quant-core/pkg/__pycache__/x.pyc",
    }
    monkeypatch.setattr(MODULE, "_git_value", lambda _root, *args: responses[args])

    assert MODULE._runtime_tree_is_preparable(tmp_path) is False

    responses[
        (
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            "services",
            "packages",
            "scripts",
            "deploy",
        )
    ] = ""
    assert MODULE._runtime_tree_is_preparable(tmp_path) is True
    assert MODULE._runtime_tree_is_execution_clean(tmp_path) is False

    responses[
        (
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "--",
            "services",
            "packages",
            "scripts",
            "deploy",
        )
    ] = "services/quant-api/.venv/bin/python"
    assert MODULE._runtime_tree_is_execution_clean(tmp_path) is True


@pytest.mark.parametrize(
    ("returncode", "stderr", "expected"),
    (
        (0, "", True),
        (113, 'Could not find service "com.guiyi.quant-after-market-scheduler"', False),
    ),
)
def test_launchd_probe_distinguishes_loaded_and_absent(monkeypatch, returncode, stderr, expected) -> None:
    class Result:
        stdout = ""

        def __init__(self):
            self.returncode = returncode
            self.stderr = stderr

    monkeypatch.setattr(MODULE.subprocess, "run", lambda *args, **kwargs: Result())

    assert MODULE._after_market_scheduler_is_loaded() is expected


def test_launchd_probe_fails_closed_on_indeterminate_error(monkeypatch) -> None:
    class Result:
        returncode = 1
        stdout = ""
        stderr = "permission denied"

    monkeypatch.setattr(MODULE.subprocess, "run", lambda *args, **kwargs: Result())

    with pytest.raises(RuntimeError, match="after_market_scheduler_probe_failed"):
        MODULE._after_market_scheduler_is_loaded()


def test_launchd_probe_fails_closed_on_timeout(monkeypatch) -> None:
    monkeypatch.setattr(
        MODULE.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(MODULE.subprocess.TimeoutExpired("launchctl", 2)),
    )

    with pytest.raises(RuntimeError, match="after_market_scheduler_probe_failed"):
        MODULE._after_market_scheduler_is_loaded()


def test_runtime_python_artifact_purge_preserves_venv_and_removes_source_bytecode(tmp_path) -> None:
    source_cache = tmp_path / "services" / "quant-api" / "app" / "__pycache__"
    venv_cache = tmp_path / "services" / "quant-api" / ".venv" / "lib" / "__pycache__"
    source_cache.mkdir(parents=True)
    venv_cache.mkdir(parents=True)
    (source_cache / "unsafe.pyc").write_bytes(b"unsafe")
    (venv_cache / "managed.pyc").write_bytes(b"managed")

    MODULE._purge_runtime_python_artifacts(tmp_path)

    assert not source_cache.exists()
    assert (venv_cache / "managed.pyc").is_file()


def test_deployment_command_environment_disables_bytecode_for_real_import(tmp_path) -> None:
    (tmp_path / "deployment_probe.py").write_text("VALUE = 1\n", encoding="utf-8")

    MODULE.subprocess.run(
        (MODULE.sys.executable, "-c", "import deployment_probe"),
        cwd=tmp_path,
        env=MODULE._deployment_command_environment(),
        check=True,
    )

    assert not (tmp_path / "__pycache__").exists()


def test_api_health_rejects_stale_listener_even_with_valid_schema(monkeypatch, tmp_path) -> None:
    runner_facts = _api_runner_facts(tmp_path, tmp_path / "runtime")

    class Result:
        returncode = 0

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout
            self.stderr = ""

    def run(command, **kwargs):
        if command[0] == "launchctl":
            return Result("state = running\npid = 200\n")
        if command[0] == "lsof":
            return Result("100\n")
        if command[0] == "ps":
            return Result("100 1\n200 1\n")
        raise AssertionError(command)

    payload = b'{"components":{"after_market_scheduler":{"status":"disabled","enabled":false}}}'
    monkeypatch.setattr(MODULE.subprocess, "run", run)
    monkeypatch.setattr(MODULE.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(payload))

    assert MODULE._api_health_is_ready(runner_facts, previous_pid=199) is False


def test_api_health_accepts_listener_from_launchd_process_tree(monkeypatch, tmp_path) -> None:
    runner_facts = _api_runner_facts(tmp_path, tmp_path / "runtime")

    class Result:
        returncode = 0

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout
            self.stderr = ""

    def run(command, **kwargs):
        if command[0] == "launchctl":
            return Result(
                "state = running\npid = 200\n"
                f"{runner_facts['destination_path']}\n"
                f"GUIYI_PROJECT_ROOT => {runner_facts['launchd_project_root']}\n"
            )
        if command[0] == "lsof":
            return Result("201\n")
        if command[0] == "ps":
            return Result("200 1\n201 200\n")
        raise AssertionError(command)

    payload = b'{"components":{"after_market_scheduler":{"status":"disabled","enabled":false}}}'
    monkeypatch.setattr(MODULE.subprocess, "run", run)
    monkeypatch.setattr(MODULE.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(payload))

    assert MODULE._api_health_is_ready(runner_facts, previous_pid=199) is True


def test_api_health_rejects_loaded_job_contract_drift(monkeypatch, tmp_path) -> None:
    runner_facts = _api_runner_facts(tmp_path, tmp_path / "runtime")

    class Result:
        returncode = 0

        def __init__(self, stdout: str) -> None:
            self.stdout = stdout
            self.stderr = ""

    def run(command, **kwargs):
        if command[0] == "launchctl":
            return Result("state = running\npid = 200\n/wrong/runner.sh\nGUIYI_PROJECT_ROOT => /wrong\n")
        if command[0] == "lsof":
            return Result("200\n")
        if command[0] == "ps":
            return Result("200 1\n")
        raise AssertionError(command)

    payload = b'{"components":{"after_market_scheduler":{"status":"disabled","enabled":false}}}'
    monkeypatch.setattr(MODULE.subprocess, "run", run)
    monkeypatch.setattr(MODULE.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(payload))

    assert MODULE._api_health_is_ready(runner_facts, previous_pid=199) is False


def test_api_runner_binding_detects_destination_and_plist_drift(monkeypatch, tmp_path) -> None:
    source_root = tmp_path / "source"
    runtime_root = tmp_path / "runtime-root"
    runtime_dir = tmp_path / "runtime-support"
    agent_dir = tmp_path / "agents"
    for root in (source_root, runtime_root):
        (root / "scripts").mkdir(parents=True)
        (root / "scripts" / "run-local-service.sh").write_text("#!/bin/sh\n# new\n", encoding="utf-8")
    runtime_dir.mkdir()
    agent_dir.mkdir()
    destination = runtime_dir / "run-local-service.sh"
    destination.write_text("#!/bin/sh\n# old\n", encoding="utf-8")
    plist_path = agent_dir / "com.guiyi.quant-api.plist"
    with plist_path.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.guiyi.quant-api",
                "ProgramArguments": ["/bin/bash", str(destination), "api"],
                "EnvironmentVariables": {"GUIYI_PROJECT_ROOT": str(runtime_root)},
            },
            handle,
        )
    monkeypatch.setenv("GUIYI_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("GUIYI_LAUNCH_AGENT_DIR", str(agent_dir))

    facts = MODULE._collect_api_runner_bound_facts(source_root=source_root, runtime_root=runtime_root)
    assert facts["source_sha256"] == MODULE._sha256_file(source_root / "scripts" / "run-local-service.sh")
    assert facts["destination_sha256"] == MODULE._sha256_file(destination)
    assert facts["launchd_plist_sha256"] == MODULE._sha256_file(plist_path)

    destination.write_text("#!/bin/sh\n# drift\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="api_runner_bound_fact_drift"):
        MODULE._refresh_api_runner(runtime_root, facts)
    assert "drift" in destination.read_text(encoding="utf-8")


def test_api_runner_binding_rejects_non_api_plist_label(monkeypatch, tmp_path) -> None:
    source_root = tmp_path / "source"
    runtime_root = tmp_path / "runtime-root"
    runtime_dir = tmp_path / "runtime-support"
    agent_dir = tmp_path / "agents"
    (source_root / "scripts").mkdir(parents=True)
    (source_root / "scripts" / "run-local-service.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    runtime_dir.mkdir()
    agent_dir.mkdir()
    destination = runtime_dir / "run-local-service.sh"
    destination.write_text("#!/bin/sh\n", encoding="utf-8")
    plist_path = agent_dir / "com.guiyi.quant-api.plist"
    with plist_path.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.guiyi.quant-web",
                "ProgramArguments": ["/bin/bash", str(destination), "api"],
                "EnvironmentVariables": {"GUIYI_PROJECT_ROOT": str(runtime_root)},
            },
            handle,
        )
    monkeypatch.setenv("GUIYI_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("GUIYI_LAUNCH_AGENT_DIR", str(agent_dir))

    with pytest.raises(RuntimeError, match="api_runner_launchd_contract_invalid"):
        MODULE._collect_api_runner_bound_facts(source_root=source_root, runtime_root=runtime_root)


def test_api_reload_boots_out_only_api_and_bootstraps_bound_plist(tmp_path) -> None:
    runner_facts = _api_runner_facts(tmp_path, tmp_path / "runtime")
    destination = Path(str(runner_facts["destination_path"]))
    destination.parent.mkdir(parents=True)
    destination.write_text("#!/bin/sh\n", encoding="utf-8")
    runner_facts["source_sha256"] = MODULE._sha256_file(destination)
    plist_path = Path(str(runner_facts["launchd_plist_path"]))
    plist_path.parent.mkdir(parents=True)
    with plist_path.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.guiyi.quant-api",
                "ProgramArguments": runner_facts["launchd_program_arguments"],
                "EnvironmentVariables": {"GUIYI_PROJECT_ROOT": runner_facts["launchd_project_root"]},
            },
            handle,
        )
    runner_facts["launchd_plist_sha256"] = MODULE._sha256_file(plist_path)
    commands: list[tuple[str, ...]] = []

    class Result:
        def __init__(self, returncode: int, stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = ""
            self.stderr = stderr

    def run(command, **kwargs):
        commands.append(tuple(command))
        if command[1] == "print":
            return Result(113, 'Could not find service "com.guiyi.quant-api"')
        return Result(0)

    MODULE._reload_bound_api_service(runner_facts, command_runner=run)

    domain = f"gui/{MODULE.os.getuid()}"
    label = f"{domain}/com.guiyi.quant-api"
    assert commands == [
        ("launchctl", "bootout", label),
        ("launchctl", "print", label),
        ("launchctl", "enable", label),
        ("launchctl", "bootstrap", domain, runner_facts["launchd_plist_path"]),
    ]
    assert all("after-market" not in " ".join(command) for command in commands)


def test_api_reload_accepts_exact_absent_bootout_signature(tmp_path) -> None:
    runner_facts = _api_runner_facts(tmp_path, tmp_path / "runtime")
    destination = Path(str(runner_facts["destination_path"]))
    destination.parent.mkdir(parents=True)
    destination.write_text("#!/bin/sh\n", encoding="utf-8")
    runner_facts["source_sha256"] = MODULE._sha256_file(destination)
    plist_path = Path(str(runner_facts["launchd_plist_path"]))
    plist_path.parent.mkdir(parents=True)
    with plist_path.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.guiyi.quant-api",
                "ProgramArguments": runner_facts["launchd_program_arguments"],
                "EnvironmentVariables": {"GUIYI_PROJECT_ROOT": runner_facts["launchd_project_root"]},
            },
            handle,
        )
    runner_facts["launchd_plist_sha256"] = MODULE._sha256_file(plist_path)

    class Result:
        def __init__(self, returncode: int, stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = ""
            self.stderr = stderr

    def run(command, **kwargs):
        if command[1] == "bootout":
            return Result(3, "Boot-out failed: 3: No such process")
        if command[1] == "print":
            return Result(113, 'Could not find service "com.guiyi.quant-api"')
        return Result(0)

    MODULE._reload_bound_api_service(runner_facts, command_runner=run)


@pytest.mark.parametrize(
    ("failure_stage", "expected_error"),
    (
        ("bootout", "api_bootout_failed"),
        ("lingering", "api_bootout_timeout"),
        ("enable", "api_enable_failed"),
        ("bootstrap", "api_bootstrap_failed"),
    ),
)
def test_api_reload_fails_closed_at_each_launchd_stage(
    monkeypatch,
    tmp_path,
    failure_stage,
    expected_error,
) -> None:
    runner_facts = _api_runner_facts(tmp_path, tmp_path / "runtime")
    destination = Path(str(runner_facts["destination_path"]))
    destination.parent.mkdir(parents=True)
    destination.write_text("#!/bin/sh\n", encoding="utf-8")
    runner_facts["source_sha256"] = MODULE._sha256_file(destination)
    plist_path = Path(str(runner_facts["launchd_plist_path"]))
    plist_path.parent.mkdir(parents=True)
    with plist_path.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.guiyi.quant-api",
                "ProgramArguments": runner_facts["launchd_program_arguments"],
                "EnvironmentVariables": {"GUIYI_PROJECT_ROOT": runner_facts["launchd_project_root"]},
            },
            handle,
        )
    runner_facts["launchd_plist_sha256"] = MODULE._sha256_file(plist_path)

    class Result:
        def __init__(self, returncode: int, stderr: str = "") -> None:
            self.returncode = returncode
            self.stdout = ""
            self.stderr = stderr

    def run(command, **kwargs):
        action = command[1]
        if action == "bootout":
            return Result(1, "permission denied") if failure_stage == "bootout" else Result(0)
        if action == "print":
            if failure_stage == "lingering":
                return Result(0)
            return Result(113, 'Could not find service "com.guiyi.quant-api"')
        if action == "enable":
            return Result(1) if failure_stage == "enable" else Result(0)
        if action == "bootstrap":
            return Result(1) if failure_stage == "bootstrap" else Result(0)
        raise AssertionError(command)

    monkeypatch.setattr(MODULE.time, "sleep", lambda _seconds: None)
    with pytest.raises(RuntimeError, match=expected_error):
        MODULE._reload_bound_api_service(runner_facts, command_runner=run)


def test_api_reload_revalidates_plist_label_before_mutation(tmp_path) -> None:
    runner_facts = _api_runner_facts(tmp_path, tmp_path / "runtime")
    destination = Path(str(runner_facts["destination_path"]))
    destination.parent.mkdir(parents=True)
    destination.write_text("#!/bin/sh\n", encoding="utf-8")
    runner_facts["source_sha256"] = MODULE._sha256_file(destination)
    plist_path = Path(str(runner_facts["launchd_plist_path"]))
    plist_path.parent.mkdir(parents=True)
    with plist_path.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.guiyi.quant-web",
                "ProgramArguments": runner_facts["launchd_program_arguments"],
                "EnvironmentVariables": {"GUIYI_PROJECT_ROOT": runner_facts["launchd_project_root"]},
            },
            handle,
        )
    runner_facts["launchd_plist_sha256"] = MODULE._sha256_file(plist_path)
    commands: list[tuple[str, ...]] = []

    with pytest.raises(RuntimeError, match="api_reload_bound_fact_drift"):
        MODULE._reload_bound_api_service(
            runner_facts,
            command_runner=lambda command, **kwargs: commands.append(tuple(command)),
        )

    assert commands == []


def test_deployment_packet_binds_exact_migration_chain_and_rejects_tampering(
    tmp_path,
) -> None:
    from app.services.after_market_deployment import (
        DEPLOYMENT_TASK_ID,
        build_deployment_approval_packet,
        validate_deployment_approval_packet,
    )

    migrations = []
    for revision in ("20260712_0023", "20260718_0024", "20260721_0025"):
        path = tmp_path / f"{revision}.py"
        path.write_text(revision, encoding="utf-8")
        migrations.append(
            {
                "revision": revision,
                "path": str(path),
                "sha256": MODULE._sha256_file(path),
            }
        )
    backup = tmp_path / "schema.sql"
    backup.write_text("schema-only", encoding="utf-8")
    facts = {
        "source_git": {
            "commit": "2" * 40,
            "tracked_status_sha256": MODULE.EMPTY_SHA256,
        },
        "runtime": {
            "root": str(tmp_path / "runtime"),
            "current_commit": "1" * 40,
            "target_commit": "2" * 40,
            "tracked_status_sha256": MODULE.EMPTY_SHA256,
        },
        "database": {
            "driver": "postgresql+psycopg",
            "host": "localhost",
            "database": "guiyi",
            "alembic_revision": "20260712_0022",
        },
        "deployment_mode": "schema_upgrade",
        "migration_chain": migrations,
        "schema_backup": {"path": str(backup), "sha256": MODULE._sha256_file(backup)},
        "row_counts": {
            "backtest_tasks": 23,
            "backtest_reports": 15,
            "signal_scan_tasks": 5,
            "strategy_signals": 5,
            "signal_events": 3,
        },
        "checkpoint_row_count": 0,
        "api_runner": _api_runner_facts(tmp_path, tmp_path / "runtime"),
    }
    packet = build_deployment_approval_packet(bound_facts=facts)

    assert packet["task_id"] == DEPLOYMENT_TASK_ID
    assert "schema_only_alembic_upgrade_0022_to_0025" in packet["allowed_operations"]
    assert (
        validate_deployment_approval_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_bound_facts=facts,
        )["packet_hash"]
        == packet["packet_hash"]
    )

    tampered = {
        **facts,
        "migration_chain": [*migrations[:-1], {**migrations[-1], "sha256": "0" * 64}],
    }
    with pytest.raises(RuntimeError, match="deployment_bound_fact_drift"):
        validate_deployment_approval_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_bound_facts=tampered,
        )

    dirty_runtime = {
        **facts,
        "runtime": {**facts["runtime"], "tracked_status_sha256": "0" * 64},
    }
    with pytest.raises(RuntimeError, match="deployment_runtime_identity_invalid"):
        build_deployment_approval_packet(bound_facts=dirty_runtime)


def test_code_only_deployment_packet_requires_0025_and_empty_migration_chain(
    tmp_path,
) -> None:
    from app.services.after_market_deployment import build_deployment_approval_packet

    backup = tmp_path / "schema.sql"
    backup.write_text("schema-only", encoding="utf-8")
    facts = {
        "source_git": {
            "commit": "2" * 40,
            "tracked_status_sha256": MODULE.EMPTY_SHA256,
        },
        "runtime": {
            "root": str(tmp_path / "runtime"),
            "current_commit": "1" * 40,
            "target_commit": "2" * 40,
            "tracked_status_sha256": MODULE.EMPTY_SHA256,
        },
        "database": {
            "driver": "postgresql+psycopg",
            "host": "localhost",
            "database": "guiyi",
            "alembic_revision": "20260721_0025",
        },
        "deployment_mode": "code_only",
        "migration_chain": [],
        "schema_backup": {"path": str(backup), "sha256": MODULE._sha256_file(backup)},
        "row_counts": {
            "backtest_tasks": 23,
            "backtest_reports": 15,
            "signal_scan_tasks": 5,
            "strategy_signals": 5,
            "signal_events": 3,
        },
        "checkpoint_row_count": 4,
        "api_runner": _api_runner_facts(tmp_path, tmp_path / "runtime"),
    }

    packet = build_deployment_approval_packet(bound_facts=facts)

    assert packet["bound_facts"]["deployment_mode"] == "code_only"
    assert "schema_only_alembic_upgrade_0022_to_0025" not in packet["allowed_operations"]
    assert "preserve_database_revision_0025" in packet["allowed_operations"]
    assert (
        "refresh_hash_bound_shared_python_runner_without_restarting_other_labels"
        in packet["allowed_operations"]
    )

    invalid_revision = {
        **facts,
        "database": {**facts["database"], "alembic_revision": "20260712_0022"},
    }
    with pytest.raises(RuntimeError, match="deployment_database_identity_invalid"):
        build_deployment_approval_packet(bound_facts=invalid_revision)

    invalid_chain = {
        **facts,
        "migration_chain": [
            {
                "revision": "20260721_0025",
                "path": str(tmp_path / "0025.py"),
                "sha256": "0" * 64,
            }
        ],
    }
    with pytest.raises(RuntimeError, match="deployment_migration_chain_invalid"):
        build_deployment_approval_packet(bound_facts=invalid_chain)


def test_recovery_schema_deployment_packet_binds_checkpoint_evidence(tmp_path) -> None:
    from app.services.after_market_deployment import (
        CHECKPOINT_RECOVERY_MODE,
        build_deployment_approval_packet,
    )

    migrations = []
    for revision in ("20260712_0023", "20260718_0024", "20260721_0025"):
        path = tmp_path / f"{revision}.py"
        path.write_text(revision, encoding="utf-8")
        migrations.append(
            {"revision": revision, "path": str(path), "sha256": MODULE._sha256_file(path)}
        )
    backup = tmp_path / "schema.sql"
    backup.write_text("schema-only", encoding="utf-8")
    receipt = tmp_path / "receipt.json"
    outage = tmp_path / "outage.json"
    failed_packet = tmp_path / "failed_packet.json"
    for path in (receipt, outage, failed_packet):
        path.write_text("{}", encoding="utf-8")
    recovery = {
        "schema_version": 1,
        "restore_state": {
            "product": "jm",
            "exchange_code": "DCE",
            "status": "blocked",
            "authorization_hash": "a" * 64,
            "last_successful_trading_day": "2026-07-23",
            "current_trading_day": "2026-07-24",
            "last_attempt_at": "2026-07-24T09:18:37+00:00",
            "last_success_at": None,
            "next_retry_at": None,
            "retry_count": 1,
            "last_error_type": "ValueError",
            "last_error_at": "2026-07-24T09:18:38+00:00",
            "last_execution_packet_hash": "b" * 64,
            "last_receipt_path": str(receipt),
        },
        "evidence": {
            "last_success_receipt": {
                "path": str(receipt),
                "sha256": MODULE._sha256_file(receipt),
                "packet_hash": "b" * 64,
            },
            "outage_snapshot": {"path": str(outage), "sha256": MODULE._sha256_file(outage)},
            "failed_execution_packet": {
                "path": str(failed_packet),
                "sha256": MODULE._sha256_file(failed_packet),
                "packet_hash": "c" * 64,
            },
            "failed_download_task": {
                "task_no": "archive:s607:jm:JM2609:2026-07-24:cccccccccccc",
                "error_type": "ValueError",
                "attempt_count": 1,
                "started_at": "2026-07-24T09:18:37+00:00",
                "finished_at": "2026-07-24T09:18:38+00:00",
            },
        },
        "database_verification": {
            "asset_count": 6,
            "active_binding_count": 7,
            "asset_identity_sha256": "d" * 64,
            "active_binding_identity_sha256": "e" * 64,
            "forbidden_counts": {
                "signal_events": 3,
                "signal_notifications": 1,
                "signal_scan_tasks": 5,
                "strategy_signals": 5,
            },
        },
    }
    facts = {
        "source_git": {"commit": "2" * 40, "tracked_status_sha256": MODULE.EMPTY_SHA256},
        "runtime": {
            "root": str(tmp_path / "runtime"),
            "current_commit": "1" * 40,
            "target_commit": "2" * 40,
            "tracked_status_sha256": MODULE.EMPTY_SHA256,
        },
        "database": {
            "driver": "postgresql+psycopg",
            "host": "localhost",
            "database": "guiyi",
            "alembic_revision": "20260712_0022",
        },
        "deployment_mode": CHECKPOINT_RECOVERY_MODE,
        "migration_chain": migrations,
        "schema_backup": {"path": str(backup), "sha256": MODULE._sha256_file(backup)},
        "row_counts": {
            "backtest_tasks": 23,
            "backtest_reports": 15,
            "signal_scan_tasks": 5,
            "strategy_signals": 5,
            "signal_events": 3,
        },
        "checkpoint_row_count": 0,
        "checkpoint_recovery": recovery,
        "api_runner": _api_runner_facts(tmp_path, tmp_path / "runtime"),
    }

    packet = build_deployment_approval_packet(bound_facts=facts)

    assert "restore_single_blocked_checkpoint_from_bound_evidence" in packet["allowed_operations"]
    assert packet["bound_facts"]["checkpoint_recovery"] == recovery

    tampered = {
        **facts,
        "checkpoint_recovery": {
            **recovery,
            "restore_state": {**recovery["restore_state"], "current_trading_day": "2026-07-25"},
        },
    }
    with pytest.raises(RuntimeError, match="deployment_checkpoint_recovery_invalid"):
        build_deployment_approval_packet(bound_facts=tampered)

    recovery_only = {
        **facts,
        "database": {**facts["database"], "alembic_revision": "20260721_0025"},
        "deployment_mode": "checkpoint_recovery_only",
        "migration_chain": [],
    }
    recovery_only_packet = build_deployment_approval_packet(bound_facts=recovery_only)
    assert "preserve_database_revision_0025" in recovery_only_packet["allowed_operations"]
    assert (
        "restore_single_blocked_checkpoint_from_bound_evidence"
        in recovery_only_packet["allowed_operations"]
    )


def test_collect_deployment_bound_facts_selects_code_only_for_0025(monkeypatch, tmp_path) -> None:
    from app.services.after_market_deployment import ROW_COUNT_TABLES

    source_root = tmp_path / "source"
    runtime_root = tmp_path / "runtime"
    source_root.mkdir()
    runtime_root.mkdir()
    backup = tmp_path / "schema.sql"
    backup.write_text("schema-only", encoding="utf-8")
    commits = iter(("2" * 40, "1" * 40))
    monkeypatch.setattr(
        MODULE,
        "_git_identity",
        lambda _root: {
            "commit": next(commits),
            "tracked_status_sha256": MODULE.EMPTY_SHA256,
        },
    )
    monkeypatch.setattr(MODULE, "_alembic_revision", lambda _session: "20260721_0025")
    monkeypatch.setattr(MODULE, "_runtime_tree_is_preparable", lambda _root: True)
    monkeypatch.setattr(
        MODULE,
        "_collect_api_runner_bound_facts",
        lambda **_kwargs: _api_runner_facts(tmp_path, runtime_root),
    )

    class Url:
        drivername = "postgresql+psycopg"
        host = "localhost"
        port = 5432
        database = "guiyi"

    class Bind:
        url = Url()

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

    class Session:
        def get_bind(self):
            return Bind()

        def execute(self, statement):
            sql = str(statement)
            if "after_market_scheduler_checkpoints" in sql:
                return Result(4)
            table = next(table for table in ROW_COUNT_TABLES if table in sql)
            return Result(ROW_COUNT_TABLES.index(table) + 1)

    facts = MODULE.collect_deployment_bound_facts(
        Session(),
        source_root=source_root,
        runtime_root=runtime_root,
        schema_backup=backup,
    )

    assert facts["deployment_mode"] == "code_only"
    assert facts["database"]["alembic_revision"] == "20260721_0025"
    assert facts["migration_chain"] == []
    assert facts["checkpoint_row_count"] == 4


def test_deployment_cli_exposes_fixed_modes() -> None:
    for option, field in (
        ("--prepare-deploy-packet", "prepare_deploy_packet"),
        ("--verify-deploy-packet", "verify_deploy_packet"),
        ("--confirm-deploy", "confirm_deploy"),
    ):
        args = MODULE.parse_args(
            [
                option,
                "--runtime-root",
                "/tmp/runtime",
                "--schema-backup",
                "/tmp/schema.sql",
                "--approval-packet",
                "/tmp/packet.json",
                "--approval-hash",
                "a" * 64,
            ]
        )
        assert getattr(args, field) is True


def test_deployment_cli_exposes_htdy_code_only_rebind_modes() -> None:
    prepared = MODULE.parse_args(
        [
            "--prepare-code-rebind-packet",
            "--deployment-packet",
            "/tmp/deployment.json",
            "--target-runtime-commit",
            "1" * 40,
            "--s6-07-final-receipt",
            "/tmp/completion_receipt.json",
            "--packet-out",
            "/tmp/rebind.json",
        ]
    )
    assert prepared.prepare_code_rebind_packet is True

    verified = MODULE.parse_args(
        [
            "--verify-code-rebind-packet",
            "--deployment-packet",
            "/tmp/deployment.json",
            "--s6-07-final-receipt",
            "/tmp/completion_receipt.json",
            "--approval-packet",
            "/tmp/rebind.json",
            "--approval-hash",
            "a" * 64,
        ]
    )
    assert verified.verify_code_rebind_packet is True


def test_confirmed_deployment_uses_exact_revision_and_restarts_only_api(tmp_path, monkeypatch) -> None:
    from app.services.after_market_deployment import ROW_COUNT_TABLES

    target = "2" * 40
    row_counts = {table: index for index, table in enumerate(ROW_COUNT_TABLES, start=1)}
    packet = {
        "task_id": "JM-EOD-INCREMENTAL-AUTOMATION-S6-07-DEPLOY",
        "packet_hash": "a" * 64,
        "bound_facts": {
            "runtime": {"root": str(tmp_path / "runtime"), "target_commit": target},
            "deployment_mode": "schema_upgrade",
            "row_counts": row_counts,
            "checkpoint_row_count": 0,
            "api_runner": _api_runner_facts(tmp_path, tmp_path / "runtime"),
        },
    }
    (tmp_path / "runtime" / "services" / "quant-api").mkdir(parents=True)

    class Result:
        def __init__(self, value):
            self.value = value

        def scalars(self):
            return self

        def all(self):
            return ["20260721_0025"]

        def scalar_one(self):
            return self.value

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, statement):
            sql = str(statement)
            if "alembic_version" in sql:
                return Result(None)
            if "after_market_scheduler_checkpoints" in sql:
                return Result(0)
            table = next(table for table in ROW_COUNT_TABLES if table in sql)
            return Result(row_counts[table])

        def rollback(self):
            return None

    commands: list[tuple[str, ...]] = []
    command_environments: list[dict[str, str] | None] = []
    monkeypatch.setattr(
        MODULE,
        "_git_identity",
        lambda _root: {"commit": target, "tracked_status_sha256": MODULE.EMPTY_SHA256},
    )
    receipt_path = tmp_path / "deployment_receipt.json"
    launchd_checks: list[None] = []
    execution_checks: list[int] = []
    api_reload_facts: list[dict[str, object]] = []

    def scheduler_loaded() -> bool:
        launchd_checks.append(None)
        return False

    def execution_clean(_root) -> bool:
        execution_checks.append(len(commands))
        return True

    def run_command(command, **kwargs) -> None:
        commands.append(tuple(command))
        command_environments.append(kwargs.get("env"))

    receipt = MODULE._execute_confirmed_deployment(
        packet=packet,
        session_factory=lambda: Session(),
        receipt_out=receipt_path,
        command_runner=run_command,
        runtime_preflight_probe=lambda _root: True,
        runtime_execution_probe=execution_clean,
        runtime_sanitizer=lambda _root: None,
        launchd_probe=scheduler_loaded,
        api_runner_refresher=lambda _root, _facts: None,
        api_pid_probe=lambda: 100,
        api_service_reloader=lambda facts: api_reload_facts.append(facts),
        api_readiness_probe=lambda _facts, _previous_pid: True,
    )

    assert commands[2] == (
        "uv",
        "venv",
        "--clear",
        str(tmp_path / "runtime" / "services" / "quant-api" / ".venv"),
    )
    assert ("alembic", "upgrade", "20260721_0025") == commands[4][-3:]
    assert command_environments[4]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert execution_checks[:2] == [0, 4]
    assert all("after-market-scheduler" not in " ".join(command) for command in commands)
    assert api_reload_facts == [packet["bound_facts"]["api_runner"]]
    assert receipt["database_revision"] == "20260721_0025"
    assert receipt["after_market_scheduler_loaded"] is False
    assert receipt["api_health_verified"] is True
    assert receipt["shared_python_runner"]["other_labels_restarted"] is False
    assert len(launchd_checks) == 2
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["gate"] == ("JM_EOD_AUTOMATION_DEPLOYMENT_PASSED")


def test_confirmed_code_only_deployment_skips_alembic_and_preserves_checkpoint_count(tmp_path, monkeypatch) -> None:
    from app.services.after_market_deployment import ROW_COUNT_TABLES

    target = "3" * 40
    row_counts = {table: index for index, table in enumerate(ROW_COUNT_TABLES, start=1)}
    packet = {
        "task_id": "JM-EOD-INCREMENTAL-AUTOMATION-S6-07-DEPLOY",
        "packet_hash": "b" * 64,
        "bound_facts": {
            "runtime": {"root": str(tmp_path / "runtime"), "target_commit": target},
            "deployment_mode": "code_only",
            "row_counts": row_counts,
            "checkpoint_row_count": 4,
            "api_runner": _api_runner_facts(tmp_path, tmp_path / "runtime"),
        },
    }
    (tmp_path / "runtime" / "services" / "quant-api").mkdir(parents=True)

    class Result:
        def __init__(self, value):
            self.value = value

        def scalars(self):
            return self

        def all(self):
            return ["20260721_0025"]

        def scalar_one(self):
            return self.value

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, statement):
            sql = str(statement)
            if "alembic_version" in sql:
                return Result(None)
            if "after_market_scheduler_checkpoints" in sql:
                return Result(4)
            table = next(table for table in ROW_COUNT_TABLES if table in sql)
            return Result(row_counts[table])

        def rollback(self):
            return None

    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        MODULE,
        "_git_identity",
        lambda _root: {"commit": target, "tracked_status_sha256": MODULE.EMPTY_SHA256},
    )

    receipt = MODULE._execute_confirmed_deployment(
        packet=packet,
        session_factory=lambda: Session(),
        receipt_out=tmp_path / "code_only_receipt.json",
        command_runner=lambda command, **kwargs: commands.append(tuple(command)),
        runtime_preflight_probe=lambda _root: True,
        runtime_execution_probe=lambda _root: True,
        runtime_sanitizer=lambda _root: None,
        launchd_probe=lambda: False,
        api_runner_refresher=lambda _root, _facts: None,
        api_pid_probe=lambda: 100,
        api_service_reloader=lambda _facts: None,
        api_readiness_probe=lambda _facts, _previous_pid: True,
    )

    assert all("alembic" not in command for command in commands)
    assert receipt["deployment_mode"] == "code_only"
    assert receipt["migration_executed"] is False
    assert receipt["checkpoint_row_count"] == 4


def test_confirmed_recovery_deployment_migrates_then_restores_one_checkpoint(
    tmp_path,
    monkeypatch,
) -> None:
    from app.services.after_market_deployment import ROW_COUNT_TABLES

    target = "4" * 40
    row_counts = {table: index for index, table in enumerate(ROW_COUNT_TABLES, start=1)}
    recovery = {"restore_state": {"current_trading_day": "2026-07-24"}}
    packet = {
        "task_id": "JM-EOD-INCREMENTAL-AUTOMATION-S6-07-DEPLOY",
        "packet_hash": "d" * 64,
        "bound_facts": {
            "runtime": {"root": str(tmp_path / "runtime"), "target_commit": target},
            "deployment_mode": "schema_upgrade_with_checkpoint_recovery",
            "row_counts": row_counts,
            "checkpoint_row_count": 0,
            "checkpoint_recovery": recovery,
            "api_runner": _api_runner_facts(tmp_path, tmp_path / "runtime"),
        },
    }
    (tmp_path / "runtime" / "services" / "quant-api").mkdir(parents=True)
    state = {"checkpoint_count": 0, "committed": False}

    class Result:
        def __init__(self, value):
            self.value = value

        def scalars(self):
            return self

        def all(self):
            return ["20260721_0025"]

        def scalar_one(self):
            return self.value

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, statement):
            sql = str(statement)
            if "alembic_version" in sql:
                return Result(None)
            if "after_market_scheduler_checkpoints" in sql:
                return Result(state["checkpoint_count"])
            table = next(table for table in ROW_COUNT_TABLES if table in sql)
            return Result(row_counts[table])

        def commit(self):
            state["committed"] = True

        def rollback(self):
            return None

    commands: list[tuple[str, ...]] = []
    restores: list[dict[str, object]] = []
    monkeypatch.setattr(
        MODULE,
        "_git_identity",
        lambda _root: {"commit": target, "tracked_status_sha256": MODULE.EMPTY_SHA256},
    )

    def restore(_session, facts):
        restores.append(facts)
        state["checkpoint_count"] = 1

    receipt = MODULE._execute_confirmed_deployment(
        packet=packet,
        session_factory=lambda: Session(),
        receipt_out=tmp_path / "recovery_receipt.json",
        command_runner=lambda command, **kwargs: commands.append(tuple(command)),
        runtime_preflight_probe=lambda _root: True,
        runtime_execution_probe=lambda _root: True,
        runtime_sanitizer=lambda _root: None,
        launchd_probe=lambda: False,
        api_runner_refresher=lambda _root, _facts: None,
        api_pid_probe=lambda: 100,
        api_service_reloader=lambda _facts: None,
        api_readiness_probe=lambda _facts, _previous_pid: True,
        checkpoint_recovery_restorer=restore,
        checkpoint_recovery_verifier=lambda _session, facts: facts == recovery,
    )

    assert ("alembic", "upgrade", "20260721_0025") == commands[4][-3:]
    assert restores == [recovery]
    assert state["committed"] is True
    assert receipt["checkpoint_recovery_executed"] is True
    assert receipt["checkpoint_row_count"] == 1


def test_confirmed_deployment_requires_api_health_before_writing_receipt(tmp_path, monkeypatch) -> None:
    from app.services.after_market_deployment import ROW_COUNT_TABLES

    target = "3" * 40
    row_counts = {table: index for index, table in enumerate(ROW_COUNT_TABLES, start=1)}
    packet = {
        "task_id": "JM-EOD-INCREMENTAL-AUTOMATION-S6-07-DEPLOY",
        "packet_hash": "c" * 64,
        "bound_facts": {
            "runtime": {"root": str(tmp_path / "runtime"), "target_commit": target},
            "deployment_mode": "code_only",
            "row_counts": row_counts,
            "checkpoint_row_count": 0,
            "api_runner": _api_runner_facts(tmp_path, tmp_path / "runtime"),
        },
    }
    (tmp_path / "runtime" / "services" / "quant-api").mkdir(parents=True)

    class Result:
        def __init__(self, value):
            self.value = value

        def scalars(self):
            return self

        def all(self):
            return ["20260721_0025"]

        def scalar_one(self):
            return self.value

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, statement):
            sql = str(statement)
            if "alembic_version" in sql:
                return Result(None)
            if "after_market_scheduler_checkpoints" in sql:
                return Result(0)
            table = next(table for table in ROW_COUNT_TABLES if table in sql)
            return Result(row_counts[table])

        def rollback(self):
            return None

    monkeypatch.setattr(
        MODULE,
        "_git_identity",
        lambda _root: {"commit": target, "tracked_status_sha256": MODULE.EMPTY_SHA256},
    )
    receipt_path = tmp_path / "receipt.json"

    with pytest.raises(RuntimeError, match="api_health_check_failed"):
        MODULE._execute_confirmed_deployment(
            packet=packet,
            session_factory=lambda: Session(),
            receipt_out=receipt_path,
            command_runner=lambda command, **kwargs: None,
            runtime_preflight_probe=lambda _root: True,
            runtime_execution_probe=lambda _root: True,
            runtime_sanitizer=lambda _root: None,
            launchd_probe=lambda: False,
            api_runner_refresher=lambda _root, _facts: None,
            api_pid_probe=lambda: 100,
            api_service_reloader=lambda _facts: None,
            api_readiness_probe=lambda _facts, _previous_pid: False,
        )

    assert not receipt_path.exists()


def test_confirmed_deployment_rejects_dirty_runtime_before_any_command(tmp_path) -> None:
    packet = {
        "bound_facts": {
            "runtime": {"root": str(tmp_path / "runtime"), "target_commit": "3" * 40},
        }
    }
    commands: list[tuple[str, ...]] = []

    with pytest.raises(RuntimeError, match="runtime_worktree_not_clean"):
        MODULE._execute_confirmed_deployment(
            packet=packet,
            session_factory=lambda: None,
            receipt_out=tmp_path / "receipt.json",
            command_runner=lambda command, **kwargs: commands.append(tuple(command)),
            runtime_preflight_probe=lambda _root: False,
            runtime_execution_probe=lambda _root: True,
            runtime_sanitizer=lambda _root: None,
            launchd_probe=lambda: False,
        )

    assert commands == []
    assert not (tmp_path / "receipt.json").exists()


def test_confirmed_deployment_rejects_loaded_scheduler_before_any_command(tmp_path) -> None:
    packet = {
        "bound_facts": {
            "runtime": {"root": str(tmp_path / "runtime"), "target_commit": "3" * 40},
        }
    }
    commands: list[tuple[str, ...]] = []

    with pytest.raises(RuntimeError, match="after_market_scheduler_already_loaded"):
        MODULE._execute_confirmed_deployment(
            packet=packet,
            session_factory=lambda: None,
            receipt_out=tmp_path / "receipt.json",
            command_runner=lambda command, **kwargs: commands.append(tuple(command)),
            runtime_preflight_probe=lambda _root: True,
            runtime_execution_probe=lambda _root: True,
            runtime_sanitizer=lambda _root: None,
            launchd_probe=lambda: True,
        )

    assert commands == []
    assert not (tmp_path / "receipt.json").exists()


def test_confirmed_deployment_rechecks_tree_after_sync_before_alembic(tmp_path) -> None:
    packet = {
        "bound_facts": {
            "runtime": {"root": str(tmp_path / "runtime"), "target_commit": "3" * 40},
            "deployment_mode": "schema_upgrade",
        }
    }
    commands: list[tuple[str, ...]] = []
    execution_states = iter((True, False))

    with pytest.raises(RuntimeError, match="deployment_runtime_post_sync_identity_invalid"):
        MODULE._execute_confirmed_deployment(
            packet=packet,
            session_factory=lambda: None,
            receipt_out=tmp_path / "receipt.json",
            command_runner=lambda command, **kwargs: commands.append(tuple(command)),
            runtime_preflight_probe=lambda _root: True,
            runtime_execution_probe=lambda _root: next(execution_states),
            runtime_sanitizer=lambda _root: None,
            launchd_probe=lambda: False,
        )

    assert len(commands) == 4
    assert all("alembic" not in command for command in commands)
    assert not (tmp_path / "receipt.json").exists()
