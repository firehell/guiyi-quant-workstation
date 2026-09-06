"""Reader contracts over owned MDS facts, never local market files or services."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.newow.product_contracts import ProductFrequency

from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
)
from app.market_data.aggregation import SessionWindow
from app.market_data.domain import (
    BarFrequency,
    ResolvedContractSegment,
    SeriesKind,
    SeriesPageCursorMode,
)
from app.market_data.market_data_service import MarketDataError
from app.market_data.newow.product_query import NewowProductQuery
from app.market_data.newow.product_reader import (
    NewowProductReadCancelled,
    NewowProductReader,
    NewowProductReadError,
)


def test_reader_consumes_all_prefix_pages(product_cases):
    reader, query, fake = product_cases.paged_reader(prefix_bars=4001, page_size=2000)
    result = reader.load(query, product_cases.as_of)
    physical = fake.physical[("RB2605", BarFrequency.H1)]

    assert isinstance(reader, NewowProductReader)
    assert isinstance(query, NewowProductQuery)
    assert len(result.replay_bars) == 4001
    assert fake.physical_page_sizes == [2000, 2000, 1]
    assert [r.before for r in fake.physical_page_requests] == [
        physical[4000].bar_end,
        physical[2001].bar_end,
        physical[1].bar_end,
    ]
    assert all(
        r.limit == 2000 and r.contract == "RB2605" for r in fake.physical_page_requests
    )
    assert all(r.frequency is BarFrequency.H1 for r in fake.physical_page_requests)
    assert [bar.bar.bar_end for bar in result.replay_bars] == [
        bar.bar_end for bar in physical
    ]
    assert [bar.bar.observation_eligible for bar in result.replay_bars[:9]] == [
        False
    ] * 8 + [True]
    assert (
        result.replay_bars[0].bar.trading_day == result.replay_bars[3].bar.trading_day
    )
    assert fake.coverage_requests == [
        (
            "rb",
            "RB2605",
            BarFrequency.H1,
            physical[-1].trading_day,
            physical[-1].bar_end,
            None,
        )
    ]


@pytest.mark.parametrize("frequency", ["1w", "1d", "60m"])
def test_reads_requested_canonical_frequency_without_fallback(product_cases, frequency):
    reader, query, fake = product_cases.paged_reader(prefix_bars=3, frequency=frequency)
    result = reader.load(query, product_cases.as_of)
    assert len(result.replay_bars) == 3
    assert set(result.bars_by_frequency) == {frequency}
    assert all(bar.frequency == frequency for bar in result.replay_bars)
    assert {r.frequency.value for r in fake.actual_requests} == {frequency}
    assert {r.frequency.value for r in fake.physical_page_requests} == {frequency}
    assert {r.series_kind for r in fake.physical_page_requests} == {SeriesKind.CONTRACT}
    assert result.sources[frequency].bar_end == result.replay_bars[-1].bar.bar_end
    assert result.sources[frequency].as_of == product_cases.as_of


def _weekly_reader(product_cases):
    reader, query, fake = product_cases.paged_reader(prefix_bars=3, frequency="1w")
    sample = fake.physical[("RB2605", BarFrequency.W1)][0]
    first = replace(
        sample,
        trading_day=date(2023, 1, 6),
        bar_end=datetime(2023, 1, 6, 7, tzinfo=UTC),
    )
    last = replace(
        sample,
        trading_day=date(2023, 1, 13),
        bar_end=datetime(2023, 1, 13, 7, tzinfo=UTC),
    )
    fake.segments = (
        ResolvedContractSegment("RB2605", date(2023, 1, 2), date(2023, 1, 8)),
        ResolvedContractSegment("RB2609", date(2023, 1, 9), date(2023, 1, 10)),
        ResolvedContractSegment("RB2610", date(2023, 1, 11), date(2023, 1, 13)),
    )
    fake.actual = {BarFrequency.W1: (first, last)}
    fake.physical = {
        ("RB2605", BarFrequency.W1): (first,),
        ("RB2610", BarFrequency.W1): (first, last),
    }
    fake.expected_physical = dict(fake.physical)
    fake.as_of = datetime(2023, 1, 13, 8, tzinfo=UTC)
    fake.coverage.through = date(2023, 1, 13)
    return (
        reader,
        replace(
            query, through=date(2023, 1, 13), performance_through=date(2023, 1, 13)
        ),
        fake,
    )


def test_weekly_empty_middle_owner_keeps_both_authoritative_boundaries(product_cases):
    reader, query, fake = _weekly_reader(product_cases)
    result = reader.load(query, fake.as_of)
    assert [owner.contract for owner in result.owners] == ["RB2605", "RB2609", "RB2610"]
    assert [
        (b.old_contract, b.new_contract, b.effective_trading_day, b.effective_at)
        for b in result.boundaries
    ] == [
        ("RB2605", "RB2609", date(2023, 1, 9), datetime(2023, 1, 9, 1, tzinfo=UTC)),
        ("RB2609", "RB2610", date(2023, 1, 11), datetime(2023, 1, 11, 1, tzinfo=UTC)),
    ]
    assert [bar.bar.physical_contract for bar in result.replay_bars] == [
        "RB2605",
        "RB2610",
        "RB2610",
    ]
    assert [bar.bar.observation_eligible for bar in result.replay_bars] == [
        True,
        False,
        True,
    ]
    assert [r.contract for r in fake.physical_page_requests] == ["RB2605", "RB2610"]
    assert all(b.source_identity for b in result.boundaries)


def test_weekly_all_zero_owner_window_keeps_authoritative_boundaries(product_cases):
    reader, query, fake = _weekly_reader(product_cases)
    fake.actual = {BarFrequency.W1: ()}

    result = reader.load(query, fake.as_of)

    assert [owner.contract for owner in result.owners] == ["RB2605", "RB2609", "RB2610"]
    assert [boundary.new_contract for boundary in result.boundaries] == [
        "RB2609",
        "RB2610",
    ]
    assert result.replay_bars == ()
    assert fake.physical_page_requests == []


@pytest.mark.parametrize(
    "cutoff, contracts",
    [
        (datetime(2023, 1, 9, 0, 59, 59, tzinfo=UTC), []),
        (datetime(2023, 1, 9, 1, tzinfo=UTC), ["RB2609"]),
        (datetime(2023, 1, 11, 1, tzinfo=UTC), ["RB2609", "RB2610"]),
    ],
)
def test_only_effective_owners_can_prove_rollover_without_next_weekly_bar(
    product_cases, cutoff, contracts
):
    reader, query, fake = _weekly_reader(product_cases)
    result = reader.load(query, cutoff)
    assert [b.new_contract for b in result.boundaries] == contracts
    assert all(b.effective_at <= cutoff for b in result.boundaries)
    assert all(bar.bar.bar_end <= cutoff for bar in result.replay_bars)
    assert all(
        owner.end_trading_day <= fake.owner_requests[0][2] for owner in result.owners
    )
    assert all(r.contract != "RB2610" for r in fake.physical_page_requests)


def test_night_session_boundary_uses_next_trading_day_without_natural_date_guess(
    product_cases,
):
    reader, query, fake = _weekly_reader(product_cases)
    boundary_time = datetime(2023, 1, 6, 13, tzinfo=UTC)
    fake.sessions[date(2023, 1, 9)] = (
        SessionWindow(boundary_time, boundary_time + timedelta(hours=2)),
        *fake.sessions[date(2023, 1, 9)],
    )
    result = reader.load(query, boundary_time)
    assert [
        (b.new_contract, b.effective_trading_day, b.effective_at)
        for b in result.boundaries
    ] == [("RB2609", date(2023, 1, 9), boundary_time)]
    assert max(request[2] for request in fake.owner_requests) == date(2023, 1, 9)


def test_request_end_is_not_rollover_but_later_effective_mapping_is(product_cases):
    reader, query, fake = _weekly_reader(product_cases)
    clipped = replace(
        query, through=date(2023, 1, 6), performance_through=date(2023, 1, 6)
    )
    early = reader.load(clipped, datetime(2023, 1, 6, 8, tzinfo=UTC))
    late = reader.load(clipped, fake.as_of)
    assert early.boundaries == ()
    assert [b.new_contract for b in late.boundaries] == ["RB2609", "RB2610"]
    assert len(early.replay_bars) == len(late.replay_bars) == 1
    assert early.replay_bars[0].bar.segment_id == late.replay_bars[0].bar.segment_id


def test_true_owner_start_survives_performance_and_display_clipping(product_cases):
    reader, query, fake = product_cases.paged_reader(prefix_bars=5, frequency="1d")
    clipped = replace(query, since=date(2023, 1, 4), performance_since=date(2023, 1, 5))
    result = reader.load(clipped, fake.as_of)
    assert result.owners[0].start_trading_day == date(2023, 1, 2)
    assert result.replay_bars[0].bar.segment_id == "rb:RB2605:2023-01-02T01:00:00+00:00"
    assert fake.actual_requests[0].since == date(2023, 1, 2)
    assert result.display_window.since == date(2023, 1, 4)
    assert result.performance_window.since == date(2023, 1, 5)
    assert len(result.replay_bars) == 5


def test_as_of_filters_intraday_suffix_before_physical_replay(product_cases):
    reader, query, fake = product_cases.paged_reader(prefix_bars=4)
    cutoff = datetime(2023, 1, 2, 3, tzinfo=UTC)
    result = reader.load(replace(query, as_of=cutoff), fake.as_of)
    assert [bar.bar.bar_end.hour for bar in result.replay_bars] == [2, 3]
    assert fake.physical_page_requests[0].before == cutoff
    assert result.as_of == cutoff


def test_prefix_at_newest_completed_bar_uses_mds_inclusive_page(product_cases):
    reader, query, fake = product_cases.paged_reader(prefix_bars=4)
    cutoff = fake.physical[("RB2605", BarFrequency.H1)][-1].bar_end

    result = reader.load(replace(query, as_of=cutoff), fake.as_of)

    assert len(result.replay_bars) == 4
    assert [request.before for request in fake.inclusive_page_requests] == [cutoff]
    assert fake.physical_page_requests[0].before == cutoff


@pytest.mark.parametrize(
    ("page_number", "mode"),
    [
        (1, SeriesPageCursorMode.EXCLUSIVE),
        (1, None),
        (2, SeriesPageCursorMode.INCLUSIVE),
    ],
)
def test_reader_rejects_corrupt_prefix_cursor_mode_identity(
    product_cases, page_number, mode
):
    """The initial page is inclusive and every continuation is exclusive."""
    reader, query, fake = product_cases.paged_reader(prefix_bars=4, page_size=2)

    def corrupt(_request, page):
        if len(fake.physical_page_requests) == page_number:
            return replace(page, cursor_mode=mode)
        return page

    fake.page_transform = corrupt
    with pytest.raises(NewowProductReadError, match="NEWOW_PREFIX_PAGINATION_INVALID"):
        reader.load(query, fake.as_of)


def test_default_performance_window_resolves_coverage_not_viewport(product_cases):
    reader, query, fake = product_cases.paged_reader(prefix_bars=5, frequency="1d")
    query = replace(
        query, since=date(2023, 1, 4), performance_since=None, performance_through=None
    )
    result = reader.load(query, fake.as_of)
    assert (result.performance_window.since, result.performance_window.through) == (
        date(2023, 1, 2),
        date(2023, 1, 6),
    )
    assert fake.coverage.requests == [
        ("product_start", "rb"),
        ("latest_complete_day", ("rb",)),
    ]
    assert result.display_window.since == date(2023, 1, 4)


def test_default_window_respects_last_complete_day_at_historical_as_of(product_cases):
    reader, query, fake = product_cases.paged_reader(prefix_bars=5, frequency="1d")
    query = replace(query, performance_since=None, performance_through=None)
    result = reader.load(query, datetime(2023, 1, 4, 3, tzinfo=UTC))
    assert result.performance_window.through == date(2023, 1, 3)
    assert all(bar.bar.bar_end <= result.as_of for bar in result.replay_bars)


def test_reference_window_uses_authoritative_session_cutoff_not_request_time(
    product_cases,
):
    reader, _query, fake = product_cases.paged_reader(prefix_bars=5, frequency="1d")
    request_as_of = datetime(2023, 1, 6, 3, tzinfo=UTC)

    resolved = reader.resolve_performance_window(
        "rb", ProductFrequency.DAILY, date(2023, 1, 2), date(2023, 1, 6), request_as_of
    )

    assert resolved.requested_through == date(2023, 1, 6)
    assert resolved.actual_through == date(2023, 1, 5)
    assert resolved.cutoff == datetime(2023, 1, 5, 7, tzinfo=UTC)
    assert resolved.cutoff < request_as_of


def test_reference_window_includes_exact_session_end_and_normalizes_same_instant(
    product_cases,
):
    reader, _query, _fake = product_cases.paged_reader(prefix_bars=5, frequency="1d")
    utc_end = datetime(2023, 1, 6, 7, tzinfo=UTC)
    shanghai_end = datetime.fromisoformat("2023-01-06T15:00:00+08:00")

    first = reader.resolve_performance_window(
        "rb", ProductFrequency.DAILY, date(2023, 1, 2), date(2023, 1, 6), utc_end
    )
    second = reader.resolve_performance_window(
        "rb", ProductFrequency.DAILY, date(2023, 1, 2), date(2023, 1, 6), shanghai_end
    )

    assert first == second
    assert first.actual_through == date(2023, 1, 6)
    assert first.cutoff == utc_end


def test_reference_window_does_not_call_future_requested_days_complete(product_cases):
    reader, _query, _fake = product_cases.paged_reader(prefix_bars=5, frequency="1d")

    resolved = reader.resolve_performance_window(
        "rb",
        ProductFrequency.DAILY,
        date(2023, 1, 2),
        date(2023, 1, 6),
        datetime(2023, 1, 4, 7, tzinfo=UTC),
    )

    assert resolved.actual_through == date(2023, 1, 4)
    assert resolved.cutoff == datetime(2023, 1, 4, 7, tzinfo=UTC)
    assert resolved.complete is False
    assert resolved.reason_code == "NEWOW_REFERENCE_WINDOW_PARTIAL"


@pytest.mark.parametrize(
    "field, value",
    [
        ("product", "RB"),
        ("product", "r钢"),
        ("product", " rb"),
        ("strategy", "unknown"),
        ("frequency", "15m"),
        ("series_kind", "continuous"),
        ("since", datetime(2023, 1, 2, tzinfo=UTC)),
        ("through", date(2023, 1, 1)),
        ("performance_since", None),
        ("performance_through", None),
        ("performance_since", date(2023, 2, 1)),
        ("history_limit", True),
        ("history_limit", 0),
        ("history_limit", 201),
        ("history_before", ""),
        ("history_before", 1),
        ("as_of", datetime(2023, 1, 2)),
    ],
)
def test_query_rejects_invalid_read_intent(product_cases, field, value):
    _, query, fake = product_cases.paged_reader(prefix_bars=3)
    with pytest.raises(ValueError):
        replace(query, **{field: value})
    assert (
        fake.owner_requests == fake.actual_requests == fake.physical_page_requests == []
    )


@pytest.mark.parametrize(
    "change", [{"product": "cu"}, {"as_of": datetime(2100, 1, 1, tzinfo=UTC)}]
)
def test_reader_rejects_inactive_product_or_future_cutoff_before_io(
    product_cases, change
):
    reader, query, fake = product_cases.paged_reader(prefix_bars=3)
    with pytest.raises(ValueError):
        reader.load(replace(query, **change), fake.as_of)
    assert (
        fake.owner_requests == fake.actual_requests == fake.physical_page_requests == []
    )


@pytest.mark.parametrize(
    "field, value",
    [
        ("open", Decimal("102")),
        ("high", Decimal("111")),
        ("low", Decimal("89")),
        ("close", Decimal("102")),
        ("volume", Decimal("11")),
        ("open_interest", Decimal("21")),
        ("turnover", Decimal("1000")),
        ("bar_end", datetime(2023, 1, 2, 2, 1, tzinfo=UTC)),
        ("trading_day", date(2023, 1, 3)),
    ],
)
def test_actual_and_physical_shared_bar_must_match_every_fact(
    product_cases, field, value
):
    reader, query, fake = product_cases.paged_reader(prefix_bars=3)
    bars = fake.physical[("RB2605", BarFrequency.H1)]
    fake.physical[("RB2605", BarFrequency.H1)] = (
        replace(bars[0], **{field: value}),
        *bars[1:],
    )
    with pytest.raises(NewowProductReadError):
        reader.load(query, fake.as_of)


@pytest.mark.parametrize("side", ["actual", "physical"])
@pytest.mark.parametrize(
    "fault", ["reversed", "duplicate", "conflicting_duplicate", "decreasing_day"]
)
def test_rejects_bad_order_and_duplicate_identity(product_cases, side, fault):
    reader, query, fake = product_cases.paged_reader(prefix_bars=3)
    bars = fake.actual[BarFrequency.H1]
    broken = {
        "reversed": tuple(reversed(bars)),
        "duplicate": (bars[0], bars[0], bars[2]),
        "conflicting_duplicate": (
            bars[0],
            replace(bars[0], close=Decimal("102")),
            bars[2],
        ),
        "decreasing_day": (
            bars[0],
            replace(bars[1], trading_day=date(2023, 1, 1)),
            bars[2],
        ),
    }[fault]
    if side == "actual":
        fake.actual[BarFrequency.H1] = broken
    else:
        fake.physical[("RB2605", BarFrequency.H1)] = broken
    with pytest.raises(
        (NewowProductReadError, ActualDominantResearchSegmentIdentityError)
    ):
        reader.load(query, fake.as_of)


@pytest.mark.parametrize(
    "fault",
    [
        "empty_more",
        "stuck",
        "wrong_next",
        "missing_next",
        "oversized",
        "wrong_contract",
    ],
)
def test_malformed_page_fails_at_first_boundary(product_cases, fault):
    reader, query, fake = product_cases.paged_reader(prefix_bars=5, page_size=2)

    def damage(request, page):
        return {
            "empty_more": replace(page, bars=()),
            "stuck": replace(page, next_before=request.before),
            "wrong_next": replace(
                page, next_before=page.bars[0].bar_end - timedelta(microseconds=1)
            ),
            "missing_next": replace(page, next_before=None),
            "oversized": replace(page, bars=page.bars * 1001),
            "wrong_contract": replace(
                page, request_identity={**page.request_identity, "contract": "RB2610"}
            ),
        }[fault]

    fake.page_transform = damage
    with pytest.raises(NewowProductReadError):
        reader.load(query, fake.as_of)
    assert len(fake.physical_page_requests) == 1


def test_overlap_at_strict_before_is_not_silently_deduplicated(product_cases):
    reader, query, fake = product_cases.paged_reader(prefix_bars=5, page_size=2)
    original = fake.physical[("RB2605", BarFrequency.H1)][3]
    fake.page_transform = lambda request, page: (
        replace(page, bars=(*page.bars, replace(original, close=Decimal("102"))))
        if len(fake.physical_page_requests) == 2
        else page
    )
    with pytest.raises(NewowProductReadError):
        reader.load(query, fake.as_of)
    assert len(fake.physical_page_requests) == 2


def test_missing_lifecycle_prefix_does_not_become_a_short_success(product_cases):
    reader, query, fake = product_cases.paged_reader(prefix_bars=12)
    key = ("RB2605", BarFrequency.H1)
    fake.physical[key] = fake.physical[key][1:]
    with pytest.raises(MarketDataError, match="CONTRACT_REPLAY_COVERAGE_UNAVAILABLE"):
        reader.load(query, fake.as_of)


@pytest.mark.parametrize(
    "stage, code",
    [
        ("owner", "MAIN_CONTRACT_MAP_MISSING"),
        ("owner", "MAIN_CONTRACT_MAP_CONFLICT"),
        ("actual", "MAPPED_CONTRACT_DATASET_MISSING"),
        ("actual", "ACTUAL_DOMINANT_WEEKLY_DATASET_ABSENT"),
        ("physical", "DATASET_OR_PARTITION_MISSING"),
        ("physical", "PARTITION_INTEGRITY_INVALID"),
        ("session", "TRADING_SESSION_MISSING"),
        ("lifecycle", "CONTRACT_REPLAY_COVERAGE_UNAVAILABLE"),
    ],
)
def test_mds_classification_and_exception_are_preserved(product_cases, stage, code):
    reader, query, fake = product_cases.paged_reader(prefix_bars=3)
    error = MarketDataError(code)
    fake.failures[stage] = error
    with pytest.raises(MarketDataError) as raised:
        reader.load(query, fake.as_of)
    assert raised.value is error
    assert raised.value.code == code
    assert {r.frequency for r in fake.physical_page_requests} <= {BarFrequency.H1}


def test_raw_frequency_owner_conflict_preserves_shared_loader_classification(
    product_cases,
):
    reader, query, fake = product_cases.paged_reader(prefix_bars=3)
    fake.actual_transform = lambda request, result: replace(
        result,
        resolved_contract_segments=(
            replace(result.resolved_contract_segments[0], contract="RB2610"),
        ),
    )
    with pytest.raises(ActualDominantResearchSegmentIdentityError):
        reader.load(query, fake.as_of)
    assert fake.physical_page_requests == []


def test_orphan_response_owner_is_not_hidden_by_as_of_filter(product_cases):
    reader, query, fake = _weekly_reader(product_cases)
    fake.actual_transform = lambda request, result: replace(
        result,
        resolved_contract_segments=(
            result.resolved_contract_segments[0],
            fake.segments[1],
            result.resolved_contract_segments[1],
        ),
    )
    with pytest.raises(ActualDominantResearchSegmentIdentityError):
        reader.load(query, fake.as_of)
    assert fake.physical_page_requests == []


@pytest.mark.parametrize(
    "field, value",
    [
        ("symbol", "cu"),
        ("frequency", "1d"),
        ("series_kind", "continuous"),
    ],
)
def test_actual_response_cannot_substitute_another_read_identity(
    product_cases, field, value
):
    reader, query, fake = product_cases.paged_reader(prefix_bars=3)
    fake.actual_transform = lambda request, result: replace(
        result, request_identity={**result.request_identity, field: value}
    )
    with pytest.raises(NewowProductReadError, match="NEWOW_DATA_IDENTITY_INVALID"):
        reader.load(query, fake.as_of)
    assert fake.physical_page_requests == []


@pytest.mark.parametrize(
    "window",
    [
        (date(2023, 1, 3), date(2023, 1, 4)),
        (date(2023, 1, 2), date(2023, 1, 4)),
    ],
)
def test_actual_response_cannot_substitute_or_truncate_requested_trading_day_window(
    product_cases, window
):
    """A response for a different bounded day window cannot seed this read."""
    reader, query, fake = product_cases.paged_reader(prefix_bars=3)
    fake.actual_transform = lambda request, result: replace(
        result, requested_trading_day_window=window
    )

    with pytest.raises(NewowProductReadError, match="NEWOW_DATA_IDENTITY_INVALID"):
        reader.load(query, fake.as_of)

    assert fake.physical_page_requests == []


def test_default_window_cannot_shrink_when_coverage_end_loses_calendar_facts(
    product_cases,
):
    reader, query, fake = product_cases.paged_reader(prefix_bars=5, frequency="1d")
    query = replace(query, performance_since=None, performance_through=None)
    del fake.sessions[date(2023, 1, 6)]
    with pytest.raises(NewowProductReadError):
        reader.load(query, fake.as_of)
    assert fake.physical_page_requests == []


def test_request_reuses_selected_context_and_never_keeps_a_resident_cache(
    product_cases,
):
    reader, query, fake = product_cases.paged_reader(
        prefix_bars=3, frequency="1d", context_frequencies=("1w", "1d", "60m", "1w")
    )
    first = reader.load(query, fake.as_of)
    assert set(first.bars_by_frequency) == {"1d", "1w", "60m"}
    assert len(fake.actual_requests) == len(fake.physical_page_requests) == 3
    key = ("RB2605", BarFrequency.D1)
    fake.physical[key] = tuple(
        replace(bar, close=Decimal("103")) for bar in fake.physical[key]
    )
    fake.actual[BarFrequency.D1] = fake.physical[key]
    second = reader.load(query, fake.as_of)
    assert second.replay_bars[-1].bar.close == Decimal("103")
    assert first.replay_bars[-1].bar.close == Decimal("101")
    assert len(fake.actual_requests) == len(fake.physical_page_requests) == 6
    with pytest.raises(TypeError):
        second.bars_by_frequency["1d"] = ()
    with pytest.raises(FrozenInstanceError):
        second.as_of = fake.as_of


def test_reentered_contract_gets_new_segment_with_one_physical_read(product_cases):
    reader, query, fake = _weekly_reader(product_cases)
    fake.segments = (*fake.segments[:2], replace(fake.segments[2], contract="RB2605"))
    fake.physical[("RB2605", BarFrequency.W1)] = fake.physical.pop(
        ("RB2610", BarFrequency.W1)
    )
    fake.expected_physical = dict(fake.physical)
    result = reader.load(query, fake.as_of)
    assert len(fake.physical_page_requests) == 1
    assert [bar.bar.segment_id for bar in result.replay_bars] == [
        "rb:RB2605:2023-01-02T01:00:00+00:00",
        "rb:RB2605:2023-01-11T01:00:00+00:00",
        "rb:RB2605:2023-01-11T01:00:00+00:00",
    ]
    assert [bar.bar.observation_eligible for bar in result.replay_bars] == [
        True,
        False,
        True,
    ]


def test_cancellation_stops_after_current_page_and_is_request_scoped(product_cases):
    _, query, fake = product_cases.paged_reader(prefix_bars=4001)
    reader = NewowProductReader(
        fake,
        coverage=fake.coverage,
        active_products=("rb",),
        now=lambda: fake.as_of,
        cancelled=lambda: bool(fake.physical_page_requests),
    )
    with pytest.raises(NewowProductReadCancelled):
        reader.load(query, fake.as_of)
    assert fake.physical_page_sizes == [2000]
    assert fake.coverage_requests == []


def test_already_cancelled_request_never_reads_market(product_cases):
    _, query, fake = product_cases.paged_reader(prefix_bars=3)
    reader = NewowProductReader(
        fake,
        coverage=fake.coverage,
        active_products=("rb",),
        now=lambda: fake.as_of,
        cancelled=lambda: True,
    )
    with pytest.raises(NewowProductReadCancelled):
        reader.load(query, fake.as_of)
    assert (
        fake.owner_requests == fake.actual_requests == fake.physical_page_requests == []
    )
