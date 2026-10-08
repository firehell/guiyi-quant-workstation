"""Real Canonical A×5m witnesses bound to frozen public-function outputs."""
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

import pytest

from guiyi_quant.newow.models import NewowDailyBar, TrendBandState
from guiyi_quant.newow.profile import NEWOW_TREND_D1_PAGE_V2
from guiyi_quant.newow.trend_band import TrendBandStateValue, initial_trend_band_state, step_trend_band

FIXTURE = json.loads((Path(__file__).parent / "fixtures/trend-binary64-real-a-5m.json").read_text())


def bars(witness):
    physical, owner, _ = witness["owner"].split("|")
    return tuple(NewowDailyBar(
        product="a", physical_contract=physical, segment_id=owner,
        trading_day=date.fromisoformat(row["trading_day"]), bar_end=datetime.fromisoformat(row["date"]),
        open=Decimal(row["open"]), high=Decimal(row["high"]), low=Decimal(row["low"]), close=Decimal(row["close"]),
        volume=row["volume"], open_interest=0, source_identity=f"canonical:{FIXTURE['input_sha256']}:{row['date']}",
        completed=True, observation_eligible=row["observation_eligible"],
    ) for row in witness["window"])


def run(inputs, state=None):
    state = initial_trend_band_state() if state is None else state
    results = []
    for bar in inputs:
        result = step_trend_band(state, bar, profile=NEWOW_TREND_D1_PAGE_V2)
        results.append(result)
        state = result.state
    return tuple(results)


@pytest.mark.parametrize("witness", FIXTURE["witnesses"], ids=lambda w:w["date"])
def test_real_boundary_matches_source_binary64_band_state_and_exact_marker_time(witness):
    inputs = bars(witness)
    results = run(inputs)
    source = witness["source_small_window"]
    for index,result in enumerate(results):
        assert result.point.b_value == source["a"][index]
        assert result.point.c_value == source["b"][index]
        assert result.point.state.value.lower() == source["states"][index]
    actual=[(index,"buy" if result.marker.marker_type.value=="BUILD" else "sell",float(result.marker.price))
            for index,result in enumerate(results) if result.marker is not None]
    assert actual == [(item["index"],item["type"],item["price"]) for item in source["signals"]]
    assert results[10].marker is not None
    assert results[10].marker.bar_end == datetime.fromisoformat(witness["date"])
    assert results[10].marker.marker_type.value == ("BUILD" if witness["marker_type"]=="buy" else "CLEAR")
    for end in range(1,len(inputs)+1):
        assert run(inputs[:end]) == results[:end]
    # A JSON persisted float round-trip must preserve the exact boundary state,
    # and validation must use the same accumulation semantics as the step.
    state=results[9].state
    decoded=json.loads(json.dumps(asdict(state),default=lambda value:value.value if isinstance(value,TrendBandState) else str(value)))
    restored=TrendBandStateValue(tuple(decoded["weighted_window"]),tuple(decoded["signal_window"]),TrendBandState(decoded["previous_state"]),
        None if decoded["last_build_close"] is None else Decimal(decoded["last_build_close"]),decoded["last_build_marker_id"],decoded["physical_contract"],decoded["segment_id"])
    assert run(inputs[10:],restored) == results[10:]
