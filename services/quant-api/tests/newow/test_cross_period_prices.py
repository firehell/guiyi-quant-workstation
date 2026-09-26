from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import pytest
from guiyi_quant.newow.cross_period_prices import (
    PriceSource,
    select_cross_period_prices,
)

END = datetime(2026, 9, 24, 7, tzinfo=UTC)


def fact(value, frequency="1d", category="page_batch"):
    return PriceSource(
        Decimal(value),
        frequency,
        END,
        "RB2701",
        "owner",
        "calc",
        "canonical-source",
        category,
    )


def select(price="100", **kwargs):
    return select_cross_period_prices(
        as_of=END,
        current=fact(price, category="canonical_completed_close"),
        previous_close=None,
        daily_signal=kwargs.pop("daily_signal", "buy"),
        weekly_signal=kwargs.pop("weekly_signal", "hold"),
        target_daily=fact("100"),
        target_weekly=fact("150", "1w"),
        target_monthly=fact("200", "1M"),
        cost_daily=fact("80"),
        cost_weekly=fact("70", "1w"),
        **kwargs,
    )


@pytest.mark.parametrize(
    "price,frequency",
    [
        ("100", "1d"),
        ("100.49", "1d"),
        ("100.50", "1w"),
        ("150.74", "1w"),
        ("150.75", "1M"),
    ],
)
def test_buffer_inclusive_boundary(price, frequency):
    assert select(price)["shared"]["target"]["frequency"] == frequency


def test_daily_hold_does_not_upgrade_and_only_daily_positive_stops_at_week():
    assert select("999", daily_signal="hold")["shared"]["target"]["frequency"] == "1d"
    assert select("999", weekly_signal="wait")["shared"]["target"]["frequency"] == "1w"


def test_absorb_only_week_positive_still_prefers_daily():
    assert select(daily_signal="wait")["shared"]["absorb"]["frequency"] == "1d"


def test_weekly_status_card_override_is_separate_surface():
    r = select(
        "999",
        period="week",
        weekly_override=(
            fact("160", "1w", "canonical_channel"),
            fact("60", "1w", "canonical_channel"),
        ),
    )
    assert r["shared"]["target"]["frequency"] == "1M"
    assert r["status_card"]["target"]["frequency"] == "1w"
    assert r["status_card"]["target"]["raw"] == "160"


def test_previous_close_must_be_prior_same_contract_canonical_close():
    prev = replace(
        fact("60", category="canonical_previous_daily_close"),
        bar_end=END - timedelta(days=1),
    )
    r = select_cross_period_prices(
        as_of=END,
        current=fact("100", category="canonical_completed_close"),
        previous_close=prev,
        daily_signal="buy",
        weekly_signal="wait",
        target_daily=fact("150"),
    )
    assert r["shared"]["target"]["display_value"] == "120.00"
    for bad in (
        replace(prev, physical_contract="RB2610"),
        replace(prev, bar_end=END),
        replace(prev, source_category="settlement"),
    ):
        with pytest.raises(ValueError):
            select_cross_period_prices(
                as_of=END,
                current=fact("100"),
                previous_close=bad,
                daily_signal="buy",
                weekly_signal="wait",
            )


def test_price_family_conflict_and_future_source_are_rejected():
    for f in (
        fact("120", category="canonical_channel"),
        replace(fact("120"), bar_end=END + timedelta(days=1)),
    ):
        with pytest.raises(ValueError, match="SOURCE_CONFLICT"):
            select_cross_period_prices(
                as_of=END,
                current=fact("100"),
                previous_close=None,
                daily_signal="buy",
                weekly_signal="hold",
                target_daily=f,
            )


def test_rejects_settlement_current_and_previous_close_from_old_calculation_segment():
    with pytest.raises(ValueError, match="SOURCE_CONFLICT"):
        select_cross_period_prices(
            as_of=END,
            current=fact("100", category="settlement"),
            previous_close=None,
            daily_signal="buy",
            weekly_signal="hold",
        )
    previous = replace(
        fact("99", category="canonical_previous_daily_close"),
        bar_end=END - timedelta(days=1),
        calculation_segment_id="old-calculation",
    )
    with pytest.raises(ValueError, match="SOURCE_CONFLICT"):
        select_cross_period_prices(
            as_of=END,
            current=fact("100", category="canonical_completed_close"),
            previous_close=previous,
            daily_signal="buy",
            weekly_signal="hold",
        )
