from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages/quant-core"
if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))

from app.services.backtest_validation_context import (  # noqa: E402
    BacktestValidationEvidenceError,
    build_backtest_validation_context,
    verify_context_hash,
)
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.htdy_review_closed_loop import (  # noqa: E402
    _bars_evidence,
    build_closed_loop_packet,
    choose_max_net_loss_trade,
    verify_closed_loop_packet,
)


def _report_identity() -> dict[str, object]:
    return {
        "id": 15,
        "report_no": "BTV-HTDY-X503-ac00ef77c66a2862-RPT-a7c44c73",
        "task_id": 23,
        "task_no": "BTV-HTDY-X503-ac00ef77c66a2862",
        "profile_id": "intraday_research_v1",
        "market_data_file_id": 71338,
    }


def test_real_validation_context_is_hash_valid_and_keeps_rejection() -> None:
    context = build_backtest_validation_context(REPO_ROOT, report_identity=_report_identity())

    assert context["report_id"] == 15
    assert context["candidate"]["gate"] == "HTDY_TRUSTED_BACKTEST_CANDIDATE"
    assert context["candidate"]["candidate_trust_audit"] == "passed"
    assert context["candidate"]["report14_trust_audit"] == "passed"
    assert context["oos"]["window_id"] == "oos_fixed"
    assert context["oos"]["gate"] == "OOS_HARD_REJECT_TRIGGERED"
    assert context["rolling_oos"]["proposal_label"] == "DIAGNOSTIC_CONFIRMS_REJECTION"
    assert [fold["fold_id"] for fold in context["rolling_oos"]["folds"]] == [
        "walk_forward_a_test",
        "walk_forward_b_test",
        "walk_forward_c_test",
    ]
    assert all(fold["overlay_scenario_count"] == 81 for fold in context["rolling_oos"]["folds"])
    assert context["candidate_status"] == "oos_hard_rejected"
    assert context["review_skip_status"] == "SKIPPED_BY_FROZEN_HARD_REJECT"
    assert verify_context_hash(context)


def test_report_identity_mismatch_fails_closed() -> None:
    identity = _report_identity()
    identity["id"] = 14

    with pytest.raises(BacktestValidationEvidenceError, match="report identity"):
        build_backtest_validation_context(REPO_ROOT, report_identity=identity)


def test_tampered_fold_artifact_fails_closed(tmp_path: Path) -> None:
    for relative in (
        "data/reports/htdy_trusted_backtest_candidate_x5_03",
        "data/reports/htdy_oos_validation_x5_04",
        "data/reports/htdy_rolling_oos_x5_05",
    ):
        source = REPO_ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
    result_path = (
        tmp_path
        / "data/reports/htdy_rolling_oos_x5_05/folds/walk_forward_a_test/result.json"
    )
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["summary"]["trade_count"] = 999999
    result_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BacktestValidationEvidenceError, match="artifact hash"):
        build_backtest_validation_context(tmp_path, report_identity=_report_identity())


def test_context_hash_detects_derived_payload_tampering() -> None:
    context = build_backtest_validation_context(REPO_ROOT, report_identity=_report_identity())
    tampered = deepcopy(context)
    tampered["candidate_status"] = "validated_research_candidate"

    assert not verify_context_hash(tampered)


def test_review_source_exposes_original_entry_signal_time() -> None:
    from app.services.review_center import backtest_trade_source_payload

    signal_time = SimpleNamespace(isoformat=lambda: "2026-01-01T09:15:00")
    trade = SimpleNamespace(
        id=7,
        report_id=15,
        trade_no="T7",
        symbol="jm",
        contract="jm2605",
        timeframe="15m",
        direction="long",
        entry_signal_time=signal_time,
        open_time=SimpleNamespace(isoformat=lambda: "2026-01-01T09:30:00"),
        close_time=SimpleNamespace(isoformat=lambda: "2026-01-01T10:30:00"),
        open_price=100.0,
        close_price=101.0,
        volume=1,
        net_pnl=1.0,
        commission=0.1,
        slippage=0.5,
        holding_bars=4,
        entry_reason="entry",
        exit_reason="exit",
        raw_payload={},
    )
    session = SimpleNamespace(get=lambda *_: None, scalar=lambda *_: None)

    payload = backtest_trade_source_payload(session, trade)

    assert payload["entry_signal_time"] == "2026-01-01T09:15:00"


def test_validation_context_endpoint_rejects_arbitrary_path_query() -> None:
    report = SimpleNamespace(**_report_identity())

    class FakeSession:
        def get(self, _model: object, report_id: int) -> object | None:
            return report if report_id == 15 else None

    def override_get_db():
        yield FakeSession()

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.get("/api/backtests/reports/15/validation-context")
        rejected = client.get(
            "/api/backtests/reports/15/validation-context",
            params={"evidence_path": "/tmp/untrusted.json"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["context_hash"]
    assert rejected.status_code == 422


def test_max_net_loss_trade_tie_breaks_by_exit_time_then_id() -> None:
    trades = [
        SimpleNamespace(id=9, net_pnl=-100.0, close_time="2026-01-02T10:00:00"),
        SimpleNamespace(id=8, net_pnl=-100.0, close_time="2026-01-02T09:00:00"),
        SimpleNamespace(id=7, net_pnl=-100.0, close_time="2026-01-02T09:00:00"),
        SimpleNamespace(id=6, net_pnl=-99.0, close_time="2026-01-01T09:00:00"),
    ]

    assert choose_max_net_loss_trade(trades).id == 7


def test_closed_loop_gate_requires_every_real_smoke_check() -> None:
    db_evidence = {
        "status": "passed",
        "report_id": 15,
        "validation_context_hash": "v" * 64,
        "review_note": {"id": 99, "saved_and_reread": True},
        "exact_bars": {"status": "passed", "row_count": 4},
        "timing": {"status": "passed"},
        "report_invariance": {"candidate": True, "report14": True},
    }
    browser_smoke = {
        "status": "passed",
        "validation_context_api": True,
        "review_deep_link": True,
        "exact_bars_rendered": True,
        "trade_markers_rendered": True,
        "market_chart_round_trip": True,
        "backtest_round_trip": True,
        "review_saved_and_reread": True,
        "console_error_count": 0,
        "screenshot_sha256": "s" * 64,
    }

    packet = build_closed_loop_packet(
        source_commit="1" * 40,
        db_evidence=db_evidence,
        browser_smoke=browser_smoke,
    )
    failed_smoke = deepcopy(browser_smoke)
    failed_smoke["trade_markers_rendered"] = False

    assert packet["gate"] == "STRATEGY_REVIEW_CLOSED_LOOP_READY"
    assert verify_closed_loop_packet(packet)
    with pytest.raises(ValueError, match="browser smoke"):
        build_closed_loop_packet(
            source_commit="1" * 40,
            db_evidence=db_evidence,
            browser_smoke=failed_smoke,
        )


def test_exact_bar_evidence_hash_normalizes_datetimes() -> None:
    evidence = _bars_evidence(
        {
            "lineage": {"bar": {"bar_start": "2026-01-01T09:15:00"}},
            "bars": [
                {
                    "datetime": datetime(2026, 1, 1, 9, 15),
                    "open": 100.0,
                    "close": 101.0,
                }
            ],
        }
    )

    assert evidence["status"] == "passed"
    assert evidence["first_bar"] == "2026-01-01T09:15:00"
    assert len(evidence["bars_hash"]) == 64
