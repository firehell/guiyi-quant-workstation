from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from dataclasses import replace
import io
import json
from types import SimpleNamespace

import pytest

from app.market_data import historical_data_manager as historical
from app.market_data.historical_data_manager import MaintenanceResult, UpdateRequest
from app.market_data.coverage_source import DatabaseCoverageSource
from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey, DatasetKind
from app.market_data.storage import PublishRequest
from app.models import MainContractMap, TradingCalendar, TradingSession
from tests.data_foundation.test_historical_data_manager import (
    FakeCoverage,
    FakeProvider,
    _manager,
    session,  # noqa: F401 - shared isolated SQLite fixture
)


def test_daily_requires_existing_baseline_without_metadata_bootstrap(session, tmp_path):  # noqa: F811
    manager = _manager(session, tmp_path, FakeCoverage({}), FakeProvider({}))
    with pytest.raises(ValueError, match="HISTORICAL_MAINTENANCE_REQUIRED"):
        manager.update(UpdateRequest(("jm",), None, date(2025, 1, 3), mode="daily"))
    assert manager.metadata.calls == []
    assert manager.provider.calls == []


def test_daily_recovery_plan_hash_uses_only_canonical_target_windows() -> None:
    target_windows = (
        {
            "dataset": ("continuous", "jm", "MAIN", "1d"),
            "year": 2026,
            "month": 9,
            "window_start": "2026-09-01T07:00:00+00:00",
            "window_end": "2026-09-02T07:00:00+00:00",
            "missing_bar_count": 2,
        },
    )

    assert historical._daily_recovery_plan_sha256(target_windows) == (
        "fa92fc89670cdcf13c01448dbc85c0c1a89f33125ec43f7f10ffc26217731bfc"
    )


@pytest.fixture
def daily_manager(session, tmp_path):  # noqa: F811
    starts = tmp_path / "starts.csv"
    starts.write_text("product,window_start\njm,2025-01-01\n")
    floor = tmp_path / "floor.txt"
    floor.write_text("2025-01-01\n")
    for offset in range(99):
        day = date(2024, 12, 1) + timedelta(days=offset)
        trading = day.weekday() < 5
        session.add(TradingCalendar(
            exchange_code="DCE", trade_date=day, is_trading_day=trading,
            has_night_session=False, provider="rqdata",
        ))
        if trading and day >= date(2025, 1, 1):
            session.add(TradingSession(
                exchange_code="DCE", instrument_symbol="jm", session_name="day",
                start_time=time(9), end_time=time(9, 5), crosses_midnight=False,
                effective_from=day, effective_to=day, is_active=True, provider="rqdata",
            ))
            session.add(MainContractMap(
                symbol="jm", trade_date=day, contract_code="JM2509", rank=1,
            ))
    session.commit()
    coverage = DatabaseCoverageSource(
        session, starts, history_floor_path=floor,
        now=lambda: datetime(2025, 3, 7, 18, tzinfo=UTC),
    )
    bars = {}
    for kind, contract in ((DatasetKind.CONTINUOUS, "MAIN"), (DatasetKind.CONTRACT, "JM2509")):
        for frequency in (BarFrequency.M1, BarFrequency.D1, BarFrequency.W1):
            key = DatasetKey(kind, "jm", contract, frequency)
            ends = tuple(end for month in (1, 2, 3) for end in coverage.expected_bar_ends(
                key, 2025, month, date(2025, 1, 1), date(2025, 3, 7),
            ))
            bars[key.as_tuple()] = tuple(CanonicalBar(
                end, end.date(), Decimal(10), Decimal(10), Decimal(10), Decimal(10),
                Decimal(1), Decimal(10), Decimal(20),
            ) for end in ends)
    manager = _manager(session, tmp_path / "canonical", coverage, FakeProvider(bars))
    result = manager.update(UpdateRequest(("jm",), None, date(2025, 1, 31), apply=True))
    assert result.status == "passed"
    manager.provider.calls.clear()
    manager.metadata.calls.clear()
    return manager


def test_daily_recovery_dry_run_is_fixed_and_has_no_provider_or_write_side_effects(
    daily_manager,
) -> None:
    manager = daily_manager
    verified: list[str] = []

    result = manager.daily_recovery(
        UpdateRequest(
            products=("jm",),
            since=None,
            through=date(2025, 3, 7),
            apply=False,
            sync_current_day_metadata=False,
            mode="daily",
        ),
        verify_identity=lambda: verified.append("verified"),
    )

    assert result.status == "planned"
    assert result.readonly is True
    assert result.through == date(2025, 3, 7)
    assert len(result.plan_sha256) == 64
    assert result.target_windows
    assert result.provider_requests == 0
    assert manager.provider.calls == []
    assert manager.metadata.current_day_calls == []
    assert verified == ["verified", "verified"]


def test_daily_recovery_apply_freezes_and_verifies_under_lease_before_side_effects(
    daily_manager, monkeypatch
) -> None:
    manager = daily_manager
    target_windows = (
        {
            "dataset": ("continuous", "jm", "MAIN", "1d"),
            "year": 2026,
            "month": 9,
            "window_start": "2026-09-01T07:00:00+00:00",
            "window_end": "2026-09-02T07:00:00+00:00",
            "missing_bar_count": 2,
        },
    )
    plan_hash = historical._daily_recovery_plan_sha256(target_windows)
    events: list[str] = []

    class Lease:
        def release(self) -> None:
            events.append("release")

    monkeypatch.setattr(
        manager.catalog,
        "acquire_maintenance_lock",
        lambda: events.append("lease") or Lease(),
    )

    plan = SimpleNamespace(target_windows=target_windows)

    def freeze(_products, _through):
        events.append("plan")
        return plan

    def execute(frozen, _through, *, console_progress):
        assert frozen is plan
        assert console_progress is False
        events.append("apply")
        return MaintenanceResult(
            "update",
            "passed",
            date(2026, 9, 11),
            1,
            1,
            0,
            0,
            1,
        )

    monkeypatch.setattr(manager, "_plan_daily_recovery", freeze)
    monkeypatch.setattr(manager, "_execute_daily_recovery_plan", execute)

    result = manager.daily_recovery(
        UpdateRequest(
            ("jm",),
            None,
            date(2026, 9, 11),
            apply=True,
            sync_current_day_metadata=False,
            mode="daily",
        ),
        expected_plan_sha256=plan_hash,
        verify_identity=lambda: events.append("verify"),
        before_apply=lambda: events.append("invalidate"),
    )

    assert result.status == "passed"
    assert result.readonly is False
    assert result.plan_sha256 == plan_hash
    assert result.target_windows == target_windows
    assert events == [
        "lease",
        "verify",
        "plan",
        "verify",
        "invalidate",
        "apply",
        "release",
    ]


def test_daily_recovery_apply_executes_the_single_locked_plan_without_replanning(
    daily_manager, monkeypatch
) -> None:
    manager = daily_manager
    request = UpdateRequest(
        ("jm",),
        None,
        date(2025, 3, 7),
        apply=False,
        sync_current_day_metadata=False,
        mode="daily",
    )
    dry_run = manager.daily_recovery(request)
    original = manager._daily_groups
    plan_calls = 0

    def plan_once(products, through):
        nonlocal plan_calls
        plan_calls += 1
        if plan_calls > 1:
            raise AssertionError("daily recovery replanned after its CAS check")
        yield from original(products, through)

    monkeypatch.setattr(manager, "_daily_groups", plan_once)

    result = manager.daily_recovery(
        replace(request, apply=True),
        expected_plan_sha256=dry_run.plan_sha256,
    )

    assert result.status == "passed"
    assert result.target_windows == dry_run.target_windows
    assert plan_calls == 1


def test_daily_recovery_main_apply_keeps_legacy_progress_off_stdout(
    daily_manager, capsys
) -> None:
    from app.guiyi_cli.daily_recovery import run_daily_recovery
    from app.guiyi_cli.main import main

    manager = daily_manager
    dry_run = manager.daily_recovery(
        UpdateRequest(
            ("jm",),
            None,
            date(2025, 3, 7),
            apply=False,
            sync_current_day_metadata=False,
            mode="daily",
        )
    )
    capsys.readouterr()
    runtime = SimpleNamespace(
        products=("jm",),
        manager=manager,
        verify_identity=lambda: None,
        invalidate_projection=lambda: None,
    )

    @contextmanager
    def open_runtime(*_args):
        yield runtime

    def runner(args, *, progress_stream):
        return run_daily_recovery(
            args,
            progress_stream=progress_stream,
            runtime_context_factory=open_runtime,
        )

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(
        [
            "data",
            "daily-recovery",
            "--runtime-root",
            "/runtime",
            "--runtime-commit",
            "a" * 40,
            "--expected-status-sha256",
            "b" * 64,
            "--through",
            "2025-03-07",
            "--apply",
            "--expected-plan-sha256",
            dry_run.plan_sha256,
        ],
        daily_recovery_runner=runner,
        stdout=stdout,
        stderr=stderr,
    )

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""
    assert json.loads(stdout.getvalue())["plan_sha256"] == dry_run.plan_sha256
    assert len(stdout.getvalue().splitlines()) > 1
    assert all(
        json.loads(line)["event"] == "data.daily-recovery.progress"
        for line in stderr.getvalue().splitlines()
    )


def test_daily_recovery_target_drift_blocks_before_invalidation_and_provider(
    daily_manager, monkeypatch
) -> None:
    manager = daily_manager
    effects: list[str] = []
    monkeypatch.setattr(
        manager,
        "_plan_daily_recovery",
        lambda *_args, **_kwargs: SimpleNamespace(
            target_windows=(
                {
                    "dataset": ("continuous", "jm", "MAIN", "1d"),
                    "year": 2026,
                    "month": 9,
                    "window_start": "2026-09-01T07:00:00+00:00",
                    "window_end": "2026-09-01T07:00:00+00:00",
                    "missing_bar_count": 1,
                },
            ),
        ),
    )

    with pytest.raises(ValueError, match="DAILY_RECOVERY_PLAN_CHANGED"):
        manager.daily_recovery(
            UpdateRequest(
                ("jm",),
                None,
                date(2026, 9, 11),
                apply=True,
                sync_current_day_metadata=False,
                mode="daily",
            ),
            expected_plan_sha256="0" * 64,
            verify_identity=lambda: effects.append("verify"),
            before_apply=lambda: effects.append("invalidate"),
        )

    assert effects == ["verify"]
    assert manager.provider.calls == []


def test_daily_recovery_identity_drift_after_locked_plan_blocks_before_side_effects(
    daily_manager, monkeypatch
) -> None:
    manager = daily_manager
    target_windows = (
        {
            "dataset": ("continuous", "jm", "MAIN", "1d"),
            "year": 2026,
            "month": 9,
            "window_start": "2026-09-01T07:00:00+00:00",
            "window_end": "2026-09-01T07:00:00+00:00",
            "missing_bar_count": 1,
        },
    )
    effects: list[str] = []
    monkeypatch.setattr(
        manager,
        "_plan_daily_recovery",
        lambda *_args, **_kwargs: SimpleNamespace(target_windows=target_windows),
    )

    def verify() -> None:
        effects.append("verify")
        if len(effects) == 2:
            raise ValueError("RUNTIME_STATUS_CHANGED")

    with pytest.raises(ValueError, match="RUNTIME_STATUS_CHANGED"):
        manager.daily_recovery(
            UpdateRequest(
                ("jm",),
                None,
                date(2026, 9, 11),
                apply=True,
                sync_current_day_metadata=False,
                mode="daily",
            ),
            expected_plan_sha256=historical._daily_recovery_plan_sha256(
                target_windows
            ),
            verify_identity=verify,
            before_apply=lambda: effects.append("invalidate"),
        )

    assert effects == ["verify", "verify"]
    assert manager.provider.calls == []


def test_daily_recovery_maintenance_lock_blocks_before_identity_and_side_effects(
    daily_manager, monkeypatch
) -> None:
    manager = daily_manager
    effects: list[str] = []
    monkeypatch.setattr(manager.catalog, "acquire_maintenance_lock", lambda: None)

    result = manager.daily_recovery(
        UpdateRequest(
            ("jm",),
            None,
            date(2026, 9, 11),
            apply=True,
            sync_current_day_metadata=False,
            mode="daily",
        ),
        expected_plan_sha256="0" * 64,
        verify_identity=lambda: effects.append("verify"),
        before_apply=lambda: effects.append("invalidate"),
    )

    assert result.status == "blocked"
    assert result.maintenance.stop_reason == "maintenance_locked"
    assert effects == []
    assert manager.provider.calls == []


@pytest.mark.parametrize(
    ("failure", "terminal_state"),
    [(RuntimeError("source failed"), "failed"), (KeyboardInterrupt(), "interrupted")],
)
def test_maintenance_progress_exposes_failure_and_interruption_terminal_states(
    daily_manager, failure, terminal_state
) -> None:
    manager = daily_manager
    events = []
    manager._observer = events.append

    with pytest.raises(type(failure)):
        with manager._progress("provider", symbol="jm"):
            raise failure

    assert [(event.phase, event.state) for event in events] == [
        ("provider", "started"),
        ("provider", terminal_state),
    ]


def test_daily_recovery_committed_subset_is_single_attempt_and_formally_readable(
    daily_manager,
) -> None:
    from app.market_data.domain import SeriesKind, SeriesQuery
    from app.market_data.market_data_service import MarketDataService

    manager = daily_manager
    request = UpdateRequest(
        ("jm",),
        None,
        date(2025, 3, 7),
        apply=False,
        sync_current_day_metadata=False,
        mode="daily",
    )
    plan = manager.daily_recovery(request)

    class FailFirstBatch(FakeProvider):
        def __init__(self, bars):
            super().__init__(bars)
            self.batch_attempts = []

        def fetch_many(self, requests):
            self.batch_attempts.append(requests)
            if len(self.batch_attempts) == 1:
                raise RuntimeError("source failed")
            return super().fetch_many(requests)

    provider = FailFirstBatch(manager.provider.bars)
    manager.provider = provider

    result = manager.daily_recovery(
        replace(request, apply=True),
        expected_plan_sha256=plan.plan_sha256,
    )

    assert result.status == "failed"
    assert result.maintenance.applied > 0
    failed_request = provider.batch_attempts[0][0]
    assert sum(
        request.key == failed_request.key and request.expected == failed_request.expected
        for batch in provider.batch_attempts
        for request in batch
    ) == 1
    committed_key, committed_ends = provider.calls[0]
    query = SeriesQuery(
        series_kind=(
            SeriesKind.CONTINUOUS
            if committed_key.kind is DatasetKind.CONTINUOUS
            else SeriesKind.CONTRACT
        ),
        symbol=committed_key.symbol,
        contract=(
            None
            if committed_key.kind is DatasetKind.CONTINUOUS
            else committed_key.series_or_contract
        ),
        frequency=committed_key.frequency,
        start=min(committed_ends) - timedelta(microseconds=1),
        end=max(committed_ends),
    )
    readback = MarketDataService(manager.catalog, manager.store).query(query)
    assert tuple(bar.bar_end for bar in readback.bars) == committed_ends


def test_daily_ignores_old_damaged_file_but_full_audit_detects_it(daily_manager):
    manager = daily_manager
    key = DatasetKey(DatasetKind.CONTINUOUS, "jm", "MAIN", BarFrequency.M1)
    old = manager.catalog.all_partitions(key)[0]
    old.file_path.write_bytes(b"damaged old file")
    result = manager.update(UpdateRequest(("jm",), None, date(2025, 3, 7), mode="daily"))
    assert result.status == "planned"
    assert all(window["month"] in (2, 3) for window in result.target_windows)
    from app.market_data.historical_data_manager import AuditRequest
    audit = manager.audit(AuditRequest(("jm",), through=date(2025, 3, 7)))
    assert any(finding.month == 1 and finding.dataset == key.as_tuple()
               for finding in audit.findings)


def test_daily_repair_missing_derived_without_provider_and_restart_noop(daily_manager):
    manager = daily_manager
    manager.update(UpdateRequest(("jm",), None, date(2025, 3, 7), apply=True))
    key = DatasetKey(DatasetKind.CONTRACT, "jm", "JM2509", BarFrequency.M15)
    from app.models import MarketPartition
    from sqlalchemy import delete
    dataset = manager.catalog.dataset_row(key)
    manager.catalog.session.execute(delete(MarketPartition).where(
        MarketPartition.dataset_id == dataset.id, MarketPartition.month == 2,
    ))
    manager.catalog.session.commit()
    manager.provider.calls.clear()
    events = []
    result = manager.update(UpdateRequest(
        ("jm",), None, date(2025, 3, 7), apply=True, mode="daily",
    ), observer=events.append)
    assert result.status == "passed" and result.applied == 1
    assert manager.provider.calls == []
    assert any(event.phase == "publishing" and event.state == "completed" for event in events)
    restarted = _manager(manager.catalog.session, manager.store.root, manager.coverage, manager.provider)
    assert restarted.update(UpdateRequest(
        ("jm",), None, date(2025, 3, 7), apply=True, mode="daily",
    )).status == "noop"


def test_daily_short_last_day_tail_is_detected_from_catalog(daily_manager):
    manager = daily_manager
    key = DatasetKey(DatasetKind.CONTINUOUS, "jm", "MAIN", BarFrequency.M1)
    row = manager.catalog.all_partitions(key)[0]
    bars = manager.store.read_catalog_partition(row)[:-1]
    partition = manager.store.publish(PublishRequest(
        key, 2025, 1, bars, tuple(bar.bar_end for bar in bars),
    ))
    manager.catalog.register_partition(partition)
    manager.catalog.session.commit()
    result = manager.update(UpdateRequest(("jm",), None, date(2025, 3, 7), mode="daily"))
    assert any(window["dataset"] == key.as_tuple() and window["month"] == 1
               and window["missing_bar_count"] == 1 for window in result.target_windows)


def test_daily_catchup_matches_full_update_with_bounded_source_reads(daily_manager, tmp_path, monkeypatch):
    manager = daily_manager
    full_root = tmp_path / "full"
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.base import Base
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    # Independent DB and physical Parquet tree; identical authoritative metadata inputs.
    with Session(engine) as db:
        for table in Base.metadata.sorted_tables:
            if table.name in {"market_datasets", "market_partitions"}:
                continue
            rows = manager.catalog.session.execute(table.select()).mappings().all()
            if rows:
                db.execute(table.insert(), [dict(row) for row in rows])
        db.commit()
        coverage = DatabaseCoverageSource(
            db, tmp_path / "starts.csv", history_floor_path=tmp_path / "floor.txt",
            now=lambda: datetime(2025, 3, 7, 18, tzinfo=UTC),
        )
        full = _manager(db, full_root, coverage, FakeProvider(manager.provider.bars))
        assert full.update(UpdateRequest(("jm",), None, date(2025, 3, 7), apply=True)).status == "passed"
        reads = []
        original = manager.store.read_catalog_partition

        def read(row):
            reads.append((row.dataset, row.year, row.month))
            return original(row)

        monkeypatch.setattr(manager.store, "read_catalog_partition", read)
        phases = []
        result = manager.update(UpdateRequest(
            ("jm",), None, date(2025, 3, 7), apply=True, mode="daily",
        ), observer=phases.append)
        assert result.status == "passed"
        assert all(month != 1 for _key, _year, month in reads)
        assert manager.metadata.calls == []
        daily_rows = manager.catalog.product_partitions("jm")
        full_rows = full.catalog.product_partitions("jm")
        assert {(r.dataset, r.year, r.month) for r in daily_rows} == {
            (r.dataset, r.year, r.month) for r in full_rows
        }
        full_by_key = {(r.dataset, r.year, r.month): r for r in full_rows}
        for row in daily_rows:
            other = full_by_key[(row.dataset, row.year, row.month)]
            assert original(row) == full.store.read_catalog_partition(other)
        # 1m source reads are once for each family-month batch plus strict publication readback.
        assert sum(key.frequency is BarFrequency.M1 for key, _year, _month in reads) <= 12
        print("daily_apply_phase_seconds", {
            phase: round(sum(event.elapsed_seconds for event in phases
                             if event.phase == phase and event.state == "completed"), 6)
            for phase in ("planning", "reading", "provider", "publishing", "aggregation")
        })


def test_daily_new_dominant_downloads_only_proven_rank1_days(daily_manager):
    from app.models import Contract
    from sqlalchemy import update
    manager = daily_manager
    db = manager.catalog.session
    db.add(Contract(
        contract_code="JM2601", instrument_symbol="jm", exchange_code="DCE",
        listed_date=date(2025, 1, 1), expired_date=date(2026, 2, 1), provider="rqdata",
    ))
    db.execute(update(MainContractMap).where(
        MainContractMap.trade_date >= date(2025, 3, 5),
    ).values(contract_code="JM2601"))
    db.commit()
    for key, bars in tuple(manager.provider.bars.items()):
        if key[0] == "contract":
            manager.provider.bars[(key[0], key[1], "JM2601", key[3])] = bars
    result = manager.update(UpdateRequest(
        ("jm",), None, date(2025, 3, 7), apply=True, mode="daily",
    ))
    assert result.status == "passed"
    new_calls = [(key, ends) for key, ends in manager.provider.calls
                 if key.series_or_contract == "JM2601"]
    assert new_calls
    assert all(end.date() >= date(2025, 3, 5) for key, ends in new_calls
               if key.frequency is BarFrequency.M1 for end in ends)
    assert {end.date() for key, ends in new_calls if key.frequency is BarFrequency.D1
            for end in ends} == {date(2025, 3, day) for day in range(3, 8)}
    assert all(row.month == 3 for row in manager.catalog.product_partitions("jm")
               if row.dataset.series_or_contract == "JM2601")


def test_daily_historical_mapping_gap_fails_before_provider(daily_manager):
    from sqlalchemy import delete
    manager = daily_manager
    manager.catalog.session.execute(delete(MainContractMap).where(
        MainContractMap.trade_date == date(2025, 1, 7),
    ))
    manager.catalog.session.commit()
    with pytest.raises(ValueError, match="HISTORICAL_MAINTENANCE_REQUIRED"):
        manager.update(UpdateRequest(
            ("jm",), None, date(2025, 3, 7), apply=True, mode="daily",
        ))
    assert manager.provider.calls == []
    assert manager.metadata.calls == []


def test_daily_unknown_historical_boundary_requires_explicit_maintenance(daily_manager):
    from sqlalchemy import delete
    manager = daily_manager
    manager.catalog.session.execute(delete(TradingSession).where(
        TradingSession.effective_from == date(2025, 1, 1),
    ))
    manager.catalog.session.commit()
    with pytest.raises(ValueError, match="HISTORICAL_MAINTENANCE_REQUIRED"):
        manager.update(UpdateRequest(
            ("jm",), None, date(2025, 3, 7), apply=True, mode="daily",
        ))
    assert manager.provider.calls == []


def test_daily_quota_stops_and_fresh_manager_resumes(daily_manager):
    manager = daily_manager
    manager.provider.quota_after = 2
    result = manager.update(UpdateRequest(
        ("jm",), None, date(2025, 3, 7), apply=True, mode="daily",
    ))
    assert result.status == "partial" and result.stop_reason == "provider_quota_exhausted"
    assert result.applied > 0 and len(manager.provider.calls) == 3
    manager.provider.quota_after = None
    manager.provider.calls.clear()
    restarted = _manager(manager.catalog.session, manager.store.root, manager.coverage, manager.provider)
    result = restarted.update(UpdateRequest(
        ("jm",), None, date(2025, 3, 7), apply=True, mode="daily",
    ))
    assert result.status == "passed"
    assert restarted.update(UpdateRequest(
        ("jm",), None, date(2025, 3, 7), apply=True, mode="daily",
    )).status == "noop"


@pytest.mark.parametrize("phase", ["planning", "reading", "provider", "publishing", "aggregation"])
def test_daily_observer_failure_escapes_family_isolation(daily_manager, phase):
    manager = daily_manager
    events = []

    def observer(event):
        events.append(event)
        if event.phase == phase and event.state == "started":
            raise OSError("simulated progress destination failure")

    with pytest.raises(RuntimeError, match="MAINTENANCE_OBSERVER_FAILED"):
        manager.update(UpdateRequest(
            ("jm",), None, date(2025, 3, 7), apply=True, mode="daily",
        ), observer=observer)
    assert events[-1].phase == phase
    assert all(event.elapsed_seconds >= 0 and event.total is None for event in events)


def test_full_update_is_default_and_daily_since_is_rejected(daily_manager):
    request = UpdateRequest(("jm",), date(2025, 2, 1), date(2025, 3, 7))
    assert daily_manager.update(request).status == "planned"
    with pytest.raises(ValueError, match="DAILY_UPDATE_SINCE_UNSUPPORTED"):
        daily_manager.update(replace(request, mode="daily"))


def test_daily_read_work_is_independent_of_complete_historical_month_count(daily_manager, monkeypatch):
    from sqlalchemy import event
    from time import monotonic
    manager = daily_manager
    manager.update(UpdateRequest(("jm",), None, date(2025, 3, 7), apply=True))
    original = manager.store.read_catalog_partition
    reads = []
    queries = []

    def read(row):
        reads.append((row.year, row.month))
        return original(row)

    def queried(_connection, _cursor, statement, _parameters, _context, _many):
        queries.append(statement.split()[0])

    monkeypatch.setattr(manager.store, "read_catalog_partition", read)
    engine = manager.catalog.session.get_bind()
    event.listen(engine, "before_cursor_execute", queried)
    samples = []
    try:
        for historical_years in (0, 2):
            if historical_years:
                _extend_complete_history(manager)
            reads.clear()
            queries.clear()
            phases = []
            start = monotonic()
            result = manager.update(UpdateRequest(
                ("jm",), None, date(2025, 3, 7), mode="daily",
            ), observer=phases.append)
            assert result.status == "noop"
            assert set(reads) == {(2025, 3)}
            samples.append((historical_years, len(reads), len(queries), monotonic() - start))
            assert any(item.phase == "planning" and item.state == "completed" for item in phases)
    finally:
        event.remove(engine, "before_cursor_execute", queried)
    assert samples[0][1:3] == samples[1][1:3]
    print("daily_history_size_benchmark", samples)


def _extend_complete_history(manager):
    """Add two years of real complete Catalog/Parquet fixtures outside the daily window."""
    from sqlalchemy import select, update
    from app.models import Contract
    from app.market_data.historical_data_manager import _months
    db = manager.catalog.session
    db.execute(update(Contract).values(listed_date=date(2023, 1, 1)))
    existing_calendar = {row.trade_date: row.is_trading_day for row in db.scalars(
        select(TradingCalendar)
    )}
    day = date(2022, 12, 1)
    while day <= date(2024, 12, 31):
        # Sparse valid trading calendar keeps the benchmark cheap; complete natural dates
        # and exact Session/rank1 facts remain authoritative, never a forged row-count baseline.
        trading = existing_calendar.get(day, day.weekday() == 0 and day.day <= 7)
        if day not in existing_calendar:
            db.add(TradingCalendar(
                exchange_code="DCE", trade_date=day, is_trading_day=trading,
                has_night_session=False, provider="rqdata",
            ))
        if trading and day >= date(2023, 1, 1):
            db.add(TradingSession(
                exchange_code="DCE", instrument_symbol="jm", session_name="day",
                start_time=time(9), end_time=time(9, 5), crosses_midnight=False,
                effective_from=day, effective_to=day, is_active=True, provider="rqdata",
            ))
            db.add(MainContractMap(symbol="jm", trade_date=day, contract_code="JM2509", rank=1))
        day += timedelta(days=1)
    db.commit()
    manager.coverage.starts["jm"] = date(2023, 1, 1)
    manager.coverage.history_floor = date(2023, 1, 1)
    for key_tuple in tuple(manager.provider.bars):
        key = DatasetKey(*key_tuple)
        ends = tuple(stamp for year, month in _months(date(2023, 1, 1), date(2024, 12, 31))
                     for stamp in manager.coverage.expected_bar_ends(
                         key, year, month, date(2023, 1, 1), date(2024, 12, 31),
                     ))
        old_bars = tuple(CanonicalBar(
            stamp, stamp.date(), Decimal(10), Decimal(10), Decimal(10), Decimal(10),
            Decimal(1), Decimal(10), Decimal(20),
        ) for stamp in ends)
        manager.provider.bars[key_tuple] = old_bars + manager.provider.bars[key_tuple]
    phases = []
    result = manager.update(UpdateRequest(
        ("jm",), None, date(2024, 12, 31), apply=True,
    ), observer=phases.append)
    assert result.status == "passed"
    assert len({(row.year, row.month) for row in manager.catalog.product_partitions("jm")}) == 27
    print("historical_fixture_apply_phase_seconds", {
        phase: round(sum(event.elapsed_seconds for event in phases
                         if event.phase == phase and event.state == "completed"), 6)
        for phase in ("reading", "provider", "publishing", "aggregation")
    })


def test_metadata_session_validation_sql_count_does_not_scale_with_days(daily_manager):
    from sqlalchemy import event
    coverage = daily_manager.coverage
    queries = []

    def queried(_connection, _cursor, statement, _parameters, _context, _many):
        queries.append(statement.split()[0])

    engine = daily_manager.catalog.session.get_bind()
    event.listen(engine, "before_cursor_execute", queried)
    counts = []
    try:
        for through in (date(2025, 1, 3), date(2025, 3, 7)):
            queries.clear()
            coverage.require_historical_session_facts(("jm",), through)
            counts.append(len(queries))
    finally:
        event.remove(engine, "before_cursor_execute", queried)
    assert counts[0] == counts[1] and counts[0] <= 6
    print("session_validation_query_counts", counts)


def test_daily_commit_unknown_stops_entire_attempt(daily_manager, monkeypatch):
    manager = daily_manager
    commits = []

    def fail_commit():
        commits.append(1)
        raise OSError("connection lost after attempted commit")

    monkeypatch.setattr(manager.catalog.session, "commit", fail_commit)
    from app.market_data.storage import StorageError
    with pytest.raises(StorageError, match="COMMIT_OUTCOME_UNKNOWN"):
        manager.update(UpdateRequest(
            ("jm",), None, date(2025, 3, 7), apply=True, mode="daily",
        ))
    assert len(commits) == 1
    assert len(manager.provider.calls) == 1


def test_daily_maintenance_lock_precedes_metadata_and_observer(daily_manager, monkeypatch):
    manager = daily_manager
    monkeypatch.setattr(manager.catalog, "acquire_maintenance_lock", lambda: None)
    events = []
    result = manager.update(UpdateRequest(
        ("jm",), None, date(2025, 3, 7), apply=True,
        sync_current_day_metadata=True, mode="daily",
    ), observer=events.append)
    assert result.status == "blocked"
    assert events == []
    assert manager.metadata.current_day_calls == []
    assert manager.provider.calls == []


@pytest.mark.parametrize("through", [date(2025, 4, 4), date(2026, 1, 2)])
def test_daily_weekly_refresh_keeps_cross_month_and_year_daily_context(daily_manager, through):
    from sqlalchemy import update
    from app.models import Contract
    manager = daily_manager
    db = manager.catalog.session
    db.execute(update(Contract).values(expired_date=date(2026, 2, 1)))
    end = through + timedelta(days=7 - through.isoweekday())
    day = date(2025, 3, 10)
    while day <= end:
        trading = day.weekday() < 5
        db.add(TradingCalendar(
            exchange_code="DCE", trade_date=day, is_trading_day=trading,
            has_night_session=False, provider="rqdata",
        ))
        if trading:
            db.add(TradingSession(
                exchange_code="DCE", instrument_symbol="jm", session_name="day",
                start_time=time(9), end_time=time(9, 5), crosses_midnight=False,
                effective_from=day, effective_to=day, is_active=True, provider="rqdata",
            ))
            db.add(MainContractMap(symbol="jm", trade_date=day, contract_code="JM2509", rank=1))
        day += timedelta(days=1)
    db.commit()
    manager.coverage._now = lambda: datetime.combine(through, time(18), tzinfo=UTC)
    from app.market_data.historical_data_manager import _months
    for key_tuple in tuple(manager.provider.bars):
        key = DatasetKey(*key_tuple)
        ends = tuple(stamp for year, month in _months(date(2025, 1, 1), through)
                     for stamp in manager.coverage.expected_bar_ends(
                         key, year, month, date(2025, 1, 1), through,
                     ))
        manager.provider.bars[key_tuple] = tuple(CanonicalBar(
            stamp, stamp.date(), Decimal(10), Decimal(10), Decimal(10), Decimal(10),
            Decimal(1), Decimal(10), Decimal(20),
        ) for stamp in ends)
    prior = through - timedelta(days=7)
    assert manager.update(UpdateRequest(("jm",), None, prior, apply=True)).status == "passed"
    # Switch on Wednesday with stale same-contract D1 already present before rank1.
    monday = through - timedelta(days=4)
    db.add(Contract(
        contract_code="JM2601", instrument_symbol="jm", exchange_code="DCE",
        listed_date=date(2025, 1, 1), expired_date=date(2026, 2, 1), provider="rqdata",
    ))
    db.execute(update(MainContractMap).where(
        MainContractMap.trade_date >= monday + timedelta(days=2),
    ).values(contract_code="JM2601"))
    db.commit()
    for key, bars in tuple(manager.provider.bars.items()):
        if key[0] == "contract":
            manager.provider.bars[(key[0], key[1], "JM2601", key[3])] = bars
    daily_key = DatasetKey(DatasetKind.CONTRACT, "jm", "JM2601", BarFrequency.D1)
    stale = tuple(bar for bar in manager.provider.bars[daily_key.as_tuple()]
                  if bar.trading_day in (prior, monday))
    for year, month in {(bar.trading_day.year, bar.trading_day.month) for bar in stale}:
        month_bars = tuple(bar for bar in stale if (bar.trading_day.year, bar.trading_day.month) == (year, month))
        manager.catalog.register_partition(manager.store.publish(PublishRequest(
            daily_key, year, month, month_bars, tuple(bar.bar_end for bar in month_bars),
        )))
    db.commit()
    original_fetch = manager.provider.fetch_many
    snapshots = []

    def fetch(requests):
        batches = original_fetch(requests)
        if not any(request.key.series_or_contract == "JM2601" for request in requests):
            return batches
        from app.market_data.historical_data_manager import BarBatch
        revision = Decimal(len(snapshots) + 10)
        snapshots.append(requests)
        return tuple(BarBatch(tuple(replace(
            bar, volume=revision * (5 if request.key.frequency is BarFrequency.W1 else 1),
        ) for bar in batch.bars)) for request, batch in zip(requests, batches, strict=True))

    manager.provider.fetch_many = fetch
    manager.provider.calls.clear()
    result = manager.update(UpdateRequest(
        ("jm",), None, through, mode="daily", apply=True,
    ))
    assert result.status == "passed"
    daily_context = {stamp.date() for key, stamps in manager.provider.calls
                     if key.kind is DatasetKind.CONTINUOUS and key.frequency is BarFrequency.D1
                     for stamp in stamps}
    assert {monday + timedelta(days=offset) for offset in range(5)} <= daily_context
    assert (monday.year, monday.month) != (through.year, through.month)
    stored_daily = tuple(bar for row in manager.catalog.all_partitions(daily_key)
                         for bar in manager.store.read_catalog_partition(row))
    week_daily = tuple(bar for bar in stored_daily if monday <= bar.trading_day <= through)
    weekly_key = DatasetKey(DatasetKind.CONTRACT, "jm", "JM2601", BarFrequency.W1)
    weekly = tuple(bar for row in manager.catalog.all_partitions(weekly_key)
                   for bar in manager.store.read_catalog_partition(row))
    assert len(week_daily) == 5
    assert sum(bar.volume for bar in week_daily) == weekly[-1].volume
    assert next(bar for bar in stored_daily if bar.trading_day == prior).volume == Decimal(1)
    week_batch = next(requests for requests in snapshots
                      if any(request.key.frequency is BarFrequency.W1 for request in requests))
    assert {stamp.date() for request in week_batch if request.key.frequency is BarFrequency.D1
            for stamp in request.expected} == {monday + timedelta(days=n) for n in range(5)}
    assert manager.update(UpdateRequest(
        ("jm",), None, through, mode="daily", apply=True,
    )).status == "noop"


def test_within_batch_source_reuse_invalidates_on_catalog_pointer_change(daily_manager, monkeypatch):
    from app.market_data.historical_data_manager import _Target
    manager = daily_manager
    source_key = DatasetKey(DatasetKind.CONTINUOUS, "jm", "MAIN", BarFrequency.M1)
    derived_key = DatasetKey(DatasetKind.CONTINUOUS, "jm", "MAIN", BarFrequency.M15)
    source_row = manager.catalog.all_partitions(source_key)[0]
    source_bars = manager.store.read_catalog_partition(source_row)
    expected = manager.coverage.expected_bar_ends(
        derived_key, 2025, 1, date(2025, 1, 1), date(2025, 1, 31),
    )
    target = _Target(derived_key, 2025, 1, expected, expected, ())
    original = manager._read_existing
    source_reads = []

    def read(key, year, month):
        source_reads.append(key)
        return original(key, year, month)

    monkeypatch.setattr(manager, "_read_existing", read)
    manager._source_cache = {}
    manager._publish_derived(target)
    manager._publish_derived(target)
    assert source_reads == [source_key]
    revised = tuple(replace(bar, open=Decimal(12), high=Decimal(12),
                            low=Decimal(12), close=Decimal(12)) for bar in source_bars)
    partition = manager.store.publish(PublishRequest(
        source_key, 2025, 1, revised, tuple(bar.bar_end for bar in revised),
    ))
    manager.catalog.register_partition(partition)
    manager.catalog.session.commit()
    manager._publish_derived(target)
    assert source_reads == [source_key, source_key]
    row = manager.catalog.all_partitions(derived_key)[0]
    assert all(bar.close == Decimal(12) for bar in manager.store.read_catalog_partition(row))


@pytest.mark.parametrize("missing", ["calendar", "session"])
def test_physical_week_context_missing_metadata_fails_before_fetch(daily_manager, missing):
    from sqlalchemy import delete
    from app.market_data.errors import InfrastructureError
    from app.market_data.historical_data_manager import _Target
    manager = daily_manager
    day = date(2025, 3, 4)
    table = TradingCalendar if missing == "calendar" else TradingSession
    field = table.trade_date if missing == "calendar" else table.effective_from
    manager.catalog.session.execute(delete(table).where(field == day))
    manager.catalog.session.commit()
    end = datetime(2025, 3, 7, 1, 5, tzinfo=UTC)
    target = _Target(DatasetKey("contract", "jm", "JM2509", "1w"), 2025, 3,
                     (end,), (end,), ())
    before = manager.catalog.product_partitions("jm")
    with pytest.raises(InfrastructureError, match="HISTORICAL_SESSION_FACT_MISSING"):
        manager._weekly_daily_companions(target, date(2025, 3, 7))
    assert manager.provider.calls == []
    assert manager.catalog.product_partitions("jm") == before


def test_physical_week_context_starts_at_contract_listing(daily_manager):
    from app.models import Contract
    from app.market_data.historical_data_manager import _Target
    manager = daily_manager
    manager.catalog.session.add(Contract(
        contract_code="JM2601", instrument_symbol="jm", exchange_code="DCE",
        listed_date=date(2025, 3, 5), expired_date=date(2026, 2, 1), provider="rqdata",
    ))
    manager.catalog.session.commit()
    end = datetime(2025, 3, 7, 1, 5, tzinfo=UTC)
    target = _Target(DatasetKey("contract", "jm", "JM2601", "1w"), 2025, 3,
                     (end,), (end,), ())
    companions = manager._weekly_daily_companions(target, date(2025, 3, 7))
    assert {stamp.date() for companion in companions for stamp in companion.missing} == {
        date(2025, 3, 5), date(2025, 3, 6), date(2025, 3, 7),
    }
