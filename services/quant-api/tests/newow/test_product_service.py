from dataclasses import replace

import pytest

from guiyi_quant.newow.product_adapters import replay_strategy
from guiyi_quant.newow.product_contracts import ProductFrequency

from app.market_data.domain import ResolvedContractSegment

from app.market_data.newow.product_query import ProductReadWindow
from app.market_data.newow.product_reader import (
    ProductReadSet,
    ResolvedPerformanceWindow,
)
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

    def resolve_performance_window(self, _product, since, through, _as_of):
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
    last = reader.bars[-1]
    reader.bars = (
        *reader.bars[:-1],
        replace(last, bar=replace(last.bar, close=last.bar.close + 1)),
    )

    with pytest.raises(
        NewowProductServiceError, match="NEWOW_SNAPSHOT_GENERATION_CONFLICT"
    ):
        service.query(replace(request, snapshot_token=first.meta.snapshot_token))


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
        "previous_close",
    }


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
