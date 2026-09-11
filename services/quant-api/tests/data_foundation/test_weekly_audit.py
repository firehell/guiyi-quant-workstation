from datetime import datetime, timedelta
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.market_data.historical_data_manager import AuditProgressEvent, MaintenanceResult
from tests.data_foundation.test_daily_maintenance import daily_manager  # noqa: F401
from tests.data_foundation.test_historical_data_manager import session as seeded_session


NOW = datetime.fromisoformat("2026-09-12T09:00:00+08:00")
IDENTITY = {"runtime_root": "/fixture/runtime", "runtime_commit": "a" * 40}


@pytest.fixture
def session():
    with Session(create_engine("sqlite://")) as value:
        yield value


def test_weekly_acquires_before_readonly_and_retains_crash_visibility(tmp_path, session):
    from app.market_data.weekly_audit import run_weekly_audit
    events = []
    path = tmp_path / "weekly-audit-status.json"
    def acquire():
        assert not session.in_transaction()
        events.append("lease")
        return SimpleNamespace(release=lambda: events.append("released"))
    def audit(request, *, observer):
        assert session.scalar(text("PRAGMA query_only")) == 1
        assert request.products == ("au",) and request.through is None
        payload = json.loads(path.read_text())
        assert payload["status"] == "running"
        observer(AuditProgressEvent("started", 0, 1, "au", None))
        raise KeyboardInterrupt()
    manager = SimpleNamespace(catalog=SimpleNamespace(session=session, acquire_maintenance_lock=acquire), audit=audit)
    with pytest.raises(KeyboardInterrupt):
        run_weekly_audit(manager, status_path=path, products=("au",), identity=IDENTITY, now=lambda: NOW)
    assert events == ["lease", "released"]
    assert not session.in_transaction()
    assert json.loads(path.read_text())["status"] == "running"


def test_busy_weekly_does_not_open_transaction_or_audit(tmp_path, session):
    from app.market_data.weekly_audit import run_weekly_audit
    manager = SimpleNamespace(catalog=SimpleNamespace(session=session, acquire_maintenance_lock=lambda: None))
    payload = run_weekly_audit(manager, status_path=tmp_path / "status.json", products=("au",),
                               identity=IDENTITY, now=lambda: NOW)
    assert payload["status"] == "skipped_busy"
    assert not session.in_transaction()
    assert payload["provider_requests"] == 0 and payload["data_writes"] == 0


def test_weekly_result_and_health_identity_age_and_progress(tmp_path, session):
    from app.market_data.weekly_audit import run_weekly_audit, weekly_audit_health
    path = tmp_path / "status.json"
    assert weekly_audit_health(path, identity=IDENTITY, products=("au",), now=NOW)["status"] == "not_run"
    def audit(request, *, observer):
        assert session.scalar(text("PRAGMA query_only")) == 1
        observer(AuditProgressEvent("completed", 1, 1, "au", 0))
        return MaintenanceResult("audit", "passed", NOW.date(), 0, 0, 0, 0, 0)
    manager = SimpleNamespace(catalog=SimpleNamespace(session=session,
        acquire_maintenance_lock=lambda: SimpleNamespace(release=lambda: None)), audit=audit)
    result = run_weekly_audit(manager, status_path=path, products=("au",), identity=IDENTITY, now=lambda: NOW)
    assert result["status"] == "passed" and result["completed"] == 1
    assert result["findings"] == [] and result["readonly"] is True
    assert weekly_audit_health(path, identity=IDENTITY, products=("au",), now=NOW)["status"] == "passed"
    assert weekly_audit_health(path, identity={**IDENTITY, "runtime_commit": "b" * 40}, products=("au",), now=NOW)["status"] == "invalid"
    assert weekly_audit_health(path, identity=IDENTITY, products=("au",), now=NOW + timedelta(days=9))["status"] == "stale"


def test_real_audit_composition_never_initializes_provider(tmp_path, session, monkeypatch):
    from app.db.base import Base
    from app.market_data import composition, rqdata_adapter
    from app.market_data.weekly_audit import run_weekly_audit
    from app.models import Exchange, Instrument
    Base.metadata.create_all(session.get_bind())
    session.add(Exchange(code="SHFE", name="SHFE"))
    session.add(Instrument(symbol="au", name="gold", exchange_code="SHFE", is_active=True))
    session.commit()
    monkeypatch.setattr(composition, "canonical_root", lambda: tmp_path / "canonical")
    monkeypatch.setattr(rqdata_adapter, "RQDataClient", lambda: pytest.fail("provider must stay uninitialized"))
    manager = composition.build_historical_data_manager(session)
    result = run_weekly_audit(manager, status_path=tmp_path / "status.json", products=("au",),
                               identity=IDENTITY, now=lambda: NOW)
    assert result["status"] == "findings"
    assert result["finding_count"] > 0
    assert result["provider_requests"] == 0 and result["data_writes"] == 0
    assert not (tmp_path / "canonical").exists()


def test_weekly_lock_error_replaces_previous_passed_with_latest_failed(tmp_path, session):
    from app.market_data.weekly_audit import run_weekly_audit, weekly_audit_health
    path = tmp_path / "status.json"
    manager = SimpleNamespace(catalog=SimpleNamespace(session=session,
        acquire_maintenance_lock=lambda: SimpleNamespace(release=lambda: None)),
        audit=lambda *args, **kwargs: MaintenanceResult("audit", "passed", NOW.date(), 0, 0, 0, 0, 0))
    run_weekly_audit(manager, status_path=path, products=("au",), identity=IDENTITY, now=lambda: NOW)
    assert weekly_audit_health(path, identity=IDENTITY, products=("au",), now=NOW)["status"] == "passed"
    def acquire():
        assert not session.in_transaction()
        assert json.loads(path.read_text())["status"] == "running"
        raise OSError("private database detail")
    manager.catalog.acquire_maintenance_lock = acquire
    manager.audit = lambda *args, **kwargs: pytest.fail("lock failure must not audit")
    result = run_weekly_audit(manager, status_path=path, products=("au",), identity=IDENTITY,
                              now=lambda: NOW + timedelta(minutes=1))
    assert result["status"] == "failed" and result["error_code"] == "WEEKLY_AUDIT_FAILED"
    assert result["completed"] == 0 and result["through"] is None
    assert weekly_audit_health(path, identity=IDENTITY, products=("au",), now=NOW + timedelta(minutes=1))["status"] == "failed"
    assert "private" not in path.read_text()
    assert not session.in_transaction()


def test_public_audit_operational_selection_and_readonly(tmp_path, session):
    import io
    from contextlib import nullcontext
    from app.guiyi_cli.main import main
    from app.market_data.operational_universe import load_operational_products
    from app.market_data.catalog import MarketCatalog
    output = io.StringIO()
    def audit(request, **kwargs):
        assert request.products == load_operational_products()
        assert session.scalar(text("PRAGMA query_only")) == 1
        return MaintenanceResult("audit", "passed", NOW.date(), 0, 0, 0, 0, 0)
    manager = SimpleNamespace(catalog=MarketCatalog(session, tmp_path), audit=audit)
    result = main(["data", "audit", "--universe", "operational"],
                  session_factory=lambda: nullcontext(session), manager_factory=lambda _: manager,
                  stdout=output, stderr=io.StringIO())
    assert result == 0
    assert json.loads(output.getvalue())["status"] == "passed"


def _assert_full_audit_preserves_facts(manager, path):
    import hashlib
    from sqlalchemy import delete
    from app.market_data.domain import DatasetKey
    from app.market_data.weekly_audit import run_weekly_audit
    from app.models import MainContractMap
    db = manager.catalog.session
    key = DatasetKey("continuous", "jm", "MAIN", "1m")
    old = manager.catalog.all_partitions(key)[0]
    old.file_path.write_bytes(b"old January corruption")
    db.execute(delete(MainContractMap).where(MainContractMap.trade_date == datetime(2025, 1, 10).date()))
    db.commit()
    def fingerprint():
        from app.models import (Exchange, Instrument, Contract, TradingCalendar, TradingSession,
                                MainContractMap, MarketDataset, MarketPartition)
        rows = {table.name: tuple(sorted(repr(tuple(row)) for row in db.execute(table.select()).all()))
                for table in (model.__table__ for model in (Exchange, Instrument, Contract, TradingCalendar,
                              TradingSession, MainContractMap, MarketDataset, MarketPartition))}
        files = {str(file.relative_to(manager.store.root)): hashlib.sha256(file.read_bytes()).hexdigest()
                 for file in manager.store.root.rglob("*") if file.is_file()}
        db.rollback()
        return rows, files
    before = fingerprint()
    manager.provider.calls.clear()
    manager.metadata.calls.clear()
    result = run_weekly_audit(manager, status_path=path, products=("jm",), identity=IDENTITY,
                              now=lambda: NOW)
    assert result["status"] == "findings"
    assert any(item["code"] == "MAIN_CONTRACT_MAP_MISSING" for item in result["findings"])
    assert any(item["dataset"] == ["continuous", "jm", "MAIN", "1m"]
               and item["month"] == 1 and item["category"] == "physical" for item in result["findings"])
    assert not manager.provider.calls and not manager.metadata.calls
    assert fingerprint() == before


def test_weekly_full_history_detects_old_corruption_and_map_hole_without_writes(tmp_path):
    # Reuse the authoritative Calendar/Session/physical-history fixture in a fresh session.
    generator = seeded_session.__wrapped__()
    db = next(generator)
    try:
        manager = daily_manager.__wrapped__(db, tmp_path)
        _assert_full_audit_preserves_facts(manager, tmp_path / "weekly.json")
    finally:
        generator.close()


@pytest.mark.parametrize("gap", ["calendar", "session"])
def test_weekly_detects_interior_metadata_hole_without_rank1(tmp_path, gap):
    from sqlalchemy import delete
    from app.models import MainContractMap, TradingCalendar, TradingSession
    from app.market_data.weekly_audit import run_weekly_audit
    generator = seeded_session.__wrapped__()
    db = next(generator)
    try:
        manager = daily_manager.__wrapped__(db, tmp_path)
        day = datetime(2025, 1, 10).date()
        db.execute(delete(MainContractMap).where(MainContractMap.trade_date == day))
        if gap == "calendar":
            db.execute(delete(TradingCalendar).where(TradingCalendar.trade_date == day))
        else:
            db.execute(delete(TradingSession).where(TradingSession.effective_from == day))
        db.commit()
        result = run_weekly_audit(manager, status_path=tmp_path / "weekly.json", products=("jm",),
                                  identity=IDENTITY, now=lambda: NOW)
        assert result["status"] == "findings"
        assert any(item["code"] == "HISTORICAL_SESSION_FACT_MISSING"
                   for item in result["findings"])
    finally:
        generator.close()
