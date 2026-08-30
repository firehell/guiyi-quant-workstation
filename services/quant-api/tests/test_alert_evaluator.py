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


def _window(length: int = 32, *, frequency: str = "15m") -> MarketReadWindow:
    bars = tuple(_bar(index) for index in range(length))
    return MarketReadWindow(
        symbol="j",
        series_kind="actual_dominant",
        frequency=frequency,
        trading_day=date(2025, 1, 2),
        contract="J2505",
        cutoff=bars[-1].bar_end,
        bars=bars,
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
