from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataQualityReport
from app.services.market_data_reader import MarketDataReader
from app.services.trader_future_importer import TraderFutureCsvImporter


def _write_csv(raw_root, period_dir: str, filename: str, rows: list[str]) -> None:
    directory = raw_root / period_dir
    directory.mkdir(parents=True)
    (directory / filename).write_text(
        "\n".join(["Date,Time,Open,Close,High,Low,Volume,Amount"] + rows),
        encoding="utf-8",
    )


def test_market_data_reader_loads_bars_by_symbol_contract_period_and_date_range(tmp_path) -> None:
    raw_root = tmp_path / "trader_Future_data"
    _write_csv(
        raw_root,
        "5分钟主力连续",
        "螺纹-主连-5分钟.csv",
        [
            "2021-01-04,09:05:00,4000,4010,4020,3990,100,1000",
            "2021-01-04,09:10:00,4010,4020,4030,4000,110,1100",
            "2021-01-04,09:15:00,4020,4030,4040,4010,120,1200",
        ],
    )
    _write_csv(
        raw_root,
        "日线主力连续",
        "螺纹-主连-日线.csv",
        [
            "2021-01-04,00:00:00,4000,4010,4020,3990,1000,10000",
            "2021-01-05,00:00:00,4010,4020,4030,4000,1100,11000",
        ],
    )

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        importer = TraderFutureCsvImporter(session=session, raw_root=raw_root, parquet_root=tmp_path / "parquet")
        importer.import_files(instrument_names=["螺纹"], periods=["5m", "1d"])
        session.commit()

        reader = MarketDataReader(session)
        five_minute = reader.load_bars(
            symbol="rb",
            contract="rb.MAIN",
            period="5m",
            start=datetime(2021, 1, 4, 9, 10, tzinfo=UTC),
            end=datetime(2021, 1, 4, 9, 15, tzinfo=UTC),
        )
        daily = reader.load_bars(
            symbol="rb",
            contract="rb.MAIN",
            period="1d",
            start=datetime(2021, 1, 4, tzinfo=UTC),
            end=datetime(2021, 1, 5, tzinfo=UTC),
        )

        assert [row["datetime"].strftime("%H:%M:%S") for row in five_minute] == ["09:10:00", "09:15:00"]
        assert all(row["symbol"] == "rb" and row["contract"] == "rb.MAIN" for row in five_minute)
        assert len(daily) == 2
        assert daily[0]["period"] == "1d"


def test_market_data_reader_quality_status_aggregates_reports(tmp_path) -> None:
    raw_root = tmp_path / "trader_Future_data"
    _write_csv(
        raw_root,
        "5分钟主力连续",
        "螺纹-主连-5分钟.csv",
        [
            "2021-01-04,09:05:00,4000,4010,4020,3990,100,1000",
            "2021-01-04,09:20:00,4010,4020,4030,4000,110,1100",
        ],
    )

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        importer = TraderFutureCsvImporter(session=session, raw_root=raw_root, parquet_root=tmp_path / "parquet")
        importer.import_files(instrument_names=["螺纹"], periods=["5m"])
        session.commit()

        report = session.scalar(select(DataQualityReport))
        assert report is not None
        assert report.status == "warning"

        status = MarketDataReader(session).get_quality_status(
            symbol="rb",
            contract="rb.MAIN",
            period="5m",
            start=datetime(2021, 1, 4, 9, 5, tzinfo=UTC),
            end=datetime(2021, 1, 4, 9, 20, tzinfo=UTC),
        )
        assert status["status"] == "warning"
        assert status["missing_bars"] == 2
