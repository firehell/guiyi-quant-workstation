from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages/quant-core"
if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))

from app.backtest.htdy_rolling_oos import (  # noqa: E402
    BLOCKED_DECISION,
    CONFIRMS_REJECTION,
    FOLD_IDS,
    INCONCLUSIVE_REJECTION,
    PROPOSED_REJECTED,
    PROPOSED_VALIDATED,
    build_overlay_grid,
    build_rolling_packet,
    load_x504_packet,
    proposal_label,
    rolling_folds,
    verify_packet_hash,
    _failed_fold,
)


PROTOCOL_PATH = REPO_ROOT / "configs/oos/htdy_strict_validation_protocol_v1.json"
SCRIPT_PATH = REPO_ROOT / "services/quant-api/scripts/htdy_rolling_oos.py"


def _protocol() -> dict:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def _trades() -> list[dict]:
    return [
        {
            "tradeid": "T1",
            "exit_datetime": "2025-01-02T10:00:00",
            "gross_pnl": 300.0,
            "commission": 12.0,
            "slippage": 60.0,
            "net_pnl": 228.0,
            "gap_execution": False,
            "price_tick": 0.5,
            "contract_multiplier": 60,
            "volume": 1,
            "margin_required": 20_000.0,
        },
        {
            "tradeid": "T2",
            "exit_datetime": "2025-01-03T10:00:00",
            "gross_pnl": -300.0,
            "commission": 12.0,
            "slippage": 60.0,
            "net_pnl": -372.0,
            "gap_execution": True,
            "price_tick": 0.5,
            "contract_multiplier": 60,
            "volume": 1,
            "margin_required": 900_000.0,
        },
    ]


def test_frozen_a_b_c_are_rolling_oos_stability_without_training_or_optimization() -> None:
    folds = rolling_folds(_protocol())

    assert [fold["fold_id"] for fold in folds] == [
        "walk_forward_a_test",
        "walk_forward_b_test",
        "walk_forward_c_test",
    ]
    assert [fold["test_months"] for fold in folds] == [3, 3, 6]
    assert [fold["train_months"] for fold in folds] == [24, 24, 24]
    assert [fold["step_months"] for fold in folds] == [6, 6, 6]
    assert all(fold["mode"] == "rolling_oos_stability" for fold in folds)
    assert all(fold["train_usage"] == "lineage_metadata_only_no_fit_no_selection" for fold in folds)
    assert folds[0]["test_start"] == "2025-01-01T00:00:00"
    assert folds[1]["test_start"] == "2025-07-01T00:00:00"
    assert folds[2]["test_end"] == "2026-06-30T15:00:00"


def test_cost_margin_grid_is_deterministic_post_trade_overlay() -> None:
    overlays = build_overlay_grid(_trades(), initial_capital=1_000_000.0, parameter_hash="p" * 64)

    assert len(overlays) == 81
    assert len({overlay["overlay_hash"] for overlay in overlays}) == 81
    assert all(overlay["post_trade_cost_overlay"] is True for overlay in overlays)
    assert all(overlay["rematched"] is False for overlay in overlays)
    assert all(overlay["parameter_hash"] == "p" * 64 for overlay in overlays)
    assert {overlay["commission_multiplier"] for overlay in overlays} == {1.0, 1.5, 2.0}
    assert {overlay["slippage_ticks"] for overlay in overlays} == {1, 2, 3}
    assert {overlay["gap_ticks"] for overlay in overlays} == {0, 1, 2}
    assert {overlay["margin_multiplier"] for overlay in overlays} == {1.0, 1.25, 1.5}


def test_gap_overlay_only_penalizes_gap_execution_trades() -> None:
    overlays = build_overlay_grid(_trades(), initial_capital=1_000_000.0, parameter_hash="p" * 64)
    baseline = next(
        item
        for item in overlays
        if item["commission_multiplier"] == 1.0
        and item["slippage_ticks"] == 1
        and item["gap_ticks"] == 0
        and item["margin_multiplier"] == 1.0
    )
    gap_two = next(
        item
        for item in overlays
        if item["commission_multiplier"] == 1.0
        and item["slippage_ticks"] == 1
        and item["gap_ticks"] == 2
        and item["margin_multiplier"] == 1.0
    )

    assert baseline["adjusted_total_net_pnl"] == pytest.approx(-144.0)
    assert gap_two["gap_cost"] == pytest.approx(60.0)
    assert gap_two["adjusted_total_net_pnl"] == pytest.approx(baseline["adjusted_total_net_pnl"] - 60.0)
    assert gap_two["gap_trade_count"] == 1


def test_margin_overlay_reports_feasibility_without_changing_signal_or_pnl() -> None:
    overlays = build_overlay_grid(_trades(), initial_capital=1_000_000.0, parameter_hash="p" * 64)
    base = next(item for item in overlays if item["scenario_id"] == "commission1_slippage1_gap0_margin1")
    stressed = next(item for item in overlays if item["scenario_id"] == "commission1_slippage1_gap0_margin1.5")

    assert base["margin_feasible"] is True
    assert stressed["margin_feasible"] is False
    assert stressed["infeasible_trade_count"] == 1
    assert stressed["adjusted_total_net_pnl"] == base["adjusted_total_net_pnl"]


def _decision_folds(*, numeric_reasons: list[str] | None = None) -> list[dict]:
    return [
        {
            "fold_id": fold_id,
            "status": "completed",
            "audit_status": "passed",
            "structural_reasons": [],
            "numeric_reasons": list(numeric_reasons or []),
        }
        for fold_id in FOLD_IDS
    ]


@pytest.mark.parametrize(
    "fold_update",
    [
        {"status": "failed", "audit_status": "failed"},
        {"audit_status": "failed"},
        {"structural_reasons": ["canonical_cost_coverage_mismatch"]},
    ],
)
def test_execution_or_structural_failure_is_blocked_not_rejected(fold_update: dict) -> None:
    folds = _decision_folds(numeric_reasons=["profit_factor"])
    folds[1].update(fold_update)

    assert proposal_label(
        x504_gate="OOS_HARD_REJECT_TRIGGERED",
        folds=folds,
    ) == BLOCKED_DECISION


def test_numeric_only_failure_is_rejected_after_all_structural_checks_pass() -> None:
    folds = _decision_folds(numeric_reasons=["profit_factor"])

    assert proposal_label(x504_gate="OOS_HARD_REJECT_TRIGGERED", folds=folds) == CONFIRMS_REJECTION
    assert proposal_label(x504_gate="OOS_VALIDATION_EXECUTED", folds=folds) == PROPOSED_REJECTED


def test_all_numeric_pass_only_validates_when_x504_was_not_hard_rejected() -> None:
    folds = _decision_folds()

    assert proposal_label(
        x504_gate="OOS_HARD_REJECT_TRIGGERED",
        folds=folds,
    ) == INCONCLUSIVE_REJECTION
    assert proposal_label(x504_gate="OOS_VALIDATION_EXECUTED", folds=folds) == PROPOSED_VALIDATED


def test_missing_required_fold_or_unknown_x504_gate_is_blocked() -> None:
    assert proposal_label(
        x504_gate="OOS_VALIDATION_EXECUTED",
        folds=_decision_folds()[:-1],
    ) == BLOCKED_DECISION
    assert proposal_label(x504_gate="UNKNOWN", folds=_decision_folds()) == BLOCKED_DECISION


def test_packet_keeps_empty_losing_and_failed_folds_and_hashes() -> None:
    folds = [
        {"fold_id": FOLD_IDS[0], "status": "completed", "trade_count": 0, "total_return_pct": 0.0, "audit_status": "passed", "numeric_reasons": ["trade_count"], "structural_reasons": []},
        {"fold_id": FOLD_IDS[1], "status": "completed", "trade_count": 2, "total_return_pct": -0.1, "audit_status": "passed", "numeric_reasons": [], "structural_reasons": []},
        {"fold_id": FOLD_IDS[2], "status": "failed", "trade_count": 0, "total_return_pct": 0.0, "audit_status": "failed", "numeric_reasons": [], "structural_reasons": ["execution exception"]},
    ]
    packet = build_rolling_packet(
        source_commit="1" * 40,
        x504_packet={"gate": "OOS_HARD_REJECT_TRIGGERED", "packet_hash": "x" * 64},
        protocol_hash="p" * 64,
        parameter_hash="a" * 64,
        candidate_identity={"report": {"id": 15}},
        folds=folds,
        fold_artifacts={FOLD_IDS[0]: "a" * 64, FOLD_IDS[1]: "b" * 64, FOLD_IDS[2]: "c" * 64},
    )

    assert packet["status"] == "blocked"
    assert packet["proposal_label"] == BLOCKED_DECISION
    assert [fold["fold_id"] for fold in packet["folds"]] == list(FOLD_IDS)
    assert packet["x504_hard_reject_preserved"] is True
    assert verify_packet_hash(packet)


def test_load_x504_packet_recomputes_hash() -> None:
    packet = load_x504_packet(REPO_ROOT)
    assert packet["gate"] == "OOS_HARD_REJECT_TRIGGERED"
    assert verify_packet_hash(packet)


def test_cli_has_no_parameter_cost_or_database_override(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("htdy_rolling_oos_cli", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    parser = module.build_parser()
    option_strings = {option for action in parser._actions for option in action.option_strings}
    assert option_strings == {"-h", "--help", "--output-dir"}
    with pytest.raises(ValueError, match="data/reports"):
        module._validated_output_dir(tmp_path / "outside")


def test_failed_fold_preserves_frozen_parameter_hash_in_all_overlays() -> None:
    fold = _failed_fold(
        {"fold_id": "walk_forward_a_test"},
        reason="empty window",
        parameter_hash="p" * 64,
    )

    assert fold["status"] == "failed"
    assert len(fold["overlays"]) == 81
    assert all(item["parameter_hash"] == "p" * 64 for item in fold["overlays"])
