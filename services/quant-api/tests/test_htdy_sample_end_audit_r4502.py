from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.backtest.htdy_sample_end_audit import (
    BLOCKED_GATE,
    NUMERIC_GATE,
    STRUCTURAL_GATE,
    EvidenceDriftError,
    build_closeout_packet,
    build_structural_audit,
    load_verified_packet,
    packet_hash,
    verify_packet_hash,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULT_PATH = REPO_ROOT / "data/reports/htdy_oos_validation_x5_04/oos_fixed_result.json"
X504_PATH = REPO_ROOT / "data/reports/htdy_oos_validation_x5_04/OOS_VALIDATION_RESULT.json"
BASELINE_PATH = REPO_ROOT / "data/reports/htdy_stage45_closeout_r45/baseline/BASELINE.json"
R4501_PATH = REPO_ROOT / "data/reports/htdy_stage45_closeout_r45/R45_01_ACCEPTANCE.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _result() -> dict:
    return _json(RESULT_PATH)


def _db_snapshot() -> dict:
    return {
        "transaction": "REPEATABLE READ READ ONLY",
        "candidate": {
            "report_id": 15,
            "task_id": 23,
            "report_no": "BTV-HTDY-X503-ac00ef77c66a2862-RPT-a7c44c73",
            "task_no": "BTV-HTDY-X503-ac00ef77c66a2862",
            "audit_status": "passed",
            "consistency_hash": "dee6c73e0972de51ae314956c038962f1c45cbfb1162322628fee3b728c07a1d",
            "facts_hash": "c" * 64,
            "last_trade": {
                "tradeid": "HTDY-1255",
                "entry_signal_time": "2026-07-10T14:45:00",
                "entry_datetime": "2026-07-10T15:00:00",
                "exit_signal_time": "2026-07-10T15:00:00",
                "exit_datetime": "2026-07-10T15:00:00",
                "exit_reason": "sample_end_forced_exit",
                "exit_signal_source": "sample_end",
                "net_pnl": -225.099,
            },
        },
        "report14": {
            "report_id": 14,
            "audit_status": "passed",
            "consistency_hash": "2b16178a371a28727e0c471d6a7d68199e213ec205d838cf6634e82de428d12a",
            "facts_hash": "d" * 64,
        },
    }


def _hashed(payload: dict) -> dict:
    value = deepcopy(payload)
    value["packet_hash"] = packet_hash(value)
    return value


def test_real_x504_sample_end_is_exact_accounting_liquidation() -> None:
    audit = build_structural_audit(_result())

    assert audit["gate"] == STRUCTURAL_GATE
    assert audit["blocked_reasons"] == []
    assert audit["ordinary_events_strict_after"] is True
    assert audit["ordinary_trades_strict_after"] is True
    assert audit["classification"] == {
        "is_accounting_liquidation": True,
        "reason": "sample_end_forced_exit",
        "window_end": "2026-07-10T15:00:00",
        "event_identity": audit["classification"]["event_identity"],
        "trade_identity": audit["classification"]["trade_identity"],
        "excluded_from_standard_next_bar_fill_check": True,
    }
    assert audit["classification"]["event_identity"]["event_index"] == 357
    assert audit["classification"]["trade_identity"]["tradeid"] == "HTDY-179"


def test_ordinary_same_time_signal_fill_is_blocked() -> None:
    result = _result()
    event = result["strategy_execution_events"][0]
    event["signal_datetime"] = event["fill_datetime"]

    audit = build_structural_audit(result)

    assert audit["gate"] == BLOCKED_GATE
    assert "ordinary event fill is not strictly after signal" in audit["blocked_reasons"]


def test_entry_same_time_signal_fill_is_never_exempt() -> None:
    result = _result()
    result["trades"][-1]["entry_signal_time"] = result["trades"][-1]["entry_datetime"]

    audit = build_structural_audit(result)

    assert audit["gate"] == BLOCKED_GATE
    assert "trade entry fill is not strictly after signal" in audit["blocked_reasons"]


@pytest.mark.parametrize(
    "mutation",
    ["not_window_end", "no_final_bar", "not_final", "multiple", "fake_reason", "fake_source"],
)
def test_sample_end_scope_cannot_be_broadened(mutation: str) -> None:
    result = _result()
    event = result["strategy_execution_events"][-1]
    trade = result["trades"][-1]
    if mutation == "not_window_end":
        event["fill_datetime"] = "2026-07-10T14:45:00"
        event["signal_datetime"] = "2026-07-10T14:45:00"
        trade["exit_datetime"] = "2026-07-10T14:45:00"
        trade["exit_signal_time"] = "2026-07-10T14:45:00"
    elif mutation == "no_final_bar":
        result["data"]["actual_end"] = "2026-07-10T14:45:00"
    elif mutation == "not_final":
        result["strategy_execution_events"].append(deepcopy(result["strategy_execution_events"][-2]))
    elif mutation == "multiple":
        extra_event = deepcopy(event)
        extra_event["trade_no"] = "HTDY-178"
        result["strategy_execution_events"].insert(-1, extra_event)
        extra_trade = deepcopy(trade)
        extra_trade["tradeid"] = "HTDY-178"
        result["trades"].insert(-1, extra_trade)
    elif mutation == "fake_reason":
        event["exit_reason"] = "sample_end_forced_exit_fake"
        trade["exit_reason"] = "sample_end_forced_exit_fake"
    else:
        trade["exit_signal_source"] = "strategy_execution_event"

    audit = build_structural_audit(result)

    assert audit["gate"] == BLOCKED_GATE
    assert audit["classification"]["is_accounting_liquidation"] is False


@pytest.mark.parametrize("mutation", ["missing", "after", "mismatched"])
def test_matching_open_event_must_precede_finalizer_close(mutation: str) -> None:
    result = _result()
    open_event = result["strategy_execution_events"][-2]
    if mutation == "missing":
        result["strategy_execution_events"].pop(-2)
    elif mutation == "after":
        result["strategy_execution_events"][-2], result["strategy_execution_events"][-1] = (
            result["strategy_execution_events"][-1],
            result["strategy_execution_events"][-2],
        )
    else:
        open_event["fill_price"] = float(open_event["fill_price"]) + 0.5

    audit = build_structural_audit(result)

    assert audit["gate"] == BLOCKED_GATE
    assert audit["classification"]["is_accounting_liquidation"] is False


def test_closeout_packet_preserves_numeric_reject_and_all_invariants() -> None:
    x504 = _json(X504_PATH)
    baseline = _json(BASELINE_PATH)
    r4501 = _json(R4501_PATH)
    db_snapshot = _db_snapshot()
    immutable_hashes = {
        "oos_fixed_result.json": "7fd07a8daf825252bcaa89430d0fc928b41c59cce689779675c4867947d23259",
        "OOS_VALIDATION_RESULT.json": "e" * 64,
    }

    packet = build_closeout_packet(
        result=_result(),
        x504_packet=x504,
        baseline_packet=baseline,
        r4501_acceptance=r4501,
        immutable_hashes_before=immutable_hashes,
        immutable_hashes_after=immutable_hashes,
        db_before=db_snapshot,
        db_after=deepcopy(db_snapshot),
        source_commit="47d96849df717d998adfc2b95bb4ef83f9f60e26",
    )

    assert packet["structural_gate"] == STRUCTURAL_GATE
    assert packet["numeric_gate"] == NUMERIC_GATE
    assert packet["overall_status"] == "completed"
    assert packet["numeric_hard_reject"]["reasons"] == [
        "max_consecutive_losses:12.0:max_consecutive_losses_gte:8.0",
        "profit_factor:0.16355909337101607:profit_factor_lt:0.5",
    ]
    assert packet["invariance"]["immutable_x5_files"] is True
    assert packet["invariance"]["report14_report15_task23"] is True
    assert verify_packet_hash(packet)


def test_prerequisite_gate_hash_and_invariance_drift_fail_closed() -> None:
    x504 = _json(X504_PATH)
    baseline = _json(BASELINE_PATH)
    r4501 = _json(R4501_PATH)
    db_before = _db_snapshot()
    db_after = deepcopy(db_before)
    db_after["candidate"]["facts_hash"] = "changed"

    with pytest.raises(EvidenceDriftError):
        build_closeout_packet(
            result=_result(),
            x504_packet=x504,
            baseline_packet=baseline,
            r4501_acceptance=r4501,
            immutable_hashes_before={"x": "before"},
            immutable_hashes_after={"x": "after"},
            db_before=db_before,
            db_after=db_after,
            source_commit="47d96849",
        )

    tampered = deepcopy(r4501)
    tampered["gate"] = "DRIFTED"
    with pytest.raises(EvidenceDriftError):
        build_closeout_packet(
            result=_result(),
            x504_packet=x504,
            baseline_packet=baseline,
            r4501_acceptance=tampered,
            immutable_hashes_before={"x": "same"},
            immutable_hashes_after={"x": "same"},
            db_before=db_before,
            db_after=deepcopy(db_before),
            source_commit="47d96849",
        )


def test_helper_never_mutates_input_payloads() -> None:
    result = _result()
    before = deepcopy(result)
    build_structural_audit(result)
    assert result == before


def test_missing_or_tampered_acceptance_pointer_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "R45_01_ACCEPTANCE.json"
    with pytest.raises(EvidenceDriftError, match="missing"):
        load_verified_packet(missing)

    tampered = _json(R4501_PATH)
    tampered["ordered_bar_hash"] = "tampered"
    missing.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(EvidenceDriftError, match="hash is invalid"):
        load_verified_packet(missing)
