from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import LiveAggregatedBar, LiveMinuteBar, MarketDataFile
from app.services.live_market_reader import LiveMarketReader


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def test_live_reader_loads_1m_rows_and_keeps_warning_visible() -> None:
    with _session() as session:
        _add_live_1m_bar(session, datetime(2026, 7, 7, 9, 1), close=100, quality_status="passed")
        _add_live_1m_bar(session, datetime(2026, 7, 7, 9, 2), close=101, quality_status="warning", raw_payload={"quality_reasons": ["missing_trading_day"]})
        _add_live_1m_bar(session, datetime(2026, 7, 7, 9, 3), close=102, quality_status="failed", bar_status="rejected")
        session.commit()

        response = LiveMarketReader(session).get_bars(
            symbol="jm",
            contract="JM2609",
            period="1m",
            start=datetime(2026, 7, 7, 9, 0),
            end=datetime(2026, 7, 7, 9, 5),
            provider=None,
            source_mode=None,
            limit=10,
        )

    assert [bar["time"] for bar in response.bars] == ["2026-07-07T09:01:00", "2026-07-07T09:02:00"]
    assert response.bars[1]["quality_status"] == "warning"
    assert response.bars[1]["quality_reasons"] == ["missing_trading_day"]
    assert response.quality.status == "warning"
    assert response.quality.warning_count == 1
    assert response.quality.failed_count == 1
    assert response.quality.rejected_count == 1
    assert response.coverage is not None
    assert response.coverage.data_type == "live_db"
    assert response.coverage.row_count == 3


def test_live_reader_excludes_unconfirmed_non_rejected_bar_from_signal_view() -> None:
    with _session() as session:
        _add_live_1m_bar(session, datetime(2026, 7, 7, 9, 1), close=100, bar_status="forming")
        _add_live_1m_bar(session, datetime(2026, 7, 7, 9, 2), close=101, bar_status="confirmed")
        session.commit()

        response = LiveMarketReader(session).get_bars(
            symbol="jm", contract="JM2609", period="1m", start=None, end=None,
            provider="rqdata", source_mode=None, limit=10,
        )

    assert [bar["time"] for bar in response.bars] == ["2026-07-07T09:02:00"]
    assert response.coverage is not None and response.coverage.row_count == 2


def test_live_reader_loads_aggregated_periods_with_partial_bucket_metadata() -> None:
    with _session() as session:
        _add_live_aggregated_bar(session, datetime(2026, 7, 7, 9, 5), close=105, source_bar_count=5, expected_bar_count=5)
        _add_live_aggregated_bar(
            session,
            datetime(2026, 7, 7, 9, 33),
            close=110,
            source_bar_count=3,
            expected_bar_count=5,
            quality_status="warning",
            raw_payload={"quality_reasons": ["incomplete_source_bucket"]},
        )
        session.commit()

        response = LiveMarketReader(session).get_bars(
            symbol="jm",
            contract="JM2609",
            period="5m",
            start=datetime(2026, 7, 7, 9, 0),
            end=datetime(2026, 7, 7, 10, 0),
            provider="rqdata",
            source_mode="live_1m_sequential_bucket",
            limit=10,
        )

    assert [bar["time"] for bar in response.bars] == ["2026-07-07T09:05:00", "2026-07-07T09:33:00"]
    assert response.bars[1]["source_bar_count"] == 3
    assert response.bars[1]["expected_bar_count"] == 5
    assert response.bars[1]["quality_reasons"] == ["incomplete_source_bucket"]
    assert response.quality.status == "warning"
    assert response.quality.partial_count == 1


def test_live_reader_coverage_summarizes_1m_and_aggregated_rows_without_market_data_files() -> None:
    with _session() as session:
        _add_live_1m_bar(session, datetime(2026, 7, 7, 9, 1), close=100)
        _add_live_aggregated_bar(session, datetime(2026, 7, 7, 9, 5), close=105, source_bar_count=5, expected_bar_count=5)
        session.commit()

        coverage = LiveMarketReader(session).get_coverage()
        market_file_count = session.scalar(select(func.count()).select_from(MarketDataFile))

    assert market_file_count == 0
    assert [(item.symbol, item.contract, item.period, item.data_type) for item in coverage.items] == [
        ("jm", "JM2609", "1m", "live_db"),
        ("jm", "JM2609", "5m", "live_db"),
    ]
    assert coverage.default_selection is not None
    assert coverage.default_selection.symbol == "jm"


def _add_live_1m_bar(
    session: Session,
    bar_datetime: datetime,
    *,
    close: int,
    quality_status: str = "passed",
    bar_status: str = "confirmed",
    raw_payload: dict | None = None,
) -> None:
    price = Decimal(close)
    session.add(
        LiveMinuteBar(
            provider="rqdata",
            instrument_symbol="jm",
            contract_code="JM2609",
            exchange_code="DCE",
            period="1m",
            bar_datetime=bar_datetime,
            trading_day=date(2026, 7, 7),
            open=price - Decimal("1"),
            high=price + Decimal("2"),
            low=price - Decimal("2"),
            close=price,
            volume=Decimal("10"),
            open_interest=Decimal("100"),
            turnover=Decimal("1000"),
            bar_status=bar_status,
            quality_status=quality_status,
            source_mode="poll_get_price_1m",
            first_seen_at=bar_datetime + timedelta(seconds=2),
            last_seen_at=bar_datetime + timedelta(seconds=3),
            confirmed_at=bar_datetime + timedelta(seconds=3),
            revision=0,
            raw_payload=raw_payload or {},
        )
    )


def _add_live_aggregated_bar(
    session: Session,
    bar_datetime: datetime,
    *,
    close: int,
    source_bar_count: int,
    expected_bar_count: int,
    quality_status: str = "passed",
    bar_status: str = "confirmed",
    raw_payload: dict | None = None,
) -> None:
    price = Decimal(close)
    session.add(
        LiveAggregatedBar(
            provider="rqdata",
            instrument_symbol="jm",
            contract_code="JM2609",
            exchange_code="DCE",
            period="5m",
            source_period="1m",
            source_mode="live_1m_sequential_bucket",
            bar_datetime=bar_datetime,
            trading_day=date(2026, 7, 7),
            source_start_datetime=bar_datetime - timedelta(minutes=max(source_bar_count - 1, 0)),
            source_end_datetime=bar_datetime,
            source_bar_count=source_bar_count,
            expected_bar_count=expected_bar_count,
            open=price - Decimal("1"),
            high=price + Decimal("2"),
            low=price - Decimal("2"),
            close=price,
            volume=Decimal("50"),
            open_interest=Decimal("100"),
            turnover=Decimal("5000"),
            bar_status=bar_status,
            quality_status=quality_status,
            first_seen_at=bar_datetime + timedelta(seconds=2),
            last_seen_at=bar_datetime + timedelta(seconds=3),
            confirmed_at=bar_datetime + timedelta(seconds=3),
            revision=0,
            raw_payload=raw_payload or {},
        )
    )
