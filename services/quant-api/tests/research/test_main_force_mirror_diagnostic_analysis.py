from __future__ import annotations

import importlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.indicators.main_force_mirror_v2 import (
    MainForceMirrorV2AuditTraceItem,
    MainForceMirrorV2LatchSnapshot,
    MainForceMirrorV2Point,
)

from app.market_data.domain import CanonicalBar
from app.research.main_force.main_force_mirror_diagnostic import (
    MainForceMirrorDiagnosticSide,
    MainForceMirrorDiagnosticUnavailableReason,
)


def _analysis():
    try:
        return importlib.import_module(
            "app.research.main_force.main_force_mirror_diagnostic_analysis"
        )
    except ModuleNotFoundError:
        pytest.fail("diagnostic analysis module is not implemented")


_LATCH_ARMED = MainForceMirrorV2LatchSnapshot(True, True, 0, 0, 0, 0)


def _bar(index: int, *, start: datetime | None = None) -> CanonicalBar:
    moment = (start or datetime(2025, 1, 2, tzinfo=UTC)) + timedelta(hours=index)
    return CanonicalBar(
        bar_end=moment,
        trading_day=moment.date(),
        open=Decimal("100"),
        high=Decimal("105"),
        low=Decimal("95"),
        close=Decimal("100"),
        volume=Decimal("100"),
        turnover=None,
        open_interest=Decimal("1000"),
    )


def _point(
    bar: CanonicalBar,
    *,
    contract: str = "JM2609",
    caution: str | None = None,
    ready: bool = True,
) -> MainForceMirrorV2Point:
    side = None if caution is None else caution.split("_", 1)[0]
    return MainForceMirrorV2Point(
        bar_end=bar.bar_end,
        trading_day=bar.trading_day,
        physical_contract=contract,
        pressure_ready=ready,
        pressure_state="long_build" if ready else None,
        instant_pressure=10.0 if ready else None,
        accumulated_ready=ready,
        accumulated_pressure=8.0 if ready else None,
        caution_ready=ready,
        caution=caution,  # type: ignore[arg-type]
        caution_conflict=False,
        long_caution_score=70.0 if side == "long" else 0.0 if ready else None,
        short_caution_score=70.0 if side == "short" else 0.0 if ready else None,
        caution_reason_codes=("fixture",) if caution else (),
        member=None,
        unavailable_reason=None if ready else "MFM_V2_INPUT_INVALID",
        price_impulse=1.0 if ready else None,
        clv=0.5 if ready else None,
        volume_ratio=1.0 if ready else None,
        delta_oi=1.0 if ready else None,
        oi_impulse=1.0 if ready else None,
        range_position=0.5 if ready else None,
    )


def _trace(
    point: MainForceMirrorV2Point,
    *,
    atr: float | None = 10.0,
    conflict: bool = False,
    long_candidate: bool | None = None,
    short_candidate: bool | None = None,
    long_suppressed: bool = False,
    short_suppressed: bool = False,
    rearm_reasons: tuple[str, ...] = (),
) -> MainForceMirrorV2AuditTraceItem:
    if long_candidate is None:
        long_candidate = bool(point.long_caution_score is not None and point.long_caution_score >= 70)
    if short_candidate is None:
        short_candidate = bool(point.short_caution_score is not None and point.short_caution_score >= 70)
    return MainForceMirrorV2AuditTraceItem(
        bar_end=point.bar_end,
        trading_day=point.trading_day,
        physical_contract=point.physical_contract,
        atr14=atr,
        volume_mean20=100.0,
        range_high20=110.0,
        range_low20=90.0,
        oi_baseline20=1.0,
        price_impulse=point.price_impulse,
        clv=point.clv,
        direction=1.0,
        volume_ratio=point.volume_ratio,
        delta_oi=point.delta_oi,
        oi_impulse=point.oi_impulse,
        range_position=point.range_position,
        long_open_pressure=1.0,
        short_open_pressure=0.0,
        prior_long_open_pressure_max=1.0,
        prior_short_open_pressure_max=1.0,
        instant_pressure=point.instant_pressure,
        accumulated_pressure=point.accumulated_pressure,
        long_score=point.long_caution_score,
        short_score=point.short_caution_score,
        components=None,
        long_candidate=long_candidate,
        short_candidate=short_candidate,
        conflict=conflict,
        latch_before=_LATCH_ARMED,
        latch_after=_LATCH_ARMED,
        trigger=point.caution,
        long_disarmed_suppressed=long_suppressed,
        short_disarmed_suppressed=short_suppressed,
        rearm_reasons=rearm_reasons,  # type: ignore[arg-type]
        reset_boundary=None,
        unavailable_reason=point.unavailable_reason,
    )


def _input(
    bars: tuple[CanonicalBar, ...],
    points: tuple[MainForceMirrorV2Point, ...],
    traces: tuple[MainForceMirrorV2AuditTraceItem, ...] | None = None,
    *,
    symbol: str = "jm",
):
    analysis = _analysis()
    return analysis.MainForceMirrorDiagnosticProductInput(
        symbol=symbol,
        bars=bars,
        points=points,
        trace=traces or tuple(_trace(point) for point in points),
    )


def _fixture(
    *,
    count: int = 24,
    cautions: dict[int, str] | None = None,
    start: datetime | None = None,
):
    bars = tuple(_bar(index, start=start) for index in range(count))
    cautions = cautions or {}
    points = tuple(
        _point(bar, caution=cautions.get(index)) for index, bar in enumerate(bars)
    )
    return bars, points


def test_early_touch_does_not_shorten_embargo_and_offset_11_can_anchor() -> None:
    """Catches shortening the 10-future-Bar sampling lock after an early touch."""
    analysis = _analysis()
    bars, points = _fixture(
        cautions={
            0: "long_chase_caution",
            1: "long_chase_caution",
            10: "long_chase_caution",
            11: "long_chase_caution",
        }
    )
    bars = tuple(
        replace(bar, open=Decimal("111"), high=Decimal("112"))
        if index == 1
        else bar
        for index, bar in enumerate(bars)
    )

    result = analysis.audit_main_force_mirror_labels((_input(bars, points),))

    assert [episode.anchor_index for episode in result.episodes if episode.kept] == [0, 11]
    assert [episode.anchor_index for episode in result.episodes if not episode.kept] == [1, 10]
    assert result.episodes[0].outcome.value == "favorable_first"
    assert result.section.raw_sample_count == 4
    assert result.section.sample_count == 2
    assert result.section.overlap_suppressed_count == 2
    assert result.section.long_sample_count == 2
    assert result.section.short_sample_count == 2
    assert result.section.duplicated_side_sample_count == 2


def test_embargo_lock_is_scoped_to_contiguous_physical_block_not_contract_string() -> None:
    """Catches an A-block lock reviving after an intervening B contract block."""
    analysis = _analysis()
    bars, points = _fixture(
        count=15,
        cautions={0: "long_chase_caution", 2: "long_chase_caution"},
    )
    points = tuple(
        replace(point, physical_contract="JM2701") if index == 1 else point
        for index, point in enumerate(points)
    )

    result = analysis.audit_main_force_mirror_labels((_input(bars, points),))

    assert [episode.anchor_index for episode in result.episodes if episode.kept] == [0, 2]
    assert result.section.raw_sample_count == 2
    assert result.section.sample_count == 2
    assert result.section.overlap_suppressed_count == 0


def test_open_gap_has_priority_and_same_bar_dual_intrabar_touch_is_ambiguous() -> None:
    """Catches treating an open gap as ambiguous or imposing an intrabar side order."""
    analysis = _analysis()
    bars, points = _fixture(cautions={0: "long_chase_caution"})
    open_gap = list(bars)
    open_gap[1] = replace(
        open_gap[1],
        open=Decimal("111"),
        high=Decimal("115"),
        low=Decimal("85"),
        close=Decimal("100"),
    )
    gap = analysis.audit_main_force_mirror_labels(
        (_input(tuple(open_gap), points),)
    )
    assert gap.episodes[0].outcome.value == "favorable_first"
    assert gap.episodes[0].first_touch_offset == 1

    intrabar = list(bars)
    intrabar[1] = replace(
        intrabar[1],
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
    )
    both = analysis.audit_main_force_mirror_labels(
        (_input(tuple(intrabar), points),)
    )
    assert both.episodes[0].outcome.value == "ambiguous"
    assert both.section.ambiguous_count == 1


def test_long_and_short_first_touch_map_adverse_and_favorable_by_anchor_side() -> None:
    """Catches applying the long barrier polarity to a short caution anchor."""
    analysis = _analysis()
    bars, long_points = _fixture(cautions={0: "long_chase_caution"})
    lower_touch = list(bars)
    lower_touch[1] = replace(lower_touch[1], open=Decimal("89"), low=Decimal("88"))
    long_result = analysis.audit_main_force_mirror_labels(
        (_input(tuple(lower_touch), long_points),)
    )
    assert long_result.episodes[0].side is MainForceMirrorDiagnosticSide.LONG
    assert long_result.episodes[0].outcome.value == "adverse_first"
    assert long_result.episodes[0].binary_target == 1

    _, short_points = _fixture(cautions={0: "short_chase_caution"})
    short_result = analysis.audit_main_force_mirror_labels(
        (_input(tuple(lower_touch), short_points),)
    )
    assert short_result.episodes[0].side is MainForceMirrorDiagnosticSide.SHORT
    assert short_result.episodes[0].outcome.value == "favorable_first"
    assert short_result.episodes[0].binary_target == 0


def test_complete_untouched_horizon_is_timeout_and_legacy_neither() -> None:
    """Catches silently shortening an untouched 10-Bar horizon."""
    analysis = _analysis()
    bars, points = _fixture(count=11, cautions={0: "long_chase_caution"})

    result = analysis.audit_main_force_mirror_labels((_input(bars, points),))

    assert result.episodes[0].outcome.value == "timeout"
    assert result.episodes[0].first_touch_offset is None
    assert result.section.timeout_count == 1
    assert result.section.legacy_neither_count == 1


@pytest.mark.parametrize(
    ("case", "expected"),
    (
        ("roll", "censored_contract_change"),
        ("input_gap", "censored_input_gap"),
        ("window_end", "censored_horizon"),
    ),
)
def test_incomplete_sampling_is_typed_without_shortening_or_filling(
    case: str,
    expected: str,
) -> None:
    """Catches turning a known sampling limitation into a timeout or binary label."""
    analysis = _analysis()
    start = datetime(2025, 1, 2, tzinfo=UTC)
    count = 6 if case == "window_end" else 11
    bars, points = _fixture(count=count, cautions={0: "long_chase_caution"}, start=start)
    if case == "roll":
        points = tuple(
            replace(point, physical_contract="JM2701") if index >= 5 else point
            for index, point in enumerate(points)
        )
    elif case == "input_gap":
        points = tuple(
            _point(bar, ready=False) if index == 5 else point
            for index, (bar, point) in enumerate(zip(bars, points, strict=True))
        )

    result = analysis.audit_main_force_mirror_labels((_input(bars, points),))

    assert result.episodes[0].outcome.value == expected
    assert result.episodes[0].binary_target is None
    assert result.section.binary_evaluable_count == 0
    assert result.section.legacy_neither_count == 1


def test_split_is_fold_specific_and_does_not_replace_physical_outcome() -> None:
    """Catches deleting a Fold2-fit sample at the Fold1 fit/evaluate boundary."""
    analysis = _analysis()
    bars, points = _fixture(
        count=11,
        cautions={0: "long_chase_caution"},
        start=datetime(2024, 12, 31, 20, tzinfo=UTC),
    )
    bars = tuple(
        replace(bar, open=Decimal("111"), high=Decimal("112"))
        if index == 1
        else bar
        for index, bar in enumerate(bars)
    )

    result = analysis.audit_main_force_mirror_labels((_input(bars, points),))
    episode = result.episodes[0]

    assert episode.outcome.value == "favorable_first"
    assert episode.binary_target == 0
    assert [
        (fold.fold, fold.segment, fold.outcome.value, fold.binary_target, fold.eligible)
        for fold in episode.fold_outcomes
    ] == [
        (1, "fit", "split_boundary_censored", None, False),
        (2, "fit", "favorable_first", 0, True),
    ]
    assert result.section.favorable_first_count == 1
    assert result.section.split_boundary_censored_count == 0
    fold_one, fold_two = result.section.breakdowns[-2:]
    assert fold_one.split_boundary_censored_count == 1
    assert fold_one.binary_evaluable_count == 0
    assert fold_two.favorable_first_count == 1
    assert fold_two.binary_evaluable_count == 1
    funnel = analysis.audit_main_force_mirror_funnel((_input(bars, points),), result)
    assert funnel.breakdowns[0].binary_evaluable_count == 1
    assert funnel.breakdowns[-2].binary_evaluable_count == 0
    assert funnel.breakdowns[-1].binary_evaluable_count == 1


def test_known_roll_precedes_window_end_censor_in_a_truncated_horizon() -> None:
    """Catches hiding an observed roll behind the later missing window tail."""
    analysis = _analysis()
    bars, points = _fixture(count=6, cautions={0: "long_chase_caution"})
    points = tuple(
        replace(point, physical_contract="JM2701") if index >= 4 else point
        for index, point in enumerate(points)
    )

    result = analysis.audit_main_force_mirror_labels((_input(bars, points),))

    assert result.episodes[0].outcome.value == "censored_contract_change"
    assert result.section.censored_contract_change_count == 1
    assert result.section.censored_horizon_count == 0


def test_invalid_anchor_barrier_is_typed_product_unavailable() -> None:
    """Catches fabricating a barrier from non-positive ATR or lower bound."""
    analysis = _analysis()
    bars, points = _fixture(count=11, cautions={0: "long_chase_caution"})
    traces = tuple(
        _trace(point, atr=0.0 if index == 0 else 10.0)
        for index, point in enumerate(points)
    )

    result = analysis.audit_main_force_mirror_labels(
        (_input(bars, points, traces),)
    )

    assert result.unavailable_products == (
        ("jm", MainForceMirrorDiagnosticUnavailableReason.LABEL_BARRIER_INVALID),
    )
    assert result.episodes == ()
    assert result.section.raw_sample_count == 0


@pytest.mark.parametrize("case", ("length", "identity", "nonmonotonic", "trigger"))
def test_identity_and_order_corruption_raise_stable_diagnostic_error(case: str) -> None:
    """Catches accepting arrays that no longer describe the same canonical Bar."""
    analysis = _analysis()
    bars, points = _fixture(count=11, cautions={0: "long_chase_caution"})
    traces = tuple(_trace(point) for point in points)
    if case == "length":
        traces = traces[:-1]
    elif case == "identity":
        traces = (replace(traces[0], physical_contract="JM2701"), *traces[1:])
    elif case == "nonmonotonic":
        bars = (bars[0], replace(bars[1], bar_end=bars[0].bar_end), *bars[2:])
    else:
        traces = (replace(traces[0], trigger=None), *traces[1:])

    with pytest.raises(
        analysis.MainForceMirrorDiagnosticAnalysisError,
        match="MFM_DIAGNOSTIC_ANALYSIS_INVALID",
    ):
        analysis.audit_main_force_mirror_labels((_input(bars, points, traces),))


def test_score_latch_funnel_uses_unrounded_70_and_conserves_sampling_anchors() -> None:
    """Catches rounding scores or conflating latch suppression with label embargo."""
    analysis = _analysis()
    bars, base_points = _fixture(count=15)
    points = list(base_points)
    points[0] = replace(points[0], long_caution_score=69.999999)
    points[1] = _point(bars[1], caution="long_chase_caution")
    points[2] = _point(bars[2], caution="short_chase_caution")
    points[3] = replace(
        points[3],
        long_caution_score=70.0,
        short_caution_score=70.0,
        caution_conflict=True,
    )
    points[4] = replace(points[4], long_caution_score=70.0)
    traces = list(_trace(point) for point in points)
    traces[3] = _trace(
        points[3], conflict=True, long_candidate=True, short_candidate=True
    )
    traces[4] = _trace(
        points[4],
        long_candidate=True,
        short_candidate=False,
        long_suppressed=True,
    )
    traces[5] = _trace(points[5], rearm_reasons=("long_range", "short_build"))
    bars = tuple(
        replace(bar, open=Decimal("111"), high=Decimal("112"))
        if index == 6
        else bar
        for index, bar in enumerate(bars)
    )
    product = _input(tuple(bars), tuple(points), tuple(traces))
    labels = analysis.audit_main_force_mirror_labels((product,))

    funnel = analysis.audit_main_force_mirror_funnel((product,), labels)

    global_row = funnel.breakdowns[0]
    assert global_row.caution_ready_bar_count == 15
    assert global_row.score_not_candidate_count == 11
    assert global_row.long_only_candidate_count == 2
    assert global_row.short_only_candidate_count == 1
    assert global_row.dual_candidate_conflict_count == 1
    assert global_row.high_score_unique_bar_count == 4
    assert global_row.armed_candidate_count == 2
    assert global_row.unarmed_candidate_suppressed_count == 1
    assert global_row.long_caution_count == 1
    assert global_row.short_caution_count == 1
    assert global_row.caution_count == 2
    assert global_row.raw_episode_anchor_count == 2
    assert global_row.kept_episode_anchor_count == 1
    assert global_row.overlap_suppressed_anchor_count == 1
    assert global_row.binary_evaluable_count == 1
    assert global_row.long_rearm_count == 1
    assert global_row.short_rearm_count == 1
    assert funnel.suppression_count == 1


@pytest.mark.parametrize(
    "case",
    ("threshold_mismatch", "conflict_trigger", "missing_latch_branch", "double_branch"),
)
def test_score_latch_conservation_corruption_fails_closed(case: str) -> None:
    """Catches accepting a trace that cannot conserve the frozen score/latch loop."""
    analysis = _analysis()
    bars, points = _fixture(count=11)
    points = list(points)
    traces = list(_trace(point) for point in points)
    points[0] = replace(points[0], long_caution_score=70.0)
    if case == "threshold_mismatch":
        traces[0] = _trace(points[0], long_candidate=False)
    elif case == "conflict_trigger":
        points[0] = replace(
            points[0],
            caution="long_chase_caution",  # type: ignore[arg-type]
            caution_conflict=True,
            short_caution_score=70.0,
        )
        traces[0] = _trace(
            points[0], conflict=True, long_candidate=True, short_candidate=True
        )
    elif case == "missing_latch_branch":
        traces[0] = _trace(points[0], long_candidate=True)
    else:
        points[0] = replace(
            points[0], caution="long_chase_caution"  # type: ignore[arg-type]
        )
        traces[0] = _trace(points[0], long_candidate=True, long_suppressed=True)
    product = _input(bars, tuple(points), tuple(traces))
    labels = analysis.audit_main_force_mirror_labels((product,))

    with pytest.raises(
        analysis.MainForceMirrorDiagnosticAnalysisError,
        match="MFM_DIAGNOSTIC_ANALYSIS_INVALID",
    ):
        analysis.audit_main_force_mirror_funnel((product,), labels)


def test_funnel_rejects_labels_from_a_different_physical_contract() -> None:
    """Catches validating label identity by anchor index alone."""
    analysis = _analysis()
    bars, points = _fixture(count=12, cautions={0: "long_chase_caution"})
    original = _input(bars, points)
    labels = analysis.audit_main_force_mirror_labels((original,))
    changed_points = tuple(
        replace(point, physical_contract="JM2701") for point in points
    )
    changed_traces = tuple(
        replace(_trace(point), physical_contract="JM2701") for point in changed_points
    )
    changed = _input(bars, changed_points, changed_traces)

    with pytest.raises(
        analysis.MainForceMirrorDiagnosticAnalysisError,
        match="MFM_DIAGNOSTIC_ANALYSIS_INVALID",
    ):
        analysis.audit_main_force_mirror_funnel((changed,), labels)


def test_funnel_requires_exact_label_input_symbol_order() -> None:
    """Catches accepting the same anchor indices from a reordered product collection."""
    analysis = _analysis()
    bars, points = _fixture(count=12, cautions={0: "long_chase_caution"})
    jm = _input(bars, points, symbol="jm")
    ag = _input(bars, points, symbol="ag")
    labels = analysis.audit_main_force_mirror_labels((jm, ag))

    with pytest.raises(
        analysis.MainForceMirrorDiagnosticAnalysisError,
        match="MFM_DIAGNOSTIC_ANALYSIS_INVALID",
    ):
        analysis.audit_main_force_mirror_funnel((ag, jm), labels)
    with pytest.raises(
        analysis.MainForceMirrorDiagnosticAnalysisError,
        match="MFM_DIAGNOSTIC_ANALYSIS_INVALID",
    ):
        analysis.audit_main_force_mirror_funnel((jm,), labels)


@pytest.mark.parametrize("drift", ("contract", "bar", "trace"))
def test_funnel_binds_labels_to_exact_no_caution_product_inputs(drift: str) -> None:
    """Catches equal empty derived labels hiding exact source DTO drift."""
    analysis = _analysis()
    bars, points = _fixture(count=12)
    traces = tuple(_trace(point) for point in points)
    original = _input(bars, points, traces)
    labels = analysis.audit_main_force_mirror_labels((original,))
    if drift == "contract":
        changed_points = tuple(
            replace(point, physical_contract="JM2701") for point in points
        )
        changed_traces = tuple(
            replace(trace, physical_contract="JM2701") for trace in traces
        )
        changed = _input(bars, changed_points, changed_traces)
    elif drift == "bar":
        changed_bars = list(bars)
        changed_bars[5] = replace(changed_bars[5], volume=Decimal("101"))
        changed = _input(tuple(changed_bars), points, traces)
    else:
        changed_traces = list(traces)
        changed_traces[5] = replace(changed_traces[5], atr14=11.0)
        changed = _input(bars, points, tuple(changed_traces))

    with pytest.raises(
        analysis.MainForceMirrorDiagnosticAnalysisError,
        match="MFM_DIAGNOSTIC_ANALYSIS_INVALID",
    ):
        analysis.audit_main_force_mirror_funnel((changed,), labels)


def _sequence_product(*, roll_before_evidence: bool = False):
    count = 34
    bars, base_points = _fixture(count=count)
    points: list[MainForceMirrorV2Point] = []
    for index, (bar, base) in enumerate(zip(bars, base_points, strict=True)):
        if index <= 20:
            state, instant, accumulated = "long_build", 10.0 + index, 8.0 + index
        elif index == 21:
            state, instant, accumulated = "long_build", 100.0, 80.0
        elif index == 22:
            state, instant, accumulated = "long_liquidation", -60.0, 30.0
        elif index == 23:
            state, instant, accumulated = "short_build", -70.0, -10.0
        else:
            state, instant, accumulated = "turnover", -10.0, -15.0
        contract = "JM2701" if roll_before_evidence and index >= 22 else "JM2609"
        points.append(
            replace(
                base,
                physical_contract=contract,
                pressure_state=state,  # type: ignore[arg-type]
                instant_pressure=instant,
                accumulated_pressure=accumulated,
            )
        )
    bars = tuple(
        replace(
            bar,
            close=Decimal(100 if index <= 21 else 100 - 5 * (index - 21)),
            open=Decimal(100 if index <= 21 else 100 - 5 * (index - 21)),
            high=Decimal(101 if index <= 21 else 101 - 5 * (index - 21)),
            low=Decimal(99 if index <= 21 else 99 - 5 * (index - 21)),
        )
        for index, bar in enumerate(bars)
    )
    return _input(bars, tuple(points))


def test_sequence_audit_preserves_same_bar_old_event_and_new_peak_for_all_profiles() -> None:
    """Catches installing a new peak before retaining the old episode's same-Bar facts."""
    analysis = _analysis()

    result = analysis.audit_main_force_mirror_sequences((_sequence_product(),))

    assert tuple(profile.profile_id for profile in result.section.profiles) == (
        "balanced",
        "fast",
        "slow",
        "loose",
        "strict",
    )
    assert tuple(fact_set.profile_id for fact_set in result.fact_sets) == (
        "balanced",
        "fast",
        "slow",
        "loose",
        "strict",
    )
    balanced = result.fact_sets[0].facts
    assert balanced[23].active_peak_index == 21
    assert balanced[23].active_peak_side == "long"
    assert balanced[23].opposite_build_seen is True
    assert balanced[23].accumulated_reversal_seen is True
    assert balanced[23].installed_peak_index == 23
    assert balanced[23].installed_peak_side == "short"
    event_kinds = {
        item.event_kind.value
        for item in result.section.profiles[0].breakdowns[0].events
        if item.raw_count
    }
    assert event_kinds == {
        "peak",
        "decay",
        "liquidation",
        "opposite_build",
        "accumulated_reversal",
    }
    event_counts = {
        item.event_kind.value: item
        for item in result.section.profiles[0].breakdowns[0].events
    }
    assert event_counts["decay"].overlap_count == 0
    assert event_counts["liquidation"].overlap_count == 0
    assert event_counts["peak"].overlap_count == 1
    assert event_counts["opposite_build"].overlap_count == 1
    assert event_counts["accumulated_reversal"].overlap_count == 1
    side_rows = {
        row.key.side: row
        for row in result.section.profiles[0].breakdowns
        if row.key.side is not None
    }
    long_row = side_rows[MainForceMirrorDiagnosticSide.LONG]
    short_row = side_rows[MainForceMirrorDiagnosticSide.SHORT]
    long_events = {item.event_kind.value: item for item in long_row.events}
    short_events = {item.event_kind.value: item for item in short_row.events}
    assert short_events["peak"].raw_count == 1
    assert "opposite_build" not in short_events
    assert "accumulated_reversal" not in short_events
    assert long_events["opposite_build"].raw_count == 1
    assert long_events["accumulated_reversal"].raw_count == 1
    assert short_row.prefix_invariance.checked_prefix_count == 1
    assert event_counts["peak"].raw_count == (
        long_events["peak"].raw_count + short_events["peak"].raw_count
    )
    global_prefix = result.section.profiles[0].breakdowns[0].prefix_invariance
    assert global_prefix.checked_prefix_count == (
        long_row.prefix_invariance.checked_prefix_count
        + short_row.prefix_invariance.checked_prefix_count
    )


def test_sequence_prefix_invariance_is_compared_and_reported_for_every_profile() -> None:
    """Catches reporting prefix invariance without comparing shorter prefixes."""
    analysis = _analysis()

    result = analysis.audit_main_force_mirror_sequences((_sequence_product(),))

    for profile in result.section.profiles:
        prefix = profile.breakdowns[0].prefix_invariance
        assert prefix.checked_prefix_count > 0
        assert prefix.matching_prefix_count == prefix.checked_prefix_count
        assert prefix.mismatch_count == 0
        assert profile.peak_then_decay_sample_count == 1
        assert profile.long_sample_count == 1
        assert profile.short_sample_count == 0
        assert profile.median_delay_bars == Decimal("1")


def test_sequence_roll_resets_old_episode_instead_of_joining_cross_contract() -> None:
    """Catches joining an installed peak to evidence after a contract roll."""
    analysis = _analysis()

    result = analysis.audit_main_force_mirror_sequences(
        (_sequence_product(roll_before_evidence=True),)
    )

    for profile in result.section.profiles:
        assert profile.peak_then_decay_sample_count == 0
        assert profile.breakdowns[0].first_evidence_count == 0


@pytest.mark.parametrize(
    ("boundary", "cross_boundary_transition"),
    (
        ("contract", ("peak", "idle")),
        ("unavailable", ("peak", "idle")),
        ("reset", ("peak", "decay")),
    ),
)
def test_sequence_transition_and_side_fallback_reset_at_physical_block_boundary(
    boundary: str,
    cross_boundary_transition: tuple[str, str],
) -> None:
    """Catches joining states across contract, unavailable, or explicit reset boundaries."""
    analysis = _analysis()
    product = _sequence_product(roll_before_evidence=boundary == "contract")
    if boundary == "unavailable":
        points = list(product.points)
        points[22] = _point(product.bars[22], ready=False)
        traces = list(product.trace)
        traces[22] = _trace(points[22])
        product = _input(product.bars, tuple(points), tuple(traces))
    elif boundary == "reset":
        traces = list(product.trace)
        traces[22] = replace(traces[22], reset_boundary="series_start")
        product = _input(product.bars, product.points, tuple(traces))

    result = analysis.audit_main_force_mirror_sequences((product,))

    for profile in result.section.profiles:
        transitions = {
            (item.from_state.value, item.to_state.value): item.count
            for item in profile.breakdowns[0].transitions
        }
        assert transitions.get(cross_boundary_transition, 0) == 0


def test_sequence_nonmonotonic_input_fails_before_derivation() -> None:
    """Catches treating a nonmonotonic timestamp as a harmless sequence reset."""
    analysis = _analysis()
    product = _sequence_product()
    bars = list(product.bars)
    bars[22] = replace(bars[22], bar_end=bars[21].bar_end)
    corrupted = analysis.MainForceMirrorDiagnosticProductInput(
        symbol=product.symbol,
        bars=tuple(bars),
        points=product.points,
        trace=product.trace,
    )

    with pytest.raises(
        analysis.MainForceMirrorDiagnosticAnalysisError,
        match="MFM_DIAGNOSTIC_ANALYSIS_INVALID",
    ):
        analysis.audit_main_force_mirror_sequences((corrupted,))


def _many_installed_peaks_product(*, with_decay: bool):
    count = 40 if with_decay else 33
    bars, base_points = _fixture(count=count)
    points: list[MainForceMirrorV2Point] = []
    for index, base in enumerate(base_points):
        if index < 20:
            state, instant, accumulated = "turnover", 10.0, 10.0
        elif index < 33:
            state, instant, accumulated = "long_build", 100.0, 80.0
        elif index == 33 and with_decay:
            state, instant, accumulated = "long_liquidation", -60.0, 20.0
        else:
            state, instant, accumulated = "turnover", -10.0, 20.0
        points.append(
            replace(
                base,
                pressure_state=state,  # type: ignore[arg-type]
                instant_pressure=instant,
                accumulated_pressure=accumulated,
            )
        )
    bars = tuple(
        replace(
            bar,
            open=Decimal(100 - max(0, index - 33)),
            high=Decimal(101 - max(0, index - 33)),
            low=Decimal(99 - max(0, index - 33)),
            close=Decimal(100 - max(0, index - 33)),
        )
        for index, bar in enumerate(bars)
    )
    return _input(bars, tuple(points))


def test_sequence_denominator_retains_all_installed_peaks_not_only_decay_samples() -> None:
    """Catches silently dropping replacement and no-decay installed-peak episodes."""
    analysis = _analysis()

    result = analysis.audit_main_force_mirror_sequences(
        (_many_installed_peaks_product(with_decay=True),)
    )
    balanced = result.section.profiles[0]
    global_row = balanced.breakdowns[0]

    assert global_row.raw_episode_count == 13
    assert global_row.kept_episode_count == 13
    assert global_row.overlap_suppressed_count == 0
    assert global_row.first_evidence_count == 1
    assert global_row.delay_sample_count == 1
    assert balanced.peak_then_decay_sample_count == 1

    no_decay = analysis.audit_main_force_mirror_sequences(
        (_many_installed_peaks_product(with_decay=False),)
    ).section.profiles[0]
    assert no_decay.breakdowns[0].raw_episode_count == 13
    assert no_decay.breakdowns[0].first_evidence_count == 0
    assert no_decay.peak_then_decay_sample_count == 0
