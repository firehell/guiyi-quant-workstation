from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.alerts import evaluators as evaluator_module
from app.alerts.evaluators import AlertEvaluationError
from app.market_data.domain import CanonicalBar
from app.market_data.market_read_service import MarketReadWindow
from guiyi_quant.indicators import compute_htdy_original
from guiyi_quant.indicators.htdy_original import CONFIGURED_REPAINT_SCAN_ZONE_BARS


def _bar(index: int) -> CanonicalBar:
    close = Decimal("100") + Decimal(index) / 10
    return CanonicalBar(
        bar_end=datetime(2025, 1, 2, 0, 15, tzinfo=UTC) + timedelta(minutes=15 * index),
        trading_day=date(2025, 1, 2),
        open=close - Decimal("0.2"),
        high=close + 1,
        low=close - 1,
        close=close,
        volume=Decimal(1000 + index),
        turnover=None,
        open_interest=None,
    )


def _window(
    length: int = 32,
    *,
    frequency: str = "15m",
    contracts: tuple[str, ...] | None = None,
) -> MarketReadWindow:
    bars = tuple(_bar(index) for index in range(length))
    bar_contracts = contracts or ("J2505",) * length
    return MarketReadWindow(
        symbol="j",
        series_kind="actual_dominant",
        frequency=frequency,
        trading_day=date(2025, 1, 2),
        contract="J2505",
        cutoff=bars[-1].bar_end,
        bars=bars,
        bar_contracts=bar_contracts,
    )


def _observation_result(
    length: int,
    *,
    buys: tuple[int, ...] = (),
    sells: tuple[int, ...] = (),
) -> SimpleNamespace:
    buy_observation = np.zeros(length, dtype=bool)
    sell_observation = np.zeros(length, dtype=bool)
    buy_observation[list(buys)] = True
    sell_observation[list(sells)] = True
    return SimpleNamespace(
        buy_observation=buy_observation,
        sell_observation=sell_observation,
    )


@pytest.mark.parametrize("frequency", ("1m", "5m", "15m", "30m", "60m", "1d", "1w"))
@pytest.mark.parametrize(
    ("buy", "sell", "expected"),
    (
        (True, False, ("buy",)),
        (False, True, ("sell",)),
        (True, True, ("buy", "sell")),
        (False, False, ()),
    ),
)
def test_evaluator_reads_only_current_bar_observations(
    monkeypatch: pytest.MonkeyPatch,
    frequency: str,
    buy: bool,
    sell: bool,
    expected: tuple[str, ...],
) -> None:
    flags_buy = np.zeros(32, dtype=bool)
    flags_sell = np.zeros(32, dtype=bool)
    flags_buy[10] = True  # an old repaint must never be scanned as a new Alert
    flags_buy[-1] = buy
    flags_sell[-1] = sell
    monkeypatch.setattr(
        "app.alerts.evaluators.compute_htdy_original",
        lambda *_args: SimpleNamespace(
            buy_observation=flags_buy,
            sell_observation=flags_sell,
        ),
    )

    assert (
        evaluator_module.HtdyOriginalEvaluator()
        .evaluate(_window(frequency=frequency))
        .observation_types
        == expected
    )


@pytest.mark.parametrize(
    "window",
    (
        replace(_window(), frequency="4h"),
        replace(_window(), series_kind="continuous"),
        _window(31),
        replace(_window(), cutoff=_window().cutoff + timedelta(minutes=15)),
    ),
)
def test_evaluator_fails_closed_for_wrong_identity_or_short_context(
    window: MarketReadWindow,
) -> None:
    with pytest.raises(AlertEvaluationError, match="ALERT_EVALUATION_INPUT_INVALID"):
        evaluator_module.HtdyOriginalEvaluator().evaluate(window)


def test_evaluator_requires_the_scoped_htdy_alert_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches Registry alert capability bypassing the scoped FormalPolicy."""
    monkeypatch.setattr(
        "app.alerts.evaluators.require_formal_policy",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("FORMAL_POLICY_CONSUMER_BLOCKED")
        ),
        raising=False,
    )

    with pytest.raises(AlertEvaluationError, match="ALERT_EVALUATION_POLICY_DISABLED"):
        evaluator_module.HtdyOriginalEvaluator().evaluate(_window())


def test_composition_uses_generalized_evaluator_and_keeps_activation_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Catches composition retaining the 15m evaluator or bypassing its marker."""
    from app.alerts import composition

    marker = tmp_path / "alert-runtime-enabled"
    monkeypatch.setattr(composition, "ALERT_RUNTIME_ACTIVATION_MARKER", marker)
    with pytest.raises(RuntimeError, match="ALERT_RUNTIME_NOT_ENABLED"):
        composition.build_alert_runtime()

    marker.write_text("enabled\n", encoding="utf-8")
    monkeypatch.setattr(composition, "build_notification_sender_from_env", object)
    monkeypatch.setattr(composition, "load_operational_products", lambda: ("j",))
    monkeypatch.setattr(composition, "load_product_taxonomy", dict)
    monkeypatch.setattr(
        composition,
        "get_redis_connection",
        lambda: SimpleNamespace(pubsub=lambda **_kwargs: object()),
    )

    runtime = composition.build_alert_runtime()

    assert isinstance(runtime._htdy_evaluator, evaluator_module.HtdyOriginalEvaluator)


def test_32_bar_contract_matches_full_history_current_observation() -> None:
    fixture = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "tests/fixtures/htdy_original_realtime_v1_golden.json"
        ).read_text(
            encoding="utf-8"
        )
    )
    golden = fixture["bars"]
    datetimes = [bar["datetime"] for bar in golden]
    open_ = [bar["open"] for bar in golden]
    high = [math.nan if bar["high"] is None else bar["high"] for bar in golden]
    low = [math.nan if bar["low"] is None else bar["low"] for bar in golden]
    close = [bar["close"] for bar in golden]
    volume = [bar["volume"] for bar in golden]

    # Continue the tracked production golden through a stable no-observation region,
    # then create a fresh three-candle edge so current buy/sell truth is exercised.
    for index in range(40):
        datetimes.append(f"golden-extension-{index}")
        open_.append(99.8)
        high.append(100.0)
        low.append(100.0)
        close.append(99.9)
        volume.append(2000.0 + index)
    for index in range(3):
        datetimes.append(f"golden-conflict-{index}")
        open_.append(99.9)
        high.append(100.0)
        low.append(100.0)
        close.append(100.1)
        volume.append(2100.0 + index)

    observed: set[tuple[bool, bool]] = set()
    length = len(datetimes)

    for cutoff in range(32, length + 1):
        full = compute_htdy_original(
            datetimes[:cutoff],
            open_[:cutoff],
            high[:cutoff],
            low[:cutoff],
            close[:cutoff],
            volume[:cutoff],
        )
        bounded = compute_htdy_original(
            datetimes[cutoff - 32 : cutoff],
            open_[cutoff - 32 : cutoff],
            high[cutoff - 32 : cutoff],
            low[cutoff - 32 : cutoff],
            close[cutoff - 32 : cutoff],
            volume[cutoff - 32 : cutoff],
        )

        assert bool(bounded.buy_observation[-1]) is bool(full.buy_observation[-1])
        assert bool(bounded.sell_observation[-1]) is bool(full.sell_observation[-1])
        observed.add((bool(full.buy_observation[-1]), bool(full.sell_observation[-1])))

    assert (False, False) in observed
    assert any(buy for buy, _sell in observed)
    assert any(sell for _buy, sell in observed)


def test_first_seen_returns_latest_bar_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = _window(32)
    monkeypatch.setattr(
        evaluator_module,
        "compute_htdy_original",
        lambda *_args: _observation_result(32, sells=(31,)),
    )

    assert evaluator_module.HtdyOriginalEvaluator().evaluate_first_seen(window) == (
        evaluator_module.HtdyFirstSeenObservation(
            bar_end=window.bars[-1].bar_end,
            trading_day=window.bars[-1].trading_day,
            contract=window.bar_contracts[-1],
            observation_types=("sell",),
        ),
    )


def test_first_seen_uses_old_observation_bar_identity_after_repaint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_index = 50
    previous_day = date(2025, 1, 1)
    contracts = tuple("J2501" if index == old_index else "J2505" for index in range(64))
    original = _window(64, contracts=contracts)
    bars = list(original.bars)
    bars[old_index] = replace(bars[old_index], trading_day=previous_day)
    window = replace(original, bars=tuple(bars))

    def compute(datetimes, *_args):
        length = len(datetimes)
        return (
            _observation_result(length)
            if length == 63
            else _observation_result(length, sells=(old_index,))
        )

    monkeypatch.setattr(evaluator_module, "compute_htdy_original", compute)

    assert evaluator_module.HtdyOriginalEvaluator().evaluate_first_seen(window) == (
        evaluator_module.HtdyFirstSeenObservation(
            bar_end=window.bars[old_index].bar_end,
            trading_day=previous_day,
            contract="J2501",
            observation_types=("sell",),
        ),
    )


@pytest.mark.parametrize(
    ("previous_types", "current_types", "expected"),
    (
        (("sell",), (), ()),
        (("buy",), ("sell",), ()),
        (("sell",), ("buy",), ()),
        (("buy",), ("buy", "sell"), ()),
        ((), ("buy", "sell"), ("buy", "sell")),
    ),
)
def test_first_seen_emits_only_empty_to_observation_transition(
    monkeypatch: pytest.MonkeyPatch,
    previous_types: tuple[str, ...],
    current_types: tuple[str, ...],
    expected: tuple[str, ...],
) -> None:
    candidate_index = 50
    window = _window(64)

    def result(length: int, observation_types: tuple[str, ...]) -> SimpleNamespace:
        return _observation_result(
            length,
            buys=(candidate_index,) if "buy" in observation_types else (),
            sells=(candidate_index,) if "sell" in observation_types else (),
        )

    monkeypatch.setattr(
        evaluator_module,
        "compute_htdy_original",
        lambda datetimes, *_args: result(
            len(datetimes),
            previous_types if len(datetimes) == 63 else current_types,
        ),
    )

    candidates = evaluator_module.HtdyOriginalEvaluator().evaluate_first_seen(window)

    if expected:
        assert len(candidates) == 1
        assert candidates[0].bar_end == window.bars[candidate_index].bar_end
        assert candidates[0].observation_types == expected
    else:
        assert candidates == ()


def test_first_seen_scans_exact_last_27_previous_bars_and_sorts_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = _window(64)
    first_scanned = 63 - CONFIGURED_REPAINT_SCAN_ZONE_BARS

    def compute(datetimes, *_args):
        length = len(datetimes)
        if length == 63:
            return _observation_result(length)
        return _observation_result(
            length,
            buys=(first_scanned - 1, 62, 63),
            sells=(first_scanned, 63),
        )

    monkeypatch.setattr(evaluator_module, "compute_htdy_original", compute)

    candidates = evaluator_module.HtdyOriginalEvaluator().evaluate_first_seen(window)

    assert tuple(candidate.bar_end for candidate in candidates) == (
        window.bars[first_scanned].bar_end,
        window.bars[62].bar_end,
        window.bars[63].bar_end,
    )
    assert tuple(candidate.observation_types for candidate in candidates) == (
        ("sell",),
        ("buy",),
        ("buy", "sell"),
    )


@pytest.mark.parametrize("length", (32, 40, 63))
def test_first_seen_keeps_current_bar_only_before_64_bar_context(
    monkeypatch: pytest.MonkeyPatch,
    length: int,
) -> None:
    window = _window(length)

    def compute(datetimes, *_args):
        computed_length = len(datetimes)
        return _observation_result(computed_length, buys=(5,), sells=(computed_length - 1,))

    monkeypatch.setattr(evaluator_module, "compute_htdy_original", compute)

    candidates = evaluator_module.HtdyOriginalEvaluator().evaluate_first_seen(window)

    assert tuple(candidate.bar_end for candidate in candidates) == (window.bars[-1].bar_end,)
    assert candidates[0].observation_types == ("sell",)


def test_first_seen_rejects_misaligned_bar_contract_ownership() -> None:
    window = replace(_window(64), bar_contracts=("J2505",) * 63)

    with pytest.raises(AlertEvaluationError, match="ALERT_EVALUATION_INPUT_INVALID"):
        evaluator_module.HtdyOriginalEvaluator().evaluate_first_seen(window)


def test_64_bar_first_seen_matches_full_history_prefix_diff() -> None:
    bars: list[CanonicalBar] = []
    start = datetime(2025, 1, 2, 0, 15, tzinfo=UTC)
    for index in range(150):
        center = 100.0 + 7.0 * math.sin(index / 4.0) + 2.5 * math.sin(index / 13.0)
        body = 1.2 * math.sin(index / 2.0)
        open_value = Decimal(str(round(center - body / 2.0, 8)))
        close_value = Decimal(str(round(center + body / 2.0, 8)))
        high = max(open_value, close_value) + Decimal("1.5")
        low = min(open_value, close_value) - Decimal("1.5")
        if index % 31 in {8, 9, 10}:
            close_value += Decimal("9")
            high = close_value + Decimal("1")
        if index % 37 in {20, 21, 22}:
            close_value -= Decimal("9")
            low = close_value - Decimal("1")
        bars.append(
            CanonicalBar(
                bar_end=start + timedelta(minutes=15 * index),
                trading_day=date(2025, 1, 2),
                open=open_value,
                high=high,
                low=low,
                close=close_value,
                volume=Decimal(1000 + index),
                turnover=None,
                open_interest=None,
            )
        )

    def compute(source: list[CanonicalBar]):
        return compute_htdy_original(
            [bar.bar_end for bar in source],
            [float(bar.open) for bar in source],
            [float(bar.high) for bar in source],
            [float(bar.low) for bar in source],
            [float(bar.close) for bar in source],
            [float(bar.volume) for bar in source],
        )

    observed_candidate_count = 0
    for cutoff in range(64, len(bars) + 1):
        previous = compute(bars[: cutoff - 1])
        current = compute(bars[:cutoff])
        expected: list[tuple[datetime, tuple[str, ...]]] = []
        for index in range(
            max(0, cutoff - 1 - CONFIGURED_REPAINT_SCAN_ZONE_BARS),
            cutoff - 1,
        ):
            previous_types = (
                *(("buy",) if bool(previous.buy_observation[index]) else ()),
                *(("sell",) if bool(previous.sell_observation[index]) else ()),
            )
            current_types = (
                *(("buy",) if bool(current.buy_observation[index]) else ()),
                *(("sell",) if bool(current.sell_observation[index]) else ()),
            )
            if not previous_types and current_types:
                expected.append((bars[index].bar_end, current_types))
        latest_types = (
            *(("buy",) if bool(current.buy_observation[cutoff - 1]) else ()),
            *(("sell",) if bool(current.sell_observation[cutoff - 1]) else ()),
        )
        if latest_types:
            expected.append((bars[cutoff - 1].bar_end, latest_types))

        bounded_bars = tuple(bars[cutoff - 64 : cutoff])
        window = MarketReadWindow(
            symbol="j",
            series_kind="actual_dominant",
            frequency="15m",
            trading_day=bounded_bars[-1].trading_day,
            contract="J2505",
            cutoff=bounded_bars[-1].bar_end,
            bars=bounded_bars,
            bar_contracts=("J2505",) * 64,
        )
        actual = evaluator_module.HtdyOriginalEvaluator().evaluate_first_seen(window)

        assert tuple((candidate.bar_end, candidate.observation_types) for candidate in actual) == tuple(
            expected
        )
        observed_candidate_count += len(expected)

    assert observed_candidate_count > 0
