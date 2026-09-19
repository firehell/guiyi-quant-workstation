"""Deterministic W1 interruption proof from authoritative physical D1 facts.

The caller supplies completed-week endpoints from Calendar/Session and a pinned
D1 revision. This module never chooses a calendar, reads data, or makes a Bar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
import json

from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey, DatasetKind
from app.market_data.source_quality import (
    NonpositiveCloseFact,
    PriceUnavailableFact,
    SourceQualityFact,
)


WEEKLY_SOURCE_CLASSIFICATION_VERSION = "weekly-d1-quality-v1"
WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2 = "weekly-d1-quality-v2"


def weekly_daily_revision_sha256(
    partition_revisions: tuple[tuple[str, str | None], ...],
    daily_bars: tuple[CanonicalBar, ...],
) -> str:
    """Bind a week proof to selected D1 URIs, quality digests and Bar values."""

    payload = {
        "partitions": partition_revisions,
        "bars": tuple(
            (
                bar.bar_end.isoformat(), bar.trading_day.isoformat(),
                *(str(getattr(bar, field)) for field in (
                    "open", "high", "low", "close", "volume", "turnover", "open_interest"
                )),
            )
            for bar in daily_bars
        ),
    }
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class WeeklySourceInterruption:
    product: str
    physical_contract: str
    iso_year: int
    iso_week: int
    week_end: datetime
    expected_daily_endpoints: tuple[tuple[datetime, date], ...]
    unavailable_days: tuple[date, ...]
    quality_source_hashes: tuple[tuple[str, str], ...]
    daily_revision_sha256: str
    source_identity: str
    classification_version: str = WEEKLY_SOURCE_CLASSIFICATION_VERSION
    quality_classifications: tuple[str, ...] = ()

    @property
    def bar_end(self) -> datetime:
        return self.week_end

    @property
    def trading_day(self) -> date:
        return self.expected_daily_endpoints[-1][1]


@dataclass(frozen=True, slots=True)
class WeeklySourceCoverage:
    """Exactly one normal complete week or one proved price interruption."""

    daily_bars: tuple[CanonicalBar, ...]
    interruption: WeeklySourceInterruption | None


def classify_weekly_source(
    *,
    product: str,
    physical_contract: str,
    expected_daily_endpoints: tuple[tuple[datetime, date], ...],
    daily_bars: tuple[CanonicalBar, ...],
    price_unavailable: tuple[SourceQualityFact, ...],
    daily_revision_sha256: str,
    classification_version: str = WEEKLY_SOURCE_CLASSIFICATION_VERSION,
) -> WeeklySourceCoverage:
    """Require a disjoint, exhaustive explanation for every completed D1 endpoint."""

    DatasetKey(DatasetKind.CONTRACT, product, physical_contract, BarFrequency.D1)
    if classification_version not in {
        WEEKLY_SOURCE_CLASSIFICATION_VERSION,
        WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2,
    }:
        raise ValueError("WEEKLY_SOURCE_CLASSIFICATION_INVALID")
    if not _digest(daily_revision_sha256):
        raise ValueError("WEEKLY_SOURCE_REVISION_INVALID")
    expected = tuple(expected_daily_endpoints)
    if not expected or any(
        not isinstance(point, tuple) or len(point) != 2
        or not isinstance(point[0], datetime)
        or point[0].tzinfo is None or point[0].utcoffset() is None
        or type(point[1]) is not date
        for point in expected
    ):
        raise ValueError("WEEKLY_SOURCE_WEEK_INVALID")
    expected = tuple((end.astimezone(UTC), day) for end, day in expected)
    if tuple(sorted(set(expected))) != expected or len({day for _, day in expected}) != len(expected):
        raise ValueError("WEEKLY_SOURCE_WEEK_INVALID")
    week = expected[-1][1].isocalendar()
    if any(day.isocalendar()[:2] != week[:2] for _, day in expected):
        raise ValueError("WEEKLY_SOURCE_WEEK_INVALID")

    bars = tuple(daily_bars)
    gaps = tuple(price_unavailable)
    allowed_facts = (
        (PriceUnavailableFact, NonpositiveCloseFact)
        if classification_version == WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2
        else (PriceUnavailableFact,)
    )
    if any(not isinstance(bar, CanonicalBar) for bar in bars) or any(
        not isinstance(gap, allowed_facts) for gap in gaps
    ):
        raise ValueError("WEEKLY_SOURCE_FACT_INVALID")
    bar_points = tuple((bar.bar_end, bar.trading_day) for bar in bars)
    gap_points = tuple((gap.bar_end, gap.trading_day) for gap in gaps)
    if bar_points != tuple(sorted(bar_points)) or gap_points != tuple(sorted(gap_points)):
        raise ValueError("WEEKLY_SOURCE_ENDPOINTS_ORDER_INVALID")
    if len(set(bar_points)) != len(bar_points) or len(set(gap_points)) != len(gap_points):
        raise ValueError("WEEKLY_SOURCE_ENDPOINTS_DUPLICATE")
    if set(bar_points) & set(gap_points):
        raise ValueError("WEEKLY_SOURCE_ENDPOINTS_OVERLAP")
    actual = set(bar_points) | set(gap_points)
    required = set(expected)
    if actual - required:
        raise ValueError("WEEKLY_SOURCE_ENDPOINTS_EXTRA")
    if required - actual:
        raise ValueError("WEEKLY_SOURCE_ENDPOINTS_MISSING")
    if not gaps:
        return WeeklySourceCoverage(bars, None)

    ordered_gaps = tuple(sorted(gaps, key=lambda gap: gap.bar_end))
    quality_hashes = tuple(
        (gap.request_sha256, gap.response_sha256) for gap in ordered_gaps
    )
    identity_input = {
        "version": classification_version,
        "product": product,
        "contract": physical_contract,
        "expected": [(end.isoformat(), day.isoformat()) for end, day in expected],
        "quality": [
            ((gap.classification,) if classification_version
             == WEEKLY_SOURCE_CLASSIFICATION_VERSION_V2 else ())
            + (gap.bar_end.isoformat(), gap.trading_day.isoformat(), *hashes)
            for gap, hashes in zip(ordered_gaps, quality_hashes, strict=True)
        ],
        "daily_revision_sha256": daily_revision_sha256,
    }
    source_identity = hashlib.sha256(json.dumps(
        identity_input, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return WeeklySourceCoverage((), WeeklySourceInterruption(
        product=product,
        physical_contract=physical_contract,
        iso_year=week.year,
        iso_week=week.week,
        week_end=expected[-1][0],
        expected_daily_endpoints=expected,
        unavailable_days=tuple(gap.trading_day for gap in ordered_gaps),
        quality_source_hashes=quality_hashes,
        daily_revision_sha256=daily_revision_sha256,
        source_identity=source_identity,
        classification_version=classification_version,
        quality_classifications=tuple(gap.classification for gap in ordered_gaps),
    ))


def _digest(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        letter in "0123456789abcdef" for letter in value
    )
