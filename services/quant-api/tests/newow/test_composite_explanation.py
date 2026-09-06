from __future__ import annotations

import importlib
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.newow.context_alignment import (
    ContextSnapshot,
    align_completed_context,
)
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
from guiyi_quant.newow.reference_trades import ReferenceTradeProjector


def _api():
    module = importlib.import_module("guiyi_quant.newow.composite_explanation")
    required = (
        "CompositeBias",
        "CompositeStatusFact",
        "CompositeStatusState",
        "FirstActionTokenOwner",
        "VerifiedCompositeEvidence",
        "calculate_composite_explanation",
        "calculate_composite_volatility",
        "calculate_first_action_principle",
        "classify_composite_biases",
        "select_composite_decision",
        "select_week_day_matrix",
    )
    missing = tuple(name for name in required if not hasattr(module, name))
    assert not missing, f"composite typed API is not implemented: {missing}"
    return module


def test_explanation_without_evidence_is_not_a_strategy() -> None:
    context = align_completed_context({}, datetime(2026, 3, 13, 7, tzinfo=UTC))
    try:
        module = importlib.import_module("guiyi_quant.newow.composite_explanation")
    except ModuleNotFoundError:
        pytest.fail("calculate_composite_explanation is not implemented", pytrace=False)

    result = module.calculate_composite_explanation(context, evidence=None)

    assert result.status == "evidence_required"
    assert result.evidence_status == "EVIDENCE_REQUIRED"
    assert result.reason_code == "NEWOW_COMPOSITE_EVIDENCE_REQUIRED"
    assert result.value is None
    for forbidden in (
        "action",
        "actions",
        "order",
        "orders",
        "target_position",
        "reference_trade",
        "reference_trades",
    ):
        assert not hasattr(result, forbidden)


def test_composite_typed_api_contract_exists() -> None:
    _api()


def _identity(frequency: ProductFrequency) -> ProductIdentity:
    return ProductIdentity(
        "rb",
        ProductStrategy.TREND,
        frequency,
        ("newow_trend_band_page_v2",),
    )


def _bar(
    frequency: ProductFrequency,
    bar_end: datetime,
    *,
    true_range: str = "2",
    contract: str = "RB2605",
    segment_id: str = "rb:RB2605:owner",
    source_suffix: str = "0",
) -> ProductBar:
    half = Decimal(true_range) / Decimal("2")
    return ProductBar(
        NewowDailyBar(
            product="rb",
            physical_contract=contract,
            segment_id=segment_id,
            trading_day=bar_end.date(),
            bar_end=bar_end,
            open=Decimal("100"),
            high=Decimal("100") + half,
            low=Decimal("100") - half,
            close=Decimal("100"),
            volume=100,
            open_interest=200,
            source_identity=f"owned:composite:{frequency}:{source_suffix}",
            observation_eligible=True,
            completed=True,
        ),
        frequency,
    )


def _replay(*bars: ProductBar) -> StrategyReplay:
    identity = _identity(bars[0].frequency)
    frames = tuple(
        StrategyFrame(
            bar=bar,
            main_state=MainState.HOLD,
            main_values=(("reference", bar.bar.close),),
            availability=FeatureStatus(
                FeatureRuntimeStatus.READY,
                EvidenceStatus.ACTIVE_CODE_VERIFIED,
            ),
        )
        for bar in bars
    )
    return StrategyReplay(identity, frames, (), (), ())


def _context(
    *,
    daily_count: int = 21,
    true_range: str = "2",
) -> tuple[ContextSnapshot, tuple[ProductBar, ...]]:
    daily_end = datetime(2026, 3, 13, 6, tzinfo=UTC)
    daily_bars = tuple(
        _bar(
            ProductFrequency.DAILY,
            daily_end - timedelta(days=daily_count - 1 - index),
            true_range=true_range,
            source_suffix=f"d{index}",
        )
        for index in range(daily_count)
    )
    weekly = _bar(
        ProductFrequency.WEEKLY,
        datetime(2026, 3, 13, 7, tzinfo=UTC),
        source_suffix="w",
    )
    hourly = _bar(
        ProductFrequency.HOURLY,
        datetime(2026, 3, 13, 5, tzinfo=UTC),
        source_suffix="h",
    )
    context = align_completed_context(
        {
            "1w": _replay(weekly),
            "1d": _replay(*daily_bars),
            "60m": _replay(hourly),
        },
        weekly.bar.bar_end,
    )
    return context, daily_bars


def _signal(module, slot, value: str):
    return module.PageSignalFact(
        value=module.PageSignalState(value),
        frequency=slot.frequency,
        bar_end=slot.bar_end,
        physical_contract=slot.physical_contract,
        segment_id=slot.segment_id,
    )


def _status(module, slot, value: str):
    return module.CompositeStatusFact(
        value=module.CompositeStatusState(value),
        frequency=slot.frequency,
        bar_end=slot.bar_end,
        physical_contract=slot.physical_contract,
        segment_id=slot.segment_id,
    )


def _evidence(
    module,
    context,
    daily_bars: tuple[ProductBar, ...],
    *,
    weekly: str = "hold",
    daily: str = "hold",
    trend_hourly: str = "holding",
    oscillation_weekly: str = "holding",
    oscillation_daily: str = "holding",
    oscillation_hourly: str = "holding",
):
    return module.VerifiedCompositeEvidence(
        trend_weekly=_signal(module, context.weekly, weekly),
        trend_daily=_signal(module, context.daily, daily),
        trend_hourly=_status(module, context.hourly, trend_hourly),
        oscillation_weekly=_status(module, context.weekly, oscillation_weekly),
        oscillation_daily=_status(module, context.daily, oscillation_daily),
        oscillation_hourly=_status(module, context.hourly, oscillation_hourly),
        daily_bars=daily_bars,
    )


@pytest.mark.parametrize(
    (
        "weekly",
        "daily",
        "trend_hourly",
        "osc_weekly",
        "osc_daily",
        "osc_hourly",
        "expected_key",
        "expected_label",
        "expected_position",
    ),
    [
        (
            "hold",
            "hold",
            "holding",
            "holding",
            "holding",
            "holding",
            "bullish-bullish",
            "建仓 / 加仓",
            "50%-100%",
        ),
        (
            "hold",
            "hold",
            "holding",
            "cleared",
            "cleared",
            "cleared",
            "bullish-bearish",
            "持仓观望",
            "30%-50%",
        ),
        (
            "hold",
            "hold",
            "holding",
            "idle",
            "idle",
            "idle",
            "bullish-neutral",
            "建仓 / 加仓",
            "50%-100%",
        ),
        (
            "wait",
            "wait",
            "cleared",
            "holding",
            "holding",
            "holding",
            "bearish-bullish",
            "减仓观望",
            "30%-50%",
        ),
        (
            "wait",
            "wait",
            "cleared",
            "cleared",
            "cleared",
            "cleared",
            "bearish-bearish",
            "清仓 / 空仓",
            "0%",
        ),
        (
            "wait",
            "wait",
            "cleared",
            "idle",
            "idle",
            "idle",
            "bearish-neutral",
            "清仓 / 空仓",
            "0%",
        ),
        (
            "hold",
            "wait",
            "holding",
            "holding",
            "holding",
            "holding",
            "cautious-bullish",
            "谨慎持仓",
            "30%-50%",
        ),
        (
            "hold",
            "wait",
            "holding",
            "cleared",
            "cleared",
            "cleared",
            "cautious-bearish",
            "减仓观望",
            "10%-30%",
        ),
        (
            "hold",
            "wait",
            "holding",
            "idle",
            "idle",
            "idle",
            "cautious-neutral",
            "谨慎持仓",
            "10%-30%",
        ),
        (
            "hold",
            "hold",
            "idle",
            "idle",
            "idle",
            "idle",
            "bullish-neutral",
            "建仓 / 加仓",
            "50%-100%",
        ),
    ],
)
def test_reachable_composite_cells_use_literal_page_table(
    weekly: str,
    daily: str,
    trend_hourly: str,
    osc_weekly: str,
    osc_daily: str,
    osc_hourly: str,
    expected_key: str,
    expected_label: str,
    expected_position: str,
) -> None:
    module = _api()
    biases = module.classify_composite_biases(
        module.PageSignalState(weekly),
        module.PageSignalState(daily),
        module.CompositeStatusState(trend_hourly),
        module.CompositeStatusState(osc_weekly),
        module.CompositeStatusState(osc_daily),
        module.CompositeStatusState(osc_hourly),
    )
    decision = module.select_composite_decision(biases.trend, biases.oscillation)

    assert f"{biases.trend}-{biases.oscillation}" == expected_key
    assert decision.selected_key == expected_key
    assert decision.label == expected_label
    assert not hasattr(decision, "action")
    assert not hasattr(decision, "action_token")
    assert decision.position_range == expected_position
    assert decision.fallback_used is False
    assert decision.warning_branches_unreachable is True


@pytest.mark.parametrize(
    ("oscillation", "expected_key"),
    [
        ("bullish", "bearish-bullish"),
        ("bearish", "bearish-bearish"),
        ("neutral", "bearish-neutral"),
    ],
)
def test_intended_warning_cells_remain_unreachable_in_page_control_flow(
    oscillation: str, expected_key: str
) -> None:
    module = _api()
    oscillation_status = {
        "bullish": "holding",
        "bearish": "cleared",
        "neutral": "idle",
    }[oscillation]

    biases = module.classify_composite_biases(
        module.PageSignalState.WAIT,
        module.PageSignalState.HOLD,
        module.CompositeStatusState.HOLDING,
        module.CompositeStatusState(oscillation_status),
        module.CompositeStatusState(oscillation_status),
        module.CompositeStatusState(oscillation_status),
    )
    decision = module.select_composite_decision(biases.trend, biases.oscillation)

    assert biases.trend == "bearish"
    assert decision.selected_key == expected_key
    assert decision.selected_key != f"warning-{oscillation}"
    assert decision.warning_branches_unreachable is True


@pytest.mark.parametrize("oscillation", ["bullish", "bearish"])
def test_two_implicit_neutral_keys_fall_back_to_neutral_neutral(
    oscillation: str,
) -> None:
    module = _api()

    decision = module.select_composite_decision(
        module.CompositeBias.NEUTRAL,
        module.CompositeBias(oscillation),
    )

    assert decision.source_key == f"neutral-{oscillation}"
    assert decision.selected_key == "neutral-neutral"
    assert decision.label == "等待信号"
    assert decision.position_range == "--"
    assert decision.fallback_used is True


def test_explicit_neutral_neutral_cell_is_reachable_without_fallback() -> None:
    module = _api()

    decision = module.select_composite_decision(
        module.CompositeBias.NEUTRAL,
        module.CompositeBias.NEUTRAL,
    )

    assert decision.source_key == "neutral-neutral"
    assert decision.selected_key == "neutral-neutral"
    assert decision.label == "等待信号"
    assert decision.position_range == "--"
    assert decision.fallback_used is False


@pytest.mark.parametrize(
    ("oscillation_status", "expected_source_key", "expected_fallback"),
    [
        ("idle", "neutral-neutral", False),
        ("holding", "neutral-bullish", True),
        ("cleared", "neutral-bearish", True),
    ],
)
def test_absent_page_signals_reach_neutral_classifier_then_selector(
    oscillation_status: str,
    expected_source_key: str,
    expected_fallback: bool,
) -> None:
    module = _api()

    biases = module.classify_composite_biases(
        None,
        None,
        module.CompositeStatusState.IDLE,
        module.CompositeStatusState(oscillation_status),
        module.CompositeStatusState(oscillation_status),
        module.CompositeStatusState(oscillation_status),
    )
    decision = module.select_composite_decision(biases.trend, biases.oscillation)

    assert decision.source_key == expected_source_key
    assert decision.selected_key == "neutral-neutral"
    assert decision.label == "等待信号"
    assert decision.position_range == "--"
    assert decision.fallback_used is expected_fallback


@pytest.mark.parametrize(
    (
        "weekly",
        "daily",
        "hourly",
        "expected_token",
        "expected_points",
    ),
    [
        ("wait", "hold", "holding", "weekly_bearish_rebound", 5),
        ("wait", "wait", "cleared", "weekly_bearish", 3),
        ("hold", "wait", "holding", "daily_pullback", 10),
        ("hold", "hold", "cleared", "sixty_minute_pullback", 10),
        ("hold", "hold", "holding", "multiperiod_bullish", 20),
        ("hold", "hold", "idle", "insufficient", 5),
    ],
)
def test_all_direction_branches_and_points_are_preserved(
    weekly: str,
    daily: str,
    hourly: str,
    expected_token: str,
    expected_points: int,
) -> None:
    module = _api()
    context, daily_bars = _context()
    evidence = _evidence(
        module,
        context,
        daily_bars,
        weekly=weekly,
        daily=daily,
        trend_hourly=hourly,
    )

    result = module.calculate_composite_explanation(context, evidence)

    assert result.value.direction.token == expected_token
    assert result.value.direction.certainty_points == expected_points


@pytest.mark.parametrize(
    (
        "kwargs",
        "expected_components",
    ),
    [
        ({}, (30, 30, 20, 20, 100, 100, None)),
        (
            {
                "oscillation_weekly": "cleared",
                "oscillation_daily": "cleared",
                "oscillation_hourly": "cleared",
            },
            (30, 0, 0, 20, 50, 50, 60),
        ),
        (
            {
                "oscillation_weekly": "idle",
                "oscillation_daily": "idle",
                "oscillation_hourly": "idle",
            },
            (30, 0, 10, 20, 60, 60, 85),
        ),
        (
            {
                "weekly": "wait",
                "daily": "wait",
                "trend_hourly": "cleared",
                "oscillation_weekly": "cleared",
                "oscillation_daily": "cleared",
                "oscillation_hourly": "cleared",
            },
            (0, 0, 20, 3, 23, 23, None),
        ),
    ],
)
def test_certainty_keeps_four_components_and_alignment_caps(
    kwargs: dict[str, str],
    expected_components: tuple[int, int, int, int, int, int, int | None],
) -> None:
    module = _api()
    context, daily_bars = _context()

    result = module.calculate_composite_explanation(
        context, _evidence(module, context, daily_bars, **kwargs)
    )
    certainty = result.value.certainty

    assert (
        certainty.trend,
        certainty.oscillation,
        certainty.alignment,
        certainty.direction,
        certainty.uncapped_total,
        certainty.total,
        certainty.cap,
    ) == expected_components
    assert certainty.is_probability is False
    assert certainty.is_win_rate is False


@pytest.mark.parametrize(
    ("count", "true_range", "expected_value", "expected_level", "expected_trs"),
    [
        (5, "2", None, None, None),
        (6, "1.9", Decimal("1.9"), "low", 5),
        (6, "2", Decimal("2.0"), "mid", 5),
        (6, "4", Decimal("4.0"), "high", 5),
        (20, "2", Decimal("2.0"), "mid", 19),
        (21, "2", Decimal("2.0"), "mid", 20),
    ],
)
def test_volatility_uses_up_to_twenty_simple_true_ranges_and_page_tiers(
    count: int,
    true_range: str,
    expected_value: Decimal | None,
    expected_level: str | None,
    expected_trs: int | None,
) -> None:
    module = _api()
    _, bars = _context(daily_count=count, true_range=true_range)

    result = module.calculate_composite_volatility(bars)

    if expected_value is None:
        assert result is None
    else:
        assert result.value_pct == expected_value
        assert result.level == expected_level
        assert result.true_range_count == expected_trs
        assert result.method == "simple_mean_true_range_over_last_close"
        assert result.is_wilder_atr is False


def test_volatility_uses_javascript_number_before_true_range_arithmetic() -> None:
    module = _api()
    _, bars = _context(daily_count=6, true_range="1.95")

    result = module.calculate_composite_volatility(bars)

    assert result.value_pct == Decimal("1.9")
    assert result.level == "low"


def test_large_finite_decimal_volatility_never_leaks_invalid_operation() -> None:
    module = _api()
    _, bars = _context(daily_count=6)
    first = replace(
        bars[0],
        bar=replace(
            bars[0].bar,
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
        ),
    )
    large = tuple(
        replace(
            bar,
            bar=replace(
                bar.bar,
                open=Decimal("1"),
                high=Decimal("1E100"),
                low=Decimal("0.5"),
                close=Decimal("1"),
            ),
        )
        for bar in bars[1:]
    )

    result = module.calculate_composite_volatility((first, *large))

    assert result.value_pct == Decimal("1E102")
    assert result.level == "high"


def test_decimal_outside_page_number_domain_raises_stable_value_error() -> None:
    module = _api()
    _, bars = _context(daily_count=6)
    outside_number_domain = tuple(
        replace(
            bar,
            bar=replace(
                bar.bar,
                high=Decimal("1E1000"),
            ),
        )
        for bar in bars
    )

    with pytest.raises(ValueError, match="NEWOW_COMPOSITE_PAGE_NUMBER_OUT_OF_RANGE"):
        module.calculate_composite_volatility(outside_number_domain)


@pytest.mark.parametrize(
    (
        "weekly",
        "daily",
        "osc_weekly",
        "osc_daily",
        "osc_hourly",
        "expected_token",
        "expected_level",
        "expected_title",
        "expected_detail",
    ),
    [
        (
            "wait",
            "sell",
            "holding",
            "holding",
            "holding",
            "weekly_daily_bearish_hard_flat",
            "violate",
            "第一行动原则：趋势周线空仓·日线清仓（蓝色带），必须空仓观望！",
            "周线与日线同时出现清仓信号，大级别空头确立，无条件空仓等待反转；"
            "震荡短暂持有不改趋势，逢高减仓。同步确认大盘趋势状态，大盘蓝色带则整体空仓。",
        ),
        (
            "wait",
            "hold",
            "holding",
            "holding",
            "holding",
            "weekly_bearish_daily_bullish_rebound_risk",
            "warn",
            "风险提示：周线空仓（蓝色带）· 日线持股（黄色带）——下跌中的反弹",
            "周线仍处空头，日线反弹多为下跌中继的背离走势（易二次探底）。若参与建议仓位"
            " ≤30%，设好止损、不追涨；日线转弱或周线未反转前不加仓；震荡短暂持有不改趋势。"
            "同步确认大盘趋势状态。",
        ),
        (
            "hold",
            "wait",
            "holding",
            "holding",
            "holding",
            "weekly_bullish_daily_bearish_wait_for_daily_stability",
            "warn",
            "提示：日线空仓（蓝色带）· 周线持股（黄色带）——等待日线企稳",
            "周线趋势仍向上，日线进入回调/清仓阶段。已持仓者按日线信号减仓；未持仓者等日线"
            "重新出现建仓信号（黄色带）再介入，勿急于抄底。",
        ),
        (
            "wait",
            None,
            "holding",
            "holding",
            "holding",
            "single_bearish_unknown_counterpart_hard_flat",
            "violate",
            "第一行动原则：趋势周线空仓（蓝色带），必须空仓观望！",
            "「趋势策略」出现清仓信号即无条件空仓，勿因 60min/日线反弹而逆势操作；"
            "震荡短暂持有不改趋势，逢高减仓。同步确认大盘趋势状态，大盘蓝色带则整体空仓。",
        ),
        (
            "hold",
            "hold",
            "holding",
            "holding",
            "cleared",
            "sixty_minute_oscillation_cleared",
            "warn",
            "看大做小：日/周线建仓 · 60分钟已清仓",
            "小周期服从大周期：60min 回踩吸筹（参考吸筹价）确认后再跟随「震荡策略」建仓；"
            "日线仓位不因 60min 清仓而清出。",
        ),
        (
            "hold",
            "hold",
            "holding",
            "cleared",
            "holding",
            "daily_oscillation_cleared",
            "warn",
            "震荡日线已清仓 · 趋势建仓",
            "趋势（黄带）向上但震荡日线已清仓，等待震荡吸筹回补信号，勿急于加仓。",
        ),
        (
            "hold",
            "hold",
            "cleared",
            "holding",
            "holding",
            "weekly_oscillation_cleared",
            "warn",
            "震荡周线已清仓 · 趋势建仓",
            "趋势（黄带）向上但震荡周线已清仓，大级别震荡转弱，控制仓位等待回补。",
        ),
        (
            "hold",
            "hold",
            "holding",
            "holding",
            "holding",
            "normal_observation",
            "ok",
            "遵守：趋势周/日线均建仓（黄色波段）",
            "处于趋势建仓区间，可操作。严格执行「震荡策略」建仓/清仓信号，节奏不乱；"
            "大盘建仓期可顺势操作，仓位按建议执行。",
        ),
    ],
)
def test_first_action_priority_has_eight_guiyi_owned_typed_tokens(
    weekly: str | None,
    daily: str | None,
    osc_weekly: str,
    osc_daily: str,
    osc_hourly: str,
    expected_token: str,
    expected_level: str,
    expected_title: str,
    expected_detail: str,
) -> None:
    module = _api()

    result = module.calculate_first_action_principle(
        None if weekly is None else module.PageSignalState(weekly),
        None if daily is None else module.PageSignalState(daily),
        module.CompositeStatusState(osc_weekly),
        module.CompositeStatusState(osc_daily),
        module.CompositeStatusState(osc_hourly),
    )

    assert result.rule_token == expected_token
    assert result.level == expected_level
    assert result.page_title == expected_title
    assert result.page_detail == expected_detail
    assert result.token_owner == module.FirstActionTokenOwner.GUIYI_CLEAN_ROOM
    assert result.page_formula_version == "newow_first_action_principle_page_v3_2_63"
    assert result.token_is_page_native is False


@pytest.mark.parametrize(
    ("key", "name", "risk", "position"),
    [
        ("buy-buy", "上涨启动", "bullish", "70-100%"),
        ("buy-hold", "震荡上涨", "bullish", "50-70%"),
        ("buy-sell", "趋势回调", "cautious", "30-50%"),
        ("buy-wait", "筑底反弹", "warning", "10-20%"),
        ("hold-buy", "上涨中继", "bullish", "50-70%"),
        ("hold-hold", "上涨趋势", "bullish", "50-70%"),
        ("hold-sell", "高位震荡", "cautious", "30-50%"),
        ("hold-wait", "高位震荡", "cautious", "30-50%"),
        ("sell-buy", "震荡反弹", "warning", "10-20%"),
        ("sell-hold", "震荡反弹", "warning", "10-20%"),
        ("sell-sell", "下跌趋势", "bearish", "0%"),
        ("sell-wait", "震荡下跌", "bearish", "0%"),
        ("wait-buy", "筑底反转", "bearish", "0%"),
        ("wait-hold", "筑底反弹", "warning", "10-20%"),
        ("wait-sell", "震荡下跌", "bearish", "0%"),
        ("wait-wait", "震荡下跌", "bearish", "0%"),
    ],
)
def test_week_day_matrix_exposes_only_sixteen_frozen_structured_tokens(
    key: str, name: str, risk: str, position: str
) -> None:
    module = _api()
    weekly, daily = key.split("-")

    result = module.select_week_day_matrix(
        module.PageSignalState(weekly), module.PageSignalState(daily)
    )

    assert asdict(result) == {
        "key": key,
        "name": name,
        "risk": risk,
        "position": position,
        "formula_version": "newow_trend_week_day_matrix_page_v3_2_49",
    }
    assert not hasattr(result, "ai")
    assert not hasattr(result, "advice")


def test_ready_result_keeps_named_evidence_gaps_null_and_separate() -> None:
    module = _api()
    context, daily_bars = _context()

    result = module.calculate_composite_explanation(
        context, _evidence(module, context, daily_bars)
    )

    assert result.status == "ready"
    assert result.evidence_status == "RESEARCH_EVIDENCE_ONLY"
    assert result.as_of == context.as_of
    assert result.value.warning_branches_unreachable is True
    assert result.value.decision.position_is_target is False
    assert result.value.decision.position_is_hand_count is False
    subfeatures = {item.name: item for item in result.value.subfeatures}
    for name in (
        "six_combo_output_oracle",
        "stable_diagnostic_token_mapping",
        "ai_copy",
        "intended_warning_semantics",
    ):
        assert subfeatures[name].status.status == "evidence_required"
        assert subfeatures[name].status.evidence_status == "EVIDENCE_REQUIRED"
        assert subfeatures[name].value is None
    assert result.value.diagnostic_tokens is None
    assert result.value.ai_copy is None
    assert result.value.six_combo_ranking is None
    assert result.value.evidence_manifest_sha256 == (
        "279aa0c3a88b6e6c5413387a57085dfe4c4d23a34befa751d95ced4c03be962f"
    )
    assert result.value.page_source_sha256 == (
        "cd962170085dc2145fbaebf28a47ce6764b9f519e6032b54a896e37f0c9d0cf9"
    )
    assert result.value.reachability_sha256 == (
        "48888a4b3f1a2634d7e4664200aed07c0ef4ce9426fb62840baa8e88e0e68d5c"
    )
    assert result.value.ai_template_evidence_sha256 == (
        "3a759abad84e1f7f03d8a4343872d2f4d9758ac746d3e9dd033bcd95106e606f"
    )
    assert result.value.frozen_results_sha256 == (
        "163337b4b425241189ae348814610c29b3ff3b24a3c4b03a95da10864efbab3e"
    )
    assert result.formula_versions == (
        "newow_composite_decision_page_v3_2_82_reachable_v1",
        "newow_composite_direction_page_v3_2_58",
        "newow_composite_certainty_page_v3_2_59",
        "newow_composite_volatility_mean_tr20_over_close_page_v3_2_59",
        "newow_first_action_principle_page_v3_2_63",
        "newow_trend_week_day_matrix_page_v3_2_49",
    )


def test_short_daily_prefix_does_not_coerce_volatility_to_zero() -> None:
    module = _api()
    context, daily_bars = _context(daily_count=5)

    result = module.calculate_composite_explanation(
        context, _evidence(module, context, daily_bars)
    )

    assert result.status == "ready"
    assert result.value.volatility is None
    volatility = {item.name: item for item in result.value.subfeatures}["volatility"]
    assert volatility.status.status == "warming"
    assert volatility.value is None


def test_missing_period_is_unavailable_not_neutral() -> None:
    module = _api()
    context, daily_bars = _context()
    evidence = replace(_evidence(module, context, daily_bars), trend_daily=None)

    result = module.calculate_composite_explanation(context, evidence)

    assert result.status == "unavailable"
    assert result.reason_code == "NEWOW_COMPOSITE_MISSING_PERIOD"
    assert result.value is None


@pytest.mark.parametrize("pollution", ["owner", "future", "frequency"])
def test_context_pollution_fails_closed(pollution: str) -> None:
    module = _api()
    context, daily_bars = _context()
    evidence = _evidence(module, context, daily_bars)
    fact = evidence.trend_daily
    assert fact is not None
    if pollution == "owner":
        fact = replace(fact, physical_contract="RB2610")
    elif pollution == "future":
        fact = replace(fact, bar_end=context.as_of + timedelta(minutes=1))
    else:
        fact = replace(fact, frequency=ProductFrequency.WEEKLY)

    result = module.calculate_composite_explanation(
        context, replace(evidence, trend_daily=fact)
    )

    assert result.status == "unavailable"
    assert result.reason_code == "NEWOW_COMPOSITE_SOURCE_CONTEXT_MISMATCH"
    assert result.value is None


def test_duplicate_or_conflicting_daily_fact_fails_closed() -> None:
    module = _api()
    context, daily_bars = _context()
    duplicate = (*daily_bars[:-1], daily_bars[-1], daily_bars[-1])
    conflict = replace(
        daily_bars[-1],
        bar=replace(
            daily_bars[-1].bar,
            open=Decimal("99"),
            source_identity="owned:composite:conflict",
        ),
    )

    duplicated = module.calculate_composite_explanation(
        context, _evidence(module, context, duplicate)
    )
    conflicted = module.calculate_composite_explanation(
        context,
        _evidence(module, context, (*daily_bars[:-1], conflict, daily_bars[-1])),
    )

    assert duplicated.status == "unavailable"
    assert conflicted.status == "unavailable"
    assert duplicated.reason_code == "NEWOW_COMPOSITE_DAILY_PREFIX_INVALID"
    assert conflicted.reason_code == "NEWOW_COMPOSITE_DAILY_PREFIX_INVALID"


def test_unconfirmed_daily_bar_is_rejected_by_the_bar_contract() -> None:
    _api()
    _, daily_bars = _context()

    with pytest.raises(ValueError, match="NEWOW_BAR_NOT_COMPLETED"):
        replace(daily_bars[1].bar, completed=False)


def test_observation_ineligible_daily_prefix_fact_fails_closed() -> None:
    module = _api()
    context, daily_bars = _context()
    invalid_bar = replace(daily_bars[1].bar, observation_eligible=False)
    invalid_prefix = (
        daily_bars[0],
        replace(daily_bars[1], bar=invalid_bar),
        *daily_bars[2:],
    )

    result = module.calculate_composite_explanation(
        context, _evidence(module, context, invalid_prefix)
    )

    assert result.status == "unavailable"
    assert result.reason_code == "NEWOW_COMPOSITE_DAILY_PREFIX_INVALID"


def test_multiple_daily_bars_on_one_trading_day_fail_closed() -> None:
    module = _api()
    context, daily_bars = _context()
    trading_day = daily_bars[-1].bar.trading_day
    same_day_prefix = tuple(
        replace(bar, bar=replace(bar.bar, trading_day=trading_day))
        for bar in daily_bars
    )

    result = module.calculate_composite_explanation(
        context, _evidence(module, context, same_day_prefix)
    )

    assert result.status == "unavailable"
    assert result.reason_code == "NEWOW_COMPOSITE_DAILY_PREFIX_INVALID"


def test_invalid_status_typo_is_rejected() -> None:
    module = _api()
    context, _ = _context()

    with pytest.raises(ValueError, match="NEWOW_COMPOSITE_INVALID_STATUS_FACT"):
        module.CompositeStatusFact(
            "typo",
            context.hourly.frequency,
            context.hourly.bar_end,
            context.hourly.physical_contract,
            context.hourly.segment_id,
        )


def test_explanation_is_pure_and_cannot_change_p1_or_p2(product_cases) -> None:
    module = _api()
    context, daily_bars = _context()
    evidence = _evidence(module, context, daily_bars)
    case = product_cases.closed()
    projector = ReferenceTradeProjector()
    actions_before = case.replay.actions
    projection_before = projector.project(case.replay, case.boundaries, case.as_of)
    context_before = asdict(context)
    evidence_before = asdict(evidence)

    result = module.calculate_composite_explanation(context, evidence)

    assert case.replay.actions == actions_before
    assert (
        projector.project(case.replay, case.boundaries, case.as_of) == projection_before
    )
    assert asdict(context) == context_before
    assert asdict(evidence) == evidence_before
    assert result.value.first_action.rule_token
    for forbidden in (
        "action",
        "actions",
        "order",
        "orders",
        "target_position",
        "reference_trade",
        "reference_trades",
    ):
        assert not hasattr(result, forbidden)
        assert not hasattr(result.value, forbidden)
