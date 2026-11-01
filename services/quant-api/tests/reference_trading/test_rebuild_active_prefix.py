"""A proven Newow prefix stays readable during a format-only rebuild."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256

import pytest

from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.inputs import HistoricalInputBar, HistoricalInputSnapshot
from app.reference_trading.packed_fingerprints import pack_fingerprints
from app.reference_trading.planning import (
    HistoricalReferencePlanner, HistoricalReferenceRequest,
    HistoricalStreamRequest, WorkBudget,
)
from app.reference_trading.query import HistoricalReferenceQuery, QueryConflict
from app.reference_trading.service import (
    HistoricalReferenceService, NewowHistoricalPayload, ServiceInterrupted,
)
from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
from tests.newow.product_fixtures import ProductCases
from tests.reference_trading.test_bootstrap import _repository
from tests.reference_trading.test_historical_integration import _newow_stream


class _FormatReader:
    def __init__(self):
        self.case = ProductCases().closed(frequency="60m")
        self.identity = build_product_identity("rb", ProductStrategy.TREND, ProductFrequency.HOURLY)
        self.stream = _newow_stream(ProductStrategy.TREND, ProductFrequency.HOURLY)
        self.reader_version = 4
        self.changed_price = False

    def _snapshot(self, request):
        source = self.case.bars
        if self.changed_price:
            first = source[0]
            revised = replace(first.bar, close=first.bar.close + 1)
            source = (replace(first, bar=revised), *source[1:])
        bars = tuple(
            HistoricalInputBar(
                item.bar.bar_end, item.bar.trading_day,
                item.bar.physical_contract, item.bar.segment_id,
                item.calculation_segment_id or item.bar.segment_id,
                item.bar.close,
                sha256(f"{index}:{item.bar.close}".encode()).hexdigest(),
                NewowHistoricalPayload(self.identity, item),
            )
            for index, item in enumerate(source)
        )
        leaves = [item.fingerprint for item in bars]
        calendar = [sha256(item.bar_end.isoformat().encode()).hexdigest()
                    for item in bars]
        proof = (lambda values: list(values)) if self.reader_version == 4 else pack_fingerprints
        manifest = {
            "reader": f"newow_product_reader_prefix_v{self.reader_version}",
            "query_since": request.since.isoformat(),
            "input_fingerprints": proof(leaves),
            "calendar_session_effective_fingerprints": proof(calendar),
            "calendar_session_source_evidence": {
                "schema_version": "v1", "exchange": "SHFE", "symbol": "rb",
                "since": request.since.isoformat(), "calendar": [], "sessions": [],
            },
            "rank1": [[bars[0].physical_contract, bars[0].trading_day.isoformat(),
                       bars[-1].trading_day.isoformat()]],
            "boundaries": [], "data_interruptions": [],
            "lifecycle_owners": [[bars[0].physical_contract, bars[0].owner_segment_id]],
            "quality_policy": self.identity.input_quality_policy.value,
            "market_source_identity": "canonical:owned-fixture",
            "input_policy_version": "owned-fixture-v1",
            "formula_versions": list(request.identity.formula_versions),
            "reference_model_version": request.identity.reference_model_version,
        }
        return HistoricalInputSnapshot(
            request.identity, bars[0].trading_day, bars[-1].bar_end,
            bars, manifest, manifest_sha256(manifest), 4096,
        )

    def plan_stream(self, request):
        return self._snapshot(request)

    def load_stream(self, request, *, expected_source_token):
        snapshot = self._snapshot(request)
        assert snapshot.source_token == expected_source_token
        return snapshot

    def revalidate(self, request, *, expected_source_token):
        return self._snapshot(request).source_token == expected_source_token


def _plan(reader, operation):
    bars = reader.case.bars
    request = HistoricalStreamRequest(
        reader.stream, bars[0].bar.trading_day, bars[-1].bar.trading_day,
        bars[-1].bar.bar_end + timedelta(seconds=1),
    )
    wanted = HistoricalReferenceRequest(
        operation, (request,), WorkBudget(1, 100, 30, 100_000), 1,
    )
    return HistoricalReferencePlanner(reader, now=lambda: request.as_of).plan(wanted)


def _stop_after_first_commit(stage, _context):
    if stage == "committed":
        raise ServiceInterrupted("stop")


def test_format_only_rebuild_keeps_old_active_until_candidate_publish():
    reader = _FormatReader()
    repository = _repository()
    initial = _plan(reader, "build")
    built = HistoricalReferenceService(repository, reader).execute(initial, initial.plan_hash)
    assert built.status == "completed", [(item.status, item.reason) for item in built.streams]
    old = built.streams[0].snapshot
    assert old is not None
    reader.reader_version = 5
    migration = _plan(reader, "rebuild")
    partial = HistoricalReferenceService(
        repository, reader, after_batch=_stop_after_first_commit,
    ).rebuild(migration, migration.plan_hash)
    assert partial.status == "partial"
    assert repository.read_state(reader.stream.stream_id).revision_id == old.revision_id
    assert repository.read_state(reader.stream.stream_id, old.revision_id).revision_status == "active"
    query = HistoricalReferenceQuery(repository._session_factory)
    summary = query.summary(
        reader.stream.stream_id,
        since=migration.streams[0].request.since,
        through=migration.streams[0].request.through,
        cutoff=migration.streams[0].request.as_of,
    )
    assert summary["revision_id"] == old.revision_id
    resumed = HistoricalReferenceService(repository, reader).resume(
        migration, partial.streams[0].resume_token, migration.plan_hash,
    )
    assert resumed.status == "completed"
    assert repository.read_state(reader.stream.stream_id, old.revision_id).revision_status == "superseded"


def test_changed_prefix_invalidates_old_active_before_rebuild():
    reader = _FormatReader()
    repository = _repository()
    initial = _plan(reader, "build")
    built = HistoricalReferenceService(repository, reader).execute(initial, initial.plan_hash)
    assert built.status == "completed", [(item.status, item.reason) for item in built.streams]
    old = built.streams[0].snapshot
    assert old is not None
    reader.reader_version = 5
    reader.changed_price = True
    changed = _plan(reader, "rebuild")
    partial = HistoricalReferenceService(
        repository, reader, after_batch=_stop_after_first_commit,
    ).rebuild(changed, changed.plan_hash)
    assert partial.status in {"partial", "failed"}
    assert repository.read_state(reader.stream.stream_id, old.revision_id).revision_status == "invalid"
    query = HistoricalReferenceQuery(repository._session_factory)
    with pytest.raises(QueryConflict):
        query.summary(
            reader.stream.stream_id,
            since=changed.streams[0].request.since,
            through=changed.streams[0].request.through,
            cutoff=changed.streams[0].request.as_of,
        )
