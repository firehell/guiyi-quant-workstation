"""The persisted proof follows semantic completed inputs, not monthly file bytes."""
from copy import deepcopy
from datetime import date

import pytest

from app.reference_trading.contracts import prove_dependency_append, validate_dependency_advance, manifest_sha256
from app.reference_trading.source_identity import verify_saved_input_prefix
from app.reference_trading.query import QueryConflict


def prefix():
    return {"reader": "newow_product_reader_prefix_v4", "query_since": "2026-10-01",
        "input_fingerprints": ["a" * 64], "calendar_session_effective_fingerprints": ["b" * 64],
        "calendar_session_source_evidence": {"schema_version": "v1", "exchange": "DCE", "symbol": "jm", "since": "2026-10-01", "calendar": [["2026-10-27"]], "sessions": [["2026-10-27", "session"]]},
        "rank1": [["JM2701", "2026-08-19", "2026-10-27"]],
        "boundaries": [], "data_interruptions": [], "lifecycle_owners": [["JM2701", "segment"]],
        "quality_policy": "quality_v1", "market_source_identity": "canonical", "input_policy_version": "v1",
        "formula_versions": ["formula_v1"], "reference_model_version": "model_v1"}


def extension(old):
    new = deepcopy(old)
    new["input_fingerprints"].append("c" * 64)
    new["calendar_session_effective_fingerprints"].append("d" * 64)
    new["rank1"][-1][-1] = "2026-10-28"
    new["calendar_session_source_evidence"]["calendar"].append(["2026-10-28"])
    new["calendar_session_source_evidence"]["sessions"].append(["2026-10-28", "session"])
    return new


def test_semantic_append_and_saved_read_share_exact_old_prefix():
    old = prefix()
    new = extension(old)
    proof = prove_dependency_append(old, new, appended_ranges=("c" * 64,))
    validate_dependency_advance(old, proof)
    verify_saved_input_prefix(new, old, date(2026, 10, 27), frozenset({("JM2701", "segment")}))
    assert "source_evidence_sha256" not in old  # byte integrity belongs to MDS


@pytest.mark.parametrize("field", ["input_fingerprints", "calendar_session_effective_fingerprints", "formula_versions", "quality_policy", "rank1", "calendar_session_source_evidence"])
def test_semantic_append_rejects_changed_prefix_or_effective_metadata(field):
    old = prefix()
    new = extension(old)
    if isinstance(new[field], list):
        new[field][0] = "revised"
    elif isinstance(new[field], dict):
        new[field]["sessions"][0] = ["revised"]
    else:
        new[field] = "revised"
    with pytest.raises(ValueError):
        prove_dependency_append(old, new, appended_ranges=("c" * 64,))


def fusion(base, seq):
    return {**base, "reader": "newow_fusion_saved_sources_v2", "source_reader": base["reader"],
        "input_count": len(base["input_fingerprints"]), "input_sha256": manifest_sha256(base["input_fingerprints"]),
        "source_input_fingerprints": list(base["input_fingerprints"]),
        "query_through": base["rank1"][-1][-1], "query_as_of": base["rank1"][-1][-1] + "T07:00:00+00:00",
        "source_dependencies": [{"stream_id": strategy, "revision_id": "revision", "seq": seq,
            "dependency_digest": str(seq) * 64, "snapshot": str(seq)} for strategy in ("trend", "oscillation")]}


def test_fusion_appends_verified_execution_prefix_as_source_generations_advance():
    old = fusion(prefix(), 2)
    new = fusion(extension(prefix()), 3)
    proof = prove_dependency_append(old, new, appended_ranges=("c" * 64,))
    validate_dependency_advance(old, proof)
    for field, value in (("input_sha256", "f" * 64), ("input_count", 999)):
        with pytest.raises(ValueError):
            prove_dependency_append(old, {**new, field: value}, appended_ranges=("c" * 64,))


def test_v4_reader_cannot_drop_identity_fields():
    saved = prefix()
    current = deepcopy(saved)
    del current["formula_versions"]
    with pytest.raises(QueryConflict):
        verify_saved_input_prefix(saved, current, date(2026, 10, 27), frozenset({("JM2701", "segment")}))


def test_reference_window_uses_wrapped_owned_night_bar_day_and_saved_cutoff():
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from app.reference_trading.persisted_newow import _completed_reference_window
    night = datetime(2026, 10, 29, 14, tzinfo=UTC)
    future = datetime(2026, 10, 30, 7, tzinfo=UTC)
    def wrapped(at, day, owned=True):
        return SimpleNamespace(bar=SimpleNamespace(bar_end=at, trading_day=day, observation_eligible=owned))
    read = SimpleNamespace(replay_bars=(wrapped(night, date(2026, 10, 30)),
        wrapped(future, date(2026, 10, 30)), wrapped(future, date(2026, 11, 2), False)))
    assert _completed_reference_window(read, night) == (night, date(2026, 10, 30))
    assert _completed_reference_window(read, future) == (future, date(2026, 10, 30))


def test_intraday_provenance_only_scope_still_detects_market_progress():
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from app.reference_trading.persisted_newow import _completed_reference_window
    endpoint = datetime(2026, 10, 30, 7, tzinfo=UTC)
    scope = SimpleNamespace(replay_bars=(), frequency='60m',
        sources={'60m': SimpleNamespace(bar_end=endpoint), '1d': SimpleNamespace(bar_end=datetime(2026, 11, 2, 7, tzinfo=UTC))})
    assert _completed_reference_window(scope, endpoint) == (endpoint, None)


def packed(manifest):
    from app.reference_trading.packed_fingerprints import pack_fingerprints
    value = deepcopy(manifest)
    value['reader'] = 'newow_product_reader_prefix_v5'
    for key in ('input_fingerprints', 'calendar_session_effective_fingerprints'):
        value[key] = pack_fingerprints(value[key])
    return value


def test_v5_partial_block_append_and_legacy_read_do_not_relabel_saved_proof():
    from app.reference_trading.fingerprint_proof import fingerprint_count
    legacy = prefix()
    before = deepcopy(legacy)
    old, new = packed(legacy), packed(extension(legacy))
    proof = prove_dependency_append(old, new, appended_ranges=('c' * 64,))
    validate_dependency_advance(old, proof)
    verify_saved_input_prefix(new, old, date(2026, 10, 27), frozenset({('JM2701', 'segment')}))
    verify_saved_input_prefix(legacy, old, date(2026, 10, 27), frozenset({('JM2701', 'segment')}))
    assert legacy == before and fingerprint_count(new['input_fingerprints']) == 2
    with pytest.raises(ValueError):
        prove_dependency_append(legacy, new, appended_ranges=('c' * 64,))


def test_v5_changed_old_leaf_rejects_append_even_inside_partial_block():
    old = packed(prefix())
    changed = extension(prefix())
    changed['input_fingerprints'][0] = 'f' * 64
    with pytest.raises(ValueError):
        prove_dependency_append(old, packed(changed), appended_ranges=('c' * 64,))


def test_v5_fusion_advances_only_same_format_and_verified_dependency_generations():
    from app.reference_trading.packed_fingerprints import pack_fingerprints
    def upgraded(base, seq):
        value = fusion(base, seq)
        value['reader'] = 'newow_fusion_saved_sources_v3'
        value['source_reader'] = 'newow_product_reader_prefix_v5'
        for key in ('input_fingerprints', 'source_input_fingerprints', 'calendar_session_effective_fingerprints'):
            value[key] = pack_fingerprints(value[key])
        value['input_sha256'] = manifest_sha256(value['input_fingerprints'])
        return value
    old, new = upgraded(prefix(), 2), upgraded(extension(prefix()), 3)
    proof = prove_dependency_append(old, new, appended_ranges=('c' * 64,))
    validate_dependency_advance(old, proof)
