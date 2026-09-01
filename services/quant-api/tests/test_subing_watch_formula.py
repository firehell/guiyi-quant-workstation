from __future__ import annotations

import json
import math
import re
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
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
    "8ea52a0f86beeea27172971bb5448d8c9ba1e11ad98881fe547c214d3af68267"
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


def watch_bar(
    index: int,
    close: float,
    *,
    fingerprint: str | None = None,
    trading_day: str = "2026-09-01",
) -> SubingWatchKernelBar:
    bar_end = datetime(2026, 9, 1, tzinfo=UTC).replace(
        hour=(index * 15) // 60,
        minute=(index * 15) % 60,
    )
    return SubingWatchKernelBar(
        bar_end=bar_end.isoformat(),
        trading_day=trading_day,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=100.0 + index,
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
    kernel = to_subing_watch_kernel_bar(canonical_bar())
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
        canonical_bar(close=Decimal("9007199254740992"))
    )
    second = to_subing_watch_kernel_bar(
        canonical_bar(close=Decimal("9007199254740993"))
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
        to_subing_watch_kernel_bar(canonical_bar(close=Decimal("1e9999")))


def test_kernel_state_is_frozen_and_accepts_one_matching_stable_fingerprint() -> None:
    identity = SubingWatchKernelIdentity(
        symbol="jm",
        contract="JM2601",
        segment_start_trading_day="2026-09-01",
    )
    state = initial_subing_watch_kernel_state(identity, load_subing_watch_policy(POLICY_PATH))
    bar = to_subing_watch_kernel_bar(canonical_bar())
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
    fingerprint = to_subing_watch_kernel_bar(canonical_bar()).source_fingerprint
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

    state = required_initial_state(watch_identity(segment_start="2026-09-02"))
    blocked, evaluation = required_step(state, watch_bar(1, 100.0))

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


def test_task2_every_prefix_and_future_tail_are_stable() -> None:
    """Catches future-tail mutation, repainting, or hidden unbounded batch dependence."""

    closes = [100.0 + ((index * 11) % 23) for index in range(40)]
    _, full_evaluations = stream_closes(closes)
    frozen_prefix = tuple(full_evaluations[:35])

    for end in range(1, len(closes) + 1):
        _, prefix = stream_closes(closes[:end])
        assert prefix[-1] == full_evaluations[end - 1]
    assert tuple(full_evaluations[:35]) == frozen_prefix


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


def test_task2_golden_fixture_has_fixed_payload_and_complete_parity() -> None:
    """Catches formula, rounding, adapter, ID, or fixture drift together."""

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
        kernel_bar = to_subing_watch_kernel_bar(canonical)
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
                "context": {
                    "ma21_slope_5_bps_per_bar": evaluation.context.ma21_slope_5_bps_per_bar,
                    "distance_to_ma21_atr14": evaluation.context.distance_to_ma21_atr14,
                    "macd_zero_distance_atr14": evaluation.context.macd_zero_distance_atr14,
                    "volume_ratio_20": evaluation.context.volume_ratio_20,
                    "range_state": evaluation.context.range_state,
                    "higher_timeframe_alignment": evaluation.context.higher_timeframe_alignment,
                },
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
                "context": {
                    "ma21_slope_5_bps_per_bar": (
                        str(app.context.ma21_slope_5_bps_per_bar)
                        if app.context.ma21_slope_5_bps_per_bar is not None
                        else None
                    ),
                    "distance_to_ma21_atr14": (
                        str(app.context.distance_to_ma21_atr14)
                        if app.context.distance_to_ma21_atr14 is not None
                        else None
                    ),
                    "macd_zero_distance_atr14": (
                        str(app.context.macd_zero_distance_atr14)
                        if app.context.macd_zero_distance_atr14 is not None
                        else None
                    ),
                    "volume_ratio_20": (
                        str(app.context.volume_ratio_20)
                        if app.context.volume_ratio_20 is not None
                        else None
                    ),
                    "range_state": app.context.range_state,
                    "higher_timeframe_alignment": app.context.higher_timeframe_alignment,
                },
                "candidate_id": app.candidate_id,
                "public_reason_codes": list(app.public_reason_codes),
            }
        )

    assert actual_kernel == fixture["expected_kernel_points"]
    assert actual_application == fixture["expected_application_evaluations"]
