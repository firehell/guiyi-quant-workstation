"""Future owner metadata must not become an out-of-window reference event."""

from datetime import timedelta
from types import SimpleNamespace
import pytest
from app.reference_trading.inputs import MarketDataHistoricalInputReader
from app.reference_trading.planning import HistoricalStreamRequest
from guiyi_quant.reference_trading import StreamIdentity
from guiyi_quant.newow.product_identity import (
    reference_model_version,
    futures_adaptation_version,
)


@pytest.mark.parametrize("event_kind", ["rollover", "gap"])
@pytest.mark.parametrize("outside", ["through", "as_of"])
@pytest.mark.parametrize("strategy", ["trend", "oscillation", "main_rise"])
@pytest.mark.parametrize("frequency", ["1w", "1d", "60m"])
def test_later_owner_metadata_is_not_a_reference_input(
    strategy, frequency, event_kind, outside
):
    if event_kind == "gap" and frequency == "60m":
        pytest.skip("quality interruption contract is D1/W1")
    from newow.product_fixtures import ProductCases

    case = ProductCases().primitive_input(strategy, frequency)
    last = case.bars[-1].bar
    p = case.identity
    stream = StreamIdentity(
        "newow_" + strategy,
        p.formula_versions,
        p.profile_id,
        reference_model_version(p),
        futures_adaptation_version(frequency, p.input_quality_policy),
        p.product,
        frequency,
        "actual_dominant",
        "historical_replay",
        None,
    )
    request = HistoricalStreamRequest(
        stream,
        case.bars[0].bar.trading_day,
        last.trading_day,
        last.bar_end
        + (timedelta(days=3) if outside == "through" else timedelta(hours=2)),
    )
    future = SimpleNamespace(
        old_contract=last.physical_contract,
        old_segment_id=last.segment_id,
        effective_at=last.bar_end + timedelta(hours=6),
        effective_trading_day=last.trading_day
        + (timedelta(days=3) if outside == "through" else timedelta()),
    )
    from guiyi_quant.newow.product_contracts import DataInterruption

    gap = DataInterruption(
        p.product,
        p.frequency,
        last.physical_contract,
        last.segment_id,
        future.effective_trading_day,
        future.effective_at,
        "fixture",
    )
    read = SimpleNamespace(
        boundaries=(future,) if event_kind == "rollover" else (),
        data_interruptions=(gap,) if event_kind == "gap" else (),
        lifecycle_evidence=(),
        replay_bars=case.bars,
        input_quality_policy=p.input_quality_policy,
        owners=(),
    )
    reader = object.__new__(MarketDataHistoricalInputReader)

    def finish(_request, _query, _reader, _read, _frequency, bars, *_, **__):
        try:
            return tuple(bars)
        finally:
            bars.close()

    reader._finish_newow_snapshot = finish
    result = reader._read_newow_loaded(
        request,
        SimpleNamespace(product=p.product),
        None,
        read,
        p.frequency,
        p.strategy,
        production_historical=False,
    )
    assert result and all(item.strategy_input for item in result)
    assert max(item.bar_end for item in result) == last.bar_end
    assert all(item.trading_day <= request.through for item in result)
