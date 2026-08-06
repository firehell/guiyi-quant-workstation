"""Session-aligned, strict historical MarketDataService probe windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Callable, Sequence

from app.data_core.aggregation import AggregationSession
from app.data_core.contracts import DatasetKey
from app.data_core.historical_sessions import build_provider_sessions


class ProbePosition(StrEnum):
    FIRST = "first"
    LAST = "last"


class MarketDataProbeError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ProbeWindow:
    start: datetime
    end: datetime


class SessionAlignedMarketDataProbe:
    """Choose one complete expected bar; never query arbitrary partition edges."""

    def __init__(
        self,
        *,
        session_provider: Callable[
            [DatasetKey, datetime, datetime], Sequence[AggregationSession]
        ],
    ) -> None:
        self._session_provider = session_provider

    def plan(
        self,
        dataset: DatasetKey,
        *,
        start: datetime,
        end: datetime,
        position: ProbePosition = ProbePosition.FIRST,
    ) -> ProbeWindow:
        sessions = self._session_provider(dataset, start, end)
        expected_ends = tuple(
            bar_end
            for session in build_provider_sessions(
                dataset, start=start, end=end, sessions=sessions
            )
            for bar_end in session.expected_bar_ends
        )
        if not expected_ends:
            raise MarketDataProbeError("MARKET_DATA_PROBE_UNAVAILABLE")
        bar_end = expected_ends[0 if position is ProbePosition.FIRST else -1]
        return ProbeWindow(start=bar_end - timedelta(microseconds=1), end=bar_end)
