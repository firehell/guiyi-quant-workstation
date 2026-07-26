from __future__ import annotations

import argparse
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CREATED_AUDIT = (
    PROJECT_ROOT
    / "data/reports/jm_eod_incremental_s6_07"
    / "s607_20260722_f2219e44/final_audit.json"
)
DEFAULT_SUPERSEDED_AUDIT = (
    PROJECT_ROOT
    / "data/reports/jm_eod_incremental_s6_07"
    / "s607_20260723_00668660/final_audit.json"
)
DEFAULT_EXTERNAL_LINEAGE = (
    PROJECT_ROOT
    / "data/reports/htdy_trusted_report_x5_02"
    / "execution_input_snapshot.json"
)
COUNT_TABLES = (
    "after_market_scheduler_checkpoints",
    "backtest_orders",
    "backtest_reports",
    "backtest_tasks",
    "backtest_trades",
    "profile_active_bindings",
    "signal_events",
    "signal_notifications",
    "signal_scan_tasks",
    "strategy_signals",
)
FORBIDDEN_TABLES = (
    "backtest_orders",
    "backtest_reports",
    "backtest_tasks",
    "backtest_trades",
    "signal_events",
    "signal_notifications",
    "signal_scan_tasks",
    "strategy_signals",
)


class S607RecoveryGateError(RuntimeError):
    pass


def collect_current_facts(
    session: Any,
    *,
    runtime_root: Path,
) -> dict[str, Any]:
    from sqlalchemy import text

    database = {
        "database": str(session.scalar(text("SELECT current_database()"))),
        "oid": int(
            session.scalar(
                text("SELECT oid FROM pg_database WHERE datname=current_database()")
            )
        ),
        "revision": str(
            session.scalar(text("SELECT version_num FROM alembic_version"))
            or ""
        ),
    }
    row_counts = {
        table: int(
            session.scalar(text(f'SELECT count(*) FROM "{table}"')) or 0
        )
        for table in COUNT_TABLES
    }
    state = {
        "active_profile_bindings_sha256": _query_hash(
            session,
            (
                'SELECT * FROM "profile_active_bindings" '
                "WHERE binding_status='active' ORDER BY id"
            ),
        ),
        "forbidden_table_sha256": {
            table: _query_hash(
                session,
                f'SELECT * FROM "{table}" ORDER BY id',
            )
            for table in FORBIDDEN_TABLES
        },
        "task_23_sha256": _query_hash(
            session,
            'SELECT * FROM "backtest_tasks" WHERE id=23 ORDER BY id',
        ),
        "report_15_sha256": _query_hash(
            session,
            'SELECT * FROM "backtest_reports" WHERE id=15 ORDER BY id',
        ),
        "report_14": {
            "md5": session.scalar(
                text(
                    "SELECT md5(to_jsonb(t)::text) "
                    "FROM backtest_reports t WHERE id=14"
                )
            ),
            "trades": int(
                session.scalar(
                    text(
                        "SELECT count(*) FROM backtest_trades "
                        "WHERE report_id=14"
                    )
                )
                or 0
            ),
            "orders": int(
                session.scalar(
                    text(
                        "SELECT count(*) FROM backtest_orders "
                        "WHERE report_id=14"
                    )
                )
                or 0
            ),
        },
    }
    return {
        "database": database,
        "row_counts": row_counts,
        "runtime": _git_identity(runtime_root),
        "state": state,
    }


def prepare_recovery_packet(
    *,
    session: Any,
    runtime_root: Path,
    backup_root: Path,
    drill_receipt_path: Path,
    completion_snapshot_path: Path,
    recovered_at: str,
    created_audit_path: Path = DEFAULT_CREATED_AUDIT,
    superseded_audit_path: Path = DEFAULT_SUPERSEDED_AUDIT,
    external_lineage_path: Path = DEFAULT_EXTERNAL_LINEAGE,
) -> dict[str, Any]:
    from app.services.s607_database_recovery import (
        build_recovery_approval_packet,
        build_semantic_recovery_manifest,
        derive_semantic_recovery_rows,
    )
    from scripts.backup.database_only_drill import (
        verify_database_only_backup,
    )

    current_facts = collect_current_facts(
        session,
        runtime_root=runtime_root,
    )
    created_audit = _read_json(created_audit_path)
    superseded_audit = _read_json(superseded_audit_path)
    completion_snapshot = _read_json(completion_snapshot_path)
    external_lineage = _read_json(external_lineage_path)
    completion_sha256 = _sha256_file(completion_snapshot_path)
    profile_rows, checkpoint = derive_semantic_recovery_rows(
        created_audit=created_audit,
        superseded_audit=superseded_audit,
        completion_snapshot=completion_snapshot,
        completion_snapshot_sha256=completion_sha256,
        recovered_at=recovered_at,
    )
    artifact = verify_database_only_backup(backup_root)
    drill = _read_json(drill_receipt_path)
    if (
        drill.get("status") != "passed"
        or drill.get("cleanup_complete") is not True
        or drill.get("backup_manifest_sha256")
        != artifact.manifest_sha256
        or drill.get("dump_sha256")
        != artifact.manifest["database"]["dump"]["sha256"]
        or drill.get("alembic_revision") != "20260721_0025"
    ):
        raise S607RecoveryGateError("isolated_restore_drill_invalid")
    evidence = {
        "profile_bindings_created": _file_identity(created_audit_path),
        "profile_bindings_superseded": _file_identity(
            superseded_audit_path
        ),
        "scheduler_checkpoint": _file_identity(
            completion_snapshot_path
        ),
        "external_backtest_lineage": _file_identity(
            external_lineage_path
        ),
    }
    if (
        str(external_lineage.get("task_id")) not in {"23", "None"}
        and external_lineage.get("task", {}).get("id") != 23
    ):
        raise S607RecoveryGateError(
            "external_backtest_lineage_invalid"
        )
    manifest = build_semantic_recovery_manifest(
        current_facts=current_facts,
        profile_active_bindings=profile_rows,
        scheduler_checkpoint=checkpoint,
        evidence=evidence,
        backup={
            "path": str(artifact.root),
            "manifest_sha256": artifact.manifest_sha256,
            "dump_sha256": artifact.manifest["database"]["dump"][
                "sha256"
            ],
            "mode": "database-only",
        },
        isolated_restore_drill={
            "path": str(drill_receipt_path.resolve()),
            "sha256": _sha256_file(drill_receipt_path),
            "status": "passed",
            "cleanup_complete": True,
        },
        synthesized_fields={
            "profile_active_bindings[*].created_at": "activated_at",
            "profile_active_bindings[*].updated_at": "superseded_at",
            "after_market_scheduler_checkpoints.last_result": (
                "semantic_provenance"
            ),
            "after_market_scheduler_checkpoints.created_at": (
                "recovered_at"
            ),
            "after_market_scheduler_checkpoints.updated_at": (
                "recovered_at"
            ),
        },
        external_lineage_exception={
            "task_id": 23,
            "report_id": 15,
            "database_write": False,
            "evidence_sha256": evidence[
                "external_backtest_lineage"
            ]["sha256"],
        },
    )
    return build_recovery_approval_packet(
        manifest=manifest,
        source=_git_source(PROJECT_ROOT),
    )


def confirm_recovery(
    *,
    session: Any,
    packet: Mapping[str, Any],
    approval_hash: str,
    runtime_root: Path,
) -> dict[str, Any]:
    from sqlalchemy import text

    from app.services.s607_database_recovery import (
        apply_semantic_recovery,
    )

    session.execute(
        text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
    )
    session.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtext('S6-07-DATABASE-REVISION-DRIFT-RECOVERY'))"
        )
    )
    before = collect_current_facts(session, runtime_root=runtime_root)
    source = _git_source(PROJECT_ROOT)
    result = apply_semantic_recovery(
        session,
        packet=packet,
        approval_hash=approval_hash,
        current_facts=before,
        current_source=source,
    )
    after = collect_current_facts(session, runtime_root=runtime_root)
    _verify_post_recovery(before=before, after=after)
    return {
        "schema_version": 1,
        "task_id": "S6-07-DATABASE-REVISION-DRIFT-RECOVERY",
        "status": "completed",
        "packet_hash": approval_hash,
        "source": source,
        "result": result,
        "before": before,
        "after": after,
        "allowed_tables": [
            "profile_active_bindings",
            "after_market_scheduler_checkpoints",
        ],
        "forbidden_tables_unchanged": True,
        "report_14_unchanged": True,
        "task_23_report_15_database_write": False,
        "semantic_reconstruction": deepcopy(
            dict(packet["manifest"]["synthesized_fields"])
        ),
        "backup": deepcopy(dict(packet["manifest"]["backup"])),
        "isolated_restore_drill": deepcopy(
            dict(packet["manifest"]["isolated_restore_drill"])
        ),
        "external_lineage_exception": deepcopy(
            dict(packet["manifest"]["external_lineage_exception"])
        ),
    }


def _verify_post_recovery(
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> None:
    before_counts = before["row_counts"]
    after_counts = after["row_counts"]
    expected = dict(before_counts)
    expected["profile_active_bindings"] += 7
    expected["after_market_scheduler_checkpoints"] += 1
    if (
        after_counts != expected
        or after["database"] != before["database"]
        or after["runtime"] != before["runtime"]
        or after["state"]["active_profile_bindings_sha256"]
        != before["state"]["active_profile_bindings_sha256"]
        or after["state"]["forbidden_table_sha256"]
        != before["state"]["forbidden_table_sha256"]
        or after["state"]["task_23_sha256"]
        != before["state"]["task_23_sha256"]
        or after["state"]["report_15_sha256"]
        != before["state"]["report_15_sha256"]
        or after["state"]["report_14"] != before["state"]["report_14"]
    ):
        raise S607RecoveryGateError(
            "post_recovery_invariant_failed"
        )


def _query_hash(session: Any, query: str) -> str:
    from sqlalchemy import text

    rows = [dict(row) for row in session.execute(text(query)).mappings()]
    return _canonical_hash(rows)


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            default=_json_default,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        normalized = (
            value
            if value.tzinfo is not None
            else value.replace(tzinfo=UTC)
        )
        return normalized.isoformat(timespec="microseconds")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "as_tuple"):
        return format(value, "f")
    raise TypeError(type(value).__name__)


def _git_identity(root: Path) -> dict[str, Any]:
    status = _git(root, "status", "--porcelain", "--untracked-files=no")
    return {
        "commit": _git(root, "rev-parse", "HEAD").strip(),
        "tracked_status_sha256": hashlib.sha256(status.encode()).hexdigest(),
    }


def _git_source(root: Path) -> dict[str, Any]:
    return {
        "commit": _git(root, "rev-parse", "HEAD").strip(),
        "tree": _git(root, "rev-parse", "HEAD^{tree}").strip(),
    }


def _git(root: Path, *arguments: str) -> str:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise S607RecoveryGateError("git_fact_unavailable") from exc


def _file_identity(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve(strict=True)
    return {"path": str(resolved), "sha256": _sha256_file(resolved)}


def _read_json(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve(strict=True)
    if not stat.S_ISREG(resolved.lstat().st_mode):
        raise S607RecoveryGateError("evidence_file_invalid")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise S607RecoveryGateError("evidence_json_invalid") from exc
    if not isinstance(value, dict):
        raise S607RecoveryGateError("evidence_json_invalid")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    target = path.expanduser().resolve(strict=False)
    if target.exists() or target.is_symlink():
        raise S607RecoveryGateError("output_already_exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags, 0o600)
    try:
        payload = (
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode()
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare", action="store_true")
    action.add_argument("--verify", action="store_true")
    action.add_argument("--confirm", action="store_true")
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--packet-out", type=Path)
    parser.add_argument("--approval-packet", type=Path)
    parser.add_argument("--approval-hash")
    parser.add_argument("--receipt-out", type=Path)
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument("--drill-receipt", type=Path)
    parser.add_argument("--completion-snapshot", type=Path)
    parser.add_argument("--recovered-at")
    return parser


def main(arguments: list[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    from sqlalchemy import text

    from app.db.session import SessionLocal
    from app.services.s607_database_recovery import (
        canonical_hash,
        verify_recovery_approval_packet,
    )

    with SessionLocal() as session:
        try:
            if args.prepare:
                required = (
                    args.packet_out,
                    args.backup_root,
                    args.drill_receipt,
                    args.completion_snapshot,
                    args.recovered_at,
                )
                if any(value is None for value in required):
                    raise S607RecoveryGateError(
                        "prepare_argument_missing"
                    )
                session.execute(
                    text(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
                    )
                )
                session.execute(text("SET TRANSACTION READ ONLY"))
                packet = prepare_recovery_packet(
                    session=session,
                    runtime_root=args.runtime_root,
                    backup_root=args.backup_root,
                    drill_receipt_path=args.drill_receipt,
                    completion_snapshot_path=args.completion_snapshot,
                    recovered_at=args.recovered_at,
                )
                session.rollback()
                _write_create_only(args.packet_out, packet)
                output = {
                    "status": "approval_required",
                    "packet": str(args.packet_out.resolve()),
                    "packet_hash": packet["packet_hash"],
                    "writes_performed": False,
                }
            else:
                if args.approval_packet is None or not args.approval_hash:
                    raise S607RecoveryGateError(
                        "approval_argument_missing"
                    )
                packet = _read_json(args.approval_packet)
                if args.verify:
                    session.execute(
                        text(
                            "SET TRANSACTION ISOLATION LEVEL "
                            "REPEATABLE READ"
                        )
                    )
                    session.execute(text("SET TRANSACTION READ ONLY"))
                    facts = collect_current_facts(
                        session,
                        runtime_root=args.runtime_root,
                    )
                    verify_recovery_approval_packet(
                        packet,
                        approval_hash=args.approval_hash,
                        current_facts=facts,
                        current_source=_git_source(PROJECT_ROOT),
                    )
                    session.rollback()
                    output = {
                        "status": "verified",
                        "packet_hash": args.approval_hash,
                        "writes_performed": False,
                    }
                else:
                    if args.receipt_out is None:
                        raise S607RecoveryGateError(
                            "receipt_out_missing"
                        )
                    receipt = confirm_recovery(
                        session=session,
                        packet=packet,
                        approval_hash=args.approval_hash,
                        runtime_root=args.runtime_root,
                    )
                    receipt["completed_at"] = datetime.now(
                        UTC
                    ).isoformat(timespec="microseconds")
                    receipt["receipt_hash"] = canonical_hash(receipt)
                    session.commit()
                    _write_create_only(args.receipt_out, receipt)
                    output = {
                        "status": "completed",
                        "packet_hash": args.approval_hash,
                        "receipt": str(args.receipt_out.resolve()),
                        "receipt_hash": receipt["receipt_hash"],
                    }
        except Exception as exc:  # noqa: BLE001 - fail-closed CLI.
            session.rollback()
            print(
                json.dumps(
                    {
                        "status": "blocked",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                )
            )
            return 2
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
