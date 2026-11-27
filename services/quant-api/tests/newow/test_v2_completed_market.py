from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.market_data.aggregation import AggregationError, SessionWindow
from app.market_data.domain import CanonicalBar
from app.market_data.live_market import LiveBarObservation, _bar_payload, live_bar_channel
from app.market_data.newow.v2_completed import (
    Admission,
    CompletedStream,
    HistoricalAvailability,
    MarketWindow,
    admit,
    completed_bucket,
    from_historical_bar,
    from_observation,
    next_executable_minute,
)
from app.market_data.newow.v2_scope import Deployment, Scope, validate_scope
from app.market_data.observation_stream import ObservationEnvelope
from guiyi_quant.newow.decision_adapter import V2Strategy


SHANGHAI = ZoneInfo("Asia/Shanghai")
DAY = date(2026, 1, 5)
D = Decimal


def clock(hour, minute=0, second=0, day=5):
    return datetime(2026, 1, day, hour, minute, second, tzinfo=SHANGHAI)


def bar(end, price="100", day=DAY):
    return CanonicalBar(end, day, D(price), D(price), D(price), D(price), D(1), None, D(2))


def window(frequency, *, sessions=None, day=DAY, completed_week=None, owner="FU2603"):
    return MarketWindow(
        "fu", owner, f"fu:{owner}", "rank1-proof", day, frequency,
        sessions or (
            SessionWindow(clock(9), clock(10, 15)),
            SessionWindow(clock(10, 30), clock(11, 30)),
            SessionWindow(clock(13, 30), clock(15)),
        ),
        completed_week=completed_week,
    )


def historical(raw, market_window, *, delay=timedelta(seconds=2), revision="canon-1", warmup=False):
    return from_historical_bar(
        raw, market_window, revision=revision, source_ref="source-1",
        availability=HistoricalAvailability(raw.bar_end + delay, "frozen-clock-v1"),
        as_of=raw.bar_end + delay, warmup=warmup,
    )


def observation(raw, market_window, *, eligible=True, confirmed=True):
    available = raw.bar_end + timedelta(seconds=2)
    contract = market_window.contract
    return ObservationEnvelope(
        f"{raw.trading_day}:{contract}:{market_window.frequency.value}:{raw.bar_end.isoformat()}",
        raw.trading_day, available, live_bar_channel("fu", market_window.frequency.value),
        _bar_payload(raw, contract=contract), eligible, stream_id="1-0",
        raw_received_at=available, confirmed_at=available if confirmed else None,
    )


def test_session_buckets_preserve_short_h1_and_block_a_missing_tail():
    market = window("60m")
    assert market.endpoints == tuple(clock(h, m) for h, m in (
        (10, 0), (10, 15), (11, 30), (14, 30), (15, 0),
    ))
    tail = tuple(LiveBarObservation(bar(clock(10, m)), "FU2603") for m in range(1, 16))
    assert completed_bucket(tail, market, through=clock(10, 15)).volume == 15
    with pytest.raises(AggregationError, match="SOURCE_1M_INCOMPLETE"):
        completed_bucket(tail[:-1], market, through=clock(10, 15))
    with pytest.raises(ValueError, match="V2_MARKET_ENDPOINT_INVALID"):
        completed_bucket((LiveBarObservation(bar(clock(12)), "FU2603"),), market, through=clock(12))


def test_night_bar_uses_trading_day_and_bucket_is_physical():
    sessions = (SessionWindow(clock(21, day=4), clock(2, 30)),)
    market = window("5m", sessions=sessions)
    incoming = tuple(LiveBarObservation(bar(clock(0, minute)), "FU2603") for minute in range(1, 6))
    completed = completed_bucket(incoming, market, through=clock(0, 5))
    assert completed.trading_day == DAY
    assert historical(completed, market).trading_day == DAY
    with pytest.raises(ValueError, match="V2_MARKET_TRADING_DAY_CONFLICT"):
        completed_bucket((LiveBarObservation(bar(clock(0, 1), day=date(2026, 1, 4)), "FU2603"), *incoming[1:]),
                         market, through=clock(0, 5))
    with pytest.raises(ValueError, match="V2_MARKET_OWNER_CONFLICT"):
        completed_bucket((LiveBarObservation(incoming[0].bar, "FU2605"), *incoming[1:]),
                         market, through=clock(0, 5))


def test_day_and_complete_holiday_week_are_as_of_safe():
    daily = window("1d")
    with pytest.raises(ValueError, match="V2_MARKET_ENDPOINT_INVALID"):
        historical(bar(clock(11, 30)), daily)
    weekly = window("1w")
    with pytest.raises(ValueError, match="V2_MARKET_ENDPOINT_INVALID"):
        historical(bar(clock(15)), weekly)
    published = window("1w", completed_week=(DAY, clock(15) + timedelta(microseconds=1)))
    assert historical(bar(clock(15)), published).bar_end == clock(15)
    with pytest.raises(ValueError, match="V2_MARKET_INPUT_NOT_AVAILABLE"):
        historical(bar(clock(15)), published, delay=timedelta(0))


def test_forward_requires_completion_and_preserves_original_time():
    market = window("5m")
    raw = bar(clock(9, 5))
    with pytest.raises(ValueError, match="V2_MARKET_OBSERVATION_INVALID"):
        from_observation(observation(raw, market, confirmed=False), market, generation="g1",
                         as_of=clock(9, 6))
    item = from_observation(observation(raw, market), market, generation="g1", as_of=clock(9, 6))
    assert item.payload.observed_at == item.payload.confirmed_at == clock(9, 5, 2)
    assert historical(raw, market).payload.observed_at is None
    assert item.payload.bar.bar.close == raw.close


def test_admission_duplicate_conflict_gap_and_late_are_distinct():
    market = window("5m")
    first = historical(bar(clock(9, 5)), market)
    state = CompletedStream()
    state, result = admit(state, first, expected=clock(9, 5))
    assert result is Admission.ACCEPTED
    assert admit(state, first, expected=clock(9, 10)) == (state, Admission.DUPLICATE)
    changed = historical(bar(clock(9, 5), "101"), market)
    blocked, result = admit(state, changed, expected=clock(9, 10))
    assert result is Admission.CONFLICT
    later = historical(bar(clock(9, 15)), market)
    assert admit(blocked, later, expected=clock(9, 15))[1] is Admission.BLOCKED
    assert admit(state, later, expected=clock(9, 10))[1] is Admission.GAP
    fresh = historical(bar(clock(9, 10)), market)
    assert admit(state, fresh, expected=clock(9, 10), fresh=False)[1] is Admission.LATE
    revised = historical(bar(clock(9, 10)), market, revision="canon-2")
    assert admit(state, revised, expected=clock(9, 10))[1] is Admission.SOURCE_CONFLICT


def test_strict_successor_open_and_config_capacity():
    assert next_executable_minute(clock(9, 5, 2), (clock(9, 5), clock(9, 6))) == clock(9, 6)
    assert next_executable_minute(clock(9, 5), (clock(9, 5),)) is None
    products = tuple(f"p{i}" for i in range(71))
    deployments = tuple(Deployment(product, V2Strategy.TREND, "5m", draining=index == 0)
                        for index, product in enumerate(products[:21]))
    accepted = Scope("v2", products[:70], deployments[:20])
    assert validate_scope(accepted, supported=products, retired=(), isolated=True) == accepted
    for candidate in (
        Scope("over-market", products, deployments[:20]),
        Scope("over-deployments", products[:70], deployments),
        Scope("duplicate", products[:70], (deployments[0], deployments[0])),
    ):
        with pytest.raises(ValueError):
            validate_scope(candidate, supported=products, retired=(), isolated=True)
    with pytest.raises(ValueError):
        validate_scope(accepted, supported=products, retired=products[:1], isolated=True)
    with pytest.raises(ValueError):
        validate_scope(accepted, supported=products, retired=(), isolated=False)
    formal = Scope("formal", products[:60], deployments[:16])
    assert validate_scope(formal, supported=products[:60], retired=(), isolated=False) == formal


def test_forward_must_prove_freshness_without_assuming_a_budget():
    market = window("5m")
    raw = bar(clock(9, 5))
    item = from_observation(observation(raw, market), market, generation="g1", as_of=clock(9, 6))
    with pytest.raises(ValueError, match="V2_MARKET_FRESHNESS_REQUIRED"):
        admit(CompletedStream(), item, expected=raw.bar_end)
    assert admit(CompletedStream(), item, expected=raw.bar_end, fresh=True)[1] is Admission.ACCEPTED


def test_published_daily_input_reuses_forward_incremental_reader():
    from dataclasses import replace
    from app.market_data.newow.v2_completed import PublishedObservation, read_next_published_input
    from guiyi_quant.newow.product_contracts import ProductFrequency
    from guiyi_quant.newow.product_identity import InputQualityPolicy

    market = window("1d")
    historical_item = historical(bar(clock(15)), market)
    calls = []
    bar_sha = "a" * 64
    product_bar = replace(historical_item.payload.bar, source_bar_sha256=bar_sha)

    class Reader:
        def forward_incremental_bar(self, **request):
            calls.append(request)
            return product_bar, InputQualityPolicy.V1

    observed = clock(18)
    request = dict(
        after=clock(15, day=4), generation="g1",
        publication=PublishedObservation("catalog-published-input", bar_sha, observed),
        prior_owner_segment_id="fu:FU2603", prior_calculation_segment_id="fu:FU2603",
    )
    item = read_next_published_input(Reader(), market, as_of=observed, **request)
    replay = read_next_published_input(Reader(), market, as_of=clock(18, 1), **request)
    assert replay == item
    with_proof = read_next_published_input(Reader(), market, as_of=observed, verified_lifecycle=True, **request)
    assert with_proof.payload.verified_lifecycle
    assert all(call["as_of"] == observed for call in calls)
    with pytest.raises(ValueError, match="V2_MARKET_PUBLICATION_CONFLICT"):
        conflicting = PublishedObservation("catalog-published-input", "b" * 64, observed)
        read_next_published_input(Reader(), market, as_of=observed, **(request | {"publication": conflicting}))
    assert calls[0]["frequency"] is ProductFrequency.DAILY
    assert calls[0]["after"] == clock(15, day=4)
    assert item.payload.available_at == item.payload.observed_at == observed
    assert item.payload.bar == product_bar
    assert item.fingerprint != historical_item.fingerprint


def test_history_reads_a_sealed_mds_window_once_for_multiple_bars():
    from app.market_data.newow.product_query import ProductReadWindow
    from app.market_data.newow.product_reader import ProductReadSet
    from app.market_data.newow.v2_completed import iter_historical_inputs
    from guiyi_quant.newow.product_contracts import ProductFrequency

    market = window("5m")
    inputs = tuple(historical(bar(end), market) for end in market.endpoints[:3])
    read_window = ProductReadWindow(DAY, DAY)
    read = ProductReadSet(
        ProductFrequency.FIVE_MINUTE,
        {ProductFrequency.FIVE_MINUTE: tuple(item.payload.bar for item in inputs)},
        (), (), read_window, read_window, {}, clock(9, 16),
    )
    calls = []

    def resolve(product_bar):
        calls.append(product_bar.bar.bar_end)
        return market

    output = tuple(iter_historical_inputs(
        read, revision="canon-1", as_of=read.as_of, window_for=resolve,
        availability_for=lambda product_bar: HistoricalAvailability(
            product_bar.bar.bar_end + timedelta(seconds=2), "frozen-clock-v1",
        ),
    ))
    assert calls == [clock(9, 5)]
    assert tuple(item.bar_end for item in output) == tuple(item.bar_end for item in inputs)
    assert all(item.payload.observed_at is None for item in output)


def test_frozen_week_checks_the_mds_authoritative_end_and_availability():
    from types import SimpleNamespace

    from guiyi_quant.newow.product_identity import build_segment_id

    market = window("1w")
    owner_start = market.sessions[0].start
    segment = build_segment_id("fu", "FU2603", owner_start)

    class Authority:
        def dominant_segment_for_day(self, symbol, day):
            assert symbol == "fu" and day == DAY
            return SimpleNamespace(contract="FU2603", start_trading_day=DAY)

        def session_windows(self, *, symbol, trading_day):
            assert symbol == "fu" and trading_day == DAY
            return market.sessions

        def completed_calendar_week(self, *, symbol, week_monday, as_of):
            assert symbol == "fu" and week_monday == DAY
            cutoff = clock(15) + timedelta(microseconds=1)
            return (DAY, cutoff) if as_of >= cutoff else None

    request = dict(product="fu", contract="FU2603", owner_segment_id=segment,
                   owner_ref="explicit-captured-owner", trading_day=DAY, frequency="1w")
    assert MarketWindow.from_mds(Authority(), **request, as_of=clock(15)).endpoints == ()
    assert MarketWindow.from_mds(Authority(), **request, as_of=clock(15, 1)).endpoints == (clock(15),)
    with pytest.raises(ValueError, match="V2_MARKET_OWNER_CONFLICT"):
        MarketWindow.from_mds(Authority(), **(request | {"owner_segment_id": "other"}), as_of=clock(15, 1))


def test_quality_break_starts_a_new_calculation_segment_in_historical_stream():
    from app.market_data.newow.product_query import ProductReadWindow
    from app.market_data.newow.product_reader import ProductReadSet
    from app.market_data.newow.v2_completed import iter_historical_inputs
    from guiyi_quant.newow.product_contracts import DataInterruption, ProductFrequency
    from guiyi_quant.newow.product_identity import InputQualityPolicy, build_calculation_segment_id

    daily = ProductFrequency.DAILY
    first = window("1d")
    later_day = date(2026, 1, 7)
    later = window("1d", day=later_day, sessions=(SessionWindow(clock(9, day=7), clock(15, day=7)),))
    prices = (
        historical(bar(clock(15)), first).payload.bar,
        historical(bar(clock(15, day=7), day=later_day), later).payload.bar,
    )
    gap = DataInterruption("fu", daily, "FU2603", "fu:FU2603", date(2026, 1, 6), clock(15, day=6), "price-gap")
    read_window = ProductReadWindow(DAY, later_day)
    read = ProductReadSet(
        daily, {daily: prices}, (), (), read_window, read_window, {}, clock(18, day=7),
        data_interruptions_by_frequency={daily: (gap,)}, input_quality_policy=InputQualityPolicy.DAILY_V2,
    )
    start, boundary, after = iter_historical_inputs(
        read, revision="canon-1", as_of=read.as_of,
        window_for=lambda item: first if item.bar.trading_day == DAY else later,
        availability_for=lambda item: HistoricalAvailability(item.bar.bar_end, "daily-fixture"),
    )
    assert boundary == gap
    assert start.calculation_segment_id == build_calculation_segment_id(
        "fu:FU2603", policy=InputQualityPolicy.DAILY_V2,
    )
    assert after.calculation_segment_id == build_calculation_segment_id(
        "fu:FU2603", gap.effective_at, InputQualityPolicy.DAILY_V2,
    )


def test_rollover_subscriptions_are_counted_separately_from_product_capacity():
    from app.market_data.newow.v2_scope import physical_subscription_count

    scope = Scope("candidate", ("fu", "rb"), (Deployment("fu", "trend", "5m", draining=True),))
    assert physical_subscription_count(scope, {"fu": ("FU2603", "FU2605"), "rb": ("RB2701",)}) == 3
    with pytest.raises(ValueError, match="V2_SCOPE_SUBSCRIPTIONS_INVALID"):
        physical_subscription_count(scope, {"fu": ("RB2603",), "rb": ("RB2701",)})


def test_older_unverifiable_replay_and_regressed_availability_block_the_stream():
    market = window("5m")
    first = historical(bar(clock(9, 5)), market, delay=timedelta(minutes=7))
    state, _ = admit(CompletedStream(), first, expected=first.bar_end)
    second = historical(bar(clock(9, 10)), market)
    assert admit(state, second, expected=second.bar_end)[1] is Admission.LATE
    valid_second = historical(bar(clock(9, 10)), market, delay=timedelta(minutes=3))
    state, _ = admit(state, valid_second, expected=valid_second.bar_end)
    altered = historical(bar(clock(9, 5), "101"), market, delay=timedelta(minutes=7))
    assert admit(state, altered, expected=clock(9, 15), previous_fingerprint=first.fingerprint)[1] is Admission.CONFLICT
    proposed, reason = admit(state, altered, expected=clock(9, 15))
    assert proposed.blocked and reason is Admission.UNVERIFIED_REPLAY


def test_warmup_only_session_cannot_be_promoted_by_the_caller():
    from dataclasses import replace

    market = replace(window("5m"), warmup_only=True)
    raw = bar(clock(9, 5))
    assert not historical(raw, market).payload.bar.bar.observation_eligible
    with pytest.raises(ValueError, match="V2_MARKET_OBSERVATION_INVALID"):
        from_observation(observation(raw, market), market, generation="g1", as_of=clock(9, 6))


def test_appending_future_quality_gap_does_not_revoke_past_input_identity():
    from dataclasses import replace

    from app.market_data.newow.product_query import ProductReadWindow
    from app.market_data.newow.product_reader import ProductReadSet
    from app.market_data.newow.v2_completed import iter_historical_inputs
    from guiyi_quant.newow.product_contracts import DataInterruption, LifecycleReplayEvidence, ProductFrequency

    daily = ProductFrequency.DAILY
    market = window("1d")
    prefix = historical(bar(clock(15)), market).payload.bar
    read_window = ProductReadWindow(DAY, date(2026, 1, 6))
    proof = LifecycleReplayEvidence(
        "fu", daily, "FU2603", "fu:FU2603", clock(15), clock(15), 1, "a" * 64,
        "market_data_service:canonical_v2", clock(15),
    )
    read = ProductReadSet(
        daily, {daily: (prefix,)}, (), (), read_window, read_window, {}, clock(18),
        lifecycle_evidence_by_frequency={daily: (proof,)},
    )
    future_gap = DataInterruption(
        "fu", daily, "FU2603", "fu:FU2603", date(2026, 1, 6), clock(15, day=6), "price-gap",
    )
    extended = replace(read, lifecycle_evidence_by_frequency={}, as_of=clock(18, day=6),
                       data_interruptions_by_frequency={daily: (future_gap,)})
    options = dict(
        revision="canon-1", window_for=lambda _: market,
        availability_for=lambda _: HistoricalAvailability(clock(15), "daily-fixture"),
    )
    original, = iter_historical_inputs(read, as_of=read.as_of, **options)
    past, later = iter_historical_inputs(extended, as_of=extended.as_of, **options)
    assert original == past
    assert later == future_gap
    verified = options | {"verified_prefix_for": lambda item: item.bar.bar_end == clock(15)}
    proved, = iter_historical_inputs(read, as_of=read.as_of, **verified)
    proved_past, _ = iter_historical_inputs(extended, as_of=extended.as_of, **verified)
    assert proved == proved_past
    assert proved.payload.verified_lifecycle


@pytest.mark.parametrize("false_value", ("false", 0))
def test_admission_rejects_non_boolean_freshness(false_value):
    market = window("5m")
    raw = bar(clock(9, 5))
    item = from_observation(observation(raw, market), market, generation="g1", as_of=clock(9, 6))
    with pytest.raises(ValueError, match="V2_MARKET_FRESHNESS_INVALID"):
        admit(CompletedStream(), item, expected=raw.bar_end, fresh=false_value)
