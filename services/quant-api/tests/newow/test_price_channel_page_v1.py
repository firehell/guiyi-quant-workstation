from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest

from guiyi_quant.newow.price_channel import (
    TARGET_ABSORB_CHANNEL_PAGE_V1,
    TARGET_ABSORB_DISPLAY_PAGE_V1,
    DisplayPeriod,
    MultiPeriodPriceFacts,
    PageSignalState,
    calculate_price_channel,
    select_display_prices,
)
from guiyi_quant.newow.research_backtest import NewowResearchBar


UTC = timezone.utc
GOLDEN = (
    Path(__file__).parent
    / "golden"
    / "newow_v3_2_82_page_facts.json"
)


def _bar(
    index: int,
    *,
    value: Decimal | None = None,
    volume: int = 100,
    product: str = "rb",
    contract: str = "RB2701",
    segment: str = "rb-2701-a",
    frequency: str = "1d",
    source: str | None = None,
) -> NewowResearchBar:
    close = value if value is not None else Decimal("100") + index
    bar_end = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index)
    return NewowResearchBar(
        product=product,
        physical_contract=contract,
        segment_id=segment,
        trading_day=date(2026, 1, 1) + timedelta(days=index),
        bar_end=bar_end,
        open=close,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        volume=volume,
        open_interest=1000,
        source_identity=source or f"fixture-{index}",
        observation_eligible=True,
        completed=True,
        frequency=frequency,
    )


def _bars(count: int) -> tuple[NewowResearchBar, ...]:
    return tuple(_bar(index) for index in range(count))


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("fixture decimal must be a string or null")
    return Decimal(value)


def _signal(value: object) -> PageSignalState | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("fixture signal must be a string or null")
    return PageSignalState(value)


def _facts(case: dict[str, object]) -> MultiPeriodPriceFacts:
    return MultiPeriodPriceFacts(
        target_daily=_optional_decimal(case.get("target_daily")),
        target_weekly=_optional_decimal(case.get("target_weekly")),
        absorb_daily=_optional_decimal(case.get("absorption_daily")),
        absorb_weekly=_optional_decimal(case.get("absorption_weekly")),
        signal_daily=_signal(case.get("daily_signal")),
        signal_weekly=_signal(case.get("weekly_signal")),
        cross_weekly_buy=case.get("cross_weekly") == "buy",
        fallback_target=_optional_decimal(case.get("fallback_target")),
        fallback_high=_optional_decimal(case.get("fallback_high")),
        fallback_absorb=_optional_decimal(case.get("fallback_absorption")),
    )


def _fixture_cases() -> list[dict[str, object]]:
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return data["display_selection_cases"]


def _page_value(value: Decimal | None) -> str:
    return "0.00" if value is None else format(value, ".2f")


def test_price_channel_requires_full_window_and_includes_current_bar() -> None:
    bars = _bars(11)

    points = calculate_price_channel(bars, window=10)

    assert len(points) == 11
    assert points[8].available is False
    assert points[8].target is None
    assert points[9].target == max(bar.high for bar in bars[:10])
    assert points[10].absorb == min(bar.low for bar in bars[1:11])
    assert points[10].formula_version == TARGET_ABSORB_CHANNEL_PAGE_V1
    with pytest.raises(FrozenInstanceError):
        points[10].target = Decimal("1")  # type: ignore[misc]


@pytest.mark.parametrize("window", (True, 0, -1, 4, 121, 10.0))
def test_price_channel_rejects_invalid_window(window: object) -> None:
    with pytest.raises(ValueError, match="NEWOW_PRICE_CHANNEL_INVALID_WINDOW"):
        calculate_price_channel(_bars(11), window=window)  # type: ignore[arg-type]


def test_price_channel_rejects_ambiguous_or_mixed_series() -> None:
    bars = _bars(11)
    with pytest.raises(ValueError, match="NEWOW_BACKTEST_BARS_NOT_STRICTLY_ORDERED"):
        calculate_price_channel(tuple(reversed(bars)), window=10)
    with pytest.raises(ValueError, match="NEWOW_BACKTEST_DUPLICATE_SOURCE_IDENTITY"):
        calculate_price_channel(
            (*bars[:10], replace(bars[10], source_identity=bars[9].source_identity)),
            window=10,
        )
    with pytest.raises(ValueError, match="NEWOW_BACKTEST_MIXED_PRODUCT"):
        calculate_price_channel(
            (*bars[:10], _bar(10, product="sc", contract="SC2701")), window=10
        )
    with pytest.raises(ValueError, match="NEWOW_BACKTEST_MIXED_FREQUENCY"):
        calculate_price_channel(
            (*bars[:10], _bar(10, frequency="1w")), window=10
        )
    with pytest.raises(ValueError, match="NEWOW_PRICE_CHANNEL_MIXED_SERIES"):
        calculate_price_channel(
            (*bars[:10], _bar(10, contract="RB2705", segment="rb-2705-b")),
            window=10,
        )


def test_price_channel_accepts_zero_volume_because_channel_is_price_only() -> None:
    bars = (*_bars(10), _bar(10, volume=0))

    point = calculate_price_channel(bars, window=10)[-1]

    assert point.available is True
    assert point.target == Decimal("111")
    assert point.absorb == Decimal("100")


@pytest.mark.parametrize("case", _fixture_cases(), ids=lambda case: case["case_id"])
def test_display_selection_matches_v3282_fixture(case: dict[str, object]) -> None:
    result = select_display_prices(
        _facts(case),
        view_period=DisplayPeriod(case["view_period"]),
        current_price=Decimal(case["current_price"]),
        previous_close=_optional_decimal(case["previous_close"]),
    )

    assert _page_value(result.target) == case["expected_target"]
    assert _page_value(result.absorb) == case["expected_absorption"]
    assert result.formula_version == TARGET_ABSORB_DISPLAY_PAGE_V1
    if case["case_id"] == "missing_period_fields_fallback":
        assert result.absorb is None


def test_display_selection_exposes_independent_periods_and_branch_tokens() -> None:
    result = select_display_prices(
        MultiPeriodPriceFacts(
            target_daily=Decimal("10"),
            target_weekly=Decimal("12"),
            absorb_daily=Decimal("8"),
            absorb_weekly=Decimal("7"),
            signal_daily=PageSignalState.WAIT,
            signal_weekly=PageSignalState.BUY,
            cross_weekly_buy=False,
        ),
        view_period=DisplayPeriod.DAY,
        current_price=Decimal("9"),
        previous_close=Decimal("9"),
    )

    assert result.target_period is DisplayPeriod.WEEK
    assert result.absorb_period is DisplayPeriod.DAY
    assert result.target_branch_token == "WEEKLY_BUY"
    assert result.absorb_branch_token == "WEEKLY_POSITIVE_DAILY_ABSORB"


@pytest.mark.parametrize(
    ("current", "previous", "error"),
    (
        (Decimal("0"), Decimal("10"), "NEWOW_DISPLAY_PRICE_FACTS_INCOMPLETE"),
        (Decimal("NaN"), Decimal("10"), "NEWOW_DISPLAY_PRICE_FACTS_INCOMPLETE"),
        (Decimal("10"), Decimal("0"), "NEWOW_DISPLAY_PRICE_FACTS_INCOMPLETE"),
    ),
)
def test_display_selection_rejects_invalid_market_prices(
    current: Decimal, previous: Decimal, error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        select_display_prices(
            MultiPeriodPriceFacts(
                target_daily=Decimal("10"),
                target_weekly=None,
                absorb_daily=Decimal("8"),
                absorb_weekly=None,
                signal_daily=PageSignalState.BUY,
                signal_weekly=PageSignalState.WAIT,
                cross_weekly_buy=False,
            ),
            view_period=DisplayPeriod.DAY,
            current_price=current,
            previous_close=previous,
        )
