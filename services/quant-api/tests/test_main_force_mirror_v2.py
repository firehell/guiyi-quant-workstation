from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import MappingProxyType

import pytest

from guiyi_quant.indicators.main_force_mirror_v2 import (
    DEFAULT_PARAMETERS,
    FORMAL_POLICY_ID,
    INDICATOR_CODE,
    INDICATOR_VERSION,
    MemberRankObservation,
    MemberRankDailyInput,
    compute_member_rank_observation,
    compute_main_force_mirror_v2,
    is_main_force_mirror_v2_candidate,
    round_half_away_from_zero_binary64,
)


_REPO_ROOT = Path(__file__).resolve().parents[3]
_V2_GOLDEN_PATH = (
    _REPO_ROOT / "tests" / "fixtures" / "main_force_mirror_v2_golden.json"
)


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _bar_inputs(bars: list[dict[str, object]]) -> dict[str, list[object]]:
    parsed = [
        datetime.fromisoformat(str(bar["time"]).replace("Z", "+00:00"))
        for bar in bars
    ]
    return {
        "bar_end": parsed,
        "trading_day": [value.date() for value in parsed],
        "physical_contract": [bar["physical_contract"] for bar in bars],
        "open_": [bar["open"] for bar in bars],
        "high": [bar["high"] for bar in bars],
        "low": [bar["low"] for bar in bars],
        "close": [bar["close"] for bar in bars],
        "volume": [bar["volume"] for bar in bars],
        "open_interest": [bar["open_interest"] for bar in bars],
    }


def _make_inputs(count: int, contract: str = "AG2601") -> dict[str, list[object]]:
    bar_end = [
        datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index)
        for index in range(count)
    ]
    close = [100.0 + index for index in range(count)]
    return {
        "bar_end": bar_end,
        "trading_day": [value.date() for value in bar_end],
        "physical_contract": [contract] * count,
        "open_": [value - 0.5 for value in close],
        "high": [value + 1.0 for value in close],
        "low": [value - 1.0 for value in close],
        "close": close,
        "volume": [1000.0 + index for index in range(count)],
        "open_interest": [5000.0 + 10.0 * index for index in range(count)],
    }


def _ready_points(result: object, contract: str) -> list[object]:
    return [
        point
        for point in result.points  # type: ignore[attr-defined]
        if point.physical_contract == contract and point.pressure_ready
    ]


def _public_point(point: object) -> dict[str, object]:
    payload = asdict(point)  # type: ignore[arg-type]
    payload["bar_end"] = point.bar_end.isoformat().replace("+00:00", "Z")  # type: ignore[attr-defined]
    payload["trading_day"] = point.trading_day.isoformat()  # type: ignore[attr-defined]
    payload["caution_reason_codes"] = list(payload["caution_reason_codes"])
    return payload


def test_v2_exposes_exact_public_identity_and_frozen_parameters() -> None:
    assert INDICATOR_CODE == "main_force_mirror_v2"
    assert INDICATOR_VERSION == "futures-member-research-v2"
    assert FORMAL_POLICY_ID == "main_force_mirror_observation_v2"
    assert isinstance(DEFAULT_PARAMETERS, MappingProxyType)
    assert list(DEFAULT_PARAMETERS.items()) == [
        ("atr_period", 14),
        ("volume_window", 20),
        ("oi_impulse_ema_period", 20),
        ("range_window", 20),
        ("pressure_divergence_window", 10),
        ("accumulated_ema_period", 5),
        ("direction_price_weight", 0.7),
        ("direction_clv_weight", 0.3),
        ("direction_deadband", 0.15),
        ("oi_deadband", 0.25),
        ("caution_threshold", 70),
        ("rearm_score_threshold", 40),
        ("rearm_low_score_bars", 3),
        ("rearm_build_bars", 2),
        ("member_neutral_strength", 0.5),
        ("member_strong_strength", 2.0),
        ("member_baseline_days", 60),
        ("member_min_baseline_days", 20),
        ("round_digits", 6),
        ("rounding_policy", "half_away_from_zero_binary64"),
    ]


def test_v2_accumulated_pressure_uses_sma_seed_and_resets_on_contract_switch() -> None:
    inputs = _make_inputs(50)
    inputs["physical_contract"][25:] = ["AG2602"] * 25

    result = compute_main_force_mirror_v2(**inputs)
    first_block_ready = _ready_points(result, "AG2601")
    second_block_ready = _ready_points(result, "AG2602")

    assert len(first_block_ready) == 5
    assert first_block_ready[3].accumulated_pressure is None
    assert first_block_ready[4].accumulated_ready is True
    assert first_block_ready[4].accumulated_pressure == round_half_away_from_zero_binary64(
        sum(point.instant_pressure for point in first_block_ready[:5]) / 5.0, 6
    )
    assert second_block_ready[0].accumulated_pressure is None
    assert second_block_ready[0].accumulated_ready is False
    assert second_block_ready[4].accumulated_ready is True


def test_v2_contract_switch_resets_consumed_caution_latch() -> None:
    inputs = _make_inputs(62)
    inputs["physical_contract"][31:] = ["AG2602"] * 31
    for index in (30, 61):
        inputs["open_"][index] = float(inputs["close"][index]) + 20.0
        inputs["high"][index] = float(inputs["close"][index]) + 50.0
        inputs["low"][index] = float(inputs["close"][index]) - 2.0
        inputs["close"][index] = float(inputs["close"][index]) + 30.0
        inputs["volume"][index] = 5000.0
        inputs["open_interest"][index] = float(inputs["open_interest"][index - 1]) - 60.0

    result = compute_main_force_mirror_v2(**inputs)

    assert result.points[30].caution == "long_chase_caution"
    assert result.points[61].caution == "long_chase_caution"


@pytest.mark.parametrize(
    ("break_kind", "expected_reason", "next_block_start"),
    [
        ("invalid", "MFM_V2_INPUT_INVALID", 26),
        ("missing_contract", "MFM_V2_PHYSICAL_CONTRACT_MISSING", 26),
        ("missing_trading_day", "MFM_V2_MARKET_IDENTITY_CONFLICT", 26),
        ("duplicate_time", "MFM_V2_TIMESTAMP_INVALID", 26),
    ],
)
def test_v2_invalid_identity_and_order_breaks_reset_every_state(
    break_kind: str,
    expected_reason: str,
    next_block_start: int,
) -> None:
    inputs = _make_inputs(52)
    if break_kind == "invalid":
        inputs["volume"][25] = -1.0
    elif break_kind == "missing_contract":
        inputs["physical_contract"][25] = None
    elif break_kind == "missing_trading_day":
        inputs["trading_day"][25] = None
    else:
        inputs["bar_end"][25] = inputs["bar_end"][24]

    result = compute_main_force_mirror_v2(**inputs)

    assert result.points[25].pressure_ready is False
    assert result.points[25].accumulated_ready is False
    assert result.points[25].caution_ready is False
    assert result.points[25].unavailable_reason == expected_reason
    first_ready_after_break = result.points[next_block_start + 20]
    assert first_ready_after_break.pressure_ready is True
    assert first_ready_after_break.accumulated_pressure is None
    assert first_ready_after_break.caution_ready is False


def test_v2_frozen_caution_points_and_break_are_stable() -> None:
    fixture = _load_json(_V2_GOLDEN_PATH)
    primary = compute_main_force_mirror_v2(**_bar_inputs(fixture["bars"]))  # type: ignore[arg-type]
    assert [
        index
        for index, point in enumerate(primary.points)
        if point.caution == "long_chase_caution"
    ] == [30, 34]
    assert [
        index
        for index, point in enumerate(primary.points)
        if point.caution == "short_chase_caution"
    ] == [37]
    assert [
        index for index, point in enumerate(primary.points) if point.caution_conflict
    ] == [36]
    assert primary.points[39].pressure_ready is False
    assert primary.points[39].accumulated_ready is False


def test_v2_member_input_is_a_non_interfering_task_4_seam() -> None:
    inputs = _make_inputs(35)
    member = MemberRankObservation(
        status="ready",
        member_trade_date=date(2025, 12, 31),
        direction="long",
        change_bias=0.02,
        strength=2.0,
        position_skew=0.1,
        top5_volume_share=0.4,
        relation_to_accumulated="strong_aligned",
        relation_to_caution="neutral",
        unavailable_reason=None,
    )
    without_member = compute_main_force_mirror_v2(**inputs)
    with_member = compute_main_force_mirror_v2(
        **inputs, member_inputs=[member] * len(inputs["bar_end"])
    )

    assert [point.member for point in without_member.points] == [None] * 35
    assert [point.member for point in with_member.points] == [member] * 35
    for field in (
        "pressure_ready",
        "pressure_state",
        "instant_pressure",
        "accumulated_ready",
        "accumulated_pressure",
        "caution_ready",
        "caution",
        "caution_conflict",
        "long_caution_score",
        "short_caution_score",
        "caution_reason_codes",
        "unavailable_reason",
    ):
        assert [getattr(point, field) for point in with_member.points] == [
            getattr(point, field) for point in without_member.points
        ]


def _member_day(
    *,
    trade_date: date = date(2025, 12, 31),
    long_total: str = "600",
    short_total: str = "400",
    long_change_total: str = "30",
    short_change_total: str = "-10",
    top5_volume_total: str = "300",
    top20_volume_total: str = "1000",
) -> MemberRankDailyInput:
    return MemberRankDailyInput(
        member_trade_date=trade_date,
        long_total=Decimal(long_total),
        short_total=Decimal(short_total),
        long_change_total=Decimal(long_change_total),
        short_change_total=Decimal(short_change_total),
        top5_volume_total=Decimal(top5_volume_total),
        top20_volume_total=Decimal(top20_volume_total),
    )


def test_member_strength_uses_current_top20_aggregation_and_prior_only_median() -> None:
    """Catches current-day leakage into the causal baseline or wrong Top20 totals."""
    result = compute_member_rank_observation(
        current=_member_day(
            long_total="400",
            short_total="600",
            top5_volume_total="999",
        ),
        prior_change_biases=(Decimal("0.010"),) * 10
        + (Decimal("0.020"),) * 10,
        accumulated_pressure=25.0,
        caution="long_chase_caution",
    )

    assert result.status == "ready"
    assert result.member_trade_date == date(2025, 12, 31)
    assert result.change_bias == 0.04
    assert result.position_skew == -0.2
    assert result.top5_volume_share == 0.999
    assert result.direction == "long"
    assert result.strength == 2.666667
    assert result.relation_to_accumulated == "aligned"
    assert result.relation_to_caution == "strong_aligned"


@pytest.mark.parametrize(
    (
        "change",
        "expected_direction",
        "expected_strength",
        "expected_accumulated_relation",
        "expected_caution_relation",
    ),
    [
        ("4.999", "neutral", 0.4999, "neutral", "neutral"),
        ("5", "long", 0.5, "divergent", "divergent"),
        ("20", "long", 2.0, "divergent", "divergent"),
        ("-20", "short", 2.0, "aligned", "strong_aligned"),
    ],
)
def test_member_direction_strength_thresholds_are_exact(
    change: str,
    expected_direction: str,
    expected_strength: float,
    expected_accumulated_relation: str,
    expected_caution_relation: str,
) -> None:
    """Catches changing neutral/directional/strong tier boundaries."""
    result = compute_member_rank_observation(
        current=_member_day(long_change_total=change, short_change_total="0"),
        prior_change_biases=(Decimal("0.010"),) * 20,
        accumulated_pressure=-1.0,
        caution="short_chase_caution",
    )

    assert result.direction == expected_direction
    assert result.strength == expected_strength
    assert result.relation_to_accumulated == expected_accumulated_relation
    assert result.relation_to_caution == expected_caution_relation


def test_member_baseline_uses_at_most_the_latest_sixty_prior_days() -> None:
    """Catches a baseline that uses stale values beyond the approved 60-day cap."""
    result = compute_member_rank_observation(
        current=_member_day(long_change_total="20", short_change_total="0"),
        prior_change_biases=(Decimal("1.000"), Decimal("1.000"))
        + (Decimal("0.010"),) * 60,
        accumulated_pressure=None,
        caution=None,
    )

    assert result.status == "ready"
    assert result.strength == 2.0
    assert result.direction == "long"
    assert result.relation_to_accumulated == "neutral"
    assert result.relation_to_caution == "neutral"


@pytest.mark.parametrize(
    "current",
    [
        _member_day(long_total="0", short_total="0"),
        _member_day(top5_volume_total="1", top20_volume_total="0"),
    ],
)
def test_member_invalid_current_aggregate_is_unavailable(
    current: MemberRankDailyInput,
) -> None:
    """Catches accepting non-positive member aggregation denominators."""
    result = compute_member_rank_observation(
        current=current,
        prior_change_biases=(Decimal("0.010"),) * 20,
        accumulated_pressure=1.0,
        caution=None,
    )

    assert result.status == "unavailable"
    assert result.unavailable_reason == "MFM_V2_MEMBER_INPUT_INVALID"
    assert result.direction is None
    assert result.relation_to_accumulated == "unavailable"
    assert result.relation_to_caution == "unavailable"


@pytest.mark.parametrize(
    "prior_change_biases",
    [
        (Decimal("0.010"),) * 19,
        (Decimal("0.000"),) * 20,
    ],
)
def test_member_baseline_warmup_is_fail_closed(
    prior_change_biases: tuple[Decimal, ...],
) -> None:
    """Catches insufficient or zero causal baseline becoming a direction."""
    result = compute_member_rank_observation(
        current=_member_day(),
        prior_change_biases=prior_change_biases,
        accumulated_pressure=1.0,
        caution="long_chase_caution",
    )

    assert result.status == "unavailable"
    assert result.unavailable_reason == "MFM_V2_MEMBER_WARMUP"
    assert result.direction is None
    assert result.relation_to_accumulated == "unavailable"
    assert result.relation_to_caution == "unavailable"


def test_v2_candidate_and_state_boundaries_use_unrounded_values() -> None:
    raw_score_that_displays_as_70 = 69.9999996
    assert round_half_away_from_zero_binary64(raw_score_that_displays_as_70, 6) == 70.0
    assert is_main_force_mirror_v2_candidate(raw_score_that_displays_as_70) is False
    assert is_main_force_mirror_v2_candidate(70.0) is True

    inputs = _make_inputs(21)
    close_value = 119.42857028571429
    inputs["open_"][20] = close_value - 0.5
    inputs["high"][20] = close_value + 1.0
    inputs["low"][20] = close_value - 1.0
    inputs["close"][20] = close_value
    result = compute_main_force_mirror_v2(**inputs)

    assert result.points[20].pressure_state == "turnover"


def test_v2_public_rounding_is_half_away_and_normalizes_negative_zero() -> None:
    assert round_half_away_from_zero_binary64(1.25, 1) == 1.3
    assert round_half_away_from_zero_binary64(-1.25, 1) == -1.3
    assert round_half_away_from_zero_binary64(-0.0, 6) == 0.0


def test_v2_matches_independently_frozen_golden() -> None:
    fixture = _load_json(_V2_GOLDEN_PATH)

    assert fixture["schema_version"] == 1
    assert fixture["indicator_code"] == "main_force_mirror_v2"
    assert fixture["indicator_version"] == "futures-member-research-v2"
    assert fixture["formal_policy_id"] == "main_force_mirror_observation_v2"
    result = compute_main_force_mirror_v2(**_bar_inputs(fixture["bars"]))  # type: ignore[arg-type]

    assert result.parameters_hash == fixture["parameters_hash"]
    assert [_public_point(point) for point in result.points] == fixture["expected_points"]
