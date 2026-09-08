"""MACD display adapts the real kernel without changing strategy facts."""

from dataclasses import asdict, replace
from decimal import Decimal

from guiyi_quant.indicators.macd import MACD_VERSION, macd_series
from app.api.market_newow import _product_response
from app.market_data.newow.product_service import ProductServiceQuery
from newow.test_product_service import _service


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


def _points(series, indices):
    return [asdict(series.points[index]) for index in indices]


def test_macd_matches_real_kernel_prefix_including_warming_and_zero(product_cases):
    service, reader, _, _ = _service(product_cases)
    reader.bars = tuple(
        replace(
            item,
            bar=replace(
                item.bar,
                open=Decimal(100),
                high=Decimal(100),
                low=Decimal(100),
                close=Decimal(100),
            ),
        )
        for item in reader.bars[:45]
    )
    result = _query(service, reader.bars)
    value = _product_response(result).model_dump(mode="json")["auxiliary"]["value"]
    expected = macd_series(
        [100] * 45,
        12,
        26,
        9,
        ema_seed_policy="sma_window",
        histogram_scale=2,
        round_digits=6,
        bar_ends=[
            item.bar.bar_end.isoformat().replace("+00:00", "Z") for item in reader.bars
        ],
    )
    assert value["formula_version"] == MACD_VERSION
    assert value["display_adapter_version"] == "guiyi_newow_macd_display_v1"
    assert value["parameters"] == expected.parameters
    assert value["parameters_hash"] == expected.parameters_hash
    indices = [i for i, item in enumerate(reader.bars) if item.bar.observation_eligible]
    data = value["segments"][0]["data"]
    for key in ("dif", "dea", "histogram"):
        assert data[key] == _points(getattr(expected, key), indices)
    assert expected.dif.points[25].ready and not expected.dea.points[25].ready
    assert data["histogram"][-1]["value"] == 0
    assert data["histogram"][-1]["valid"] is True
    assert (
        value["repainting"]
        is value["formal_signal_eligible"]
        is value["page_parity"]
        is False
    )
    assert value["allowed_uses"] == ["research_display"]


def test_macd_window_and_as_of_only_clip_same_lifecycle_values(product_cases):
    service, reader, _, _ = _service(product_cases)
    bars = reader.bars
    full = _query(service, bars).auxiliary.value
    since, through = bars[-15].bar.trading_day, bars[-5].bar.trading_day
    cutoff = bars[-8].bar.bar_end
    clipped = _query(
        service, bars, since=since, through=through, as_of=cutoff
    ).auxiliary.value
    expected = {
        point.bar_end: point for segment in full.segments for point in segment.value.dif
    }
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
    expected = macd_series(
        [float(item.bar.close) for item in second],
        12,
        26,
        9,
        ema_seed_policy="sma_window",
        histogram_scale=2,
        round_digits=6,
        bar_ends=[item.bar.bar_end.isoformat() for item in second],
    )
    assert segment.value.dif == tuple(expected.dif.points[3:])
    assert segment.value.dea == tuple(expected.dea.points[3:])
    assert segment.value.histogram == tuple(expected.histogram.points[3:])
    assert not segment.value.dif[0].ready
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

    def counted(identity, read):
        calls.append(read)
        return calculate(identity, read)

    monkeypatch.setattr(module, "calculate_macd_display", counted)
    first = _query(service, reader.bars)
    assert first.meta.snapshot_token is not None
    assert _query(service, reader.bars).auxiliary == first.auxiliary
    assert len(calls) == 1
    monkeypatch.setattr(
        module, "MACD_CACHE_IDENTITY", ("v1-draft", "test-adapter-v2", "new-parameters")
    )
    _query(service, reader.bars)
    assert len(calls) == 2

    cache = SnapshotCache(max_entry_bytes=4096)
    assert cache.put("facts", ("macd",), first) is None
    assert cache.get("facts", ("macd",)) is None
