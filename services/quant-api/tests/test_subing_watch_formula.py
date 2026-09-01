from __future__ import annotations

import json
import math
import re
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

import guiyi_quant.indicators.subing_watch_15m as subing_watch_kernel
from app.market_data.domain import CanonicalBar
from app.market_data.subing_watch.contracts import (
    SubingWatchContractError,
    SubingWatchPolicyError,
    SubingWatchSourceIdentity,
    from_kernel_evaluation,
    load_subing_watch_policy,
    to_subing_watch_kernel_bar,
)
from guiyi_quant.indicators.subing_watch_15m import (
    SubingWatchKernelBar,
    SubingWatchKernelContext,
    SubingWatchKernelError,
    SubingWatchKernelEvaluation,
    SubingWatchKernelHigherTimeframe,
    SubingWatchKernelIdentity,
    initial_subing_watch_kernel_state,
)


POLICY_PATH = (
    Path(__file__).resolve().parents[3]
    / "data/research_policies/subing_watch_15m_v1.json"
)
OPAQUE_FINGERPRINT = "0" * 64
GOLDEN_PATH = Path(__file__).parent / "fixtures/subing_watch_15m_v1_golden.json"
GOLDEN_PAYLOAD_SHA256 = (
    "8423e85c5e0cd4c9abaad89e4a59bbaa1a9468544f031d68b7878bd5341bfec0"
)


def canonical_bar(*, close: Decimal = Decimal("123.4567894")) -> CanonicalBar:
    return CanonicalBar(
        bar_end=datetime(2026, 9, 1, 2, 15, tzinfo=UTC),
        trading_day=date(2026, 9, 1),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=Decimal("20"),
        turnover=None,
        open_interest=None,
    )


def kernel_evaluation(
    *,
    ma21: float = 123.456789,
    identity: SubingWatchKernelIdentity | None = None,
) -> SubingWatchKernelEvaluation:
    source_identity = identity or SubingWatchKernelIdentity(
        symbol="jm",
        contract="JM2601",
        segment_start_trading_day="2026-09-01",
    )
    context = SubingWatchKernelContext(
        ma21_slope_5_bps_per_bar=None,
        distance_to_ma21_atr14=None,
        macd_zero_distance_atr14=None,
        volume_ratio_20=None,
        range_state="range_unavailable",
        higher_timeframe_alignment="unavailable",
    )
    return SubingWatchKernelEvaluation(
        formula_version="subing_watch_15m_v1",
        identity=source_identity,
        trading_day="2026-09-01",
        bar_end="2026-09-01T02:15:00+00:00",
        outcome="evaluated_no_signal",
        observation_types=(),
        close=123.456789,
        ma21=ma21,
        dif=None,
        dea=None,
        macd_histogram=None,
        context=context,
        public_reason_codes=(),
    )


def watch_identity(
    *, contract: str = "JM2601", segment_start: str = "2026-09-01"
) -> SubingWatchKernelIdentity:
    return SubingWatchKernelIdentity(
        symbol=contract.rstrip("0123456789").lower(),
        contract=contract,
        segment_start_trading_day=segment_start,
    )


def watch_source_identity(
    *, contract: str = "JM2601", segment_start: date = date(2026, 9, 1)
) -> SubingWatchSourceIdentity:
    return SubingWatchSourceIdentity(
        symbol=contract.rstrip("0123456789").lower(),
        contract=contract,
        segment_start_trading_day=segment_start,
    )


def watch_bar(
    index: int,
    close: float,
    *,
    fingerprint: str | None = None,
    trading_day: str = "2026-09-01",
    identity: SubingWatchKernelIdentity | None = None,
    high_low_width: float = 0.0,
    volume: float | None = None,
) -> SubingWatchKernelBar:
    bar_end = datetime(2026, 9, 1, tzinfo=UTC) + timedelta(minutes=index * 15)
    return SubingWatchKernelBar(
        identity=identity or watch_identity(),
        bar_end=bar_end.isoformat(),
        trading_day=trading_day,
        open=close,
        high=close + high_low_width,
        low=close - high_low_width,
        close=close,
        volume=100.0 + index if volume is None else volume,
        source_fingerprint=fingerprint
        or sha256(f"subing-watch-test-{index}-{close}".encode()).hexdigest(),
    )


def required_initial_state(
    identity: SubingWatchKernelIdentity | None = None,
) -> Any:
    policy = load_subing_watch_policy(POLICY_PATH)
    try:
        return initial_subing_watch_kernel_state(identity or watch_identity(), policy)
    except TypeError:
        pytest.fail("Task 2 initial state does not yet require the frozen policy")


def required_step(state: Any, bar: SubingWatchKernelBar) -> tuple[Any, Any]:
    step = getattr(subing_watch_kernel, "step_subing_watch_15m", None)
    assert callable(step), "Task 2 completed-15m step is not implemented"
    return step(state, bar)


def stream_closes(closes: list[float]) -> tuple[Any, list[Any]]:
    state = required_initial_state()
    evaluations = []
    for index, close in enumerate(closes, start=1):
        state, evaluation = required_step(state, watch_bar(index, close))
        evaluations.append(evaluation)
    return state, evaluations


def watch_higher_timeframe(
    *,
    alignment: str = "aligned",
    bar_end: str = "2026-09-01T08:00:00+00:00",
    identity: SubingWatchKernelIdentity | None = None,
    ready: bool = True,
    valid: bool = True,
) -> SubingWatchKernelHigherTimeframe:
    close, slope = {
        "aligned": (110.0, 5.0),
        "opposed": (90.0, -5.0),
        "neutral": (110.0, -5.0),
    }[alignment]
    return SubingWatchKernelHigherTimeframe(
        bar_end=bar_end,
        close=close,
        ma21=100.0,
        ma21_slope_5_bps_per_bar=slope,
        ready=ready,
        valid=valid,
        identity=identity or watch_identity(),
    )


def candidate_prefix_state() -> Any:
    state = required_initial_state()
    for index in range(1, 35):
        state, _ = required_step(
            state,
            watch_bar(index, 100.0, high_low_width=1.0),
        )
    return state


def ready_range_state(kind: str) -> Any:
    from guiyi_quant.indicators import (
        initial_range_detector_lux_state,
        step_range_detector_lux,
    )

    source_identity = "jm|JM2601|2026-09-01|actual_dominant|15m"
    multiplier = (
        100.0
        if kind == "intact"
        else 0.01
        if kind == "no_active_range"
        else 0.1
    )
    closes = [100.0] * 4 if kind != "no_active_range" else [100.0, 110.0, 100.0, 110.0]
    state = initial_range_detector_lux_state(
        source_identity=source_identity,
        minimum_range_length=3,
        range_width_atr_multiplier=multiplier,
        range_atr_length=3,
    )
    for index, close in enumerate(closes, start=1):
        state, _ = step_range_detector_lux(
            state,
            high=close + 1.0,
            low=close - 1.0,
            close=close,
            bar_end=watch_bar(index, close).bar_end,
            trading_day="2026-09-01",
        )
    if kind in {"broken_up", "broken_down"}:
        close = 110.0 if kind == "broken_up" else 90.0
        state, _ = step_range_detector_lux(
            state,
            high=close + 1.0,
            low=close - 1.0,
            close=close,
            bar_end=watch_bar(5, close).bar_end,
            trading_day="2026-09-01",
        )
    return state


def candidate_fixture(
    case: str,
) -> tuple[Any, SubingWatchKernelBar, SubingWatchKernelHigherTimeframe | None]:
    state = candidate_prefix_state()
    higher: SubingWatchKernelHigherTimeframe | None = watch_higher_timeframe()
    if case != "range_unavailable":
        state = replace(state, range_state=ready_range_state("intact"))
    if case == "atr_unavailable":
        from guiyi_quant.indicators import initial_atr_state

        state = replace(
            state,
            atr_state=initial_atr_state(
                14,
                smoothing_policy="wilder_sma_seed",
                round_digits=6,
            ),
        )
    elif case == "volume_denominator_zero":
        state = replace(state, previous_twenty_volumes=(0.0,) * 20)
    elif case == "higher_timeframe_missing":
        higher = None
    elif case == "higher_timeframe_opposed":
        higher = watch_higher_timeframe(alignment="opposed")
    return state, watch_bar(35, 110.0, high_low_width=1.0), higher


def test_policy_pins_sma21_and_macd_seed() -> None:
    policy = load_subing_watch_policy(POLICY_PATH)

    assert policy.ma_type == "simple_moving_average"
    assert policy.ma_period == 21
    assert policy.macd == (12, 26, 9)
    assert policy.ema_seed_policy == "sma_window"
    assert policy.histogram_scale == 2
    assert policy.auto_order is False


def test_policy_exposes_the_complete_frozen_context() -> None:
    policy = load_subing_watch_policy(POLICY_PATH)

    assert policy.series_kind == "actual_dominant"
    assert policy.frequency == "15m"
    assert policy.completed_bar_only is True
    assert policy.ma_source == "close"
    assert policy.atr_period == 14
    assert policy.atr_smoothing_policy == "wilder_sma_seed"
    assert policy.ma_slope_points == 5
    assert policy.volume_previous_bars == 20
    assert policy.range_indicator_code == "range_detector_lux_v1"
    assert policy.higher_timeframe == "60m"
    assert policy.round_digits == 6


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("ma", "type"), "exponential_moving_average"),
        (("auto_order",), True),
        (("macd", "fast"), 12.0),
    ),
)
def test_policy_rejects_semantic_or_type_drift(
    tmp_path: Path, path: tuple[str, ...], value: object
) -> None:
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    invalid_path = tmp_path / "policy.json"
    invalid_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SubingWatchPolicyError, match="SUBING_WATCH_POLICY_INVALID"):
        load_subing_watch_policy(invalid_path)


def test_policy_rejects_unknown_field(tmp_path: Path) -> None:
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    invalid_path = tmp_path / "policy.json"
    invalid_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SubingWatchPolicyError, match="SUBING_WATCH_POLICY_INVALID"):
        load_subing_watch_policy(invalid_path)


def test_policy_rejects_missing_field(tmp_path: Path) -> None:
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    del payload["context"]["atr_period"]
    invalid_path = tmp_path / "policy.json"
    invalid_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SubingWatchPolicyError, match="SUBING_WATCH_POLICY_INVALID"):
        load_subing_watch_policy(invalid_path)


def test_decimal_float_boundary_is_single_and_deterministic() -> None:
    kernel = to_subing_watch_kernel_bar(
        canonical_bar(), source_identity=watch_source_identity()
    )
    app = from_kernel_evaluation(kernel_evaluation(), source_mode="canonical")

    assert kernel.close == 123.4567894
    assert re.fullmatch(r"[0-9a-f]{64}", kernel.source_fingerprint)
    assert app.ma21 == Decimal("123.456789")
    assert app.close == Decimal("123.456789")
    assert app.source_identity == SubingWatchSourceIdentity(
        symbol="jm",
        contract="JM2601",
        segment_start_trading_day=date(2026, 9, 1),
    )
    assert app.source_identity_digest.startswith("subing-watch-source:")


def test_adapter_uses_distinct_opaque_fingerprints_before_float_boundary() -> None:
    first = to_subing_watch_kernel_bar(
        canonical_bar(close=Decimal("9007199254740992")),
        source_identity=watch_source_identity(),
    )
    second = to_subing_watch_kernel_bar(
        canonical_bar(close=Decimal("9007199254740993")),
        source_identity=watch_source_identity(),
    )

    assert first.close == second.close
    assert first.source_fingerprint != second.source_fingerprint
    assert re.fullmatch(r"[0-9a-f]{64}", first.source_fingerprint)
    assert re.fullmatch(r"[0-9a-f]{64}", second.source_fingerprint)


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (1.2, Decimal("1.200000")),
        (1.2345674, Decimal("1.234567")),
        (1.2345678, Decimal("1.234568")),
    ),
)
def test_adapter_restores_kernel_numbers_as_fixed_six_decimal_text(
    value: float, expected: Decimal
) -> None:
    app = from_kernel_evaluation(
        kernel_evaluation(ma21=value), source_mode="canonical"
    )

    assert app.ma21 == expected
    assert app.ma21.as_tuple().exponent == -6


@pytest.mark.parametrize(
    ("symbol", "contract", "frequency"),
    (
        ("jm ", "JM2601", "15m"),
        ("jm", "RB2601", "15m"),
        ("jm", "JM2601", "5m"),
    ),
)
def test_source_identity_rejects_invalid_symbol_contract_or_frequency(
    symbol: str, contract: str, frequency: str
) -> None:
    with pytest.raises(SubingWatchContractError, match="SUBING_WATCH_CONTRACT_INVALID"):
        SubingWatchSourceIdentity(
            symbol=symbol,
            contract=contract,
            segment_start_trading_day=date(2026, 9, 1),
            frequency=frequency,  # type: ignore[arg-type]
        )


def test_kernel_bar_rejects_non_aware_time() -> None:
    with pytest.raises(SubingWatchKernelError, match="SUBING_WATCH_KERNEL_INVALID"):
        SubingWatchKernelBar(
            identity=watch_identity(),
            bar_end="2026-09-01T02:15:00",
            trading_day="2026-09-01",
            open=10.0,
            high=10.0,
            low=8.0,
            close=10.0,
            volume=20.0,
            source_fingerprint=OPAQUE_FINGERPRINT,
        )


def test_kernel_bar_rejects_invalid_ohlc_after_aware_time_validation() -> None:
    with pytest.raises(SubingWatchKernelError, match="SUBING_WATCH_KERNEL_INVALID"):
        SubingWatchKernelBar(
            identity=watch_identity(),
            bar_end="2026-09-01T02:15:00+00:00",
            trading_day="2026-09-01",
            open=10.0,
            high=9.0,
            low=8.0,
            close=10.0,
            volume=20.0,
            source_fingerprint=OPAQUE_FINGERPRINT,
        )


def test_kernel_bar_rejects_malformed_opaque_digest() -> None:
    with pytest.raises(SubingWatchKernelError, match="SUBING_WATCH_KERNEL_INVALID"):
        SubingWatchKernelBar(
            identity=watch_identity(),
            bar_end="2026-09-01T02:15:00+00:00",
            trading_day="2026-09-01",
            open=10.0,
            high=10.0,
            low=8.0,
            close=10.0,
            volume=20.0,
            source_fingerprint="0" * 63,
        )


@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf))
def test_adapter_rejects_non_finite_kernel_numbers(value: float) -> None:
    evaluation = kernel_evaluation()
    object.__setattr__(evaluation, "ma21", value)

    with pytest.raises(SubingWatchContractError, match="SUBING_WATCH_CONTRACT_INVALID"):
        from_kernel_evaluation(evaluation, source_mode="canonical")


def test_adapter_rejects_decimal_to_float_overflow() -> None:
    with pytest.raises(SubingWatchContractError, match="SUBING_WATCH_CONTRACT_INVALID"):
        to_subing_watch_kernel_bar(
            canonical_bar(close=Decimal("1e9999")),
            source_identity=watch_source_identity(),
        )


def test_kernel_state_is_frozen_and_accepts_one_matching_stable_fingerprint() -> None:
    identity = SubingWatchKernelIdentity(
        symbol="jm",
        contract="JM2601",
        segment_start_trading_day="2026-09-01",
    )
    state = initial_subing_watch_kernel_state(identity, load_subing_watch_policy(POLICY_PATH))
    bar = to_subing_watch_kernel_bar(
        canonical_bar(), source_identity=watch_source_identity()
    )
    evaluation = kernel_evaluation(identity=identity)
    populated = replace(
        state,
        last_bar_fingerprint=bar.source_fingerprint,
        last_evaluation=evaluation,
        blocked_reason="SOURCE_UNAVAILABLE",
    )

    assert populated.last_bar_fingerprint == bar.source_fingerprint
    with pytest.raises(FrozenInstanceError):
        populated.blocked_reason = "MUTATED"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("sma21_window", (1.0,) * 22),
        ("latest_five_valid_sma21", (1.0,) * 6),
        ("previous_twenty_volumes", (1.0,) * 21),
    ),
)
def test_kernel_state_rejects_values_beyond_each_bounded_window(
    field: str, value: tuple[float, ...]
) -> None:
    identity = SubingWatchKernelIdentity(
        symbol="jm",
        contract="JM2601",
        segment_start_trading_day="2026-09-01",
    )

    with pytest.raises(SubingWatchKernelError, match="SUBING_WATCH_KERNEL_INVALID"):
        replace(
            initial_subing_watch_kernel_state(
                identity, load_subing_watch_policy(POLICY_PATH)
            ),
            **{field: value},
        )


def test_kernel_state_rejects_mismatched_identity_fingerprint_or_blocked_reason() -> None:
    identity = SubingWatchKernelIdentity(
        symbol="jm",
        contract="JM2601",
        segment_start_trading_day="2026-09-01",
    )
    state = initial_subing_watch_kernel_state(identity, load_subing_watch_policy(POLICY_PATH))
    fingerprint = to_subing_watch_kernel_bar(
        canonical_bar(), source_identity=watch_source_identity()
    ).source_fingerprint
    different_identity = SubingWatchKernelIdentity(
        symbol="rb",
        contract="RB2601",
        segment_start_trading_day="2026-09-01",
    )

    with pytest.raises(SubingWatchKernelError, match="SUBING_WATCH_KERNEL_INVALID"):
        replace(
            state,
            last_bar_fingerprint=fingerprint,
            last_evaluation=kernel_evaluation(identity=different_identity),
        )
    with pytest.raises(SubingWatchKernelError, match="SUBING_WATCH_KERNEL_INVALID"):
        replace(
            state,
            last_bar_fingerprint="subing-watch-bar:v1|invalid",
            last_evaluation=kernel_evaluation(identity=identity),
        )
    with pytest.raises(SubingWatchKernelError, match="SUBING_WATCH_KERNEL_INVALID"):
        replace(
            state,
            last_bar_fingerprint=("not", "a", "fingerprint"),  # type: ignore[arg-type]
            last_evaluation=kernel_evaluation(identity=identity),
        )
    with pytest.raises(SubingWatchKernelError, match="SUBING_WATCH_KERNEL_INVALID"):
        replace(state, blocked_reason="")


def test_task2_first_ready_equality_then_golden_buy_and_dead_sell() -> None:
    """Catches strict previous-side comparisons or reversed close filters."""

    _, evaluations = stream_closes([100.0] * 34 + [110.0, 80.0])

    first_ready = evaluations[33]
    assert (first_ready.ma21, first_ready.dif, first_ready.dea) == (100.0, 0.0, 0.0)
    assert first_ready.outcome == "evaluated_no_signal"
    assert first_ready.observation_types == ()
    assert evaluations[34].observation_types == ("buy",)
    assert evaluations[34].outcome == "evaluated_candidate"
    assert (evaluations[34].ma21, evaluations[34].dif, evaluations[34].dea) == (
        100.47619,
        0.797721,
        0.159544,
    )
    assert evaluations[35].observation_types == ("sell",)
    assert evaluations[35].outcome == "evaluated_candidate"
    assert (evaluations[35].ma21, evaluations[35].dif, evaluations[35].dea) == (
        99.52381,
        -0.979538,
        -0.068272,
    )


def test_task2_current_dif_dea_equality_is_not_a_cross() -> None:
    """Catches treating current equality as a golden or dead cross."""

    _, evaluations = stream_closes([100.0] * 34)

    assert evaluations[-1].dif == evaluations[-1].dea == 0.0
    assert evaluations[-1].observation_types == ()
    assert evaluations[-1].outcome == "evaluated_no_signal"


def test_task2_close_equal_sma21_blocks_candidate_even_on_golden_cross() -> None:
    """Catches using >= instead of > for the BUY price filter."""

    closes = [
        100.0,
        99.0,
        96.0,
        101.0,
        101.0,
        106.0,
        107.0,
        106.0,
        109.0,
        109.0,
        108.0,
        111.0,
        111.0,
        108.0,
        105.0,
        100.0,
        97.0,
        94.0,
        91.0,
        94.0,
        91.0,
        86.0,
        86.0,
        91.0,
        92.0,
        89.0,
        88.0,
        87.0,
        82.0,
        79.0,
        79.0,
        80.0,
        79.0,
        80.0,
        88.5,
    ]
    _, evaluations = stream_closes(closes)
    previous, current = evaluations[-2:]

    assert previous.dif is not None and previous.dea is not None
    assert current.dif is not None and current.dea is not None
    assert previous.dif <= previous.dea
    assert current.dif > current.dea
    assert current.close == current.ma21 == 88.5
    assert current.observation_types == ()


def test_fix1_candidate_uses_unrounded_sma21_for_strict_price_comparison() -> None:
    """Catches rounding SMA21 before the strict BUY/SELL decision."""

    closes = [
        100.0,
        99.0,
        96.0,
        101.0,
        101.0,
        106.0,
        107.0,
        106.0,
        109.0,
        109.0,
        108.0,
        111.0,
        111.0,
        108.0,
        105.00000981,
        100.0,
        97.0,
        94.0,
        91.0,
        94.0,
        91.0,
        86.0,
        86.0,
        91.0,
        92.0,
        89.0,
        88.0,
        87.0,
        82.0,
        79.0,
        79.0,
        80.0,
        79.0,
        80.0,
        88.50000048,
    ]
    _, evaluations = stream_closes(closes)
    previous, current = evaluations[-2:]

    assert previous.dif == -7.107306
    assert previous.dea == -6.862888
    assert current.dif == -6.225074
    assert current.dea == -6.735325
    assert current.close == current.ma21 == 88.5
    assert current.observation_types == ()
    assert current.outcome == "evaluated_no_signal"


def test_fix1_adapter_binds_explicit_physical_identity_into_fingerprint() -> None:
    """Catches an adapter/fingerprint that cannot distinguish physical segments."""

    source = canonical_bar()
    jm = watch_source_identity()
    rb = watch_source_identity(contract="RB2601")
    try:
        jm_kernel = to_subing_watch_kernel_bar(source, source_identity=jm)
        rb_kernel = to_subing_watch_kernel_bar(source, source_identity=rb)
    except TypeError:
        pytest.fail("Task 2 adapter does not require explicit source identity")

    assert jm_kernel.identity == watch_identity()
    assert rb_kernel.identity == watch_identity(contract="RB2601")
    assert jm_kernel.source_fingerprint != rb_kernel.source_fingerprint


def test_fix1_wrong_contract_incoming_bar_blocks_before_formula_progression() -> None:
    """Catches comparing the state MACD/SMA against another physical contract."""

    state = required_initial_state(watch_identity())
    try:
        wrong_contract = to_subing_watch_kernel_bar(
            canonical_bar(),
            source_identity=watch_source_identity(contract="RB2601"),
        )
    except TypeError:
        pytest.fail("Task 2 kernel Bar cannot carry incoming physical identity")

    blocked, evaluation = required_step(state, wrong_contract)

    assert evaluation.outcome == "source_unavailable"
    assert evaluation.public_reason_codes == ("SUBING_WATCH_IDENTITY_MISMATCH",)
    assert blocked.blocked_reason == "SUBING_WATCH_IDENTITY_MISMATCH"
    assert blocked.sma21_window == ()
    assert blocked.macd_state == state.macd_state


def test_task2_first_segment_bar_is_bounded_warmup_without_candidate() -> None:
    """Catches accidental signal evaluation before SMA/MACD readiness."""

    state = required_initial_state()
    next_state, evaluation = required_step(state, watch_bar(1, 100.0))

    assert evaluation.outcome == "evaluated_no_signal"
    assert evaluation.observation_types == ()
    assert evaluation.close == 100.0
    assert evaluation.ma21 is None
    assert evaluation.dif is None
    assert evaluation.dea is None
    assert next_state.sma21_window == (100.0,)
    assert len(next_state.sma21_window) <= 21
    assert next_state.previous_ready_dif is None
    assert next_state.previous_ready_dea is None


@pytest.mark.parametrize(
    ("field", "value"),
    (("close", math.nan), ("high", 99.0), ("volume", -1.0)),
)
def test_task2_invalid_completed_bar_blocks_instead_of_skipping(
    field: str, value: float
) -> None:
    """Catches silently skipping malformed completed input and continuing recursion."""

    state = required_initial_state()
    invalid = watch_bar(1, 100.0)
    object.__setattr__(invalid, field, value)

    blocked, unavailable = required_step(state, invalid)
    after_block, still_unavailable = required_step(
        blocked,
        watch_bar(2, 101.0, trading_day="2026-09-02"),
    )

    assert unavailable.outcome == "source_unavailable"
    assert unavailable.public_reason_codes == ("SUBING_WATCH_SOURCE_INVALID",)
    assert blocked.blocked_reason == "SUBING_WATCH_SOURCE_INVALID"
    assert after_block == blocked
    assert still_unavailable.outcome == "source_unavailable"
    assert still_unavailable.public_reason_codes == ("SUBING_WATCH_SOURCE_INVALID",)


def test_task2_bar_before_physical_segment_blocks_source() -> None:
    """Catches cross-segment recursion before the frozen segment start."""

    identity = watch_identity(segment_start="2026-09-02")
    state = required_initial_state(identity)
    blocked, evaluation = required_step(
        state, watch_bar(1, 100.0, identity=identity)
    )

    assert evaluation.outcome == "source_unavailable"
    assert evaluation.public_reason_codes == ("SUBING_WATCH_SEGMENT_MISMATCH",)
    assert blocked.blocked_reason == "SUBING_WATCH_SEGMENT_MISMATCH"


def test_task2_same_bar_same_fingerprint_is_idempotent_even_if_float_view_drifts() -> None:
    """Catches deriving duplicate identity from lossy OHLCV floats."""

    state = required_initial_state()
    bar = watch_bar(1, 100.0)
    accepted, evaluation = required_step(state, bar)
    float_drift = replace(
        bar,
        open=101.0,
        high=101.0,
        low=101.0,
        close=101.0,
    )

    duplicate_state, duplicate_evaluation = required_step(accepted, float_drift)

    assert duplicate_state is accepted
    assert duplicate_evaluation is evaluation


def test_fix1_invalid_float_view_precedes_duplicate_even_with_same_fingerprint() -> None:
    """Catches duplicate handling bypassing finite/OHLC validation."""

    state = required_initial_state()
    bar = watch_bar(1, 100.0)
    accepted, accepted_evaluation = required_step(state, bar)
    object.__setattr__(bar, "close", math.nan)

    blocked, unavailable = required_step(accepted, bar)

    assert unavailable is not accepted_evaluation
    assert unavailable.outcome == "source_unavailable"
    assert unavailable.public_reason_codes == ("SUBING_WATCH_SOURCE_INVALID",)
    assert blocked.blocked_reason == "SUBING_WATCH_SOURCE_INVALID"
    assert blocked.sma21_window == accepted.sma21_window
    assert blocked.macd_state == accepted.macd_state


def test_task2_same_bar_different_fingerprint_raises_fixed_conflict() -> None:
    """Catches accepting conflicting Canonical source facts for one completed Bar."""

    state = required_initial_state()
    bar = watch_bar(1, 100.0)
    accepted, _ = required_step(state, bar)
    conflict = replace(bar, source_fingerprint="f" * 64)

    with pytest.raises(
        SubingWatchKernelError,
        match="SUBING_WATCH_DUPLICATE_CONFLICT",
    ):
        required_step(accepted, conflict)


def test_task2_restored_identity_mismatch_forbids_cross_contract_comparison() -> None:
    """Catches comparing prior DIF/DEA from one physical contract with another."""

    state = required_initial_state()
    accepted, _ = required_step(state, watch_bar(1, 100.0))
    object.__setattr__(accepted, "identity", watch_identity(contract="RB2601"))

    with pytest.raises(SubingWatchKernelError, match="SUBING_WATCH_KERNEL_INVALID"):
        required_step(accepted, watch_bar(2, 101.0))


def test_task2_batch_and_incremental_formula_points_match() -> None:
    """Catches a second MACD formula or off-by-one SMA window in the kernel."""

    from guiyi_quant.indicators import macd_series

    closes = [100.0 + ((index * 7) % 19) for index in range(48)]
    _, evaluations = stream_closes(closes)
    batch_macd = macd_series(
        closes,
        12,
        26,
        9,
        ema_seed_policy="sma_window",
        histogram_scale=2,
        bar_ends=[watch_bar(index, close).bar_end for index, close in enumerate(closes, 1)],
        round_digits=6,
    )

    for index, evaluation in enumerate(evaluations):
        expected_ma = (
            round(sum(closes[index - 20 : index + 1]) / 21, 6)
            if index >= 20
            else None
        )
        assert evaluation.ma21 == expected_ma
        assert evaluation.dif == batch_macd.dif.points[index].value
        assert evaluation.dea == batch_macd.dea.points[index].value
        assert evaluation.macd_histogram == batch_macd.histogram.points[index].value


def test_fix1_independent_replays_with_different_tails_freeze_common_prefix() -> None:
    """Catches future-tail mutation of kernel/application evaluations or IDs."""

    common_prefix = [100.0] * 34 + [110.0]
    _, first_kernel = stream_closes([*common_prefix, 80.0, 120.0])
    _, second_kernel = stream_closes([*common_prefix, 140.0, 60.0])
    first_application = tuple(
        from_kernel_evaluation(item, source_mode="canonical")
        for item in first_kernel[: len(common_prefix)]
    )
    second_application = tuple(
        from_kernel_evaluation(item, source_mode="canonical")
        for item in second_kernel[: len(common_prefix)]
    )

    assert tuple(first_kernel[: len(common_prefix)]) == tuple(
        second_kernel[: len(common_prefix)]
    )
    assert first_application == second_application
    assert first_application[-1].candidate_id == (
        "b9ca9144652972a43e8b87346fcf95b9cdaabd9dccc66042ed878200b5267905"
    )


def test_fix1_full_incremental_application_matches_hand_frozen_batch_points() -> None:
    """Catches application rounding, identity, or Candidate ID parity drift."""

    from guiyi_quant.indicators import macd_series

    closes = [100.0] * 34 + [110.0, 80.0]
    _, kernel = stream_closes(closes)
    batch = macd_series(
        closes,
        12,
        26,
        9,
        ema_seed_policy="sma_window",
        histogram_scale=2,
        round_digits=6,
    )
    application = [
        from_kernel_evaluation(item, source_mode="canonical") for item in kernel[-2:]
    ]
    assert [item.dif for item in application] == [
        Decimal(str(point.value)).quantize(Decimal("0.000001"))
        for point in batch.dif.points[-2:]
    ]
    assert [item.dea for item in application] == [
        Decimal(str(point.value)).quantize(Decimal("0.000001"))
        for point in batch.dea.points[-2:]
    ]
    assert [item.macd_histogram for item in application] == [
        Decimal(str(point.value)).quantize(Decimal("0.000001"))
        for point in batch.histogram.points[-2:]
    ]
    actual = [
        {
            "source_identity_digest": item.source_identity_digest,
            "bar_end": item.bar_end.isoformat(),
            "outcome": item.outcome,
            "observation_types": item.observation_types,
            "close": item.close,
            "ma21": item.ma21,
            "dif": item.dif,
            "dea": item.dea,
            "macd_histogram": item.macd_histogram,
            "candidate_id": item.candidate_id,
        }
        for item in application
    ]

    assert actual == [
        {
            "source_identity_digest": (
                "subing-watch-source:"
                "e796df38831a949b367fb11232a788979ca097bacdfc64fb29b1e0aa988c2cea"
            ),
            "bar_end": "2026-09-01T08:45:00+00:00",
            "outcome": "evaluated_candidate",
            "observation_types": ("buy",),
            "close": Decimal("110.000000"),
            "ma21": Decimal("100.476190"),
            "dif": Decimal("0.797721"),
            "dea": Decimal("0.159544"),
            "macd_histogram": Decimal("1.276353"),
            "candidate_id": (
                "b9ca9144652972a43e8b87346fcf95b9cdaabd9dccc66042ed878200b5267905"
            ),
        },
        {
            "source_identity_digest": (
                "subing-watch-source:"
                "e796df38831a949b367fb11232a788979ca097bacdfc64fb29b1e0aa988c2cea"
            ),
            "bar_end": "2026-09-01T09:00:00+00:00",
            "outcome": "evaluated_candidate",
            "observation_types": ("sell",),
            "close": Decimal("80.000000"),
            "ma21": Decimal("99.523810"),
            "dif": Decimal("-0.979538"),
            "dea": Decimal("-0.068272"),
            "macd_histogram": Decimal("-1.822531"),
            "candidate_id": (
                "7e73fcfde76cc9920e06a7e5d7cc7cc7434f732c25603b9a3830aa3a2c3e0489"
            ),
        },
    ]


def test_task2_candidate_id_uses_only_frozen_application_identity() -> None:
    """Catches candidate IDs incorporating float values or source mode."""

    candidate = replace(
        kernel_evaluation(),
        outcome="evaluated_candidate",
        observation_types=("buy",),
        close=110.0,
        ma21=100.0,
        dif=1.0,
        dea=0.5,
        macd_histogram=1.0,
    )
    changed_numbers = replace(
        candidate,
        close=999.0,
        ma21=1.0,
        dif=9.0,
        dea=-9.0,
        macd_histogram=36.0,
    )

    canonical = from_kernel_evaluation(candidate, source_mode="canonical")
    live = from_kernel_evaluation(changed_numbers, source_mode="canonical_live")

    assert canonical.candidate_id == (
        "16121129d867e27249c17fb77654d03fd5944a28dfd7d73cd34d975f616732ae"
    )
    assert live.candidate_id == canonical.candidate_id
    assert from_kernel_evaluation(
        kernel_evaluation(), source_mode="canonical"
    ).candidate_id is None


def test_task2_golden_fixture_has_fixed_payload_and_base_formula_parity() -> None:
    """Catches Task 2 formula, rounding, adapter, ID, or fixture drift."""

    fixture = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    payload = {key: value for key, value in fixture.items() if key != "payload_sha256"}
    actual_sha = sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assert fixture["payload_sha256"] == GOLDEN_PAYLOAD_SHA256
    assert actual_sha == GOLDEN_PAYLOAD_SHA256
    assert fixture["policy"] == json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    source = fixture["identity"]
    identity = SubingWatchKernelIdentity(
        symbol=source["symbol"],
        contract=source["contract"],
        segment_start_trading_day=source["segment_start_trading_day"],
        series_kind=source["series_kind"],
        frequency=source["frequency"],
    )
    state = required_initial_state(identity)
    expected_indexes = {
        point["input_index"] for point in fixture["expected_kernel_points"]
    }
    actual_kernel = []
    actual_application = []
    for input_index, item in enumerate(fixture["input_bars"]):
        canonical = CanonicalBar(
            bar_end=datetime.fromisoformat(item["bar_end"]),
            trading_day=date.fromisoformat(item["trading_day"]),
            open=Decimal(item["open"]),
            high=Decimal(item["high"]),
            low=Decimal(item["low"]),
            close=Decimal(item["close"]),
            volume=Decimal(item["volume"]),
            turnover=None,
            open_interest=None,
        )
        kernel_bar = to_subing_watch_kernel_bar(
            canonical,
            source_identity=watch_source_identity(),
        )
        assert kernel_bar.source_fingerprint == item["source_fingerprint"]
        state, evaluation = required_step(state, kernel_bar)
        if input_index not in expected_indexes:
            continue
        actual_kernel.append(
            {
                "input_index": input_index,
                "formula_version": evaluation.formula_version,
                "trading_day": evaluation.trading_day,
                "bar_end": evaluation.bar_end,
                "outcome": evaluation.outcome,
                "observation_types": list(evaluation.observation_types),
                "close": evaluation.close,
                "ma21": evaluation.ma21,
                "dif": evaluation.dif,
                "dea": evaluation.dea,
                "macd_histogram": evaluation.macd_histogram,
                "public_reason_codes": list(evaluation.public_reason_codes),
            }
        )
        app = from_kernel_evaluation(evaluation, source_mode="canonical")
        actual_application.append(
            {
                "input_index": input_index,
                "formula_version": app.formula_version,
                "source_identity_digest": app.source_identity_digest,
                "trading_day": app.trading_day.isoformat(),
                "bar_end": app.bar_end.isoformat(),
                "source_mode": app.source_mode,
                "outcome": app.outcome,
                "observation_types": list(app.observation_types),
                "close": str(app.close) if app.close is not None else None,
                "ma21": str(app.ma21) if app.ma21 is not None else None,
                "dif": str(app.dif) if app.dif is not None else None,
                "dea": str(app.dea) if app.dea is not None else None,
                "macd_histogram": (
                    str(app.macd_histogram)
                    if app.macd_histogram is not None
                    else None
                ),
                "candidate_id": app.candidate_id,
                "public_reason_codes": list(app.public_reason_codes),
            }
        )

    expected_kernel = [
        {key: value for key, value in point.items() if key != "context"}
        for point in fixture["expected_kernel_points"]
    ]
    expected_application = [
        {key: value for key, value in point.items() if key != "context"}
        for point in fixture["expected_application_evaluations"]
    ]
    assert actual_kernel == expected_kernel
    assert actual_application == expected_application


def test_task3_sma21_regression_slope_uses_latest_five_points_and_current_denominator() -> None:
    """Catches endpoint slope or mean-SMA normalization replacing OLS/current SMA21."""

    state, bar, higher = candidate_fixture("all_ready")

    next_state, evaluation = subing_watch_kernel.step_subing_watch_15m(
        state,
        bar,
        higher_timeframe=higher,
    )

    assert evaluation.context.ma21_slope_5_bps_per_bar == 9.478673
    assert next_state.latest_five_valid_sma21 == (
        100.0,
        100.0,
        100.0,
        100.0,
        100.47619047619048,
    )


def test_task3_sma21_slope_zero_current_denominator_is_unavailable() -> None:
    """Catches division by zero or an invented substitute slope denominator."""

    state = replace(
        required_initial_state(),
        sma21_window=(0.0,) * 20,
        latest_five_valid_sma21=(-4.0, -3.0, -2.0, -1.0),
    )

    next_state, evaluation = required_step(state, watch_bar(1, 0.0))

    assert evaluation.context.ma21_slope_5_bps_per_bar is None
    assert next_state.latest_five_valid_sma21 == (-4.0, -3.0, -2.0, -1.0, 0.0)


def test_task3_atr14_normalizes_price_and_macd_distances() -> None:
    """Catches wrong ATR timing, absolute-price distance, or histogram normalization."""

    state, bar, higher = candidate_fixture("all_ready")

    _, evaluation = subing_watch_kernel.step_subing_watch_15m(
        state,
        bar,
        higher_timeframe=higher,
    )

    assert evaluation.context.distance_to_ma21_atr14 == 3.603604
    assert evaluation.context.macd_zero_distance_atr14 == 0.30184


def test_task3_zero_atr_denominator_makes_both_distances_unavailable() -> None:
    """Catches zero ATR being emitted as infinity or a fabricated zero distance."""

    state = candidate_prefix_state()
    zero_atr = replace(
        state.atr_state,
        count=14,
        seed_values=(0.0,) * 14,
        previous_close=100.0,
        previous_atr=0.0,
    )
    state = replace(state, atr_state=zero_atr)

    next_state, evaluation = required_step(state, watch_bar(35, 100.0))

    assert evaluation.context.distance_to_ma21_atr14 is None
    assert evaluation.context.macd_zero_distance_atr14 is None
    assert next_state.atr_state.count == 15


def test_task3_volume_ratio_uses_previous_twenty_and_excludes_current() -> None:
    """Catches adding the current Bar to its own denominator."""

    state = replace(candidate_prefix_state(), previous_twenty_volumes=(10.0,) * 20)

    next_state, evaluation = required_step(
        state,
        watch_bar(35, 110.0, high_low_width=1.0, volume=1000.0),
    )

    assert evaluation.context.volume_ratio_20 == 100.0
    assert next_state.previous_twenty_volumes == (10.0,) * 19 + (1000.0,)


def test_task3_zero_previous_volume_denominator_is_unavailable() -> None:
    """Catches zero prior mean being emitted as infinity or normalized with current volume."""

    state = replace(candidate_prefix_state(), previous_twenty_volumes=(0.0,) * 20)

    next_state, evaluation = required_step(
        state,
        watch_bar(35, 110.0, high_low_width=1.0),
    )

    assert evaluation.context.volume_ratio_20 is None
    assert next_state.previous_twenty_volumes == (0.0,) * 19 + (135.0,)


@pytest.mark.parametrize(
    ("source_range", "expected"),
    (
        ("range_unavailable", "range_unavailable"),
        ("no_active_range", "no_active_range"),
        ("intact", "intact"),
        ("broken_up", "broken_up"),
        ("broken_down", "broken_down"),
    ),
)
def test_task3_maps_existing_causal_range_state(
    source_range: str,
    expected: str,
) -> None:
    """Catches recomputing or collapsing the existing Range Detector state."""

    state = candidate_prefix_state()
    if source_range != "range_unavailable":
        state = replace(state, range_state=ready_range_state(source_range))

    next_state, evaluation = required_step(
        state,
        watch_bar(35, 110.0, high_low_width=1.0),
    )

    assert evaluation.context.range_state == expected
    assert next_state.range_state.index == state.range_state.index + 1


@pytest.mark.parametrize(
    ("alignment", "expected"),
    (("aligned", "aligned"), ("opposed", "opposed"), ("neutral", "neutral")),
)
def test_task3_higher_timeframe_alignment_uses_candidate_direction(
    alignment: str,
    expected: str,
) -> None:
    """Catches one-sided or direction-free 60m alignment labels."""

    state = candidate_prefix_state()

    _, evaluation = subing_watch_kernel.step_subing_watch_15m(
        state,
        watch_bar(35, 110.0, high_low_width=1.0),
        higher_timeframe=watch_higher_timeframe(alignment=alignment),
    )

    assert evaluation.observation_types == ("buy",)
    assert evaluation.context.higher_timeframe_alignment == expected


def test_task3_higher_timeframe_equal_cutoff_is_completed_and_allowed() -> None:
    """Catches using strict-before when the accepted cutoff contract is before-or-equal."""

    state = candidate_prefix_state()

    _, evaluation = subing_watch_kernel.step_subing_watch_15m(
        state,
        watch_bar(35, 110.0, high_low_width=1.0),
        higher_timeframe=watch_higher_timeframe(
            bar_end="2026-09-01T08:45:00+00:00"
        ),
    )

    assert evaluation.context.higher_timeframe_alignment == "aligned"


def test_task3_higher_timeframe_after_cutoff_raises_fixed_future_error() -> None:
    """Catches future 60m facts leaking into a completed 15m Candidate."""

    state = candidate_prefix_state()

    with pytest.raises(
        SubingWatchKernelError,
        match="SUBING_WATCH_HIGHER_TIMEFRAME_FUTURE",
    ):
        subing_watch_kernel.step_subing_watch_15m(
            state,
            watch_bar(35, 110.0, high_low_width=1.0),
            higher_timeframe=watch_higher_timeframe(
                bar_end="2026-09-01T09:00:00+00:00"
            ),
        )


@pytest.mark.parametrize("case", ("missing_identity", "mismatched_identity", "not_ready", "invalid"))
def test_task3_missing_invalid_or_wrong_60m_identity_is_non_gating_unavailable(
    case: str,
) -> None:
    """Catches accepting an unproven 60m physical source or suppressing the base Candidate."""

    if case == "missing_identity":
        higher = SubingWatchKernelHigherTimeframe(
            bar_end="2026-09-01T08:00:00+00:00",
            close=110.0,
            ma21=100.0,
            ma21_slope_5_bps_per_bar=5.0,
            ready=True,
            valid=True,
        )
    else:
        higher = watch_higher_timeframe(
            identity=(
                watch_identity(contract="RB2601")
                if case == "mismatched_identity"
                else watch_identity()
            ),
            ready=case != "not_ready",
            valid=case != "invalid",
        )
    state = candidate_prefix_state()

    _, evaluation = subing_watch_kernel.step_subing_watch_15m(
        state,
        watch_bar(35, 110.0, high_low_width=1.0),
        higher_timeframe=higher,
    )

    assert evaluation.outcome == "evaluated_candidate"
    assert evaluation.observation_types == ("buy",)
    assert evaluation.context.ma21_slope_5_bps_per_bar == 9.478673
    assert evaluation.context.higher_timeframe_alignment == "unavailable"


@pytest.mark.parametrize(
    "case",
    (
        "all_ready",
        "atr_unavailable",
        "volume_denominator_zero",
        "range_unavailable",
        "higher_timeframe_missing",
        "higher_timeframe_opposed",
    ),
)
def test_context_never_suppresses_base_candidate(case: str) -> None:
    """Catches any explanation-only fact entering the Task 2 Candidate truth table."""

    state, bar, higher = candidate_fixture(case)

    _, evaluation = subing_watch_kernel.step_subing_watch_15m(
        state,
        bar,
        higher_timeframe=higher,
    )

    assert evaluation.outcome == "evaluated_candidate"
    assert evaluation.observation_types == ("buy",)
    assert evaluation.context.ma21_slope_5_bps_per_bar == 9.478673
    assert evaluation.context.volume_ratio_20 == (
        None if case == "volume_denominator_zero" else 1.084337
    )
    assert evaluation.context.distance_to_ma21_atr14 == (
        None if case == "atr_unavailable" else 3.603604
    )
    assert evaluation.context.macd_zero_distance_atr14 == (
        None if case == "atr_unavailable" else 0.30184
    )
    assert evaluation.context.range_state == (
        "range_unavailable" if case == "range_unavailable" else "intact"
    )
    assert evaluation.context.higher_timeframe_alignment == {
        "higher_timeframe_missing": "unavailable",
        "higher_timeframe_opposed": "opposed",
    }.get(case, "aligned")


def test_task3_context_exception_preserves_candidate_and_other_ready_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches an ATR context failure aborting or suppressing the frozen observation."""

    state, bar, higher = candidate_fixture("all_ready")

    def raise_context_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic context failure")

    monkeypatch.setattr(subing_watch_kernel, "step_atr", raise_context_error, raising=False)

    next_state, evaluation = subing_watch_kernel.step_subing_watch_15m(
        state,
        bar,
        higher_timeframe=higher,
    )

    assert evaluation.outcome == "evaluated_candidate"
    assert evaluation.observation_types == ("buy",)
    assert evaluation.context.ma21_slope_5_bps_per_bar == 9.478673
    assert evaluation.context.distance_to_ma21_atr14 is None
    assert evaluation.context.macd_zero_distance_atr14 is None
    assert evaluation.context.volume_ratio_20 == 1.084337
    assert evaluation.context.range_state == "intact"
    assert evaluation.context.higher_timeframe_alignment == "aligned"
    assert next_state.atr_state is state.atr_state


def test_task3_context_state_remains_frozen_and_bounded_after_progression() -> None:
    """Catches retaining unbounded SMA or volume history in the Watch state."""

    state, bar, higher = candidate_fixture("all_ready")

    next_state, _ = subing_watch_kernel.step_subing_watch_15m(
        state,
        bar,
        higher_timeframe=higher,
    )

    assert len(next_state.sma21_window) == 21
    assert len(next_state.latest_five_valid_sma21) == 5
    assert len(next_state.previous_twenty_volumes) == 20
    with pytest.raises(FrozenInstanceError):
        next_state.previous_twenty_volumes = ()  # type: ignore[misc]


@pytest.mark.parametrize(
    "case",
    ("ready", "not_ready_and_invalid", "identity_mismatch"),
)
def test_task3_fix1_duplicate_still_rejects_future_higher_timeframe(case: str) -> None:
    """Catches the duplicate fast-path bypassing the future-context guard."""

    state, bar, higher = candidate_fixture("all_ready")
    accepted_state, _ = subing_watch_kernel.step_subing_watch_15m(
        state,
        bar,
        higher_timeframe=higher,
    )
    duplicate_higher = watch_higher_timeframe(
        bar_end="2026-09-01T09:00:00+00:00",
        identity=(
            watch_identity(contract="RB2601")
            if case == "identity_mismatch"
            else watch_identity()
        ),
        ready=case != "not_ready_and_invalid",
        valid=case != "not_ready_and_invalid",
    )

    with pytest.raises(
        SubingWatchKernelError,
        match="SUBING_WATCH_HIGHER_TIMEFRAME_FUTURE",
    ):
        subing_watch_kernel.step_subing_watch_15m(
            accepted_state,
            bar,
            higher_timeframe=duplicate_higher,
        )


@pytest.mark.parametrize(
    "higher_bar_end",
    ("2026-09-01T08:45:00+00:00", "2026-09-01T08:00:00+00:00"),
)
def test_task3_fix1_duplicate_equal_or_past_higher_timeframe_is_exact_noop(
    higher_bar_end: str,
) -> None:
    """Catches the future guard recomputing context or mutating an allowed duplicate."""

    state, bar, higher = candidate_fixture("all_ready")
    accepted_state, accepted_evaluation = subing_watch_kernel.step_subing_watch_15m(
        state,
        bar,
        higher_timeframe=higher,
    )

    duplicate_state, duplicate_evaluation = subing_watch_kernel.step_subing_watch_15m(
        accepted_state,
        bar,
        higher_timeframe=watch_higher_timeframe(bar_end=higher_bar_end),
    )

    assert duplicate_state is accepted_state
    assert duplicate_evaluation is accepted_evaluation
