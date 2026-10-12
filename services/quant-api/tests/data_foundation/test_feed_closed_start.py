from datetime import timedelta

import pytest
from app.market_data.aggregation import SessionWindow
from app.market_data.live_market import RedisLiveStore
from app.market_data.market_feed import MarketFeedService, FeedLiveStore
from app.market_data.market_phase import MarketPhase, ProductMarketPhase
from app.market_data.observation_stream import ObservationStream
from tests.data_foundation import test_observation_stream as stream_tests
from tests.data_foundation.test_live_market import FakeDominants, FakePhases, _bar
from tests.data_foundation.test_observation_restore import fixture


@pytest.fixture
def isolated_redis():
    yield from stream_tests.isolated_redis.__wrapped__()


def build(redis, day, *, current_day=None):
    products = ("rb", "jm")
    mapping = {"rb": "RB2505", "jm": "JM2505"}
    window = SessionWindow(
        _bar(1).bar_end + timedelta(days=1),
        _bar(1).bar_end + timedelta(days=1, hours=1),
    )

    def provider():
        raise AssertionError("CLOSED_MUST_NOT_CONNECT_PROVIDER")

    return MarketFeedService(
        source_stream=ObservationStream(redis, kind="source"),
        provider_factory=provider,
        dominant_source=FakeDominants({(p, day): mapping[p] for p in products}),
        phase_resolver=FakePhases(
            {
                p: ProductMarketPhase(
                    p, MarketPhase.CLOSED, current_day, None, window.start
                )
                for p in products
            }
        ),
        coverage_sessions=lambda *_: (window,),
        store=FeedLiveStore(redis),
        operational_products=products,
        authoritative_dominants=True,
    )


def test_closed_start_snapshot_precedes_normal_new_day_and_connects_no_provider(
    isolated_redis,
):
    old = _bar(1).trading_day
    new = old + timedelta(days=1)
    source = ObservationStream(isolated_redis, kind="source")
    completed = ObservationStream(isolated_redis, kind="completed")
    source.initialize("live", old, cursor="0-0")
    completed.initialize("alert", old, cursor="0-0")
    completed.initialize("reference", old, cursor="0-0")
    feed = build(isolated_redis, new, current_day=new)
    prepare = source.prepare_registered_day

    def check_order(day):
        assert RedisLiveStore(isolated_redis).subscriptions(day) == {
            "rb": "RB2505",
            "jm": "JM2505",
        }
        prepare(day)

    source = feed.source_stream
    source.prepare_registered_day = check_order
    assert feed.poll(_bar(1).bar_end + timedelta(days=1)) is None
    assert feed._trading_day == new and feed._contracts == {
        "rb": "RB2505",
        "jm": "JM2505",
    }
    assert feed._provider is None
    for stream, consumer in (
        (source, "live"),
        (completed, "alert"),
        (completed, "reference"),
    ):
        assert stream.registered_day(consumer) == new
        assert stream.cursor(consumer, new) == "0-0"
        assert stream.tail(new) == "0-0"
    assert not isolated_redis.exists(source.key(new))
    assert not isolated_redis.exists(completed.key(new))


def test_unconsumed_previous_prefix_blocks_snapshot_and_new_day(isolated_redis):
    base, _, _, source, completed, _ = fixture(isolated_redis)
    new = base.trading_day + timedelta(days=1)
    before = source.cursor("live", base.trading_day)
    feed = build(isolated_redis, new, current_day=new)
    assert (
        feed.poll(base.bar_end + timedelta(days=1))
        == "OBSERVATION_DAY_BASELINE_UNPROVEN"
    )
    assert source.cursor("live", base.trading_day) == before
    assert source.registered_day("live") == base.trading_day
    assert completed.registered_day("alert") == base.trading_day
    assert RedisLiveStore(isolated_redis).subscriptions(new) is None


def test_closed_nontrading_day_never_infers_future_day(isolated_redis):
    old = _bar(1).trading_day
    source = ObservationStream(isolated_redis, kind="source")
    source.initialize("live", old, cursor="0-0")
    new = old + timedelta(days=1)
    feed = build(isolated_redis, new, current_day=None)
    assert feed.poll(_bar(1).bar_end + timedelta(days=1)) is None
    assert source.registered_day("live") == old
    assert RedisLiveStore(isolated_redis).subscriptions(new) is None


def initialize_previous(redis):
    old = _bar(1).trading_day
    source = ObservationStream(redis, kind="source")
    completed = ObservationStream(redis, kind="completed")
    source.initialize("live", old, cursor="0-0")
    completed.initialize("alert", old, cursor="0-0")
    completed.initialize("reference", old, cursor="0-0")
    return source, completed, old + timedelta(days=1)


def test_existing_different_snapshot_never_overwritten_or_registers(isolated_redis):
    source, completed, new = initialize_previous(isolated_redis)
    store = RedisLiveStore(isolated_redis)
    store.set_subscriptions(new, {"rb": "RB2501", "jm": "JM2501"})
    prior = isolated_redis.dump(store._subscription_key(new))
    assert (
        build(isolated_redis, new, current_day=new).poll(
            _bar(1).bar_end + timedelta(days=1)
        )
        == "OBSERVATION_SUBSCRIPTION_CONFLICT"
    )
    assert isolated_redis.dump(store._subscription_key(new)) == prior
    assert source.registered_day("live") == new - timedelta(days=1)
    assert completed.registered_day("reference") == new - timedelta(days=1)


def test_missing_formal_session_never_creates_subscription_or_registers(isolated_redis):
    source, _, new = initialize_previous(isolated_redis)
    feed = build(isolated_redis, new, current_day=new)
    feed._coverage_session_source = lambda *_: ()
    assert (
        feed.poll(_bar(1).bar_end + timedelta(days=1))
        == "LIVE_RANK1_CATALOG_UNAVAILABLE"
    )
    assert RedisLiveStore(isolated_redis).subscriptions(new) is None
    assert source.registered_day("live") == new - timedelta(days=1)


@pytest.mark.parametrize("kind", ("stream", "identity", "cursor"))
def test_orphan_target_partition_never_receives_new_authority(isolated_redis, kind):
    source, _, new = initialize_previous(isolated_redis)
    if kind == "stream":
        isolated_redis.xadd(source.key(new), {"envelope": "unowned"})
    elif kind == "identity":
        isolated_redis.hset(source.identity_key(new), "unowned", "prior")
    else:
        isolated_redis.set(source.cursor_key("live", new), "0-0")
    assert (
        build(isolated_redis, new, current_day=new).poll(
            _bar(1).bar_end + timedelta(days=1)
        )
        == "OBSERVATION_DAY_BASELINE_UNPROVEN"
    )
    assert RedisLiveStore(isolated_redis).subscriptions(new) is None
    assert source.registered_day("live") == new - timedelta(days=1)
