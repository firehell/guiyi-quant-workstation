from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.data_sources.roles import DataRole


@dataclass(frozen=True)
class MarketDataQuery:
    symbol: str
    contract: str
    period: str
    start: datetime
    end: datetime
    limit: int | None = None


class MarketDataProvider(ABC):
    """Abstract read boundary for local standardized market data."""

    data_role: DataRole
    provider_names: frozenset[str]

    @abstractmethod
    def load_bars(self, query: MarketDataQuery) -> list[dict[str, Any]]:
        """Load historical bars for the query."""

    @abstractmethod
    def load_latest_bars(self, symbol: str, contract: str, period: str, limit: int) -> list[dict[str, Any]]:
        """Load the latest bars for signal or preview use."""

    @abstractmethod
    def get_quality_status(self, query: MarketDataQuery) -> dict[str, Any]:
        """Return an aggregate quality status for the query."""
