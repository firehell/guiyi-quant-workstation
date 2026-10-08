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
