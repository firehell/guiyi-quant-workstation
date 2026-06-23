from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataDownloadTask, DataQualityReport, MarketDataFile
from app.services.trader_future_importer import TraderFutureCsvImporter


def test_trader_future_importer_writes_parquet_and_quality_report(tmp_path) -> None:
    raw_dir = tmp_path / "trader_Future_data" / "5分钟主力连续"
    raw_dir.mkdir(parents=True)
    csv_path = raw_dir / "螺纹-主连-5分钟.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Date,Time,Open,Close,High,Low,Volume,Amount",
                "2026-06-05,09:05:00,3000,3010,3020,2990,100,12345",
                "2026-06-05,09:10:00,3010,3005,3015,3000,120,22345",
            ]
        ),
        encoding="utf-8",
    )

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    parquet_root = tmp_path / "parquet"
    with SessionLocal() as session:
        importer = TraderFutureCsvImporter(session=session, raw_root=tmp_path / "trader_Future_data", parquet_root=parquet_root)
        summary = importer.import_files(instrument_names=["螺纹"], periods=["5m"])
        session.commit()

        assert summary.imported_files == 1
        assert summary.imported_rows == 2

        task = session.scalar(select(DataDownloadTask))
        assert task is not None
        assert task.status == "success"

        market_file = session.scalar(select(MarketDataFile))
        assert market_file is not None
        assert market_file.row_count == 2
        assert market_file.quality_status == "passed"
        assert (tmp_path / market_file.file_path).exists() or market_file.file_path.endswith(".parquet")

        quality = session.scalar(select(DataQualityReport))
        assert quality is not None
        assert quality.status == "passed"
        assert quality.abnormal_price_count == 0

        summary = importer.import_files(instrument_names=["螺纹"], periods=["5m"])
        session.commit()

        assert summary.imported_files == 1
        assert session.scalar(select(func.count()).select_from(DataDownloadTask)) == 2
        assert session.scalar(select(func.count()).select_from(MarketDataFile)) == 1
        assert session.scalar(select(func.count()).select_from(DataQualityReport)) == 1
