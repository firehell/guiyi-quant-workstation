"""MACD display adapts the real kernel without changing strategy facts."""

from dataclasses import replace
from decimal import Decimal
from importlib.metadata import version
from math import isfinite
import re

import numpy as np
import pytest
import talib
from guiyi_quant.compute import REGISTRY
from app.api.market_newow import _product_response
from app.market_data.newow.product_macd import MACD_CACHE_IDENTITY
from app.market_data.newow.product_service import ProductServiceQuery
from newow.test_product_service import _service


def _auxiliary_out(result):
    return _product_response(result).model_dump(mode="json")["auxiliary"]


def _query(service, bars, **kwargs):
    return service.query(
        ProductServiceQuery(
            "rb",
            "trend",
            "1d",
            section="auxiliary",
            component="macd",
            as_of=kwargs.pop("as_of", bars[-1].bar.bar_end),
            **kwargs,
        )
    )


def _direct_macd(bars):
    closes = np.array([float(item.bar.close) for item in bars], dtype=np.float64)
    return dict(zip(
        ("dif", "dea", "histogram"),
        talib.MACD(closes, fastperiod=12, slowperiod=26, signalperiod=9),
        strict=True,
    ))


@pytest.mark.parametrize("constant", [False, True])
def test_macd_matches_unscaled_talib_prefix_including_warming_and_zero(product_cases, constant):
    service, reader, _, _ = _service(product_cases)
    reader.bars = reader.bars[:45]
    if constant:
        reader.bars = _constant_bars(reader.bars, Decimal(100))
    value = _auxiliary_out(_query(service, reader.bars))["value"]
    expected = _direct_macd(reader.bars)
    assert value["formula_version"] == REGISTRY.definition("macd").formula_version == "talib_macd_12_26_9_v1"
    assert value["display_adapter_version"] == "guiyi_newow_macd_display_v2"
    assert value["parameters"] == {"fast": 12, "slow": 26, "signal": 9}
    assert re.fullmatch("[0-9a-f]{16}", value["parameters_hash"])
    assert value["parameters_hash"] == MACD_CACHE_IDENTITY[2]
    indices = [i for i, item in enumerate(reader.bars) if item.bar.observation_eligible]
    data = value["segments"][0]["data"]
    for key, outputs in expected.items():
        assert data[key] == [
            {
                "bar_end": reader.bars[index].bar.bar_end.isoformat().replace("+00:00", "Z"),
                "value": float(outputs[index]) if isfinite(outputs[index]) else None,
                "ready": index >= 33,
                "valid": True,
                "reason": None if index >= 33 else "warming_up",
            }
            for index in indices
        ]
    if constant:
        assert data["histogram"][-1]["value"] == 0
    else:
        assert any(point["value"] not in (None, 0) for point in data["histogram"])
    assert (
        value["repainting"]
        is value["formal_signal_eligible"]
        is value["page_parity"]
        is False
    )
    assert value["allowed_uses"] == ["research_display"]


def _constant_bars(bars, price):
    return tuple(
        replace(item, bar=replace(item.bar, open=price, high=price, low=price, close=price))
        for item in bars
    )


def test_macd_nonfinite_outputs_are_unavailable(product_cases):
    service, reader, _, _ = _service(product_cases)
    reader.bars = _constant_bars(reader.bars[:45], Decimal("1e308"))
    direct = _direct_macd(reader.bars)
    assert all(not isfinite(outputs[-1]) for outputs in direct.values())
    wire = _auxiliary_out(_query(service, reader.bars))
    assert wire["status"]["status"] == "unavailable"
    segment = wire["value"]["segments"][0]
    assert segment["status"]["status"] == "unavailable"
    for points in segment["data"].values():
        assert points[-1] | {"bar_end": None} == {
            "bar_end": None, "value": None, "ready": False, "valid": False, "reason": "OUTPUT_NONFINITE",
        }


def test_macd_window_and_as_of_only_clip_same_lifecycle_values(product_cases):
    service, reader, _, _ = _service(product_cases)
    bars = reader.bars
    full = _query(service, bars).auxiliary.value
    since, through = bars[-15].bar.trading_day, bars[-5].bar.trading_day
    cutoff = bars[-8].bar.bar_end
    clipped = _query(
        service, bars, since=since, through=through, as_of=cutoff
    ).auxiliary.value
    assert clipped.segments
    for segment in clipped.segments:
        assert segment.bar_ends
        for key in ("dif", "dea", "histogram"):
            expected = {
                point.bar_end: point
                for full_segment in full.segments
                for point in getattr(full_segment.value, key)
            }
            for point in getattr(segment.value, key):
                assert point == expected[point.bar_end]
        assert all(
            since <= end.date() <= through and end <= cutoff for end in segment.bar_ends
        )
    assert min(clipped.segments[0].bar_ends) >= bars[-15].bar.bar_end


def test_macd_resets_each_physical_segment_and_hides_warmup_only_bars(product_cases):
    service, reader, _, _ = _service(product_cases)
    first = reader.bars[:40]
    second = tuple(
        replace(
            item,
            bar=replace(
                item.bar,
                physical_contract="RB2701",
                segment_id="rb:RB2701:new",
                observation_eligible=index >= 3,
            ),
        )
        for index, item in enumerate(reader.bars[40:80])
    )
    reader.bars = first + second
    layer = _query(service, reader.bars).auxiliary.value
    assert len(layer.segments) == 2
    segment = layer.segments[1]
    for key, values in _direct_macd(second).items():
        points = getattr(segment.value, key)
        assert [point.value for point in points] == [
            float(value) if isfinite(value) else None for value in values[3:]
        ]
        assert not points[29].ready
        assert points[30].ready
    assert segment.bar_ends[0] == second[3].bar.bar_end


def test_macd_does_not_change_chart_action_or_reference_identity(product_cases):
    service, reader, build, clear = _service(product_cases)
    chart_query = ProductServiceQuery("rb", "trend", "1d", as_of=clear.bar_end)
    reference_query = ProductServiceQuery(
        "rb",
        "trend",
        "1d",
        section="reference",
        as_of=clear.bar_end,
        performance_since=build.trading_day,
        performance_through=clear.trading_day,
    )
    before = service.query(chart_query), service.query(reference_query)
    _query(service, reader.bars, as_of=clear.bar_end)
    after = service.query(chart_query), service.query(reference_query)
    assert before[0].chart == after[0].chart
    assert before[1].reference == after[1].reference
    assert before[0].meta.identity == after[0].meta.identity


def test_macd_cache_identity_and_budget_cover_display_payload(
    monkeypatch, product_cases
):
    from app.market_data.newow import product_service as module
    from app.market_data.newow.snapshot_cache import SnapshotCache

    service, reader, _, _ = _service(product_cases)
    calls = []
    calculate = module.calculate_macd_display

    def counted(identity, read, *, source_revision):
        calls.append(read)
        return calculate(identity, read, source_revision=source_revision)

    monkeypatch.setattr(module, "calculate_macd_display", counted)
    first = _query(service, reader.bars)
    assert first.meta.snapshot_token is not None
    assert _query(service, reader.bars).auxiliary == first.auxiliary
    assert len(calls) == 1
    formula, adapter, parameters, backend = MACD_CACHE_IDENTITY
    assert backend == f"ta-lib:{version('ta-lib')}"
    for index, changed in enumerate((
        (formula, "test-adapter-v3", parameters, backend),
        (formula, adapter, "a" * 16, backend),
        (formula, adapter, parameters, "ta-lib:testing"),
    ), start=2):
        monkeypatch.setattr(module, "MACD_CACHE_IDENTITY", changed)
        result = _query(service, reader.bars)
        assert len(calls) == index
        assert result.meta.shared_input_proof.market_input_sha256 == first.meta.shared_input_proof.market_input_sha256
        assert result.meta.shared_input_proof.auxiliary_input_sha256 != first.meta.shared_input_proof.auxiliary_input_sha256

    cache = SnapshotCache(max_entry_bytes=4096)
    assert cache.put("facts", ("macd",), first) is None
    assert cache.get("facts", ("macd",)) is None
