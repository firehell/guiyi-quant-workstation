"""A missing weekly price is explainable only by a complete D1 source proof."""

from datetime import UTC, date, datetime
from decimal import Decimal
import hashlib
import json

import pytest

from app.market_data.domain import CanonicalBar
from app.market_data.source_quality import NonpositiveCloseFact, PriceUnavailableFact
from app.market_data.weekly_quality import classify_weekly_source


def _end(day: int) -> datetime:
    return datetime(2026, 9, day, 7, tzinfo=UTC)


def _bar(day: int) -> CanonicalBar:
    return CanonicalBar(
        _end(day), date(2026, 9, day), Decimal("10"), Decimal("11"),
        Decimal("9"), Decimal("10"), Decimal("1"), Decimal("10"), None,
    )


def _unavailable(day: int) -> PriceUnavailableFact:
    return PriceUnavailableFact(
        _end(day), date(2026, 9, day), Decimal(0), Decimal(0),
        Decimal(0), Decimal("10"), Decimal(1), Decimal(10), None,
        "a" * 64, "b" * 64, _end(day),
    )


def _nonpositive(day: int) -> NonpositiveCloseFact:
    return NonpositiveCloseFact(
        _end(day), date(2026, 9, day), Decimal(10), Decimal(11),
        Decimal(0), Decimal(0), Decimal(1), Decimal(10), None,
        "a" * 64, "b" * 64, _end(day),
    )


def _expected(*days: int) -> tuple[tuple[datetime, date], ...]:
    return tuple((_end(day), date(2026, 9, day)) for day in days)


def _classify(*, expected=None, bars=None, gaps=(), quality_facts=None, **kwargs):
    return classify_weekly_source(
        product="au", physical_contract="AU2612",
        expected_daily_endpoints=expected or _expected(7, 8, 9, 10, 11),
        daily_bars=bars if bars is not None else tuple(_bar(day) for day in (7, 8, 10, 11)),
        price_unavailable=gaps if quality_facts is None else quality_facts,
        daily_revision_sha256="c" * 64,
        **kwargs,
    )


def test_complete_normal_week_has_no_interruption():
    result = _classify(bars=tuple(_bar(day) for day in (7, 8, 9, 10, 11)))
    assert result.interruption is None
    assert len(result.daily_bars) == 5


def test_complete_week_with_no_trade_daily_fact_is_not_a_price_interruption():
    no_trade = CanonicalBar(
        _end(9), date(2026, 9, 9),
        *(Decimal(0) for _ in range(6)), None,
    )
    bars = tuple(no_trade if day == 9 else _bar(day)
                 for day in (7, 8, 9, 10, 11))
    result = _classify(bars=bars)
    assert result.daily_bars == bars
    assert result.interruption is None


def test_one_or_multiple_proven_price_gaps_make_one_weekly_interruption():
    result = _classify(gaps=(_unavailable(9),))
    assert result.daily_bars == ()
    assert result.interruption is not None
    assert result.interruption.week_end == _end(11)
    assert result.interruption.unavailable_days == (date(2026, 9, 9),)
    assert result.interruption.source_identity == _classify(gaps=(_unavailable(9),)).interruption.source_identity

    multiple = _classify(
        bars=tuple(_bar(day) for day in (7, 10, 11)),
        gaps=(_unavailable(8), _unavailable(9)),
    )
    assert multiple.interruption is not None
    assert multiple.interruption.unavailable_days == (date(2026, 9, 8), date(2026, 9, 9))


def test_nonpositive_close_requires_explicit_v2_policy_for_a_weekly_interruption():
    facts = (_nonpositive(9),)
    with pytest.raises(ValueError, match="WEEKLY_SOURCE_FACT_INVALID"):
        _classify(quality_facts=facts)

    result = _classify(
        quality_facts=facts,
        classification_version="weekly-d1-quality-v2",
    )

    assert result.daily_bars == ()
    assert result.interruption is not None
    assert result.interruption.classification_version == "weekly-d1-quality-v2"
    assert result.interruption.unavailable_days == (date(2026, 9, 9),)


def test_v1_price_unavailable_identity_remains_the_pre_v2_identity():
    gap = _unavailable(9)
    result = _classify(gaps=(gap,)).interruption
    assert result is not None
    legacy_payload = {
        "version": "weekly-d1-quality-v1",
        "product": "au",
        "contract": "AU2612",
        "expected": [(end.isoformat(), day.isoformat()) for end, day in _expected(7, 8, 9, 10, 11)],
        "quality": [(gap.bar_end.isoformat(), gap.trading_day.isoformat(), "a" * 64, "b" * 64)],
        "daily_revision_sha256": "c" * 64,
    }
    expected = hashlib.sha256(json.dumps(
        legacy_payload, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    assert result.source_identity == expected


def test_full_price_gap_and_calendar_short_week():
    result = _classify(
        expected=_expected(10, 11), bars=(), gaps=(_unavailable(10), _unavailable(11)),
    )
    assert result.interruption is not None
    assert result.interruption.expected_daily_endpoints == _expected(10, 11)


def test_price_gap_does_not_excuse_another_missing_day():
    with pytest.raises(ValueError, match="WEEKLY_SOURCE_ENDPOINTS_MISSING"):
        _classify(bars=(_bar(7), _bar(8), _bar(11)), gaps=(_unavailable(9),))


def test_unordered_input_does_not_turn_into_normal_week():
    with pytest.raises(ValueError, match="WEEKLY_SOURCE_ENDPOINTS_ORDER_INVALID"):
        _classify(bars=tuple(_bar(day) for day in (8, 7, 9, 10, 11)))


@pytest.mark.parametrize("bars,gaps,code", [
    ((_bar(7), _bar(7), _bar(8), _bar(10), _bar(11)), (_unavailable(9),), "WEEKLY_SOURCE_ENDPOINTS_DUPLICATE"),
    ((_bar(7), _bar(8), _bar(9), _bar(10), _bar(11)), (_unavailable(9),), "WEEKLY_SOURCE_ENDPOINTS_OVERLAP"),
    ((_bar(7), _bar(8), _bar(10), _bar(11), _bar(12)), (_unavailable(9),), "WEEKLY_SOURCE_ENDPOINTS_EXTRA"),
])
def test_conflicting_endpoints_fail_closed(bars, gaps, code):
    with pytest.raises(ValueError, match=code):
        _classify(bars=bars, gaps=gaps)


def test_invalid_revision_or_week_identity_fails_closed():
    with pytest.raises(ValueError, match="WEEKLY_SOURCE_REVISION_INVALID"):
        classify_weekly_source(
            product="au", physical_contract="AU2612",
            expected_daily_endpoints=_expected(7, 8),
            daily_bars=(_bar(7), _bar(8)), price_unavailable=(),
            daily_revision_sha256="unknown",
        )
    with pytest.raises(ValueError, match="WEEKLY_SOURCE_WEEK_INVALID"):
        _classify(expected=_expected(7, 14), bars=(_bar(7), _bar(14)))


def test_daily_revision_change_invalidates_weekly_interruption_identity():
    first = _classify(gaps=(_unavailable(9),)).interruption
    second = classify_weekly_source(
        product="au", physical_contract="AU2612",
        expected_daily_endpoints=_expected(7, 8, 9, 10, 11),
        daily_bars=tuple(_bar(day) for day in (7, 8, 10, 11)),
        price_unavailable=(_unavailable(9),),
        daily_revision_sha256="d" * 64,
    ).interruption
    assert first is not None and second is not None
    assert first.source_identity != second.source_identity
