from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.reference_trading.persisted_newow import _CompletePresentation, PersistedNewowReference
from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.newow_fusion import PersistedFusionComparison, fusion_source_stream_identity
from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity
from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.product_identity import build_newow_stream_identity
from guiyi_quant.newow.reference_pricing import GAP_FILL_PRICE_POLICY
from app.reference_trading.query import QueryConflict, _encode
from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy


PRODUCT_IDENTITY = build_product_identity("rb", "trend", "60m")
TREND = build_newow_stream_identity(PRODUCT_IDENTITY)
FUSION = build_fusion_stream_identity("rb", "60m")
OSCILLATION = fusion_source_stream_identity(FUSION, ProductStrategy.OSCILLATION)


def _saved(monkeypatch, latest_seq=7, *, reference_price_policy=None):
    monkeypatch.setattr("app.reference_trading.page_material_query.select_page_material", lambda *_args, **_kw: None)
    cutoff = datetime(2026, 9, 10, 7, tzinfo=UTC)
    manifest = {
        "query_since": "2025-01-01", "query_through": "2026-09-10",
        "query_as_of": cutoff.isoformat(), "reader": "newow_product_reader_intraday_v3",
    }
    complete = _CompletePresentation(
        {"performance_since": "2025-01-01", "performance_through": "2026-09-10",
         "reference_cutoff": cutoff.isoformat(), "reference_input_sha256": "a" * 64},
        {"saved-1": {"reference_trade_id": "public-1"}},
        "ready-status", (TREND.stream_id, "revision", 7),
    )
    saved = PersistedNewowReference(lambda: None, cache=SimpleNamespace(
        get=lambda *_args, **_kwargs: complete,
    ), reference_price_policy=reference_price_policy)
    saved._manifest = lambda *_args: (TREND, manifest)
    saved._query = SimpleNamespace(
        stream_for=lambda identity: {"stream_id": identity.stream_id},
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
    delivery = saved.section(request, None, PRODUCT_IDENTITY, reader, "a" * 64, None, resolved)
    assert delivery.value.payload["items"] == [{"reference_trade_id": "public-1"}]
    assert delivery.value.payload["next_before"] == "next"
    assert delivery.value.saved_generation == (TREND.stream_id, "revision", 7)


def test_persisted_page_rejects_old_saved_generation_even_when_cached(monkeypatch):
    saved, request, reader, resolved = _saved(monkeypatch, latest_seq=8)
    with pytest.raises(QueryConflict, match="SOURCE_GENERATION_CONFLICT"):
        saved.section(request, None, PRODUCT_IDENTITY, reader, "a" * 64, None, resolved)


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
    fusion_manifest = {"query_since": "2025-01-01", "source_dependencies": [
        {"stream_id": "trend", "revision_id": "trend-revision", "seq": 7},
        {"stream_id": "oscillation", "revision_id": "oscillation-revision", "seq": 7},
    ]}
    saved._manifest = lambda stream_id, *_args: (
        (TREND, base_manifest) if stream_id == TREND.stream_id else (FUSION, fusion_manifest)
    )
    saved._query.summary = lambda stream_id, **_kwargs: (
        {"revision_id": "revision", "seq": 7} if stream_id == TREND.stream_id
        else {"revision_id": "fusion-revision", "seq": 8, "snapshot": "new-fusion-snapshot"})
    with pytest.raises(QueryConflict, match="SOURCE_GENERATION_CONFLICT"):
        saved.section(request, None, PRODUCT_IDENTITY, reader, "a" * 64, None, resolved)


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
        for stream, revision in ((TREND.stream_id, "revision"), (OSCILLATION.stream_id, "osc-revision"))
    ]
    fusion_manifest = {"query_since": "2025-01-01", "source_dependencies": dependencies}
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
        (FUSION, fusion_manifest) if stream_id == FUSION.stream_id else (TREND, base_manifest)
    )
    saved._query.stream_for = lambda identity: {
        "stream_id": identity.stream_id,
        "active_revision_id": "osc-revision" if identity == OSCILLATION else "revision",
        "latest_seq": 7,
    }
    saved._query.summary = lambda stream_id, **_kwargs: (
        {"revision_id": "fusion-revision", "seq": 8, "snapshot": "fusion-snapshot"}
        if stream_id == FUSION.stream_id else
        {"revision_id": "osc-revision" if stream_id == OSCILLATION.stream_id else "revision", "seq": 7})
    proofs = []
    monkeypatch.setattr(PersistedFusionComparison, "verify_saved_source",
                        lambda *args, **kwargs: proofs.append((args, kwargs)))
    delivery = saved.section(request, None, PRODUCT_IDENTITY, reader, "a" * 64, None, resolved)
    assert delivery.value.payload["fusion_comparison"]["reference_revision"] == revision
    assert len(proofs) == 1 and proofs[0][1]["reader"] is reader


def test_gap_page_rejects_legacy_cursor_and_cached_generation(monkeypatch):
    saved, request, reader, resolved = _saved(monkeypatch, reference_price_policy=GAP_FILL_PRICE_POLICY)
    candidate = build_product_identity("rb", "trend", "60m", reference_price_policy=GAP_FILL_PRICE_POLICY)
    candidate_stream = build_newow_stream_identity(candidate)
    routes = []

    def exact_stream(identity):
        routes.append(identity)
        return {"stream_id": identity.stream_id}

    saved._query.stream_for = exact_stream
    request.history_before = _encode({
        "kind": "record_trades",
        "snapshot": _encode({"kind": "snapshot", "stream": TREND.stream_id}),
    })
    saved._query.trades = lambda *_args, **_kw: pytest.fail("legacy cursor reached the candidate query")
    with pytest.raises(QueryConflict, match="CURSOR_CONFLICT"):
        saved.section(request, None, candidate, reader, "a" * 64, None, resolved)
    assert routes == [candidate_stream]

    cached = saved._cache.get(None, None)
    delivery = SimpleNamespace(value=SimpleNamespace(
        payload=cached.payload, saved_generation=cached.generation,
    ))
    with pytest.raises(QueryConflict, match="SOURCE_GENERATION_CONFLICT"):
        saved.validate_cached_generation(delivery)


def test_lagging_compact_reference_verifies_saved_source_before_reporting_update(monkeypatch):
    saved, request, reader, resolved = _saved(monkeypatch)
    resolved.cutoff += timedelta(days=1)
    resolved.actual_through += timedelta(days=1)
    with pytest.raises(QueryConflict, match="REFERENCE_UPDATE_PENDING") as exc:
        saved.section(request, None, PRODUCT_IDENTITY, reader, "a" * 64, None, resolved)
    assert exc.value.reference_status == {
        "reason": "REFERENCE_UPDATE_PENDING",
        "result_through": "2026-09-10T07:00:00+00:00",
        "market_through": "2026-09-11T07:00:00+00:00",
    }
    def reject(*_args):
        raise QueryConflict("SOURCE_IDENTITY_UNVERIFIED")
    monkeypatch.setattr("app.reference_trading.persisted_newow.verify_saved_compact_source", reject)
    with pytest.raises(QueryConflict, match="SOURCE_IDENTITY_UNVERIFIED"):
        saved.section(request, None, PRODUCT_IDENTITY, reader, "a" * 64, None, resolved)
