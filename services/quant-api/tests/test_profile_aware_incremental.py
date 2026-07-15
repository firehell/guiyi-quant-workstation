from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataProfile, MarketDataFile, ProfileActiveBinding, TradingCalendar, TradingSession
from app.services.rqdata_ingest.dominant_v2_parquet import _standard_path
from app.services.rqdata_ingest.profile_aware_incremental import (
    audit_profile_incremental_orphans,
    rollback_profile_aware_incremental_closure,
    run_profile_aware_incremental_closure,
)


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_profile(session: Session, *, periods: list[str] | None = None) -> None:
    session.add(
        DataProfile(
            profile_id="intraday_research_v1",
            label="Intraday Research V1",
            description="test",
            contract_roles=["dominant_main"],
            periods=periods or ["1d"],
            quality_policy="passed_only",
            provider="rqdata",
        )
    )


def _seed_sessions_and_calendar(session: Session, *, start: date = date(2026, 7, 6), days: int = 7) -> None:
    for offset in range(days):
        day = start + timedelta(days=offset)
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=day,
                is_trading_day=day.weekday() < 5,
                has_night_session=day.weekday() < 5,
                provider="fixture",
            )
        )
    for name, start_time, end_time in (
        ("night", time(21, 0), time(23, 0)),
        ("day_am", time(9, 0), time(11, 30)),
        ("day_pm", time(13, 30), time(15, 0)),
    ):
        session.add(
            TradingSession(
                exchange_code="DCE",
                instrument_symbol="jm",
                session_name=name,
                start_time=start_time,
                end_time=end_time,
                crosses_midnight=False,
                is_active=True,
                provider="fixture",
            )
        )


def _write_baseline(
    output_root: Path,
    *,
    symbol: str = "jm",
    period: str = "1d",
    start: date = date(2023, 1, 3),
    end: date = date(2026, 7, 10),
    stamps: list[datetime] | None = None,
) -> Path:
    path = _standard_path(
        output_root,
        symbol=symbol,
        exchange="DCE",
        contract=f"{symbol}.MAIN",
        period=period,
        start_date=start,
        end_date=end,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    values = stamps or [datetime(2026, 7, 9)]
    frame = pd.DataFrame(
        {
            "symbol": [symbol] * len(values),
            "contract": [f"{symbol}.MAIN"] * len(values),
            "exchange": ["DCE"] * len(values),
            "vt_symbol": [f"{symbol}.MAIN.DCE"] * len(values),
            "datetime": values,
            "trading_day": [item.date() for item in values],
            "interval": [period] * len(values),
            "period": [period] * len(values),
            "open": [100.0] * len(values),
            "high": [101.0] * len(values),
            "low": [99.0] * len(values),
            "close": [100.5] * len(values),
            "volume": [10.0] * len(values),
            "turnover": [1000.0] * len(values),
            "open_interest": [100.0] * len(values),
            "source": ["rqdata"] * len(values),
            "provider": ["rqdata"] * len(values),
            "source_symbol": ["JM2609"] * len(values),
            "data_role": ["primary"] * len(values),
            "quality_status": ["passed"] * len(values),
            "data_version": [f"rqdata_{symbol}_standard_{period}_{start:%Y%m%d}_{end:%Y%m%d}_v2"] * len(values),
            "created_at": [pd.Timestamp("2026-07-10")] * len(values),
        }
    )
    frame.to_parquet(path, index=False)
    return path


def _seed_old_active(session: Session, path: Path) -> None:
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="jm",
        contract_code="jm.MAIN",
        period="1d",
        start_time=datetime(2023, 1, 3, tzinfo=UTC),
        end_time=datetime(2026, 7, 9, tzinfo=UTC),
        file_path=str(path),
        row_count=1,
        checksum="a" * 64,
        data_version="old_v1",
        data_role="primary",
        quality_status="passed",
    )
    session.add(market_file)
    session.flush()
    session.add(
        ProfileActiveBinding(
            profile_id="intraday_research_v1",
            instrument_symbol="jm",
            contract_code="jm.MAIN",
            contract_role="dominant_main",
            period="1d",
            data_version="old_v1",
            market_data_file_id=market_file.id,
            binding_status="active",
            activated_at=datetime.now(UTC),
        )
    )


class FakeClient:
    def underlying_symbol(self, product: str) -> str:
        return product.upper()

    def dominant_contracts(self, product: str, start_date: date, end_date: date, rank: int) -> pd.DataFrame:
        dates = pd.date_range(start_date, end_date, freq="D")
        return pd.DataFrame({"date": dates, "dominant": ["JM2609"] * len(dates)})

    def contract_bars(self, contract: str, start_date: date, end_date: date, frequency: str) -> pd.DataFrame:
        stamps = pd.date_range(start_date, end_date, freq="D")
        return pd.DataFrame(
            {
                "datetime": stamps,
                "open": [100.0] * len(stamps),
                "high": [101.0] * len(stamps),
                "low": [99.0] * len(stamps),
                "close": [100.5] * len(stamps),
                "volume": [10.0] * len(stamps),
                "turnover": [1000.0] * len(stamps),
                "open_interest": [100.0] * len(stamps),
            }
        )


def test_profile_closure_apply_is_idempotent_and_keeps_one_active(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    output_root = tmp_path / "data"
    baseline = _write_baseline(output_root, end=date(2026, 7, 7), stamps=[datetime(2026, 7, 7)])
    with SessionLocal() as session:
        _seed_profile(session)
        _seed_sessions_and_calendar(session)
        _seed_old_active(session, baseline)
        session.commit()

        first = run_profile_aware_incremental_closure(
            session=session,
            client=FakeClient(),
            output_root=output_root,
            products=["jm"],
            periods=("1d",),
            target_end=date(2026, 7, 11),
            profile_ids=["intraday_research_v1"],
            dry_run=False,
            commit=True,
            batch_id="apply_001",
            output_dir=tmp_path / "reports",
        )
        second = run_profile_aware_incremental_closure(
            session=session,
            client=FakeClient(),
            output_root=output_root,
            products=["jm"],
            periods=("1d",),
            target_end=date(2026, 7, 11),
            profile_ids=["intraday_research_v1"],
            dry_run=False,
            commit=True,
            batch_id="apply_002",
            output_dir=tmp_path / "reports",
        )

        active_count = session.scalar(
            select(func.count()).select_from(ProfileActiveBinding).where(ProfileActiveBinding.binding_status == "active")
        )
        total_count = session.scalar(select(func.count()).select_from(ProfileActiveBinding))
        active = session.scalar(select(ProfileActiveBinding).where(ProfileActiveBinding.binding_status == "active"))

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert second["switch_target_count"] == 0
    assert active_count == 1
    assert total_count == 2
    assert active is not None
    assert active.data_version == "rqdata_jm_standard_1d_20230103_20260711_v2"


def test_profile_closure_rolls_back_db_when_later_period_is_blocked(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    output_root = tmp_path / "data"
    baseline = _write_baseline(output_root, end=date(2026, 7, 7), stamps=[datetime(2026, 7, 7)])
    with SessionLocal() as session:
        _seed_profile(session, periods=["1d", "1w"])
        _seed_sessions_and_calendar(session)
        _seed_old_active(session, baseline)
        session.commit()

        result = run_profile_aware_incremental_closure(
            session=session,
            client=FakeClient(),
            output_root=output_root,
            products=["jm"],
            periods=("1d", "1w"),
            target_end=date(2026, 7, 9),
            profile_ids=["intraday_research_v1"],
            dry_run=False,
            commit=True,
            batch_id="blocked_001",
            output_dir=tmp_path / "reports",
        )
        active = session.scalar(select(ProfileActiveBinding).where(ProfileActiveBinding.binding_status == "active"))
        new_file_count = session.scalar(
            select(func.count())
            .select_from(MarketDataFile)
            .where(MarketDataFile.data_version == "rqdata_jm_standard_1d_20230103_20260709_v2")
        )
        orphan_report = audit_profile_incremental_orphans(session=session, output_dir=tmp_path / "reports", batch_id="blocked_001")

    assert result["status"] == "failed"
    assert result["failure_count"] == 1
    assert result["failures"][0]["reason"] == "weekly_not_last_actual_trading_day"
    assert active is not None
    assert active.data_version == "old_v1"
    assert new_file_count == 0
    assert orphan_report["status"] == "orphans_found"
    assert orphan_report["orphans"][0]["recovery_action"] == "safe_retry_or_manual_archive"


def test_profile_closure_batch_rollback_restores_previous_active(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    output_root = tmp_path / "data"
    baseline = _write_baseline(output_root)
    with SessionLocal() as session:
        _seed_profile(session)
        _seed_sessions_and_calendar(session)
        _seed_old_active(session, baseline)
        session.commit()

        run_profile_aware_incremental_closure(
            session=session,
            client=FakeClient(),
            output_root=output_root,
            products=["jm"],
            periods=("1d",),
            target_end=date(2026, 7, 11),
            profile_ids=["intraday_research_v1"],
            dry_run=False,
            commit=True,
            batch_id="rollback_001",
            output_dir=tmp_path / "reports",
        )
        rollback = rollback_profile_aware_incremental_closure(
            session=session,
            output_dir=tmp_path / "reports",
            batch_id="rollback_001",
            dry_run=False,
            commit=True,
        )
        active = session.scalar(select(ProfileActiveBinding).where(ProfileActiveBinding.binding_status == "active"))

    assert rollback["status"] == "rolled_back"
    assert rollback["rolled_back"] == 1
    assert active is not None
    assert active.data_version == "old_v1"


def test_weekly_gate_accepts_short_holiday_week_last_actual_day(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_profile(session, periods=["1w"])
        _seed_sessions_and_calendar(session, start=date(2026, 10, 5), days=7)
        for row in session.scalars(select(TradingCalendar)):
            if row.trade_date in {date(2026, 10, 5), date(2026, 10, 6)}:
                row.is_trading_day = False
        session.commit()

        blocked = run_profile_aware_incremental_closure(
            session=session,
            client=None,
            output_root=tmp_path / "data",
            products=["jm"],
            periods=("1w",),
            target_end=date(2026, 10, 8),
            profile_ids=["intraday_research_v1"],
            dry_run=True,
            batch_id="weekly_blocked",
            output_dir=tmp_path / "reports",
        )
        passed = run_profile_aware_incremental_closure(
            session=session,
            client=None,
            output_root=tmp_path / "data",
            products=["jm"],
            periods=("1w",),
            target_end=date(2026, 10, 9),
            profile_ids=["intraday_research_v1"],
            dry_run=True,
            batch_id="weekly_passed",
            output_dir=tmp_path / "reports",
        )

    assert blocked["failure_count"] == 1
    assert blocked["failures"][0]["last_actual_trading_day"] == "2026-10-09"
    assert passed["failure_count"] == 0
    assert passed["period_results"][0]["status"] == "skipped_no_baseline"

