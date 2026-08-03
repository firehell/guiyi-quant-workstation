from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.backtest.htdy_trusted_report import file_sha256, packet_hash
from app.backtest.service import BacktestService
from app.backtest.trust_audit import build_backtest_trust_audit
from app.models.backtest import BacktestOrderModel, BacktestReportModel, BacktestTask, BacktestTradeModel
from app.models.data_center import ProfileActiveBinding, utc_now
from guiyi_quant.strategies.huotian_dayou_strict import STRATEGY_CLASS_PATH, validate_params


TASK_ID = "HTDY-TRUSTED-BACKTEST-CANDIDATE-X503"
SUCCESS_GATE = "HTDY_TRUSTED_BACKTEST_CANDIDATE"
FAILURE_GATE = "HTDY_TRUST_AUDIT_FAILED_REVIEW_REQUIRED"
REPORT14_ID = 14
X502_GATE = "HTDY_TRUSTED_REPORT_APPLY_PACKET_READY"
RETIRED_GATE = "HTDY_X503_HISTORICAL_GATE_RETIRED"
RETIRED_MESSAGE = (
    "HTDY_X503_HISTORICAL_GATE_RETIRED: X5-03 is a frozen historical Gate and "
    "is not an active formal backtest creation path"
)

_ARTIFACT_FILES = {
    "execution_snapshot": "execution_input_snapshot.json",
    "canonical_cost_timeline": "canonical_cost_timeline.json",
    "full_window_dry_run": "full_window_dry_run.json",
    "preapply_audit": "preapply_audit.json",
}


class CandidateApplyError(RuntimeError):
    """Raised after a failed X5-03 transaction has been rolled back."""

    def __init__(self, message: str, *, failure: dict[str, Any]) -> None:
        super().__init__(message)
        self.failure = failure


def verify_packet_hash(value: Mapping[str, Any]) -> bool:
    payload = dict(value)
    expected = str(payload.pop("packet_hash", ""))
    return bool(expected) and expected == packet_hash(payload)


def load_x502_bundle(directory: Path) -> dict[str, Any]:
    root = directory.expanduser().resolve()
    packet_path = root / "HTDY_TRUSTED_REPORT_APPLY_PACKET.json"
    if not packet_path.is_file():
        raise CandidateApplyError(
            "X5-02 apply packet is missing",
            failure=_pretransaction_failure("X5-02 apply packet is missing"),
        )
    packet = _read_json(packet_path)
    if not verify_packet_hash(packet) or packet.get("gate") != X502_GATE:
        raise CandidateApplyError(
            "X5-02 apply packet hash or Gate is invalid",
            failure=_pretransaction_failure("X5-02 apply packet hash or Gate is invalid"),
        )

    artifacts = packet.get("artifacts") or {}
    payloads: dict[str, Any] = {}
    for name, expected_filename in _ARTIFACT_FILES.items():
        artifact = artifacts.get(name) or {}
        filename = str(artifact.get("path") or "")
        if filename != expected_filename or Path(filename).name != filename:
            raise CandidateApplyError(
                f"X5-02 artifact path is invalid: {name}",
                failure=_pretransaction_failure(f"X5-02 artifact path is invalid: {name}"),
            )
        path = root / filename
        if not path.is_file() or file_sha256(path) != artifact.get("sha256"):
            raise CandidateApplyError(
                f"X5-02 artifact hash is invalid: {name}",
                failure=_pretransaction_failure(f"X5-02 artifact hash is invalid: {name}"),
            )
        payloads[name] = _read_json(path)

    snapshot = payloads["execution_snapshot"]
    cost_timeline = payloads["canonical_cost_timeline"]
    dry_run = payloads["full_window_dry_run"]
    preapply_audit = payloads["preapply_audit"]
    logical_hashes = {
        "execution_snapshot_hash": snapshot.get("snapshot_hash"),
        "cost_timeline_hash": packet_hash(cost_timeline),
        "dry_run_hash": packet_hash(dry_run),
        "preapply_audit_hash": packet_hash(preapply_audit),
    }
    for field, actual in logical_hashes.items():
        if packet.get(field) != actual:
            raise CandidateApplyError(
                f"X5-02 logical artifact hash is invalid: {field}",
                failure=_pretransaction_failure(f"X5-02 logical artifact hash is invalid: {field}"),
            )
    if preapply_audit.get("audit_status") != "passed":
        raise CandidateApplyError(
            "X5-02 pre-apply audit is not passed",
            failure=_pretransaction_failure("X5-02 pre-apply audit is not passed"),
        )
    if snapshot.get("data_role") != "primary" or snapshot.get("quality_status") != "passed":
        raise CandidateApplyError(
            "X5-02 execution snapshot is not primary/passed",
            failure=_pretransaction_failure("X5-02 execution snapshot is not primary/passed"),
        )
    if snapshot.get("binding_status") != "active" or snapshot.get("quality_policy") != "passed_only":
        raise CandidateApplyError(
            "X5-02 execution snapshot binding is not active/passed-only",
            failure=_pretransaction_failure("X5-02 execution snapshot binding is not active/passed-only"),
        )
    if dry_run.get("protocol_hash") != packet.get("protocol_hash"):
        raise CandidateApplyError(
            "X5-02 protocol hash mismatch",
            failure=_pretransaction_failure("X5-02 protocol hash mismatch"),
        )
    if dry_run.get("parameter_hash") != packet.get("parameter_hash"):
        raise CandidateApplyError(
            "X5-02 parameter hash mismatch",
            failure=_pretransaction_failure("X5-02 parameter hash mismatch"),
        )
    if dry_run.get("execution_snapshot_hash") != snapshot.get("snapshot_hash"):
        raise CandidateApplyError(
            "X5-02 dry-run execution snapshot mismatch",
            failure=_pretransaction_failure("X5-02 dry-run execution snapshot mismatch"),
        )
    return {
        "packet": packet,
        "execution_snapshot": snapshot,
        "cost_timeline": cost_timeline,
        "dry_run": dry_run,
        "preapply_audit": preapply_audit,
    }


def apply_candidate_transaction(
    session_factory: Callable[[], Session],
    *,
    repo_root: Path,
    bundle: Mapping[str, Any],
    source_commit: str,
    report14_id: int = REPORT14_ID,
) -> dict[str, Any]:
    del session_factory, repo_root, bundle, source_commit, report14_id
    raise CandidateApplyError(
        RETIRED_MESSAGE,
        failure={
            "schema_version": "htdy_x503_historical_retired_v1",
            "task_id": TASK_ID,
            "gate": RETIRED_GATE,
            "status": "retired",
            "transaction": {"status": "not_started"},
            "database_accessed": False,
            "historical_evidence_mutated": False,
            "reason": RETIRED_MESSAGE,
        },
    )


def _retired_historical_apply_implementation(
    session_factory: Callable[[], Session],
    *,
    repo_root: Path,
    bundle: Mapping[str, Any],
    source_commit: str,
    report14_id: int = REPORT14_ID,
) -> dict[str, Any]:
    """Unreachable historical implementation retained only for evidence review."""
    raise CandidateApplyError(
        RETIRED_MESSAGE,
        failure={
            "schema_version": "htdy_x503_historical_retired_v1",
            "task_id": TASK_ID,
            "gate": RETIRED_GATE,
            "status": "retired",
            "transaction": {"status": "not_started"},
            "database_accessed": False,
            "historical_evidence_mutated": False,
            "reason": RETIRED_MESSAGE,
        },
    )
    before_counts: dict[str, int] = {}
    candidate_task_no: str | None = None
    report14_before: dict[str, Any] | None = None
    staged_result: dict[str, Any] | None = None
    failure_reason = "candidate transaction failed"
    try:
        if not repo_root.is_dir():
            raise ValueError("repository root is missing")
        with session_factory() as session:
            with session.begin():
                if session.bind is not None and session.bind.dialect.name == "postgresql":
                    session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
                before_counts = _table_counts(session)
                report14 = session.get(BacktestReportModel, report14_id)
                if report14 is None:
                    raise ValueError(f"report14 is missing: report_id={report14_id}")
                report14_before = _report_fingerprint(report14)
                report14_pre_audit = build_backtest_trust_audit(session, report_id=report14_id)
                if report14_pre_audit.get("audit_status") != "passed":
                    raise ValueError("report14 trust audit failed before candidate write")

                snapshot = dict(bundle.get("execution_snapshot") or {})
                dry_run = dict(bundle.get("dry_run") or {})
                packet = dict(bundle.get("packet") or {})
                _validate_bundle_identity(snapshot=snapshot, dry_run=dry_run, packet=packet)
                fixed_task_no = _candidate_task_no(str(packet.get("packet_hash") or ""))
                if session.scalar(select(BacktestTask.id).where(BacktestTask.task_no == fixed_task_no)) is not None:
                    raise ValueError("candidate already exists for the approved X5-02 packet")
                request = _formal_request(dry_run=dry_run, snapshot=snapshot)
                service = BacktestService(session)
                task = service.create_formal_task(
                    request,
                    server_context={
                        "stage5_task": TASK_ID,
                        "x502_packet_hash": packet.get("packet_hash"),
                        "protocol_hash": packet.get("protocol_hash"),
                        "parameter_hash": packet.get("parameter_hash"),
                        "execution_snapshot_hash": snapshot.get("snapshot_hash"),
                        "cost_timeline_hash": packet.get("cost_timeline_hash"),
                    },
                )
                task.task_no = fixed_task_no
                candidate_task_no = fixed_task_no
                _assert_task_binding(session, task=task, snapshot=snapshot)
                binding_snapshot = deepcopy(task.binding_snapshot or {})
                binding_snapshot["formal_execution_snapshot"] = deepcopy(snapshot)
                binding_snapshot["formal_execution_snapshot_hash"] = snapshot.get("snapshot_hash")
                task.binding_snapshot = binding_snapshot
                task.status = "running"
                task.progress = 50.0
                task.started_at = utc_now()

                service.persist_result(task, dry_run)
                task.status = "success"
                task.progress = 100.0
                task.completed_items = 1
                task.failed_items = 0
                task.finished_at = utc_now()
                service.sanitize_task_local_paths(task)
                session.flush()

                report_id = int(task.result_payload["report_id"])
                report = session.get(BacktestReportModel, report_id)
                if report is None:
                    raise ValueError("candidate report disappeared after flush")
                candidate_audit = build_backtest_trust_audit(session, report_id=report_id)
                if candidate_audit.get("audit_status") != "passed":
                    failure_reason = "candidate trust audit failed"
                    raise ValueError(failure_reason)
                report14_audit = build_backtest_trust_audit(session, report_id=report14_id)
                if report14_audit.get("audit_status") != "passed":
                    failure_reason = "report14 trust audit failed after candidate flush"
                    raise ValueError(failure_reason)
                report14_after = _report_fingerprint(session.get(BacktestReportModel, report14_id))
                if report14_before != report14_after:
                    failure_reason = "report14 changed inside candidate transaction"
                    raise ValueError(failure_reason)

                after_counts = _table_counts(session)
                expected_delta = {
                    "tasks": 1,
                    "reports": 1,
                    "trades": len(dry_run.get("trades") or []),
                    "orders": len(dry_run.get("orders") or []),
                }
                actual_delta = {key: after_counts[key] - before_counts[key] for key in before_counts}
                if actual_delta != expected_delta:
                    failure_reason = "candidate row count delta is not exact"
                    raise ValueError(f"{failure_reason}: expected={expected_delta} actual={actual_delta}")
                staged_result = _transaction_result(
                    task=task,
                    report=report,
                    dry_run=dry_run,
                    bundle=bundle,
                    source_commit=source_commit,
                    before_counts=before_counts,
                    after_counts=after_counts,
                    candidate_audit=candidate_audit,
                    report14_audit=report14_audit,
                    report14_before=report14_before,
                    report14_after=report14_after,
                )
        if staged_result is None:
            raise RuntimeError("candidate transaction completed without result")
        staged_result["transaction"]["status"] = "committed"
        return staged_result
    except CandidateApplyError:
        raise
    except Exception as exc:
        failure_reason = failure_reason if failure_reason != "candidate transaction failed" else str(exc)
        failure = _rolled_back_failure(
            session_factory,
            before_counts=before_counts,
            candidate_task_no=candidate_task_no,
            report14_id=report14_id,
            report14_before=report14_before,
            reason=failure_reason,
        )
        raise CandidateApplyError(failure_reason, failure=failure) from exc


def build_success_packet(
    result: Mapping[str, Any],
    *,
    source_commit: str,
    x502_packet_hash: str,
    protocol_hash: str,
    parameter_hash: str,
    cost_timeline_hash: str,
    dry_run_hash: str,
    artifact_hashes: Mapping[str, str],
) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema_version": "htdy_trusted_backtest_candidate_x503_v1",
        "task_id": TASK_ID,
        "gate": SUCCESS_GATE,
        "status": "completed",
        "source_commit": source_commit,
        "x502_packet_hash": x502_packet_hash,
        "protocol_hash": protocol_hash,
        "parameter_hash": parameter_hash,
        "cost_timeline_hash": cost_timeline_hash,
        "dry_run_hash": dry_run_hash,
        "transaction": deepcopy(result.get("transaction") or {}),
        "candidate_identity": deepcopy(result.get("candidate_identity") or {}),
        "execution_snapshot": deepcopy(result.get("execution_snapshot") or {}),
        "strategy_identity": deepcopy(result.get("strategy_identity") or {}),
        "policy_snapshot": deepcopy(result.get("policy_snapshot") or {}),
        "cost_model": deepcopy(result.get("cost_model") or {}),
        "formal_lineage": deepcopy(result.get("formal_lineage") or {}),
        "future_fill_timing": deepcopy(result.get("future_fill_timing") or {}),
        "row_counts": deepcopy(result.get("row_counts") or {}),
        "facts_hash": result.get("facts_hash"),
        "audits": deepcopy(result.get("audits") or {}),
        "report14_regression": deepcopy(result.get("report14_regression") or {}),
        "tables_touched": ["backtest_tasks", "backtest_reports", "backtest_trades", "backtest_orders"],
        "storage_semantics": {
            "dedicated_equity_table": False,
            "equity_source": "deterministic_recompute_from_backtest_trades",
            "metrics_location": "backtest_reports.summary",
            "orders_location": "backtest_orders",
            "trades_location": "backtest_trades",
        },
        "rollback": {
            "scope": "single_database_transaction",
            "write_flush_candidate_audit_report14_audit": "atomic",
            "any_failure": "full_rollback_zero_candidate_rows",
            "failure_evidence": "sanitized_file_only",
        },
        "artifacts": {name: {"sha256": value} for name, value in sorted(artifact_hashes.items())},
        "boundaries": {
            "modified_existing_task_or_report": False,
            "modified_report14": False,
            "modified_profile_binding": False,
            "modified_parquet": False,
            "ran_oos": False,
            "tuned_parameters": False,
        },
    }
    packet["packet_hash"] = packet_hash(packet)
    return packet


def build_failure_packet(
    *,
    source_commit: str,
    reason: str,
    failure: Mapping[str, Any],
) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema_version": "htdy_trusted_backtest_candidate_failure_x503_v1",
        "task_id": TASK_ID,
        "gate": FAILURE_GATE,
        "status": "stage5_suspended",
        "source_commit": source_commit,
        "reason": _sanitize_error(reason),
        "transaction": deepcopy(failure.get("transaction") or {"status": "rolled_back"}),
        "row_counts": deepcopy(failure.get("row_counts") or {}),
        "report14_regression": deepcopy(failure.get("report14_regression") or {}),
        "rollback": {
            "database": "canonical_postgresql",
            "candidate_rows_retained": 0,
            "failure_evidence": "sanitized_file_only",
        },
    }
    packet["packet_hash"] = packet_hash(packet)
    return packet


def write_candidate_artifacts(
    output_dir: Path,
    *,
    result: Mapping[str, Any],
    bundle: Mapping[str, Any],
    source_commit: str,
) -> dict[str, Any]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("X5-03 output directory must be empty; immutable evidence cannot be overwritten")
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_paths = {
        "candidate_audit": output_dir / "candidate_trust_audit.json",
        "report14_audit": output_dir / "report14_trust_audit.json",
        "row_count_hash": output_dir / "candidate_row_count_hash.json",
    }
    _write_json(audit_paths["candidate_audit"], result["audits"]["candidate"])
    _write_json(audit_paths["report14_audit"], result["audits"]["report14"])
    _write_json(
        audit_paths["row_count_hash"],
        {
            "row_counts": result["row_counts"],
            "facts_hash": result["facts_hash"],
            "candidate_identity": result["candidate_identity"],
        },
    )
    artifact_hashes = {name: file_sha256(path) for name, path in audit_paths.items()}
    x502 = bundle["packet"]
    packet = build_success_packet(
        result,
        source_commit=source_commit,
        x502_packet_hash=x502["packet_hash"],
        protocol_hash=x502["protocol_hash"],
        parameter_hash=x502["parameter_hash"],
        cost_timeline_hash=x502["cost_timeline_hash"],
        dry_run_hash=x502["dry_run_hash"],
        artifact_hashes=artifact_hashes,
    )
    _write_json(output_dir / "HTDY_TRUSTED_BACKTEST_CANDIDATE.json", packet)
    (output_dir / "HTDY_TRUSTED_BACKTEST_CANDIDATE.md").write_text(
        _render_markdown(packet), encoding="utf-8"
    )
    return packet


def write_failure_artifact(output_dir: Path, packet: Mapping[str, Any]) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("X5-03 output directory is non-empty; failure evidence cannot overwrite artifacts")
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "HTDY_TRUST_AUDIT_FAILED_REVIEW_REQUIRED.json", packet)


def _formal_request(*, dry_run: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    params = validate_params()
    data = dry_run.get("data") or {}
    return {
        "instrument_symbol": "jm",
        "contract_code": "jm.MAIN",
        "exchange": "DCE",
        "interval": "15m",
        "auxiliary_periods": [],
        "profile_id": snapshot["profile_id"],
        "start": datetime.fromisoformat(str(data["start"]).replace("Z", "+00:00")),
        "end": datetime.fromisoformat(str(data["end"]).replace("Z", "+00:00")),
        "strategy_class_path": STRATEGY_CLASS_PATH,
        "strategy_code": params.strategy_code,
        "strategy_version": params.strategy_version,
        "strategy_parameters": params.to_dict(),
        "rate": 0.0001,
        "slippage": float(params.slippage_ticks),
        "size": 60,
        "pricetick": 0.5,
        "capital": float(params.initial_capital),
        "execution_timing": params.execution_timing,
    }


def _candidate_task_no(x502_packet_hash: str) -> str:
    if len(x502_packet_hash) != 64:
        raise ValueError("X5-02 packet hash must be a SHA-256 digest")
    return f"BTV-HTDY-X503-{x502_packet_hash[:16]}"


def _validate_bundle_identity(
    *,
    snapshot: Mapping[str, Any],
    dry_run: Mapping[str, Any],
    packet: Mapping[str, Any],
) -> None:
    required = (
        "profile_id",
        "profile_active_binding_id",
        "market_data_file_id",
        "data_version",
        "snapshot_hash",
    )
    if any(snapshot.get(field) in (None, "") for field in required):
        raise ValueError("execution snapshot identity is incomplete")
    if snapshot.get("data_role") != "primary" or snapshot.get("quality_status") != "passed":
        raise ValueError("execution snapshot is not primary/passed")
    if dry_run.get("strategy_code") != "huotian_dayou_strict":
        raise ValueError("dry-run strategy code is not frozen HTDY strict")
    params = validate_params()
    if dry_run.get("strategy_version") != params.strategy_version:
        raise ValueError("dry-run strategy version is not frozen")
    if dry_run.get("candidate_policy") != params.candidate_policy:
        raise ValueError("dry-run candidate policy is not frozen")
    if packet.get("protocol_hash") != dry_run.get("protocol_hash"):
        raise ValueError("protocol hash mismatch")
    if packet.get("parameter_hash") != dry_run.get("parameter_hash"):
        raise ValueError("parameter hash mismatch")
    if snapshot.get("snapshot_hash") != dry_run.get("execution_snapshot_hash"):
        raise ValueError("execution snapshot hash mismatch")


def _assert_task_binding(session: Session, *, task: BacktestTask, snapshot: Mapping[str, Any]) -> None:
    if task.profile_id != snapshot.get("profile_id"):
        raise ValueError("formal task profile differs from X5-02 snapshot")
    if task.market_data_file_id != snapshot.get("market_data_file_id"):
        raise ValueError("formal task file differs from X5-02 snapshot")
    if task.data_version != snapshot.get("data_version"):
        raise ValueError("formal task data version differs from X5-02 snapshot")
    binding = session.get(ProfileActiveBinding, int(snapshot["profile_active_binding_id"]))
    if binding is None or binding.binding_status != "active":
        raise ValueError("X5-02 Profile binding is no longer active")
    if binding.market_data_file_id != task.market_data_file_id:
        raise ValueError("X5-02 Profile binding no longer points to the candidate file")


def _transaction_result(
    *,
    task: BacktestTask,
    report: BacktestReportModel,
    dry_run: Mapping[str, Any],
    bundle: Mapping[str, Any],
    source_commit: str,
    before_counts: Mapping[str, int],
    after_counts: Mapping[str, int],
    candidate_audit: Mapping[str, Any],
    report14_audit: Mapping[str, Any],
    report14_before: Mapping[str, Any],
    report14_after: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot = deepcopy(bundle["execution_snapshot"])
    summary = report.summary or {}
    metadata = summary.get("report_metadata") or {}
    trades = list(report.trades)
    orders = list(report.order_rows)
    timing_failures = [
        trade.trade_no
        for trade in trades
        if trade.entry_signal_time is None or trade.open_time <= trade.entry_signal_time
    ]
    if timing_failures:
        raise ValueError(f"future/fill timing audit failed for {len(timing_failures)} trades")
    delta = {key: int(after_counts[key]) - int(before_counts[key]) for key in before_counts}
    facts = _candidate_facts(task=task, report=report)
    return {
        "transaction": {
            "status": "staged",
            "isolation": "single_session_single_transaction",
            "flush_before_audit": True,
            "candidate_and_report14_audit_before_commit": True,
        },
        "source_commit": source_commit,
        "candidate_identity": {
            "task": {"id": task.id, "task_no": task.task_no},
            "report": {"id": report.id, "report_no": report.report_no},
        },
        "execution_snapshot": snapshot,
        "strategy_identity": {
            "strategy_code": report.strategy_code,
            "strategy_version": report.strategy_version,
            "candidate_policy": dry_run.get("candidate_policy"),
        },
        "policy_snapshot": deepcopy(metadata.get("indicator_policy_snapshot") or {}),
        "cost_model": {
            "timeline_hash": bundle["packet"].get("cost_timeline_hash"),
            "timeline_rows": (bundle.get("cost_timeline") or {}).get("row_count"),
            "total_commission": summary.get("total_commission"),
            "total_slippage": summary.get("total_slippage"),
            "source": "canonical_per_trading_day_cost_timeline",
        },
        "formal_lineage": {
            "profile_id": report.profile_id,
            "profile_active_binding_id": snapshot.get("profile_active_binding_id"),
            "market_data_file_id": report.market_data_file_id,
            "data_version": report.data_version,
            "execution_snapshot_hash": snapshot.get("snapshot_hash"),
            "consistency_hash": report.consistency_hash,
        },
        "future_fill_timing": {
            "policy": "confirmed_close_signal_then_next_bar_open_fill",
            "trade_count": len(trades),
            "violations": 0,
            "status": "passed",
        },
        "row_counts": {
            "before": dict(before_counts),
            "after": dict(after_counts),
            "delta": delta,
            "candidate": {
                "tasks": 1,
                "reports": 1,
                "trades": len(trades),
                "orders": len(orders),
                "equity_points": len(dry_run.get("equity_curve") or []),
                "metric_fields": len(summary),
            },
        },
        "facts_hash": packet_hash(facts),
        "audits": {
            "candidate": deepcopy(candidate_audit),
            "report14": deepcopy(report14_audit),
        },
        "report14_regression": {
            "report_id": report14_before.get("report_id"),
            "before": dict(report14_before),
            "after": dict(report14_after),
            "unchanged": report14_before == report14_after,
        },
    }


def _candidate_facts(*, task: BacktestTask, report: BacktestReportModel) -> dict[str, Any]:
    return {
        "task": {
            "id": task.id,
            "task_no": task.task_no,
            "status": task.status,
            "profile_id": task.profile_id,
            "market_data_file_id": task.market_data_file_id,
            "data_version": task.data_version,
        },
        "report": {
            "id": report.id,
            "report_no": report.report_no,
            "status": report.status,
            "strategy_code": report.strategy_code,
            "strategy_version": report.strategy_version,
            "consistency_hash": report.consistency_hash,
            "summary": report.summary,
        },
        "trades": [
            {
                "trade_no": trade.trade_no,
                "sequence": trade.sequence,
                "contract": trade.contract,
                "direction": trade.direction,
                "entry_signal_time": trade.entry_signal_time.isoformat() if trade.entry_signal_time else None,
                "open_time": trade.open_time.isoformat(),
                "close_time": trade.close_time.isoformat(),
                "open_price": trade.open_price,
                "close_price": trade.close_price,
                "volume": trade.volume,
                "commission": trade.commission,
                "slippage": trade.slippage,
                "net_pnl": trade.net_pnl,
                "lineage_status": trade.lineage_status,
            }
            for trade in sorted(report.trades, key=lambda row: (row.sequence, row.trade_no))
        ],
        "orders": [
            {
                "order_no": order.order_no,
                "trade_no": order.trade_no,
                "leg": order.leg,
                "contract": order.contract,
                "direction": order.direction,
                "order_time": order.order_time.isoformat() if order.order_time else None,
                "price": order.price,
                "volume": order.volume,
                "mapping_status": order.mapping_status,
            }
            for order in sorted(report.order_rows, key=lambda row: (row.order_time or datetime.min, row.order_no))
        ],
    }


def _table_counts(session: Session) -> dict[str, int]:
    return {
        "tasks": int(session.scalar(select(func.count(BacktestTask.id))) or 0),
        "reports": int(session.scalar(select(func.count(BacktestReportModel.id))) or 0),
        "trades": int(session.scalar(select(func.count(BacktestTradeModel.id))) or 0),
        "orders": int(session.scalar(select(func.count(BacktestOrderModel.id))) or 0),
    }


def _report_fingerprint(report: BacktestReportModel | None) -> dict[str, Any]:
    if report is None:
        return {}
    return {
        "report_id": report.id,
        "report_no": report.report_no,
        "task_id": report.task_id,
        "task_no": report.task_no,
        "consistency_hash": report.consistency_hash,
        "trade_count": len(report.trades),
        "order_count": len(report.order_rows),
        "summary_hash": packet_hash(report.summary or {}),
    }


def _rolled_back_failure(
    session_factory: Callable[[], Session],
    *,
    before_counts: Mapping[str, int],
    candidate_task_no: str | None,
    report14_id: int,
    report14_before: Mapping[str, Any] | None,
    reason: str,
) -> dict[str, Any]:
    with session_factory() as verification:
        after = _table_counts(verification)
        delta = {
            key: after[key] - int(before_counts.get(key, after[key]))
            for key in after
        }
        retained = 0
        if candidate_task_no:
            retained = int(
                verification.scalar(
                    select(func.count(BacktestTask.id)).where(BacktestTask.task_no == candidate_task_no)
                )
                or 0
            )
        report14_after = _report_fingerprint(verification.get(BacktestReportModel, report14_id))
    if any(delta.values()) or retained:
        raise RuntimeError("candidate rollback verification detected retained canonical rows")
    return {
        "transaction": {"status": "rolled_back", "reason": _sanitize_error(reason)},
        "row_counts": {"before": dict(before_counts), "after": after, "delta": delta},
        "report14_regression": {
            "before": dict(report14_before or {}),
            "after": report14_after,
            "unchanged": not report14_before or dict(report14_before) == report14_after,
        },
    }


def _pretransaction_failure(reason: str) -> dict[str, Any]:
    return {
        "transaction": {"status": "not_started", "reason": _sanitize_error(reason)},
        "row_counts": {"delta": {"tasks": 0, "reports": 0, "trades": 0, "orders": 0}},
        "report14_regression": {"unchanged": True},
    }


def _sanitize_error(reason: str) -> str:
    text = str(reason).strip().splitlines()[0] if str(reason).strip() else "candidate transaction failed"
    lowered = text.lower()
    if any(marker in lowered for marker in ("password", "token", "secret", "license", "webhook")):
        return "<redacted>"
    for marker in ("/Users/", "/Volumes/", "/private/", "\\Users\\"):
        text = text.replace(marker, "<local-path>/")
    return text[:500]


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False, default=str) + "\n",
        encoding="utf-8",
    )


def _render_markdown(packet: Mapping[str, Any]) -> str:
    identity = packet.get("candidate_identity") or {}
    return "\n".join(
        [
            "# HTDY X5-03 Trusted Backtest Candidate",
            "",
            f"- Gate: `{packet.get('gate')}`",
            f"- Packet hash: `{packet.get('packet_hash')}`",
            f"- Source commit: `{packet.get('source_commit')}`",
            f"- Task: `{(identity.get('task') or {}).get('id')}` / `{(identity.get('task') or {}).get('task_no')}`",
            f"- Report: `{(identity.get('report') or {}).get('id')}` / `{(identity.get('report') or {}).get('report_no')}`",
            f"- Candidate audit: `{((packet.get('audits') or {}).get('candidate') or {}).get('audit_status')}`",
            f"- Report14 audit: `{((packet.get('audits') or {}).get('report14') or {}).get('audit_status')}`",
            "",
            "The candidate is a research artifact. This Gate is not OOS validation or live-trading approval.",
            "",
        ]
    )


__all__ = [
    "CandidateApplyError",
    "FAILURE_GATE",
    "REPORT14_ID",
    "RETIRED_GATE",
    "SUCCESS_GATE",
    "TASK_ID",
    "apply_candidate_transaction",
    "build_failure_packet",
    "build_success_packet",
    "load_x502_bundle",
    "verify_packet_hash",
    "write_candidate_artifacts",
    "write_failure_artifact",
]
