from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.data_core.canonical_store import CanonicalStore
from app.data_core.bar_schema import CanonicalBar
from app.data_core.catalog import HistoricalCatalog
from app.data_core.contracts import (
    BarFrequency,
    BarsResult,
    DatasetKey,
    DatasetKind,
)
from app.data_core.rqdata_adapter import (
    ProviderBarBatch,
    ProviderBarRequest,
    TradingSessionCoverage,
)
from app.data_core.task07_migration import (
    Task07RepairTarget,
    Task07MigrationError,
    execute_task07_prepared_batch,
    prepare_legacy_parquet_batch,
    load_task07_rank1_map,
    resolve_task07_provider_sessions,
    verify_task07_published_batch,
)
from app.data_core.task07 import (
    AssetDisposition,
    _build_inventory_index as build_inventory_index,
    build_migration_plan,
    classify_asset,
    collect_task07_assets,
)
from app.data_core import task07 as task07_module
from app.data_core.cli_service import run_data_core_command
from app.models.data_center import Instrument, MainContractMap, TradingCalendar, TradingSession
from app.data_core import task07_migration as migration_module


def _write_legacy_minute(path: Path, *, trading_day: date) -> str:
    pq.write_table(
        pa.table(
            {
                "datetime": [datetime(2026, 7, 31, 21, 1)],
                "trading_day": [trading_day],
                "open": [Decimal("100.1")],
                "high": [Decimal("101.2")],
                "low": [Decimal("99.8")],
                "close": [Decimal("100.7")],
                "volume": [Decimal("12")],
                "turnover": [Decimal("1208.4")],
                "open_interest": [Decimal("30")],
            }
        ),
        path,
    )
    return sha256(path.read_bytes()).hexdigest()


def _dataset() -> DatasetKey:
    return DatasetKey(
        provider="rqdata",
        dataset_kind=DatasetKind.ACTUAL_DOMINANT,
        symbol="jm",
        contract_or_series="JM2609",
        frequency=BarFrequency.M1,
        adjustment="none",
        schema_version="canonical-bar-v1",
    )


def _friday_night_session() -> TradingSessionCoverage:
    return TradingSessionCoverage(
        trading_day=date(2026, 8, 3),
        start=datetime(2026, 7, 31, 13, 0, tzinfo=UTC),
        end=datetime(2026, 7, 31, 13, 1, tzinfo=UTC),
        expected_bar_ends=(datetime(2026, 7, 31, 13, 1, tzinfo=UTC),),
    )


def _repair_bar() -> CanonicalBar:
    return CanonicalBar(
        provider="rqdata",
        dataset_kind=DatasetKind.ACTUAL_DOMINANT,
        symbol="jm",
        contract_or_series="JM2609",
        frequency=BarFrequency.M1,
        bar_end=datetime(2026, 7, 31, 13, 1, tzinfo=UTC),
        trading_day=date(2026, 8, 3),
        open=Decimal("100.1"),
        high=Decimal("101.2"),
        low=Decimal("99.8"),
        close=Decimal("100.7"),
        volume=Decimal("12"),
        turnover=Decimal("1208.4"),
        open_interest=Decimal("30"),
        adjustment="none",
        schema_version="canonical-bar-v1",
    )


def _direct_repair_target() -> Task07RepairTarget:
    return Task07RepairTarget(
        operation="rqdata_redownload",
        dataset=_dataset(),
        start=datetime(2026, 7, 31, 13, 0, tzinfo=UTC),
        end=datetime(2026, 7, 31, 13, 1, tzinfo=UTC),
        source_action_ids=(1,),
        source_action_digests=("1" * 64,),
        target_digest="2" * 64,
    )


def test_direct_repair_fetches_exact_window_and_publishes_once() -> None:
    target = _direct_repair_target()
    session = _friday_night_session()
    observed: dict[str, object] = {}

    def fetch(request: ProviderBarRequest) -> ProviderBarBatch:
        observed["request"] = request
        return ProviderBarBatch(
            request=request,
            bars=(_repair_bar(),),
            data_version="rqdata-test-repair-v1",
        )

    def publish(batch: ProviderBarBatch, lineage: object) -> dict[str, object]:
        observed["batch"] = batch
        observed["lineage"] = lineage
        return {"publication_status": "published", "receipt_digest": "3" * 64}

    receipt = migration_module.execute_task07_repair_target(
        target,
        sessions=(session,),
        fetch_direct=fetch,
        read_canonical_1m=lambda _target: pytest.fail("direct repair must not read canonical 1m"),
        publish=publish,
        record_gap=lambda *_args, **_kwargs: pytest.fail("successful repair must not record a gap"),
        publication_state_unchanged=lambda _target: True,
    )

    request = observed["request"]
    assert isinstance(request, ProviderBarRequest)
    assert request.dataset == target.dataset
    assert (request.start, request.end) == (target.start, target.end)
    assert observed["lineage"] is None
    assert receipt["status"] == "passed"
    assert receipt["calls_rqdata"] is True


def test_direct_repair_failure_records_gap_without_publishing() -> None:
    target = _direct_repair_target()
    recorded: list[tuple[Task07RepairTarget, str]] = []

    receipt = migration_module.execute_task07_repair_target(
        target,
        sessions=(_friday_night_session(),),
        fetch_direct=lambda _request: (_ for _ in ()).throw(
            Exception("untyped provider SDK failure")
        ),
        read_canonical_1m=lambda _target: pytest.fail("direct repair must not read canonical 1m"),
        publish=lambda _batch, _lineage: pytest.fail("failed repair must not publish"),
        record_gap=lambda repair_target, reason: recorded.append((repair_target, reason)),
        publication_state_unchanged=lambda _target: True,
    )

    assert recorded == [(target, "task07_rqdata_redownload_failed")]
    assert receipt["status"] == "data_gap"
    assert receipt["calls_rqdata"] is True
    assert receipt["publication"] is None


def test_repair_publish_failure_records_gap_only_when_state_is_unchanged() -> None:
    target = _direct_repair_target()
    recorded: list[tuple[Task07RepairTarget, str]] = []

    def fetch(request: ProviderBarRequest) -> ProviderBarBatch:
        return ProviderBarBatch(
            request=request,
            bars=(_repair_bar(),),
            data_version="rqdata-test-repair-v1",
        )

    receipt = migration_module.execute_task07_repair_target(
        target,
        sessions=(_friday_night_session(),),
        fetch_direct=fetch,
        read_canonical_1m=lambda _target: pytest.fail(
            "direct repair must not read canonical 1m"
        ),
        publish=lambda _batch, _lineage: (_ for _ in ()).throw(
            OSError("publish failed before catalog commit")
        ),
        record_gap=lambda repair_target, reason: recorded.append(
            (repair_target, reason)
        ),
        publication_state_unchanged=lambda _target: True,
    )

    assert recorded == [(target, "task07_rqdata_redownload_publish_failed")]
    assert receipt["status"] == "data_gap"

    with pytest.raises(
        migration_module.Task07MigrationError,
        match="TASK07_REPAIR_PUBLICATION_STATE_AMBIGUOUS",
    ):
        migration_module.execute_task07_repair_target(
            target,
            sessions=(_friday_night_session(),),
            fetch_direct=fetch,
            read_canonical_1m=lambda _target: pytest.fail(
                "direct repair must not read canonical 1m"
            ),
            publish=lambda _batch, _lineage: (_ for _ in ()).throw(
                OSError("publish failed after catalog commit")
            ),
            record_gap=lambda *_args: pytest.fail(
                "ambiguous publication must not record a gap"
            ),
            publication_state_unchanged=lambda _target: False,
        )


def test_aggregate_repair_reads_only_canonical_1m_and_publishes_lineage() -> None:
    target_dataset = _aggregate_dataset()
    target = Task07RepairTarget(
        operation="canonical_1m_reaggregate",
        dataset=target_dataset,
        start=datetime(2026, 3, 31, 13, 0, tzinfo=UTC),
        end=datetime(2026, 3, 31, 13, 5, tzinfo=UTC),
        source_action_ids=(2,),
        source_action_digests=("4" * 64,),
        target_digest="5" * 64,
    )
    source_dataset = DatasetKey(
        provider="rqdata",
        dataset_kind=DatasetKind.CONTINUOUS,
        symbol="a",
        contract_or_series="A.MAIN",
        frequency=BarFrequency.M1,
        adjustment="none",
        schema_version="canonical-bar-v1",
    )
    session = TradingSessionCoverage(
        trading_day=date(2026, 4, 1),
        start=target.start,
        end=target.end,
        expected_bar_ends=(target.end,),
    )
    source_bars = tuple(
        CanonicalBar(
            provider="rqdata",
            dataset_kind=DatasetKind.CONTINUOUS,
            symbol="a",
            contract_or_series="A.MAIN",
            frequency=BarFrequency.M1,
            bar_end=datetime(2026, 3, 31, 13, minute, tzinfo=UTC),
            trading_day=date(2026, 4, 1),
            open=Decimal(str(100 + minute)),
            high=Decimal(str(101 + minute)),
            low=Decimal(str(99 + minute)),
            close=Decimal(str(100.5 + minute)),
            volume=Decimal("1"),
            turnover=Decimal("100"),
            open_interest=Decimal("10"),
            adjustment="none",
            schema_version="canonical-bar-v1",
        )
        for minute in range(1, 6)
    )
    source = BarsResult(
        bars=source_bars,
        source_datasets=(source_dataset,),
        manifest_digests=("6" * 64,),
        requested_window=(target.start, target.end),
        data_type=DatasetKind.CONTINUOUS,
        derived_frequency=None,
        source_data_versions=("rqdata-source-v1",),
    )
    observed: dict[str, object] = {}

    def publish(batch: ProviderBarBatch, lineage: object) -> dict[str, object]:
        observed["batch"] = batch
        observed["lineage"] = lineage
        return {"publication_status": "published", "receipt_digest": "7" * 64}

    receipt = migration_module.execute_task07_repair_target(
        target,
        sessions=(session,),
        fetch_direct=lambda _request: pytest.fail("aggregate repair must not call RQData"),
        read_canonical_1m=lambda observed_target: (
            source
            if observed_target == target
            else pytest.fail("aggregate repair target drift")
        ),
        publish=publish,
        record_gap=lambda *_args, **_kwargs: pytest.fail("successful repair must not record a gap"),
        publication_state_unchanged=lambda _target: True,
    )

    batch = observed["batch"]
    assert isinstance(batch, ProviderBarBatch)
    assert batch.request.dataset == target_dataset
    assert len(tuple(batch.bars)) == 1
    lineage = observed["lineage"]
    assert lineage is not None
    assert lineage.as_payload()["origin"] == "preaggregated_from_1m"
    assert lineage.as_payload()["source_frequency"] == "1m"
    assert receipt["status"] == "passed"
    assert receipt["calls_rqdata"] is False


def test_repair_publication_is_append_only_and_verifiable(tmp_path: Path) -> None:
    target = _direct_repair_target()
    request = ProviderBarRequest(
        dataset=target.dataset,
        start=target.start,
        end=target.end,
        sessions=(_friday_night_session(),),
    )
    batch = ProviderBarBatch(
        request=request,
        bars=(_repair_bar(),),
        data_version="rqdata-test-repair-v1",
    )
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    canonical_root = tmp_path / "canonical"
    store = CanonicalStore(
        staging_root=tmp_path / "staging",
        canonical_root=canonical_root,
        metadata_session_factory=lambda: Session(engine),
    )

    with Session(engine) as session:
        publication = migration_module.publish_task07_repair_batch(
            batch,
            lineage=None,
            target=target,
            store=store,
            catalog=HistoricalCatalog(session),
            batch_key="repair:rqdata_redownload:jm:actual_dominant:1m:1",
            plan_digest="8" * 64,
            batch_digest="9" * 64,
            source_market_data_file_id=1,
            canonical_root=canonical_root,
        )

    assert publication["publication_status"] == "published"
    assert publication["overlap_reason"] == "version_replacement"
    with Session(engine) as session:
        verified = verify_task07_published_batch(
            publication,
            catalog=HistoricalCatalog(session),
            canonical_root=canonical_root,
        )
    assert verified["status"] == "passed"


def _aggregate_dataset(
    *,
    dataset_kind: DatasetKind = DatasetKind.CONTINUOUS,
    contract: str = "A.MAIN",
) -> DatasetKey:
    return DatasetKey(
        provider="rqdata",
        dataset_kind=dataset_kind,
        symbol="a",
        contract_or_series=contract,
        frequency=BarFrequency.M5,
        adjustment="none",
        schema_version="canonical-bar-v1",
    )


def _write_legacy_aggregate(
    path: Path,
    *,
    datetimes: list[datetime] | None = None,
    trading_days: list[date] | None = None,
) -> str:
    values = datetimes or [
        datetime(2026, 3, 31, 21, 5),
        datetime(2026, 3, 31, 21, 10),
    ]
    days = trading_days or [date(2026, 4, 1)] * len(values)
    pq.write_table(
        pa.table(
            {
                "datetime": values,
                "trading_day": days,
                "open": ["100.10", "100.20"][: len(values)],
                "high": ["100.50", "100.60"][: len(values)],
                "low": ["99.90", "100.00"][: len(values)],
                "close": ["100.30", "100.40"][: len(values)],
                "volume": ["12", "13"][: len(values)],
                "turnover": ["1203.60", "1305.20"][: len(values)],
                "open_interest": ["30", "31"][: len(values)],
                "period": ["5m"] * len(values),
                "source_interval": ["1m"] * len(values),
            }
        ),
        path,
    )
    return sha256(path.read_bytes()).hexdigest()


def test_prepare_aggregate_batch_is_schema_only_and_preserves_source_values(
    tmp_path: Path,
) -> None:
    source = tmp_path / "aggregate.parquet"
    checksum = _write_legacy_aggregate(source)
    prepare = getattr(
        migration_module,
        "prepare_legacy_aggregate_parquet_batch",
        None,
    )
    assert callable(prepare), "aggregate schema-only converter must exist"

    prepared = prepare(
        path=source,
        source_checksum=checksum,
        dataset=_aggregate_dataset(),
        data_version="legacy-aggregate-v1",
        quality_evidence_digest="a" * 64,
    )

    bars = tuple(prepared.batch.bars)
    assert [item.bar_end for item in bars] == [
        datetime(2026, 3, 31, 13, 5, tzinfo=UTC),
        datetime(2026, 3, 31, 13, 10, tzinfo=UTC),
    ]
    assert [item.trading_day for item in bars] == [date(2026, 4, 1)] * 2
    assert [item.close for item in bars] == [Decimal("100.3"), Decimal("100.4")]
    assert [item.volume for item in bars] == [Decimal("12"), Decimal("13")]
    assert prepared.evidence.schema_conversion_only is True
    assert prepared.evidence.session_completeness_validated is False
    assert prepared.evidence.quality_evidence_digest == "a" * 64
    assert prepared.lineage is not None
    assert prepared.lineage.as_payload() == {
        "origin": "preaggregated_from_1m",
        "source_frequency": "1m",
        "legacy_source_checksum": checksum,
        "quality_evidence_digest": "a" * 64,
    }


def test_execute_aggregate_batch_publishes_v2_manifest_with_exact_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "aggregate.parquet"
    checksum = _write_legacy_aggregate(source)
    prepared = migration_module.prepare_legacy_aggregate_parquet_batch(
        path=source,
        source_checksum=checksum,
        dataset=_aggregate_dataset(),
        data_version="legacy-aggregate-v1",
        quality_evidence_digest="a" * 64,
    )
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    canonical_root = tmp_path / "canonical"
    store = CanonicalStore(
        staging_root=tmp_path / "staging",
        canonical_root=canonical_root,
        metadata_session_factory=lambda: Session(engine),
    )

    with Session(engine) as session:
        receipt = execute_task07_prepared_batch(
            prepared,
            store=store,
            catalog=HistoricalCatalog(session),
            manifest_version=migration_module.TASK07_AGGREGATE_MANIFEST_VERSION,
            batch_key="a:continuous:5m:1",
            plan_digest="1" * 64,
            batch_digest="2" * 64,
            source_market_data_file_id=1,
            canonical_root=canonical_root,
        )

    manifest = json.loads(
        (canonical_root / str(receipt["manifest_uri"])).read_text(encoding="utf-8")
    )
    assert receipt["manifest_format"] == "canonical-manifest-v2"
    assert receipt["source_lineage"] == {
        "origin": "preaggregated_from_1m",
        "source_frequency": "1m",
        "legacy_source_checksum": checksum,
        "quality_evidence_digest": "a" * 64,
    }
    assert manifest["manifest_format"] == receipt["manifest_format"]
    assert manifest["source_lineage"] == receipt["source_lineage"]

    with Session(engine) as session:
        verified = verify_task07_published_batch(
            receipt,
            catalog=HistoricalCatalog(session),
            canonical_root=canonical_root,
        )
    assert verified["status"] == "passed"

    with Session(engine) as session:
        canonical_asset = next(
            item
            for item in collect_task07_assets(
                session,
                data_root=tmp_path,
                canonical_root=canonical_root,
            )
            if item.data_type == "v2_canonical"
        )
    assert (
        classify_asset(canonical_asset)
        == AssetDisposition.KEEP_CANONICAL_VERIFIED
    ), {
        "content": canonical_asset.content_gate_status,
        "readback": canonical_asset.canonical_readback_status,
        "format": canonical_asset.manifest_format,
        "version": canonical_asset.manifest_version,
        "lineage": canonical_asset.source_lineage,
        "checksums": (
            canonical_asset.checksum,
            canonical_asset.physical_checksum,
            canonical_asset.catalog_checksum,
        ),
    }
    plan = build_migration_plan(
        build_inventory_index(
            [canonical_asset],
            base_sha="3" * 40,
            database_revision="20260803_0032",
        ),
        write_targets={
            "staging_root": str((tmp_path / "approved-staging").resolve()),
            "canonical_root": str(canonical_root.resolve()),
            "postgresql_target": {
                "drivername": "postgresql+psycopg",
                "username": "task07_test",
                "host": "localhost",
                "port": 5432,
                "database": "task07_test",
            },
            "protected_roots": [str((tmp_path / "evidence").resolve())],
        },
    )
    assert plan["batches"][0]["sources"] == []
    assert len(plan["batches"][0]["verified_partitions"]) == 1

    packet = task07_module.build_approval_packet(
        plan,
        command="data.task07.apply",
    )
    plan_path = tmp_path / "verified-plan.json"
    packet_path = tmp_path / "verified-approval.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    approval_hash = task07_module.canonical_digest(packet)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO alembic_version VALUES ('20260803_0032')"
        )
    monkeypatch.setattr(
        "app.data_core.cli_service._git_state",
        lambda _root: {"head": "3" * 40, "clean": True},
    )
    monkeypatch.setattr(
        "app.data_core.cli_service._postgresql_target",
        lambda _session: plan["write_targets"]["postgresql_target"],
    )
    preflight_args = SimpleNamespace(
        plan=plan_path,
        approval_packet=packet_path,
        approval_hash=approval_hash,
        batch_key="a:continuous:5m",
        staging_root=Path(plan["write_targets"]["staging_root"]),
        canonical_root=canonical_root,
    )
    with Session(engine) as session:
        preflight = run_data_core_command(
            "task07.preflight",
            session,
            preflight_args,
        )
    assert preflight["validation"][0]["asset_kind"] == "verified_partition"
    preflight_path = tmp_path / "verified-preflight.json"
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")
    apply_args = SimpleNamespace(
        **vars(preflight_args),
        preflight_receipt=preflight_path,
        preflight_hash=task07_module.canonical_digest(preflight),
    )
    with Session(engine) as session:
        apply_receipt = run_data_core_command(
            "task07.apply",
            session,
            apply_args,
        )
    assert apply_receipt["published_source_count"] == 0
    assert apply_receipt["verified_partition_count"] == 1
    assert len(apply_receipt["verified_partition_readbacks"]) == 1
    apply_path = tmp_path / "verified-apply.json"
    apply_path.write_text(json.dumps(apply_receipt), encoding="utf-8")
    verify_args = SimpleNamespace(
        plan=plan_path,
        receipt=apply_path,
        batch_key="a:continuous:5m",
        canonical_root=canonical_root,
    )
    with Session(engine) as session:
        batch_verified = run_data_core_command(
            "task07.verify",
            session,
            verify_args,
        )
    assert batch_verified["verified_partition_count"] == 1
    migration_args = SimpleNamespace(
        plan=plan_path,
        approval_packet=packet_path,
        approval_hash=approval_hash,
        canonical_root=canonical_root,
        apply_receipt=[apply_path],
    )
    with Session(engine) as session:
        migration_verified = run_data_core_command(
            "task07.migration-verify",
            session,
            migration_args,
        )
    assert migration_verified["runtime_cutover_eligible"] is True

    manifest["source_lineage"]["quality_evidence_digest"] = "b" * 64
    (canonical_root / str(receipt["manifest_uri"])).write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    with Session(engine) as session:
        tampered_asset = next(
            item
            for item in collect_task07_assets(
                session,
                data_root=tmp_path,
                canonical_root=canonical_root,
            )
            if item.data_type == "v2_canonical"
        )
    assert classify_asset(tampered_asset) == AssetDisposition.CONFLICT_BLOCKED


def test_aggregate_overlap_reuse_rejects_existing_lineage_before_passed_receipt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "aggregate.parquet"
    checksum = _write_legacy_aggregate(source)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    canonical_root = tmp_path / "canonical"
    store = CanonicalStore(
        staging_root=tmp_path / "staging",
        canonical_root=canonical_root,
        metadata_session_factory=lambda: Session(engine),
    )
    first = migration_module.prepare_legacy_aggregate_parquet_batch(
        path=source,
        source_checksum=checksum,
        dataset=_aggregate_dataset(),
        data_version="legacy-aggregate-v1",
        quality_evidence_digest="a" * 64,
    )
    changed = migration_module.prepare_legacy_aggregate_parquet_batch(
        path=source,
        source_checksum=checksum,
        dataset=_aggregate_dataset(),
        data_version="legacy-aggregate-v1",
        quality_evidence_digest="b" * 64,
    )
    with Session(engine) as session:
        execute_task07_prepared_batch(
            first,
            store=store,
            catalog=HistoricalCatalog(session),
            manifest_version=migration_module.TASK07_AGGREGATE_MANIFEST_VERSION,
            batch_key="a:continuous:5m:1",
            plan_digest="1" * 64,
            batch_digest="2" * 64,
            source_market_data_file_id=1,
            canonical_root=canonical_root,
        )
    with Session(engine) as session, pytest.raises(
        Task07MigrationError,
        match="TASK07_MANIFEST_LINEAGE_MISMATCH",
    ):
        execute_task07_prepared_batch(
            changed,
            store=store,
            catalog=HistoricalCatalog(session),
            manifest_version=migration_module.TASK07_AGGREGATE_MANIFEST_VERSION,
            batch_key="a:continuous:5m:2",
            plan_digest="1" * 64,
            batch_digest="2" * 64,
            source_market_data_file_id=2,
            canonical_root=canonical_root,
        )


def test_prepare_legacy_batch_corrects_weekend_trading_day_without_changing_values(
    tmp_path: Path,
) -> None:
    source = tmp_path / "bars.parquet"
    checksum = _write_legacy_minute(source, trading_day=date(2026, 8, 1))

    prepared = prepare_legacy_parquet_batch(
        path=source,
        source_checksum=checksum,
        dataset=_dataset(),
        sessions=(_friday_night_session(),),
        data_version="rqdata-legacy-corrected-20260731",
        rank1_contract_by_day={date(2026, 8, 3): "JM2609"},
    )

    bar = tuple(prepared.batch.bars)[0]
    assert bar.bar_end == datetime(2026, 7, 31, 13, 1, tzinfo=UTC)
    assert bar.trading_day == date(2026, 8, 3)
    assert (bar.open, bar.high, bar.low, bar.close) == (
        Decimal("100.1"),
        Decimal("101.2"),
        Decimal("99.8"),
        Decimal("100.7"),
    )
    assert prepared.evidence.corrected_row_count == 1
    assert prepared.evidence.corrected_trading_day_count == 1
    assert prepared.evidence.source_checksum == checksum


def test_prepare_legacy_batch_rejects_actual_contract_that_is_not_rank1(
    tmp_path: Path,
) -> None:
    source = tmp_path / "bars.parquet"
    checksum = _write_legacy_minute(source, trading_day=date(2026, 8, 1))

    with pytest.raises(Task07MigrationError, match="TASK07_MAIN_MAP_MISMATCH"):
        prepare_legacy_parquet_batch(
            path=source,
            source_checksum=checksum,
            dataset=_dataset(),
            sessions=(_friday_night_session(),),
            data_version="rqdata-legacy-corrected-20260731",
            rank1_contract_by_day={date(2026, 8, 3): "JM2701"},
        )


def test_prepare_legacy_batch_rejects_source_checksum_drift(tmp_path: Path) -> None:
    source = tmp_path / "bars.parquet"
    _write_legacy_minute(source, trading_day=date(2026, 8, 1))

    with pytest.raises(Task07MigrationError, match="TASK07_SOURCE_DRIFT"):
        prepare_legacy_parquet_batch(
            path=source,
            source_checksum="0" * 64,
            dataset=_dataset(),
            sessions=(_friday_night_session(),),
            data_version="rqdata-legacy-corrected-20260731",
            rank1_contract_by_day={date(2026, 8, 3): "JM2609"},
        )


def test_resolve_sessions_uses_instrument_exchange_for_non_jm_product() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Instrument(symbol="rb", name="螺纹钢", exchange_code="SHFE"))
        session.add_all(
            [
                TradingCalendar(
                    exchange_code="SHFE",
                    trade_date=date(2026, 7, 31),
                    is_trading_day=True,
                    has_night_session=True,
                ),
                TradingCalendar(
                    exchange_code="SHFE",
                    trade_date=date(2026, 8, 3),
                    is_trading_day=True,
                    has_night_session=True,
                ),
                TradingSession(
                    exchange_code="SHFE",
                    instrument_symbol="rb",
                    session_name="night",
                    start_time=time(21, 0),
                    end_time=time(21, 1),
                    crosses_midnight=False,
                    is_active=True,
                ),
            ]
        )
        session.commit()
        dataset = DatasetKey(
            provider="rqdata",
            dataset_kind=DatasetKind.CONTINUOUS,
            symbol="rb",
            contract_or_series="RB.MAIN",
            frequency=BarFrequency.M1,
            adjustment="none",
            schema_version="canonical-bar-v1",
        )

        sessions = resolve_task07_provider_sessions(
            session,
            dataset=dataset,
            start=datetime(2026, 7, 31, 13, 0, tzinfo=UTC),
            end=datetime(2026, 7, 31, 13, 1, tzinfo=UTC),
        )

    assert len(sessions) == 1
    assert sessions[0].trading_day == date(2026, 8, 3)
    assert sessions[0].expected_bar_ends == (
        datetime(2026, 7, 31, 13, 1, tzinfo=UTC),
    )


def test_load_rank1_map_accepts_same_contract_version_history() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                MainContractMap(
                    instrument_symbol="jm",
                    trade_date=date(2026, 8, 3),
                    rank=1,
                    contract_code="JM2609",
                    rule="volume_open_interest",
                    provider="rqdata",
                    data_version="v1",
                ),
                MainContractMap(
                    instrument_symbol="jm",
                    trade_date=date(2026, 8, 3),
                    rank=1,
                    contract_code="JM2609",
                    rule="volume_open_interest",
                    provider="rqdata",
                    data_version="v2",
                ),
            ]
        )
        session.commit()

        mapping = load_task07_rank1_map(
            session,
            dataset=_dataset(),
            trading_days=(date(2026, 8, 3),),
        )

    assert mapping == {date(2026, 8, 3): "JM2609"}


def test_load_rank1_map_rejects_missing_day() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        with pytest.raises(Task07MigrationError, match="TASK07_MAIN_MAP_MISSING"):
            load_task07_rank1_map(
                session,
                dataset=_dataset(),
                trading_days=(date(2026, 8, 3),),
            )


def test_load_rank1_map_fills_missing_direct_day_with_bound_contract() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        mapping = load_task07_rank1_map(
            session,
            dataset=_dataset(),
            trading_days=(date(2026, 8, 3),),
            missing_contract="JM2609",
        )

    assert mapping == {date(2026, 8, 3): "JM2609"}


def test_execute_prepared_batch_publishes_create_only_catalog_and_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "bars.parquet"
    checksum = _write_legacy_minute(source, trading_day=date(2026, 8, 1))
    prepared = prepare_legacy_parquet_batch(
        path=source,
        source_checksum=checksum,
        dataset=_dataset(),
        sessions=(_friday_night_session(),),
        data_version="rqdata-legacy-corrected-20260731",
        rank1_contract_by_day={date(2026, 8, 3): "JM2609"},
    )
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    staging_root = tmp_path / "staging"
    canonical_root = tmp_path / "canonical"
    store = CanonicalStore(
        staging_root=staging_root,
        canonical_root=canonical_root,
        metadata_session_factory=lambda: Session(engine),
    )
    with Session(engine) as session:
        receipt = execute_task07_prepared_batch(
            prepared,
            store=store,
            catalog=HistoricalCatalog(session),
            manifest_version="task07-corrected-v1",
            batch_key="jm:actual_dominant:1m:20260731T130000Z:20260731T130100Z",
            plan_digest="1" * 64,
            batch_digest="2" * 64,
            source_market_data_file_id=1,
            canonical_root=canonical_root,
        )

        partitions = HistoricalCatalog(session).list_partitions(_dataset())

    assert receipt["status"] == "passed"
    assert receipt["publication_status"] == "published"
    assert receipt["row_count"] == 1
    assert len(partitions) == 1
    assert (canonical_root / partitions[0].file_uri).is_file()
    assert (canonical_root / partitions[0].manifest_uri).is_file()
    with Session(engine) as session:
        verified = verify_task07_published_batch(
            receipt,
            catalog=HistoricalCatalog(session),
            canonical_root=canonical_root,
        )
    assert verified["status"] == "passed"
    assert verified["physical_checksum"] == receipt["physical_checksum"]

    with Session(engine) as session:
        reused = execute_task07_prepared_batch(
            prepared,
            store=store,
            catalog=HistoricalCatalog(session),
            manifest_version="task07-corrected-v1",
            batch_key="jm:actual_dominant:1m:20260731T130000Z:20260731T130100Z",
            plan_digest="1" * 64,
            batch_digest="2" * 64,
            source_market_data_file_id=1,
            canonical_root=canonical_root,
        )
    assert reused["status"] == "passed"
    assert reused["publication_status"] == "reused"
    assert reused["physical_checksum"] == receipt["physical_checksum"]
