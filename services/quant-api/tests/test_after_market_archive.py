from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataDownloadTask, MainContractMap
from app.services.after_market_archive import AfterMarketArchiveService
from app.services.rqdata_ingest.actual_contract_bars_pilot import _download_period, _periods


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


class ClosedClock:
    def trading_day_closed(self, trading_day, *, product: str, exchange: str, now: datetime):
        return True

    def expected_minute_count(self, trading_day, *, product: str, exchange: str):
        return 5


def test_disabled_archive_has_no_external_side_effects(tmp_path: Path) -> None:
    with _session() as session:
        result = AfterMarketArchiveService(
            session=session,
            client=object(),
            output_root=tmp_path,
            trading_clock=object(),
        ).archive_once(trading_day=date(2026, 7, 7), enabled=False, confirmed=False)

        assert session.scalar(select(func.count()).select_from(DataDownloadTask)) == 0

    assert result["status"] == "blocked"
    assert result["would_call_rqdata"] is False
    assert result["would_register_primary"] is False


def test_archive_orchestration_is_idempotent_and_live_is_reference_only(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict] = []

    def fake_archive(**kwargs):
        calls.append(kwargs)
        return {
            "quality_gate": "passed",
            "manifest_path": str(tmp_path / "manifest.csv"),
            "periods": {period: {"quality_status": "passed"} for period in kwargs["periods"]},
        }

    monkeypatch.setattr("app.services.after_market_archive.run_actual_contract_bars_pilot_write", fake_archive)
    with _session() as session:
        _add_mapping(session)
        service = AfterMarketArchiveService(
            session=session,
            client=object(),
            output_root=tmp_path,
            now=datetime(2026, 7, 7, 16, 0),
            trading_clock=ClosedClock(),
        )
        first = service.archive_once(trading_day=date(2026, 7, 7), enabled=True, confirmed=True)
        session.commit()
        second = service.archive_once(trading_day=date(2026, 7, 7), enabled=True, confirmed=True)

        tasks = list(session.scalars(select(DataDownloadTask)))

    assert first["status"] == "success"
    assert second["status"] == "already_archived"
    assert len(calls) == 1
    assert calls[0]["local_daily"] is True
    assert calls[0]["expected_source_rows"] == 5
    assert len(tasks) == 1
    assert tasks[0].task_no == "archive:jm:JM2609:2026-07-07"
    assert tasks[0].result["live_reference_only"] is True
    assert tasks[0].result["historical_active_source"] == "rqdata_after_market_direct"


def test_local_daily_bundle_uses_1m_as_source() -> None:
    periods = _periods(("1m", "5m", "15m", "30m", "60m", "1d"), local_daily=True)

    assert periods[-1] == "1d"
    assert _download_period(periods, local_daily=True) == "1m"


def test_archive_failure_retains_task_error_evidence(tmp_path: Path, monkeypatch) -> None:
    def fail_archive(**kwargs):
        raise RuntimeError("quality row count mismatch")

    monkeypatch.setattr("app.services.after_market_archive.run_actual_contract_bars_pilot_write", fail_archive)
    with _session() as session:
        _add_mapping(session)
        service = AfterMarketArchiveService(
            session=session,
            client=object(),
            output_root=tmp_path,
            now=datetime(2026, 7, 7, 16, 0),
            trading_clock=ClosedClock(),
        )
        result = service.archive_once(trading_day=date(2026, 7, 7), enabled=True, confirmed=True)
        session.commit()
        task = session.scalar(select(DataDownloadTask))

    assert result["status"] == "failed"
    assert task is not None
    assert task.status == "failed"
    assert task.result["quality_gate"] == "failed"
    assert task.result["error_type"] == "RuntimeError"
    assert task.result["live_reference_only"] is True


def _add_mapping(session) -> None:
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=date(2026, 7, 7),
            rank=1,
            contract_code="JM2609",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="archive_test",
            raw_payload={},
        )
    )
    session.flush()
