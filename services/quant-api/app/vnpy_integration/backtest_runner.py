from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.vnpy_integration.errors import BacktestConfigurationError
from app.vnpy_integration.execution_policy import DEFAULT_EXECUTION_TIMING, validate_execution_timing
from app.vnpy_integration.settings import VnpyBacktestSettings, require_vnpy
from app.vnpy_integration.strategy_loader import load_strategy_class
from app.vnpy_integration.symbol_mapper import to_vt_symbol


@dataclass(frozen=True)
class GuiyiBacktestRequest:
    symbol: str
    exchange: str
    interval: str
    start: datetime
    end: datetime
    rate: float
    slippage: float
    size: int
    pricetick: float
    capital: float
    strategy_class_path: str
    strategy_parameters: dict[str, Any] = field(default_factory=dict)
    execution_timing: str = DEFAULT_EXECUTION_TIMING


@dataclass(frozen=True)
class PreparedVnpyBacktest:
    settings: VnpyBacktestSettings
    strategy_class: type[Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "vt_symbol": self.settings.vt_symbol,
            "interval": self.settings.interval,
            "start": self.settings.start.isoformat(),
            "end": self.settings.end.isoformat(),
            "rate": self.settings.rate,
            "slippage": self.settings.slippage,
            "size": self.settings.size,
            "pricetick": self.settings.pricetick,
            "capital": self.settings.capital,
            "strategy_class_path": self.settings.strategy_class_path,
            "strategy_parameters": dict(self.settings.strategy_parameters),
            "strategy_class_name": self.strategy_class.__name__,
            "execution_timing": self.settings.execution_timing,
        }


class VnpyBacktestRunner:
    """Adapter boundary for future vn.py CTA BacktestingEngine execution."""

    def prepare(self, request: GuiyiBacktestRequest) -> PreparedVnpyBacktest:
        self._validate_request(request)
        require_vnpy()
        strategy_class = load_strategy_class(request.strategy_class_path)
        execution_timing = validate_execution_timing(request.execution_timing)
        settings = VnpyBacktestSettings(
            vt_symbol=to_vt_symbol(request.symbol, request.exchange),
            interval=request.interval,
            start=request.start,
            end=request.end,
            rate=request.rate,
            slippage=request.slippage,
            size=request.size,
            pricetick=request.pricetick,
            capital=request.capital,
            strategy_class_path=request.strategy_class_path,
            strategy_parameters=dict(request.strategy_parameters),
            execution_timing=execution_timing,
        )
        return PreparedVnpyBacktest(settings=settings, strategy_class=strategy_class)

    def run(self, request: GuiyiBacktestRequest) -> dict[str, Any]:
        prepared = self.prepare(request)
        return {
            "status": "prepared",
            "engine": "vnpy_cta_backtesting",
            "executed": False,
            "execution_timing": prepared.settings.execution_timing,
            "message": (
                "vn.py backtest settings prepared with next-bar-open execution policy; "
                "formal engine execution is not wired yet."
            ),
            "prepared": prepared.to_json(),
        }

    @staticmethod
    def _validate_request(request: GuiyiBacktestRequest) -> None:
        if request.start >= request.end:
            raise BacktestConfigurationError("start must be earlier than end")
        if request.rate < 0:
            raise BacktestConfigurationError("rate cannot be negative")
        if request.slippage < 0:
            raise BacktestConfigurationError("slippage cannot be negative")
        if request.size <= 0:
            raise BacktestConfigurationError("size must be greater than zero")
        if request.pricetick <= 0:
            raise BacktestConfigurationError("pricetick must be greater than zero")
        if request.capital <= 0:
            raise BacktestConfigurationError("capital must be greater than zero")
