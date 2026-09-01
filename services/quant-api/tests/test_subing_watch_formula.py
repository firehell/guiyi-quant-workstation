from __future__ import annotations

import json
import math
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
    SubingWatchKernelEvaluation,
    SubingWatchKernelIdentity,
)


POLICY_PATH = (
    Path(__file__).resolve().parents[3]
    / "data/research_policies/subing_watch_15m_v1.json"
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


def kernel_evaluation(*, ma21: float = 123.456789) -> SubingWatchKernelEvaluation:
    identity = SubingWatchKernelIdentity(
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
        identity=identity,
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


def test_decimal_float_boundary_is_single_and_deterministic() -> None:
    kernel = to_subing_watch_kernel_bar(canonical_bar())
    app = from_kernel_evaluation(kernel_evaluation(), source_mode="canonical")

    assert kernel.close == 123.4567894
    assert app.ma21 == Decimal("123.456789")
    assert app.close == Decimal("123.456789")
    assert app.source_identity == SubingWatchSourceIdentity(
        symbol="jm",
        contract="JM2601",
        segment_start_trading_day=date(2026, 9, 1),
    )
    assert app.source_identity_digest.startswith("subing-watch-source:")


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


def test_kernel_bar_rejects_non_aware_time_and_invalid_ohlc() -> None:
    with pytest.raises(ValueError, match="SUBING_WATCH_KERNEL_INVALID"):
        SubingWatchKernelBar(
            bar_end="2026-09-01T02:15:00",
            trading_day="2026-09-01",
            open=10.0,
            high=9.0,
            low=8.0,
            close=10.0,
            volume=20.0,
        )


@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf))
def test_adapter_rejects_non_finite_kernel_numbers(value: float) -> None:
    with pytest.raises(ValueError, match="SUBING_WATCH_KERNEL_INVALID"):
        kernel_evaluation(ma21=value)
