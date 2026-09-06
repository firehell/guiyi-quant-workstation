from app.market_data.newow.snapshot_cache import SnapshotCache


def test_section_parameter_key_prevents_cross_component_or_cursor_hits():
    cache = SnapshotCache(max_entries=4, max_bytes=1024, max_entry_bytes=512)
    first = cache.put("facts", ("auxiliary", "main_force_control"), {"value": 1}, 64)
    assert first is not None
    assert cache.get("facts", ("auxiliary", "main_force_control")) == {"value": 1}
    assert cache.get("facts", ("auxiliary", "up_down_energy")) is None
    assert cache.get("facts", ("reference", "cursor-a", 50)) is None


def test_verified_sections_expand_one_common_fact_entry():
    cache = SnapshotCache(max_entries=1, max_bytes=1024, max_entry_bytes=512)
    token = cache.put("facts", ("chart", 500), "chart", 64)
    expanded = cache.put("facts", ("auxiliary", "cup_handle"), "cup", 64)
    assert token == expanded
    assert cache.get_by_token(token, "facts", ("chart", 500)) == "chart"
    assert cache.get_by_token(token, "facts", ("auxiliary", "cup_handle")) == "cup"


def test_lru_eviction_and_oversized_bypass_return_nullable_token():
    cache = SnapshotCache(max_entries=2, max_bytes=128, max_entry_bytes=80)
    first = cache.put("one", ("chart",), 1, 50)
    second = cache.put("two", ("chart",), 2, 50)
    assert first and second
    assert cache.get("one", ("chart",)) == 1
    third = cache.put("three", ("chart",), 3, 50)
    assert third
    assert cache.get("two", ("chart",)) is None
    assert cache.put("huge", ("chart",), object(), 81) is None


def test_expired_or_disabled_cache_never_claims_a_snapshot():
    clock = [0.0]
    cache = SnapshotCache(now=lambda: clock[0], ttl_seconds=5)
    token = cache.put("facts", ("chart",), "ok", 1)
    assert token
    clock[0] = 6.0
    assert cache.get_by_token(token, "facts", ("chart",)) is None
    disabled = SnapshotCache(enabled=False)
    assert disabled.put("facts", ("chart",), "ok", 1) is None
