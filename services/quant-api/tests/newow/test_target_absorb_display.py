from __future__ import annotations

import importlib
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

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
    StrategyReplay,
)


def test_missing_selection_contract_is_not_zero() -> None:
    context = align_completed_context({}, datetime(2026, 1, 5, 7, tzinfo=UTC))
    try:
        module = importlib.import_module("guiyi_quant.newow.target_absorb_display")
    except ModuleNotFoundError:
        pytest.fail("calculate_target_absorb is not implemented", pytrace=False)

    result = module.calculate_target_absorb(context, evidence=None)

    assert result.status == "evidence_required"
    assert result.evidence_status == "EVIDENCE_REQUIRED"
    assert result.reason_code == "NEWOW_TARGET_ABSORB_EVIDENCE_REQUIRED"
    assert result.value is None


@pytest.mark.parametrize(
    ("raw", "previous_close", "expected"),
    [
        (None, None, Decimal("0")),
        (Decimal("NaN"), None, Decimal("0")),
        (Decimal("Infinity"), None, Decimal("0")),
        (Decimal("-1"), None, Decimal("0")),
        (Decimal("12.345"), None, Decimal("12.35")),
        (Decimal("40"), Decimal("100"), Decimal("50.00")),
        (Decimal("250"), Decimal("100"), Decimal("200.00")),
        (Decimal("125.125"), Decimal("100"), Decimal("125.13")),
    ],
)
def test_page_price_guard_preserves_verified_invalid_and_clamp_branches(
    raw: Decimal | None,
    previous_close: Decimal | None,
    expected: Decimal,
) -> None:
    module = importlib.import_module("guiyi_quant.newow.target_absorb_display")
    guard = getattr(module, "guard_page_price", None)
    assert guard is not None, "guard_page_price is not implemented"

    assert guard(raw, previous_close) == expected


def _target_api():
    module = importlib.import_module("guiyi_quant.newow.target_absorb_display")
    required = (
        "PagePriceFact",
        "PageSelectionInputs",
        "PageSelectionPeriod",
        "VerifiedTargetAbsorbEvidence",
        "select_page_prices",
    )
    missing = tuple(name for name in required if not hasattr(module, name))
    assert not missing, f"target/absorb typed API is not implemented: {missing}"
    return module


def _identity(frequency: ProductFrequency) -> ProductIdentity:
    return ProductIdentity(
        product="rb",
        strategy=ProductStrategy.TREND,
        frequency=frequency,
        formula_versions=("newow_trend_band_page_v2",),
    )


def _product_bar(
    frequency: ProductFrequency,
    bar_end: datetime,
    *,
    high: str = "105",
    low: str = "95",
    contract: str = "RB2605",
    segment_id: str = "rb:RB2605:owner",
) -> ProductBar:
    return ProductBar(
        NewowDailyBar(
            product="rb",
            physical_contract=contract,
            segment_id=segment_id,
            trading_day=bar_end.date(),
            bar_end=bar_end,
            open=Decimal("99"),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal("100"),
            volume=100,
            open_interest=200,
            source_identity=f"canonical:{frequency}:{bar_end.isoformat()}",
            observation_eligible=True,
            completed=True,
        ),
        frequency,
    )


def _replay(product_bar: ProductBar) -> StrategyReplay:
    identity = _identity(product_bar.frequency)
    frame = StrategyFrame(
        bar=product_bar,
        main_state=MainState.HOLD,
        main_values=(("reference", Decimal("100")),),
        availability=FeatureStatus(
            FeatureRuntimeStatus.READY,
            EvidenceStatus.ACTIVE_CODE_VERIFIED,
        ),
    )
    return StrategyReplay(identity, (frame,), (), (), ())


def _context(*, day_contract: str = "RB2605"):
    weekly_end = datetime(2026, 3, 13, 7, tzinfo=UTC)
    daily_end = datetime(2026, 3, 13, 6, tzinfo=UTC)
    hourly_end = datetime(2026, 3, 13, 5, tzinfo=UTC)
    weekly = _product_bar(ProductFrequency.WEEKLY, weekly_end)
    daily = _product_bar(
        ProductFrequency.DAILY,
        daily_end,
        contract=day_contract,
        segment_id=f"rb:{day_contract}:owner",
    )
    hourly = _product_bar(ProductFrequency.HOURLY, hourly_end)
    snapshot = align_completed_context(
        {"1w": _replay(weekly), "1d": _replay(daily), "60m": _replay(hourly)},
        weekly_end,
    )
    return snapshot, weekly


def _fact(module, slot, value: str):
    return module.PagePriceFact(
        value=Decimal(value),
        frequency=slot.frequency,
        bar_end=slot.bar_end,
        physical_contract=slot.physical_contract,
        segment_id=slot.segment_id,
    )


def _inputs(module, context, **changes):
    values = {
        "signal_daily": "hold",
        "signal_weekly": "hold",
        "cross_weekly_buy": False,
        "current_price": Decimal("100"),
        "target_daily": _fact(module, context.daily, "110.125"),
        "target_weekly": _fact(module, context.weekly, "140"),
        "target": _fact(module, context.daily, "150"),
        "high": _fact(module, context.hourly, "105"),
        "cost_daily": _fact(module, context.daily, "90.125"),
        "cost_weekly": _fact(module, context.weekly, "75"),
        "cost": _fact(module, context.hourly, "80"),
    }
    values.update(changes)
    return module.PageSelectionInputs(**values)


@pytest.mark.parametrize(
    ("period", "target", "target_branch", "absorb", "absorb_branch"),
    [
        ("day", "110.125", "target_daily_hold", "90.125", "absorb_daily_hold"),
        ("week", "140", "target_week_view", "75", "absorb_week_view"),
        (
            "best_available",
            "140",
            "target_weekly_hold",
            "90.125",
            "absorb_daily_hold",
        ),
    ],
)
def test_page_selection_preserves_day_week_and_distinct_best_available_precedence(
    period: str,
    target: str,
    target_branch: str,
    absorb: str,
    absorb_branch: str,
) -> None:
    module = _target_api()
    context, _ = _context()
    inputs = _inputs(module, context)

    selected = module.select_page_prices(inputs, module.PageSelectionPeriod(period))

    assert selected.target is not None
    assert selected.target.fact.value == Decimal(target)
    assert selected.target.branch == target_branch
    assert selected.absorb is not None
    assert selected.absorb.fact.value == Decimal(absorb)
    assert selected.absorb.branch == absorb_branch


def test_page_target_breakout_upgrades_weekly_while_absorb_remains_daily() -> None:
    module = _target_api()
    context, _ = _context()
    inputs = _inputs(
        module,
        context,
        signal_daily="buy",
        current_price=Decimal("111"),
    )

    selected = module.select_page_prices(inputs, module.PageSelectionPeriod.DAY)

    assert selected.target is not None
    assert selected.target.fact.value == Decimal("140")
    assert selected.target.branch == "target_daily_breakout_weekly"
    assert selected.absorb is not None
    assert selected.absorb.fact.value == Decimal("90.125")
    assert selected.absorb.branch == "absorb_daily_buy"


def test_verified_day_result_exposes_sources_identities_and_explicit_gaps() -> None:
    module = _target_api()
    context, _ = _context()
    evidence = module.VerifiedTargetAbsorbEvidence(
        period=module.PageSelectionPeriod.DAY,
        view_frequency=ProductFrequency.DAILY,
        inputs=_inputs(module, context),
    )

    result = module.calculate_target_absorb(context, evidence)

    assert result.status == "ready"
    assert result.evidence_status == "RESEARCH_EVIDENCE_ONLY"
    assert result.formula_versions == (
        "newow_target_absorb_display_selection_page_v2",
        "newow_price_guard_page_v3_1_6",
        "guiyi_newow_target_absorb_segment_adapter_v1",
    )
    assert result.value is not None
    assert result.value.target.raw_value == Decimal("110.125")
    assert result.value.target.display_value == Decimal("110.13")
    assert result.value.target.source_frequency == ProductFrequency.DAILY
    assert result.value.target.bar_end == context.daily.bar_end
    assert result.value.target.physical_contract == "RB2605"
    assert result.value.target.segment_id == "rb:RB2605:owner"
    assert result.value.absorb.raw_value == Decimal("90.125")
    assert result.value.absorb.display_value == Decimal("90.13")
    assert result.value.previous_close is None
    gaps = {item.name: item for item in result.value.subfeatures}
    assert gaps["page_selection"].status.status == "ready"
    assert gaps["price_guard_algorithm"].status.status == "ready"
    for name in (
        "previous_close_activation",
        "unified_short_history_warmup",
        "original_page_timing",
        "futures_cross_segment_parity",
    ):
        assert gaps[name].status.status == "evidence_required"
        assert gaps[name].status.evidence_status == "EVIDENCE_REQUIRED"
        assert gaps[name].value is None
        assert gaps[name].status.reason_code is not None
    assert result.actions == ()
    assert result.hints == ()
    assert result.reference_trades == ()


def _weekly_channel_bars(last: ProductBar, count: int) -> tuple[ProductBar, ...]:
    start_day = last.bar.bar_end.date().toordinal() - (count - 1) * 7
    bars = []
    for index in range(count):
        day = datetime.fromordinal(start_day + index * 7).replace(hour=7, tzinfo=UTC)
        bars.append(
            _product_bar(
                ProductFrequency.WEEKLY,
                day,
                high=str(110 + index),
                low=str(90 - index),
            )
        )
    assert bars[-1].bar.bar_end == last.bar.bar_end
    return tuple(bars)


def test_weekly_status_card_override_reuses_full_hhv_llv10_channel() -> None:
    module = _target_api()
    context, latest_weekly = _context()
    evidence = module.VerifiedTargetAbsorbEvidence(
        period=module.PageSelectionPeriod.WEEK,
        view_frequency=ProductFrequency.WEEKLY,
        inputs=_inputs(module, context),
        weekly_channel_bars=_weekly_channel_bars(latest_weekly, 10),
    )

    result = module.calculate_target_absorb(context, evidence)

    assert result.value is not None
    assert result.value.target.raw_value == Decimal("119")
    assert result.value.target.branch == "weekly_channel_override"
    assert result.value.absorb.raw_value == Decimal("81")
    assert result.value.absorb.branch == "weekly_channel_override"
    assert result.value.target.source_frequency == ProductFrequency.WEEKLY
    assert result.value.target.bar_end == context.weekly.bar_end


def test_short_weekly_history_is_evidence_required_not_partial_window() -> None:
    module = _target_api()
    context, latest_weekly = _context()
    evidence = module.VerifiedTargetAbsorbEvidence(
        period=module.PageSelectionPeriod.WEEK,
        view_frequency=ProductFrequency.WEEKLY,
        inputs=_inputs(module, context),
        weekly_channel_bars=_weekly_channel_bars(latest_weekly, 9),
    )

    result = module.calculate_target_absorb(context, evidence)

    assert result.status == "evidence_required"
    assert result.reason_code == "NEWOW_TARGET_ABSORB_WEEKLY_WARMUP_EVIDENCE_REQUIRED"
    assert result.value is None


def test_missing_context_is_unavailable_without_zero_or_cross_frequency_fallback() -> (
    None
):
    module = _target_api()
    context = align_completed_context({}, datetime(2026, 3, 13, 7, tzinfo=UTC))
    evidence = module.VerifiedTargetAbsorbEvidence(
        period=module.PageSelectionPeriod.DAY,
        view_frequency=ProductFrequency.DAILY,
        inputs=module.PageSelectionInputs(),
    )

    result = module.calculate_target_absorb(context, evidence)

    assert result.status == "unavailable"
    assert result.reason_code == "NEWOW_TARGET_ABSORB_VIEW_CONTEXT_UNAVAILABLE"
    assert result.value is None


def test_selected_cross_owner_value_is_unavailable_instead_of_borrowed() -> None:
    module = _target_api()
    context, _ = _context(day_contract="RB2610")
    inputs = _inputs(module, context)
    inputs = replace(
        inputs,
        target_daily=replace(
            inputs.target_daily,
            physical_contract="RB2605",
            segment_id="rb:RB2605:owner",
        ),
    )
    evidence = module.VerifiedTargetAbsorbEvidence(
        period=module.PageSelectionPeriod.DAY,
        view_frequency=ProductFrequency.DAILY,
        inputs=inputs,
    )

    result = module.calculate_target_absorb(context, evidence)

    assert result.status == "unavailable"
    assert result.reason_code == "NEWOW_TARGET_ABSORB_SOURCE_CONTEXT_MISMATCH"
    assert result.value is None


def test_daily_candidate_cannot_be_relabelled_from_weekly_context() -> None:
    module = _target_api()
    context, _ = _context()
    inputs = _inputs(module, context)
    inputs = replace(
        inputs,
        target_daily=_fact(module, context.weekly, "110.125"),
    )
    evidence = module.VerifiedTargetAbsorbEvidence(
        period=module.PageSelectionPeriod.DAY,
        view_frequency=ProductFrequency.DAILY,
        inputs=inputs,
    )

    result = module.calculate_target_absorb(context, evidence)

    assert result.status == "unavailable"
    assert result.reason_code == "NEWOW_TARGET_ABSORB_SOURCE_FREQUENCY_MISMATCH"
    assert result.value is None


def test_unverified_boolean_or_wrong_hash_cannot_enable_page_behavior() -> None:
    module = _target_api()
    context, _ = _context()
    with pytest.raises(ValueError, match="NEWOW_TARGET_ABSORB_INVALID_EVIDENCE"):
        module.calculate_target_absorb(context, True)
    with pytest.raises(ValueError, match="NEWOW_TARGET_ABSORB_EVIDENCE_IDENTITY"):
        module.VerifiedTargetAbsorbEvidence(
            period=module.PageSelectionPeriod.DAY,
            view_frequency=ProductFrequency.DAILY,
            inputs=_inputs(module, context),
            manifest_sha256="0" * 64,
        )
