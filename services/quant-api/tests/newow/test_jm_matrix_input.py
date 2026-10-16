from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.market_data.domain import BarFrequency
from app.market_data.newow import jm_matrix_input
from app.market_data.newow.jm_matrix_input import MatrixInput, load_matrix_input
from app.market_data.newow.jm_pilot_research import JMPilotInput, _input_sha256
from guiyi_quant.newow.product_contracts import ProductFrequency
from guiyi_quant.newow.research_backtest import (
    NewowResearchBar,
    NewowStrategyReplaySegment,
)


def _bar(frequency: str = "5m", *, eligible: bool = True) -> NewowResearchBar:
    return NewowResearchBar(
        product="jm", physical_contract="JM2605", segment_id="jm:JM2605:fixture",
        trading_day=date(2026, 1, 5),
        bar_end=datetime(2026, 1, 5, 7, tzinfo=UTC),
        open=Decimal("100"), high=Decimal("101"),
        low=Decimal("99"), close=Decimal("100"),
        volume=100, open_interest=1000, source_identity="canonical-jm-0",
        observation_eligible=eligible, completed=True, frequency=frequency,
        series_kind="actual_dominant" if eligible else "contract",
    )


def test_matrix_input_binds_frequency_and_replay_hash() -> None:
    bar = _bar()
    segments = (NewowStrategyReplaySegment((bar,)),)
    source = MatrixInput(
        (bar,), segments, bar.trading_day, bar.trading_day,
        _input_sha256(segments), ProductFrequency.FIVE_MINUTE,
    )
    assert source.bars == (bar,)

    with pytest.raises(ValueError, match="JM_MATRIX_INPUT_INVALID"):
        MatrixInput(
            (bar,), segments, bar.trading_day, bar.trading_day,
            "0" * 64, ProductFrequency.FIVE_MINUTE,
        )
    with pytest.raises(ValueError, match="JM_MATRIX_INPUT_INVALID"):
        MatrixInput(
            (bar,), segments, bar.trading_day, bar.trading_day,
            source.input_sha256, ProductFrequency.WEEKLY,
        )


def test_five_minute_load_reuses_pilot_input_and_completed_window(monkeypatch) -> None:
    bar = _bar()
    segments = (NewowStrategyReplaySegment((bar,)),)
    pilot = JMPilotInput(
        (bar,), segments, bar.trading_day, bar.trading_day,
        _input_sha256(segments),
    )
    calls = []

    class Reader:
        def resolve_performance_window(self, *args):
            calls.append(args)
            return SimpleNamespace(actual_through=bar.trading_day)

    monkeypatch.setattr(
        jm_matrix_input, "load_jm_pilot_input",
        lambda _market, *, since, actual_through: pilot,
    )
    as_of = datetime(2026, 1, 6, tzinfo=UTC)
    source = load_matrix_input(
        object(), Reader(), ProductFrequency.FIVE_MINUTE,
        since=bar.trading_day, requested_through=bar.trading_day + timedelta(days=1),
        as_of=as_of,
    )
    assert source.frequency is ProductFrequency.FIVE_MINUTE
    assert source.input_sha256 == pilot.input_sha256
    assert calls == [(
        "jm", ProductFrequency.FIVE_MINUTE, bar.trading_day,
        bar.trading_day + timedelta(days=1), as_of,
    )]


def test_weekly_last_endpoint_uses_owned_completed_mds_identity() -> None:
    owner = SimpleNamespace(
        contract="JM2605", start_trading_day=date(2026, 1, 1),
        end_trading_day=date(2026, 1, 10),
    )
    expected_end = datetime(2026, 1, 9, 7, tzinfo=UTC)

    class Market:
        def expected_contract_replay_endpoints(self, **kwargs):
            assert kwargs["frequency"] is BarFrequency.W1
            assert kwargs["since"] == owner.start_trading_day
            return ((expected_end, date(2026, 1, 9)),)

    assert jm_matrix_input._last_completed_weekly_endpoint(
        Market(), owners=(owner,), actual_through=date(2026, 1, 10),
        cutoff=datetime(2026, 1, 10, tzinfo=UTC),
    ) == (date(2026, 1, 9), expected_end)
    assert jm_matrix_input._physical_since(BarFrequency.W1, date(2026, 1, 1)) == date.min
    assert jm_matrix_input._physical_since(BarFrequency.M15, date(2026, 1, 1)) == date(2025, 12, 2)

    class EmptyMarket:
        def expected_contract_replay_endpoints(self, **_kwargs):
            return ()

    with pytest.raises(ValueError, match="JM_MATRIX_COMPLETED_WEEKLY_INPUT_MISSING"):
        jm_matrix_input._last_completed_weekly_endpoint(
            EmptyMarket(), owners=(owner,), actual_through=date(2026, 1, 10),
            cutoff=datetime(2026, 1, 10, tzinfo=UTC),
        )
