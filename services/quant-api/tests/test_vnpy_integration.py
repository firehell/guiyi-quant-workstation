from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import importlib
import importlib.util
import json
from pathlib import Path
import sys

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
    assert result["summary"]["total_return"] == 0.123
    assert result["trades"][0]["datetime"] == "2024-01-02T09:00:00"
    assert result["trades"][0]["price"] == 3500.5
    assert result["equity_curve"][0]["date"] == "2024-01-02"
    assert result["metadata"]["research_only"] is True


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
    assert normalized["daily_results"]
    assert normalized["equity_curve"]
    assert normalized["drawdown_curve"]
    json.dumps(normalized, ensure_ascii=False)


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
