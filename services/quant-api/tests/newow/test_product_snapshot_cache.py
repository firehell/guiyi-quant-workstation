from app.market_data.newow.snapshot_cache import SnapshotCache


def test_section_parameter_key_prevents_cross_component_or_cursor_hits():
    cache = SnapshotCache(max_entries=4, max_bytes=16384, max_entry_bytes=8192)
    first = cache.put("facts", ("auxiliary", "main_force_control"), {"value": 1})
    assert first is not None
    assert cache.get("facts", ("auxiliary", "main_force_control")) == {"value": 1}
    assert cache.get("facts", ("auxiliary", "up_down_energy")) is None
    assert cache.get("facts", ("reference", "cursor-a", 50)) is None


def test_verified_sections_expand_one_common_fact_entry():
    cache = SnapshotCache(max_entries=1, max_bytes=16384, max_entry_bytes=8192)
    token = cache.put("facts", ("chart", 500), "chart")
    expanded = cache.put("facts", ("auxiliary", "cup_handle"), "cup")
    assert token == expanded
    assert cache.get_by_token(token, "facts", ("chart", 500)) == "chart"
    assert cache.get_by_token(token, "facts", ("auxiliary", "cup_handle")) == "cup"


def test_single_entry_budget_counts_all_retained_sections():
    cache = SnapshotCache(max_entries=4, max_bytes=10000, max_entry_bytes=4096)
    token = cache.put("facts", ("chart",), "c" * 2000)
    assert token is not None

    assert cache.put("facts", ("reference",), "r" * 2000) is None
    assert cache.get("facts", ("chart",)) == "c" * 2000
    assert cache.get("facts", ("reference",)) is None


def test_token_requires_equal_values_for_overlapping_dependency_facts():
    cache = SnapshotCache(max_entries=4, max_bytes=16384, max_entry_bytes=8192)
    token = cache.put("identity", ("chart",), "chart", proof={"bar|a": "value-1"})
    assert token is not None
    assert cache.token_is_compatible(
        token, "identity", {"bar|a": "value-1", "bar|b": "value-2"}
    )
    assert not cache.token_is_compatible(token, "identity", {"bar|a": "revised"})
    assert not cache.token_is_compatible(token, "identity", {"unrelated": "value"})


def test_token_rejects_owner_boundary_or_adapter_revision():
    cache = SnapshotCache(max_entries=4, max_bytes=16384, max_entry_bytes=8192)
    proof = {
        "bar|a": "same-bar",
        "boundary|switch": "owner-v1",
        "version|product": "adapter-v1",
    }
    token = cache.put("identity", ("chart",), "chart", proof=proof)
    assert token is not None

    assert not cache.token_is_compatible(
        token,
        "identity",
        {**proof, "boundary|switch": "owner-v2"},
    )
    assert not cache.token_is_compatible(
        token,
        "identity",
        {**proof, "version|product": "adapter-v2"},
    )


def test_lru_eviction_and_oversized_bypass_return_nullable_token():
    cache = SnapshotCache(max_entries=2, max_bytes=16384, max_entry_bytes=4096)
    first = cache.put("one", ("chart",), 1)
    second = cache.put("two", ("chart",), 2)
    assert first and second
    assert cache.get("one", ("chart",)) == 1
    third = cache.put("three", ("chart",), 3)
    assert third
    assert cache.get("two", ("chart",)) is None
    assert cache.put("huge", ("chart",), "x" * 5000) is None


def test_expired_or_disabled_cache_never_claims_a_snapshot():
    clock = [0.0]
    cache = SnapshotCache(now=lambda: clock[0], ttl_seconds=5)
    token = cache.put("facts", ("chart",), "ok")
    assert token
    clock[0] = 6.0
    assert cache.get_by_token(token, "facts", ("chart",)) is None
    disabled = SnapshotCache(enabled=False)
    assert disabled.put("facts", ("chart",), "ok") is None


def test_proof_payload_cannot_bypass_entry_or_global_memory_budget():
    for budgets in ({"max_entry_bytes": 4096}, {"max_bytes": 4096}):
        cache = SnapshotCache(**budgets)
        assert cache.put(
            "facts", ("chart",), "small",
            proof={"bar|a": "x" * 100_000},
        ) is None
        assert cache.get("facts", ("chart",)) is None


def test_rejected_proof_extension_does_not_change_values_proof_or_expiry():
    clock = [0.0]
    cache = SnapshotCache(max_entry_bytes=4096, now=lambda: clock[0], ttl_seconds=5)
    token = cache.put("facts", ("chart",), "o" * 2000, proof={"bar|a": "v1"})
    assert token
    clock[0] = 4.0
    assert cache.put(
        "facts", ("reference",), "n" * 2000, token=token,
        proof={"bar|a": "v1", "bar|b": "b"},
    ) is None
    assert cache.get_by_token(token, "facts", ("chart",)) == "o" * 2000
    assert cache.get("facts", ("reference",)) is None
    assert cache.token_is_compatible(token, "facts", {"bar|a": "v1", "bar|b": "changed"})
    clock[0] = 5.0
    assert cache.get_by_token(token, "facts", ("chart",)) is None


def test_rejected_revision_keeps_previous_token_and_cached_result():
    cache = SnapshotCache(max_entry_bytes=4096)
    token = cache.put("facts", ("chart",), "old", proof={"bar|a": "v1"})
    assert token
    assert cache.put(
        "facts", ("chart",), "new",
        proof={"bar|a": "revised" * 100_000},
    ) is None
    assert cache.get_by_token(token, "facts", ("chart",)) == "old"
    assert cache.token_is_compatible(token, "facts", {"bar|a": "v1"})


def test_global_eviction_counts_proofs_even_with_tiny_section_values():
    cache = SnapshotCache(max_entries=4, max_bytes=6000, max_entry_bytes=5000)
    first = cache.put("one", ("chart",), 1, proof={"bar|a": "a" * 2500})
    second = cache.put("two", ("chart",), 2, proof={"bar|b": "b" * 2500})
    assert first and second
    assert cache.get_by_token(first, "one", ("chart",)) is None
    assert cache.get_by_token(second, "two", ("chart",)) == 2
    third = cache.put("three", ("chart",), 3, proof={"bar|c": "c" * 2500})
    assert third
    assert cache.get_by_token(second, "two", ("chart",)) is None
    assert cache.get_by_token(third, "three", ("chart",)) == 3


def test_metadata_and_proof_growth_are_charged_before_an_update():
    cache = SnapshotCache(max_entry_bytes=4096)
    token = cache.put("facts", ("chart",), "old", proof={"bar|a": "v1"})
    assert token
    for key, proof in (
        (("reference", "cursor" * 1000), {"bar|a": "v1"}),
        (("reference",), {"bar|a": "v1", "bar|b": "x" * 10000}),
    ):
        assert cache.put("facts", key, "new", token=token, proof=proof) is None
        assert cache.get_by_token(token, "facts", ("chart",)) == "old"
        assert cache.token_is_compatible(token, "facts", {"bar|a": "v1", "bar|b": "other"})


def test_repeated_eviction_keeps_actual_index_capacity_inside_global_budget():
    import sys

    cache = SnapshotCache(max_entries=1, max_bytes=1300, max_entry_bytes=1300)
    for i in range(30):
        token = cache.put(str(i), ("chart",), i)
        assert token
        entry = cache._entries[str(i)]
        # Lower bound from the actual retained containers and their owned fields,
        # independent of the cache's own accounting function.
        retained = sum(sys.getsizeof(item) for item in (
            cache._entries, cache._tokens, entry, entry.fact_key, entry.token,
            entry.expires_at, entry.values, entry.proof, entry.retained_bytes,
            next(iter(entry.values)), "chart", i,
        ))
        assert retained <= 1300
