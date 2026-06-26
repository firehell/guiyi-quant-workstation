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
    def get_bars(self, query: MarketDataQuery) -> list[dict[str, Any]]:
        """Load historical bars for the query."""

    @abstractmethod
    def get_contracts(self) -> list[dict[str, Any]]:
        """Return contracts or coverage records visible to this provider."""

    @abstractmethod
    def get_quality_status(self, query: MarketDataQuery) -> dict[str, Any]:
        """Return an aggregate quality status for the query."""

    def load_bars(self, query: MarketDataQuery) -> list[dict[str, Any]]:
        """Compatibility alias for existing service naming."""
        return self.get_bars(query)
