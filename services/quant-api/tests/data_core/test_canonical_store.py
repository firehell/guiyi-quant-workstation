from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
import gc
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
from typing import Sequence
import uuid

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

import app.data_core.canonical_store as canonical_store_module
from app.data_core.bar_schema import CanonicalBar
from app.data_core.canonical_store import (
    CANONICAL_PARQUET_PROFILE_ID,
    CANONICAL_PARQUET_SCHEMA,
    CANONICAL_PARQUET_WRITER_PARAMETERS,
    CanonicalPublishError,
    CanonicalStore,
    CanonicalStoreError,
    PublishExpectation,
)
from app.data_core.catalog import HistoricalCatalog
from app.data_core.contracts import (
    BarFrequency,
    ContractValidationError,
    DatasetKey,
    DatasetKind,
    DatasetOrigin,
    ManifestLineage,
)
from app.data_core.quality import QualityValidationError
from app.data_core.rqdata_adapter import (
    MainMapRequest,
    MainMapRow,
    ProviderBarBatch,
    ProviderBarRequest,
    TradingSessionCoverage,
)
from app.db.base import Base
from app.models.data_core import MarketDataset, MarketPartition


START = datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
FIRST = datetime(2026, 7, 1, 1, 1, tzinfo=UTC)
SECOND = datetime(2026, 7, 1, 1, 2, tzinfo=UTC)
TRADING_DAY = date(2026, 7, 1)


def _independent_canonical_json_digest(value: object) -> str:
    encoded = (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


@pytest.fixture
def session(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'metadata.sqlite'}",
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session


def _key(**overrides: object) -> DatasetKey:
    values: dict[str, object] = {
        "provider": "rqdata",
        "dataset_kind": DatasetKind.ACTUAL_DOMINANT,
        "symbol": "jm",
        "contract_or_series": "JM2609",
        "frequency": BarFrequency.M1,
        "adjustment": "none",
        "schema_version": "canonical-bar-v1",
    }
    values.update(overrides)
    return DatasetKey(**values)


def _request(dataset: DatasetKey | None = None) -> ProviderBarRequest:
    return ProviderBarRequest(
        dataset=dataset or _key(),
        start=START,
        end=SECOND,
        sessions=(
            TradingSessionCoverage(
                trading_day=TRADING_DAY,
                start=START,
                end=SECOND,
                expected_bar_ends=(FIRST, SECOND),
            ),
        ),
    )


def _bar(bar_end: datetime, close: str) -> CanonicalBar:
    return CanonicalBar(
        provider="rqdata",
        dataset_kind=DatasetKind.ACTUAL_DOMINANT,
        symbol="jm",
        contract_or_series="JM2609",
        frequency=BarFrequency.M1,
        bar_end=bar_end,
        trading_day=TRADING_DAY,
        open=Decimal("100.000000000000000001"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal(close),
        volume=Decimal("12"),
        turnover=Decimal("1213.50"),
        open_interest=Decimal("99"),
        adjustment="none",
        schema_version="canonical-bar-v1",
    )


class FakeAdapter:
    def __init__(self, bars: Sequence[CanonicalBar] | object = None) -> None:
        self.bars = (
            (_bar(FIRST, "101.125"), _bar(SECOND, "101.25"))
            if bars is None
            else bars
        )

    def fetch_bars(self, request: ProviderBarRequest) -> ProviderBarBatch:
        return ProviderBarBatch(
            request=request,
            bars=self.bars,  # type: ignore[arg-type]
            data_version="provider-final-20260701",
        )

    def fetch_rank1_map(
        self,
        request: MainMapRequest,
    ) -> Sequence[MainMapRow]:
        return ()


def _store(
    tmp_path: Path,
    session: Session,
    fault: str | None = None,
) -> CanonicalStore:
    def inject(point: str) -> None:
        if point == fault:
            raise RuntimeError(f"injected:{point}")

    return CanonicalStore(
        staging_root=tmp_path / "staging",
        canonical_root=tmp_path / "canonical",
        metadata_session_factory=sessionmaker(
            bind=session.get_bind(),
            expire_on_commit=False,
        ),
        fault_injector=inject,
    )


def _stage_and_validate(
    store: CanonicalStore,
    *,
    bars: Sequence[CanonicalBar] | object = None,
):
    batch = FakeAdapter(bars).fetch_bars(_request())
    staged = store.stage(batch)
    return staged, store.validate(staged)


def _stage_and_validate_aggregate(store: CanonicalStore):
    dataset = _key(frequency=BarFrequency.M5)
    bars = tuple(
        replace(bar, frequency=BarFrequency.M5)
        for bar in (_bar(FIRST, "101.125"), _bar(SECOND, "101.25"))
    )
    batch = ProviderBarBatch(
        request=_request(dataset),
        bars=bars,
        data_version="legacy-aggregate-20260701",
    )
    staged = store.stage(batch)
    return staged, store.validate(staged)


def _expectation(validation) -> PublishExpectation:
    return PublishExpectation.from_validation(
        validation,
        manifest_version="canonical-manifest-v1",
    )


def _aggregate_expectation(validation) -> PublishExpectation:
    return PublishExpectation.from_validation(
        validation,
        manifest_version="task07-aggregate-migration-v1",
        manifest_format="canonical-manifest-v2",
        lineage=ManifestLineage(
            origin=DatasetOrigin.PREAGGREGATED_FROM_1M,
            source_frequency=BarFrequency.M1,
            legacy_source_checksum="a" * 64,
            quality_evidence_digest="b" * 64,
        ),
    )


def _crash_publish_worker(
    staging_root: str,
    canonical_root: str,
    database_path: str,
    fault_point: str,
    aggregate: bool = False,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def crash(point: str) -> None:
        if point == fault_point:
            os._exit(91)

    store = CanonicalStore(
        staging_root=Path(staging_root),
        canonical_root=Path(canonical_root),
        metadata_session_factory=factory,
        fault_injector=crash,
    )
    if aggregate:
        staged, validation = _stage_and_validate_aggregate(store)
        expectation = _aggregate_expectation(validation)
    else:
        staged, validation = _stage_and_validate(store)
        expectation = _expectation(validation)
    store.publish(staged, expectation)


def _crash_replacement_worker(
    staging_root: str,
    canonical_root: str,
    database_path: str,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed = CanonicalStore(
        staging_root=Path(staging_root),
        canonical_root=Path(canonical_root),
        metadata_session_factory=factory,
    )
    staged, validation = _stage_and_validate(seed)
    seed.publish(staged, _expectation(validation))

    def crash(point: str) -> None:
        if point == "after_metadata_commit":
            os._exit(91)

    replacement_store = CanonicalStore(
        staging_root=Path(staging_root),
        canonical_root=Path(canonical_root),
        metadata_session_factory=factory,
        fault_injector=crash,
    )
    batch = replace(
        FakeAdapter(
            (_bar(FIRST, "100.125"), _bar(SECOND, "100.25"))
        ).fetch_bars(_request()),
        data_version="provider-final-20260701-jm-session-v1",
    )
    replacement_staged = replacement_store.stage(batch)
    replacement_validation = replacement_store.validate(replacement_staged)
    replacement_store.publish(
        replacement_staged,
        PublishExpectation.from_validation(
            replacement_validation,
            manifest_version="canonical-manifest-v2-jm-session",
            overlap_reason="version_replacement",
        ),
    )


def _spawn_crashed_publish(
    tmp_path: Path,
    fault_point: str,
    *,
    aggregate: bool = False,
) -> tuple[Path, Path, Path]:
    database_path = tmp_path / "metadata.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    staging_root = tmp_path / "staging"
    canonical_root = tmp_path / "canonical"
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_publish_worker,
        args=(
            str(staging_root),
            str(canonical_root),
            str(database_path),
            fault_point,
            aggregate,
        ),
    )
    process.start()
    process.join(timeout=20)
    assert process.exitcode == 91
    return database_path, staging_root, canonical_root


@pytest.mark.parametrize(
    "overrides",
    [
        {"dataset": object()},
        {"coverage_start": START.replace(tzinfo=None)},
        {"coverage_end": SECOND.replace(tzinfo=None)},
        {"coverage_start": SECOND, "coverage_end": START},
        {"row_count": True},
        {"row_count": 1.0},
        {"row_count": 0},
        {"data_version": "../escape"},
        {"manifest_version": "nested/path"},
        {"file_checksum": "A" * 64},
        {"canonical_logical_fingerprint": "short"},
        {"manifest_digest": 1},
    ],
)
def test_publish_expectation_rejects_inexact_types_and_invalid_facts(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "dataset": _key(),
        "coverage_start": START,
        "coverage_end": SECOND,
        "row_count": 2,
        "data_version": "provider-final-20260701",
        "manifest_version": "canonical-manifest-v1",
        "file_checksum": "a" * 64,
        "canonical_logical_fingerprint": "b" * 64,
        "manifest_digest": None,
    }
    values.update(overrides)

    with pytest.raises(CanonicalPublishError) as error:
        PublishExpectation(**values)  # type: ignore[arg-type]

    assert error.value.code == "CANONICAL_PUBLISH_EXPECTATION_INVALID"


def test_publish_expectation_rejects_unknown_manifest_format() -> None:
    with pytest.raises(CanonicalPublishError) as error:
        PublishExpectation(
            dataset=_key(),
            coverage_start=START,
            coverage_end=SECOND,
            row_count=2,
            data_version="provider-final-20260701",
            manifest_version="provider-business-v7",
            manifest_format="canonical-manifest-v3",
        )

    assert error.value.code == "CANONICAL_PUBLISH_EXPECTATION_INVALID"


def _all_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file())


def _tree_snapshot(root: Path) -> dict[str, tuple[str, bytes | str]]:
    if not root.exists():
        return {}
    snapshot: dict[str, tuple[str, bytes | str]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot[relative] = ("symlink", os.readlink(path))
        elif path.is_dir():
            snapshot[relative] = ("dir", "")
        elif path.is_file():
            snapshot[relative] = ("file", path.read_bytes())
    return snapshot


def _assert_snapshot_preserved_with_only_empty_directories_added(
    before: dict[str, tuple[str, bytes | str]],
    after: dict[str, tuple[str, bytes | str]],
) -> None:
    assert {path: after[path] for path in before} == before
    assert all(
        kind == "dir"
        for path, (kind, _content) in after.items()
        if path not in before
    )


def _open_fd_count() -> int:
    descriptor_root = Path("/dev/fd")
    if not descriptor_root.is_dir():
        pytest.skip("platform does not expose /dev/fd")
    return len(list(descriptor_root.iterdir()))


def _expected_logical_fingerprint() -> str:
    logical_schema = [
        {"name": "provider", "type": "string", "nullable": False},
        {"name": "dataset_kind", "type": "string", "nullable": False},
        {"name": "symbol", "type": "string", "nullable": False},
        {"name": "contract_or_series", "type": "string", "nullable": False},
        {"name": "frequency", "type": "string", "nullable": False},
        {
            "name": "bar_end",
            "type": "utc_datetime_microsecond",
            "nullable": False,
        },
        {"name": "trading_day", "type": "date", "nullable": False},
        {"name": "open", "type": "decimal", "nullable": False},
        {"name": "high", "type": "decimal", "nullable": False},
        {"name": "low", "type": "decimal", "nullable": False},
        {"name": "close", "type": "decimal", "nullable": False},
        {"name": "volume", "type": "decimal", "nullable": False},
        {"name": "turnover", "type": "optional_decimal", "nullable": True},
        {
            "name": "open_interest",
            "type": "optional_decimal",
            "nullable": True,
        },
        {"name": "adjustment", "type": "string", "nullable": False},
        {"name": "schema_version", "type": "string", "nullable": False},
    ]

    def decimal(sign: int, coefficient: str, exponent: int) -> dict[str, object]:
        return {
            "sign": sign,
            "coefficient": coefficient,
            "exponent": exponent,
        }

    common = {
        "provider": "rqdata",
        "dataset_kind": "actual_dominant",
        "symbol": "jm",
        "contract_or_series": "JM2609",
        "frequency": "1m",
        "trading_day": "2026-07-01",
        "open": decimal(0, "100000000000000000001", -18),
        "high": decimal(0, "102", 0),
        "low": decimal(0, "99", 0),
        "volume": decimal(0, "12", 0),
        "turnover": decimal(0, "12135", -1),
        "open_interest": decimal(0, "99", 0),
        "adjustment": "none",
        "schema_version": "canonical-bar-v1",
    }
    payload = {
        "dataset_key": {
            "provider": "rqdata",
            "dataset_kind": "actual_dominant",
            "symbol": "jm",
            "contract_or_series": "JM2609",
            "frequency": "1m",
            "adjustment": "none",
            "schema_version": "canonical-bar-v1",
        },
        "logical_schema": logical_schema,
        "rows": [
            {
                **common,
                "bar_end": "2026-07-01T01:01:00.000000Z",
                "close": decimal(0, "101125", -3),
            },
            {
                **common,
                "bar_end": "2026-07-01T01:02:00.000000Z",
                "close": decimal(0, "10125", -2),
            },
        ],
    }
    canonical = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def test_stage_validate_publish_round_trip_with_exact_schema_and_values(
    tmp_path: Path,
    session: Session,
) -> None:
    store = _store(tmp_path, session)
    staged, validation = _stage_and_validate(store)

    published = store.publish(staged, _expectation(validation))

    assert published.file_path.is_relative_to(tmp_path / "canonical")
    assert published.manifest_path.is_relative_to(tmp_path / "canonical")
    assert not staged.task_root.exists()
    assert pq.read_schema(published.file_path) == CANONICAL_PARQUET_SCHEMA
    table = pq.read_table(published.file_path)
    assert table.num_rows == 2
    assert table.column("bar_end").to_pylist() == [FIRST, SECOND]
    assert table.column("provider").to_pylist() == ["rqdata", "rqdata"]
    assert table.column("dataset_kind").to_pylist() == [
        "actual_dominant",
        "actual_dominant",
    ]
    assert table.column("open").to_pylist() == [
        Decimal("100.000000000000000001"),
        Decimal("100.000000000000000001"),
    ]
    with duckdb.connect() as connection:
        duckdb_schema = connection.execute(
            """
            DESCRIBE SELECT *
            FROM read_parquet(?)
            """,
            [str(published.file_path)],
        ).fetchall()
        rows = connection.execute(
            """
            SELECT
                provider,
                dataset_kind,
                symbol,
                contract_or_series,
                frequency,
                epoch_us(bar_end),
                trading_day,
                open,
                high,
                low,
                close,
                volume,
                turnover,
                open_interest,
                adjustment,
                schema_version
            FROM read_parquet(?)
            ORDER BY bar_end
            """,
            [str(published.file_path)],
        ).fetchall()
    assert [(row[0], row[1]) for row in duckdb_schema] == [
        ("provider", "VARCHAR"),
        ("dataset_kind", "VARCHAR"),
        ("symbol", "VARCHAR"),
        ("contract_or_series", "VARCHAR"),
        ("frequency", "VARCHAR"),
        ("bar_end", "TIMESTAMP WITH TIME ZONE"),
        ("trading_day", "DATE"),
        ("open", "DECIMAL(38,18)"),
        ("high", "DECIMAL(38,18)"),
        ("low", "DECIMAL(38,18)"),
        ("close", "DECIMAL(38,18)"),
        ("volume", "DECIMAL(38,18)"),
        ("turnover", "DECIMAL(38,18)"),
        ("open_interest", "DECIMAL(38,18)"),
        ("adjustment", "VARCHAR"),
        ("schema_version", "VARCHAR"),
    ]
    common_duckdb = (
        "rqdata",
        "actual_dominant",
        "jm",
        "JM2609",
        "1m",
        TRADING_DAY,
        Decimal("100.000000000000000001"),
        Decimal("102.000000000000000000"),
        Decimal("99.000000000000000000"),
    )
    assert rows == [
        (
            *common_duckdb[:5],
            1782867660000000,
            *common_duckdb[5:],
            Decimal("101.125000000000000000"),
            Decimal("12.000000000000000000"),
            Decimal("1213.500000000000000000"),
            Decimal("99.000000000000000000"),
            "none",
            "canonical-bar-v1",
        ),
        (
            *common_duckdb[:5],
            1782867720000000,
            *common_duckdb[5:],
            Decimal("101.250000000000000000"),
            Decimal("12.000000000000000000"),
            Decimal("1213.500000000000000000"),
            Decimal("99.000000000000000000"),
            "none",
            "canonical-bar-v1",
        ),
    ]
    assert published.partition_manifest.coverage_start == START
    assert published.partition_manifest.coverage_end == SECOND
    assert published.partition_manifest.row_count == 2
    assert (
        hashlib.sha256(published.file_path.read_bytes()).hexdigest()
        == published.file_checksum
        == published.partition_manifest.checksum
    )
    manifest = json.loads(published.manifest_path.read_text())
    assert manifest["manifest_format"] == "canonical-manifest-v1"
    assert "source_lineage" not in manifest
    manifest_without_digest = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_digest"
    }
    independently_computed_manifest_digest = hashlib.sha256(
        (
            json.dumps(
                manifest_without_digest,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode()
    ).hexdigest()
    assert manifest["profile_id"] == CANONICAL_PARQUET_PROFILE_ID
    assert manifest["writer"]["parameters"] == CANONICAL_PARQUET_WRITER_PARAMETERS
    assert manifest["writer"]["pyarrow_version"] == pa.__version__
    assert manifest["writer"]["duckdb_version"] == duckdb.__version__
    assert manifest["file_checksum"] == published.file_checksum
    assert (
        manifest["canonical_logical_fingerprint"]
        == published.canonical_logical_fingerprint
    )
    assert (
        published.canonical_logical_fingerprint
        == _expected_logical_fingerprint()
    )
    assert manifest["manifest_digest"] == published.partition_manifest.manifest_digest
    assert manifest["manifest_digest"] == independently_computed_manifest_digest
    assert session.scalars(select(MarketDataset)).all()
    assert session.scalars(select(MarketPartition)).all()


def test_v2_direct_manifest_has_exact_nonaggregate_lineage(
    tmp_path: Path,
    session: Session,
) -> None:
    store = _store(tmp_path, session)
    staged, validation = _stage_and_validate(store)

    published = store.publish(
        staged,
        PublishExpectation.from_validation(
            validation,
            manifest_version="provider-final-manifest-business-v7",
            manifest_format="canonical-manifest-v2",
            lineage=ManifestLineage(origin=DatasetOrigin.PROVIDER_DIRECT),
        ),
    )

    manifest = json.loads(published.manifest_path.read_text())
    assert manifest["manifest_format"] == "canonical-manifest-v2"
    assert manifest["source_lineage"] == {"origin": "provider_direct"}
    assert manifest["manifest_digest"] == _independent_canonical_json_digest(
        {key: value for key, value in manifest.items() if key != "manifest_digest"}
    )


def test_v2_aggregate_manifest_binds_legacy_and_quality_lineage(
    tmp_path: Path,
    session: Session,
) -> None:
    store = _store(tmp_path, session)
    staged, validation = _stage_and_validate_aggregate(store)

    published = store.publish(
        staged,
        PublishExpectation.from_validation(
            validation,
            manifest_version="task07-aggregate-migration-v1",
            manifest_format="canonical-manifest-v2",
            lineage=ManifestLineage(
                origin=DatasetOrigin.PREAGGREGATED_FROM_1M,
                source_frequency=BarFrequency.M1,
                legacy_source_checksum="a" * 64,
                quality_evidence_digest="b" * 64,
            ),
        ),
    )

    manifest = json.loads(published.manifest_path.read_text())
    assert manifest["manifest_format"] == "canonical-manifest-v2"
    assert manifest["source_lineage"] == {
        "origin": "preaggregated_from_1m",
        "source_frequency": "1m",
        "legacy_source_checksum": "a" * 64,
        "quality_evidence_digest": "b" * 64,
    }
    assert manifest["manifest_digest"] == _independent_canonical_json_digest(
        {key: value for key, value in manifest.items() if key != "manifest_digest"}
    )


def test_aggregate_publish_requires_explicit_digest_bound_lineage(
    tmp_path: Path,
    session: Session,
) -> None:
    store = _store(tmp_path, session)
    _, validation = _stage_and_validate_aggregate(store)

    with pytest.raises(CanonicalPublishError) as error:
        PublishExpectation.from_validation(
            validation,
            manifest_version="task07-aggregate-migration-v1",
            manifest_format="canonical-manifest-v2",
        )

    assert error.value.code == "CANONICAL_PUBLISH_EXPECTATION_INVALID"


@pytest.mark.parametrize(
    "tamper",
    [
        "missing_lineage_field",
        "extra_top_level_field",
        "forged_source_frequency",
        "lineage_digest_tamper",
    ],
)
def test_v2_manifest_lineage_schema_and_digest_fail_closed(
    tmp_path: Path,
    session: Session,
    tamper: str,
) -> None:
    store = _store(tmp_path, session)
    staged, validation = _stage_and_validate_aggregate(store)
    published = store.publish(
        staged,
        PublishExpectation.from_validation(
            validation,
            manifest_version="task07-aggregate-migration-v1",
            manifest_format="canonical-manifest-v2",
            lineage=ManifestLineage(
                origin=DatasetOrigin.PREAGGREGATED_FROM_1M,
                source_frequency=BarFrequency.M1,
                legacy_source_checksum="a" * 64,
                quality_evidence_digest="b" * 64,
            ),
        ),
    )
    document = json.loads(published.manifest_path.read_text())
    if tamper == "missing_lineage_field":
        del document["source_lineage"]["quality_evidence_digest"]
    elif tamper == "extra_top_level_field":
        document["unexpected"] = True
    elif tamper == "forged_source_frequency":
        document["source_lineage"]["source_frequency"] = "5m"
    elif tamper == "lineage_digest_tamper":
        document["source_lineage"]["legacy_source_checksum"] = "c" * 64
    else:
        raise AssertionError(tamper)
    if tamper != "lineage_digest_tamper":
        document["manifest_digest"] = _independent_canonical_json_digest(
            {
                key: value
                for key, value in document.items()
                if key != "manifest_digest"
            }
        )

    with pytest.raises(ValueError):
        canonical_store_module._validate_stored_manifest_document(
            document,
            dataset=validation.dataset,
            coverage_start=validation.coverage_start,
            coverage_end=validation.coverage_end,
            row_count=validation.row_count,
            data_version=validation.data_version,
            manifest_version="task07-aggregate-migration-v1",
            file_uri=published.partition_manifest.file_uri,
            manifest_uri=published.partition_manifest.manifest_uri,
            file_checksum=published.file_checksum,
            canonical_logical_fingerprint=(
                published.canonical_logical_fingerprint
            ),
        )


def test_manifest_format_defaults_to_v1_independent_of_business_version(
    tmp_path: Path,
    session: Session,
) -> None:
    store = _store(tmp_path, session)
    staged, validation = _stage_and_validate(store)

    published = store.publish(
        staged,
        PublishExpectation.from_validation(
            validation,
            manifest_version="canonical-manifest-v2",
        ),
    )

    document = json.loads(published.manifest_path.read_text())
    assert document["manifest_format"] == "canonical-manifest-v1"
    assert document["manifest_version"] == "canonical-manifest-v2"
    assert "source_lineage" not in document


def test_publish_appends_version_replacement_without_deleting_original(
    tmp_path: Path,
    session: Session,
) -> None:
    store = _store(tmp_path, session)
    staged, validation = _stage_and_validate(store)
    original = store.publish(staged, _expectation(validation))
    original_bytes = original.file_path.read_bytes()

    replacement_batch = replace(
        FakeAdapter(
            (_bar(FIRST, "100.125"), _bar(SECOND, "100.25"))
        ).fetch_bars(_request()),
        data_version="provider-final-20260701-jm-session-v1",
    )
    replacement_staged = store.stage(replacement_batch)
    replacement_validation = store.validate(replacement_staged)
    replacement = store.publish(
        replacement_staged,
        PublishExpectation.from_validation(
            replacement_validation,
            manifest_version="canonical-manifest-v2-jm-session",
            overlap_reason="version_replacement",
        ),
    )

    with sessionmaker(bind=session.get_bind(), expire_on_commit=False)() as check:
        catalog = HistoricalCatalog(check)
        assert len(catalog.list_partitions(_key())) == 2
        assert catalog.list_effective_partitions(_key())[0].file_uri == (
            replacement.partition_manifest.file_uri
        )
    assert original.file_path.read_bytes() == original_bytes
    assert original.file_path.is_file()
    assert replacement.file_path.is_file()
    assert replacement.partition_manifest.overlap_reason == "version_replacement"


def test_constructor_rejects_symlink_root_without_touching_referent(
    tmp_path: Path,
    session: Session,
) -> None:
    referent = tmp_path / "referent"
    referent.mkdir()
    sentinel = referent / "sentinel.txt"
    sentinel.write_text("preserve")
    staging = tmp_path / "staging"
    staging.mkdir()
    canonical_link = tmp_path / "canonical-link"
    canonical_link.symlink_to(referent, target_is_directory=True)

    with pytest.raises(CanonicalStoreError) as error:
        CanonicalStore(
            staging_root=staging,
            canonical_root=canonical_link,
            metadata_session_factory=sessionmaker(
                bind=session.get_bind(),
                expire_on_commit=False,
            ),
        )

    assert error.value.code == "CANONICAL_ROOT_UNSAFE"
    assert sentinel.read_text() == "preserve"


def test_parent_swap_to_symlink_is_rejected_without_writing_victim(
    tmp_path: Path,
    session: Session,
) -> None:
    staging = tmp_path / "staging"
    canonical = tmp_path / "canonical"
    staging.mkdir()
    canonical.mkdir()
    store = CanonicalStore(
        staging_root=staging,
        canonical_root=canonical,
        metadata_session_factory=sessionmaker(
            bind=session.get_bind(),
            expire_on_commit=False,
        ),
    )
    staged, validation = _stage_and_validate(store)
    moved = tmp_path / "canonical-moved"
    canonical.rename(moved)
    victim = tmp_path / "victim"
    victim.mkdir()
    sentinel = victim / "sentinel.txt"
    sentinel.write_text("preserve")
    canonical.symlink_to(victim, target_is_directory=True)

    with pytest.raises(CanonicalStoreError) as error:
        store.publish(staged, _expectation(validation))

    assert error.value.code == "CANONICAL_ROOT_CHANGED"
    assert _all_files(staging) == []
    assert _tree_snapshot(victim) == {
        "sentinel.txt": ("file", b"preserve")
    }


def test_store_requires_owned_session_factory_and_preserves_caller_uow(
    tmp_path: Path,
    session: Session,
) -> None:
    staging = tmp_path / "owned-staging"
    canonical = tmp_path / "owned-canonical"
    staging.mkdir()
    canonical.mkdir()
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    pending = MarketDataset(
        provider="rqdata",
        dataset_kind="continuous",
        symbol="rb",
        contract_or_series="RB88",
        frequency="1d",
        adjustment="none",
        schema_version="canonical-bar-v1",
    )
    session.add(pending)
    store = CanonicalStore(
        staging_root=staging,
        canonical_root=canonical,
        metadata_session_factory=factory,
    )

    staged, validation = _stage_and_validate(store)
    store.publish(staged, _expectation(validation))

    assert pending in session.new
    assert pending.id is None
    with factory() as verification:
        assert verification.scalars(
            select(MarketDataset).where(MarketDataset.symbol == "rb")
        ).all() == []


def test_order_and_exact_duplicates_have_deterministic_three_identities(
    tmp_path: Path,
) -> None:
    facts: list[tuple[str, str, str]] = []
    variants = (
        (_bar(FIRST, "101.125"), _bar(SECOND, "101.25")),
        (
            _bar(SECOND, "101.25"),
            _bar(FIRST, "101.125"),
            _bar(FIRST, "101.125"),
        ),
    )
    for index, bars in enumerate(variants):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            case_root = tmp_path / str(index)
            case_root.mkdir()
            store = _store(case_root, session)
            staged, validation = _stage_and_validate(store, bars=bars)
            published = store.publish(staged, _expectation(validation))
            facts.append(
                (
                    published.file_checksum,
                    published.canonical_logical_fingerprint,
                    published.partition_manifest.manifest_digest,
                )
            )

    assert facts[0] == facts[1]


@pytest.mark.parametrize(
    "changed",
    [
        {"row_count": 3},
        {"coverage_end": FIRST},
        {"data_version": "other-version"},
        {"file_checksum": "0" * 64},
        {"canonical_logical_fingerprint": "1" * 64},
        {"manifest_digest": "2" * 64},
    ],
)
def test_publish_expectation_mismatch_has_no_canonical_or_metadata_side_effect(
    tmp_path: Path,
    session: Session,
    changed: dict[str, object],
) -> None:
    store = _store(tmp_path, session)
    staged, validation = _stage_and_validate(store)
    expected = replace(_expectation(validation), **changed)

    with pytest.raises(CanonicalPublishError) as error:
        store.publish(staged, expected)

    assert error.value.code == "CANONICAL_PUBLISH_EXPECTATION_MISMATCH"
    assert _all_files(tmp_path / "staging") == []
    assert _all_files(tmp_path / "canonical") == []
    assert session.scalars(select(MarketDataset)).all() == []
    assert session.scalars(select(MarketPartition)).all() == []


@pytest.mark.parametrize(
    "fault",
    [
        "staging_write",
        "validation",
        "file_rename",
        "manifest_rename",
        "metadata_registration",
        "metadata_commit",
    ],
)
def test_fault_injection_leaves_no_half_partition_and_rolls_back_metadata(
    tmp_path: Path,
    session: Session,
    fault: str,
) -> None:
    store = _store(tmp_path, session, fault)
    batch = FakeAdapter().fetch_bars(_request())
    canonical_before = _tree_snapshot(tmp_path / "canonical")
    staging_before = _tree_snapshot(tmp_path / "staging")

    with pytest.raises((RuntimeError, CanonicalPublishError)):
        if fault == "staging_write":
            store.stage(batch)
        else:
            staged = store.stage(batch)
            if fault == "validation":
                store.validate(staged)
            else:
                validation = store.validate(staged)
                store.publish(staged, _expectation(validation))

    assert _all_files(tmp_path / "staging") == []
    assert _all_files(tmp_path / "canonical") == []
    assert session.scalars(select(MarketDataset)).all() == []
    assert session.scalars(select(MarketPartition)).all() == []
    _assert_snapshot_preserved_with_only_empty_directories_added(
        canonical_before,
        _tree_snapshot(tmp_path / "canonical"),
    )
    assert _tree_snapshot(tmp_path / "staging") == staging_before


def test_failed_writer_never_relocates_shared_directory_populated_by_peer(
    tmp_path: Path,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, session, "metadata_registration")
    staged, validation = _stage_and_validate(store)
    shared_path = (
        tmp_path
        / "canonical"
        / Path(*store._partition_parts(validation))
    )
    peer_bytes = b"writer-b-live-partial"
    peer_name = "writer-b.partial"
    race: dict[str, object] = {"inserted": False}
    destructive_cleanup = getattr(
        canonical_store_module,
        "_rmdir_owned_reverse",
        None,
    )

    if destructive_cleanup is not None:

        def populate_after_former_empty_observation(root_fd, directories):
            assert directories
            assert shared_path.is_dir()
            assert list(shared_path.iterdir()) == []
            race["identity"] = canonical_store_module._Identity.from_stat(
                shared_path.stat()
            )
            (shared_path / peer_name).write_bytes(peer_bytes)
            race["inserted"] = True
            with monkeypatch.context() as context:
                context.setattr(
                    canonical_store_module,
                    "_owned_directory_is_empty",
                    lambda *_args, **_kwargs: True,
                )
                destructive_cleanup(root_fd, directories)

        monkeypatch.setattr(
            canonical_store_module,
            "_rmdir_owned_reverse",
            populate_after_former_empty_observation,
        )

    with pytest.raises(CanonicalPublishError):
        store.publish(staged, _expectation(validation))

    if not race["inserted"]:
        assert shared_path.is_dir()
        assert list(shared_path.iterdir()) == []
        race["identity"] = canonical_store_module._Identity.from_stat(
            shared_path.stat()
        )
        (shared_path / peer_name).write_bytes(peer_bytes)

    assert shared_path.is_dir()
    assert canonical_store_module._Identity.from_stat(
        shared_path.stat()
    ) == race["identity"]
    assert (shared_path / peer_name).read_bytes() == peer_bytes
    assert [
        path.relative_to(tmp_path / "canonical").as_posix()
        for path in _all_files(tmp_path / "canonical")
    ] == [
        (
            shared_path.relative_to(tmp_path / "canonical") / peer_name
        ).as_posix()
    ]
    assert _all_files(tmp_path / "staging") == []
    assert session.scalars(select(MarketDataset)).all() == []
    assert session.scalars(select(MarketPartition)).all() == []


def test_existing_target_and_manifest_are_preserved_on_collision(
    tmp_path: Path,
    session: Session,
) -> None:
    store = _store(tmp_path, session)
    staged, validation = _stage_and_validate(store)
    first = store.publish(staged, _expectation(validation))
    original_file = first.file_path.read_bytes()
    original_manifest = first.manifest_path.read_bytes()
    rows_before = session.scalars(select(MarketPartition)).all()
    staged_again, validation_again = _stage_and_validate(store)

    with pytest.raises(CanonicalPublishError) as error:
        store.publish(staged_again, _expectation(validation_again))

    assert error.value.code == "CANONICAL_PUBLISH_COLLISION"
    assert first.file_path.read_bytes() == original_file
    assert first.manifest_path.read_bytes() == original_manifest
    assert session.scalars(select(MarketPartition)).all() == rows_before


@pytest.mark.parametrize(
    "role,final_name",
    [
        ("file", "part-00000.parquet"),
        (
            "manifest",
            "part-00000.canonical-manifest-v1.manifest.json",
        ),
        (
            "marker",
            "part-00000.canonical-manifest-v1.prepared.json",
        ),
    ],
)
def test_peer_final_winning_after_recheck_is_never_compensated(
    tmp_path: Path,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    final_name: str,
) -> None:
    store = _store(tmp_path, session)
    staged, validation = _stage_and_validate(store)
    shared_path = (
        tmp_path
        / "canonical"
        / Path(*store._partition_parts(validation))
    )
    peer_bytes = f"peer-{role}-final".encode()
    original_link = os.link
    peer_identity: canonical_store_module._Identity | None = None

    def peer_wins_then_real_link(source, target, **kwargs):
        nonlocal peer_identity
        if target == final_name:
            target_fd = os.open(
                target,
                canonical_store_module._FILE_CREATE_FLAGS,
                0o600,
                dir_fd=kwargs["dst_dir_fd"],
            )
            try:
                os.write(target_fd, peer_bytes)
                os.fsync(target_fd)
                peer_identity = canonical_store_module._Identity.from_stat(
                    os.fstat(target_fd)
                )
            finally:
                os.close(target_fd)
        return original_link(source, target, **kwargs)

    monkeypatch.setattr(os, "link", peer_wins_then_real_link)

    with pytest.raises(CanonicalPublishError) as error:
        store.publish(staged, _expectation(validation))

    peer_path = shared_path / final_name
    assert error.value.code == "CANONICAL_PUBLISH_COLLISION"
    assert peer_identity is not None
    assert peer_path.read_bytes() == peer_bytes
    assert canonical_store_module._Identity.from_stat(
        peer_path.stat()
    ) == peer_identity
    assert _all_files(tmp_path / "canonical") == [peer_path]
    assert _all_files(tmp_path / "staging") == []
    assert session.scalars(select(MarketDataset)).all() == []
    assert session.scalars(select(MarketPartition)).all() == []


@pytest.mark.parametrize(
    "bad_component",
    ["../escape", "nested/path", "/absolute", "a\\b"],
)
def test_malicious_identity_or_data_version_creates_no_paths(
    tmp_path: Path,
    session: Session,
    bad_component: str,
) -> None:
    store = _store(tmp_path, session)
    batch = FakeAdapter().fetch_bars(_request())
    object.__setattr__(batch, "data_version", bad_component)

    with pytest.raises(QualityValidationError):
        store.stage(batch)

    assert _all_files(tmp_path / "staging") == []
    assert _all_files(tmp_path / "canonical") == []


@pytest.mark.parametrize(
    "bad_component",
    ["../escape", "nested/path", "/absolute", "a\\b"],
)
def test_malicious_dataset_identity_creates_no_paths(
    tmp_path: Path,
    session: Session,
    bad_component: str,
) -> None:
    with pytest.raises(ContractValidationError):
        _key(symbol=bad_component)

    assert _all_files(tmp_path / "staging") == []
    assert _all_files(tmp_path / "canonical") == []


def test_decimal_and_timestamp_profile_rejections_have_zero_side_effects(
    tmp_path: Path,
    session: Session,
) -> None:
    store = _store(tmp_path, session)
    bad_decimal = _bar(FIRST, "101.125")
    object.__setattr__(bad_decimal, "volume", Decimal("9" * 900))

    with pytest.raises(QualityValidationError) as decimal_error:
        store.stage(
            FakeAdapter((bad_decimal, _bar(SECOND, "101.25"))).fetch_bars(
                _request()
            )
        )

    assert decimal_error.value.code == "CANONICAL_PARQUET_DECIMAL_OUT_OF_PROFILE"
    assert _all_files(tmp_path / "staging") == []
    assert _all_files(tmp_path / "canonical") == []
    assert session.scalars(select(MarketDataset)).all() == []

    class NanosecondDateTime(datetime):
        nanosecond = 1

    precise = NanosecondDateTime(2026, 7, 1, 1, 1, tzinfo=UTC)
    bad_timestamp = _bar(precise, "101.125")
    with pytest.raises(QualityValidationError) as timestamp_error:
        store.stage(
            FakeAdapter((bad_timestamp, _bar(SECOND, "101.25"))).fetch_bars(
                _request()
            )
        )

    assert timestamp_error.value.code == (
        "CANONICAL_PARQUET_TIMESTAMP_OUT_OF_PROFILE"
    )
    assert _all_files(tmp_path / "staging") == []
    assert _all_files(tmp_path / "canonical") == []
    assert session.scalars(select(MarketDataset)).all() == []


def test_post_effect_metadata_registration_failure_rolls_back(
    tmp_path: Path,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, session)
    before = _tree_snapshot(tmp_path)
    staged, validation = _stage_and_validate(store)
    original = HistoricalCatalog.register_partition

    def register_then_raise(self, key, manifest):
        original(self, key, manifest)
        raise RuntimeError("post-effect registration failure")

    monkeypatch.setattr(
        HistoricalCatalog,
        "register_partition",
        register_then_raise,
    )

    with pytest.raises(CanonicalPublishError):
        store.publish(staged, _expectation(validation))

    session.expire_all()
    assert session.scalars(select(MarketDataset)).all() == []
    _assert_snapshot_preserved_with_only_empty_directories_added(
        before,
        _tree_snapshot(tmp_path),
    )


def test_post_effect_link_failure_is_compensated(
    tmp_path: Path,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, session)
    before = _tree_snapshot(tmp_path)
    staged, validation = _stage_and_validate(store)
    original = os.link
    raised = False

    def link_then_raise(*args, **kwargs):
        nonlocal raised
        original(*args, **kwargs)
        if not raised:
            raised = True
            raise RuntimeError("post-effect link failure")

    monkeypatch.setattr(os, "link", link_then_raise)

    with pytest.raises(CanonicalPublishError):
        store.publish(staged, _expectation(validation))

    session.expire_all()
    assert session.scalars(select(MarketDataset)).all() == []
    _assert_snapshot_preserved_with_only_empty_directories_added(
        before,
        _tree_snapshot(tmp_path),
    )


def test_ambiguous_commit_is_resolved_by_exact_metadata_query(
    tmp_path: Path,
    session: Session,
) -> None:
    engine = session.get_bind()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    arm = {"value": False}
    created_sessions: list[Session] = []

    def ambiguous_factory() -> Session:
        owned = factory()
        created_sessions.append(owned)
        if arm["value"]:
            original_commit = owned.commit

            def ambiguous_commit() -> None:
                arm["value"] = False
                original_commit()
                raise RuntimeError("commit acknowledgement lost")

            owned.commit = ambiguous_commit  # type: ignore[method-assign]
        return owned

    store = CanonicalStore(
        staging_root=tmp_path / "staging",
        canonical_root=tmp_path / "canonical",
        metadata_session_factory=ambiguous_factory,
    )
    staged, validation = _stage_and_validate(store)
    arm["value"] = True

    published = store.publish(staged, _expectation(validation))

    session.expire_all()
    assert published.file_path.is_file()
    assert published.manifest_path.is_file()
    assert published.prepared_marker_path.is_file()
    assert len(session.scalars(select(MarketPartition)).all()) == 1
    assert len(created_sessions) == 2
    assert created_sessions[0] is not created_sessions[1]
    assert not list(
        (tmp_path / "canonical" / "canonical-publish-journal").iterdir()
    )


def test_dirty_factory_session_is_rejected_without_changing_caller_uow(
    tmp_path: Path,
    session: Session,
) -> None:
    store = CanonicalStore(
        staging_root=tmp_path / "staging",
        canonical_root=tmp_path / "canonical",
        metadata_session_factory=lambda: session,
    )
    staged, validation = _stage_and_validate(store)
    transaction = session.begin()

    with pytest.raises(CanonicalPublishError) as error:
        store.publish(staged, _expectation(validation))

    assert error.value.code == "CANONICAL_METADATA_SESSION_NOT_CLEAN"
    assert session.in_transaction()
    assert transaction.is_active
    transaction.rollback()


def test_compensation_failure_leaves_journal_for_idempotent_recovery(
    tmp_path: Path,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, session, "after_file_link")
    canonical_before = _tree_snapshot(tmp_path / "canonical")
    staging_before = _tree_snapshot(tmp_path / "staging")
    staged, validation = _stage_and_validate(store)
    original = canonical_store_module._unlink_owned
    raised = False

    def fail_once(root_fd, entry):
        nonlocal raised
        if not raised:
            raised = True
            original(root_fd, entry)
            raise OSError("compensation interrupted")
        return original(root_fd, entry)

    monkeypatch.setattr(canonical_store_module, "_unlink_owned", fail_once)
    with pytest.raises(CanonicalPublishError) as error:
        store.publish(staged, _expectation(validation))
    assert error.value.code == "CANONICAL_RECOVERY_UNCERTAIN"
    assert list(
        (tmp_path / "canonical" / "canonical-publish-journal").glob(
            "txn-*.json"
        )
    )

    monkeypatch.setattr(canonical_store_module, "_unlink_owned", original)
    recovered = _store(tmp_path, session)

    assert recovered is not None
    session.expire_all()
    assert session.scalars(select(MarketDataset)).all() == []
    assert _all_files(tmp_path / "canonical") == []
    _assert_snapshot_preserved_with_only_empty_directories_added(
        canonical_before,
        _tree_snapshot(tmp_path / "canonical"),
    )
    assert _tree_snapshot(tmp_path / "staging") == staging_before


def test_existing_parent_symlink_is_rejected_without_touching_referent(
    tmp_path: Path,
    session: Session,
) -> None:
    store = _store(tmp_path, session)
    staged, validation = _stage_and_validate(store)
    victim = tmp_path / "victim"
    victim.mkdir()
    sentinel = victim / "sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    (tmp_path / "canonical" / "provider").symlink_to(
        victim,
        target_is_directory=True,
    )

    with pytest.raises(CanonicalStoreError):
        store.publish(staged, _expectation(validation))

    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_parent_directory_swap_between_lstat_and_open_is_rejected(
    tmp_path: Path,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, session)
    staged, validation = _stage_and_validate(store)
    legitimate = tmp_path / "canonical" / "provider"
    legitimate.mkdir()
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    sentinel = attacker / "sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    displaced = tmp_path / "provider-displaced"
    original_open = os.open
    swapped = False

    def swap_then_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == "provider" and kwargs.get("dir_fd") is not None and not swapped:
            legitimate.rename(displaced)
            attacker.rename(legitimate)
            swapped = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_then_open)

    with pytest.raises(CanonicalStoreError) as error:
        store.publish(staged, _expectation(validation))

    assert error.value.code == "CANONICAL_PATH_CHANGED"
    assert (legitimate / "sentinel.txt").read_text(encoding="utf-8") == "preserve"
    assert _tree_snapshot(legitimate) == {
        "sentinel.txt": ("file", b"preserve")
    }


@pytest.mark.parametrize("replacement", ["symlink", "hardlink"])
def test_replaced_published_entry_is_never_unlinked(
    tmp_path: Path,
    session: Session,
    replacement: str,
) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("preserve", encoding="utf-8")

    def replace_and_fail(point: str) -> None:
        if point != "after_file_link":
            return
        published_file = next(
            (tmp_path / "canonical").rglob("part-00000.parquet")
        )
        published_file.unlink()
        if replacement == "symlink":
            published_file.symlink_to(victim)
        else:
            os.link(victim, published_file)
        raise RuntimeError("adversarial replacement")

    store = CanonicalStore(
        staging_root=tmp_path / "staging",
        canonical_root=tmp_path / "canonical",
        metadata_session_factory=sessionmaker(
            bind=session.get_bind(),
            expire_on_commit=False,
        ),
        fault_injector=replace_and_fail,
    )
    staged, validation = _stage_and_validate(store)

    with pytest.raises(CanonicalPublishError) as error:
        store.publish(staged, _expectation(validation))

    assert error.value.code == "CANONICAL_RECOVERY_UNCERTAIN"
    assert victim.read_text(encoding="utf-8") == "preserve"
    assert victim.exists()


def test_file_replacement_after_identity_observation_survives_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "owned.txt"
    target.write_bytes(b"transaction-owned")
    expected = canonical_store_module._Identity.from_stat(target.stat())
    replacement = root / "replacement.txt"
    replacement.write_bytes(b"replacement-must-survive")
    replacement_inode = replacement.stat().st_ino
    displaced = root / "displaced-owned.txt"
    original_lstat = canonical_store_module._lstat_identity
    swapped = False

    def swap_after_observation(parent_fd, name, **kwargs):
        nonlocal swapped
        actual = original_lstat(parent_fd, name, **kwargs)
        if not swapped and actual == expected:
            if target.exists():
                target.rename(displaced)
            replacement.rename(target)
            swapped = True
        return actual

    monkeypatch.setattr(
        canonical_store_module,
        "_lstat_identity",
        swap_after_observation,
    )
    root_fd = os.open(root, canonical_store_module._DIR_FLAGS)
    try:
        canonical_store_module._unlink_owned(
            root_fd,
            canonical_store_module._OwnedEntry((), target.name, expected),
        )
    finally:
        os.close(root_fd)

    assert swapped
    assert target.read_bytes() == b"replacement-must-survive"
    assert target.stat().st_ino == replacement_inode


def test_atomic_rename_no_replace_preserves_existing_target(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    source_root.mkdir()
    target_root.mkdir()
    source = source_root / "entry"
    target = target_root / "entry"
    source.write_bytes(b"source")
    target.write_bytes(b"target")
    source_fd = os.open(source_root, canonical_store_module._DIR_FLAGS)
    target_fd = os.open(target_root, canonical_store_module._DIR_FLAGS)
    try:
        with pytest.raises(FileExistsError):
            canonical_store_module._atomic_rename_no_replace_at(
                source_fd,
                source.name,
                target_fd,
                target.name,
            )
    finally:
        os.close(target_fd)
        os.close(source_fd)

    assert source.read_bytes() == b"source"
    assert target.read_bytes() == b"target"


def test_atomic_rename_unavailable_fails_closed_without_moving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    source = root / "source"
    source.write_bytes(b"source")
    monkeypatch.setattr(canonical_store_module.sys, "platform", "unsupported")
    root_fd = os.open(root, canonical_store_module._DIR_FLAGS)
    try:
        with pytest.raises(CanonicalPublishError) as error:
            canonical_store_module._atomic_rename_no_replace_at(
                root_fd,
                source.name,
                root_fd,
                "target",
            )
    finally:
        os.close(root_fd)

    assert error.value.code == "CANONICAL_ATOMIC_RENAME_UNAVAILABLE"
    assert source.read_bytes() == b"source"
    assert not (root / "target").exists()


def test_constructor_rejects_non_private_cleanup_quarantine(
    tmp_path: Path,
    session: Session,
) -> None:
    canonical_root = tmp_path / "canonical"
    canonical_root.mkdir()
    quarantine = canonical_root / "canonical-cleanup-quarantine"
    quarantine.mkdir(mode=0o700)
    quarantine.chmod(0o755)

    with pytest.raises(CanonicalPublishError) as error:
        CanonicalStore(
            staging_root=tmp_path / "staging",
            canonical_root=canonical_root,
            metadata_session_factory=sessionmaker(
                bind=session.get_bind(),
                expire_on_commit=False,
            ),
        )

    assert error.value.code == "CANONICAL_CLEANUP_QUARANTINE_UNSAFE"
    assert quarantine.is_dir()


def test_cleanup_claim_never_uses_overwriting_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "owned.txt"
    target.write_bytes(b"transaction-owned")
    expected = canonical_store_module._Identity.from_stat(target.stat())

    def forbidden_rename(*_args, **_kwargs):
        raise AssertionError("overwriting rename fallback used")

    monkeypatch.setattr(os, "rename", forbidden_rename)
    root_fd = os.open(root, canonical_store_module._DIR_FLAGS)
    try:
        canonical_store_module._unlink_owned(
            root_fd,
            canonical_store_module._OwnedEntry((), target.name, expected),
        )
    finally:
        os.close(root_fd)

    assert not target.exists()


def test_preclaim_replacement_is_quarantined_and_never_deleted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "owned.txt"
    target.write_bytes(b"transaction-owned")
    expected = canonical_store_module._Identity.from_stat(target.stat())
    replacement = root / "replacement.txt"
    replacement.write_bytes(b"replacement-evidence")
    replacement_inode = replacement.stat().st_ino
    displaced = root / "displaced-owned.txt"
    original_rename = os.rename
    original_atomic_rename = (
        canonical_store_module._atomic_rename_no_replace_at
    )
    swapped = False

    def swap_before_claim(
        source_dir_fd,
        source,
        target_dir_fd,
        destination,
    ):
        nonlocal swapped
        if not swapped and source == target.name:
            original_rename(target, displaced)
            original_rename(replacement, target)
            swapped = True
        return original_atomic_rename(
            source_dir_fd,
            source,
            target_dir_fd,
            destination,
        )

    monkeypatch.setattr(
        canonical_store_module,
        "_atomic_rename_no_replace_at",
        swap_before_claim,
    )
    root_fd = os.open(root, canonical_store_module._DIR_FLAGS)
    try:
        with pytest.raises(CanonicalPublishError) as error:
            canonical_store_module._unlink_owned(
                root_fd,
                canonical_store_module._OwnedEntry(
                    (),
                    target.name,
                    expected,
                ),
            )
    finally:
        os.close(root_fd)

    assert swapped
    assert error.value.code == "CANONICAL_OWNERSHIP_CHANGED"
    evidence = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.stat().st_ino == replacement_inode
    ]
    assert len(evidence) == 1
    assert evidence[0].read_bytes() == b"replacement-evidence"
    assert displaced.read_bytes() == b"transaction-owned"


@pytest.mark.parametrize(
    "fault_point,committed",
    [
        ("after_journal_fsync", False),
        ("after_file_link", False),
        ("after_manifest_link", False),
        ("after_commit_marker", False),
        ("after_metadata_commit", True),
    ],
)
def test_force_exit_is_reconciled_to_absent_or_fully_committed_state(
    tmp_path: Path,
    fault_point: str,
    committed: bool,
) -> None:
    database_path = tmp_path / "metadata.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    staging_root = tmp_path / "staging"
    canonical_root = tmp_path / "canonical"
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_crash_publish_worker,
        args=(
            str(staging_root),
            str(canonical_root),
            str(database_path),
            fault_point,
        ),
    )

    process.start()
    process.join(timeout=20)

    assert process.exitcode == 91
    recovery_engine = create_engine(
        f"sqlite+pysqlite:///{database_path}"
    )
    recovery_factory = sessionmaker(
        bind=recovery_engine,
        expire_on_commit=False,
    )
    CanonicalStore(
        staging_root=staging_root,
        canonical_root=canonical_root,
        metadata_session_factory=recovery_factory,
    )

    with recovery_factory() as recovered_session:
        datasets = recovered_session.scalars(select(MarketDataset)).all()
        partitions = recovered_session.scalars(select(MarketPartition)).all()
    assert _all_files(staging_root) == []
    assert not list(
        (canonical_root / "canonical-publish-journal").iterdir()
    )
    assert not list(canonical_root.rglob("*.partial"))
    if committed:
        assert len(datasets) == 1
        assert len(partitions) == 1
        assert len(list(canonical_root.rglob("part-00000.parquet"))) == 1
        assert len(list(canonical_root.rglob("*.manifest.json"))) == 1
        assert len(list(canonical_root.rglob("*.prepared.json"))) == 1
    else:
        assert datasets == []
        assert partitions == []
        assert _all_files(canonical_root) == []
        _assert_snapshot_preserved_with_only_empty_directories_added(
            {
                "canonical-cleanup-quarantine": ("dir", ""),
                "canonical-publish-journal": ("dir", ""),
            },
            _tree_snapshot(canonical_root),
        )
        assert _tree_snapshot(staging_root) == {
            "canonical-cleanup-quarantine": ("dir", ""),
        }


def test_v2_aggregate_post_commit_recovery_preserves_exact_catalog_manifest(
    tmp_path: Path,
) -> None:
    database_path, staging_root, canonical_root = _spawn_crashed_publish(
        tmp_path,
        "after_metadata_commit",
        aggregate=True,
    )
    journal = next(
        (canonical_root / "canonical-publish-journal").glob("txn-*.json")
    )
    intent = json.loads(journal.read_text(encoding="utf-8"))
    manifest_document = intent["manifest_document"]
    manifest_facts = intent["partition_manifest"]
    assert manifest_document["manifest_format"] == "canonical-manifest-v2"
    assert manifest_document["manifest_version"] == (
        "task07-aggregate-migration-v1"
    )
    assert manifest_document["source_lineage"] == {
        "origin": "preaggregated_from_1m",
        "source_frequency": "1m",
        "legacy_source_checksum": "a" * 64,
        "quality_evidence_digest": "b" * 64,
    }
    factory = sessionmaker(
        bind=create_engine(f"sqlite+pysqlite:///{database_path}"),
        expire_on_commit=False,
    )

    CanonicalStore(
        staging_root=staging_root,
        canonical_root=canonical_root,
        metadata_session_factory=factory,
    )

    with factory() as recovered_session:
        partitions = HistoricalCatalog(recovered_session).list_partitions(
            _key(frequency=BarFrequency.M5)
        )
    assert len(partitions) == 1
    partition = partitions[0]
    assert partition.manifest_version == manifest_facts["manifest_version"]
    assert partition.manifest_digest == manifest_facts["manifest_digest"]
    assert partition.file_uri == manifest_facts["file_uri"]
    assert partition.manifest_uri == manifest_facts["manifest_uri"]
    assert partition.checksum == manifest_facts["checksum"]
    assert partition.row_count == manifest_facts["row_count"]
    manifest_path = canonical_root / partition.manifest_uri
    file_path = canonical_root / partition.file_uri
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == (
        manifest_document
    )
    assert hashlib.sha256(file_path.read_bytes()).hexdigest() == (
        partition.checksum
    )
    assert _independent_canonical_json_digest(
        {
            key: value
            for key, value in manifest_document.items()
            if key != "manifest_digest"
        }
    ) == partition.manifest_digest
    assert not list(
        (canonical_root / "canonical-publish-journal").iterdir()
    )


def test_v2_aggregate_critical_precommit_crash_recovers_to_absent(
    tmp_path: Path,
) -> None:
    database_path, staging_root, canonical_root = _spawn_crashed_publish(
        tmp_path,
        "after_manifest_link",
        aggregate=True,
    )
    journal = next(
        (canonical_root / "canonical-publish-journal").glob("txn-*.json")
    )
    intent = json.loads(journal.read_text(encoding="utf-8"))
    assert intent["manifest_document"]["source_lineage"]["origin"] == (
        "preaggregated_from_1m"
    )
    factory = sessionmaker(
        bind=create_engine(f"sqlite+pysqlite:///{database_path}"),
        expire_on_commit=False,
    )

    CanonicalStore(
        staging_root=staging_root,
        canonical_root=canonical_root,
        metadata_session_factory=factory,
    )

    with factory() as recovered_session:
        assert recovered_session.scalars(select(MarketDataset)).all() == []
        assert recovered_session.scalars(select(MarketPartition)).all() == []
    assert _all_files(staging_root) == []
    assert _all_files(canonical_root) == []


@pytest.mark.parametrize(
    "tamper",
    [
        "missing_lineage_field",
        "extra_lineage_field",
        "lineage_digest_tamper",
    ],
)
def test_v2_aggregate_journal_lineage_tamper_fails_closed_before_mutation(
    tmp_path: Path,
    tamper: str,
) -> None:
    database_path, staging_root, canonical_root = _spawn_crashed_publish(
        tmp_path,
        "after_journal_fsync",
        aggregate=True,
    )
    journal = next(
        (canonical_root / "canonical-publish-journal").glob("txn-*.json")
    )
    payload = json.loads(journal.read_text(encoding="utf-8"))
    lineage = payload["manifest_document"]["source_lineage"]
    if tamper == "missing_lineage_field":
        del lineage["quality_evidence_digest"]
    elif tamper == "extra_lineage_field":
        lineage["unexpected"] = True
    elif tamper == "lineage_digest_tamper":
        lineage["legacy_source_checksum"] = "c" * 64
    else:
        raise AssertionError(tamper)
    if tamper != "lineage_digest_tamper":
        manifest_document = payload["manifest_document"]
        repaired_digest = _independent_canonical_json_digest(
            {
                key: value
                for key, value in manifest_document.items()
                if key != "manifest_digest"
            }
        )
        manifest_document["manifest_digest"] = repaired_digest
        payload["partition_manifest"]["manifest_digest"] = repaired_digest
    journal.write_text(json.dumps(payload), encoding="utf-8")
    canonical_before = _tree_snapshot(canonical_root)
    staging_before = _tree_snapshot(staging_root)
    factory = sessionmaker(
        bind=create_engine(f"sqlite+pysqlite:///{database_path}"),
        expire_on_commit=False,
    )

    with pytest.raises(CanonicalPublishError) as error:
        CanonicalStore(
            staging_root=staging_root,
            canonical_root=canonical_root,
            metadata_session_factory=factory,
        )

    assert error.value.code == "CANONICAL_JOURNAL_INVALID"
    assert _tree_snapshot(canonical_root) == canonical_before
    assert _tree_snapshot(staging_root) == staging_before


@pytest.mark.parametrize(
    "fault_point",
    [
        "after_journal_temp_partial_write",
        "after_journal_temp_fsync",
    ],
)
def test_journal_temp_crash_never_exposes_malformed_intent(
    tmp_path: Path,
    fault_point: str,
) -> None:
    database_path = tmp_path / "metadata.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    staging_root = tmp_path / "staging"
    canonical_root = tmp_path / "canonical"
    seed_store = CanonicalStore(
        staging_root=staging_root,
        canonical_root=canonical_root,
        metadata_session_factory=factory,
    )
    staged, validation = _stage_and_validate(seed_store)
    published = seed_store.publish(staged, _expectation(validation))
    final_paths = (
        published.file_path,
        published.manifest_path,
        published.prepared_marker_path,
    )
    preserved = tuple(
        (path.read_bytes(), path.stat().st_ino) for path in final_paths
    )
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_crash_publish_worker,
        args=(
            str(staging_root),
            str(canonical_root),
            str(database_path),
            fault_point,
        ),
    )

    process.start()
    process.join(timeout=20)

    assert process.exitcode == 91
    journal_root = canonical_root / "canonical-publish-journal"
    assert not list(journal_root.glob("txn-*.json"))
    assert len(list(journal_root.glob("journal-temp-*.partial"))) == 1

    CanonicalStore(
        staging_root=staging_root,
        canonical_root=canonical_root,
        metadata_session_factory=factory,
    )

    for path, (content, inode) in zip(final_paths, preserved, strict=True):
        assert path.read_bytes() == content
        assert path.stat().st_ino == inode
    with factory() as recovered_session:
        assert len(recovered_session.scalars(select(MarketDataset)).all()) == 1
        assert len(
            recovered_session.scalars(select(MarketPartition)).all()
        ) == 1


def test_version_replacement_recovers_after_post_commit_crash(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "metadata.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    staging_root = tmp_path / "staging"
    canonical_root = tmp_path / "canonical"
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_replacement_worker,
        args=(
            str(staging_root),
            str(canonical_root),
            str(database_path),
        ),
    )

    process.start()
    process.join(timeout=20)

    assert process.exitcode == 91
    factory = sessionmaker(
        bind=create_engine(f"sqlite+pysqlite:///{database_path}"),
        expire_on_commit=False,
    )
    CanonicalStore(
        staging_root=staging_root,
        canonical_root=canonical_root,
        metadata_session_factory=factory,
    )
    with factory() as session:
        catalog = HistoricalCatalog(session)
        assert len(catalog.list_partitions(_key())) == 2
        effective = catalog.list_effective_partitions(_key())
        assert len(effective) == 1
        assert effective[0].overlap_reason == "version_replacement"
    assert not list(
        (canonical_root / "canonical-publish-journal").glob("txn-*.json")
    )
    assert len(list(canonical_root.rglob("part-00000.parquet"))) == 2


def test_post_effect_journal_publish_crash_recovers_complete_intent(
    tmp_path: Path,
) -> None:
    database_path, staging_root, canonical_root = _spawn_crashed_publish(
        tmp_path,
        "after_journal_publish",
    )
    journal_root = canonical_root / "canonical-publish-journal"
    assert len(list(journal_root.glob("txn-*.json"))) == 1
    assert not list(journal_root.glob("journal-temp-*.partial"))
    journal_path = next(journal_root.glob("txn-*.json"))
    assert json.loads(journal_path.read_bytes())["journal_version"] == (
        "canonical-publish-intent-v2"
    )
    recovery_engine = create_engine(
        f"sqlite+pysqlite:///{database_path}"
    )
    recovery_factory = sessionmaker(
        bind=recovery_engine,
        expire_on_commit=False,
    )

    CanonicalStore(
        staging_root=staging_root,
        canonical_root=canonical_root,
        metadata_session_factory=recovery_factory,
    )

    with recovery_factory() as recovered_session:
        assert recovered_session.scalars(select(MarketDataset)).all() == []
        assert recovered_session.scalars(select(MarketPartition)).all() == []
    assert not list(journal_root.iterdir())
    assert _all_files(staging_root) == []
    assert _all_files(canonical_root) == []


def test_committed_recovery_accepts_already_removed_partial(
    tmp_path: Path,
) -> None:
    database_path, staging_root, canonical_root = _spawn_crashed_publish(
        tmp_path,
        "after_metadata_commit",
    )
    journal = next(
        (canonical_root / "canonical-publish-journal").glob("txn-*.json")
    )
    payload = json.loads(journal.read_text(encoding="utf-8"))
    parent = canonical_root.joinpath(*payload["parent_parts"])
    removed_partial = parent / payload["names"]["partial_marker"]
    removed_partial.unlink()
    finals = {
        role: (
            (parent / payload["names"][role]).read_bytes(),
            (parent / payload["names"][role]).stat().st_ino,
        )
        for role in ("file", "manifest", "marker")
    }
    recovery_engine = create_engine(
        f"sqlite+pysqlite:///{database_path}"
    )
    recovery_factory = sessionmaker(
        bind=recovery_engine,
        expire_on_commit=False,
    )

    CanonicalStore(
        staging_root=staging_root,
        canonical_root=canonical_root,
        metadata_session_factory=recovery_factory,
    )

    for role, (content, inode) in finals.items():
        final = parent / payload["names"][role]
        assert final.read_bytes() == content
        assert final.stat().st_ino == inode
    with recovery_factory() as recovered_session:
        assert len(recovered_session.scalars(select(MarketDataset)).all()) == 1
        assert len(
            recovered_session.scalars(select(MarketPartition)).all()
        ) == 1
    assert not list(
        (canonical_root / "canonical-publish-journal").iterdir()
    )
    assert not list(canonical_root.rglob("*.partial"))


@pytest.mark.parametrize(
    ("fault_point", "remaining_partial_count"),
    [
        ("after_partial_marker_unlink", 2),
        ("after_partial_manifest_unlink", 1),
        ("after_partial_file_unlink", 0),
        ("before_journal_unlink", 0),
    ],
)
def test_committed_cleanup_crash_recovers_exact_publication(
    tmp_path: Path,
    fault_point: str,
    remaining_partial_count: int,
) -> None:
    database_path, staging_root, canonical_root = _spawn_crashed_publish(
        tmp_path,
        fault_point,
    )
    journal_root = canonical_root / "canonical-publish-journal"
    journal = next(journal_root.glob("txn-*.json"))
    payload = json.loads(journal.read_text(encoding="utf-8"))
    parent = canonical_root.joinpath(*payload["parent_parts"])
    finals = {
        role: (
            (parent / payload["names"][role]).read_bytes(),
            (parent / payload["names"][role]).stat().st_ino,
        )
        for role in ("file", "manifest", "marker")
    }
    assert len(list(canonical_root.rglob("*.partial"))) == (
        remaining_partial_count
    )
    recovery_engine = create_engine(
        f"sqlite+pysqlite:///{database_path}"
    )
    recovery_factory = sessionmaker(
        bind=recovery_engine,
        expire_on_commit=False,
    )

    def catalog_snapshot() -> tuple[tuple[tuple[object, ...], ...], ...]:
        with recovery_factory() as recovered_session:
            return tuple(
                tuple(
                    tuple(
                        getattr(row, column.name)
                        for column in model.__table__.columns
                    )
                    for row in recovered_session.scalars(
                        select(model).order_by(model.id)
                    ).all()
                )
                for model in (MarketDataset, MarketPartition)
            )

    metadata_before = catalog_snapshot()
    assert tuple(len(rows) for rows in metadata_before) == (1, 1)

    CanonicalStore(
        staging_root=staging_root,
        canonical_root=canonical_root,
        metadata_session_factory=recovery_factory,
    )

    assert catalog_snapshot() == metadata_before
    for role, (content, inode) in finals.items():
        final = parent / payload["names"][role]
        assert final.read_bytes() == content
        assert final.stat().st_ino == inode
    assert not list(journal_root.iterdir())
    assert not list(canonical_root.rglob("*.partial"))
    assert _all_files(staging_root) == []


@pytest.mark.parametrize(
    "tamper",
    [
        "absolute_name",
        "parent_traversal",
        "wrong_parent_parts",
        "wrong_transaction_id",
        "bool_inode",
        "forged_manifest_uri",
        "forged_created_prefix",
        "oversized_writer_version",
        "nonstring_writer_version",
    ],
)
def test_recovery_rejects_invalid_journal_before_any_mutation(
    tmp_path: Path,
    tamper: str,
) -> None:
    database_path = tmp_path / "metadata.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    staging_root = tmp_path / "staging"
    canonical_root = tmp_path / "canonical"
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_publish_worker,
        args=(
            str(staging_root),
            str(canonical_root),
            str(database_path),
            "after_journal_fsync",
        ),
    )
    process.start()
    process.join(timeout=20)
    assert process.exitcode == 91
    journal = next(
        (canonical_root / "canonical-publish-journal").glob("txn-*.json")
    )
    payload = json.loads(journal.read_text(encoding="utf-8"))
    sentinel = tmp_path / "outside-sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    if tamper == "absolute_name":
        payload["names"]["file"] = str(sentinel)
    elif tamper == "parent_traversal":
        payload["names"]["partial_file"] = "/".join(
            [".."] * 19 + ["outside-sentinel.txt"]
        )
    elif tamper == "wrong_parent_parts":
        payload["parent_parts"][-1] = "forged-window"
    elif tamper == "wrong_transaction_id":
        payload["transaction_id"] = "0" * 32
    elif tamper == "bool_inode":
        payload["staged"]["task_inode"] = True
    elif tamper == "forged_manifest_uri":
        payload["partition_manifest"]["file_uri"] = "../outside.parquet"
    elif tamper == "forged_created_prefix":
        payload["created_dirs"].append(["forged"])
    elif tamper == "oversized_writer_version":
        payload["manifest_document"]["writer"]["pyarrow_version"] = "x" * 129
    elif tamper == "nonstring_writer_version":
        payload["manifest_document"]["writer"]["duckdb_version"] = 1
    else:
        raise AssertionError(tamper)
    with journal.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    canonical_before = _tree_snapshot(canonical_root)
    staging_before = _tree_snapshot(staging_root)
    sentinel_before = sentinel.read_bytes()
    recovery_engine = create_engine(
        f"sqlite+pysqlite:///{database_path}"
    )
    recovery_factory = sessionmaker(
        bind=recovery_engine,
        expire_on_commit=False,
    )

    with pytest.raises(CanonicalPublishError) as error:
        CanonicalStore(
            staging_root=staging_root,
            canonical_root=canonical_root,
            metadata_session_factory=recovery_factory,
        )

    assert error.value.code == "CANONICAL_JOURNAL_INVALID"
    assert _tree_snapshot(canonical_root) == canonical_before
    assert _tree_snapshot(staging_root) == staging_before
    assert sentinel.read_bytes() == sentinel_before
    with recovery_factory() as recovered_session:
        assert recovered_session.scalars(select(MarketDataset)).all() == []
        assert recovered_session.scalars(select(MarketPartition)).all() == []


@pytest.mark.parametrize(
    "fault_point",
    [
        "after_intent_fsync",
        *[
            f"after_publish_directory_fsync_{index}"
            for index in range(1, 18)
        ],
        "after_partial_file_fsync",
        "after_partial_manifest_fsync",
        "after_partial_prepared_marker_fsync",
    ],
)
def test_intent_first_crashes_recover_without_canonical_artifacts(
    tmp_path: Path,
    fault_point: str,
) -> None:
    database_path, staging_root, canonical_root = _spawn_crashed_publish(
        tmp_path,
        fault_point,
    )
    recovery_engine = create_engine(
        f"sqlite+pysqlite:///{database_path}"
    )
    recovery_factory = sessionmaker(
        bind=recovery_engine,
        expire_on_commit=False,
    )

    CanonicalStore(
        staging_root=staging_root,
        canonical_root=canonical_root,
        metadata_session_factory=recovery_factory,
    )

    with recovery_factory() as recovered_session:
        assert recovered_session.scalars(select(MarketDataset)).all() == []
        assert recovered_session.scalars(select(MarketPartition)).all() == []
    assert _all_files(staging_root) == []
    assert _all_files(canonical_root) == []


@pytest.mark.parametrize("artifact", ["file", "manifest", "marker"])
def test_recovery_rejects_same_inode_committed_artifact_corruption(
    tmp_path: Path,
    artifact: str,
) -> None:
    database_path, staging_root, canonical_root = _spawn_crashed_publish(
        tmp_path,
        "after_metadata_commit",
    )
    if artifact == "file":
        target = next(canonical_root.rglob("part-00000.parquet"))
    elif artifact == "manifest":
        target = next(canonical_root.rglob("*.manifest.json"))
    else:
        target = next(
            path
            for path in canonical_root.rglob("*.prepared.json")
            if "canonical-publish-journal" not in path.parts
        )
    inode_before = target.stat().st_ino
    with target.open("r+b") as handle:
        handle.seek(0)
        handle.write(b"CORRUPTED")
        handle.flush()
        os.fsync(handle.fileno())
    assert target.stat().st_ino == inode_before
    canonical_before = _tree_snapshot(canonical_root)
    staging_before = _tree_snapshot(staging_root)
    recovery_engine = create_engine(
        f"sqlite+pysqlite:///{database_path}"
    )
    recovery_factory = sessionmaker(
        bind=recovery_engine,
        expire_on_commit=False,
    )

    with pytest.raises(CanonicalPublishError) as error:
        CanonicalStore(
            staging_root=staging_root,
            canonical_root=canonical_root,
            metadata_session_factory=recovery_factory,
        )

    assert error.value.code == "CANONICAL_RECOVERY_UNCERTAIN"
    assert _tree_snapshot(canonical_root) == canonical_before
    assert _tree_snapshot(staging_root) == staging_before


def test_marker_is_prepared_evidence_not_standalone_commit(
    tmp_path: Path,
    session: Session,
) -> None:
    store = _store(tmp_path, session)
    staged, validation = _stage_and_validate(store)

    published = store.publish(staged, _expectation(validation))

    assert published.prepared_marker_path.name.endswith(".prepared.json")
    marker = json.loads(
        published.prepared_marker_path.read_text(encoding="utf-8")
    )
    assert marker["state"] == "PREPARED"
    assert len(session.scalars(select(MarketPartition)).all()) == 1


def test_open_staged_closes_file_fd_when_identity_check_fails(
    tmp_path: Path,
    session: Session,
) -> None:
    store = _store(tmp_path, session)
    baseline = _open_fd_count()

    for _ in range(25):
        staged = store.stage(FakeAdapter().fetch_bars(_request()))
        invalid = replace(
            staged,
            file_identity=canonical_store_module._Identity(1, 1),
        )
        with pytest.raises(CanonicalStoreError):
            store.validate(invalid)

    assert _open_fd_count() == baseline


def test_publish_closes_journal_fd_when_parent_open_fails(
    tmp_path: Path,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, session)
    original_open_parts = canonical_store_module._open_directory_parts

    def fail_parent_open(root_fd, parts, **kwargs):
        if parts != ("canonical-publish-journal",):
            raise OSError("parent open failure")
        return original_open_parts(root_fd, parts, **kwargs)

    monkeypatch.setattr(
        canonical_store_module,
        "_open_directory_parts",
        fail_parent_open,
    )
    gc.collect()
    baseline = _open_fd_count()

    for _ in range(25):
        staged, validation = _stage_and_validate(store)
        with pytest.raises(CanonicalPublishError):
            store.publish(staged, _expectation(validation))

    gc.collect()
    assert _open_fd_count() == baseline


def test_each_created_partition_directory_fsyncs_its_parent(
    tmp_path: Path,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, session)
    staged, validation = _stage_and_validate(store)
    original_mkdir = os.mkdir
    original_fsync = os.fsync
    events: list[tuple[str, int]] = []

    def tracked_mkdir(path, mode=0o777, *, dir_fd=None):
        result = original_mkdir(path, mode, dir_fd=dir_fd)
        if dir_fd is not None:
            events.append(("mkdir", dir_fd))
        return result

    def tracked_fsync(descriptor):
        events.append(("fsync", descriptor))
        return original_fsync(descriptor)

    monkeypatch.setattr(os, "mkdir", tracked_mkdir)
    monkeypatch.setattr(os, "fsync", tracked_fsync)

    store.publish(staged, _expectation(validation))

    mkdir_indexes = [
        index
        for index, event in enumerate(events)
        if event[0] == "mkdir"
    ]
    assert len(mkdir_indexes) == 17
    for position, event_index in enumerate(mkdir_indexes):
        next_mkdir = (
            mkdir_indexes[position + 1]
            if position + 1 < len(mkdir_indexes)
            else len(events)
        )
        parent_fd = events[event_index][1]
        assert ("fsync", parent_fd) in events[event_index + 1 : next_mkdir]


@pytest.mark.parametrize(
    "preexisting",
    ["file_only", "manifest_only", "complete_publication"],
)
def test_intent_crash_never_deletes_preexisting_final_entries(
    tmp_path: Path,
    preexisting: str,
) -> None:
    database_path = tmp_path / "metadata.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    staging_root = tmp_path / "staging"
    canonical_root = tmp_path / "canonical"
    seed_store = CanonicalStore(
        staging_root=staging_root,
        canonical_root=canonical_root,
        metadata_session_factory=factory,
    )
    staged, validation = _stage_and_validate(seed_store)
    published = seed_store.publish(staged, _expectation(validation))
    final_paths = {
        "file": published.file_path,
        "manifest": published.manifest_path,
        "marker": published.prepared_marker_path,
    }
    if preexisting == "file_only":
        final_paths["manifest"].unlink()
        final_paths["marker"].unlink()
    elif preexisting == "manifest_only":
        final_paths["file"].unlink()
        final_paths["marker"].unlink()
    with factory() as cleanup_session:
        if preexisting != "complete_publication":
            cleanup_session.execute(delete(MarketPartition))
            cleanup_session.execute(delete(MarketDataset))
            cleanup_session.commit()
    preserved = {
        role: (path.read_bytes(), path.stat().st_ino)
        for role, path in final_paths.items()
        if path.exists()
    }
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_publish_worker,
        args=(
            str(staging_root),
            str(canonical_root),
            str(database_path),
            "after_intent_fsync",
        ),
    )
    process.start()
    process.join(timeout=20)
    assert process.exitcode == 91

    CanonicalStore(
        staging_root=staging_root,
        canonical_root=canonical_root,
        metadata_session_factory=factory,
    )

    for role, (content, inode) in preserved.items():
        assert final_paths[role].read_bytes() == content
        assert final_paths[role].stat().st_ino == inode
    assert not list(
        (canonical_root / "canonical-publish-journal").iterdir()
    )


def test_recovery_rejects_excess_journal_count_before_parsing(
    tmp_path: Path,
    session: Session,
) -> None:
    store = _store(tmp_path, session)
    journal_root = tmp_path / "canonical" / "canonical-publish-journal"
    for index in range(65):
        (journal_root / f"txn-{index:032x}.json").write_text(
            "{}",
            encoding="utf-8",
        )
    before = _tree_snapshot(tmp_path)

    with pytest.raises(CanonicalPublishError) as error:
        CanonicalStore(
            staging_root=tmp_path / "staging",
            canonical_root=tmp_path / "canonical",
            metadata_session_factory=sessionmaker(
                bind=session.get_bind(),
                expire_on_commit=False,
            ),
        )

    assert store is not None
    assert error.value.code == "CANONICAL_JOURNAL_COUNT_EXCEEDED"
    assert _tree_snapshot(tmp_path) == before


def test_recovery_rejects_oversized_journal_before_reading_json(
    tmp_path: Path,
    session: Session,
) -> None:
    store = _store(tmp_path, session)
    journal = (
        tmp_path
        / "canonical"
        / "canonical-publish-journal"
        / f"txn-{'a' * 32}.json"
    )
    journal.write_bytes(b"x" * (1024 * 1024 + 1))
    before = _tree_snapshot(tmp_path)

    with pytest.raises(CanonicalPublishError) as error:
        CanonicalStore(
            staging_root=tmp_path / "staging",
            canonical_root=tmp_path / "canonical",
            metadata_session_factory=sessionmaker(
                bind=session.get_bind(),
                expire_on_commit=False,
            ),
        )

    assert store is not None
    assert error.value.code == "CANONICAL_JOURNAL_TOO_LARGE"
    assert _tree_snapshot(tmp_path) == before


def test_recovery_rejects_deeply_nested_bounded_journal_before_mutation(
    tmp_path: Path,
    session: Session,
) -> None:
    store = _store(tmp_path, session)
    journal = (
        tmp_path
        / "canonical"
        / "canonical-publish-journal"
        / f"txn-{'a' * 32}.json"
    )
    content = ("[" * 10_000 + "0" + "]" * 10_000).encode()
    assert len(content) < 1024 * 1024
    journal.write_bytes(content)
    before = _tree_snapshot(tmp_path)

    with pytest.raises(CanonicalPublishError) as error:
        CanonicalStore(
            staging_root=tmp_path / "staging",
            canonical_root=tmp_path / "canonical",
            metadata_session_factory=sessionmaker(
                bind=session.get_bind(),
                expire_on_commit=False,
            ),
        )

    assert store is not None
    assert error.value.code == "CANONICAL_JOURNAL_INVALID"
    assert _tree_snapshot(tmp_path) == before
    assert session.scalars(select(MarketDataset)).all() == []
    assert session.scalars(select(MarketPartition)).all() == []


def test_two_uncommitted_intents_for_same_target_fail_before_mutation(
    tmp_path: Path,
) -> None:
    database_path, staging_root, canonical_root = _spawn_crashed_publish(
        tmp_path,
        "after_intent_fsync",
    )
    journal_root = canonical_root / "canonical-publish-journal"
    first = next(journal_root.glob("txn-*.json"))
    payload = json.loads(first.read_text(encoding="utf-8"))
    payload.setdefault(
        "final_entries",
        {
            role: {"present": False}
            for role in ("file", "manifest", "marker")
        },
    )
    first.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    second_tx = uuid.uuid4().hex
    duplicate = json.loads(json.dumps(payload))
    old_tx = duplicate["transaction_id"]
    duplicate["transaction_id"] = second_tx
    duplicate["staged"]["task_name"] = f"canonical-stage-{uuid.uuid4().hex}"
    for role in ("partial_file", "partial_manifest", "partial_marker"):
        duplicate["names"][role] = duplicate["names"][role].replace(
            old_tx,
            second_tx,
        )
    (journal_root / f"txn-{second_tx}.json").write_text(
        json.dumps(duplicate, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    before = _tree_snapshot(tmp_path)
    recovery_engine = create_engine(
        f"sqlite+pysqlite:///{database_path}"
    )
    recovery_factory = sessionmaker(
        bind=recovery_engine,
        expire_on_commit=False,
    )

    with pytest.raises(CanonicalPublishError) as error:
        CanonicalStore(
            staging_root=staging_root,
            canonical_root=canonical_root,
            metadata_session_factory=recovery_factory,
        )

    assert error.value.code == "CANONICAL_JOURNAL_CONFLICT"
    assert _tree_snapshot(tmp_path) == before


@pytest.mark.parametrize("loser_sort", ["before", "after"])
def test_committed_winner_and_prelink_loser_reconcile_in_any_sort_order(
    tmp_path: Path,
    loser_sort: str,
) -> None:
    database_path, staging_root, canonical_root = _spawn_crashed_publish(
        tmp_path,
        "after_metadata_commit",
    )
    journal_root = canonical_root / "canonical-publish-journal"
    winner_path = next(journal_root.glob("txn-*.json"))
    winner = json.loads(winner_path.read_text(encoding="utf-8"))
    parent = canonical_root.joinpath(*winner["parent_parts"])
    final_paths = {
        role: parent / winner["names"][role]
        for role in ("file", "manifest", "marker")
    }
    winner.setdefault(
        "final_entries",
        {
            role: {"present": False}
            for role in ("file", "manifest", "marker")
        },
    )
    winner_path.write_text(
        json.dumps(winner, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    loser_tx = "0" * 32 if loser_sort == "before" else "f" * 32
    loser = json.loads(json.dumps(winner))
    old_tx = loser["transaction_id"]
    loser["transaction_id"] = loser_tx
    loser["staged"]["task_name"] = f"canonical-stage-{uuid.uuid4().hex}"
    for role in ("partial_file", "partial_manifest", "partial_marker"):
        loser["names"][role] = loser["names"][role].replace(old_tx, loser_tx)
    loser["final_entries"] = {
        role: {
            "present": True,
            "device": path.stat().st_dev,
            "inode": path.stat().st_ino,
        }
        for role, path in final_paths.items()
    }
    (journal_root / f"txn-{loser_tx}.json").write_text(
        json.dumps(loser, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    preserved = {
        role: (path.read_bytes(), path.stat().st_ino)
        for role, path in final_paths.items()
    }
    recovery_engine = create_engine(
        f"sqlite+pysqlite:///{database_path}"
    )
    recovery_factory = sessionmaker(
        bind=recovery_engine,
        expire_on_commit=False,
    )

    CanonicalStore(
        staging_root=staging_root,
        canonical_root=canonical_root,
        metadata_session_factory=recovery_factory,
    )

    for role, (content, inode) in preserved.items():
        assert final_paths[role].read_bytes() == content
        assert final_paths[role].stat().st_ino == inode
    assert not list(journal_root.iterdir())
    with recovery_factory() as recovered_session:
        assert len(recovered_session.scalars(select(MarketPartition)).all()) == 1


def test_malformed_second_journal_blocks_independent_first_without_mutation(
    tmp_path: Path,
) -> None:
    database_path, staging_root, canonical_root = _spawn_crashed_publish(
        tmp_path,
        "after_intent_fsync",
    )
    journal_root = canonical_root / "canonical-publish-journal"
    (journal_root / f"txn-{'f' * 32}.json").write_text(
        "{}",
        encoding="utf-8",
    )
    before = _tree_snapshot(tmp_path)
    recovery_engine = create_engine(
        f"sqlite+pysqlite:///{database_path}"
    )
    recovery_factory = sessionmaker(
        bind=recovery_engine,
        expire_on_commit=False,
    )

    with pytest.raises(CanonicalPublishError) as error:
        CanonicalStore(
            staging_root=staging_root,
            canonical_root=canonical_root,
            metadata_session_factory=recovery_factory,
        )

    assert error.value.code == "CANONICAL_JOURNAL_INVALID"
    assert _tree_snapshot(tmp_path) == before


@pytest.mark.parametrize("runtime", ["pyarrow", "duckdb"])
def test_recovery_uses_stored_writer_versions_across_runtime_upgrade(
    tmp_path: Path,
    runtime: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path, staging_root, canonical_root = _spawn_crashed_publish(
        tmp_path,
        "after_metadata_commit",
    )
    module = (
        canonical_store_module.pa
        if runtime == "pyarrow"
        else canonical_store_module.duckdb
    )
    monkeypatch.setattr(module, "__version__", "99.0.0-upgraded")
    recovery_engine = create_engine(
        f"sqlite+pysqlite:///{database_path}"
    )
    recovery_factory = sessionmaker(
        bind=recovery_engine,
        expire_on_commit=False,
    )

    CanonicalStore(
        staging_root=staging_root,
        canonical_root=canonical_root,
        metadata_session_factory=recovery_factory,
    )

    assert not list(
        (canonical_root / "canonical-publish-journal").iterdir()
    )
    assert len(list(canonical_root.rglob("part-00000.parquet"))) == 1
