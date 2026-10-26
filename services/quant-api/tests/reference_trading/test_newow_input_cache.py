from datetime import UTC, datetime, timedelta
from app.reference_trading.input_cache import NewowInputCache


def test_shared_inputs_only_live_for_one_unit_and_exact_context():
    cache = NewowInputCache()
    count = []
    def read():
        count.append(1)
        return object()
    now = datetime(2026, 10, 8, tzinfo=UTC)
    cache.begin(now)
    key = ("rb", "60m", now, "owner", "quality")
    first = cache.read(key, read)
    assert cache.read(key, read) is first and len(count) == 1
    assert cache.read((*key, "other-watermark"), read) is not first
    cache.end()
    cache.begin(now + timedelta(seconds=5))
    assert cache.read(key, read) is not first


def test_failed_read_is_never_cached():
    cache = NewowInputCache()
    cache.begin(datetime(2026, 10, 8, tzinfo=UTC))
    import pytest
    with pytest.raises(ValueError):
        cache.read(("source",), lambda: (_ for _ in ()).throw(ValueError("SOURCE_BUSY")))
    assert cache.read(("source",), lambda: "ready") == "ready"


def test_terminal_snapshot_is_frozen_once_across_three_strategies_and_refreshed_next_unit():
    from types import SimpleNamespace
    now = datetime(2026, 10, 8, 15, tzinfo=UTC)
    calls=[]
    def snapshot(*args):
        calls.append(args)
        return object()
    cache=NewowInputCache()
    reader=cache.live_reader(SimpleNamespace(newow_completed_observation_snapshot=snapshot))
    cache.begin(now)
    first=reader.newow_completed_observation_snapshot('rb-60m',now-timedelta(hours=1),now)
    assert reader.newow_completed_observation_snapshot('rb-60m',now-timedelta(hours=1),now) is first
    assert len(calls)==1
    cache.end()
    cache.begin(now)
    assert reader.newow_completed_observation_snapshot('rb-60m',now-timedelta(hours=1),now) is not first
    assert len(calls)==2


def test_canonical_cache_shares_market_input_across_strategies_and_reader_instances():
    from types import SimpleNamespace
    from guiyi_quant.newow.product_identity import InputQualityPolicy
    cache = NewowInputCache()
    now = datetime(2026, 10, 27, tzinfo=UTC)
    cache.begin(now)
    identity = SimpleNamespace(futures_adaptation_version="adaptation", frequency="1d")
    calls = []
    def incremental(**kwargs):
        calls.append(kwargs)
        return object()
    values = [cache.canonical_reader(SimpleNamespace(_input_quality_policy=InputQualityPolicy.DAILY_V2,
        forward_incremental_bar=incremental), identity).forward_incremental_bar(
            product="rb", frequency="1d", after=now-timedelta(days=1), as_of=now) for _ in range(3)]
    assert values[0] is values[1] is values[2] and len(calls) == 1


def test_canonical_cache_never_shares_different_actual_policy_or_after():
    from types import SimpleNamespace
    from guiyi_quant.newow.product_identity import InputQualityPolicy
    cache = NewowInputCache()
    now = datetime(2026, 10, 27, tzinfo=UTC)
    cache.begin(now)
    identity = SimpleNamespace(futures_adaptation_version="adaptation", frequency="1d")
    calls = []
    def reader(policy):
        return SimpleNamespace(_input_quality_policy=policy,
            forward_incremental_bar=lambda **kwargs: calls.append((policy, kwargs)) or object())
    daily = cache.canonical_reader(reader(InputQualityPolicy.DAILY_V2), identity)
    legacy = cache.canonical_reader(reader(InputQualityPolicy.V1), identity)
    kwargs = dict(product="rb", frequency="1d", after=now-timedelta(days=1), as_of=now)
    first = daily.forward_incremental_bar(**kwargs)
    assert legacy.forward_incremental_bar(**kwargs) is not first
    assert daily.forward_incremental_bar(**{**kwargs, "after": now-timedelta(days=2)}) is not first
    assert len(calls) == 3


def test_missing_unknown_or_changed_reader_policy_cannot_reuse_prior_snapshot():
    from types import SimpleNamespace
    from guiyi_quant.newow.product_identity import InputQualityPolicy
    cache = NewowInputCache()
    now = datetime(2026, 10, 27, tzinfo=UTC)
    cache.begin(now)
    identity = SimpleNamespace(futures_adaptation_version="adaptation", frequency="1d")
    calls = []
    def read(**kwargs):
        calls.append(kwargs)
        return object()
    underlying = SimpleNamespace(forward_incremental_bar=read)
    reader = cache.canonical_reader(underlying, identity)
    kwargs = dict(product="rb", frequency="1d", after=now-timedelta(days=1), as_of=now)
    assert reader.forward_incremental_bar(**kwargs) is not reader.forward_incremental_bar(**kwargs)
    underlying._input_quality_policy = "unknown-policy"
    assert reader.forward_incremental_bar(**kwargs) is not reader.forward_incremental_bar(**kwargs)
    underlying._input_quality_policy = InputQualityPolicy.DAILY_V2
    known = reader.forward_incremental_bar(**kwargs)
    assert reader.forward_incremental_bar(**kwargs) is known
    underlying._input_quality_policy = InputQualityPolicy.V1
    assert reader.forward_incremental_bar(**kwargs) is not known
    assert len(calls) == 6


def test_initial_load_without_incremental_watermark_still_bypasses_cache():
    from types import SimpleNamespace
    cache = NewowInputCache()
    cache.begin(datetime(2026, 10, 27, tzinfo=UTC))
    calls = []
    reader = SimpleNamespace(load=lambda *args: calls.append(args) or object(),
        forward_incremental_bar=lambda **_: (_ for _ in ()).throw(AssertionError("initial load must not use incremental seam")))
    wrapped = cache.canonical_reader(reader, SimpleNamespace(futures_adaptation_version="adaptation"))
    assert wrapped.load("query", "now") is not wrapped.load("query", "now")
    assert len(calls) == 2
