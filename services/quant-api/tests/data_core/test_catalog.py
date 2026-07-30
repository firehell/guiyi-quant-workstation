from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.data_core.catalog import (
    CatalogError,
    DatasetKey,
    GapWindow,
    HistoricalCatalog,
    PartitionManifest,
)
from app.db.base import Base
from app.models.data_center import MainContractMap
from app.models.data_core import DataGap, MarketDataset, MarketPartition


SHA_A = "a" * 64
SHA_B = "b" * 64
START = datetime(2026, 7, 1, tzinfo=UTC)
END = datetime(2026, 7, 2, tzinfo=UTC)


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


def _key(**overrides: str) -> DatasetKey:
    values = {
        "provider": "rqdata",
        "data_type": "bars",
        "instrument_symbol": "jm",
        "contract_code": "JM2609",
        "period": "1m",
    }
    values.update(overrides)
    return DatasetKey(**values)


def _manifest(**overrides: object) -> PartitionManifest:
    values: dict[str, object] = {
        "coverage_start": START,
        "coverage_end": END,
        "manifest_version": "manifest-v1",
        "manifest_uri": "manifest://jm/2026-07-01",
        "manifest_digest": SHA_A,
        "file_uri": "file://jm/2026-07-01.parquet",
        "checksum": SHA_B,
        "row_count": 345,
    }
    values.update(overrides)
    return PartitionManifest(**values)


def _gap(**overrides: object) -> GapWindow:
    values: dict[str, object] = {
        "gap_start": START,
        "gap_end": END,
        "reason_code": "missing_source_rows",
        "details": {"expected": 345, "actual": 0},
    }
    values.update(overrides)
    return GapWindow(**values)


def test_dataset_key_normalizes_identity_and_is_frozen() -> None:
    key = DatasetKey(
        provider=" RQData ",
        data_type=" BARS ",
        instrument_symbol=" JM ",
        contract_code=" JM2609 ",
        period=" 1M ",
    )

    assert key == _key()
    with pytest.raises(FrozenInstanceError):
        key.provider = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    "field",
    ["provider", "data_type", "instrument_symbol", "contract_code", "period"],
)
def test_dataset_key_rejects_empty_parts(field: str) -> None:
    with pytest.raises(CatalogError) as error:
        _key(**{field: " \t "})

    assert error.value.code == "CATALOG_DATASET_KEY_INVALID"
    assert str(error.value) == "CATALOG_DATASET_KEY_INVALID"


def test_get_or_create_dataset_is_idempotent_for_one_logical_key(
    session: Session,
) -> None:
    catalog = HistoricalCatalog(session)

    first = catalog.get_or_create_dataset(
        _key(provider=" RQDATA ", instrument_symbol=" JM ")
    )
    second = catalog.get_or_create_dataset(_key())

    assert first.id == second.id
    assert session.scalars(select(MarketDataset)).all() == [first]
    assert (
        first.provider,
        first.data_type,
        first.instrument_symbol,
        first.contract_code,
        first.period,
    ) == ("rqdata", "bars", "jm", "JM2609", "1m")


def test_dataset_database_constraint_rejects_duplicate_identity(
    session: Session,
) -> None:
    values = {
        "provider": "rqdata",
        "data_type": "bars",
        "instrument_symbol": "jm",
        "contract_code": "JM2609",
        "period": "1m",
    }
    session.add_all([MarketDataset(**values), MarketDataset(**values)])

    with pytest.raises(IntegrityError):
        session.commit()


def test_register_partition_is_create_only_and_idempotent(
    session: Session,
) -> None:
    catalog = HistoricalCatalog(session)
    manifest = _manifest()

    first = catalog.register_partition(_key(), manifest)
    second = catalog.register_partition(_key(), manifest)

    assert first.id == second.id
    assert session.scalars(select(MarketPartition)).all() == [first]


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        ("manifest_uri", "manifest://different"),
        ("manifest_digest", "c" * 64),
        ("file_uri", "file://different.parquet"),
        ("checksum", "d" * 64),
        ("row_count", 346),
        ("overlap_reason", "repair_overlay"),
    ],
)
def test_register_partition_rejects_conflicting_immutable_facts(
    session: Session,
    changed_field: str,
    changed_value: object,
) -> None:
    catalog = HistoricalCatalog(session)
    original = _manifest()
    catalog.register_partition(_key(), original)

    with pytest.raises(CatalogError) as error:
        catalog.register_partition(
            _key(),
            replace(original, **{changed_field: changed_value}),
        )

    assert error.value.code == "CATALOG_PARTITION_CONFLICT"
    assert str(error.value) == "CATALOG_PARTITION_CONFLICT"


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        ({"coverage_start": END, "coverage_end": START}, "CATALOG_TIME_WINDOW_INVALID"),
        (
            {"coverage_start": START.replace(tzinfo=None)},
            "CATALOG_TIME_WINDOW_INVALID",
        ),
        ({"manifest_digest": "A" * 64}, "CATALOG_SHA256_INVALID"),
        ({"manifest_digest": "a" * 63}, "CATALOG_SHA256_INVALID"),
        ({"checksum": "g" * 64}, "CATALOG_SHA256_INVALID"),
        ({"row_count": -1}, "CATALOG_ROW_COUNT_INVALID"),
        ({"overlap_reason": "manual_override"}, "CATALOG_OVERLAP_REASON_INVALID"),
    ],
)
def test_partition_manifest_rejects_invalid_facts(
    overrides: dict[str, object],
    expected_code: str,
) -> None:
    with pytest.raises(CatalogError) as error:
        _manifest(**overrides)

    assert error.value.code == expected_code
    assert str(error.value) == expected_code


def test_partition_database_checks_reject_invalid_direct_insert(
    session: Session,
) -> None:
    dataset = HistoricalCatalog(session).get_or_create_dataset(_key())
    session.add(
        MarketPartition(
            dataset_id=dataset.id,
            coverage_start=END,
            coverage_end=START,
            manifest_version="manifest-v1",
            manifest_uri="manifest://jm",
            manifest_digest="A" * 64,
            file_uri="file://jm.parquet",
            checksum="g" * 64,
            row_count=-1,
            overlap_reason="manual_override",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_record_gap_is_create_only_and_rejects_conflicting_facts(
    session: Session,
) -> None:
    catalog = HistoricalCatalog(session)
    gap = _gap()

    first = catalog.record_gap(_key(), gap)
    second = catalog.record_gap(_key(), gap)

    assert first.id == second.id
    assert session.scalars(select(DataGap)).all() == [first]

    with pytest.raises(CatalogError) as error:
        catalog.record_gap(
            _key(),
            replace(gap, reason_code="provider_outage"),
        )
    assert error.value.code == "CATALOG_GAP_CONFLICT"
    assert str(error.value) == "CATALOG_GAP_CONFLICT"


@pytest.mark.parametrize(
    "overrides",
    [
        {"gap_start": END, "gap_end": START},
        {"gap_end": END.replace(tzinfo=None)},
        {"reason_code": "   "},
    ],
)
def test_gap_window_rejects_invalid_facts(overrides: dict[str, object]) -> None:
    with pytest.raises(CatalogError):
        _gap(**overrides)


def test_list_methods_order_windows_chronologically(session: Session) -> None:
    catalog = HistoricalCatalog(session)
    key = _key()
    later_start = START + timedelta(days=3)
    later_end = END + timedelta(days=3)

    later_partition = catalog.register_partition(
        key,
        _manifest(
            coverage_start=later_start,
            coverage_end=later_end,
            manifest_version="manifest-v2",
            manifest_uri="manifest://later",
        ),
    )
    earlier_partition = catalog.register_partition(key, _manifest())
    later_gap = catalog.record_gap(
        key,
        _gap(
            gap_start=later_start,
            gap_end=later_end,
            reason_code="later_gap",
        ),
    )
    earlier_gap = catalog.record_gap(key, _gap())

    assert catalog.list_partitions(key) == [earlier_partition, later_partition]
    assert catalog.list_gaps(key) == [earlier_gap, later_gap]


def test_strict_main_contract_lookup_uses_shared_formal_rank_one_semantics(
    session: Session,
) -> None:
    target_day = date(2026, 7, 30)
    session.add_all(
        [
            MainContractMap(
                instrument_symbol="jm",
                trade_date=target_day,
                rank=2,
                contract_code="JM2611",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="rank-2",
            ),
            MainContractMap(
                instrument_symbol="jm",
                trade_date=target_day,
                rank=1,
                contract_code="JM2605",
                rule="other",
                provider="rqdata",
                data_version="wrong-rule",
            ),
            MainContractMap(
                instrument_symbol="jm",
                trade_date=target_day,
                rank=1,
                contract_code="JM2607",
                rule="volume_open_interest",
                provider="other",
                data_version="wrong-provider",
            ),
            MainContractMap(
                instrument_symbol="jm",
                trade_date=target_day,
                rank=1,
                contract_code="JM2609",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="formal",
            ),
        ]
    )
    session.commit()

    mapping = HistoricalCatalog(session).get_main_contract_mapping(
        instrument_symbol=" JM ",
        trade_date=target_day,
    )

    assert mapping.contract_code == "JM2609"
    assert mapping.data_version == "formal"


def test_strict_main_contract_lookup_raises_stable_not_found(
    session: Session,
) -> None:
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=date(2026, 7, 30),
            rank=2,
            contract_code="JM2611",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="rank-2",
        )
    )
    session.commit()

    with pytest.raises(CatalogError) as error:
        HistoricalCatalog(session).get_main_contract_mapping(
            instrument_symbol="jm",
            trade_date=date(2026, 7, 30),
        )

    assert error.value.code == "CATALOG_MAIN_CONTRACT_MAPPING_NOT_FOUND"
    assert str(error.value) == "CATALOG_MAIN_CONTRACT_MAPPING_NOT_FOUND"
