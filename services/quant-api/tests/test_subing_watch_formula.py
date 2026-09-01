from __future__ import annotations

import json
import math
import re
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

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
    state = initial_subing_watch_kernel_state(identity)
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
        replace(initial_subing_watch_kernel_state(identity), **{field: value})


def test_kernel_state_rejects_mismatched_identity_fingerprint_or_blocked_reason() -> None:
    identity = SubingWatchKernelIdentity(
        symbol="jm",
        contract="JM2601",
        segment_start_trading_day="2026-09-01",
    )
    state = initial_subing_watch_kernel_state(identity)
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
