"""Typed publication of derived bars into the CanonicalStore."""

from __future__ import annotations

from typing import Protocol, Sequence

from app.data_core.aggregation import AggregationSession
from app.data_core.bar_schema import CanonicalBar
from app.data_core.canonical_store import (
    CANONICAL_MANIFEST_FORMAT_V2,
    PublishExpectation,
    canonical_json_digest,
)
from app.data_core.contracts import (
    BarFrequency,
    BarsResult,
    DatasetKey,
    DatasetOrigin,
    ManifestLineage,
)
from app.data_core.historical_sessions import build_provider_sessions
from app.data_core.rqdata_adapter import ProviderBarBatch, ProviderBarRequest


class _CanonicalStore(Protocol):
    def stage(self, batch: ProviderBarBatch) -> object: ...

    def publish(self, staged: object, expected: PublishExpectation) -> object: ...


class DerivedCanonicalPublisher:
    """Publish a derived DatasetKey with deterministic V2 lineage."""

    def __init__(
        self,
        store: _CanonicalStore,
        *,
        manifest_version: str = "canonical-manifest-v2",
    ) -> None:
        self._store = store
        self._manifest_version = manifest_version

    def __call__(
        self,
        bars: Sequence[CanonicalBar],
        *,
        dataset: DatasetKey,
        source: BarsResult,
        aggregation_sessions: Sequence[AggregationSession],
    ) -> object:
        rows = tuple(bars)
        algorithm = "canonical-aggregate-v1"
        source_digest = canonical_json_digest(
            {
                "algorithm": algorithm,
                "source_datasets": [_dataset_payload(item) for item in source.source_datasets],
                "manifest_digests": list(source.manifest_digests),
                "source_data_versions": list(source.source_data_versions),
                "requested_window": [item.isoformat() for item in source.requested_window],
            }
        )
        quality_digest = canonical_json_digest(
            {
                "source_digest": source_digest,
                "target": _dataset_payload(dataset),
                "bar_count": len(rows),
                "bar_ends": [item.bar_end.isoformat() for item in rows],
            }
        )
        lineage = ManifestLineage(
            origin=DatasetOrigin.PREAGGREGATED_FROM_1M,
            source_frequency=BarFrequency.M1,
            legacy_source_checksum=source_digest,
            quality_evidence_digest=quality_digest,
        )
        lineage.validate_dataset(dataset)
        version_digest = canonical_json_digest(
            {"algorithm": algorithm, "source": source_digest, "quality": quality_digest}
        )
        data_version = f"aggregate-{algorithm}-{version_digest[:24]}"
        request = ProviderBarRequest(
            dataset=dataset,
            start=source.requested_window[0],
            end=source.requested_window[1],
            sessions=build_provider_sessions(
                dataset,
                start=source.requested_window[0],
                end=source.requested_window[1],
                sessions=aggregation_sessions,
            ),
        )
        batch = ProviderBarBatch(request=request, bars=rows, data_version=data_version)
        staged = self._store.stage(batch)
        expectation = PublishExpectation(
            dataset=dataset,
            coverage_start=request.start,
            coverage_end=request.end,
            row_count=len(rows),
            data_version=data_version,
            manifest_version=self._manifest_version,
            manifest_format=CANONICAL_MANIFEST_FORMAT_V2,
            file_checksum=getattr(staged, "file_checksum", None),
            canonical_logical_fingerprint=getattr(
                staged, "canonical_logical_fingerprint", None
            ),
            lineage=lineage,
        )
        return self._store.publish(staged, expectation)


def _dataset_payload(dataset: DatasetKey) -> dict[str, str]:
    return {
        "provider": dataset.provider,
        "dataset_kind": dataset.dataset_kind.value,
        "symbol": dataset.symbol,
        "contract_or_series": dataset.contract_or_series,
        "frequency": dataset.frequency.value,
        "adjustment": dataset.adjustment,
        "schema_version": dataset.schema_version,
    }
