from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from types import MappingProxyType

from guiyi_quant.indicators.main_force_mirror_v2 import (
    MainForceMirrorV2Point,
    MemberRankObservation,
)

from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesKind,
)
from app.market_data.main_force_mirror_v2_research_service import (
    MainForceMirrorV2ResearchRequest,
    MainForceMirrorV2ResearchService,
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
    def query_actual_dominant_trading_days(self, request: object) -> MarketSeriesResult:
        return MarketSeriesResult(
            request_identity=MappingProxyType({"fixture": True}),
            bars=_BARS,
            coverage=(_BARS[0].bar_end, _BARS[-1].bar_end),
            resolved_contract_segments=_SEGMENTS,
        )

    def query_contract_trading_days(self, request: object) -> MarketSeriesResult:
        raise AssertionError("contract mode is not used by this fixture")


class _MirrorService:
    def __init__(
        self,
        *,
        points: tuple[MainForceMirrorV2Point, ...] = _POINTS,
        member_dataset: MemberDatasetState | None = None,
    ) -> None:
        self.points = points
        self.member_dataset = member_dataset or MemberDatasetState(
            "ready",
            "fixture-member-v1",
            1,
            True,
            (date(2025, 11, 1), date(2026, 1, 5)),
        )

    def query_page(self, request: object) -> MainForceMirrorV2PageResult:
        return MainForceMirrorV2PageResult(
            request_identity=MappingProxyType({"fixture": True}),
            indicator_code="main_force_mirror_v2",
            indicator_version="futures-member-research-v2",
            formal_policy_id="main_force_mirror_observation_v2",
            parameters_hash="fixture-parameters",
            points=self.points,
            member_dataset=self.member_dataset,
            has_more_before=False,
            next_before=None,
            resolved_contract_segments=_SEGMENTS,
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


def test_research_labels_retrospective_and_reports_explicit_denominators() -> None:
    result = _result()

    assert result.research_protocol == "main_force_mirror_v2_retrospective_v1"
    assert result.evaluation_classification == (
        "retrospective_walk_forward_diagnostic"
    )
    assert result.prospective_oos_starts_after == date(2026, 1, 6)
    assert result.member_dataset_id == "fixture-member-v1"
    assert result.member_coverage == Decimal("0.583333")
    assert result.caution_ready_bars == 10
    assert result.caution_events == 2
    assert result.caution_events_per_1000_ready_bars == Decimal("200")


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
