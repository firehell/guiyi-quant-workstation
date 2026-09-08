"""Real reader/resolver and service over isolated MDS facts; no external services."""

from dataclasses import replace

import pytest

from app.market_data.domain import BarFrequency, ResolvedContractSegment
from app.market_data.newow.product_service import NewowProductService, ProductServiceQuery
from app.market_data.newow.snapshot_cache import SnapshotCache


def setup_service(product_cases, frequency="1d", count=520, cache=None):
    reader, _, facts = product_cases.paged_reader(prefix_bars=count, frequency=frequency)
    # Exact flat average avoids unrelated floating-band transitions in the
    # main-rise formula; this fixture exercises navigation, not formula policy.
    facts.physical = {key: tuple(replace(bar, close=bar.open) for bar in bars)
                      for key, bars in facts.physical.items()}
    facts.expected_physical = dict(facts.physical)
    facts.actual = {period: tuple(replace(bar, close=bar.open) for bar in bars)
                    for period, bars in facts.actual.items()}
    service = NewowProductService(
        lambda _context, _cancelled: reader, cache=cache, now=lambda: facts.as_of
    )
    return service, reader, facts


def older_request(request, result):
    return replace(request, since=None, through=None, chart_before=None,
                   chart_older_window=result.chart.value.next_older_window,
                   snapshot_token=result.meta.snapshot_token)


@pytest.mark.parametrize("frequency", ["1d", "1w", "60m"])
@pytest.mark.parametrize("strategy", ["trend", "oscillation", "main_rise"])
def test_default_window_can_end_before_authoritative_history(product_cases, frequency, strategy):
    service, _, facts = setup_service(product_cases, frequency)
    request = ProductServiceQuery("rb", strategy, frequency, as_of=facts.as_of)
    first = service.query(request)
    assert first.chart.value.next_before is None
    assert first.chart.value.next_older_window is not None
    older = service.query(older_request(request, first))
    assert older.meta.snapshot_token == first.meta.snapshot_token
    assert older.chart.value.bars[-1].bar.bar_end < first.chart.value.bars[0].bar.bar_end
    assert older.chart.value.next_older_window is None
    assert older.reference.delivery == "not_requested"


def test_hourly_exhausts_all_pages_before_issuing_older_window(product_cases):
    service, _, facts = setup_service(product_cases, "60m")
    request = ProductServiceQuery("rb", "trend", "60m", as_of=facts.as_of, chart_limit=3)
    first = service.query(request)
    assert first.chart.value.next_before is not None
    assert first.chart.value.next_older_window is None
    window = first.chart.value.actual_window
    last = service.query(replace(request, since=window.since, through=window.through,
                                chart_before=first.chart.value.next_before,
                                snapshot_token=first.meta.snapshot_token))
    assert len(last.chart.value.bars) == 1
    assert last.chart.value.next_before is None
    assert last.chart.value.next_older_window is not None
    older = service.query(older_request(request, last))
    assert older.chart.value.bars[-1].bar.bar_end < last.chart.value.bars[0].bar.bar_end


def test_disjoint_physical_windows_revalidate_authoritative_anchor(product_cases):
    service, reader, facts = setup_service(product_cases, count=1040)
    bars = facts.physical[("RB2605", BarFrequency.D1)]
    split = 540
    facts.segments = (
        ResolvedContractSegment("RB2605", facts.segments[0].start_trading_day, bars[split-1].trading_day),
        ResolvedContractSegment("RB2609", bars[split].trading_day, bars[-1].trading_day),
    )
    facts.physical = {("RB2605", BarFrequency.D1): bars[:split],
                      ("RB2609", BarFrequency.D1): bars[split:]}
    facts.expected_physical = dict(facts.physical)
    request = ProductServiceQuery("rb", "trend", "1d", as_of=facts.as_of)
    first = service.query(request)
    facts.physical_page_requests.clear()
    older = service.query(older_request(request, first))
    assert {bar.bar.physical_contract for bar in first.chart.value.bars} == {"RB2609"}
    assert {bar.bar.physical_contract for bar in older.chart.value.bars} == {"RB2605"}
    assert older.meta.snapshot_token == first.meta.snapshot_token
    assert {page.contract for page in facts.physical_page_requests} == {"RB2605", "RB2609"}


@pytest.mark.parametrize("mode", ["tamper", "strategy", "limit", "expired", "restart", "changed", "evicted"])
def test_older_cursor_rejects_unverified_generation(product_cases, mode):
    clock = [0.0]
    cache = SnapshotCache(now=lambda: clock[0], max_entries=1)
    service, reader, facts = setup_service(product_cases, cache=cache)
    request = ProductServiceQuery("rb", "trend", "1d", as_of=facts.as_of)
    first = service.query(request)
    following = older_request(request, first)
    if mode == "tamper":
        following = replace(following, chart_older_window=following.chart_older_window + "x")
    elif mode == "strategy":
        following = replace(following, strategy="main_rise")
    elif mode == "limit":
        following = replace(following, chart_limit=499)
    elif mode == "expired":
        clock[0] = 301
    elif mode == "restart":
        service = NewowProductService(lambda *_: reader, now=lambda: facts.as_of)
    elif mode == "evicted":
        service.query(replace(request, strategy="oscillation"))
    elif mode == "changed":
        key = ("RB2605", BarFrequency.D1)
        bars = facts.physical[key]
        changed = replace(bars[-1], close=bars[-1].close + 1)
        facts.physical[key] = (*bars[:-1], changed)
        facts.expected_physical = dict(facts.physical)
        facts.actual[BarFrequency.D1] = (*facts.actual[BarFrequency.D1][:-1], changed)
    with pytest.raises(ValueError, match="NEWOW_(CHART_CURSOR|SNAPSHOT_GENERATION_CONFLICT)"):
        service.query(following)


@pytest.mark.parametrize("cache", [SnapshotCache(enabled=False), SnapshotCache(max_entry_bytes=100)])
def test_unretained_results_do_not_offer_older_cursor(product_cases, cache):
    service, _, facts = setup_service(product_cases, cache=cache)
    result = service.query(ProductServiceQuery("rb", "trend", "1d", as_of=facts.as_of))
    assert result.meta.snapshot_token is None
    assert result.chart.value.next_older_window is None


def test_explicit_window_does_not_escape_user_range(product_cases):
    service, _, facts = setup_service(product_cases)
    result = service.query(ProductServiceQuery("rb", "trend", "1d", as_of=facts.as_of,
        since=facts.coverage.through, through=facts.coverage.through))
    assert result.chart.value.next_older_window is None


@pytest.mark.parametrize("frequency", ["1d", "1w", "60m"])
def test_multiple_windows_and_pages_end_at_authoritative_start(product_cases, frequency):
    service, _, facts = setup_service(product_cases, frequency, count=72)
    request = ProductServiceQuery("rb", "trend", frequency, as_of=facts.as_of, chart_limit=11)
    seen = []
    for _ in range(30):
        result = service.query(request)
        bars = result.chart.value.bars
        if bars and seen:
            assert bars[-1].bar.bar_end < seen[0]
        seen = [bar.bar.bar_end for bar in bars] + seen
        if result.chart.value.next_before is not None:
            window = result.chart.value.actual_window
            request = replace(request, since=window.since, through=window.through,
                chart_before=result.chart.value.next_before, chart_older_window=None,
                snapshot_token=result.meta.snapshot_token)
        elif result.chart.value.next_older_window is not None:
            request = older_request(request, result)
        else:
            break
    else:
        pytest.fail("bounded history never exhausted")
    assert seen == [bar.bar_end for bar in facts.actual[BarFrequency(frequency)]]


def test_related_cursor_state_is_atomically_bounded_with_cached_results():
    cache = SnapshotCache(max_entry_bytes=4096)
    token = cache.put("identity", ("chart",), "accepted", proof={"bar|a": "v1"})
    assert token
    assert cache.put("identity", ("chart",), "new", token=token,
        proof={"bar|a": "v1", "bar|b": "v2"},
        related_values={("older_window", "cursor"): "x" * 5000}) is None
    assert cache.get_by_token(token, "identity", ("chart",)) == "accepted"
    assert cache.get_by_token(token, "identity", ("older_window", "cursor")) is None
    assert cache.token_is_compatible(token, "identity", {"bar|a": "v1", "bar|b": "other"})


def test_failed_older_availability_read_does_not_cache_partial_navigation(product_cases, monkeypatch):
    from app.market_data.newow.product_reader import NewowProductReadError

    service, reader, facts = setup_service(product_cases)
    original = reader.resolve_older_chart_window
    failed = [False]

    def read(*args):
        if not failed[0]:
            failed[0] = True
            raise NewowProductReadError("NEWOW_COMPLETE_TRADING_DAY_MISSING")
        return original(*args)

    monkeypatch.setattr(reader, "resolve_older_chart_window", read)
    request = ProductServiceQuery("rb", "trend", "1d", as_of=facts.as_of)
    with pytest.raises(NewowProductReadError):
        service.query(request)
    retried = service.query(request)
    assert retried.chart.value.next_older_window is not None
