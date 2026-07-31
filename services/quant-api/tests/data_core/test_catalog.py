from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.data_core.catalog import (
    CatalogError,
    GapWindow,
    HistoricalCatalog,
    PartitionManifest,
)
from app.data_core.contracts import (
    BarFrequency,
    ContractValidationError,
    DatasetKey,
    DatasetKind,
)
from app.data_core.rqdata_adapter import MainMapRow
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
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE VIEW data_core_main_contract_map AS
                SELECT DISTINCT
                    id,
                    instrument_symbol AS symbol,
                    trade_date AS trading_day,
                    contract_code AS actual_contract,
                    provider,
                    rank,
                    rule,
                    data_version,
                    created_at
                FROM main_contract_map
                WHERE provider = 'rqdata'
                  AND rank = 1
                  AND rule = 'volume_open_interest'
                """
            )
        )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session


def _key(**overrides: object) -> DatasetKey:
    values = {
        "provider": "rqdata",
        "dataset_kind": DatasetKind.ACTUAL_DOMINANT,
        "symbol": "jm",
        "contract_or_series": "JM2609",
        "frequency": BarFrequency.M1,
        "adjustment": "none",
        "schema_version": "v1",
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


def _miss_one_entity_query(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    entity: type[Any],
) -> None:
    original_scalar = session.scalar
    missed = False

    def scalar_with_one_stale_read(statement: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal missed
        entities = {
            description.get("entity")
            for description in statement.column_descriptions
        }
        if not missed and entity in entities:
            missed = True
            return None
        return original_scalar(statement, *args, **kwargs)

    monkeypatch.setattr(session, "scalar", scalar_with_one_stale_read)


def test_dataset_key_normalizes_identity_and_is_frozen() -> None:
    key = DatasetKey(
        provider=" RQData ",
        dataset_kind=DatasetKind.ACTUAL_DOMINANT,
        symbol=" JM ",
        contract_or_series=" jm2609 ",
        frequency="1m",
        adjustment=" NONE ",
        schema_version=" v1 ",
    )

    assert key == _key()
    with pytest.raises(FrozenInstanceError):
        key.provider = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    "field",
    [
        "provider",
        "symbol",
        "contract_or_series",
        "adjustment",
        "schema_version",
    ],
)
def test_dataset_key_rejects_empty_parts(field: str) -> None:
    with pytest.raises(ContractValidationError) as error:
        _key(**{field: " \t "})

    assert error.value.code == "DATA_CONTRACT_INVALID"
    assert str(error.value) == "DATA_CONTRACT_INVALID"


def test_get_or_create_dataset_is_idempotent_for_one_logical_key(
    session: Session,
) -> None:
    catalog = HistoricalCatalog(session)

    first = catalog.get_or_create_dataset(
        _key(provider=" RQDATA ", symbol=" JM ")
    )
    second = catalog.get_or_create_dataset(_key())

    assert first.id == second.id
    assert session.scalars(select(MarketDataset)).all() == [first]
    assert (
        first.provider,
        first.dataset_kind,
        first.symbol,
        first.contract_or_series,
        first.frequency,
        first.adjustment,
        first.schema_version,
    ) == ("rqdata", "actual_dominant", "jm", "JM2609", "1m", "none", "v1")


def test_list_datasets_returns_only_the_requested_symbol(session: Session) -> None:
    catalog = HistoricalCatalog(session)
    jm = catalog.get_or_create_dataset(_key())
    catalog.get_or_create_dataset(
        _key(symbol="rb", contract_or_series="RB2609")
    )

    rows = catalog.list_datasets(symbol="JM")

    assert rows == [jm]


def test_get_or_create_dataset_arbitrates_unique_collision(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = HistoricalCatalog(session).get_or_create_dataset(_key())
    _miss_one_entity_query(session, monkeypatch, MarketDataset)

    resolved = HistoricalCatalog(session).get_or_create_dataset(_key())

    assert resolved.id == existing.id
    assert session.scalars(select(MarketDataset)).all() == [existing]


def test_dataset_database_constraint_rejects_duplicate_identity(
    session: Session,
) -> None:
    values = {
        "provider": "rqdata",
        "dataset_kind": "actual_dominant",
        "symbol": "jm",
        "contract_or_series": "JM2609",
        "frequency": "1m",
        "adjustment": "none",
        "schema_version": "v1",
    }
    session.add_all([MarketDataset(**values), MarketDataset(**values)])

    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize(
    "override",
    [
        {"dataset_kind": DatasetKind.CONTINUOUS},
        {"frequency": BarFrequency.D1},
        {"adjustment": "pre"},
        {"schema_version": "v2"},
    ],
)
def test_dataset_identity_keeps_each_canonical_dimension_distinct(
    session: Session,
    override: dict[str, object],
) -> None:
    catalog = HistoricalCatalog(session)

    original = catalog.get_or_create_dataset(_key())
    distinct = catalog.get_or_create_dataset(_key(**override))

    assert distinct.id != original.id
    assert len(session.scalars(select(MarketDataset)).all()) == 2


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("provider", "other"),
        ("dataset_kind", "synthetic"),
        ("frequency", "5m"),
        ("symbol", " "),
        ("symbol", "JM"),
        ("contract_or_series", "jm2609"),
        ("adjustment", "NONE"),
        ("schema_version", " v1"),
    ],
)
def test_dataset_database_checks_reject_noncanonical_identity(
    session: Session,
    field: str,
    invalid_value: str,
) -> None:
    values = {
        "provider": "rqdata",
        "dataset_kind": "actual_dominant",
        "symbol": "jm",
        "contract_or_series": "JM2609",
        "frequency": "1m",
        "adjustment": "none",
        "schema_version": "v1",
    }
    values[field] = invalid_value
    session.add(MarketDataset(**values))

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


def test_register_partition_arbitrates_identical_unique_collision(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = HistoricalCatalog(session)
    existing = catalog.register_partition(_key(), _manifest())
    _miss_one_entity_query(session, monkeypatch, MarketPartition)

    resolved = catalog.register_partition(_key(), _manifest())

    assert resolved.id == existing.id
    assert session.scalars(select(MarketPartition)).all() == [existing]


def test_register_partition_translates_collision_with_different_facts(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = HistoricalCatalog(session)
    existing = catalog.register_partition(_key(), _manifest())
    _miss_one_entity_query(session, monkeypatch, MarketPartition)

    with pytest.raises(CatalogError) as error:
        catalog.register_partition(
            _key(),
            _manifest(file_uri="file://conflicting.parquet"),
        )

    assert error.value.code == "CATALOG_PARTITION_CONFLICT"
    assert session.scalars(select(MarketPartition)).all() == [existing]


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


def test_partition_windows_use_utc_identity_across_offsets(
    session: Session,
) -> None:
    plus_eight = timezone(timedelta(hours=8))
    catalog = HistoricalCatalog(session)
    utc_partition = catalog.register_partition(_key(), _manifest())
    offset_manifest = _manifest(
        coverage_start=START.astimezone(plus_eight),
        coverage_end=END.astimezone(plus_eight),
    )

    offset_partition = catalog.register_partition(_key(), offset_manifest)

    assert offset_manifest.coverage_start == START
    assert offset_manifest.coverage_start.tzinfo is UTC
    assert offset_partition.id == utc_partition.id
    assert session.scalars(select(MarketPartition)).all() == [utc_partition]


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


def test_record_gap_arbitrates_identical_unique_collision(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = HistoricalCatalog(session)
    existing = catalog.record_gap(_key(), _gap())
    _miss_one_entity_query(session, monkeypatch, DataGap)

    resolved = catalog.record_gap(_key(), _gap())

    assert resolved.id == existing.id
    assert session.scalars(select(DataGap)).all() == [existing]


def test_record_gap_translates_collision_with_different_facts(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = HistoricalCatalog(session)
    existing = catalog.record_gap(_key(), _gap())
    _miss_one_entity_query(session, monkeypatch, DataGap)

    with pytest.raises(CatalogError) as error:
        catalog.record_gap(
            _key(),
            _gap(reason_code="provider_outage"),
        )

    assert error.value.code == "CATALOG_GAP_CONFLICT"
    assert session.scalars(select(DataGap)).all() == [existing]


def test_gap_windows_use_utc_identity_across_offsets(session: Session) -> None:
    plus_eight = timezone(timedelta(hours=8))
    catalog = HistoricalCatalog(session)
    utc_gap = catalog.record_gap(_key(), _gap())
    offset_gap = _gap(
        gap_start=START.astimezone(plus_eight),
        gap_end=END.astimezone(plus_eight),
    )

    resolved = catalog.record_gap(_key(), offset_gap)

    assert offset_gap.gap_start == START
    assert offset_gap.gap_start.tzinfo is UTC
    assert resolved.id == utc_gap.id
    assert session.scalars(select(DataGap)).all() == [utc_gap]


def test_gap_details_are_detached_and_tuples_become_json_arrays() -> None:
    source = {
        "nested": {
            "values": [1, {"label": "original"}],
            "coordinates": (2, 3),
        }
    }

    gap = _gap(details=source)
    source["nested"]["values"].append(4)
    source["nested"]["values"][1]["label"] = "mutated"

    assert gap.details == {
        "nested": {
            "values": [1, {"label": "original"}],
            "coordinates": [2, 3],
        }
    }


def test_persisted_gap_details_detach_from_value_object_nested_state(
    session: Session,
) -> None:
    catalog = HistoricalCatalog(session)
    gap = _gap(details={"nested": {"values": [1]}})
    persisted = catalog.record_gap(_key(), gap)

    gap.details["nested"]["values"].append(2)  # type: ignore[index,union-attr]

    assert persisted.details == {"nested": {"values": [1]}}
    resolved = catalog.record_gap(
        _key(),
        _gap(details={"nested": {"values": [1]}}),
    )
    assert resolved.id == persisted.id


@pytest.mark.parametrize(
    "invalid_details",
    [
        {"bad": object()},
        {"bad": {1, 2}},
        {1: "non-string-key"},
        {"bad": float("nan")},
        {"bad": float("inf")},
    ],
)
def test_gap_details_reject_non_json_values(
    invalid_details: object,
) -> None:
    with pytest.raises(CatalogError) as error:
        _gap(details=invalid_details)

    assert error.value.code == "CATALOG_GAP_INVALID"


def test_gap_details_reject_cyclic_json_without_recursion_error() -> None:
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic

    with pytest.raises(CatalogError) as error:
        _gap(details=cyclic)

    assert error.value.code == "CATALOG_GAP_INVALID"


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

    view_rows = session.execute(
        text(
            """
            SELECT provider, rank, rule, symbol, trading_day, actual_contract
            FROM data_core_main_contract_map
            """
        )
    ).all()
    assert view_rows == [
        (
            "rqdata",
            1,
            "volume_open_interest",
            "jm",
            "2026-07-30",
            "JM2609",
        )
    ]
    assert mapping.contract_code == "JM2609"
    assert mapping.actual_contract == "JM2609"
    assert mapping.trading_day == target_day
    assert mapping.data_version == "formal"


def test_main_contract_lookup_reads_only_from_canonical_view(
    session: Session,
) -> None:
    target_day = date(2026, 7, 30)
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=target_day,
            rank=1,
            contract_code="JM2609",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="hidden-by-test-view",
        )
    )
    session.commit()
    session.execute(text("DROP VIEW data_core_main_contract_map"))
    session.execute(
        text(
            """
            CREATE VIEW data_core_main_contract_map AS
            SELECT DISTINCT
                id,
                instrument_symbol AS symbol,
                trade_date AS trading_day,
                contract_code AS actual_contract,
                provider,
                rank,
                rule,
                data_version,
                created_at
            FROM main_contract_map
            WHERE 0
            """
        )
    )
    session.commit()

    with pytest.raises(CatalogError) as error:
        HistoricalCatalog(session).get_main_contract_mapping(
            instrument_symbol="jm",
            trade_date=target_day,
        )

    assert error.value.code == "CATALOG_MAIN_CONTRACT_MAPPING_NOT_FOUND"


def test_main_contract_view_conflicts_fail_visible(
    session: Session,
) -> None:
    target_day = date(2026, 7, 30)
    session.add_all(
        [
            MainContractMap(
                instrument_symbol="jm",
                trade_date=target_day,
                rank=1,
                contract_code="JM2609",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="v1",
            ),
            MainContractMap(
                instrument_symbol="jm",
                trade_date=target_day,
                rank=1,
                contract_code="JM2611",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="v2",
            ),
        ]
    )
    session.commit()

    with pytest.raises(ValueError, match="ACTUAL_CONTRACT_MAPPING_CONFLICT"):
        HistoricalCatalog(session).get_main_contract_mapping(
            instrument_symbol="jm",
            trade_date=target_day,
        )


def test_main_contract_view_selects_latest_version_deterministically(
    session: Session,
) -> None:
    target_day = date(2026, 7, 30)
    session.add_all(
        [
            MainContractMap(
                instrument_symbol="jm",
                trade_date=target_day,
                rank=1,
                contract_code="JM2609",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="older",
                created_at=datetime(2026, 7, 30, 1, tzinfo=UTC),
            ),
            MainContractMap(
                instrument_symbol="jm",
                trade_date=target_day,
                rank=1,
                contract_code="JM2609",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="newer",
                created_at=datetime(2026, 7, 30, 2, tzinfo=UTC),
            ),
        ]
    )
    session.commit()

    mapping = HistoricalCatalog(session).get_main_contract_mapping(
        instrument_symbol="jm",
        trade_date=target_day,
    )

    assert mapping.actual_contract == "JM2609"
    assert mapping.data_version == "newer"


def test_main_contract_view_duplicate_version_and_invalid_series_fail_visible(
    session: Session,
) -> None:
    target_day = date(2026, 7, 30)
    session.add_all(
        [
            MainContractMap(
                instrument_symbol="jm",
                trade_date=target_day,
                rank=1,
                contract_code="JM2609",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="duplicate",
            ),
            MainContractMap(
                instrument_symbol="JM",
                trade_date=target_day,
                rank=1,
                contract_code="JM2609",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="duplicate",
            ),
        ]
    )
    session.commit()

    with pytest.raises(ValueError, match="ACTUAL_CONTRACT_MAPPING_DUPLICATE"):
        HistoricalCatalog(session).get_main_contract_mapping(
            instrument_symbol="jm",
            trade_date=target_day,
        )

    session.query(MainContractMap).delete()
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=target_day,
            rank=1,
            contract_code="JM.MAIN",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="invalid-series",
        )
    )
    session.commit()

    with pytest.raises(ValueError, match="ACTUAL_CONTRACT_MAPPING_INVALID"):
        HistoricalCatalog(session).get_main_contract_mapping(
            instrument_symbol="jm",
            trade_date=target_day,
        )


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


def test_clear_gaps_covered_by_published_window_preserves_partial_gap(
    session: Session,
) -> None:
    catalog = HistoricalCatalog(session)
    full_gap = _gap()
    partial_gap = _gap(
        gap_start=datetime(2026, 7, 2, tzinfo=UTC),
        gap_end=datetime(2026, 7, 3, tzinfo=UTC),
    )
    catalog.record_gap(_key(), full_gap)
    catalog.record_gap(_key(), partial_gap)
    session.commit()

    cleared = catalog.clear_gaps_covered_by(
        _key(),
        coverage_start=START,
        coverage_end=END,
    )

    assert cleared == 1
    remaining = catalog.list_gaps(_key())
    assert len(remaining) == 1
    assert remaining[0].gap_start.date() == partial_gap.gap_start.date()
    assert remaining[0].gap_end.date() == partial_gap.gap_end.date()


def test_register_rank1_mapping_is_idempotent_but_rejects_same_version_conflict(
    session: Session,
) -> None:
    catalog = HistoricalCatalog(session)
    row = MainMapRow(
        symbol="jm",
        trading_day=date(2026, 7, 30),
        actual_contract="JM2609",
        rank=1,
        data_version="rqdata-rank1-20260730",
    )

    first = catalog.register_main_contract_mapping(row)
    second = catalog.register_main_contract_mapping(row)

    assert first.id == second.id
    with pytest.raises(CatalogError) as error:
        catalog.register_main_contract_mapping(
            MainMapRow(
                symbol="jm",
                trading_day=row.trading_day,
                actual_contract="JM2611",
                rank=1,
                data_version=row.data_version,
            )
        )

    assert error.value.code == "CATALOG_MAIN_CONTRACT_MAPPING_CONFLICT"
