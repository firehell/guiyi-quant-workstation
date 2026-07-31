from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Sequence

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.data_core.bar_schema import CanonicalBar
from app.data_core.canonical_store import (
    CANONICAL_PARQUET_PROFILE_ID,
    CANONICAL_PARQUET_SCHEMA,
    CANONICAL_PARQUET_WRITER_PARAMETERS,
    CanonicalPublishError,
    CanonicalStore,
    PublishExpectation,
)
from app.data_core.contracts import BarFrequency, DatasetKey, DatasetKind
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


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
        metadata_session=session,
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


def _expectation(validation) -> PublishExpectation:
    return PublishExpectation.from_validation(
        validation,
        manifest_version="canonical-manifest-v1",
    )


def _all_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file())


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
                close
            FROM read_parquet(?)
            ORDER BY bar_end
            """,
            [str(published.file_path)],
        ).fetchall()
    assert rows[0][:5] == (
        "rqdata",
        "actual_dominant",
        "jm",
        "JM2609",
        "1m",
    )
    assert rows[0][5:] == (
        1782867660000000,
        TRADING_DAY,
        Decimal("100.000000000000000001"),
        Decimal("101.125000000000000000"),
    )
    assert published.partition_manifest.coverage_start == START
    assert published.partition_manifest.coverage_end == SECOND
    assert published.partition_manifest.row_count == 2
    assert (
        hashlib.sha256(published.file_path.read_bytes()).hexdigest()
        == published.file_checksum
        == published.partition_manifest.checksum
    )
    manifest = json.loads(published.manifest_path.read_text())
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
            store = _store(tmp_path / str(index), session)
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

    assert _all_files(tmp_path) == []


@pytest.mark.parametrize(
    "bad_component",
    ["../escape", "nested/path", "/absolute", "a\\b"],
)
def test_malicious_dataset_identity_creates_no_paths(
    tmp_path: Path,
    session: Session,
    bad_component: str,
) -> None:
    store = _store(tmp_path, session)
    dataset = _key(symbol=bad_component)
    request = _request(dataset)
    first = _bar(FIRST, "101.125")
    second = _bar(SECOND, "101.25")
    object.__setattr__(first, "symbol", bad_component)
    object.__setattr__(second, "symbol", bad_component)

    with pytest.raises(QualityValidationError):
        store.stage(
            ProviderBarBatch(
                request=request,
                bars=(first, second),
                data_version="provider-final-20260701",
            )
        )

    assert _all_files(tmp_path) == []


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
    assert _all_files(tmp_path) == []
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
    assert _all_files(tmp_path) == []
    assert session.scalars(select(MarketDataset)).all() == []
