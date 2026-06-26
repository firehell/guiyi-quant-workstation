from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import importlib

import pytest

from app.vnpy_integration import (
    GuiyiBacktestRequest,
    SymbolMappingError,
    VnpyBacktestRunner,
    VnpyNotInstalledError,
    convert_vnpy_result,
    from_vt_symbol,
    normalize_exchange,
    require_vnpy,
    to_vt_symbol,
)


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


def test_backtest_runner_prepares_config_without_executing(monkeypatch: pytest.MonkeyPatch) -> None:
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
    )

    result = VnpyBacktestRunner().run(request)

    assert result["status"] == "prepared"
    assert result["executed"] is False
    assert result["prepared"]["vt_symbol"] == "rb2405.SHFE"
    assert result["prepared"]["strategy_class_name"] == "DemoStrategy"
