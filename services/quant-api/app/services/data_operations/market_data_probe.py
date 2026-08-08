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


class ProbeReasonCode(StrEnum):
    CALENDAR_MISSING = "calendar_missing"
    SESSION_MISSING = "session_missing"
    PROBE_WINDOW_UNAVAILABLE = "probe_window_unavailable"
    DATASET_MISSING = "dataset_missing"
    COVERAGE_MISSING = "coverage_missing"
    CATALOG_GAP = "catalog_gap"
    MANIFEST_INVALID = "manifest_invalid"
    READER_EMPTY = "reader_empty"
    READER_ERROR = "reader_error"


class MarketDataProbeError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ProbeWindow:
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class ProbeOutcome:
    """Bounded M2/session-aligned probe result; reason_code only when unreadable."""

    readable: bool
    reason_code: str | None = None


def classify_probe_exception(exc: BaseException) -> str:
    """Map existing reader/probe error codes into the bounded M2 reason set."""
    code = str(getattr(exc, "code", "") or type(exc).__name__).upper()
    if "CALENDAR" in code:
        return ProbeReasonCode.CALENDAR_MISSING.value
    if "SESSION" in code:
        return ProbeReasonCode.SESSION_MISSING.value
    if "GAP" in code:
        return ProbeReasonCode.CATALOG_GAP.value
    if "MANIFEST" in code:
        return ProbeReasonCode.MANIFEST_INVALID.value
    if "COVERAGE" in code or "PARTITION" in code:
        return ProbeReasonCode.COVERAGE_MISSING.value
    if "DATASET" in code or "NOT_FOUND" in code or "MISSING" in code:
        return ProbeReasonCode.DATASET_MISSING.value
    if "PROBE" in code or code == "MARKET_DATA_PROBE_UNAVAILABLE":
        return ProbeReasonCode.PROBE_WINDOW_UNAVAILABLE.value
    return ProbeReasonCode.READER_ERROR.value


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
