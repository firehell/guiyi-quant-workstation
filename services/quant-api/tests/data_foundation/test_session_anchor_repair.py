from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.aggregation import SessionWindow, aggregate_from_1m
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey
from app.market_data.historical_data_manager import BarBatch
from app.market_data.rqdata_adapter import _normalized_historical_session_periods
from app.market_data.session_anchor_repair import (
    SessionAnchorRepairError,
    SessionAnchorRepairService,
    local_runtime_stopped,
)
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.models import (
    Exchange,
    Instrument,
    MarketDataset,
    MarketPartition,
    TradingCalendar,
    TradingSession,
)


def _bar(bar_end: datetime, price: int) -> CanonicalBar:
    value = Decimal(price)
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=date(2026, 9, 1),
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal(1),
        turnover=Decimal(1),
        open_interest=Decimal(1),
    )


def _minute_bars(window: SessionWindow, *, first_price: int) -> tuple[CanonicalBar, ...]:
    count = int((window.end - window.start).total_seconds() // 60)
    return tuple(
        _bar(window.start + timedelta(minutes=offset), first_price + offset - 1)
        for offset in range(1, count + 1)
    )


def test_corrected_session_windows_anchor_all_day_and_night_15m_buckets() -> None:
    morning_periods = _normalized_historical_session_periods(
        "09:01-10:15,10:31-11:30,13:31-15:00"
    )
    assert morning_periods == (
        (time(9), time(10, 15)),
        (time(10, 30), time(11, 30)),
        (time(13, 30), time(15)),
    )
    morning = tuple(
        SessionWindow(
            datetime.combine(date(2026, 9, 1), start, tzinfo=UTC),
            datetime.combine(date(2026, 9, 1), end, tzinfo=UTC),
        )
        for start, end in morning_periods
    )
    morning_bars = tuple(
        bar
        for index, window in enumerate(morning)
        for bar in _minute_bars(window, first_price=1000 + index * 100)
    )

    morning_15m = aggregate_from_1m(
        morning_bars,
        target_frequency=BarFrequency.M15,
        sessions=morning,
    )

    assert [bar.bar_end.time() for bar in morning_15m] == [
        time(9, 15),
        time(9, 30),
        time(9, 45),
        time(10),
        time(10, 15),
        time(10, 45),
        time(11),
        time(11, 15),
        time(11, 30),
        time(13, 45),
        time(14),
        time(14, 15),
        time(14, 30),
        time(14, 45),
        time(15),
    ]
    assert morning_15m[0].open == morning_bars[0].open
    assert morning_15m[5].open == Decimal(1100)
    assert morning_15m[9].open == Decimal(1200)

    assert _normalized_historical_session_periods("21:01-02:30") == (
        (time(21), time(2, 30)),
    )
    overnight = SessionWindow(
        datetime.combine(date(2026, 9, 1), time(21), tzinfo=UTC),
        datetime.combine(date(2026, 9, 2), time(2, 30), tzinfo=UTC),
    )
    overnight_15m = aggregate_from_1m(
        _minute_bars(overnight, first_price=2000),
        target_frequency=BarFrequency.M15,
        sessions=(overnight,),
    )

    assert overnight_15m[0].bar_end == datetime(2026, 9, 1, 21, 15, tzinfo=UTC)
    assert datetime(2026, 9, 2, 0, 15, tzinfo=UTC) in {
        bar.bar_end for bar in overnight_15m
    }
    assert overnight_15m[-1].bar_end == datetime(2026, 9, 2, 2, 30, tzinfo=UTC)


class MissingMinuteProvider:
    def __init__(self, missing: CanonicalBar) -> None:
        self.missing = missing
        self.requests = []

    def fetch_many(self, requests):
        self.requests.extend(requests)
        assert len(requests) == 1
        assert requests[0].expected == (self.missing.bar_end,)
        return (BarBatch((self.missing,)),)


@pytest.fixture
def repair_context(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Exchange(code="DCE", name="DCE"))
    session.add(Instrument(symbol="jm", name="JM", exchange_code="DCE", is_active=True))
    session.add_all([
        TradingCalendar(
            exchange_code="DCE",
            trade_date=date(2026, 8, 31),
            is_trading_day=True,
            provider="rqdata",
        ),
        TradingCalendar(
            exchange_code="DCE",
            trade_date=date(2026, 9, 1),
            is_trading_day=True,
            provider="rqdata",
        ),
        TradingSession(
            exchange_code="DCE",
            instrument_symbol="jm",
            session_name="day",
            start_time=time(9, 1),
            end_time=time(9, 15),
            effective_from=date(2026, 9, 1),
            effective_to=date(2026, 9, 1),
            crosses_midnight=False,
            is_active=True,
            provider="rqdata",
        ),
    ])
    session.execute(text("CREATE TABLE alembic_version (version_num varchar(32))"))
    session.execute(text(
        "INSERT INTO alembic_version (version_num) VALUES ('20260902_0044')"
    ))
    session.commit()

    root = tmp_path / "canonical"
    store = CanonicalMonthlyStore(root)
    catalog = MarketCatalog(session, root)
    start = datetime(2026, 9, 1, 1, 1, tzinfo=UTC)
    current = tuple(_bar(start + timedelta(minutes=offset), 100 + offset) for offset in range(1, 15))
    wrong_window = SessionWindow(start, datetime(2026, 9, 1, 1, 15, tzinfo=UTC))
    for frequency in (
        BarFrequency.M1,
        BarFrequency.M5,
        BarFrequency.M15,
        BarFrequency.M30,
        BarFrequency.H1,
    ):
        key = DatasetKey("continuous", "jm", "MAIN", frequency)
        bars = current if frequency is BarFrequency.M1 else aggregate_from_1m(
            current,
            target_frequency=frequency,
            sessions=(wrong_window,),
        )
        published = store.publish(PublishRequest(
            key,
            2026,
            9,
            bars,
            tuple(bar.bar_end for bar in bars),
        ))
        catalog.register_partition(published)
    session.commit()
    missing = _bar(datetime(2026, 9, 1, 1, 1, tzinfo=UTC), 99)
    provider = MissingMinuteProvider(missing)
    unchanged_daily = root / "preserve" / "frequency=1d" / "part.parquet"
    unchanged_daily.parent.mkdir(parents=True)
    unchanged_daily.write_bytes(b"daily-fact-must-not-change")
    try:
        yield session, root, provider
    finally:
        session.close()
        engine.dispose()


def test_plan_reports_stable_scope_without_provider_or_file_writes(
    repair_context,
    tmp_path: Path,
) -> None:
    session, root, provider = repair_context
    shadow = tmp_path / "shadow"
    service = SessionAnchorRepairService(session, canonical_root=root, provider=provider)

    result = service.plan()

    assert result.status == "planned"
    assert result.readonly is True
    assert result.session_count == 1
    assert result.dataset_count == 5
    assert result.partition_count == 5
    assert result.missing_first_minute_count == 1
    assert len(result.scope_sha256) == 64
    assert len(result.affected_session_ids) == 1
    assert len(result.affected_datasets) == 5
    assert len(result.affected_partitions) == 5
    assert provider.requests == []
    assert not shadow.exists()


def test_plan_rejects_a_non_anchor_gap_instead_of_expanding_repair_scope(
    repair_context,
) -> None:
    session, root, provider = repair_context
    key = DatasetKey("continuous", "jm", "MAIN", "1m")
    store = CanonicalMonthlyStore(root)
    current = store.read_month(key, 2026, 9)
    with_gap = tuple(bar for bar in current if bar.bar_end.minute != 10)
    store.publish(PublishRequest(
        key,
        2026,
        9,
        with_gap,
        tuple(bar.bar_end for bar in with_gap),
    ))
    service = SessionAnchorRepairService(session, canonical_root=root, provider=provider)

    with pytest.raises(SessionAnchorRepairError, match="SESSION_ANCHOR_BASE_INVALID"):
        service.plan()

    assert provider.requests == []


def test_prepare_rebuilds_shadow_from_real_missing_minute_without_touching_active(
    repair_context,
    tmp_path: Path,
) -> None:
    session, root, provider = repair_context
    shadow = tmp_path / "shadow"
    manifest = tmp_path / "session-anchor-manifest.json"
    service = SessionAnchorRepairService(session, canonical_root=root, provider=provider)
    active_before = CanonicalMonthlyStore(root).read_month(
        DatasetKey("continuous", "jm", "MAIN", "1m"), 2026, 9
    )

    result = service.prepare(shadow_root=shadow, manifest_path=manifest, apply=True)

    assert result.status == "prepared"
    assert result.readonly is False
    assert result.partition_count == 5
    assert manifest.is_file()
    assert CanonicalMonthlyStore(root).read_month(
        DatasetKey("continuous", "jm", "MAIN", "1m"), 2026, 9
    ) == active_before
    corrected_1m = CanonicalMonthlyStore(shadow).read_month(
        DatasetKey("continuous", "jm", "MAIN", "1m"), 2026, 9
    )
    corrected_15m = CanonicalMonthlyStore(shadow).read_month(
        DatasetKey("continuous", "jm", "MAIN", "15m"), 2026, 9
    )
    assert len(corrected_1m) == 15
    assert corrected_1m[0].bar_end == datetime(2026, 9, 1, 1, 1, tzinfo=UTC)
    assert corrected_15m[0].bar_end == datetime(2026, 9, 1, 1, 15, tzinfo=UTC)
    assert corrected_15m[0].open == Decimal(99)
    assert (
        shadow / "preserve" / "frequency=1d" / "part.parquet"
    ).read_bytes() == b"daily-fact-must-not-change"


def test_prepare_failure_keeps_active_and_never_creates_publishable_manifest(
    repair_context,
    tmp_path: Path,
) -> None:
    session, root, _provider = repair_context
    shadow = tmp_path / "shadow"
    manifest = tmp_path / "manifest.json"

    class IncompleteProvider:
        def fetch_many(self, _requests):
            return (BarBatch(()),)

    service = SessionAnchorRepairService(
        session,
        canonical_root=root,
        provider=IncompleteProvider(),
    )
    active_before = CanonicalMonthlyStore(root).read_month(
        DatasetKey("continuous", "jm", "MAIN", "1m"), 2026, 9
    )

    with pytest.raises(SessionAnchorRepairError, match="SESSION_ANCHOR_PROVIDER_INVALID"):
        service.prepare(shadow_root=shadow, manifest_path=manifest, apply=True)

    assert CanonicalMonthlyStore(root).read_month(
        DatasetKey("continuous", "jm", "MAIN", "1m"), 2026, 9
    ) == active_before
    assert shadow.is_dir()
    assert not manifest.exists()


def test_publish_requires_stopped_runtime_before_any_mutation(
    repair_context,
    tmp_path: Path,
) -> None:
    session, root, provider = repair_context
    shadow = tmp_path / "shadow"
    manifest = tmp_path / "manifest.json"
    service = SessionAnchorRepairService(
        session,
        canonical_root=root,
        provider=provider,
        runtime_stopped=lambda: False,
    )
    service.prepare(shadow_root=shadow, manifest_path=manifest, apply=True)

    with pytest.raises(SessionAnchorRepairError, match="RUNTIME_NOT_STOPPED"):
        service.publish(shadow_root=shadow, manifest_path=manifest, apply=True)

    assert root.is_dir()
    assert shadow.is_dir()
    assert session.scalar(text("SELECT version_num FROM alembic_version")) == "20260902_0044"


def test_publish_switches_root_reconciles_catalog_then_crosses_forward_boundary(
    repair_context,
    tmp_path: Path,
) -> None:
    session, root, provider = repair_context
    shadow = tmp_path / "shadow"
    manifest = tmp_path / "manifest.json"
    cleaned: list[date] = []
    lease_state = {"acquired": False, "released": False}

    class Lease:
        def release(self) -> None:
            lease_state["released"] = True

    def acquire_lock():
        lease_state["acquired"] = True
        return Lease()

    def migrate() -> None:
        assert lease_state == {"acquired": True, "released": False}
        row = session.scalar(select(TradingSession))
        assert row is not None
        row.start_time = time(9)
        session.execute(text(
            "UPDATE alembic_version SET version_num = '20260903_0045'"
        ))
        session.commit()

    def cleanup(day: date) -> None:
        assert lease_state == {"acquired": True, "released": False}
        cleaned.append(day)

    service = SessionAnchorRepairService(
        session,
        canonical_root=root,
        provider=provider,
        runtime_stopped=lambda: True,
        migration_runner=migrate,
        current_trading_day=lambda: date(2026, 9, 2),
        live_cleanup=cleanup,
        acquire_maintenance_lock=acquire_lock,
    )
    service.prepare(shadow_root=shadow, manifest_path=manifest, apply=True)

    result = service.publish(shadow_root=shadow, manifest_path=manifest, apply=True)

    assert result.status == "published"
    assert result.readonly is False
    assert result.forward_only is True
    assert not shadow.exists()
    assert result.rollback_root.is_dir()
    assert len(CanonicalMonthlyStore(root).read_month(
        DatasetKey("continuous", "jm", "MAIN", "1m"), 2026, 9
    )) == 15
    row_count = session.scalar(
        select(MarketPartition.row_count)
        .join(MarketDataset, MarketDataset.id == MarketPartition.dataset_id)
        .where(MarketDataset.frequency == "1m")
    )
    assert row_count == 15
    assert session.scalar(text("SELECT version_num FROM alembic_version")) == "20260903_0045"
    assert cleaned == [date(2026, 9, 2)]
    assert lease_state == {"acquired": True, "released": True}


def test_publish_fails_before_preflight_when_maintenance_lock_is_unavailable(
    repair_context,
    tmp_path: Path,
) -> None:
    session, root, provider = repair_context
    shadow = tmp_path / "shadow"
    manifest = tmp_path / "manifest.json"
    runtime_probed = False

    def runtime_stopped() -> bool:
        nonlocal runtime_probed
        runtime_probed = True
        return True

    service = SessionAnchorRepairService(
        session,
        canonical_root=root,
        provider=provider,
        runtime_stopped=runtime_stopped,
        acquire_maintenance_lock=lambda: None,
    )
    service.prepare(shadow_root=shadow, manifest_path=manifest, apply=True)

    with pytest.raises(
        SessionAnchorRepairError,
        match="SESSION_ANCHOR_MAINTENANCE_LOCKED",
    ):
        service.publish(shadow_root=shadow, manifest_path=manifest, apply=True)

    assert runtime_probed is False
    assert root.is_dir()
    assert shadow.is_dir()


def test_publish_preserves_original_failure_when_maintenance_release_fails(
    repair_context,
    tmp_path: Path,
) -> None:
    session, root, provider = repair_context
    shadow = tmp_path / "shadow"
    manifest = tmp_path / "manifest.json"

    class BrokenLease:
        def release(self) -> None:
            raise RuntimeError("unlock failed")

    service = SessionAnchorRepairService(
        session,
        canonical_root=root,
        provider=provider,
        runtime_stopped=lambda: False,
        acquire_maintenance_lock=BrokenLease,
    )
    service.prepare(shadow_root=shadow, manifest_path=manifest, apply=True)

    with pytest.raises(SessionAnchorRepairError, match="RUNTIME_NOT_STOPPED"):
        service.publish(shadow_root=shadow, manifest_path=manifest, apply=True)


def test_publish_maps_release_failure_after_success_to_forward_recovery(
    repair_context,
    tmp_path: Path,
) -> None:
    session, root, provider = repair_context
    shadow = tmp_path / "shadow"
    manifest = tmp_path / "manifest.json"

    class BrokenLease:
        def release(self) -> None:
            raise RuntimeError("unlock failed")

    def migrate() -> None:
        row = session.scalar(select(TradingSession))
        assert row is not None
        row.start_time = time(9)
        session.execute(text(
            "UPDATE alembic_version SET version_num = '20260903_0045'"
        ))
        session.commit()

    service = SessionAnchorRepairService(
        session,
        canonical_root=root,
        provider=provider,
        runtime_stopped=lambda: True,
        migration_runner=migrate,
        current_trading_day=lambda: date(2026, 9, 2),
        live_cleanup=lambda _: None,
        acquire_maintenance_lock=BrokenLease,
    )
    service.prepare(shadow_root=shadow, manifest_path=manifest, apply=True)

    with pytest.raises(
        SessionAnchorRepairError,
        match="SESSION_ANCHOR_FORWARD_RECOVERY_REQUIRED",
    ):
        service.publish(shadow_root=shadow, manifest_path=manifest, apply=True)

    assert session.scalar(text("SELECT version_num FROM alembic_version")) == (
        "20260903_0045"
    )
    assert root.with_name(f"{root.name}.pre-session-anchor-0045").is_dir()


def test_runtime_stop_probe_requires_all_five_launchd_services_absent() -> None:
    calls = []

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        label = arguments[-1].rsplit("/", maxsplit=1)[-1]
        return type("Result", (), {
            "returncode": 0 if label == "com.guiyi.quant-web" else 113,
            "stderr": (
                "" if label == "com.guiyi.quant-web" else
                f'Could not find service "{label}" in domain for user gui: 501'
            ),
        })()

    assert local_runtime_stopped(run=run, uid=501) is False
    assert [call[0][-1] for call in calls] == [
        "gui/501/com.guiyi.quant-api",
        "gui/501/com.guiyi.quant-web",
    ]


def test_runtime_stop_probe_fails_closed_on_launchctl_error() -> None:
    def run(*_args, **_kwargs):
        return type("Result", (), {"returncode": 1, "stderr": "permission denied"})()

    with pytest.raises(SessionAnchorRepairError, match="RUNTIME_STOP_PREFLIGHT_FAILED"):
        local_runtime_stopped(run=run, uid=501)


def test_publish_rejects_active_file_drift_before_root_switch(
    repair_context,
    tmp_path: Path,
) -> None:
    session, root, provider = repair_context
    shadow = tmp_path / "shadow"
    manifest = tmp_path / "manifest.json"

    service = SessionAnchorRepairService(
        session,
        canonical_root=root,
        provider=provider,
        runtime_stopped=lambda: True,
        migration_runner=lambda: None,
        current_trading_day=lambda: date(2026, 9, 2),
        live_cleanup=lambda _: None,
    )
    service.prepare(shadow_root=shadow, manifest_path=manifest, apply=True)
    active_partition = next(root.glob("kind=*/symbol=*/series=*/frequency=1m/year=*/month=*/part.parquet"))
    active_partition.write_bytes(active_partition.read_bytes() + b"drift")

    with pytest.raises(SessionAnchorRepairError, match="SESSION_ANCHOR_MANIFEST_DRIFT"):
        service.publish(shadow_root=shadow, manifest_path=manifest, apply=True)

    assert root.is_dir()
    assert shadow.is_dir()
    assert session.scalar(text("SELECT version_num FROM alembic_version")) == "20260902_0044"


def test_publish_rejects_daily_inventory_drift_before_root_switch(
    repair_context,
    tmp_path: Path,
) -> None:
    session, root, provider = repair_context
    shadow = tmp_path / "shadow"
    manifest = tmp_path / "manifest.json"
    service = SessionAnchorRepairService(
        session,
        canonical_root=root,
        provider=provider,
        runtime_stopped=lambda: True,
        migration_runner=lambda: None,
        current_trading_day=lambda: date(2026, 9, 2),
        live_cleanup=lambda _: None,
    )
    service.prepare(shadow_root=shadow, manifest_path=manifest, apply=True)
    added = root / "added" / "frequency=1d" / "part.parquet"
    added.parent.mkdir(parents=True)
    added.write_bytes(b"new-daily-fact")

    with pytest.raises(SessionAnchorRepairError, match="SESSION_ANCHOR_MANIFEST_DRIFT"):
        service.publish(shadow_root=shadow, manifest_path=manifest, apply=True)

    assert root.is_dir()
    assert shadow.is_dir()


@pytest.mark.parametrize("corruption", ["duplicate_identity", "wrong_row_count"])
def test_publish_rejects_manifest_identity_or_physical_metadata_tampering(
    repair_context,
    tmp_path: Path,
    corruption: str,
) -> None:
    session, root, provider = repair_context
    shadow = tmp_path / "shadow"
    manifest = tmp_path / "manifest.json"
    service = SessionAnchorRepairService(
        session,
        canonical_root=root,
        provider=provider,
        runtime_stopped=lambda: True,
        migration_runner=lambda: None,
        current_trading_day=lambda: date(2026, 9, 2),
        live_cleanup=lambda _: None,
    )
    service.prepare(shadow_root=shadow, manifest_path=manifest, apply=True)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if corruption == "duplicate_identity":
        payload["partitions"][-1] = payload["partitions"][0]
        expected_error = "SESSION_ANCHOR_MANIFEST_INVALID"
    else:
        payload["partitions"][0]["new_row_count"] += 1
        expected_error = "SESSION_ANCHOR_MANIFEST_DRIFT"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SessionAnchorRepairError, match=expected_error):
        service.publish(shadow_root=shadow, manifest_path=manifest, apply=True)

    assert root.is_dir()
    assert shadow.is_dir()


def test_publish_restores_root_and_catalog_when_migration_fails_before_0045(
    repair_context,
    tmp_path: Path,
) -> None:
    session, root, provider = repair_context
    shadow = tmp_path / "shadow"
    manifest = tmp_path / "manifest.json"

    def fail_migration() -> None:
        raise RuntimeError("migration failed")

    service = SessionAnchorRepairService(
        session,
        canonical_root=root,
        provider=provider,
        runtime_stopped=lambda: True,
        migration_runner=fail_migration,
        current_trading_day=lambda: date(2026, 9, 2),
        live_cleanup=lambda _: None,
    )
    service.prepare(shadow_root=shadow, manifest_path=manifest, apply=True)

    with pytest.raises(SessionAnchorRepairError, match="SESSION_ANCHOR_PUBLISH_FAILED"):
        service.publish(shadow_root=shadow, manifest_path=manifest, apply=True)

    assert len(CanonicalMonthlyStore(root).read_month(
        DatasetKey("continuous", "jm", "MAIN", "1m"), 2026, 9
    )) == 14
    assert shadow.is_dir()
    assert session.scalar(select(MarketPartition.row_count).join(
        MarketDataset, MarketDataset.id == MarketPartition.dataset_id
    ).where(MarketDataset.frequency == "1m")) == 14
    assert session.scalar(text("SELECT version_num FROM alembic_version")) == "20260902_0044"


def test_publish_keeps_corrected_root_after_0045_cleanup_failure(
    repair_context,
    tmp_path: Path,
) -> None:
    session, root, provider = repair_context
    shadow = tmp_path / "shadow"
    manifest = tmp_path / "manifest.json"

    def migrate() -> None:
        session.execute(text(
            "UPDATE alembic_version SET version_num = '20260903_0045'"
        ))
        session.commit()

    def fail_cleanup(_: date) -> None:
        raise RuntimeError("cleanup failed")

    service = SessionAnchorRepairService(
        session,
        canonical_root=root,
        provider=provider,
        runtime_stopped=lambda: True,
        migration_runner=migrate,
        current_trading_day=lambda: date(2026, 9, 2),
        live_cleanup=fail_cleanup,
    )
    service.prepare(shadow_root=shadow, manifest_path=manifest, apply=True)

    with pytest.raises(
        SessionAnchorRepairError,
        match="SESSION_ANCHOR_FORWARD_RECOVERY_REQUIRED",
    ):
        service.publish(shadow_root=shadow, manifest_path=manifest, apply=True)

    assert len(CanonicalMonthlyStore(root).read_month(
        DatasetKey("continuous", "jm", "MAIN", "1m"), 2026, 9
    )) == 15
    assert root.with_name(f"{root.name}.pre-session-anchor-0045").is_dir()
    assert session.scalar(text("SELECT version_num FROM alembic_version")) == "20260903_0045"


def test_publish_reports_forward_recovery_when_pre0045_compensation_fails(
    repair_context,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, root, provider = repair_context
    shadow = tmp_path / "shadow"
    manifest = tmp_path / "manifest.json"

    def fail_migration() -> None:
        raise RuntimeError("migration failed")

    def fail_catalog_restore(_entries) -> None:
        raise RuntimeError("catalog restore failed")

    service = SessionAnchorRepairService(
        session,
        canonical_root=root,
        provider=provider,
        runtime_stopped=lambda: True,
        migration_runner=fail_migration,
        current_trading_day=lambda: date(2026, 9, 2),
        live_cleanup=lambda _: None,
    )
    service.prepare(shadow_root=shadow, manifest_path=manifest, apply=True)
    monkeypatch.setattr(
        service,
        "_restore_catalog",
        fail_catalog_restore,
    )

    with pytest.raises(
        SessionAnchorRepairError,
        match="SESSION_ANCHOR_FORWARD_RECOVERY_REQUIRED",
    ):
        service.publish(shadow_root=shadow, manifest_path=manifest, apply=True)

    assert root.is_dir()
    assert shadow.is_dir()
    assert not root.with_name(f"{root.name}.pre-session-anchor-0045").exists()
    assert session.scalar(text("SELECT version_num FROM alembic_version")) == "20260902_0044"
