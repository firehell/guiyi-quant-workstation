from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backtest.trust_audit import build_backtest_trust_audit
from app.models.backtest import (
    BacktestOrderModel,
    BacktestReportModel,
    BacktestTask,
    BacktestTradeModel,
)


TASK_ID = "TASK-HTDY-SAMPLE-END-LIQUIDATION-R4502"
EXECUTION_TASK_ID = "HTDY-SAMPLE-END-LIQUIDATION-R4502"
STRUCTURAL_GATE = "OOS_STRUCTURAL_AUDIT_AMENDED"
NUMERIC_GATE = "NUMERIC_HARD_REJECT_PRESERVED"
BLOCKED_GATE = "STRATEGY_VALIDATION_BLOCKED_FILL_POLICY_DRIFT"
BASELINE_GATE = "STAGE45_CLOSEOUT_BASELINE_READY"
DATA_GATE = "HTDY_FROZEN_DATA_WINDOW_EQUIVALENT"
SAMPLE_END_REASON = "sample_end_forced_exit"
SAMPLE_END_SOURCE = "sample_end"
EXPECTED_NUMERIC_REASONS = [
    "max_consecutive_losses:12.0:max_consecutive_losses_gte:8.0",
    "profit_factor:0.16355909337101607:profit_factor_lt:0.5",
]
EXPECTED_MAX_CONSECUTIVE_LOSSES = 12
EXPECTED_PROFIT_FACTOR = 0.16355909337101607
EXPECTED_CANDIDATE_HASH = "dee6c73e0972de51ae314956c038962f1c45cbfb1162322628fee3b728c07a1d"
EXPECTED_REPORT14_HASH = "2b16178a371a28727e0c471d6a7d68199e213ec205d838cf6634e82de428d12a"

BASELINE_PATH = Path("data/reports/htdy_stage45_closeout_r45/baseline/BASELINE.json")
R4501_PATH = Path("data/reports/htdy_stage45_closeout_r45/R45_01_ACCEPTANCE.json")
X504_PACKET_PATH = Path("data/reports/htdy_oos_validation_x5_04/OOS_VALIDATION_RESULT.json")
X504_RESULT_PATH = Path("data/reports/htdy_oos_validation_x5_04/oos_fixed_result.json")
IMMUTABLE_PATHS = (
    Path("data/reports/htdy_oos_validation_x5_04/OOS_VALIDATION_RESULT.json"),
    Path("data/reports/htdy_oos_validation_x5_04/oos_fixed_result.json"),
    Path("data/reports/htdy_oos_validation_x5_04/oos_trust_audit.json"),
    Path("data/reports/htdy_oos_validation_x5_04/execution_input_snapshot.json"),
    Path("data/reports/htdy_oos_validation_x5_04/oos_canonical_cost_timeline.json"),
    Path("data/reports/htdy_trusted_backtest_candidate_x5_03/HTDY_TRUSTED_BACKTEST_CANDIDATE.json"),
)


class EvidenceDriftError(ValueError):
    """Raised when immutable R45/X5/report facts fail closed."""


def packet_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_packet_hash(packet: Mapping[str, Any]) -> bool:
    payload = dict(packet)
    expected = str(payload.pop("packet_hash", ""))
    return bool(expected) and expected == packet_hash(payload)


def load_verified_packet(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise EvidenceDriftError(f"required evidence is missing: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not verify_packet_hash(value):
        raise EvidenceDriftError(f"evidence packet hash is invalid: {path.name}")
    return value


def immutable_file_hashes(repo_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative_path in IMMUTABLE_PATHS:
        path = repo_root / relative_path
        if not path.is_file():
            raise EvidenceDriftError(f"immutable evidence is missing: {relative_path.as_posix()}")
        hashes[relative_path.as_posix()] = file_sha256(path)
    return hashes


def build_structural_audit(result: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = deepcopy(dict(result))
    events = list(snapshot.get("strategy_execution_events") or [])
    trades = list(snapshot.get("trades") or [])
    data = dict(snapshot.get("data") or {})
    blocked: list[str] = []
    window_end = _optional_datetime(data.get("end"))
    actual_end = _optional_datetime(data.get("actual_end"))

    sample_events = [
        (index, event)
        for index, event in enumerate(events)
        if event.get("action") == "close" and event.get("exit_reason") == SAMPLE_END_REASON
    ]
    sample_trades = [
        (index, trade)
        for index, trade in enumerate(trades)
        if trade.get("exit_reason") == SAMPLE_END_REASON
        and trade.get("exit_signal_source") == SAMPLE_END_SOURCE
    ]

    if len(sample_events) != 1:
        blocked.append("exactly one sample-end close event is required")
    if len(sample_trades) != 1:
        blocked.append("exactly one sample-end trade is required")
    if window_end is None or actual_end is None or actual_end != window_end:
        blocked.append("frozen window has no exact final tradable bar")

    event_index, event = sample_events[0] if len(sample_events) == 1 else (-1, {})
    trade_index, trade = sample_trades[0] if len(sample_trades) == 1 else (-1, {})
    event_fill = _optional_datetime(event.get("fill_datetime"))
    event_signal = _optional_datetime(event.get("signal_datetime"))
    exit_fill = _optional_datetime(trade.get("exit_datetime"))
    exit_signal = _optional_datetime(trade.get("exit_signal_time"))

    if event_index != len(events) - 1 or event.get("action") != "close":
        blocked.append("sample-end close must be the final execution event")
    if trade_index != len(trades) - 1:
        blocked.append("sample-end trade must be the final closed trade")
    if window_end is None or any(value != window_end for value in (event_fill, event_signal, exit_fill, exit_signal)):
        blocked.append("sample-end close signal and fill must equal frozen window end")
    if event.get("exit_reason") != SAMPLE_END_REASON:
        blocked.append("sample-end event reason is not exact")
    if trade.get("exit_reason") != SAMPLE_END_REASON or trade.get("exit_signal_source") != SAMPLE_END_SOURCE:
        blocked.append("sample-end trade reason or source is not exact")
    if event.get("trade_no") != trade.get("tradeid"):
        blocked.append("sample-end event and trade identities do not match")

    entry_signal = _optional_datetime(trade.get("entry_signal_time"))
    entry_fill = _optional_datetime(trade.get("entry_datetime"))
    if entry_signal is None or entry_fill is None or entry_fill <= entry_signal:
        blocked.append("trade entry fill is not strictly after signal")
    if window_end is None or entry_signal is None or entry_signal >= window_end:
        blocked.append("sample-end position was not signaled before window end")

    matching_open_indices = [
        index
        for index, candidate in enumerate(events)
        if _matches_open_event(candidate, trade)
    ]
    if len(matching_open_indices) != 1:
        blocked.append("exactly one matching open event is required")
    elif matching_open_indices[0] >= event_index:
        blocked.append("matching open event must precede sample-end finalizer close")

    for index, candidate in enumerate(events):
        signal = _optional_datetime(candidate.get("signal_datetime"))
        fill = _optional_datetime(candidate.get("fill_datetime"))
        if fill is None:
            blocked.append("strategy event is missing fill time")
        elif signal is not None and index != event_index and fill <= signal:
            blocked.append("ordinary event fill is not strictly after signal")

    for index, candidate in enumerate(trades):
        candidate_entry_signal = _optional_datetime(candidate.get("entry_signal_time"))
        candidate_entry_fill = _optional_datetime(candidate.get("entry_datetime"))
        candidate_exit_signal = _optional_datetime(candidate.get("exit_signal_time"))
        candidate_exit_fill = _optional_datetime(candidate.get("exit_datetime"))
        if (
            candidate_entry_signal is None
            or candidate_entry_fill is None
            or candidate_entry_fill <= candidate_entry_signal
        ):
            blocked.append("trade entry fill is not strictly after signal")
        if candidate_exit_signal is not None and candidate_exit_fill is not None:
            if index != trade_index and candidate_exit_fill <= candidate_exit_signal:
                blocked.append("ordinary trade exit fill is not strictly after signal")

    blocked = list(dict.fromkeys(blocked))
    is_liquidation = not blocked
    classification = {
        "is_accounting_liquidation": is_liquidation,
        "reason": SAMPLE_END_REASON if is_liquidation else None,
        "window_end": _iso(window_end),
        "event_identity": _event_identity(event_index, event) if is_liquidation else None,
        "trade_identity": _trade_identity(trade_index, trade) if is_liquidation else None,
        "excluded_from_standard_next_bar_fill_check": is_liquidation,
    }
    return {
        "schema_version": "htdy_sample_end_structural_audit_r4502_v1",
        "gate": STRUCTURAL_GATE if is_liquidation else BLOCKED_GATE,
        "classification": classification,
        "ordinary_events_strict_after": not any(
            reason == "ordinary event fill is not strictly after signal" for reason in blocked
        ),
        "ordinary_trades_strict_after": not any(
            reason in {
                "trade entry fill is not strictly after signal",
                "ordinary trade exit fill is not strictly after signal",
            }
            for reason in blocked
        ),
        "event_order_semantics": {
            "matching_open_event_index": matching_open_indices[0] if len(matching_open_indices) == 1 else None,
            "finalizer_close_event_index": event_index if event_index >= 0 else None,
            "same_bar_open_precedes_finalizer_close": bool(
                len(matching_open_indices) == 1 and matching_open_indices[0] < event_index
            ),
            "entry_signal_strictly_before_window_end": bool(
                entry_signal is not None and window_end is not None and entry_signal < window_end
            ),
        },
        "blocked_reasons": blocked,
    }


def build_closeout_packet(
    *,
    result: Mapping[str, Any],
    x504_packet: Mapping[str, Any],
    baseline_packet: Mapping[str, Any],
    r4501_acceptance: Mapping[str, Any],
    immutable_hashes_before: Mapping[str, str],
    immutable_hashes_after: Mapping[str, str],
    db_before: Mapping[str, Any],
    db_after: Mapping[str, Any],
    source_commit: str,
) -> dict[str, Any]:
    _validate_prerequisites(x504_packet, baseline_packet, r4501_acceptance)
    if dict(immutable_hashes_before) != dict(immutable_hashes_after):
        raise EvidenceDriftError("immutable X5 evidence changed during R45-02")
    if dict(db_before) != dict(db_after):
        raise EvidenceDriftError("report14/report15/task23 facts changed during R45-02")
    _validate_db_snapshot(db_before)
    if packet_hash(dict(result)) != x504_packet.get("result_hash"):
        raise EvidenceDriftError("X5-04 result hash does not match its immutable packet")

    structural = build_structural_audit(result)
    if structural["gate"] != STRUCTURAL_GATE:
        raise EvidenceDriftError(BLOCKED_GATE + ": " + "; ".join(structural["blocked_reasons"]))
    summary = dict(result.get("summary") or {})
    numeric_reasons = list((x504_packet.get("hard_reject") or {}).get("numeric_reasons") or [])
    if numeric_reasons != EXPECTED_NUMERIC_REASONS:
        raise EvidenceDriftError("X5-04 numeric hard-reject reasons drifted")
    if summary.get("max_consecutive_losses") != EXPECTED_MAX_CONSECUTIVE_LOSSES:
        raise EvidenceDriftError("X5-04 max_consecutive_losses drifted")
    if summary.get("profit_factor") != EXPECTED_PROFIT_FACTOR:
        raise EvidenceDriftError("X5-04 profit_factor drifted")

    packet: dict[str, Any] = {
        "schema_version": "htdy_sample_end_audit_r4502_v1",
        "task_id": TASK_ID,
        "execution_task_id": EXECUTION_TASK_ID,
        "source_commit": source_commit,
        "structural_gate": STRUCTURAL_GATE,
        "numeric_gate": NUMERIC_GATE,
        "overall_status": "completed",
        "classification": structural["classification"],
        "structural_audit": structural,
        "numeric_hard_reject": {
            "preserved": True,
            "max_consecutive_losses": EXPECTED_MAX_CONSECUTIVE_LOSSES,
            "profit_factor": EXPECTED_PROFIT_FACTOR,
            "reasons": numeric_reasons,
            "research_outcome_remains": "REJECTED_RESEARCH_CANDIDATE",
        },
        "prerequisites": {
            "baseline_gate": baseline_packet.get("gate"),
            "baseline_packet_hash": baseline_packet.get("packet_hash"),
            "data_window_gate": r4501_acceptance.get("gate"),
            "data_window_packet_hash": r4501_acceptance.get("packet_hash"),
            "x504_gate": x504_packet.get("gate"),
            "x504_packet_hash": x504_packet.get("packet_hash"),
            "x504_result_hash": x504_packet.get("result_hash"),
        },
        "invariance": {
            "immutable_x5_files": True,
            "immutable_file_sha256": dict(immutable_hashes_after),
            "report14_report15_task23": True,
            "db_before": deepcopy(dict(db_before)),
            "db_after": deepcopy(dict(db_after)),
            "pnl_trade_order_equity_changed": False,
        },
        "boundaries": {
            "readonly_db": True,
            "would_write_database": False,
            "would_modify_strategy": False,
            "would_modify_report14_or_report15": False,
            "would_modify_profile_binding": False,
            "would_modify_parquet": False,
            "would_modify_original_x5_evidence": False,
            "would_run_strategy": False,
            "would_send_notification": False,
            "would_place_order": False,
        },
    }
    packet["packet_hash"] = packet_hash(packet)
    return packet


def build_report_snapshot(session: Session) -> dict[str, Any]:
    candidate = session.get(BacktestReportModel, 15)
    report14 = session.get(BacktestReportModel, 14)
    task23 = session.get(BacktestTask, 23)
    if candidate is None or report14 is None or task23 is None:
        raise EvidenceDriftError("report14/report15/task23 is missing")
    if candidate.task_id != task23.id:
        raise EvidenceDriftError("report15 is not bound to task23")
    last_trade = session.scalar(
        select(BacktestTradeModel)
        .where(BacktestTradeModel.report_id == 15)
        .order_by(BacktestTradeModel.close_time.desc(), BacktestTradeModel.sequence.desc())
        .limit(1)
    )
    if last_trade is None:
        raise EvidenceDriftError("report15 has no last trade")
    candidate_audit = build_backtest_trust_audit(session, report_id=15)
    report14_audit = build_backtest_trust_audit(session, report_id=14)
    trade_count = int(
        session.scalar(select(func.count(BacktestTradeModel.id)).where(BacktestTradeModel.report_id == 15)) or 0
    )
    order_count = int(
        session.scalar(select(func.count(BacktestOrderModel.id)).where(BacktestOrderModel.report_id == 15)) or 0
    )
    return {
        "transaction": "REPEATABLE READ READ ONLY",
        "candidate": {
            "report_id": candidate.id,
            "task_id": candidate.task_id,
            "report_no": candidate.report_no,
            "task_no": task23.task_no,
            "audit_status": candidate_audit.get("audit_status"),
            "consistency_hash": candidate_audit.get("consistency_hash"),
            "facts_hash": packet_hash(
                {
                    "report": _model_payload(candidate),
                    "task": _model_payload(task23),
                    "trade_count": trade_count,
                    "order_count": order_count,
                }
            ),
            "trade_count": trade_count,
            "order_count": order_count,
            "last_trade": {
                "tradeid": last_trade.trade_no,
                "entry_signal_time": _iso(last_trade.entry_signal_time),
                "entry_datetime": _iso(last_trade.open_time),
                "exit_signal_time": _iso(last_trade.exit_signal_time),
                "exit_datetime": _iso(last_trade.close_time),
                "exit_reason": last_trade.exit_reason,
                "exit_signal_source": last_trade.exit_signal_source,
                "net_pnl": last_trade.net_pnl,
            },
        },
        "report14": {
            "report_id": report14.id,
            "audit_status": report14_audit.get("audit_status"),
            "consistency_hash": report14_audit.get("consistency_hash"),
            "facts_hash": packet_hash(_model_payload(report14)),
        },
    }


def render_markdown(packet: Mapping[str, Any]) -> str:
    classification = packet.get("classification") or {}
    numeric = packet.get("numeric_hard_reject") or {}
    return "\n".join(
        [
            "# HTDY R45-02 Sample-End Accounting Liquidation Audit",
            "",
            f"- Structural Gate: `{packet.get('structural_gate')}`",
            f"- Numeric Gate: `{packet.get('numeric_gate')}`",
            f"- Accounting liquidation: `{classification.get('is_accounting_liquidation')}`",
            f"- Window end: `{classification.get('window_end')}`",
            f"- Event: `{(classification.get('event_identity') or {}).get('trade_no')}`",
            f"- Trade: `{(classification.get('trade_identity') or {}).get('tradeid')}`",
            f"- Max consecutive losses: `{numeric.get('max_consecutive_losses')}`",
            f"- Profit factor: `{numeric.get('profit_factor')}`",
            "",
            "The one excluded close is an accounting-only sample-end liquidation, not an ordinary next-bar fill.",
            "All entries and all other signal-bearing events/trades retain strict `fill > signal` checks.",
            "The numeric hard reject and rejected research outcome remain unchanged.",
            "",
        ]
    )


def _validate_prerequisites(
    x504_packet: Mapping[str, Any],
    baseline_packet: Mapping[str, Any],
    r4501_acceptance: Mapping[str, Any],
) -> None:
    for name, packet in (
        ("X5-04", x504_packet),
        ("R45-00", baseline_packet),
        ("R45-01", r4501_acceptance),
    ):
        if not verify_packet_hash(packet):
            raise EvidenceDriftError(f"{name} packet hash is invalid")
    if baseline_packet.get("gate") != BASELINE_GATE:
        raise EvidenceDriftError(f"R45-00 Gate must be {BASELINE_GATE}")
    if r4501_acceptance.get("gate") != DATA_GATE:
        raise EvidenceDriftError(f"R45-01 Gate must be {DATA_GATE}")
    if x504_packet.get("gate") != "OOS_HARD_REJECT_TRIGGERED":
        raise EvidenceDriftError("X5-04 hard reject Gate drifted")


def _validate_db_snapshot(snapshot: Mapping[str, Any]) -> None:
    candidate = dict(snapshot.get("candidate") or {})
    report14 = dict(snapshot.get("report14") or {})
    if snapshot.get("transaction") != "REPEATABLE READ READ ONLY":
        raise EvidenceDriftError("database snapshot was not repeatable-read read-only")
    if candidate.get("report_id") != 15 or candidate.get("task_id") != 23:
        raise EvidenceDriftError("candidate report15/task23 identity drifted")
    if candidate.get("audit_status") != "passed" or candidate.get("consistency_hash") != EXPECTED_CANDIDATE_HASH:
        raise EvidenceDriftError("candidate report15 trust audit drifted")
    if report14.get("report_id") != 14 or report14.get("audit_status") != "passed":
        raise EvidenceDriftError("report14 trust audit is not passed")
    if report14.get("consistency_hash") != EXPECTED_REPORT14_HASH:
        raise EvidenceDriftError("report14 consistency hash drifted")
    trade = dict(candidate.get("last_trade") or {})
    required = {
        "entry_signal_time": "2026-07-10T14:45:00",
        "entry_datetime": "2026-07-10T15:00:00",
        "exit_signal_time": "2026-07-10T15:00:00",
        "exit_datetime": "2026-07-10T15:00:00",
        "exit_reason": SAMPLE_END_REASON,
        "exit_signal_source": SAMPLE_END_SOURCE,
    }
    if any(trade.get(key) != value for key, value in required.items()):
        raise EvidenceDriftError("report15 last trade is not the frozen sample-end liquidation")
    if trade.get("net_pnl") != -225.099:
        raise EvidenceDriftError("report15 last trade numeric facts drifted")


def _matches_open_event(event: Mapping[str, Any], trade: Mapping[str, Any]) -> bool:
    expected_action = "open_long" if trade.get("direction") == "long" else "open_short"
    return (
        event.get("action") == expected_action
        and event.get("signal_datetime") == trade.get("entry_signal_time")
        and event.get("fill_datetime") == trade.get("entry_datetime")
        and event.get("fill_price") == trade.get("entry_price")
        and event.get("entry_reason") == trade.get("entry_reason")
    )


def _event_identity(index: int, event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event_index": index,
        "trade_no": event.get("trade_no"),
        "action": event.get("action"),
        "signal_datetime": event.get("signal_datetime"),
        "fill_datetime": event.get("fill_datetime"),
        "identity_hash": packet_hash(dict(event)),
    }


def _trade_identity(index: int, trade: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "trade_index": index,
        "tradeid": trade.get("tradeid"),
        "entry_datetime": trade.get("entry_datetime"),
        "exit_datetime": trade.get("exit_datetime"),
        "identity_hash": packet_hash(dict(trade)),
    }


def _model_payload(model: Any) -> dict[str, Any]:
    return {column.name: getattr(model, column.name) for column in model.__table__.columns}


def _optional_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=None).isoformat(timespec="seconds")


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


__all__ = [
    "BASELINE_PATH",
    "BLOCKED_GATE",
    "DATA_GATE",
    "EXECUTION_TASK_ID",
    "EvidenceDriftError",
    "IMMUTABLE_PATHS",
    "NUMERIC_GATE",
    "R4501_PATH",
    "STRUCTURAL_GATE",
    "TASK_ID",
    "X504_PACKET_PATH",
    "X504_RESULT_PATH",
    "build_closeout_packet",
    "build_report_snapshot",
    "build_structural_audit",
    "file_sha256",
    "immutable_file_hashes",
    "load_verified_packet",
    "packet_hash",
    "render_markdown",
    "verify_packet_hash",
]
