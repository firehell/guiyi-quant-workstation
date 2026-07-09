from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
import importlib
import importlib.util
import json
from pathlib import Path
import sys

import pandas as pd
import pytest
from vnpy_ctastrategy import CtaTemplate

from app.vnpy_integration import (
    BacktestConfigurationError,
    DEFAULT_EXECUTION_TIMING,
    GuiyiBacktestRequest,
    SymbolMappingError,
    VnpyBacktestRunner,
    VnpyNotInstalledError,
    convert_vnpy_result,
    from_vt_symbol,
    normalize_exchange,
    require_vnpy,
    schedule_signal_fill,
    signal_bar_index_to_fill_bar_index,
    to_vt_symbol,
    validate_execution_timing,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"
GENERATOR_PATH = REPO_ROOT / "experiments" / "vnpy_rqdata_demo" / "generate_standard_fixture.py"

if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))

GENERATOR_SPEC = importlib.util.spec_from_file_location("generate_standard_fixture", GENERATOR_PATH)
assert GENERATOR_SPEC is not None
assert GENERATOR_SPEC.loader is not None
fixture_generator = importlib.util.module_from_spec(GENERATOR_SPEC)
GENERATOR_SPEC.loader.exec_module(fixture_generator)

FIXTURE_PATH: Path = fixture_generator.DEFAULT_FIXTURE_PATH


@dataclass(frozen=True)
class FakeTrade:
    trade_id: str
    datetime: datetime
    price: Decimal
    volume: int


@dataclass(frozen=True)
class FakeRawResult:
    statistics: dict
    trades: list[FakeTrade]
    equity_curve: list[dict]
    warnings: list[str]


class DemoStrategy:
    pass


class FixtureRoundTripStrategy(CtaTemplate):
    """Tiny test-only strategy that creates one open and one close trade."""

    parameters: list[str] = []
    variables: list[str] = ["bar_count"]

    def __init__(self, cta_engine, strategy_name: str, vt_symbol: str, setting: dict) -> None:
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.bar_count = 0

    def on_init(self) -> None:
        return None

    def on_start(self) -> None:
        return None

    def on_stop(self) -> None:
        return None

    def on_bar(self, bar) -> None:
        self.bar_count += 1
        if self.bar_count == 2 and self.pos == 0:
            self.buy(bar.close_price + 20, 1)
        elif self.bar_count == 5 and self.pos > 0:
            self.sell(bar.close_price - 20, abs(self.pos))


def _ensure_fixture() -> Path:
    return fixture_generator.write_fixture(FIXTURE_PATH)


def _fixture_request(*, strategy_class_path: str, prepared_only: bool = False) -> GuiyiBacktestRequest:
    return GuiyiBacktestRequest(
        symbol="rb2405",
        exchange="SHFE",
        interval="60m",
        start=datetime(2024, 1, 2, 9, 0),
        end=datetime(2024, 1, 6, 8, 0),
        rate=0.0001,
        slippage=1,
        size=10,
        pricetick=1,
        capital=100000,
        strategy_class_path=strategy_class_path,
        strategy_parameters={},
        bar_data_path=_ensure_fixture(),
        prepared_only=prepared_only,
    )


def test_require_vnpy_raises_clear_error_when_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = importlib.import_module

    def fake_import(name: str, package: str | None = None):
        if name == "vnpy":
            raise ImportError("simulated missing vn.py")
        return original_import(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    with pytest.raises(VnpyNotInstalledError, match="not installed or cannot be imported"):
        require_vnpy()


def test_symbol_mapper_converts_between_guiyi_and_vnpy_symbols() -> None:
    assert normalize_exchange(" shfe ") == "SHFE"
    assert to_vt_symbol("rb2405", "shfe") == "rb2405.SHFE"

    mapped = from_vt_symbol("IF2406.CFFEX")

    assert mapped.symbol == "IF2406"
    assert mapped.exchange == "CFFEX"
    assert mapped.vt_symbol == "IF2406.CFFEX"


def test_symbol_mapper_rejects_unsupported_exchange() -> None:
    with pytest.raises(SymbolMappingError):
        to_vt_symbol("rb2405", "UNKNOWN")


def test_result_converter_normalizes_fake_raw_result_to_json() -> None:
    raw = FakeRawResult(
        statistics={"total_return": Decimal("0.123"), "trading_days": 2},
        trades=[
            FakeTrade(
                trade_id="T1",
                datetime=datetime(2024, 1, 2, 9, 0),
                price=Decimal("3500.5"),
                volume=1,
            )
        ],
        equity_curve=[{"date": date(2024, 1, 2), "balance": Decimal("100123.45")}],
        warnings=["fake result only"],
    )

    result = convert_vnpy_result(raw)

    assert result["engine"] == "vnpy_cta_backtesting"
    assert result["source"] == "vnpy"
    assert result["schema_version"] == "backtest_result.v1.0"
    assert result["report"]["trade_count"] == 1
    assert result["summary"]["total_return"] == 0.0
    assert result["trades"][0]["datetime"] == "2024-01-02T09:00:00"
    assert result["trades"][0]["price"] == 3500.5
    assert result["equity_curve"][0]["source"] == "initial_capital"
    assert result["drawdown_curve"][0]["drawdown"] == 0.0
    assert result["metadata"]["research_only"] is True


def test_result_converter_derives_v1_report_and_curves_from_trades_only() -> None:
    raw = {
        "status": "success",
        "statistics": {
            "initial_capital": Decimal("100000"),
            "final_equity": Decimal("999999"),
            "total_return": Decimal("9.99"),
            "max_drawdown": Decimal("0.99"),
        },
        "strategy_trades": [
            {
                "trade_id": "T1",
                "sequence": 1,
                "symbol": "jm",
                "exchange": "DCE",
                "entry_datetime": datetime(2024, 1, 2, 9, 0),
                "exit_datetime": datetime(2024, 1, 2, 10, 0),
                "direction": "long",
                "entry_price": Decimal("1000"),
                "exit_price": Decimal("1010"),
                "volume": 1,
                "contract_multiplier": 100,
                "price_tick": Decimal("0.5"),
                "gross_pnl": Decimal("1000"),
                "commission": Decimal("0"),
                "slippage": Decimal("0"),
                "net_pnl": Decimal("1000"),
                "margin_required": Decimal("12000"),
                "holding_bars": 4,
            },
            {
                "trade_id": "T2",
                "sequence": 2,
                "symbol": "jm",
                "exchange": "DCE",
                "entry_datetime": datetime(2024, 1, 3, 9, 0),
                "exit_datetime": datetime(2024, 1, 3, 10, 0),
                "direction": "long",
                "entry_price": Decimal("1010"),
                "exit_price": Decimal("980"),
                "volume": 1,
                "contract_multiplier": 100,
                "price_tick": Decimal("0.5"),
                "gross_pnl": Decimal("-3000"),
                "commission": Decimal("0"),
                "slippage": Decimal("0"),
                "net_pnl": Decimal("-3000"),
                "margin_required": Decimal("12000"),
                "holding_bars": 4,
            },
        ],
        "equity_curve": [{"datetime": "2024-01-03T10:00:00Z", "equity": 999999}],
        "drawdown_curve": [{"datetime": "2024-01-03T10:00:00Z", "drawdown": 1, "drawdown_pct": 0.99}],
        "daily_results": [{"date": "2024-01-03", "balance": 999999}],
    }

    result = convert_vnpy_result(raw)

    assert result["schema_version"] == "backtest_result.v1.0"
    assert result["report"]["initial_capital"] == 100000.0
    assert result["report"]["final_equity"] == 98000.0
    assert result["report"]["total_net_pnl"] == -2000.0
    assert result["report"]["max_drawdown_amount"] == 3000.0
    assert result["report"]["max_drawdown_pct"] == pytest.approx(3000.0 / 101000.0)
    assert result["summary"] == result["report"]
    assert result["equity_curve"][-1]["equity"] == 98000.0
    assert result["drawdown_curve"][-1]["drawdown"] == 3000.0
    assert result["drawdown_curve"][-1]["drawdown_pct"] == pytest.approx(3000.0 / 101000.0)
    assert "daily_results" not in result
    assert result["metadata"]["ignored_raw_curve_fields"] == ["daily_results", "drawdown_curve", "equity_curve"]


def test_result_converter_preserves_rejected_signals() -> None:
    raw = {
        "status": "success",
        "statistics": {"capital": 100000},
        "strategy_trades": [],
        "strategy_execution_events": [{"action": "open_long", "fill_datetime": "2024-01-02T09:30:00"}],
        "rejected_signals": [
            {
                "rejected_reason": "daily_direction_blocks_entry",
                "bar_datetime": "2024-01-02T09:15:00",
                "entry_interval": "15m",
            }
        ],
        "prepared": {
            "vt_symbol": "jm_MAIN.DCE",
            "interval": "15m",
            "start": "2024-01-02T09:00:00",
            "end": "2024-01-03T15:00:00",
            "capital": 100000,
        },
    }

    result = convert_vnpy_result(raw)

    assert result["strategy_execution_events"] == [{"action": "open_long", "fill_datetime": "2024-01-02T09:30:00"}]
    assert result["rejected_signals"] == [
        {
            "rejected_reason": "daily_direction_blocks_entry",
            "bar_datetime": "2024-01-02T09:15:00",
            "entry_interval": "15m",
        }
    ]


def test_result_converter_maps_strategy_execution_event_lineage() -> None:
    raw = {
        "status": "success",
        "statistics": {"capital": 100000},
        "strategy_trades": [
            {
                "trade_id": "T-LINEAGE-1",
                "symbol": "jm.MAIN",
                "direction": "long",
                "entry_datetime": "2024-01-02T09:15:00",
                "exit_datetime": "2024-01-02T10:00:00",
                "entry_price": 100,
                "exit_price": 105,
                "volume": 1,
                "commission": 12,
                "slippage": 30,
            }
        ],
        "strategy_execution_events": [
            {
                "action": "open_long",
                "signal_datetime": "2024-01-02T09:00:00",
                "fill_datetime": "2024-01-02T09:15:00",
            }
        ],
        "orders": [
            {
                "orderid": "O-LINEAGE-1",
                "symbol": "jm.MAIN",
                "direction": "long",
                "offset": "open",
                "datetime": "2024-01-02T09:15:00",
                "price": 100,
                "volume": 1,
                "traded": 1,
            },
            {
                "orderid": "O-LINEAGE-2",
                "symbol": "jm.MAIN",
                "direction": "short",
                "offset": "close",
                "datetime": "2024-01-02T10:00:00",
                "price": 105,
                "volume": 1,
                "traded": 1,
            }
        ],
        "prepared": {
            "vt_symbol": "jm_MAIN.DCE",
            "interval": "15m",
            "start": "2024-01-02T09:00:00",
            "end": "2024-01-02T15:00:00",
            "capital": 100000,
            "size": 60,
            "pricetick": 0.5,
        },
    }

    result = convert_vnpy_result(raw)

    trade = result["trades"][0]
    assert trade["entry_signal_time"] == "2024-01-02T09:00:00"
    assert trade["entry_signal_source"] == "strategy_execution_event"
    assert trade["entry_order_no"] == "O-LINEAGE-1"
    assert trade["lineage_status"] == "mapped"
    assert result["orders"][0]["trade_no"] == "T-LINEAGE-1"
    assert result["orders"][0]["leg"] == "entry"
    assert result["orders"][0]["mapping_status"] == "mapped"
    assert result["orders"][1]["trade_no"] == "T-LINEAGE-1"
    assert result["orders"][1]["leg"] == "exit"
    assert result["orders"][1]["mapping_status"] == "mapped"
    assert result["lineage_summary"]["mapped_trades"] == 1


def test_result_converter_maps_vnpy_order_submission_time_to_strategy_trade_lineage() -> None:
    raw = {
        "status": "success",
        "statistics": {"capital": 100000},
        "strategy_trades": [
            {
                "trade_id": "T-SUBMIT-1",
                "symbol": "jm.MAIN",
                "direction": "long",
                "signal_datetime": "2024-01-02T09:00:00",
                "entry_signal_time": "2024-01-02T09:00:00",
                "fill_datetime": "2024-01-02T09:15:00",
                "entry_datetime": "2024-01-02T09:15:00",
                "exit_datetime": "2024-01-02T10:00:00",
                "entry_price": 100,
                "exit_price": 105,
                "volume": 1,
                "commission": 12,
                "slippage": 30,
                "exit_reason": "max_hold_bars_exit",
            }
        ],
        "orders": [
            {
                "orderid": "O-ENTRY-SUBMIT",
                "symbol": "jm.MAIN",
                "direction": "多",
                "offset": "开",
                "datetime": "2024-01-02T09:00:00",
                "price": 100,
                "volume": 1,
                "traded": 1,
            },
            {
                "orderid": "O-EXIT-SUBMIT",
                "symbol": "jm.MAIN",
                "direction": "空",
                "offset": "平",
                "datetime": "2024-01-02T09:45:00",
                "price": 105,
                "volume": 1,
                "traded": 1,
            },
        ],
        "prepared": {
            "vt_symbol": "jm_MAIN.DCE",
            "interval": "15m",
            "start": "2024-01-02T09:00:00",
            "end": "2024-01-02T15:00:00",
            "capital": 100000,
            "size": 60,
            "pricetick": 0.5,
        },
    }

    result = convert_vnpy_result(raw)

    trade = result["trades"][0]
    assert trade["entry_signal_time"] == "2024-01-02T09:00:00"
    assert trade["entry_signal_source"] == "trade_field"
    assert trade["entry_order_no"] == "O-ENTRY-SUBMIT"
    assert trade["exit_order_no"] == "O-EXIT-SUBMIT"
    assert trade["lineage_status"] == "mapped"
    assert result["orders"][0]["trade_no"] == "T-SUBMIT-1"
    assert result["orders"][0]["leg"] == "entry"
    assert result["orders"][0]["lineage_source"] == "order_submission_signal_time"
    assert result["orders"][0]["mapping_status"] == "mapped"
    assert result["orders"][1]["trade_no"] == "T-SUBMIT-1"
    assert result["orders"][1]["leg"] == "exit"
    assert result["orders"][1]["lineage_source"] == "single_position_exit_order_range"
    assert result["orders"][1]["mapping_status"] == "mapped"
    assert result["lineage_summary"]["mapped_trades"] == 1
    assert result["lineage_summary"]["mapped_orders"] == 2
    assert result["lineage_summary"]["unmapped_orders"] == 0


def test_result_converter_marks_direct_stop_loss_exit_without_faking_exit_order() -> None:
    raw = {
        "status": "success",
        "statistics": {"capital": 100000},
        "strategy_trades": [
            {
                "trade_id": "T-DIRECT-STOP-1",
                "symbol": "jm.MAIN",
                "direction": "short",
                "signal_datetime": "2024-01-02T09:00:00",
                "entry_signal_time": "2024-01-02T09:00:00",
                "fill_datetime": "2024-01-02T09:15:00",
                "entry_datetime": "2024-01-02T09:15:00",
                "exit_datetime": "2024-01-02T09:45:00",
                "entry_price": 100,
                "exit_price": 98,
                "volume": 1,
                "commission": 12,
                "slippage": 30,
                "exit_reason": "stop_loss_atr_or_structure",
            }
        ],
        "orders": [
            {
                "orderid": "O-ENTRY-ONLY",
                "symbol": "jm.MAIN",
                "direction": "空",
                "offset": "开",
                "datetime": "2024-01-02T09:00:00",
                "price": 100,
                "volume": 1,
                "traded": 1,
            }
        ],
        "prepared": {
            "vt_symbol": "jm_MAIN.DCE",
            "interval": "15m",
            "start": "2024-01-02T09:00:00",
            "end": "2024-01-02T15:00:00",
            "capital": 100000,
            "size": 60,
            "pricetick": 0.5,
        },
    }

    result = convert_vnpy_result(raw)

    trade = result["trades"][0]
    assert trade["entry_order_no"] == "O-ENTRY-ONLY"
    assert "exit_order_no" not in trade
    assert trade["exit_signal_source"] == "strategy_trade_direct_exit"
    assert trade["lineage_status"] == "mapped"
    assert result["orders"][0]["trade_no"] == "T-DIRECT-STOP-1"
    assert result["orders"][0]["leg"] == "entry"
    assert result["orders"][0]["mapping_status"] == "mapped"
    assert result["lineage_summary"]["mapped_trades"] == 1
    assert result["lineage_summary"]["mapped_orders"] == 1
    assert result["lineage_summary"]["unmapped_orders"] == 0


def test_result_converter_preserves_signal_candidates() -> None:
    raw = {
        "status": "success",
        "statistics": {"capital": 100000},
        "strategy_trades": [],
        "signal_candidates": [
            {
                "datetime": "2024-01-02T15:00:00",
                "final_signal": "long",
                "long_score": 3,
                "short_score": 1,
                "satisfied_conditions": ["long_trend_ok", "macd_near_zero", "volume_expanded"],
            }
        ],
        "prepared": {
            "vt_symbol": "jm_MAIN.DCE",
            "interval": "1d",
            "start": "2024-01-02T15:00:00",
            "end": "2024-01-03T15:00:00",
            "capital": 100000,
        },
    }

    result = convert_vnpy_result(raw)

    assert result["signal_candidates"] == [
        {
            "datetime": "2024-01-02T15:00:00",
            "final_signal": "long",
            "long_score": 3,
            "short_score": 1,
            "satisfied_conditions": ["long_trend_ok", "macd_near_zero", "volume_expanded"],
        }
    ]


def test_backtest_runner_prepares_config_without_executing_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.vnpy_integration.backtest_runner as runner_module

    monkeypatch.setattr(runner_module, "require_vnpy", lambda: object())

    request = GuiyiBacktestRequest(
        symbol="rb2405",
        exchange="SHFE",
        interval="1m",
        start=datetime(2024, 1, 2, 9, 0),
        end=datetime(2024, 1, 2, 15, 0),
        rate=0.0001,
        slippage=1,
        size=10,
        pricetick=1,
        capital=100000,
        strategy_class_path="tests.test_vnpy_integration:DemoStrategy",
        strategy_parameters={"ema_period": 21},
        prepared_only=True,
    )

    result = VnpyBacktestRunner().run(request)

    assert result["status"] == "prepared"
    assert result["executed"] is False
    assert result["execution_timing"] == DEFAULT_EXECUTION_TIMING
    assert result["prepared"]["vt_symbol"] == "rb2405.SHFE"
    assert result["prepared"]["strategy_class_name"] == "DemoStrategy"
    assert result["prepared"]["execution_timing"] == DEFAULT_EXECUTION_TIMING


def test_backtest_runner_executes_vnpy_engine_with_su_bing_fixture() -> None:
    request = _fixture_request(
        strategy_class_path="guiyi_quant.strategies.su_bing_ema21.vnpy_strategy.SuBingEma21VnpyStrategy"
    )

    result = VnpyBacktestRunner().run(request)
    normalized = convert_vnpy_result(result)

    assert result["status"] == "success"
    assert result["executed"] is True
    assert result["metadata"]["load_data_called"] is False
    assert result["metadata"]["live_gateway_used"] is False
    assert result["metadata"]["bar_count"] == 96
    assert isinstance(result["statistics"], dict)
    assert "total_trade_count" in result["statistics"]
    assert "trades" in result
    assert result["strategy_trades"] == []
    assert result["strategy_execution_events"] == []
    assert "daily_results" in result
    assert normalized["summary"]["total_trade_count"] == result["statistics"]["total_trade_count"]
    json.dumps(normalized, ensure_ascii=False)


def test_backtest_runner_converts_real_vnpy_trades_to_standard_json() -> None:
    request = _fixture_request(strategy_class_path="tests.test_vnpy_integration:FixtureRoundTripStrategy")

    result = VnpyBacktestRunner().run(request)
    normalized = convert_vnpy_result(result)

    assert result["executed"] is True
    assert len(result["trades"]) >= 1
    assert len(normalized["trades"]) >= 1
    assert normalized["trades"][0]["gateway_name"] == "BACKTESTING"
    assert "daily_results" not in normalized
    assert "daily_results" in normalized["metadata"]["ignored_raw_curve_fields"]
    assert normalized["equity_curve"]
    assert normalized["drawdown_curve"]
    json.dumps(normalized, ensure_ascii=False)


def test_backtest_runner_executes_research_contract_with_5m_standard_bars(tmp_path: Path) -> None:
    start = datetime(2025, 1, 2, 9, 5)
    rows = []
    for index in range(10):
        moment = start + timedelta(minutes=5 * index)
        close = 1000.0 + index * 2
        rows.append(
            {
                "symbol": "jm",
                "contract": "jm.MAIN",
                "exchange": "DCE",
                "vt_symbol": "jm.MAIN.DCE",
                "datetime": moment,
                "trading_day": moment.date(),
                "interval": "5m",
                "period": "5m",
                "open": close - 1,
                "high": close + 2,
                "low": close - 2,
                "close": close,
                "volume": 100 + index,
                "turnover": close * (100 + index),
                "open_interest": 1000 + index,
                "source": "rqdata",
                "data_role": "primary",
                "quality_status": "passed",
            }
        )
    parquet_path = tmp_path / "jm_MAIN_5m.parquet"
    pd.DataFrame(rows).to_parquet(parquet_path, index=False)
    daily_rows = []
    for index in range(3):
        moment = datetime(2025, 1, 1 + index, 15, 0)
        close = 990.0 + index * 5
        daily_rows.append(
            {
                "symbol": "jm",
                "contract": "jm.MAIN",
                "exchange": "DCE",
                "vt_symbol": "jm.MAIN.DCE",
                "datetime": moment,
                "trading_day": moment.date(),
                "interval": "1d",
                "period": "1d",
                "open": close - 1,
                "high": close + 2,
                "low": close - 2,
                "close": close,
                "volume": 1000 + index,
                "turnover": close * (1000 + index),
                "open_interest": 3000 + index,
                "source": "rqdata",
                "data_role": "primary",
                "quality_status": "passed",
            }
        )
    daily_path = tmp_path / "jm_MAIN_1d.parquet"
    pd.DataFrame(daily_rows).to_parquet(daily_path, index=False)

    request = GuiyiBacktestRequest(
        symbol="jm.MAIN",
        exchange="DCE",
        interval="5m",
        start=start,
        end=start + timedelta(minutes=45),
        rate=0.0001,
        slippage=0.5,
        size=1,
        pricetick=0.5,
        capital=100000,
        strategy_class_path="app.vnpy_integration.smoke_strategy:VnpySmokeRoundTripStrategy",
        strategy_parameters={"entry_bar": 2, "exit_bar": 6, "volume": 1},
        bar_data_path=parquet_path,
        auxiliary_bar_data_paths={"1d": daily_path},
    )

    result = VnpyBacktestRunner().run(request)
    normalized = convert_vnpy_result(result)

    assert result["executed"] is True
    assert result["prepared"]["vt_symbol"] == "jm_MAIN.DCE"
    assert result["metadata"]["vnpy_runtime_symbol"] == "jm_MAIN"
    assert result["metadata"]["auxiliary_bar_counts"] == {"1d": 3}
    assert result["metadata"]["load_data_called"] is False
    assert result["metadata"]["live_gateway_used"] is False
    assert len(normalized["trades"]) >= 1
    assert normalized["equity_curve"]
    assert normalized["drawdown_curve"]


def test_backtest_runner_missing_cta_runtime_has_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = importlib.import_module

    def fake_import(name: str, package: str | None = None):
        if name == "vnpy_ctastrategy.backtesting":
            raise ImportError("simulated missing vn.py CTA engine")
        return original_import(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    with pytest.raises(VnpyNotInstalledError, match="vnpy_ctastrategy.backtesting is not installed"):
        VnpyBacktestRunner().run(_fixture_request(strategy_class_path="tests.test_vnpy_integration:FixtureRoundTripStrategy"))


def test_execution_policy_schedules_next_bar_open_fill() -> None:
    assert validate_execution_timing(DEFAULT_EXECUTION_TIMING) == "next_bar_open"
    assert signal_bar_index_to_fill_bar_index(10) == 11

    pending = schedule_signal_fill(
        signal_bar_index=10,
        direction="long",
        reason="ema21_bullish_macd_golden_cross",
    )

    assert pending.execution_bar_index == 11
    assert pending.execution_timing == "next_bar_open"
    assert pending.direction == "long"


def test_execution_policy_rejects_same_bar_fill() -> None:
    with pytest.raises(BacktestConfigurationError, match="execution_timing must be one of"):
        validate_execution_timing("same_bar_close")


def test_backtest_runner_rejects_unsupported_execution_timing(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.vnpy_integration.backtest_runner as runner_module

    monkeypatch.setattr(runner_module, "require_vnpy", lambda: object())

    request = GuiyiBacktestRequest(
        symbol="rb2405",
        exchange="SHFE",
        interval="1m",
        start=datetime(2024, 1, 2, 9, 0),
        end=datetime(2024, 1, 2, 15, 0),
        rate=0.0001,
        slippage=1,
        size=10,
        pricetick=1,
        capital=100000,
        strategy_class_path="tests.test_vnpy_integration:DemoStrategy",
        execution_timing="same_bar_close",
    )

    with pytest.raises(BacktestConfigurationError, match="execution_timing must be one of"):
        VnpyBacktestRunner().prepare(request)
