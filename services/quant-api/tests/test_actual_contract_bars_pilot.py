from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import (
    Contract,
    DataQualityReport,
    Exchange,
    FeeMarginRule,
    FuturesTradingParameter,
    Instrument,
    MainContractMap,
    MarketDataFile,
)
from app.services.rqdata_ingest.actual_contract_bars_pilot import (
    ActualContractBarsGateError,
    ActualContractBarsQualityError,
    build_actual_contract_bars_dry_run_payload,
    plan_actual_contract_bars_pilot,
    run_actual_contract_bars_pilot_write,
    run_actual_contract_bars_roll_write,
)


class FakeBarsClient:
    def __init__(self, *, bad_ohlc: bool = False, natural_gap: bool = False) -> None:
        self.bad_ohlc = bad_ohlc
        self.natural_gap = natural_gap
        self.calls: list[tuple[str, date, date, str]] = []

    def contract_bars(self, contract: str, start_date: date, end_date: date, frequency: str) -> pd.DataFrame:
        self.calls.append((contract, start_date, end_date, frequency))
        rows = []
        if frequency == "1d":
            stamps = list(pd.date_range(start_date, end_date, freq="B"))
            if not stamps:
                stamps = [pd.Timestamp(start_date)]
        elif self.natural_gap:
            stamps = [
                pd.Timestamp("2026-07-03 22:59:00"),
                pd.Timestamp("2026-07-03 23:00:00"),
                pd.Timestamp("2026-07-06 09:01:00"),
                pd.Timestamp("2026-07-06 09:02:00"),
            ]
        else:
            stamps = list(pd.date_range("2026-07-06 09:01:00", periods=6, freq="min"))
        for index, stamp in enumerate(stamps):
            rows.append(
                {
                    "datetime": stamp,
                    "open": 100.0 + index,
                    "high": 99.0 if self.bad_ohlc and index == 0 else 102.0 + index,
                    "low": 99.0 + index,
                    "close": 101.0 + index,
                    "volume": 10 + index,
                    "turnover": 1000 + index,
                    "open_interest": 1000 + index,
                }
            )
        return pd.DataFrame(rows)


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_reference_data(session: Session, *, contract: str = "JM2609", complete_params: bool = True) -> None:
    session.add(Exchange(code="DCE", name="DCE", country="CN", timezone="Asia/Shanghai", is_active=True))
    session.add(Instrument(symbol="jm", name="焦煤", exchange_code="DCE", is_active=True))
    session.add(
        Contract(
            contract_code=contract,
            instrument_symbol="jm",
            exchange_code="DCE",
            name="焦煤2609",
            contract_month="2609",
            contract_multiplier=60,
            provider="rqdata",
        )
    )
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=date(2026, 7, 7),
            rank=1,
            contract_code=contract,
            rule="volume_open_interest",
            provider="rqdata",
            data_version="test-mapping-v1",
        )
    )
    session.add(
        FuturesTradingParameter(
            contract_code=contract,
            instrument_symbol="jm",
            exchange_code="DCE",
            trade_date=date(2026, 7, 7),
            long_margin_ratio=Decimal("0.12"),
            short_margin_ratio=Decimal("0.13"),
            open_commission=Decimal("0.0001"),
            close_commission=Decimal("0.00011"),
            close_today_commission=Decimal("0.0002"),
            commission_type="by_money",
            price_tick=Decimal("0.5") if complete_params else None,
            contract_multiplier=60 if complete_params else None,
            provider="rqdata",
            data_version="test-params-v1",
        )
    )


def _seed_fee_margin_fallback(session: Session, contract: str = "JM2609") -> None:
    session.add(
        FeeMarginRule(
            provider="rqdata",
            exchange_code="DCE",
            instrument_symbol="jm",
            contract_code=contract,
            price_tick=Decimal("0.5"),
            volume_multiple=60,
            margin_rate=Decimal("0.14"),
            open_fee=Decimal("0.00012"),
            close_fee=Decimal("0.00013"),
            close_today_fee=Decimal("0.00021"),
            fee_type="by_money",
            effective_date=date(2026, 7, 1),
            source="test_fee_rule",
        )
    )


def test_dry_run_payload_does_not_touch_database_or_files(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        payload = build_actual_contract_bars_dry_run_payload(
            product="jm",
            trade_date=date(2026, 7, 7),
            start_date=date(2026, 7, 6),
            end_date=date(2026, 7, 7),
            periods=("1m", "5m", "15m", "30m", "60m"),
            output_root=tmp_path,
        )

        assert payload["mode"] == "dry-run"
        assert payload["would_construct_rqdata_client"] is False
        assert payload["would_write_parquet"] is False
        assert payload["would_write_database"] is False
        assert payload["would_register_primary"] is False
        assert session.scalar(select(func.count()).select_from(MarketDataFile)) == 0
        assert not (tmp_path / "parquet").exists()


def test_plan_resolves_actual_contract_and_paths_without_writing(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        session.commit()

        plan = plan_actual_contract_bars_pilot(
            session=session,
            output_root=tmp_path,
            product="jm",
            trade_date=date(2026, 7, 7),
            start_date=date(2026, 7, 6),
            end_date=date(2026, 7, 7),
            periods=("1m", "5m"),
        )

        assert plan["actual_contract"] == "JM2609"
        assert plan["continuous_contract"] == "jm.MAIN"
        assert plan["dominant_mapping_date"] == "2026-07-07"
        assert plan["parameter_gate"]["status"] == "passed"
        assert plan["periods"]["1m"]["canonical_path"].endswith("contract=JM2609/JM2609_1m_20260706_20260707.parquet")
        assert plan["periods"]["5m"]["data_version"] == "rq_acb_jm_JM2609_5m_20260706_20260707_v1"
        assert session.scalar(select(func.count()).select_from(MarketDataFile)) == 0
        assert not (tmp_path / "parquet").exists()


def test_missing_main_contract_mapping_blocks_plan(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        with pytest.raises(ActualContractBarsGateError, match="MainContractMap.rank=1 missing"):
            plan_actual_contract_bars_pilot(
                session=session,
                output_root=tmp_path,
                product="jm",
                trade_date=date(2026, 7, 7),
                start_date=date(2026, 7, 6),
                end_date=date(2026, 7, 7),
                periods=("1m",),
            )


def test_main_contract_code_cannot_be_used_as_actual_contract(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session, contract="jm.MAIN")
        session.commit()

        with pytest.raises(ActualContractBarsGateError, match="continuous contract cannot be actual_contract"):
            plan_actual_contract_bars_pilot(
                session=session,
                output_root=tmp_path,
                product="jm",
                trade_date=date(2026, 7, 7),
                start_date=date(2026, 7, 6),
                end_date=date(2026, 7, 7),
                periods=("1m",),
            )


def test_missing_required_trading_parameter_blocks_plan(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session, complete_params=False)
        session.commit()

        with pytest.raises(ActualContractBarsGateError, match="trading parameter gate failed"):
            plan_actual_contract_bars_pilot(
                session=session,
                output_root=tmp_path,
                product="jm",
                trade_date=date(2026, 7, 7),
                start_date=date(2026, 7, 6),
                end_date=date(2026, 7, 7),
                periods=("1m",),
            )


def test_fake_write_registers_only_passed_actual_contract_primary_files(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        _seed_fee_margin_fallback(session)
        client = FakeBarsClient()

        result = run_actual_contract_bars_pilot_write(
            session=session,
            client=client,
            output_root=tmp_path,
            product="jm",
            trade_date=date(2026, 7, 7),
            start_date=date(2026, 7, 6),
            end_date=date(2026, 7, 7),
            periods=("1m", "5m", "15m", "30m", "60m"),
        )
        session.commit()

        primary_files = session.scalars(
            select(MarketDataFile).where(MarketDataFile.data_type == "bars", MarketDataFile.data_role == "primary")
        ).all()
        reports = session.scalars(select(DataQualityReport).order_by(DataQualityReport.period)).all()

    assert client.calls == [("JM2609", date(2026, 7, 6), date(2026, 7, 7), "1m")]
    assert result["actual_contract"] == "JM2609"
    assert result["quality_gate"] == "passed"
    assert result["periods"]["1m"]["duckdb"]["row_count"] == 6
    assert result["periods"]["5m"]["quality_status"] == "passed"
    assert Path(result["manifest_path"]).exists()
    assert {item.contract_code for item in primary_files} == {"JM2609"}
    assert {item.period for item in primary_files} == {"1m", "5m", "15m", "30m", "60m"}
    assert {item.quality_status for item in primary_files} == {"passed"}
    assert {item.status for item in reports} == {"passed"}
    assert all("JM2609" in item.file_path for item in primary_files)
    assert all(item.checksum and len(item.checksum) == 64 for item in primary_files)


def test_natural_session_gap_is_recorded_without_blocking_actual_contract_primary_file(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        client = FakeBarsClient(natural_gap=True)

        result = run_actual_contract_bars_pilot_write(
            session=session,
            client=client,
            output_root=tmp_path,
            product="jm",
            trade_date=date(2026, 7, 7),
            start_date=date(2026, 7, 6),
            end_date=date(2026, 7, 7),
            periods=("1m",),
        )
        session.commit()

        market_file = session.scalar(
            select(MarketDataFile).where(MarketDataFile.data_type == "bars", MarketDataFile.data_role == "primary")
        )
        report = session.scalar(select(DataQualityReport).where(DataQualityReport.file_id == market_file.id))

    assert result["periods"]["1m"]["quality_status"] == "passed"
    assert result["periods"]["1m"]["missing_bars"] == 0
    assert market_file.quality_status == "passed"
    assert report.status == "passed"
    assert report.missing_bars == 0
    assert report.details["missing_bars_before_session_calendar"] > 0
    assert report.details["gap_samples"]
    assert "natural lunch, night, holiday and weekend gaps" in report.details["missing_bar_note"]


def test_quality_failed_fake_write_does_not_register_primary_file(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        client = FakeBarsClient(bad_ohlc=True)

        with pytest.raises(ActualContractBarsQualityError, match="quality_status must be passed"):
            run_actual_contract_bars_pilot_write(
                session=session,
                client=client,
                output_root=tmp_path,
                product="jm",
                trade_date=date(2026, 7, 7),
                start_date=date(2026, 7, 6),
                end_date=date(2026, 7, 7),
                periods=("1m",),
            )

        assert session.scalar(
            select(func.count()).select_from(MarketDataFile).where(MarketDataFile.data_role == "primary")
        ) == 0


def test_plan_rejects_mixing_1d_with_minute_bundle(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        session.commit()

        with pytest.raises(ActualContractBarsGateError, match="mixing rqdata-only periods"):
            plan_actual_contract_bars_pilot(
                session=session,
                output_root=tmp_path,
                product="jm",
                trade_date=date(2026, 7, 7),
                start_date=date(2026, 7, 6),
                end_date=date(2026, 7, 7),
                periods=("1m", "5m", "1d"),
            )


def test_plan_allows_1d_only_without_1m(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        session.commit()

        plan = plan_actual_contract_bars_pilot(
            session=session,
            output_root=tmp_path,
            product="jm",
            trade_date=date(2026, 7, 7),
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 7),
            periods=("1d",),
        )

        assert plan["source_period"] == "1d"
        assert plan["periods"]["1d"]["raw_path"].endswith("frequency=1d/JM2609_1d_raw_20260701_20260707.parquet")
        assert plan["periods"]["1d"]["canonical_path"].endswith("contract=JM2609/JM2609_1d_20260701_20260707.parquet")


def test_1d_only_write_downloads_direct_daily_bars(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        client = FakeBarsClient()

        result = run_actual_contract_bars_pilot_write(
            session=session,
            client=client,
            output_root=tmp_path,
            product="jm",
            trade_date=date(2026, 7, 7),
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 7),
            periods=("1d",),
        )
        session.commit()

        primary_files = session.scalars(
            select(MarketDataFile).where(MarketDataFile.data_type == "bars", MarketDataFile.data_role == "primary")
        ).all()

    assert client.calls == [("JM2609", date(2026, 7, 1), date(2026, 7, 7), "1d")]
    assert result["source_period"] == "1d"
    assert result["periods"]["1d"]["quality_status"] == "passed"
    assert {item.period for item in primary_files} == {"1d"}


def test_plan_allows_1w_only_without_1m(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        session.commit()

        plan = plan_actual_contract_bars_pilot(
            session=session,
            output_root=tmp_path,
            product="jm",
            trade_date=date(2026, 7, 7),
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 7),
            periods=("1w",),
        )

        assert plan["source_period"] == "1w"
        assert plan["periods"]["1w"]["raw_path"].endswith("frequency=1w/JM2609_1w_raw_20260701_20260707.parquet")
        assert plan["periods"]["1w"]["canonical_path"].endswith("contract=JM2609/JM2609_1w_20260701_20260707.parquet")


def test_1w_only_write_downloads_direct_weekly_bars(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        client = FakeBarsClient()

        result = run_actual_contract_bars_pilot_write(
            session=session,
            client=client,
            output_root=tmp_path,
            product="jm",
            trade_date=date(2026, 7, 7),
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 7),
            periods=("1w",),
        )
        session.commit()

        primary_files = session.scalars(
            select(MarketDataFile).where(MarketDataFile.data_type == "bars", MarketDataFile.data_role == "primary")
        ).all()

    assert client.calls == [("JM2609", date(2026, 7, 1), date(2026, 7, 7), "1w")]
    assert result["source_period"] == "1w"
    assert result["periods"]["1w"]["quality_status"] == "passed"
    assert {item.period for item in primary_files} == {"1w"}


def test_roll_write_skips_existing_1d_canonical(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_reference_data(session)
        session.add(
            MainContractMap(
                instrument_symbol="jm",
                trade_date=date(2026, 7, 1),
                rank=1,
                contract_code="JM2609",
                rule="volume_open_interest",
                provider="rqdata",
                data_version="test-mapping-v0",
            )
        )
        session.commit()

        existing_path = (
            tmp_path
            / "parquet"
            / "canonical"
            / "bars"
            / "provider=rqdata"
            / "period=1d"
            / "exchange=DCE"
            / "symbol=jm"
            / "contract=JM2609"
            / "JM2609_1d_20260701_20260707.parquet"
        )
        existing_path.parent.mkdir(parents=True, exist_ok=True)
        existing_path.write_bytes(b"existing")

        client = FakeBarsClient()
        result = run_actual_contract_bars_roll_write(
            session=session,
            client=client,
            output_root=tmp_path,
            product="jm",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 7),
            periods=("1d",),
            jm_only=False,
            skip_existing=True,
        )

    assert client.calls == []
    assert result["skipped_count"] == 1
    assert result["success_count"] == 0
    assert result["segments"][0]["status"] == "skipped_existing"
    assert result["segments"][0]["period"] == "1d"
