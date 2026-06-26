from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.vnpy_integration.errors import VnpyNotInstalledError
from app.vnpy_integration.execution_policy import DEFAULT_EXECUTION_TIMING, ExecutionTiming


def require_vnpy(module: str = "vnpy") -> Any:
    """Import vn.py lazily at the adapter boundary."""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise VnpyNotInstalledError(module) from exc


@dataclass(frozen=True)
class VnpyBacktestSettings:
    vt_symbol: str
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
    execution_timing: ExecutionTiming = DEFAULT_EXECUTION_TIMING

    def to_vnpy_kwargs(self) -> dict[str, Any]:
        return {
            "vt_symbol": self.vt_symbol,
            "interval": self.interval,
            "start": self.start,
            "end": self.end,
            "rate": self.rate,
            "slippage": self.slippage,
            "size": self.size,
            "pricetick": self.pricetick,
            "capital": self.capital,
        }
