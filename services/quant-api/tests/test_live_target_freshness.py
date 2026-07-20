from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.data_center import FuturesTradingParameter, MainContractMap, MarketDataFile
from app.services.live_target_contracts import LiveTargetContractResolver


TARGET_DATE = date(2026, 7, 17)
ACTUAL_CONTRACT = "JM2609"


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_reference(session: Session, *, metadata_date: date) -> None:
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=metadata_date,
            rank=1,
            contract_code=ACTUAL_CONTRACT,
            rule="volume_open_interest",
            provider="rqdata",
            data_version=f"mapping-{metadata_date.isoformat()}",
        )
    )
    session.add(
        FuturesTradingParameter(
            contract_code=ACTUAL_CONTRACT,
            instrument_symbol="jm",
            exchange_code="DCE",
            trade_date=metadata_date,
            long_margin_ratio=Decimal("0.12"),
            short_margin_ratio=Decimal("0.12"),
            open_commission=Decimal("1"),
            close_commission=Decimal("1"),
            close_today_commission=Decimal("1"),
            price_tick=Decimal("0.5"),
            contract_multiplier=60,
            provider="rqdata",
            data_version=f"params-{metadata_date.isoformat()}",
        )
    )


def _seed_coverage(session: Session, *, end_date: date, quality_status: str = "passed") -> None:
    for period in ("1m", "5m", "15m"):
        session.add(
            MarketDataFile(
                provider="rqdata",
                data_type="bars",
                instrument_symbol="jm",
                contract_code=ACTUAL_CONTRACT,
                period=period,
                start_time=datetime(2026, 7, 1, tzinfo=timezone.utc),
                end_time=datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc),
                file_path=f"/not-exposed/{period}.parquet",
                row_count=100,
                data_version=f"actual-{period}-{end_date.isoformat()}",
                data_role="primary",
                quality_status=quality_status,
            )
        )


def test_required_date_blocks_stale_rank1_mapping() -> None:
    with _session() as session:
        _seed_reference(session, metadata_date=date(2026, 7, 16))
        _seed_coverage(session, end_date=TARGET_DATE)
        session.commit()

        target = LiveTargetContractResolver(session).resolve_product("jm", required_date=TARGET_DATE)

    assert target["readiness_status"] == "blocked"
    assert "main_contract_map_rank1_stale:2026-07-16<2026-07-17" in target["blocked_reasons"]


def test_required_date_does_not_substitute_a_future_rank1_mapping() -> None:
    with _session() as session:
        _seed_reference(session, metadata_date=date(2026, 7, 20))
        _seed_coverage(session, end_date=TARGET_DATE)
        session.commit()

        target = LiveTargetContractResolver(session).resolve_product("jm", required_date=TARGET_DATE)

    assert target["readiness_status"] == "blocked"
    assert "main_contract_map_rank1_missing:2026-07-17" in target["blocked_reasons"]


def test_required_date_blocks_stale_historical_actual_coverage() -> None:
    with _session() as session:
        _seed_reference(session, metadata_date=TARGET_DATE)
        _seed_coverage(session, end_date=date(2026, 7, 16))
        session.commit()

        target = LiveTargetContractResolver(session).resolve_product("jm", required_date=TARGET_DATE)

    assert target["readiness_status"] == "blocked"
    assert "historical_actual_contract_coverage_stale:1m,5m,15m" in target["blocked_reasons"]


def test_required_date_blocks_stale_trading_parameters() -> None:
    with _session() as session:
        session.add(
            MainContractMap(
                instrument_symbol="jm",
                trade_date=TARGET_DATE,
                rank=1,
                contract_code=ACTUAL_CONTRACT,
                rule="volume_open_interest",
                provider="rqdata",
                data_version="mapping-current",
            )
        )
        session.add(
            FuturesTradingParameter(
                contract_code=ACTUAL_CONTRACT,
                instrument_symbol="jm",
                exchange_code="DCE",
                trade_date=date(2026, 7, 16),
                long_margin_ratio=Decimal("0.12"),
                short_margin_ratio=Decimal("0.12"),
                open_commission=Decimal("1"),
                close_commission=Decimal("1"),
                close_today_commission=Decimal("1"),
                price_tick=Decimal("0.5"),
                contract_multiplier=60,
                provider="rqdata",
                data_version="params-stale",
            )
        )
        _seed_coverage(session, end_date=TARGET_DATE)
        session.commit()

        target = LiveTargetContractResolver(session).resolve_product("jm", required_date=TARGET_DATE)

    assert target["readiness_status"] == "blocked"
    assert "trading_parameter_gate_failed" in target["blocked_reasons"]
    assert target["trading_parameter_status"]["metadata_fresh"] is False
    assert "fresh_trading_parameters" in target["trading_parameter_status"]["missing_fields"]


def test_required_date_is_ready_only_when_metadata_and_coverage_are_fresh() -> None:
    with _session() as session:
        _seed_reference(session, metadata_date=TARGET_DATE)
        _seed_coverage(session, end_date=TARGET_DATE)
        session.commit()

        target = LiveTargetContractResolver(session).resolve_product("jm", required_date=TARGET_DATE)

    assert target["readiness_status"] == "ready"
    assert target["required_date"] == "2026-07-17"
    assert target["dominant_mapping_date"] == "2026-07-17"
    assert target["trading_parameter_status"]["metadata_fresh"] is True
    assert all(target["historical_coverage"][period]["fresh_for_required_date"] for period in ("1m", "5m", "15m"))


def test_list_targets_propagates_required_date() -> None:
    with _session() as session:
        _seed_reference(session, metadata_date=TARGET_DATE)
        _seed_coverage(session, end_date=TARGET_DATE)
        session.commit()

        payload = LiveTargetContractResolver(session).list_targets(required_date=TARGET_DATE)

    assert payload["required_date"] == "2026-07-17"
    assert payload["readiness_status"] == "ready"
    assert payload["items"][0]["required_date"] == "2026-07-17"
