from __future__ import annotations

from datetime import date, datetime, timedelta
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"
if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))

from app.backtest.htdy_oos_validation import (  # noqa: E402
    EXECUTED_GATE,
    HARD_REJECT_GATE,
    OOSPrerequisiteError,
    WARMUP_BARS,
    build_oos_audit,
    evaluate_hard_reject,
    evaluate_oos_window,
    load_candidate_prerequisite,
    packet_hash,
    select_oos_rows,
    verify_canonical_packet_hash,
    write_oos_artifacts,
)
from app.backtest.htdy_trusted_report import (  # noqa: E402
    CandidateBar,
    FrozenProfileSelection,
)


def _selection(*, data_version: str = "frozen-data-v1") -> FrozenProfileSelection:
    base = FrozenProfileSelection(
        profile_id="intraday_research_v1",
        profile_active_binding_id=4945,
        market_data_file_id=71338,
        data_version=data_version,
        relative_path="data/parquet/canonical/jm.parquet",
        file_sha256="source-sha",
        start="2023-01-03T00:00:00",
        end="2026-07-10T15:00:00",
        row_count=100,
        source_interval="1m",
        provider="rqdata",
        data_role="primary",
        quality_status="passed",
        quality_policy="passed_only",
        binding_status="active",
    )
    return FrozenProfileSelection(**{**base.__dict__, "snapshot_hash": packet_hash(base.payload_without_hash())})


def _candidate_packet() -> dict:
    selection = _selection()
    packet = {
        "schema_version": "htdy_trusted_backtest_candidate_x503_v1",
        "gate": "HTDY_TRUSTED_BACKTEST_CANDIDATE",
        "transaction": {"status": "committed"},
        "candidate_identity": {
            "task": {"id": 101, "task_no": "HTDY-X503-001"},
            "report": {"id": 202, "report_no": "HTDY-X503-REPORT-001"},
        },
        "audits": {
            "candidate": {"audit_status": "passed"},
            "report14": {"audit_status": "passed"},
        },
        "execution_snapshot": {
            "snapshot_hash": selection.snapshot_hash,
            "profile_id": selection.profile_id,
            "profile_active_binding_id": selection.profile_active_binding_id,
            "market_data_file_id": selection.market_data_file_id,
            "data_version": selection.data_version,
        },
    }
    packet["packet_hash"] = packet_hash(packet)
    return packet


def _protocol(*, data_version: str = "frozen-data-v1") -> dict:
    return {
        "parameter_hash": "params",
        "frozen_data_policy": {"data_version": data_version},
        "frozen_strategy": {
            "strategy_code": "huotian_dayou_strict",
            "strategy_version": "v0.1.0-backtest-candidate",
            "indicator_version": "huotian_dayou_strict_v1",
            "fill_policy": "signal_on_close_fill_next_bar_open",
        },
        "windows": [
            {
                "id": "oos_fixed",
                "start": "2026-01-01T00:00:00",
                "end": "2026-07-10T15:00:00",
            }
        ],
    }


def _row(at: datetime) -> dict:
    return {
        "datetime": at,
        "trading_day": at.date(),
        "open": 1000.0,
        "high": 1005.0,
        "low": 995.0,
        "close": 1001.0,
        "volume": 100,
        "provider": "rqdata",
        "source": "rqdata",
        "data_role": "primary",
        "quality_status": "passed",
        "data_version": "frozen-data-v1",
        "symbol": "jm",
        "contract": "jm.MAIN",
        "period": "15m",
    }


def _candidate_bar(at: datetime) -> CandidateBar:
    return CandidateBar(
        datetime=at,
        trading_day=at.date(),
        open=1000.0,
        high=1005.0,
        low=995.0,
        close=1001.0,
        volume=100.0,
        price_tick=0.5,
        contract_multiplier=60,
        commission_rate=0.0001,
        commission_per_contract=None,
        margin_rate=0.12,
        symbol="jm",
        exchange="DCE",
        contract="JM2609",
        fee_type="rate",
        open_fee=0.0001,
        close_fee=0.0001,
        close_today_fee=0.0003,
        parameter_source="futures_trading_parameters",
        main_contract_map_id=10,
        main_contract_data_version="map-v1",
    )


def _empty_result(*, data_version: str = "frozen-data-v1") -> dict:
    return {
        "strategy_code": "huotian_dayou_strict",
        "strategy_version": "v0.1.0-backtest-candidate",
        "indicator_version": "huotian_dayou_strict_v1",
        "candidate_policy": "strict_v1_15m_formal_candidate_v0",
        "execution_policy": {
            "confirmed_only": True,
            "execution_timing": "next_bar_open",
            "fill_policy": "signal_on_close_fill_next_bar_open",
        },
        "parameter_hash": "params",
        "summary": {
            "trade_count": 0,
            "max_drawdown_pct": 0.0,
            "max_consecutive_losses": 0,
            "profit_factor": 0.0,
            "total_return_pct": 0.0,
            "total_commission": 0.0,
            "total_slippage": 0.0,
        },
        "trades": [],
        "orders": [],
        "strategy_execution_events": [],
        "equity_curve": [{"point_index": 0, "time": None, "equity": 1_000_000.0}],
        "drawdown_curve": [{"point_index": 0, "time": None, "equity": 1_000_000.0}],
        "data": {
            "warmup_row_count": 72,
            "row_count": 1,
            "start": "2026-01-01T00:00:00",
            "end": "2026-07-10T15:00:00",
            "trading_days": ["2026-01-02"],
            "data_version": data_version,
        },
        "warmup_policy": {"mode": "indicator_only_no_inherited_state"},
        "boundaries": {
            "would_write_db": False,
            "would_create_backtest_task": False,
            "would_create_backtest_report": False,
            "would_touch_report14": False,
        },
    }


def test_candidate_prerequisite_is_hash_bound_and_requires_both_passed_audits(tmp_path: Path) -> None:
    path = tmp_path / "candidate.json"
    packet = _candidate_packet()
    path.write_text(json.dumps(packet), encoding="utf-8")

    assert load_candidate_prerequisite(path)["candidate_identity"]["report"]["id"] == 202

    packet["audits"]["report14"]["audit_status"] = "failed"
    packet["packet_hash"] = packet_hash({key: value for key, value in packet.items() if key != "packet_hash"})
    path.write_text(json.dumps(packet), encoding="utf-8")
    with pytest.raises(OOSPrerequisiteError, match="report14"):
        load_candidate_prerequisite(path)


def test_candidate_prerequisite_tamper_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "candidate.json"
    packet = _candidate_packet()
    packet["candidate_identity"]["report"]["id"] = 999
    path.write_text(json.dumps(packet), encoding="utf-8")

    assert verify_canonical_packet_hash(packet) is False
    with pytest.raises(OOSPrerequisiteError, match="hash"):
        load_candidate_prerequisite(path)


def test_select_oos_rows_uses_exactly_72_preceding_bars_and_only_oos_fixed() -> None:
    start = datetime(2026, 1, 1)
    rows = [_row(start - timedelta(minutes=15 * offset)) for offset in range(80, 0, -1)]
    rows += [_row(start + timedelta(minutes=15 * offset)) for offset in range(3)]
    rows += [_row(datetime(2026, 7, 11))]

    warmup, oos = select_oos_rows(
        rows,
        start=start,
        end=datetime(2026, 7, 10, 15),
    )

    assert len(warmup) == WARMUP_BARS
    assert warmup[0]["datetime"] == start - timedelta(minutes=15 * WARMUP_BARS)
    assert [row["datetime"] for row in oos] == [start + timedelta(minutes=15 * offset) for offset in range(3)]


def test_evaluation_slices_warmup_snapshots_and_feeds_only_oos_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.backtest.htdy_oos_validation as module

    warmup = [SimpleNamespace(datetime=datetime(2025, 12, 31) + timedelta(minutes=index)) for index in range(72)]
    oos = [_candidate_bar(datetime(2026, 1, 2, 9, 0) + timedelta(minutes=15 * index)) for index in range(2)]
    captured: dict[str, object] = {}

    def fake_snapshots(bars, params):
        captured["combined_count"] = len(bars)
        return [{"snapshot_index": index} for index in range(len(bars))]

    class FakeStrategy:
        def __init__(self, engine, name, symbol, setting):
            captured["snapshots"] = setting["_guiyi_strict_snapshots"]
            self.fed = []
            self.strategy_trades = []
            self.execution_events = []
            self.rejected_signals = []
            captured["strategy"] = self

        def on_bar(self, bar):
            self.fed.append(bar)

        def finalize_sample_end(self):
            captured["finalized"] = True

    monkeypatch.setattr(module, "build_strict_snapshot_series", fake_snapshots)
    monkeypatch.setattr(module, "HuoTianDaYouStrictStrategy", FakeStrategy)
    monkeypatch.setattr(
        module,
        "build_normalized_result",
        lambda strategy: {
            "summary": {},
            "trades": [],
            "orders": [],
            "strategy_execution_events": [],
            "warnings": [],
        },
    )

    result = evaluate_oos_window(
        warmup,
        oos,
        execution_snapshot=_selection(),
        protocol_hash="protocol",
        parameter_hash="params",
        window_start=datetime(2026, 1, 1),
        window_end=datetime(2026, 7, 10, 15),
    )

    assert captured["combined_count"] == 74
    assert captured["snapshots"] == [{"snapshot_index": 72}, {"snapshot_index": 73}]
    assert captured["strategy"].fed == oos
    assert result["runner"]["strategy_event_bars"] == 2
    assert result["warmup_policy"]["strategy_state_reset_at_oos_start"] is True


@pytest.mark.parametrize(
    ("field", "accepted", "rejected"),
    [
        ("max_drawdown_pct", 0.15, 0.1500001),
        ("max_consecutive_losses", 7, 8),
        ("trade_count", 5, 4),
        ("profit_factor", 0.5, 0.4999999),
        ("total_return_pct", -0.1999999, -0.2),
    ],
)
def test_hard_reject_threshold_boundaries(field: str, accepted: float, rejected: float) -> None:
    criteria = {
        "max_drawdown_pct_gt": 0.15,
        "max_consecutive_losses_gte": 8,
        "trade_count_lt": 5,
        "profit_factor_lt": 0.5,
        "total_return_pct_lte": -0.2,
    }
    baseline = {
        "max_drawdown_pct": 0.15,
        "max_consecutive_losses": 7,
        "trade_count": 5,
        "profit_factor": 0.5,
        "total_return_pct": -0.1999999,
    }

    assert evaluate_hard_reject({**baseline, field: accepted}, criteria) == []
    assert any(field in reason for reason in evaluate_hard_reject({**baseline, field: rejected}, criteria))


def test_zero_trade_window_is_retained_and_hard_rejected() -> None:
    criteria = {
        "max_drawdown_pct_gt": 0.15,
        "max_consecutive_losses_gte": 8,
        "trade_count_lt": 5,
        "profit_factor_lt": 0.5,
        "total_return_pct_lte": -0.2,
    }
    reasons = evaluate_hard_reject(_empty_result()["summary"], criteria)

    assert any("trade_count" in reason for reason in reasons)
    assert any("profit_factor" in reason for reason in reasons)


def test_profit_factor_is_not_rejected_when_trades_have_wins_and_no_losses() -> None:
    criteria = {
        "max_drawdown_pct_gt": 0.15,
        "max_consecutive_losses_gte": 8,
        "trade_count_lt": 5,
        "profit_factor_lt": 0.5,
        "total_return_pct_lte": -0.2,
    }
    summary = {
        "max_drawdown_pct": 0.01,
        "max_consecutive_losses": 0,
        "trade_count": 5,
        "profit_factor": 0.0,
        "winning_trade_count": 5,
        "losing_trade_count": 0,
        "total_return_pct": 0.1,
    }

    assert evaluate_hard_reject(summary, criteria) == []


def test_audit_fails_closed_on_candidate_binding_drift_and_non_next_bar_fill() -> None:
    result = _empty_result(data_version="active-drift-v2")
    result["strategy_execution_events"] = [
        {
            "action": "open_long",
            "signal_datetime": "2026-01-02T09:00:00",
            "fill_datetime": "2026-01-02T09:00:00",
        }
    ]
    cost_payload = {"rows": [{"trading_day": "2026-01-02"}]}
    audit = build_oos_audit(
        result,
        execution_snapshot=_selection(data_version="active-drift-v2"),
        cost_payload=cost_payload,
        expected_trading_days={date(2026, 1, 2)},
        protocol=_protocol(data_version="frozen-data-v1"),
        candidate_packet=_candidate_packet(),
    )

    assert audit["audit_status"] == "failed"
    assert audit["checks"]["candidate_binding_snapshot"] == "failed"
    assert audit["checks"]["future_fill_timing"] == "failed"


def test_audit_promotes_equity_or_fee_mismatch_to_structural_failure() -> None:
    result = _empty_result()
    result["equity_curve"] = []
    result["summary"]["total_commission"] = 1.0
    audit = build_oos_audit(
        result,
        execution_snapshot=_selection(),
        cost_payload={"rows": [{"trading_day": "2026-01-02"}]},
        expected_trading_days={date(2026, 1, 2)},
        protocol=_protocol(),
        candidate_packet=_candidate_packet(),
    )

    assert audit["audit_status"] == "failed"
    assert audit["checks"]["trade_order_equity_metrics"] == "failed"
    assert any("equity curve" in reason for reason in audit["blocked_reasons"])
    assert any("commission" in reason for reason in audit["blocked_reasons"])


def test_oos_artifacts_are_hash_bound_and_file_only(tmp_path: Path) -> None:
    result = _empty_result()
    result["warmup_policy"] = {
        "mode": "indicator_only_no_inherited_state",
        "required_bars": 72,
    }
    audit = {"audit_status": "passed", "blocked_reasons": [], "readonly": True, "would_write_db": False}
    bundle = {
        "gate": EXECUTED_GATE,
        "protocol_hash": "protocol",
        "parameter_hash": "params",
        "execution_snapshot": _selection(),
        "cost_payload": {"rows": [{"trading_day": "2026-01-02"}], "timeline_hash": "costs"},
        "result": result,
        "audit": audit,
        "structural_reasons": [],
        "numeric_reasons": [],
        "candidate_packet": _candidate_packet(),
        "x502_packet": {"packet_hash": "x502"},
    }

    packet = write_oos_artifacts(tmp_path, source_commit="abc123", bundle=bundle)

    assert packet["gate"] == EXECUTED_GATE
    assert verify_canonical_packet_hash(packet)
    assert packet["data_identity"]["market_data_file_id"] == 71338
    assert packet["strategy_identity"]["indicator_version"] == "huotian_dayou_strict_v1"
    assert packet["execution_policy"]["execution_timing"] == "next_bar_open"
    assert packet["boundaries"]["would_write_db"] is False
    assert all((tmp_path / artifact["path"]).is_file() for artifact in packet["artifacts"].values())
    assert (tmp_path / "OOS_VALIDATION_RESULT.json").is_file()


def test_oos_artifacts_refuse_to_overwrite_nonempty_output(tmp_path: Path) -> None:
    (tmp_path / "existing.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot be overwritten"):
        write_oos_artifacts(tmp_path, source_commit="abc123", bundle={})


def test_cli_has_no_canonical_db_or_cost_override_arguments() -> None:
    script_path = REPO_ROOT / "services/quant-api/scripts/htdy_oos_validation.py"
    spec = importlib.util.spec_from_file_location("htdy_x504_cli", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parser = module.build_parser()
    options = {flag for action in parser._actions for flag in action.option_strings}

    assert options == {"-h", "--help", "--output-dir", "--candidate-packet"}
    assert "--apply" not in options
    assert "--database-url" not in options
    assert "--price-tick" not in options


def test_cli_missing_x503_gate_stops_before_database_session(monkeypatch: pytest.MonkeyPatch) -> None:
    script_path = REPO_ROOT / "services/quant-api/scripts/htdy_oos_validation.py"
    spec = importlib.util.spec_from_file_location("htdy_x504_cli_missing_gate", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "SessionLocal", lambda: pytest.fail("database session must not open"))
    monkeypatch.setattr(sys, "argv", [str(script_path), "--candidate-packet", "/tmp/x503-missing.json"])

    assert module.main() == 2


def test_gate_constants_are_mutually_exclusive() -> None:
    assert EXECUTED_GATE == "OOS_VALIDATION_EXECUTED"
    assert HARD_REJECT_GATE == "OOS_HARD_REJECT_TRIGGERED"
    assert EXECUTED_GATE != HARD_REJECT_GATE
