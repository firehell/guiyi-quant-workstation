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


def test_query_rejects_section_specific_parameter_leakage():
    try:
        ProductServiceQuery(
            "rb", "trend", "1d", section="chart", history_before="opaque"
        )
    except ValueError as error:
        assert str(error) == "NEWOW_SECTION_PARAMETER_INVALID"
    else:
        raise AssertionError("invalid cross-section parameter accepted")


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
    service = NewowProductService(lambda _context, _cancelled: reader, now=lambda: as_of)

    result = service.query(
        ProductServiceQuery(
            "rb",
            "trend",
            "1d",
            section="explanation",
            since=min(items[0].bar.trading_day for items in bars.values()),
            through=as_of.date(),
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
    service = NewowProductService(lambda _context, _cancelled: reader, now=lambda: as_of)

    result = service.query(
        ProductServiceQuery(
            "rb",
            "oscillation",
            "1d",
            section="comparator",
            since=case.bars[0].bar.trading_day,
            through=case.bars[-1].bar.trading_day,
            as_of=as_of,
        )
    )

    assert result.comparator.delivery == "delivered"
    assert result.comparator.value.value is not None
    assert result.reference.delivery == "not_requested"
