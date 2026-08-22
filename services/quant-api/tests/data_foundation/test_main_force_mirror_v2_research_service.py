from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

import pytest

from guiyi_quant.indicators.main_force_mirror_v2 import (
    MainForceMirrorV2Point,
    MemberRankDailyInput,
    MemberRankObservation,
    compute_member_rank_observation,
)

from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesKind,
)
from app.research.main_force.main_force_mirror_v2_research_service import (
    MainForceMirrorV2ResearchError,
    MainForceMirrorV2ResearchRequest,
    MainForceMirrorV2ResearchService,
    MainForceMirrorV2SequenceProfile,
    SEQUENCE_PROFILES,
    _derive_sequence_facts,
)
from app.market_data.main_force_mirror_v2_service import (
    MainForceMirrorV2PageResult,
    MemberDatasetState,
)


_CLOSES = (100, 98, 96, 94, 92, 90, 200, 204, 208, 212, 216, 220)


def _bar(index: int) -> CanonicalBar:
    close = Decimal(_CLOSES[index])
    year = 2025 if index < 6 else 2026
    month = 12 if index < 6 else 1
    day = index + 1 if index < 6 else index - 5
    return CanonicalBar(
        bar_end=datetime(year, month, day, 7, tzinfo=UTC),
        trading_day=date(year, month, day),
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=Decimal("100"),
        turnover=None,
        open_interest=Decimal("1000"),
    )


def _member(
    *,
    direction: str,
    strength: str,
    accumulated_relation: str,
    caution_relation: str,
) -> MemberRankObservation:
    return MemberRankObservation(
        status="ready",
        member_trade_date=date(2025, 11, 28),
        direction=direction,  # type: ignore[arg-type]
        change_bias=0.1 if direction == "long" else -0.1,
        strength=float(strength),
        position_skew=0.1,
        top5_volume_share=0.5,
        relation_to_accumulated=accumulated_relation,  # type: ignore[arg-type]
        relation_to_caution=caution_relation,  # type: ignore[arg-type]
        unavailable_reason=None,
    )


def _point(index: int) -> MainForceMirrorV2Point:
    bar = _bar(index)
    is_long_caution = index == 0
    is_short_caution = index == 6
    caution = (
        "long_chase_caution"
        if is_long_caution
        else "short_chase_caution"
        if is_short_caution
        else None
    )
    if is_long_caution:
        member = _member(
            direction="long",
            strength="2.5",
            accumulated_relation="aligned",
            caution_relation="strong_aligned",
        )
    elif is_short_caution:
        member = _member(
            direction="short",
            strength="1.0",
            accumulated_relation="aligned",
            caution_relation="aligned",
        )
    elif index < 6:
        member = _member(
            direction="neutral",
            strength="0.1",
            accumulated_relation="neutral",
            caution_relation="neutral",
        )
    else:
        member = MemberRankObservation.unavailable("fixture-unavailable")
    direction = 1.0 if index < 6 else -1.0
    return MainForceMirrorV2Point(
        bar_end=bar.bar_end,
        trading_day=bar.trading_day,
        physical_contract="JM2609" if index < 6 else "JM2701",
        pressure_ready=True,
        pressure_state="long_build" if index < 6 else "short_build",
        instant_pressure=direction * 10.0,
        accumulated_ready=True,
        accumulated_pressure=direction * 8.0,
        caution_ready=index < 10,
        caution=caution,  # type: ignore[arg-type]
        caution_conflict=False,
        long_caution_score=80.0 if is_long_caution else 0.0,
        short_caution_score=80.0 if is_short_caution else 0.0,
        caution_reason_codes=("fixture",) if caution else (),
        member=member,
        unavailable_reason=None,
        price_impulse=1.0,
        clv=0.5,
        volume_ratio=1.0,
        delta_oi=1.0,
        oi_impulse=1.0,
        range_position=0.5,
    )


_BARS = tuple(_bar(index) for index in range(len(_CLOSES)))
_POINTS = tuple(_point(index) for index in range(len(_CLOSES)))
_SEGMENTS = (
    ResolvedContractSegment("JM2609", date(2025, 12, 1), date(2025, 12, 6)),
    ResolvedContractSegment("JM2701", date(2026, 1, 1), date(2026, 1, 6)),
)


class _MarketData:
    def __init__(
        self,
        *,
        bars: tuple[CanonicalBar, ...] = _BARS,
        segments: tuple[ResolvedContractSegment, ...] = _SEGMENTS,
    ) -> None:
        self.bars = bars
        self.segments = segments

    def query_actual_dominant_trading_days(self, request: object) -> MarketSeriesResult:
        return MarketSeriesResult(
            request_identity=MappingProxyType({"fixture": True}),
            bars=self.bars,
            coverage=(self.bars[0].bar_end, self.bars[-1].bar_end),
            resolved_contract_segments=self.segments,
        )

    def query_contract_trading_days(self, request: object) -> MarketSeriesResult:
        raise AssertionError("contract mode is not used by this fixture")


class _MirrorService:
    def __init__(
        self,
        *,
        points: tuple[MainForceMirrorV2Point, ...] = _POINTS,
        segments: tuple[ResolvedContractSegment, ...] = _SEGMENTS,
        member_dataset: MemberDatasetState | None = None,
    ) -> None:
        self.points = points
        self.segments = segments
        self.member_dataset = member_dataset or MemberDatasetState(
            "ready",
            "fixture-member-v1",
            1,
            True,
            (date(2025, 11, 1), date(2026, 1, 5)),
        )

    def query_page(self, request: object) -> MainForceMirrorV2PageResult:
        return MainForceMirrorV2PageResult(
            request_identity=MappingProxyType(
                {
                    "series_kind": request.series_kind.value,
                    "symbol": request.symbol,
                    "contract": request.contract,
                    "frequency": request.frequency.value,
                    "before": request.before.isoformat() if request.before else None,
                    "limit": request.limit,
                }
            ),
            indicator_code="main_force_mirror_v2",
            indicator_version="futures-member-research-v2",
            formal_policy_id="main_force_mirror_observation_v2",
            parameters_hash="fixture-parameters",
            points=self.points,
            member_dataset=self.member_dataset,
            has_more_before=False,
            next_before=None,
            resolved_contract_segments=self.segments,
        )


def _request() -> MainForceMirrorV2ResearchRequest:
    return MainForceMirrorV2ResearchRequest(
        symbol="jm",
        series_kind=SeriesKind.ACTUAL_DOMINANT,
        contract=None,
        frequency=BarFrequency.H1,
        since=date(2025, 12, 1),
        through=date(2026, 1, 6),
    )


def _result():
    return MainForceMirrorV2ResearchService(
        market_data=_MarketData(),
        mirror_service=_MirrorService(),
    ).run(_request())


def test_research_groups_caution_by_member_relation_without_crossing_roll() -> None:
    result = _result()

    assert result.pooled["all_caution"][5].sample_count == 2
    assert result.pooled["caution_member_strong_aligned"][5].sample_count == 1
    assert result.pooled["caution_member_aligned"][5].sample_count == 1
    assert result.pooled["all_caution"][10].sample_count == 0


def test_research_metrics_are_hand_calculated_from_complete_same_contract_targets() -> None:
    summary = _result().pooled["all_caution"][5]

    assert summary.sample_count == 2
    assert summary.median_directional_return == Decimal("-0.1")
    assert summary.median_reversal_return == Decimal("0.1")
    assert summary.hit_rate == Decimal("1")
    assert summary.median_mfe == Decimal("0.1075")
    assert summary.median_mae == Decimal("0")


def test_research_keeps_product_year_and_frozen_state_as_primary_output() -> None:
    result = _result()

    assert result.yearly[2025]["jm"]["long_chase_caution"]["all_caution"][
        5
    ].sample_count == 1
    assert result.yearly[2026]["jm"]["short_chase_caution"]["all_caution"][
        5
    ].sample_count == 1
    assert result.by_product["jm"]["long_chase_caution"]["all_caution"][
        5
    ].sample_count == 1


def test_research_uses_only_fixed_global_member_strength_sensitivity() -> None:
    result = _result()

    assert tuple(result.sensitivity) == tuple(
        Decimal(value) for value in ("0.5", "1.0", "1.5", "2.0", "2.5")
    )
    assert result.sensitivity[Decimal("0.5")].pooled[5].sample_count == 2
    assert result.sensitivity[Decimal("1.5")].pooled[5].sample_count == 1
    assert result.sensitivity[Decimal("2.0")].pooled[5].sample_count == 1
    assert result.sensitivity[Decimal("2.5")].pooled[5].sample_count == 1
    assert set(result.sensitivity[Decimal("2.0")].by_product) == {"jm"}


def test_research_uses_raw_decimal_member_strength_at_threshold_boundaries() -> None:
    member = compute_member_rank_observation(
        MemberRankDailyInput(
            member_trade_date=date(2025, 11, 28),
            long_total=Decimal("500"),
            short_total=Decimal("500"),
            long_change_total=Decimal("19.999996"),
            short_change_total=Decimal("0"),
            top5_volume_total=Decimal("50"),
            top20_volume_total=Decimal("100"),
        ),
        (Decimal("0.01"),) * 20,
        accumulated_pressure=8.0,
        caution="long_chase_caution",
    )
    assert member.strength == 2.0
    assert member.raw_strength == Decimal("1.9999996")
    assert member.relation_to_caution == "aligned"
    points = (replace(_POINTS[0], member=member), *_POINTS[1:])
    result = MainForceMirrorV2ResearchService(
        market_data=_MarketData(),
        mirror_service=_MirrorService(points=points),
    ).run(_request())

    assert result.pooled["member_strong_aligned"][5].sample_count == 0
    assert result.sensitivity[Decimal("2.0")].pooled[5].sample_count == 0


def test_research_rejects_points_swapped_from_authoritative_market_segments() -> None:
    swapped = tuple(
        replace(
            point,
            physical_contract="JM2701" if point.physical_contract == "JM2609" else "JM2609",
        )
        for point in _POINTS
    )

    with pytest.raises(
        MainForceMirrorV2ResearchError,
        match="MFM_V2_RESEARCH_IDENTITY_CONFLICT",
    ):
        MainForceMirrorV2ResearchService(
            market_data=_MarketData(),
            mirror_service=_MirrorService(points=swapped),
        ).run(_request())


def test_research_rejects_page_request_identity_drift() -> None:
    class _DriftedMirror(_MirrorService):
        def query_page(self, request: object) -> MainForceMirrorV2PageResult:
            page = super().query_page(request)
            return replace(
                page,
                request_identity=MappingProxyType(
                    {**page.request_identity, "symbol": "ag"}
                ),
            )

    with pytest.raises(
        MainForceMirrorV2ResearchError,
        match="MFM_V2_RESEARCH_IDENTITY_CONFLICT",
    ):
        MainForceMirrorV2ResearchService(
            market_data=_MarketData(),
            mirror_service=_DriftedMirror(),
        ).run(_request())


def test_research_labels_retrospective_and_reports_explicit_denominators() -> None:
    result = _result()

    assert result.research_protocol == "main_force_mirror_v2_retrospective_v1"
    assert result.evaluation_classification == (
        "retrospective_walk_forward_diagnostic"
    )
    assert result.prospective_oos_starts_after == date(2026, 8, 20)
    assert result.member_dataset_id == "fixture-member-v1"
    assert result.member_coverage == Decimal("0.583333")
    assert result.caution_ready_bars == 10
    assert result.caution_events == 2
    assert result.caution_events_per_1000_ready_bars == Decimal("200")


@pytest.mark.parametrize(
    ("through", "expected_starts_after"),
    (
        (date(2026, 1, 6), date(2026, 8, 20)),
        (date(2026, 8, 20), date(2026, 8, 20)),
        (date(2026, 8, 21), date(2026, 8, 21)),
    ),
)
def test_research_never_repackages_known_retrospective_days_as_prospective(
    through: date,
    expected_starts_after: date,
) -> None:
    result = MainForceMirrorV2ResearchService(
        market_data=_MarketData(),
        mirror_service=_MirrorService(),
    ).run(replace(_request(), through=through))

    assert result.prospective_oos_starts_after == expected_starts_after


def test_research_reports_member_coverage_unknown_when_dataset_is_unavailable() -> None:
    points = tuple(replace(point, member=None) for point in _POINTS)
    result = MainForceMirrorV2ResearchService(
        market_data=_MarketData(),
        mirror_service=_MirrorService(
            points=points,
            member_dataset=MemberDatasetState(
                "unavailable", None, None, False, None
            ),
        ),
    ).run(_request())

    assert result.member_dataset_id is None
    assert result.member_coverage is None


def _minimal_point(
    bar: CanonicalBar,
    *,
    physical_contract: str,
    instant_pressure: float | None,
    accumulated_pressure: float | None = None,
    member: MemberRankObservation | None = None,
) -> MainForceMirrorV2Point:
    ready = instant_pressure is not None
    accumulated_ready = accumulated_pressure is not None
    return MainForceMirrorV2Point(
        bar_end=bar.bar_end,
        trading_day=bar.trading_day,
        physical_contract=physical_contract,
        pressure_ready=ready,
        pressure_state="long_build" if ready or accumulated_ready else None,
        instant_pressure=instant_pressure,
        accumulated_ready=accumulated_ready,
        accumulated_pressure=accumulated_pressure,
        caution_ready=False,
        caution=None,
        caution_conflict=False,
        long_caution_score=None,
        short_caution_score=None,
        caution_reason_codes=(),
        member=member,
        unavailable_reason=None,
        price_impulse=None,
        clv=None,
        volume_ratio=None,
        delta_oi=None,
        oi_impulse=None,
        range_position=None,
    )


def _custom_result(
    bars: tuple[CanonicalBar, ...],
    points: tuple[MainForceMirrorV2Point, ...],
    segments: tuple[ResolvedContractSegment, ...],
    *,
    since: date,
    through: date,
):
    return MainForceMirrorV2ResearchService(
        market_data=_MarketData(bars=bars, segments=segments),
        mirror_service=_MirrorService(points=points, segments=segments),
    ).run(
        MainForceMirrorV2ResearchRequest(
            symbol="jm",
            series_kind=SeriesKind.ACTUAL_DOMINANT,
            contract=None,
            frequency=BarFrequency.H1,
            since=since,
            through=through,
        )
    )


def test_research_hit_rate_uses_raw_micro_returns_before_public_rounding() -> None:
    day = date(2026, 1, 8)
    prices = (
        Decimal("1000000"),
        Decimal("1000000.4"),
        Decimal("1000000"),
        Decimal("999999.6"),
    )
    bars = tuple(
        CanonicalBar(
            bar_end=datetime(2026, 1, 8, index + 1, tzinfo=UTC),
            trading_day=day,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=Decimal("1"),
            turnover=None,
            open_interest=Decimal("1"),
        )
        for index, price in enumerate(prices)
    )
    points = tuple(
        _minimal_point(
            bar,
            physical_contract="JM2609",
            instant_pressure=1.0 if index in {0, 2} else None,
        )
        for index, bar in enumerate(bars)
    )
    result = _custom_result(
        bars,
        points,
        (ResolvedContractSegment("JM2609", day, day),),
        since=day,
        through=day,
    )

    summary = result.pooled["instant_pressure"][1]
    assert summary.sample_count == 2
    assert summary.median_directional_return == Decimal("0")
    assert summary.hit_rate == Decimal("0.5")


def _sequence_point(
    index: int,
    *,
    state: str,
    instant: float | None,
    accumulated: float | None,
    contract: str | None = "JM2609",
    pressure_ready: bool = True,
    accumulated_ready: bool = True,
) -> MainForceMirrorV2Point:
    moment = datetime(2026, 2, 1, 7, tzinfo=UTC) + timedelta(hours=index)
    return replace(
        _POINTS[0],
        bar_end=moment,
        trading_day=moment.date(),
        physical_contract=contract,
        pressure_ready=pressure_ready,
        pressure_state=state,  # type: ignore[arg-type]
        instant_pressure=instant,
        accumulated_ready=accumulated_ready,
        accumulated_pressure=accumulated,
        caution=None,
        caution_conflict=False,
        long_caution_score=0.0,
        short_caution_score=0.0,
        caution_reason_codes=(),
        unavailable_reason=None,
    )


def _long_sequence_points() -> tuple[MainForceMirrorV2Point, ...]:
    prior = tuple(
        _sequence_point(
            index,
            state="long_build",
            instant=10.0 + index,
            accumulated=8.0 + index,
        )
        for index in range(21)
    )
    return (
        *prior,
        _sequence_point(21, state="long_build", instant=100.0, accumulated=80.0),
        _sequence_point(
            22,
            state="long_liquidation",
            instant=-60.0,
            accumulated=30.0,
        ),
        _sequence_point(23, state="short_build", instant=-70.0, accumulated=-10.0),
    )


def _short_sequence_points() -> tuple[MainForceMirrorV2Point, ...]:
    mirror_state = {
        "long_build": "short_build",
        "long_liquidation": "short_cover",
        "short_build": "long_build",
    }
    return tuple(
        replace(
            point,
            pressure_state=mirror_state[str(point.pressure_state)],  # type: ignore[arg-type]
            instant_pressure=(
                None
                if point.instant_pressure is None
                else -point.instant_pressure
            ),
            accumulated_pressure=(
                None
                if point.accumulated_pressure is None
                else -point.accumulated_pressure
            ),
        )
        for point in _long_sequence_points()
    )


def _sequence_profile(profile_id: str) -> MainForceMirrorV2SequenceProfile:
    return next(
        profile for profile in SEQUENCE_PROFILES if profile.profile_id == profile_id
    )


def test_sequence_profiles_are_exact_small_global_set() -> None:
    assert [
        (
            profile.profile_id,
            profile.peak_window,
            profile.peak_quantile,
            profile.decay_threshold,
            profile.transition_window,
        )
        for profile in SEQUENCE_PROFILES
    ] == [
        ("balanced", 10, Decimal("0.90"), Decimal("0.40"), 2),
        ("fast", 5, Decimal("0.90"), Decimal("0.40"), 1),
        ("slow", 20, Decimal("0.90"), Decimal("0.40"), 3),
        ("loose", 10, Decimal("0.85"), Decimal("0.25"), 2),
        ("strict", 10, Decimal("0.95"), Decimal("0.55"), 2),
    ]


def test_sequence_long_peak_emits_later_events_on_evidence_bars() -> None:
    facts = _derive_sequence_facts(
        _long_sequence_points(), _sequence_profile("balanced")
    )

    assert facts[21].installed_peak_side == "long"
    assert facts[21].peak_seen is True
    assert facts[21].decay_seen is False
    assert facts[21].liquidation_seen is False
    assert facts[22].active_peak_index == 21
    assert facts[22].active_peak_side == "long"
    assert facts[22].decay_ratio == Decimal("0.625")
    assert facts[22].decay_seen is True
    assert facts[22].liquidation_seen is True
    assert facts[23].active_peak_index == 21
    assert facts[23].opposite_build_seen is True
    assert facts[23].accumulated_reversal_seen is True


def test_sequence_overlap_retains_old_event_and_new_peak_installation() -> None:
    facts = _derive_sequence_facts(
        _long_sequence_points(), _sequence_profile("balanced")
    )

    assert facts[23].active_peak_index == 21
    assert facts[23].active_peak_side == "long"
    assert facts[23].opposite_build_seen is True
    assert facts[23].installed_peak_index == 23
    assert facts[23].installed_peak_side == "short"
    assert facts[23].peak_seen is True


def test_sequence_short_side_is_exact_sign_state_mirror() -> None:
    facts = _derive_sequence_facts(
        _short_sequence_points(), _sequence_profile("balanced")
    )

    assert facts[21].installed_peak_side == "short"
    assert facts[21].peak_seen is True
    assert facts[22].active_peak_side == "short"
    assert facts[22].decay_ratio == Decimal("0.625")
    assert facts[22].decay_seen is True
    assert facts[22].liquidation_seen is True
    assert facts[23].opposite_build_seen is True
    assert facts[23].accumulated_reversal_seen is True
    assert facts[23].installed_peak_side == "long"


def test_sequence_event_types_emit_only_first_occurrence_for_one_peak() -> None:
    points = (
        *_long_sequence_points()[:23],
        _sequence_point(23, state="short_build", instant=-1.0, accumulated=-10.0),
        _sequence_point(24, state="short_build", instant=-1.0, accumulated=-20.0),
    )
    facts = _derive_sequence_facts(points, _sequence_profile("slow"))

    assert facts[22].decay_seen is True
    assert facts[22].liquidation_seen is True
    assert facts[23].active_peak_index == 21
    assert facts[23].opposite_build_seen is True
    assert facts[23].accumulated_reversal_seen is True
    assert facts[23].peak_seen is False
    assert facts[24].active_peak_index == 21
    assert facts[24].decay_seen is False
    assert facts[24].opposite_build_seen is False
    assert facts[24].accumulated_reversal_seen is False


def test_sequence_requires_full_strict_prior_window() -> None:
    points = tuple(
        _sequence_point(
            index,
            state="long_build",
            instant=100.0,
            accumulated=80.0,
        )
        for index in range(11)
    )
    facts = _derive_sequence_facts(points, _sequence_profile("balanced"))

    assert all(not fact.peak_seen for fact in facts[:10])
    assert facts[10].installed_peak_index == 10


def test_sequence_memory_resets_at_physical_contract_change() -> None:
    points = tuple(
        replace(point, physical_contract="JM2701") if index >= 22 else point
        for index, point in enumerate(_long_sequence_points())
    )
    facts = _derive_sequence_facts(points, _sequence_profile("balanced"))

    assert facts[21].peak_seen is True
    assert facts[22].active_peak_index is None
    assert facts[22].decay_seen is False
    assert facts[22].liquidation_seen is False
    assert facts[23].opposite_build_seen is False


def test_sequence_memory_resets_on_non_monotonic_time() -> None:
    points = list(_long_sequence_points())
    points[22] = replace(points[22], bar_end=points[21].bar_end)
    facts = _derive_sequence_facts(tuple(points), _sequence_profile("balanced"))

    assert facts[22].active_peak_index is None
    assert facts[22].liquidation_seen is False


def test_sequence_pressure_unavailable_resets_memory() -> None:
    points = list(_long_sequence_points())
    points[22] = replace(points[22], pressure_ready=False)
    facts = _derive_sequence_facts(tuple(points), _sequence_profile("balanced"))

    assert facts[22].active_peak_index is None
    assert facts[22].liquidation_seen is False


def test_sequence_accumulated_unavailable_keeps_state_events_only() -> None:
    points = list(_long_sequence_points())
    points[22] = replace(
        points[22], accumulated_ready=False, accumulated_pressure=None
    )
    facts = _derive_sequence_facts(tuple(points), _sequence_profile("balanced"))

    assert facts[22].active_peak_index == 21
    assert facts[22].liquidation_seen is True
    assert facts[22].decay_ratio is None
    assert facts[22].decay_seen is False
    assert facts[22].accumulated_reversal_seen is False


def test_sequence_zero_peak_accumulated_does_not_fabricate_decay() -> None:
    points = list(_long_sequence_points())
    points[21] = replace(points[21], accumulated_pressure=0.0)
    facts = _derive_sequence_facts(tuple(points), _sequence_profile("balanced"))

    assert facts[22].active_peak_index == 21
    assert facts[22].liquidation_seen is True
    assert facts[22].decay_ratio is None
    assert facts[22].decay_seen is False
    assert facts[23].accumulated_reversal_seen is False


@pytest.mark.parametrize("profile", SEQUENCE_PROFILES)
def test_sequence_derivation_is_prefix_invariant(
    profile: MainForceMirrorV2SequenceProfile,
) -> None:
    points = _long_sequence_points()
    full = _derive_sequence_facts(points, profile)

    for end in range(1, len(points) + 1):
        assert _derive_sequence_facts(points[:end], profile)[-1] == full[end - 1]


def _directional_fixture_result():
    first_day = date(2026, 2, 2)
    second_day = date(2026, 2, 3)
    bars: list[CanonicalBar] = []
    points: list[MainForceMirrorV2Point] = []
    aligned = _member(
        direction="long",
        strength="1.0",
        accumulated_relation="aligned",
        caution_relation="neutral",
    )
    divergent = _member(
        direction="short",
        strength="1.0",
        accumulated_relation="divergent",
        caution_relation="neutral",
    )
    for block, (trading_day, contract, price_step, member) in enumerate(
        (
            (first_day, "JM2609", 1, aligned),
            (second_day, "JM2701", -1, divergent),
        )
    ):
        for offset in range(11):
            close = Decimal(100 + price_step * offset)
            bar = CanonicalBar(
                bar_end=datetime(2026, 2, 2 + block, tzinfo=UTC)
                + timedelta(hours=offset + 1),
                trading_day=trading_day,
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=Decimal("10"),
                turnover=None,
                open_interest=Decimal("100"),
            )
            bars.append(bar)
            points.append(
                _minimal_point(
                    bar,
                    physical_contract=contract,
                    instant_pressure=1.0 if offset == 0 else None,
                    accumulated_pressure=1.0 if offset == 0 else None,
                    member=member if offset == 0 else None,
                )
            )
    return _custom_result(
        tuple(bars),
        tuple(points),
        (
            ResolvedContractSegment("JM2609", first_day, first_day),
            ResolvedContractSegment("JM2701", second_day, second_day),
        ),
        since=first_day,
        through=second_day,
    )


@pytest.mark.parametrize(
    (
        "horizon",
        "aligned_return",
        "aligned_mfe",
        "divergent_return",
        "divergent_mae",
        "pooled_excursion",
        "spread_value",
    ),
    (
        (1, "0.01", "0.02", "-0.01", "0.02", "0.01", "0.02"),
        (3, "0.03", "0.04", "-0.03", "0.04", "0.02", "0.06"),
        (5, "0.05", "0.06", "-0.05", "0.06", "0.03", "0.1"),
        (10, "0.1", "0.11", "-0.1", "0.11", "0.055", "0.2"),
    ),
)
def test_research_hand_fixture_covers_directional_metrics_and_group_spread(
    horizon: int,
    aligned_return: str,
    aligned_mfe: str,
    divergent_return: str,
    divergent_mae: str,
    pooled_excursion: str,
    spread_value: str,
) -> None:
    result = _directional_fixture_result()
    instant = result.pooled["instant_pressure"][horizon]
    accumulated = result.pooled["accumulated_pressure"][horizon]
    aligned = result.pooled["member_aligned"][horizon]
    divergent = result.pooled["member_divergent"][horizon]
    spread = result.top_bottom_spreads[horizon]

    assert instant.sample_count == accumulated.sample_count == 2
    assert instant.median_directional_return == Decimal("0")
    assert accumulated.median_directional_return == Decimal("0")
    assert instant.hit_rate == accumulated.hit_rate == Decimal("0.5")
    assert instant.median_mfe == accumulated.median_mfe == Decimal(
        pooled_excursion
    )
    assert instant.median_mae == accumulated.median_mae == Decimal(
        pooled_excursion
    )
    assert aligned.sample_count == 1
    assert aligned.median_directional_return == Decimal(aligned_return)
    assert aligned.hit_rate == Decimal("1")
    assert aligned.median_mfe == Decimal(aligned_mfe)
    assert aligned.median_mae == Decimal("0")
    assert divergent.sample_count == 1
    assert divergent.median_directional_return == Decimal(divergent_return)
    assert divergent.hit_rate == Decimal("0")
    assert divergent.median_mfe == Decimal("0")
    assert divergent.median_mae == Decimal(divergent_mae)
    assert spread.top_group == "member_aligned"
    assert spread.bottom_group == "member_divergent"
    assert spread.directional_return_spread == Decimal(spread_value)
