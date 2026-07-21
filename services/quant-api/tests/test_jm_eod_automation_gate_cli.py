from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "jm_eod_automation_gate.py"
SPEC = importlib.util.spec_from_file_location("jm_eod_automation_gate_cli", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


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


def test_deployment_packet_binds_exact_migration_chain_and_rejects_tampering(tmp_path) -> None:
    from app.services.after_market_deployment import (
        DEPLOYMENT_TASK_ID,
        build_deployment_approval_packet,
        validate_deployment_approval_packet,
    )

    migrations = []
    for revision in ("20260712_0023", "20260718_0024", "20260721_0025"):
        path = tmp_path / f"{revision}.py"
        path.write_text(revision, encoding="utf-8")
        migrations.append({"revision": revision, "path": str(path), "sha256": MODULE._sha256_file(path)})
    backup = tmp_path / "schema.sql"
    backup.write_text("schema-only", encoding="utf-8")
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
        "migration_chain": migrations,
        "schema_backup": {"path": str(backup), "sha256": MODULE._sha256_file(backup)},
        "row_counts": {
            "backtest_tasks": 23,
            "backtest_reports": 15,
            "signal_scan_tasks": 5,
            "strategy_signals": 5,
            "signal_events": 3,
        },
    }
    packet = build_deployment_approval_packet(bound_facts=facts)

    assert packet["task_id"] == DEPLOYMENT_TASK_ID
    assert validate_deployment_approval_packet(
        packet,
        approval_hash=packet["packet_hash"],
        current_bound_facts=facts,
    )["packet_hash"] == packet["packet_hash"]

    tampered = {**facts, "migration_chain": [*migrations[:-1], {**migrations[-1], "sha256": "0" * 64}]}
    with pytest.raises(RuntimeError, match="deployment_bound_fact_drift"):
        validate_deployment_approval_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_bound_facts=tampered,
        )


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


def test_confirmed_deployment_uses_exact_revision_and_restarts_only_api(tmp_path, monkeypatch) -> None:
    from app.services.after_market_deployment import ROW_COUNT_TABLES

    target = "2" * 40
    row_counts = {table: index for index, table in enumerate(ROW_COUNT_TABLES, start=1)}
    packet = {
        "task_id": "JM-EOD-INCREMENTAL-AUTOMATION-S6-07-DEPLOY",
        "packet_hash": "a" * 64,
        "bound_facts": {
            "runtime": {"root": str(tmp_path / "runtime"), "target_commit": target},
            "row_counts": row_counts,
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
    monkeypatch.setattr(
        MODULE,
        "_git_identity",
        lambda _root: {"commit": target, "tracked_status_sha256": MODULE.EMPTY_SHA256},
    )
    receipt_path = tmp_path / "deployment_receipt.json"

    receipt = MODULE._execute_confirmed_deployment(
        packet=packet,
        session_factory=lambda: Session(),
        receipt_out=receipt_path,
        command_runner=lambda command, **kwargs: commands.append(tuple(command)),
    )

    assert ("alembic", "upgrade", "20260721_0025") == commands[3][-3:]
    assert commands[-1] == (
        "launchctl",
        "kickstart",
        "-k",
        f"gui/{MODULE.os.getuid()}/com.guiyi.quant-api",
    )
    assert all("after-market-scheduler" not in " ".join(command) for command in commands)
    assert receipt["database_revision"] == "20260721_0025"
    assert receipt["after_market_scheduler_loaded"] is False
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["gate"] == (
        "JM_EOD_AUTOMATION_DEPLOYMENT_PASSED"
    )
