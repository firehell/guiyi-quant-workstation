from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import math
from types import SimpleNamespace

import numpy as np
import pytest

from app.alerts.evaluators import AlertEvaluationError, HtdyOriginal15mEvaluator
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


def _window(length: int = 32) -> MarketReadWindow:
    bars = tuple(_bar(index) for index in range(length))
    return MarketReadWindow(
        symbol="j",
        series_kind="actual_dominant",
        frequency="15m",
        trading_day=date(2025, 1, 2),
        contract="J2505",
        cutoff=bars[-1].bar_end,
        bars=bars,
    )


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

    assert HtdyOriginal15mEvaluator().evaluate(_window()).observation_types == expected


@pytest.mark.parametrize(
    "window",
    (
        replace(_window(), frequency="5m"),
        replace(_window(), series_kind="continuous"),
        _window(31),
    ),
)
def test_evaluator_fails_closed_for_wrong_identity_or_short_context(
    window: MarketReadWindow,
) -> None:
    with pytest.raises(AlertEvaluationError, match="ALERT_EVALUATION_INPUT_INVALID"):
        HtdyOriginal15mEvaluator().evaluate(window)


def test_32_bar_contract_matches_full_history_current_observation() -> None:
    length = 128
    datetimes = [f"t{index}" for index in range(length)]
    base = [100 + math.sin(index / 4) * 3 + index * 0.03 for index in range(length)]
    open_ = [value + math.sin(index) * 0.5 for index, value in enumerate(base)]
    high = [max(open_[index], base[index]) + 1 + index % 5 * 0.1 for index in range(length)]
    low = [min(open_[index], base[index]) - 1 - index % 3 * 0.1 for index in range(length)]
    close = [value + math.cos(index / 3) * 0.7 for index, value in enumerate(base)]
    volume = [1000 + index * 7 for index in range(length)]

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
