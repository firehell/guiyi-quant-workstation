from dataclasses import replace
from datetime import timedelta
from threading import Event, Thread
from time import sleep

import pytest

from guiyi_quant.newow.product_adapters import replay_strategy
from guiyi_quant.newow.product_contracts import ProductFrequency

from app.market_data.domain import ResolvedContractSegment

from app.market_data.newow.product_query import ProductReadWindow
from app.market_data.newow.product_reader import (
    ProductReadSet,
    ResolvedPerformanceWindow,
)
from app.market_data.newow.resource_gate import HeavyResourceGate, NewowResourceBusy
from app.market_data.newow.product_service import (
    NewowProductService,
    NewowProductServiceError,
    ProductSection,
    ProductServiceQuery,
)


class _Reader:
    def __init__(self, bars, boundary_cutoff, extended_cutoff):
        self.bars = bars
        self.boundary_cutoff = boundary_cutoff
        self.extended_cutoff = extended_cutoff
        self.loads = []

    def resolve_chart_window(self, _product, _frequency, _limit, _as_of):
        return ProductReadWindow(
            self.bars[0].bar.trading_day, self.bars[-1].bar.trading_day
        )

    def resolve_performance_window(self, _product, _frequency, since, through, _as_of):
        assert since is not None and through is not None
        cutoff = (
            self.boundary_cutoff
            if through == self.boundary_cutoff.date()
            else self.extended_cutoff
        )
        actual = through
        return ResolvedPerformanceWindow(since, through, actual, cutoff)

    def load(self, query, as_of):
        self.loads.append(query)
        return ProductReadSet(
            query.frequency,
            {query.frequency: self.bars},
            (),
            (),
            ProductReadWindow(query.since, query.through),
            ProductReadWindow(query.performance_since, query.performance_through),
            {},
            as_of,
        )


def _service(product_cases):
    case = product_cases.primitive_input("trend", "1d")
    replay = replay_strategy(case.identity, case.bars)
    build, clear = replay.actions[:2]
    reader = _Reader(case.bars, build.bar_end, clear.bar_end)
    now = clear.bar_end.replace(year=2027)
    service = NewowProductService(lambda _context, _cancelled: reader, now=lambda: now)
    return service, reader, build, clear


def test_reference_cutoff_keeps_later_clear_open_until_user_extends_window(
    product_cases,
):
    service, _reader, build, clear = _service(product_cases)
    first = service.query(
        ProductServiceQuery(
            "rb",
            "trend",
            "1d",
            section="reference",
            performance_since=build.trading_day,
            performance_through=build.trading_day,
            as_of=clear.bar_end,
        )
    )
    extended = service.query(
        ProductServiceQuery(
            "rb",
            "trend",
            "1d",
            section="reference",
            performance_since=build.trading_day,
            performance_through=clear.trading_day,
            as_of=clear.bar_end,
        )
    )

    assert first.reference.value.summary.open_count == 1
    assert first.reference.value.summary.closed_count == 0
    assert first.reference.value.reference_cutoff == build.bar_end
    assert first.meta.as_of == clear.bar_end
    assert extended.reference.value.summary.open_count == 0
    assert extended.reference.value.summary.closed_count == 1
    assert extended.reference.value.reference_cutoff == clear.bar_end


def test_chart_does_not_call_reference_or_auxiliary(monkeypatch, product_cases):
    service, reader, _build, clear = _service(product_cases)
    from app.market_data.newow import product_service as module

    monkeypatch.setattr(
        module,
        "ReferenceTradeProjector",
        lambda: (_ for _ in ()).throw(AssertionError("reference requested implicitly")),
    )
    monkeypatch.setattr(
        module,
        "calculate_auxiliary_component",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("auxiliary requested implicitly")
        ),
    )

    result = service.query(
        ProductServiceQuery("rb", "trend", "1d", as_of=clear.bar_end, chart_limit=10)
    )

    assert result.section is ProductSection.CHART
    assert result.chart.delivery == "delivered"
    assert result.reference.delivery == "not_requested"
    assert reader.loads[-1].performance_since == reader.loads[-1].since


def test_identical_service_misses_share_reader_and_calculation(product_cases):
    service, reader, _build, clear = _service(product_cases)
    original = reader.load
    entered = Event()
    release = Event()
    calls = []
    results = []

    def slow_load(query, as_of):
        calls.append(query)
        entered.set()
        release.wait(1)
        return original(query, as_of)

    reader.load = slow_load
    request = ProductServiceQuery("rb", "trend", "1d", as_of=clear.bar_end)
    first = Thread(target=lambda: results.append(service.query(request)))
    second = Thread(target=lambda: results.append(service.query(request)))
    first.start()
    assert entered.wait(1)
    second.start()
    sleep(0.02)
    release.set()
    first.join(1)
    second.join(1)

    assert len(calls) == 1
    assert len(results) == 2
    assert results[0].meta.input_content_sha256 == results[1].meta.input_content_sha256


def test_heavy_admission_happens_before_reader_resolution_or_load(product_cases):
    _service_instance, reader, build, clear = _service(product_cases)
    gate = HeavyResourceGate(max_running=1, max_waiting=0, wait_timeout=0.01)
    lease = gate.acquire()
    service = NewowProductService(
        lambda _context, _cancelled: reader,
        heavy_gate=gate,
        now=lambda: clear.bar_end,
    )

    with pytest.raises(NewowResourceBusy, match="NEWOW_RESOURCE_BUSY"):
        service.query(
            ProductServiceQuery(
                "rb",
                "trend",
                "1d",
                section="reference",
                performance_since=build.trading_day,
                performance_through=clear.trading_day,
                as_of=clear.bar_end,
            )
        )
    lease.release()

    assert reader.loads == []


def test_different_heavy_queries_share_the_same_single_reader_admission(product_cases):
    _service_instance, reader, build, clear = _service(product_cases)
    original = reader.load
    first_entered = Event()
    release_first = Event()
    active = 0
    maximum_active = 0
    calls = 0

    def slow_load(query, as_of):
        nonlocal active, maximum_active, calls
        calls += 1
        active += 1
        maximum_active = max(maximum_active, active)
        try:
            if calls == 1:
                first_entered.set()
                release_first.wait(1)
            return original(query, as_of)
        finally:
            active -= 1

    reader.load = slow_load
    service = NewowProductService(
        lambda _context, _cancelled: reader,
        heavy_gate=HeavyResourceGate(max_running=1, max_waiting=2),
        now=lambda: clear.bar_end,
    )
    common = dict(
        product="rb",
        strategy="trend",
        frequency="1d",
        section="reference",
        performance_since=build.trading_day,
        performance_through=clear.trading_day,
        as_of=clear.bar_end,
    )
    results = []
    first = Thread(
        target=lambda: results.append(
            service.query(ProductServiceQuery(**common, history_limit=1))
        )
    )
    second = Thread(
        target=lambda: results.append(
            service.query(ProductServiceQuery(**common, history_limit=2))
        )
    )
    first.start()
    assert first_entered.wait(1)
    second.start()
    sleep(0.02)
    assert calls == 1
    release_first.set()
    first.join(1)
    second.join(1)

    assert len(results) == 2
    assert calls == 2
    assert maximum_active == 1


def test_history_limit_and_viewport_do_not_change_reference_summary_or_identity(
    product_cases,
):
    service, _reader, build, clear = _service(product_cases)
    common = dict(
        product="rb",
        strategy="trend",
        frequency="1d",
        section="reference",
        performance_since=build.trading_day,
        performance_through=clear.trading_day,
        as_of=clear.bar_end,
    )
    first = service.query(ProductServiceQuery(**common, history_limit=1))
    second = service.query(ProductServiceQuery(**common, history_limit=200))

    assert first.reference.value.summary == second.reference.value.summary
    assert (
        first.reference.value.reference_input_sha256
        == second.reference.value.reference_input_sha256
    )
    assert first.meta.input_content_sha256 == second.meta.input_content_sha256


def test_reference_cursor_moves_strictly_left_without_repeating_trade(product_cases):
    case = product_cases.primitive_input("trend", "1d")
    replay = replay_strategy(case.identity, case.bars)
    reader = _Reader(case.bars, replay.actions[0].bar_end, case.bars[-1].bar.bar_end)
    service = NewowProductService(
        lambda _context, _cancelled: reader,
        now=lambda: case.bars[-1].bar.bar_end,
    )
    request = ProductServiceQuery(
        "rb",
        "trend",
        "1d",
        section="reference",
        performance_since=replay.actions[0].trading_day,
        performance_through=case.bars[-1].bar.trading_day,
        as_of=case.bars[-1].bar.bar_end,
        history_limit=1,
    )
    first = service.query(request)
    cursor = first.reference.value.next_before
    assert cursor is not None

    second = service.query(replace(request, history_before=cursor))

    assert (
        first.reference.value.items[0].reference_trade_id
        != second.reference.value.items[0].reference_trade_id
    )
    third = service.query(
        replace(request, history_before=second.reference.value.next_before)
    )
    assert (
        len(
            {
                first.reference.value.items[0].reference_trade_id,
                second.reference.value.items[0].reference_trade_id,
                third.reference.value.items[0].reference_trade_id,
            }
        )
        == 3
    )

    with pytest.raises(
        NewowProductServiceError, match="NEWOW_CURSOR_GENERATION_CONFLICT"
    ):
        service.query(replace(request, history_before=cursor, history_limit=2))


def test_incomplete_requested_reference_window_is_warming_and_not_cached(
    product_cases,
):
    service, reader, build, clear = _service(product_cases)
    reader.resolve_performance_window = lambda *_args: ResolvedPerformanceWindow(
        build.trading_day,
        clear.trading_day,
        build.trading_day,
        build.bar_end,
        False,
        "NEWOW_REFERENCE_WINDOW_PARTIAL",
    )

    result = service.query(
        ProductServiceQuery(
            "rb",
            "trend",
            "1d",
            section="reference",
            performance_since=build.trading_day,
            performance_through=clear.trading_day,
            as_of=clear.bar_end,
        )
    )

    assert result.reference.status.status == "warming"
    assert result.reference.status.reason_code == "NEWOW_REFERENCE_WINDOW_PARTIAL"
    assert result.meta.snapshot_token is None


def test_weekly_reference_uses_last_completed_w1_bar_not_midweek_session(
    product_cases,
):
    case = product_cases.primitive_input("trend", "1w")
    last = case.bars[-1].bar
    midweek_day = last.trading_day + timedelta(days=2)
    midweek_as_of = last.bar_end + timedelta(days=2)
    reader = _Reader(case.bars, last.bar_end, midweek_as_of)
    reader.resolve_performance_window = lambda *_args: ResolvedPerformanceWindow(
        case.bars[0].bar.trading_day,
        midweek_day,
        midweek_day,
        midweek_as_of,
        False,
        "NEWOW_REFERENCE_WEEKLY_COMPLETION_PENDING",
    )
    service = NewowProductService(
        lambda _context, _cancelled: reader, now=lambda: midweek_as_of
    )

    result = service.query(
        ProductServiceQuery(
            "rb",
            "trend",
            "1w",
            section="reference",
            performance_since=case.bars[0].bar.trading_day,
            performance_through=midweek_day,
            as_of=midweek_as_of,
        )
    )

    assert result.reference.value.actual_available_through == last.trading_day
    assert result.reference.value.reference_cutoff == last.bar_end
    assert result.reference.status.status == "warming"
    assert (
        result.reference.status.reason_code == "NEWOW_REFERENCE_WEEKLY_WINDOW_PARTIAL"
    )


def test_query_rejects_section_specific_parameter_leakage():
    try:
        ProductServiceQuery(
            "rb", "trend", "1d", section="chart", history_before="opaque"
        )
    except ValueError as error:
        assert str(error) == "NEWOW_SECTION_PARAMETER_INVALID"
    else:
        raise AssertionError("invalid cross-section parameter accepted")


def test_snapshot_token_rejects_a_revised_common_bar(product_cases):
    service, reader, _build, clear = _service(product_cases)
    request = ProductServiceQuery(
        "rb", "trend", "1d", as_of=clear.bar_end, chart_limit=10
    )
    first = service.query(request)
    assert first.meta.snapshot_token is not None
    changed = list(reader.bars)
    anchor_index = max(
        index for index, item in enumerate(changed) if item.bar.bar_end <= clear.bar_end
    )
    anchor = changed[anchor_index]
    changed[anchor_index] = replace(
        anchor, bar=replace(anchor.bar, close=anchor.bar.close + 1)
    )
    reader.bars = tuple(changed)

    with pytest.raises(
        NewowProductServiceError, match="NEWOW_SNAPSHOT_GENERATION_CONFLICT"
    ):
        service.query(replace(request, snapshot_token=first.meta.snapshot_token))


def test_snapshot_token_allows_reference_with_compatible_common_facts(product_cases):
    service, reader, build, clear = _service(product_cases)
    original_load = reader.load

    def load_with_smaller_chart(query, as_of):
        loaded = original_load(query, as_of)
        if len(reader.loads) == 1:
            selected = tuple(
                item for item in loaded.replay_bars if item.bar.bar_end <= as_of
            )[-10:]
            return replace(
                loaded,
                bars_by_frequency={loaded.frequency: selected},
            )
        return loaded

    reader.load = load_with_smaller_chart
    chart = service.query(ProductServiceQuery("rb", "trend", "1d", as_of=clear.bar_end))

    reference = service.query(
        ProductServiceQuery(
            "rb",
            "trend",
            "1d",
            section="reference",
            performance_since=build.trading_day,
            performance_through=clear.trading_day,
            as_of=clear.bar_end,
            snapshot_token=chart.meta.snapshot_token,
        )
    )

    assert reference.meta.snapshot_token == chart.meta.snapshot_token
    assert reference.meta.input_content_sha256 != chart.meta.input_content_sha256


@pytest.mark.parametrize("strategy", ["trend", "oscillation", "main_rise"])
@pytest.mark.parametrize("frequency", ["1w", "1d", "60m"])
def test_chart_supports_all_nine_product_combinations(
    product_cases, strategy, frequency
):
    case = product_cases.primitive_input(strategy, frequency)
    reader = _Reader(case.bars, case.bars[0].bar.bar_end, case.bars[-1].bar.bar_end)
    service = NewowProductService(
        lambda _context, _cancelled: reader,
        now=lambda: case.bars[-1].bar.bar_end,
    )
    result = service.query(
        ProductServiceQuery(
            "rb",
            strategy,
            frequency,
            since=case.bars[0].bar.trading_day,
            through=case.bars[-1].bar.trading_day,
            as_of=case.bars[-1].bar.bar_end,
        )
    )
    assert result.chart.delivery == "delivered"
    assert result.meta.identity.strategy == strategy
    assert result.meta.identity.frequency == frequency


def test_chart_4001_prefix_pages_strictly_left_without_changing_fingerprint(
    product_cases,
):
    reader, low_query, fake = product_cases.paged_reader(
        prefix_bars=4001, frequency="60m"
    )
    service = NewowProductService(
        lambda _context, _cancelled: reader,
        now=lambda: fake.as_of,
    )
    request = ProductServiceQuery(
        "rb",
        "trend",
        "60m",
        since=low_query.since,
        through=low_query.through,
        as_of=fake.as_of,
        chart_limit=2000,
    )
    first = service.query(request)
    assert len(first.chart.value.bars) == 2000
    assert first.chart.value.next_before is not None
    second = service.query(replace(request, chart_before=first.chart.value.next_before))

    assert first.meta.input_content_sha256 == second.meta.input_content_sha256
    assert set(bar.bar.bar_end for bar in first.chart.value.bars).isdisjoint(
        bar.bar.bar_end for bar in second.chart.value.bars
    )
    assert max(bar.bar.bar_end for bar in second.chart.value.bars) < min(
        bar.bar.bar_end for bar in first.chart.value.bars
    )


class _MultiReader:
    def __init__(self, bars_by_frequency):
        self.bars_by_frequency = bars_by_frequency

    def resolve_chart_window(self, _product, frequency, _limit, _as_of):
        bars = self.bars_by_frequency[frequency]
        return ProductReadWindow(bars[0].bar.trading_day, bars[-1].bar.trading_day)

    def load(self, query, as_of):
        bars = self.bars_by_frequency[query.frequency]
        first = bars[0].bar
        last = bars[-1].bar
        return ProductReadSet(
            query.frequency,
            self.bars_by_frequency,
            (
                ResolvedContractSegment(
                    first.physical_contract, first.trading_day, last.trading_day
                ),
            ),
            (),
            ProductReadWindow(query.since, query.through),
            ProductReadWindow(query.performance_since, query.performance_through),
            {},
            as_of,
        )


def test_explanation_builds_six_owned_sources_and_keeps_target_gap(product_cases):
    bars = {
        frequency: product_cases.primitive_input("trend", frequency).bars
        for frequency in ProductFrequency
    }
    reader = _MultiReader(bars)
    as_of = min(items[-1].bar.bar_end for items in bars.values())
    service = NewowProductService(
        lambda _context, _cancelled: reader, now=lambda: as_of
    )

    result = service.query(
        ProductServiceQuery(
            "rb",
            "trend",
            "1d",
            section="explanation",
            as_of=as_of,
        )
    )

    value = result.explanation.value
    assert value.composite.value is not None
    assert value.target_absorb.status == "evidence_required"
    assert {source.role for source in value.sources} >= {
        "trend_weekly",
        "oscillation_hourly",
        "volatility_daily_prefix",
        "previous_close",
    }
    assert result.explanation.status.status == "evidence_required"
    assert result.meta.snapshot_token is None


def test_comparator_is_explicit_and_never_becomes_reference_trade(product_cases):
    case = product_cases.primitive_input("oscillation", "1d")
    reader = _MultiReader({ProductFrequency.DAILY: case.bars})
    as_of = case.bars[-1].bar.bar_end
    service = NewowProductService(
        lambda _context, _cancelled: reader, now=lambda: as_of
    )

    result = service.query(
        ProductServiceQuery(
            "rb",
            "oscillation",
            "1d",
            section="comparator",
            as_of=as_of,
        )
    )

    assert result.comparator.delivery == "delivered"
    assert result.comparator.value.value is not None
    assert result.reference.delivery == "not_requested"
