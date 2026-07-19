from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backtest.service import BacktestService
from app.backtest.trust_audit import build_backtest_trust_audit
from app.db.base import Base
from app.models.backtest import BacktestReportModel
from app.schemas.backtest import BacktestTaskConfig


REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"
DRY_RUN_PATH = REPO_ROOT / "experiments" / "htdy_indicator" / "formal_backtest_candidate.py"

if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))


@dataclass
class TimedBar:
    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 200.0
    price_tick: float = 0.5
    contract_multiplier: int = 60
    commission_rate: float = 0.0001
    margin_rate: float = 0.12
    symbol: str = "JM2609"
    exchange: str = "DCE"
    contract: str = "JM2609"


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _bars(length: int = 16, *, start: datetime = datetime(2026, 1, 2, 9, 0)) -> list[TimedBar]:
    bars = []
    for index in range(length):
        close = 100.0 + index * 0.2
        bars.append(
            TimedBar(
                datetime=start + timedelta(minutes=15 * index),
                open=close,
                high=close + 2.0,
                low=close - 2.0,
                close=close + 0.5,
            )
        )
    return bars


def _base_setting(**overrides: Any) -> dict[str, Any]:
    setting = {
        "price_tick": 0.5,
        "contract_multiplier": 60,
        "commission_rate": 0.0001,
        "margin_rate": 0.12,
        "submit_vnpy_orders": False,
    }
    setting.update(overrides)
    return setting


def _blank_snapshot() -> dict[str, Any]:
    return {
        "zk1": None,
        "zd1": None,
        "zd2": None,
        "var23": None,
        "yellow_candle": False,
        "white_candle": False,
        "buy_observation": False,
        "sell_observation": False,
        "callback_buy": False,
        "xg_observation": False,
    }


def _snapshot(**overrides: Any) -> dict[str, Any]:
    value = _blank_snapshot()
    value.update(overrides)
    return value


def _patch_snapshots(monkeypatch: pytest.MonkeyPatch, snapshots: dict[int, dict[str, Any]]) -> None:
    import guiyi_quant.strategies.huotian_dayou_strict.vnpy_strategy as htdy

    def fake_snapshot(bars: list[Any], params: Any) -> dict[str, Any]:
        return snapshots.get(len(bars) - 1, _blank_snapshot())

    monkeypatch.setattr(htdy, "strict_signal_snapshot", fake_snapshot)


def test_default_params_json_is_frozen_to_formal_candidate() -> None:
    from guiyi_quant.strategies.huotian_dayou_strict import STRATEGY_CLASS_PATH, validate_params

    params = validate_params()

    assert STRATEGY_CLASS_PATH.endswith("HuoTianDaYouStrictStrategy")
    assert params.strategy_code == "huotian_dayou_strict"
    assert params.strategy_version == "v0.1.0-backtest-candidate"
    assert params.candidate_policy == "strict_v1_15m_formal_candidate_v0"
    assert params.fill_policy == "signal_on_close_fill_next_bar_open"
    assert params.entry_interval == "15m"
    assert params.take_profit_r_multiple == 1.5
    assert params.planned_time_exit_bars == 8
    assert params.submit_vnpy_orders is False
    assert params.indicator_version == "huotian_dayou_strict_v1"
    assert list(params.indicator_versions) == ["huotian_dayou_strict_v1"]
    assert list(params.formal_policy_ids) == ["huotian_dayou_strict_v1"]
    assert params.confirmed_only is True
    assert params.execution_timing == "next_bar_open"
    assert params.cost_model_version == "cost_model_v1_rate_slippage_size"
    assert params.research_status == "backtest_candidate"


def test_strategy_class_loads_via_strategy_loader() -> None:
    from app.vnpy_integration.strategy_loader import load_strategy_class
    from guiyi_quant.strategies.huotian_dayou_strict import STRATEGY_CLASS_PATH, HuoTianDaYouStrictStrategy

    assert load_strategy_class(STRATEGY_CLASS_PATH) is HuoTianDaYouStrictStrategy


def test_strict_candidate_future_tail_does_not_repaint_prior_outputs() -> None:
    from guiyi_quant.strategies.huotian_dayou_strict import compute_strict_fields

    bars = _bars(120)
    base = compute_strict_fields(
        [bar.open for bar in bars],
        [bar.high for bar in bars],
        [bar.low for bar in bars],
        [bar.close for bar in bars],
    )
    modified = list(bars)
    modified[-1] = TimedBar(
        datetime=modified[-1].datetime,
        open=200,
        high=240,
        low=180,
        close=220,
    )
    changed = compute_strict_fields(
        [bar.open for bar in modified],
        [bar.high for bar in modified],
        [bar.low for bar in modified],
        [bar.close for bar in modified],
    )

    for name in ("zk1", "zd1", "zd2", "var23"):
        assert base[name][:-1].tolist() == pytest.approx(changed[name][:-1].tolist(), nan_ok=True)
    for name in ("buy_observation", "sell_observation", "xg_observation"):
        assert base[name][:-1].tolist() == changed[name][:-1].tolist()


def test_entry_signal_fills_next_bar_open_with_slippage(monkeypatch: pytest.MonkeyPatch) -> None:
    from guiyi_quant.strategies.huotian_dayou_strict import HuoTianDaYouStrictStrategy

    _patch_snapshots(monkeypatch, {2: _snapshot(buy_observation=True)})
    strategy = HuoTianDaYouStrictStrategy(None, "htdy-test", "jm_MAIN.DCE", _base_setting())
    bars = _bars(5)

    for bar in bars[:3]:
        strategy.on_bar(bar)

    assert strategy.pending_action == "open_long"
    assert strategy.position_direction == "flat"

    strategy.on_bar(bars[3])

    assert strategy.position_direction == "long"
    assert strategy.entry_price == pytest.approx(bars[3].open + 0.5)
    assert strategy.execution_events[-1]["signal_datetime"] == bars[2].datetime.isoformat()
    assert strategy.execution_events[-1]["fill_datetime"] == bars[3].datetime.isoformat()


def test_stop_loss_has_priority_over_take_profit_same_bar(monkeypatch: pytest.MonkeyPatch) -> None:
    from guiyi_quant.strategies.huotian_dayou_strict import HuoTianDaYouStrictStrategy

    _patch_snapshots(monkeypatch, {2: _snapshot(buy_observation=True)})
    strategy = HuoTianDaYouStrictStrategy(None, "htdy-test", "jm_MAIN.DCE", _base_setting())
    bars = _bars(4)
    signal_bar = TimedBar(datetime=bars[2].datetime, open=100, high=102, low=99, close=101)
    fill_bar = TimedBar(datetime=bars[3].datetime, open=101, high=101.4, low=100.8, close=101.1)
    conflict_bar = TimedBar(datetime=bars[3].datetime + timedelta(minutes=15), open=101, high=106, low=98, close=101)

    for bar in [bars[0], bars[1], signal_bar, fill_bar, conflict_bar]:
        strategy.on_bar(bar)

    assert strategy.strategy_trades
    trade = strategy.strategy_trades[-1]
    assert trade["exit_reason"] == "stop_loss"
    assert trade["exit_price"] == pytest.approx(98.0)


def test_time_exit_schedules_close_at_bar_8_next_open(monkeypatch: pytest.MonkeyPatch) -> None:
    from guiyi_quant.strategies.huotian_dayou_strict import HuoTianDaYouStrictStrategy

    _patch_snapshots(monkeypatch, {2: _snapshot(buy_observation=True)})
    strategy = HuoTianDaYouStrictStrategy(None, "htdy-test", "jm_MAIN.DCE", _base_setting())
    bars = _bars(13)
    for index, bar in enumerate(bars):
        safe_bar = TimedBar(
            datetime=bar.datetime,
            open=110 if index < 3 else 113,
            high=111 if index < 3 else 114,
            low=109 if index < 3 else 112,
            close=110.5 if index < 3 else 113.2,
        )
        strategy.on_bar(safe_bar)

    assert strategy.strategy_trades
    trade = strategy.strategy_trades[-1]
    assert trade["exit_reason"] == "time_exit_bar_8"
    assert trade["holding_bars"] == 8


def test_reverse_observation_closes_first_and_does_not_reenter_same_bar(monkeypatch: pytest.MonkeyPatch) -> None:
    from guiyi_quant.strategies.huotian_dayou_strict import HuoTianDaYouStrictStrategy

    _patch_snapshots(monkeypatch, {2: _snapshot(buy_observation=True), 5: _snapshot(sell_observation=True)})
    strategy = HuoTianDaYouStrictStrategy(None, "htdy-test", "jm_MAIN.DCE", _base_setting())
    bars = _bars(8)
    for index, bar in enumerate(bars):
        safe_bar = TimedBar(
            datetime=bar.datetime,
            open=110 + index,
            high=111 + index,
            low=109 + index,
            close=110.5 + index,
        )
        strategy.on_bar(safe_bar)

    assert strategy.strategy_trades
    assert strategy.strategy_trades[-1]["exit_reason"] == "reverse_observation_exit"
    assert len(strategy.strategy_trades) == 1


def test_conflict_candidate_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    from guiyi_quant.strategies.huotian_dayou_strict import HuoTianDaYouStrictStrategy

    _patch_snapshots(monkeypatch, {2: _snapshot(buy_observation=True, sell_observation=True)})
    strategy = HuoTianDaYouStrictStrategy(None, "htdy-test", "jm_MAIN.DCE", _base_setting())
    for bar in _bars(4):
        strategy.on_bar(bar)

    assert strategy.position_direction == "flat"
    assert strategy.pending_action == ""
    assert strategy.rejected_signals[-1]["rejected_reason"] == "conflict_candidate_skipped"


def test_missing_cost_fields_reject_candidate_instead_of_defaulting(monkeypatch: pytest.MonkeyPatch) -> None:
    from guiyi_quant.strategies.huotian_dayou_strict import HuoTianDaYouStrictStrategy

    _patch_snapshots(monkeypatch, {2: _snapshot(buy_observation=True)})
    strategy = HuoTianDaYouStrictStrategy(None, "htdy-test", "jm_MAIN.DCE", _base_setting(price_tick=None))

    for bar in _bars(4):
        strategy.on_bar(bar)

    assert strategy.position_direction == "flat"
    assert strategy.pending_action == ""
    assert strategy.rejected_signals[-1]["rejected_reason"] == "missing_price_tick"


def test_normalized_result_can_be_persisted_and_passes_trust_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    from guiyi_quant.strategies.huotian_dayou_strict import HuoTianDaYouStrictStrategy, build_normalized_result

    _patch_snapshots(monkeypatch, {2: _snapshot(buy_observation=True)})
    strategy = HuoTianDaYouStrictStrategy(None, "htdy-test", "jm_MAIN.DCE", _base_setting())
    safe_bars = [
        TimedBar(
            datetime=bar.datetime,
            open=110 + index,
            high=111 + index,
            low=109 + index,
            close=110.5 + index,
        )
        for index, bar in enumerate(_bars(13))
    ]
    for bar in safe_bars:
        strategy.on_bar(bar)
    normalized = build_normalized_result(strategy)
    assert normalized["orders"]

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        service = BacktestService(session)
        task = service.create_task(
            BacktestTaskConfig(
                symbol="jm.MAIN",
                exchange="DCE",
                interval="15m",
                start=safe_bars[0].datetime.replace(tzinfo=UTC),
                end=safe_bars[-1].datetime.replace(tzinfo=UTC),
                strategy_class_path="guiyi_quant.strategies.huotian_dayou_strict.vnpy_strategy.HuoTianDaYouStrictStrategy",
                strategy_code="huotian_dayou_strict",
                strategy_version="v0.1.0-backtest-candidate",
                strategy_parameters={},
                rate=0.0001,
                slippage=1,
                size=60,
                pricetick=0.5,
                capital=1_000_000,
                data_source="local_parquet",
                data_role="primary",
                data_version="rqdata_jm_standard_15m_20230103_20260710_v2",
                quality_status="passed",
                research_only=True,
                request_payload={
                    "candidate_policy": "strict_v1_15m_formal_candidate_v0",
                    "note": "dry_run_test",
                },
            )
        )
        service.persist_result(task, normalized)
        session.commit()
        report = session.scalars(select(BacktestReportModel).where(BacktestReportModel.task_id == task.id)).one()
        audit = build_backtest_trust_audit(session, report_id=report.id)

        assert report.strategy_code == "huotian_dayou_strict"
        assert report.strategy_version == "v0.1.0-backtest-candidate"
        assert report.research_only is True
        assert audit["audit_status"] == "passed"
        assert audit["would_write_db"] is False


def test_formal_dry_run_rejects_non_primary_passed_lineage(tmp_path: Path) -> None:
    dry_run = _load_dry_run_module()
    source = tmp_path / "wrong_lineage.parquet"
    table = pa.Table.from_pylist(
        [
            {
                "datetime": datetime(2026, 1, 2, 9, 0),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100.5,
                "volume": 100,
                "provider": "rqdata",
                "source": "rqdata",
                "data_role": "candidate",
                "quality_status": "passed",
                "data_version": "rqdata_jm_standard_15m_20230103_20260710_v2",
                "symbol": "jm",
                "contract": "jm.MAIN",
                "period": "15m",
            }
        ]
    )
    pq.write_table(table, source)
    manifest = dry_run.load_manifest()

    with pytest.raises(ValueError, match="source lineage mismatch for data_role"):
        dry_run.read_candidate_input(
            source,
            manifest,
            price_tick=0.5,
            contract_multiplier=60,
            commission_rate=0.0001,
            commission_per_contract=None,
            margin_rate=0.12,
        )


def _load_dry_run_module():
    spec = importlib.util.spec_from_file_location("htdy_formal_candidate_for_tests", DRY_RUN_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
