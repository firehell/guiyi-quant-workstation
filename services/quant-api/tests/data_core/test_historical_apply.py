from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.data_core.bar_schema import CanonicalBar
from app.data_core.canonical_store import CanonicalStore
from app.data_core.catalog import HistoricalCatalog
from app.data_core import cli_service
from app.data_core.contracts import BarFrequency, DatasetKind
from app.data_core.historical_apply import (
    execute_prepared_historical_apply,
    filter_actual_dominant_sessions,
    prepare_historical_apply_roots,
    prepare_historical_apply,
)
from app.data_core.historical_apply_gate import (
    HistoricalApplyGateError,
    build_apply_approval_packet,
)
from app.data_core.historical_sync import MappingSyncResult, SyncResult
from app.data_core.historical_sync import CanonicalBatchPublisher, HistoricalSynchronizer
from app.data_core.rqdata_adapter import (
    MainMapRow,
    ProviderBarBatch,
    TradingSessionCoverage,
)
from app.db.base import Base
from app.models.data_center import MainContractMap
from app.models.data_core import MarketDataset, MarketPartition


def _facts() -> dict[str, object]:
    return {
        "task_head": "a" * 40,
        "migration_revisions": ["20260730_0026", "20260730_0027"],
        "scope": {
            "symbol": "jm",
            "provider": "rqdata",
            "schema_version": "canonical-bar-v1",
            "dataset_kinds": ["continuous", "actual_dominant"],
            "direct_frequencies": ["1m", "1d", "1w"],
            "window": {
                "start": "2026-07-01T00:00:00+00:00",
                "end": "2026-07-03T00:00:00+00:00",
            },
            "contract_or_series": ["JM.MAIN", "JM2609", "JM2610"],
        },
        "plan_digest": "b" * 64,
        "write_set": {
            "canonical_root": "/tmp/data/parquet/data-core-v2/canonical",
            "staging_root": "/tmp/data/parquet/data-core-v2/staging",
            "postgresql_target": {
                "drivername": "postgresql+psycopg",
                "username": "guiyi",
                "host": "127.0.0.1",
                "port": 5432,
                "database": "guiyi_quant",
            },
            "postgresql_tables": [
                "market_datasets",
                "market_partitions",
                "data_gaps",
                "main_contract_map",
            ],
            "writes_legacy_market_data_assets": False,
        },
        "rollback": {
            "deletes_physical_data": False,
            "strategy": "keep_legacy_readonly_and_disable_canonical_consumer",
        },
    }


def _prepared():
    facts = _facts()
    facts["scope"] = {
        **facts["scope"],
        "window": {
            "start": "2026-06-30T00:00:00+00:00",
            "end": "2026-07-03T00:00:00+00:00",
        },
    }
    packet = build_apply_approval_packet(bound_facts=facts)
    return prepare_historical_apply(
        packet,
        approval_hash=packet["packet_hash"],
        current_facts=facts,
    )


def _mapping(day: int, contract: str) -> MainMapRow:
    return MainMapRow(
        symbol="jm",
        trading_day=date(2026, 7, day),
        actual_contract=contract,
        rank=1,
        data_version="rqdata-test-rank1",
    )


def test_prepare_apply_rejects_fact_drift_before_executor_dependencies() -> None:
    facts = _facts()
    packet = build_apply_approval_packet(bound_facts=facts)

    with pytest.raises(HistoricalApplyGateError, match="approval_facts_changed"):
        prepare_historical_apply(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts={**facts, "task_head": "c" * 40},
        )


def test_execute_apply_commits_mapping_before_exact_direct_dataset_set() -> None:
    calls: list[object] = []
    commits: list[str] = []
    rollbacks: list[str] = []

    class Synchronizer:
        def sync_rank1_mapping(self, **kwargs: object) -> MappingSyncResult:
            calls.append(("mapping", kwargs))
            return MappingSyncResult(
                dry_run=False,
                rows=(_mapping(1, "JM2609"), _mapping(2, "JM2610")),
            )

        def sync(self, **kwargs: object) -> SyncResult:
            dataset = kwargs["dataset"]
            calls.append(("dataset", dataset))
            return SyncResult(
                dry_run=False,
                planned_windows=((kwargs["start"], kwargs["end"]),),
                published_windows=((kwargs["start"], kwargs["end"]),),
                gap_windows=(),
            )

    result = execute_prepared_historical_apply(
        _prepared(),
        synchronizer=Synchronizer(),
        expected_trading_days=(date(2026, 7, 1), date(2026, 7, 2)),
        commit=lambda: commits.append("commit"),
        rollback=lambda: rollbacks.append("rollback"),
    )

    datasets = [entry[1] for entry in calls if entry[0] == "dataset"]
    assert [(item.dataset_kind, item.contract_or_series, item.frequency) for item in datasets] == [
        (DatasetKind.CONTINUOUS, "JM.MAIN", BarFrequency.M1),
        (DatasetKind.CONTINUOUS, "JM.MAIN", BarFrequency.D1),
        (DatasetKind.CONTINUOUS, "JM.MAIN", BarFrequency.W1),
        (DatasetKind.ACTUAL_DOMINANT, "JM2609", BarFrequency.M1),
        (DatasetKind.ACTUAL_DOMINANT, "JM2609", BarFrequency.D1),
        (DatasetKind.ACTUAL_DOMINANT, "JM2609", BarFrequency.W1),
        (DatasetKind.ACTUAL_DOMINANT, "JM2610", BarFrequency.M1),
        (DatasetKind.ACTUAL_DOMINANT, "JM2610", BarFrequency.D1),
        (DatasetKind.ACTUAL_DOMINANT, "JM2610", BarFrequency.W1),
    ]
    assert len(commits) == 10
    assert rollbacks == []
    assert result["status"] == "passed"
    assert result["mapping_row_count"] == 2
    assert result["dataset_count"] == 9
    assert result["gap_dataset_count"] == 0


def test_execute_apply_persists_gap_result_and_reports_blocked() -> None:
    commits: list[str] = []

    class Synchronizer:
        def sync_rank1_mapping(self, **_kwargs: object) -> MappingSyncResult:
            return MappingSyncResult(dry_run=False, rows=(_mapping(1, "JM2609"),))

        def sync(self, **kwargs: object) -> SyncResult:
            window = (kwargs["start"], kwargs["end"])
            dataset = kwargs["dataset"]
            return SyncResult(
                dry_run=False,
                planned_windows=(window,),
                published_windows=() if dataset.frequency is BarFrequency.M1 else (window,),
                gap_windows=(window,) if dataset.frequency is BarFrequency.M1 else (),
            )

    result = execute_prepared_historical_apply(
        _prepared(),
        synchronizer=Synchronizer(),
        expected_trading_days=(date(2026, 7, 1),),
        commit=lambda: commits.append("commit"),
        rollback=lambda: (_ for _ in ()).throw(AssertionError("must not roll back committed gaps")),
    )

    assert result["status"] == "blocked"
    assert result["gap_dataset_count"] == 2
    assert len(commits) == 7


def test_execute_apply_rolls_back_current_transaction_on_unexpected_error() -> None:
    rollbacks: list[str] = []

    class Synchronizer:
        def sync_rank1_mapping(self, **_kwargs: object) -> MappingSyncResult:
            return MappingSyncResult(dry_run=False, rows=(_mapping(1, "JM2609"),))

        def sync(self, **_kwargs: object) -> SyncResult:
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError, match="injected"):
        execute_prepared_historical_apply(
            _prepared(),
            synchronizer=Synchronizer(),
            expected_trading_days=(date(2026, 7, 1),),
            commit=lambda: None,
            rollback=lambda: rollbacks.append("rollback"),
        )

    assert rollbacks == ["rollback"]


def test_actual_dominant_sessions_keep_only_exact_rank1_contract_days() -> None:
    dataset = next(
        item
        for item in _prepared().datasets_for_contracts(("JM2609",))
        if item.frequency is BarFrequency.M1
        and item.dataset_kind is DatasetKind.ACTUAL_DOMINANT
    )
    sessions = tuple(
        TradingSessionCoverage(
            trading_day=date(2026, 7, day),
            start=datetime(2026, 7, day, 1, 0, tzinfo=UTC),
            end=datetime(2026, 7, day, 1, 1, tzinfo=UTC),
            expected_bar_ends=(datetime(2026, 7, day, 1, 1, tzinfo=UTC),),
        )
        for day in (1, 2)
    )

    filtered = filter_actual_dominant_sessions(
        dataset,
        sessions,
        actual_contract_for_day=lambda trading_day: (
            "JM2609" if trading_day.day == 1 else "JM2610"
        ),
    )

    assert tuple(item.trading_day for item in filtered) == (date(2026, 7, 1),)


def test_apply_executor_writes_only_direct_canonical_partitions_and_mapping(
    tmp_path: Path,
) -> None:
    facts = _facts()
    facts["scope"] = {
        **facts["scope"],
        "window": {
            "start": "2026-06-30T00:00:00+00:00",
            "end": "2026-07-03T00:00:00+00:00",
        },
    }
    facts["write_set"] = {
        **facts["write_set"],
        "canonical_root": str(
            tmp_path / "data" / "parquet" / "data-core-v2" / "canonical"
        ),
        "staging_root": str(
            tmp_path / "data" / "parquet" / "data-core-v2" / "staging"
        ),
    }
    packet = build_apply_approval_packet(bound_facts=facts)
    prepared = prepare_historical_apply(
        packet,
        approval_hash=packet["packet_hash"],
        current_facts=facts,
    )
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'metadata.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()

    def sessions(dataset, start, end):
        if dataset.frequency is BarFrequency.M1:
            bar_end = datetime(2026, 7, 1, 1, 1, tzinfo=UTC)
            coverage_start = bar_end - timedelta(minutes=1)
        else:
            bar_end = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
            coverage_start = bar_end - timedelta(microseconds=1)
        return (
            TradingSessionCoverage(
                trading_day=date(2026, 7, 1),
                start=coverage_start,
                end=bar_end,
                expected_bar_ends=(bar_end,),
            ),
        )

    class Adapter:
        def fetch_rank1_map(self, _request):
            return (_mapping(1, "JM2609"),)

        def fetch_bars(self, request):
            bars = tuple(
                CanonicalBar(
                    provider="rqdata",
                    dataset_kind=request.dataset.dataset_kind,
                    symbol="jm",
                    contract_or_series=request.dataset.contract_or_series,
                    frequency=request.dataset.frequency,
                    bar_end=bar_end,
                    trading_day=session_coverage.trading_day,
                    open=Decimal("100"),
                    high=Decimal("102"),
                    low=Decimal("99"),
                    close=Decimal("101"),
                    volume=Decimal("10"),
                    turnover=Decimal("1000"),
                    open_interest=Decimal("20"),
                    adjustment="none",
                    schema_version="canonical-bar-v1",
                )
                for session_coverage in request.sessions
                for bar_end in session_coverage.expected_bar_ends
            )
            return ProviderBarBatch(
                request=request,
                bars=bars,
                data_version=f"fake-{request.dataset.frequency.value}-20260701",
            )

    prepared.canonical_root.parent.parent.mkdir(parents=True)
    prepare_historical_apply_roots(prepared)
    store = CanonicalStore(
        staging_root=prepared.staging_root,
        canonical_root=prepared.canonical_root,
        metadata_session_factory=factory,
    )
    synchronizer = HistoricalSynchronizer(
        catalog=HistoricalCatalog(session),
        adapter=Adapter(),
        session_provider=sessions,
        publish_batch=CanonicalBatchPublisher(store),
    )

    result = execute_prepared_historical_apply(
        prepared,
        synchronizer=synchronizer,
        expected_trading_days=(date(2026, 7, 1),),
        commit=session.commit,
        rollback=session.rollback,
    )

    assert result["status"] == "passed", result
    assert result["dataset_count"] == 6
    assert session.scalar(select(func.count()).select_from(MarketDataset)) == 6
    assert session.scalar(select(func.count()).select_from(MarketPartition)) == 6
    assert session.scalar(select(func.count()).select_from(MainContractMap)) == 1
    assert len(tuple(prepared.canonical_root.rglob("*.parquet"))) == 6
    assert not tuple(prepared.canonical_root.rglob("*5m*"))
    session.close()
    engine.dispose()


def test_migrate_apply_runner_rechecks_facts_before_writer_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _facts()
    packet = build_apply_approval_packet(bound_facts=facts)
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(cli_service, "inventory_jm_legacy_assets", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        cli_service,
        "build_jm_migration_plan",
        lambda _inventory: {"plan_digest": facts["plan_digest"]},
    )
    monkeypatch.setattr(
        cli_service,
        "build_jm_apply_bound_facts",
        lambda *_args, **_kwargs: facts,
    )
    monkeypatch.setattr(
        cli_service,
        "_git_state",
        lambda _root: {"head": facts["task_head"], "clean": True},
    )
    monkeypatch.setattr(
        cli_service,
        "_postgresql_target",
        lambda _session: facts["write_set"]["postgresql_target"],
    )
    monkeypatch.setattr(
        cli_service,
        "_require_data_core_revision",
        lambda _session: calls.append("revision"),
        raising=False,
    )
    monkeypatch.setattr(
        cli_service,
        "_expected_jm_trading_days",
        lambda *_args, **_kwargs: (date(2026, 7, 1),),
        raising=False,
    )

    class Client:
        def __init__(self, **_kwargs: object) -> None:
            calls.append("client")

    class Adapter:
        def __init__(self, _client: object) -> None:
            calls.append("adapter")

    class Store:
        def __init__(self, **_kwargs: object) -> None:
            calls.append("store")

    class Publisher:
        def __init__(self, _store: object) -> None:
            pass

    class Synchronizer:
        def __init__(self, **_kwargs: object) -> None:
            calls.append("synchronizer")

        def sync_rank1_mapping(self, **_kwargs: object) -> MappingSyncResult:
            calls.append("mapping")
            return MappingSyncResult(dry_run=False, rows=(_mapping(1, "JM2609"),))

        def sync(self, **_kwargs: object) -> SyncResult:
            calls.append("sync")
            return SyncResult(
                dry_run=False,
                planned_windows=(),
                published_windows=(),
                gap_windows=(),
            )

    monkeypatch.setattr(cli_service, "RqDataClient", Client, raising=False)
    monkeypatch.setattr(cli_service, "CanonicalRQDataAdapter", Adapter, raising=False)
    monkeypatch.setattr(cli_service, "CanonicalStore", Store, raising=False)
    monkeypatch.setattr(cli_service, "CanonicalBatchPublisher", Publisher, raising=False)
    monkeypatch.setattr(cli_service, "HistoricalSynchronizer", Synchronizer, raising=False)
    monkeypatch.setattr(
        cli_service,
        "prepare_historical_apply_roots",
        lambda _prepared: calls.append("roots"),
        raising=False,
    )

    class Session:
        def commit(self) -> None:
            calls.append("commit")

        def rollback(self) -> None:
            calls.append("rollback")

        def get_bind(self):
            return object()

    args = SimpleNamespace(
        project_root=Path("/tmp/project"),
        legacy_root=Path("/tmp/legacy"),
        canonical_root=Path(facts["write_set"]["canonical_root"]),
        staging_root=Path(facts["write_set"]["staging_root"]),
        start=facts["scope"]["window"]["start"],
        end=facts["scope"]["window"]["end"],
        approval_packet=packet_path,
        approval_hash=packet["packet_hash"],
    )

    result = cli_service.run_data_core_command(
        "migrate.apply",
        Session(),
        args,
    )

    assert result["status"] == "passed"
    assert calls[:5] == ["revision", "roots", "client", "adapter", "store"]
    assert calls.count("sync") == 6
    assert "rollback" not in calls
