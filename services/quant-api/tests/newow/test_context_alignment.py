from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest

from guiyi_quant.newow.context_alignment import align_completed_context
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_contracts import (
    EvidenceStatus,
    FeatureRuntimeStatus,
    FeatureStatus,
    MainState,
    ProductBar,
    ProductFrequency,
    ProductIdentity,
    ProductStrategy,
    StrategyFrame,
    StrategyHint,
    StrategyReplay,
)


def _identity(
    frequency: ProductFrequency | str,
    *,
    product: str = "rb",
) -> ProductIdentity:
    return ProductIdentity(
        product=product,
        strategy=ProductStrategy.TREND,
        frequency=ProductFrequency(frequency),
        formula_versions=(
            "newow_escape_d123_page_v2",
            "newow_trend_band_page_v2",
        ),
    )


def _frame(
    identity: ProductIdentity,
    bar_end: datetime,
    *,
    contract: str,
    segment_id: str,
    source_identity: str,
    observation_eligible: bool = True,
    hint_known_at: datetime | None = None,
) -> StrategyFrame:
    product_bar = ProductBar(
        NewowDailyBar(
            product=identity.product,
            physical_contract=contract,
            segment_id=segment_id,
            trading_day=bar_end.date(),
            bar_end=bar_end,
            open=Decimal("100"),
            high=Decimal("102"),
            low=Decimal("99"),
            close=Decimal("101"),
            volume=100,
            open_interest=200,
            source_identity=source_identity,
            observation_eligible=observation_eligible,
            completed=True,
        ),
        identity.frequency,
    )
    hints = (
        (
            StrategyHint(
                identity=identity,
                physical_contract=contract,
                segment_id=segment_id,
                bar_end=bar_end,
                trading_day=bar_end.date(),
                kind="CONFIRMED_FACT",
                known_at=hint_known_at,
                anchor_price=Decimal("101"),
            ),
        )
        if hint_known_at is not None
        else ()
    )
    return StrategyFrame(
        bar=product_bar,
        main_state=MainState.HOLD,
        main_values=(("reference", Decimal("101")),),
        availability=FeatureStatus(
            FeatureRuntimeStatus.READY,
            EvidenceStatus.ACTIVE_CODE_VERIFIED,
        ),
        hints=hints,
    )


def _replay(identity: ProductIdentity, *frames: StrategyFrame) -> StrategyReplay:
    return StrategyReplay(
        identity=identity,
        frames=tuple(frames),
        actions=(),
        hints=tuple(hint for frame in frames for hint in frame.hints),
        diagnostics=(),
    )


def test_each_frequency_uses_its_own_latest_completed_owner_before_as_of() -> None:
    monday = datetime(2026, 1, 5, 6, tzinfo=UTC)
    prior_friday = datetime(2026, 1, 2, 7, tzinfo=UTC)
    future_friday = datetime(2026, 1, 9, 7, tzinfo=UTC)
    prior_daily = datetime(2026, 1, 2, 7, tzinfo=UTC)
    unfinished_daily = datetime(2026, 1, 5, 7, tzinfo=UTC)
    weekly_identity = _identity("1w")
    daily_identity = _identity("1d")
    hourly_identity = _identity("60m")
    inputs = {
        "60m": _replay(
            hourly_identity,
            _frame(
                hourly_identity,
                monday,
                contract="RB2605",
                segment_id="rb:RB2605:hourly",
                source_identity="canonical:hourly:monday",
            ),
        ),
        "1w": _replay(
            weekly_identity,
            _frame(
                weekly_identity,
                prior_friday,
                contract="RB2601",
                segment_id="rb:RB2601:weekly",
                source_identity="canonical:weekly:prior",
            ),
            _frame(
                weekly_identity,
                future_friday,
                contract="RB2605",
                segment_id="rb:RB2605:weekly",
                source_identity="canonical:weekly:future",
            ),
        ),
        "1d": _replay(
            daily_identity,
            _frame(
                daily_identity,
                prior_daily,
                contract="RB2603",
                segment_id="rb:RB2603:daily",
                source_identity="canonical:daily:prior",
            ),
            _frame(
                daily_identity,
                unfinished_daily,
                contract="RB2605",
                segment_id="rb:RB2605:daily",
                source_identity="canonical:daily:unfinished",
            ),
        ),
    }

    result = align_completed_context(inputs, monday)

    assert result.weekly.bar_end == prior_friday
    assert result.weekly.bar_end != future_friday
    assert result.weekly.physical_contract == "RB2601"
    assert result.weekly.segment_id == "rb:RB2601:weekly"
    assert result.daily.bar_end == prior_daily
    assert result.daily.physical_contract == "RB2603"
    assert result.hourly.bar_end == monday
    assert result.hourly.physical_contract == "RB2605"
    assert result.weekly.source_identity == "canonical:weekly:prior"
    assert result.daily.source_identity == "canonical:daily:prior"
    assert result.hourly.source_identity == "canonical:hourly:monday"
    assert result.weekly.formula_versions == weekly_identity.formula_versions
    assert result.as_of == monday
    assert result.missing_frequencies == ()


def test_snapshot_is_immutable_and_disclaims_historical_database_reconstruction() -> (
    None
):
    as_of = datetime(2026, 1, 5, 6, tzinfo=UTC)

    result = align_completed_context({}, as_of)

    assert result.recompute_mode == "current_canonical_cutoff_recompute"
    assert result.historical_database_knowledge_reconstructed is False
    assert result.metadata == (
        ("recompute_mode", "current_canonical_cutoff_recompute"),
        ("historical_database_knowledge_reconstructed", False),
    )
    with pytest.raises(FrozenInstanceError):
        result.as_of = as_of + timedelta(hours=1)  # type: ignore[misc]


def test_missing_one_or_all_frequencies_are_explicitly_unavailable() -> None:
    as_of = datetime(2026, 1, 5, 6, tzinfo=UTC)
    daily_identity = _identity("1d")
    daily = _frame(
        daily_identity,
        datetime(2026, 1, 2, 7, tzinfo=UTC),
        contract="RB2603",
        segment_id="rb:RB2603:daily",
        source_identity="canonical:daily",
    )

    partial = align_completed_context({"1d": _replay(daily_identity, daily)}, as_of)

    assert partial.daily.status is FeatureRuntimeStatus.READY
    assert partial.weekly.status is FeatureRuntimeStatus.UNAVAILABLE
    assert partial.weekly.reason_code == "NEWOW_CONTEXT_MISSING_FREQUENCY"
    assert partial.weekly.frame is None
    assert partial.hourly.status is FeatureRuntimeStatus.UNAVAILABLE
    assert partial.missing_frequencies == (
        ProductFrequency.WEEKLY,
        ProductFrequency.HOURLY,
    )

    empty = align_completed_context({}, as_of)
    assert empty.missing_frequencies == (
        ProductFrequency.WEEKLY,
        ProductFrequency.DAILY,
        ProductFrequency.HOURLY,
    )
    assert all(slot.frame is None for slot in empty.slots)


def test_no_eligible_frame_is_unavailable_without_cross_frequency_fallback() -> None:
    as_of = datetime(2026, 1, 5, 6, tzinfo=UTC)
    weekly_identity = _identity("1w")
    daily_identity = _identity("1d")
    weekly_future = _frame(
        weekly_identity,
        datetime(2026, 1, 9, 7, tzinfo=UTC),
        contract="RB2605",
        segment_id="rb:RB2605:weekly",
        source_identity="canonical:weekly:future",
    )
    daily = _frame(
        daily_identity,
        datetime(2026, 1, 2, 7, tzinfo=UTC),
        contract="RB2603",
        segment_id="rb:RB2603:daily",
        source_identity="canonical:daily",
    )

    result = align_completed_context(
        {
            "1w": _replay(weekly_identity, weekly_future),
            "1d": _replay(daily_identity, daily),
        },
        as_of,
    )

    assert result.weekly.status is FeatureRuntimeStatus.UNAVAILABLE
    assert result.weekly.reason_code == "NEWOW_CONTEXT_NO_ELIGIBLE_FRAME"
    assert result.weekly.frame is None
    assert result.weekly.physical_contract is None
    assert result.daily.frame == daily


def test_confirmation_derived_hints_are_hidden_until_their_own_known_at() -> None:
    identity = _identity("60m")
    bar_end = datetime(2026, 1, 5, 5, tzinfo=UTC)
    known_at = datetime(2026, 1, 5, 7, tzinfo=UTC)
    frame = _frame(
        identity,
        bar_end,
        contract="RB2605",
        segment_id="rb:RB2605:hourly",
        source_identity="canonical:hourly",
        hint_known_at=known_at,
    )

    before = align_completed_context(
        {"60m": _replay(identity, frame)},
        datetime(2026, 1, 5, 6, tzinfo=UTC),
    )
    confirmed = align_completed_context({"60m": _replay(identity, frame)}, known_at)

    assert before.hourly.frame is not None
    assert before.hourly.frame.hints == ()
    assert before.hourly.confirmation_status.status is FeatureRuntimeStatus.UNAVAILABLE
    assert (
        before.hourly.confirmation_status.reason_code
        == "NEWOW_CONTEXT_CONFIRMATION_AFTER_AS_OF"
    )
    assert confirmed.hourly.frame is not None
    assert confirmed.hourly.frame.hints == frame.hints
    assert confirmed.hourly.confirmation_status.status is FeatureRuntimeStatus.READY


def test_observation_ineligible_frame_is_not_selected_as_current_context() -> None:
    identity = _identity("60m")
    eligible = _frame(
        identity,
        datetime(2026, 1, 5, 4, tzinfo=UTC),
        contract="RB2605",
        segment_id="rb:RB2605:hourly",
        source_identity="canonical:hourly:eligible",
    )
    ineligible = _frame(
        identity,
        datetime(2026, 1, 5, 5, tzinfo=UTC),
        contract="RB2605",
        segment_id="rb:RB2605:hourly",
        source_identity="canonical:hourly:preview",
        observation_eligible=False,
    )

    result = align_completed_context(
        {"60m": _replay(identity, eligible, ineligible)},
        datetime(2026, 1, 5, 6, tzinfo=UTC),
    )

    assert result.hourly.bar_end == eligible.bar.bar.bar_end
    assert result.hourly.source_identity == "canonical:hourly:eligible"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("duplicate", "NEWOW_CONTEXT_DUPLICATE_FACT"),
        ("order", "NEWOW_CONTEXT_INPUT_ORDER"),
        ("frequency", "NEWOW_CONTEXT_FREQUENCY_MISMATCH"),
        ("identity", "NEWOW_CONTEXT_IDENTITY_MISMATCH"),
        ("future_knowledge", "NEWOW_CONTEXT_FUTURE_KNOWLEDGE"),
    ],
)
def test_malformed_replays_fail_closed(mutation: str, message: str) -> None:
    identity = _identity("1d")
    first = _frame(
        identity,
        datetime(2026, 1, 2, 7, tzinfo=UTC),
        contract="RB2603",
        segment_id="rb:RB2603:daily",
        source_identity="canonical:daily:first",
    )
    second = _frame(
        identity,
        datetime(2026, 1, 3, 7, tzinfo=UTC),
        contract="RB2603",
        segment_id="rb:RB2603:daily",
        source_identity="canonical:daily:second",
        hint_known_at=datetime(2026, 1, 3, 8, tzinfo=UTC),
    )
    replay = _replay(identity, first, second)

    if mutation == "duplicate":
        object.__setattr__(replay, "frames", (first, first))
    elif mutation == "order":
        object.__setattr__(replay, "frames", (second, first))
    elif mutation == "frequency":
        object.__setattr__(replay, "identity", _identity("60m"))
    elif mutation == "identity":
        object.__setattr__(replay, "identity", _identity("1d", product="cu"))
    else:
        (hint,) = second.hints
        object.__setattr__(
            hint, "known_at", second.bar.bar.bar_end - timedelta(seconds=1)
        )

    with pytest.raises(ValueError, match=message):
        align_completed_context({"1d": replay}, datetime(2026, 1, 5, 7, tzinfo=UTC))


def test_cross_frequency_product_or_strategy_conflicts_fail_closed() -> None:
    weekly_identity = _identity("1w")
    daily_identity = _identity("1d", product="cu")
    weekly = _frame(
        weekly_identity,
        datetime(2026, 1, 2, 7, tzinfo=UTC),
        contract="RB2601",
        segment_id="rb:RB2601:weekly",
        source_identity="canonical:weekly",
    )
    daily = _frame(
        daily_identity,
        datetime(2026, 1, 2, 7, tzinfo=UTC),
        contract="CU2603",
        segment_id="cu:CU2603:daily",
        source_identity="canonical:daily",
    )

    with pytest.raises(ValueError, match="NEWOW_CONTEXT_IDENTITY_MISMATCH"):
        align_completed_context(
            {
                "1w": _replay(weekly_identity, weekly),
                "1d": _replay(daily_identity, daily),
            },
            datetime(2026, 1, 5, 7, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "as_of",
    [
        datetime(2026, 1, 5, 7),
        "2026-01-05T07:00:00Z",
    ],
)
def test_malformed_as_of_is_rejected(as_of: object) -> None:
    with pytest.raises(ValueError, match="NEWOW_CONTEXT_INVALID_AS_OF"):
        align_completed_context({}, cast(datetime, as_of))
