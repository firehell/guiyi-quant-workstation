from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.data_core.consumer_identity import (
    CanonicalConsumerInput,
    build_canonical_consumer_input,
    reconstruct_bar_query,
)
from app.data_core.contracts import (
    BarFrequency,
    BarQuery,
    BarsResult,
    DatasetKey,
    DatasetKind,
)


def _source(contract: str) -> DatasetKey:
    return DatasetKey(
        provider="rqdata",
        dataset_kind=DatasetKind.ACTUAL_DOMINANT,
        symbol="jm",
        contract_or_series=contract,
        frequency=BarFrequency.M1,
        adjustment="none",
        schema_version="canonical-bar-v1",
    )


def _query(*, contract_or_series: str | None = None) -> BarQuery:
    shanghai = timezone(timedelta(hours=8))
    return BarQuery(
        dataset_kind=DatasetKind.ACTUAL_DOMINANT,
        symbol="jm",
        contract_or_series=contract_or_series,
        frequency=BarFrequency.M15,
        start=datetime(2026, 7, 31, 9, 0, tzinfo=shanghai),
        end=datetime(2026, 7, 31, 10, 0, tzinfo=shanghai),
    )


def _result() -> BarsResult:
    return BarsResult(
        bars=(),
        source_datasets=(_source("JM2611"), _source("JM2609")),
        manifest_digests=("b" * 64, "a" * 64),
        source_data_versions=("rqdata-final-z", "rqdata-final-a"),
        requested_window=(
            datetime(2026, 7, 31, 1, 0, tzinfo=UTC),
            datetime(2026, 7, 31, 2, 0, tzinfo=UTC),
        ),
        data_type=DatasetKind.ACTUAL_DOMINANT,
        derived_frequency=BarFrequency.M15,
    )


def test_builds_immutable_canonical_snapshot_and_reconstructs_review_query() -> None:
    identity = build_canonical_consumer_input(
        _query(),
        _result(),
        strategy_input_version="htdy-v1",
    )

    assert identity.to_snapshot() == {
        "schema_version": "canonical_consumer_input_v1",
        "request": {
            "dataset_kind": "actual_dominant",
            "symbol": "jm",
            "contract_or_series": None,
            "frequency": "15m",
            "start": "2026-07-31T01:00:00+00:00",
            "end": "2026-07-31T02:00:00+00:00",
            "strict": True,
        },
        "source_datasets": [
            {
                "provider": "rqdata",
                "dataset_kind": "actual_dominant",
                "symbol": "jm",
                "contract_or_series": "JM2609",
                "frequency": "1m",
                "adjustment": "none",
                "schema_version": "canonical-bar-v1",
            },
            {
                "provider": "rqdata",
                "dataset_kind": "actual_dominant",
                "symbol": "jm",
                "contract_or_series": "JM2611",
                "frequency": "1m",
                "adjustment": "none",
                "schema_version": "canonical-bar-v1",
            },
        ],
        "manifest_digests": ["a" * 64, "b" * 64],
        "source_data_versions": ["rqdata-final-a", "rqdata-final-z"],
        "derived_frequency": "15m",
        "strategy_input_version": "htdy-v1",
        "digest": "5c146cef7616bff9e8b19479815768173f58a26a3b8d4426df4a03de2a10083d",
    }
    assert reconstruct_bar_query(identity.to_snapshot()) == _query()
    with pytest.raises(FrozenInstanceError):
        identity.digest = "a" * 64  # type: ignore[misc]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda snapshot: snapshot.pop("digest"),
        lambda snapshot: snapshot.__setitem__("unexpected", "value"),
        lambda snapshot: snapshot.__setitem__("digest", "bad"),
        lambda snapshot: snapshot.__setitem__("digest", "0" * 64),
        lambda snapshot: snapshot.__setitem__("schema_version", "v0"),
    ],
    ids=(
        "missing_field",
        "extra_field",
        "malformed_hash",
        "digest_mismatch",
        "unsupported_schema",
    ),
)
def test_reconstruction_rejects_noncanonical_or_untrusted_snapshot(mutate) -> None:
    snapshot = build_canonical_consumer_input(
        _query(),
        _result(),
        strategy_input_version="htdy-v1",
    ).to_snapshot()
    mutate(snapshot)

    with pytest.raises(ValueError):
        reconstruct_bar_query(snapshot)


def test_build_rejects_query_result_identity_mismatch() -> None:
    with pytest.raises(ValueError):
        build_canonical_consumer_input(
            _query(contract_or_series="JM2605"),
            _result(),
            strategy_input_version="htdy-v1",
        )


def test_reconstruction_rejects_whitespace_strategy_version_with_valid_digest() -> None:
    snapshot = build_canonical_consumer_input(
        _query(),
        _result(),
        strategy_input_version="htdy-v1",
    ).to_snapshot()
    snapshot["strategy_input_version"] = " htdy-v1 "

    with pytest.raises(ValueError):
        reconstruct_bar_query(snapshot)


def test_parsing_returns_immutable_identity_with_the_verified_digest() -> None:
    snapshot = build_canonical_consumer_input(
        _query(),
        _result(),
        strategy_input_version="htdy-v1",
    ).to_snapshot()

    identity = CanonicalConsumerInput.from_snapshot(snapshot)

    assert identity.digest == snapshot["digest"]
    assert identity.to_snapshot() == snapshot
