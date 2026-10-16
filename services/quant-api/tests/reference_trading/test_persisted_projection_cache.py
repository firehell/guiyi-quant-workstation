from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.reference_trading.persisted_newow import _CompletePresentation, PersistedNewowReference
from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.newow_fusion import PersistedFusionComparison
from app.reference_trading.query import QueryConflict, _encode
from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy


def _saved(monkeypatch, latest_seq=7):
    cutoff = datetime(2026, 9, 10, 7, tzinfo=UTC)
    manifest = {
        "query_since": "2025-01-01", "query_through": "2026-09-10",
        "query_as_of": cutoff.isoformat(), "reader": "newow_product_reader_intraday_v3",
    }
    complete = _CompletePresentation(
        {"performance_since": "2025-01-01", "performance_through": "2026-09-10",
         "reference_cutoff": cutoff.isoformat(), "reference_input_sha256": "a" * 64},
        {"saved-1": {"reference_trade_id": "public-1"}},
        "ready-status", ("stream", "revision", 7),
    )
    saved = PersistedNewowReference(lambda: None, cache=SimpleNamespace(
        get=lambda *_args, **_kwargs: complete,
    ))
    saved._manifest = lambda *_args: (None, manifest)
    saved._query = SimpleNamespace(
        streams=lambda **_kwargs: [{"stream_id": "stream"}],
        trades=lambda *_args, **_kwargs: {
            "snapshot": _encode({"kind": "snapshot", "since": "2025-01-01"}),
            "revision_id": "revision", "seq": 7,
            "items": [{"reference_trade_id": "saved-1"}], "next_cursor": "next",
        },
        summary=lambda *_args, **_kwargs: {"revision_id": "revision", "seq": latest_seq},
    )
    saved._reference_facts = lambda *_args: pytest.fail("complete presentation recomputed")
    monkeypatch.setattr("app.reference_trading.persisted_newow.verify_saved_compact_source",
                        lambda *_args: None)
    request = SimpleNamespace(product="rb", strategy=ProductStrategy.TREND,
                              frequency=ProductFrequency.HOURLY, history_before=None,
                              history_limit=50, include_fusion=False, fusion_before=None)
    reader = SimpleNamespace(historical_source_evidence=lambda **_kwargs: {})
    resolved = SimpleNamespace(requested_since=date(2025, 1, 1),
        requested_through=date(2026, 9, 10), actual_through=date(2026, 9, 10),
        cutoff=cutoff)
    return saved, request, reader, resolved


def test_persisted_page_reuses_complete_projection_after_fresh_source_and_generation(monkeypatch):
    saved, request, reader, resolved = _saved(monkeypatch)
    delivery = saved.section(request, None, None, reader, "a" * 64, None, resolved)
    assert delivery.value.payload["items"] == [{"reference_trade_id": "public-1"}]
    assert delivery.value.payload["next_before"] == "next"
    assert delivery.value.saved_generation == ("stream", "revision", 7)


def test_persisted_page_rejects_old_saved_generation_even_when_cached(monkeypatch):
    saved, request, reader, resolved = _saved(monkeypatch, latest_seq=8)
    with pytest.raises(QueryConflict, match="SOURCE_GENERATION_CONFLICT"):
        saved.section(request, None, None, reader, "a" * 64, None, resolved)


def test_persisted_page_rejects_stale_fusion_with_unchanged_base_generation(monkeypatch):
    saved, request, reader, resolved = _saved(monkeypatch)
    request.include_fusion = True
    original = saved._cache.get(None, None)
    stale = _CompletePresentation(
        {**original.payload, "fusion_comparison": {
            "product": "rb", "frequency": "60m", "reference_revision": "old-fusion-revision",
        }}, original.items_by_saved_id, original.status, original.generation,
    )
    saved._cache = SimpleNamespace(get=lambda *_args, **_kwargs: stale)
    base_manifest = {
        "query_since": "2025-01-01", "query_through": "2026-09-10",
        "query_as_of": resolved.cutoff.isoformat(),
        "reader": "newow_product_reader_intraday_v3",
    }
    fusion_manifest = {"source_dependencies": [
        {"stream_id": "trend", "revision_id": "trend-revision", "seq": 7},
        {"stream_id": "oscillation", "revision_id": "oscillation-revision", "seq": 7},
    ]}
    saved._manifest = lambda stream_id, *_args: (
        None, base_manifest if stream_id == "stream" else fusion_manifest)
    saved._query.streams = lambda *, strategy, **_kwargs: [{
        "stream_id": "stream" if strategy == "newow_trend" else "fusion",
    }]
    saved._query.summary = lambda stream_id, **_kwargs: (
        {"revision_id": "revision", "seq": 7} if stream_id == "stream"
        else {"revision_id": "fusion-revision", "seq": 8, "snapshot": "new-fusion-snapshot"})
    with pytest.raises(QueryConflict, match="SOURCE_GENERATION_CONFLICT"):
        saved.section(request, None, None, reader, "a" * 64, None, resolved)


def test_persisted_fusion_cache_hit_rechecks_saved_source_and_dependencies(monkeypatch):
    saved, request, reader, resolved = _saved(monkeypatch)
    request.include_fusion = True
    original = saved._cache.get(None, None)
    base_manifest = {
        "query_since": "2025-01-01", "query_through": "2026-09-10",
        "query_as_of": resolved.cutoff.isoformat(),
        "reader": "newow_product_reader_intraday_v3",
    }
    dependencies = [
        {"stream_id": stream, "revision_id": revision, "seq": 7,
         "dependency_digest": manifest_sha256(base_manifest)}
        for stream, revision in (("stream", "revision"), ("oscillation", "osc-revision"))
    ]
    fusion_manifest = {"source_dependencies": dependencies}
    revision = manifest_sha256({
        "snapshot": "fusion-snapshot", "dependencies": dependencies,
        "record_since": (resolved.requested_through - timedelta(days=364)).isoformat(),
        "record_through": resolved.requested_through.isoformat(),
    })
    cached = _CompletePresentation(
        {**original.payload, "fusion_comparison": {
            "product": "rb", "frequency": "60m", "reference_revision": revision,
        }}, original.items_by_saved_id, original.status, original.generation,
    )
    saved._cache = SimpleNamespace(get=lambda *_args, **_kwargs: cached)
    saved._manifest = lambda stream_id, *_args: (
        None, fusion_manifest if stream_id == "fusion" else base_manifest)
    saved._query.streams = lambda *, strategy, **_kwargs: [{
        "stream_id": {"newow_trend": "stream", "newow_oscillation": "oscillation",
                      "newow_dual_fusion": "fusion"}[strategy],
        "active_revision_id": "osc-revision" if strategy == "newow_oscillation" else "revision",
        "latest_seq": 7,
    }]
    saved._query.summary = lambda stream_id, **_kwargs: (
        {"revision_id": "fusion-revision", "seq": 8, "snapshot": "fusion-snapshot"}
        if stream_id == "fusion" else
        {"revision_id": "osc-revision" if stream_id == "oscillation" else "revision", "seq": 7})
    proofs = []
    monkeypatch.setattr(PersistedFusionComparison, "verify_saved_source",
                        lambda *args, **kwargs: proofs.append((args, kwargs)))
    delivery = saved.section(request, None, None, reader, "a" * 64, None, resolved)
    assert delivery.value.payload["fusion_comparison"]["reference_revision"] == revision
    assert len(proofs) == 1 and proofs[0][1]["reader"] is reader
