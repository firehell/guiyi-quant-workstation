from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
from typing import Sequence

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import create_engine, select
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


def _expectation(validation) -> PublishExpectation:
    return PublishExpectation.from_validation(
        validation,
        manifest_version="canonical-manifest-v1",
    )


def _crash_publish_worker(
    staging_root: str,
    canonical_root: str,
    database_path: str,
    fault_point: str,
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
    staged, validation = _stage_and_validate(store)
    store.publish(staged, _expectation(validation))


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
    assert _tree_snapshot(tmp_path / "canonical") == canonical_before
    assert _tree_snapshot(tmp_path / "staging") == staging_before


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
    assert _tree_snapshot(tmp_path) == before


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
    assert _tree_snapshot(tmp_path) == before


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
    assert published.commit_marker_path.is_file()
    assert len(session.scalars(select(MarketPartition)).all()) == 1
    assert len(created_sessions) == 2
    assert created_sessions[0] is not created_sessions[1]
    assert not (tmp_path / "canonical" / "canonical-publish-journal").exists()


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
    assert _tree_snapshot(tmp_path / "canonical") == canonical_before
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
    assert not (canonical_root / "canonical-publish-journal").exists()
    assert not list(canonical_root.rglob("*.partial"))
    if committed:
        assert len(datasets) == 1
        assert len(partitions) == 1
        assert len(list(canonical_root.rglob("part-00000.parquet"))) == 1
        assert len(list(canonical_root.rglob("*.manifest.json"))) == 1
        assert len(list(canonical_root.rglob("*.committed.json"))) == 1
    else:
        assert datasets == []
        assert partitions == []
        assert _all_files(canonical_root) == []
        assert _tree_snapshot(canonical_root) == {}
        assert _tree_snapshot(staging_root) == {}
