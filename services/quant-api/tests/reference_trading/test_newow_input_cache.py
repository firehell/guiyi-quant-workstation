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
