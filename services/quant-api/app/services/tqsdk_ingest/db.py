from datetime import date
from pathlib import Path
from uuid import uuid4

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.data_center import (
    Contract,
    DataDownloadTask,
    DataQualityReport,
    DataSource,
    Exchange,
    Instrument,
    MarketDataFile,
    utc_now,
)
from app.services.tqsdk_ingest.parquet import sha256_file, write_parquet_atomic
from app.services.tqsdk_ingest.products import ProductSpec
from app.services.tqsdk_ingest.quality import QualityResult, evaluate_1m_quality
from app.services.tqsdk_ingest.transformer import (
    CANONICAL_DATA_TYPE,
    PERIOD,
    PROVIDER,
    RAW_DATA_TYPE,
    as_datetime,
)


class TqSdkIngestRecorder:
    def __init__(self, session: Session, project_root: Path) -> None:
        self.session = session
        self.project_root = project_root

    def start_task(self, *, spec: ProductSpec, chunk_start: date, chunk_end: date) -> DataDownloadTask:
        self._ensure_reference_rows(spec)
        task = DataDownloadTask(
            task_no=f"tqsdk-main-1m-{uuid4().hex[:12]}",
            provider=PROVIDER,
            data_type=CANONICAL_DATA_TYPE,
            instrument_symbol=spec.product,
            contract_code=spec.contract_code,
            period=PERIOD,
            start_time=as_datetime(chunk_start),
            end_time=as_datetime(chunk_end, end_of_day=True),
            status="running",
            progress=0,
            result={"download_symbol": spec.download_symbol},
            started_at=utc_now(),
        )
        self.session.add(task)
        self.session.flush()
        return task

    def record_chunk(
        self,
        *,
        task: DataDownloadTask,
        spec: ProductSpec,
        year: int,
        month: int,
        chunk_start: date,
        chunk_end: date,
        raw_path: Path,
        raw_frame: pd.DataFrame,
        canonical_path: Path,
        canonical_frame: pd.DataFrame,
        source_csv: Path,
    ) -> QualityResult:
        written_raw = write_parquet_atomic(raw_frame, raw_path)
        written_canonical = write_parquet_atomic(canonical_frame, canonical_path)
        quality = evaluate_1m_quality(canonical_frame)
        self._record_file(
            task=task,
            spec=spec,
            path=written_raw,
            data_type=RAW_DATA_TYPE,
            row_count=len(raw_frame),
            data_version=f"tqsdk_main_1m_{spec.product}_{year:04d}_{month:02d}_raw_v1",
            quality_status=quality.status,
            start_time=as_datetime(chunk_start),
            end_time=as_datetime(chunk_end, end_of_day=True),
        )
        canonical_file = self._record_file(
            task=task,
            spec=spec,
            path=written_canonical,
            data_type=CANONICAL_DATA_TYPE,
            row_count=len(canonical_frame),
            data_version=f"tqsdk_main_1m_{spec.product}_{year:04d}_{month:02d}_canonical_v1",
            quality_status=quality.status,
            start_time=canonical_frame["datetime"].min().to_pydatetime(),
            end_time=canonical_frame["datetime"].max().to_pydatetime(),
        )
        self._replace_quality_report(
            task=task,
            market_file=canonical_file,
            spec=spec,
            quality=quality,
            canonical_frame=canonical_frame,
            source_csv=source_csv,
            chunk_start=chunk_start,
            chunk_end=chunk_end,
        )
        task.result = {
            "download_symbol": spec.download_symbol,
            "raw_file": str(written_raw),
            "canonical_file": str(written_canonical),
            "row_count": len(canonical_frame),
            "quality_status": quality.status,
        }
        return quality

    def finish_task(self, task: DataDownloadTask, *, status: str, row_count: int = 0, error: str | None = None) -> None:
        task.status = status
        task.progress = 100 if status == "success" else 0
        task.error_message = error
        task.finished_at = utc_now()
        task.result = {**(task.result or {}), "row_count": row_count}

    def _record_file(
        self,
        *,
        task: DataDownloadTask,
        spec: ProductSpec,
        path: Path,
        data_type: str,
        row_count: int,
        data_version: str,
        quality_status: str,
        start_time,
        end_time,
    ) -> MarketDataFile:
        market_file = self.session.scalar(
            select(MarketDataFile).where(
                MarketDataFile.provider == PROVIDER,
                MarketDataFile.data_type == data_type,
                MarketDataFile.instrument_symbol == spec.product,
                MarketDataFile.contract_code == spec.contract_code,
                MarketDataFile.period == PERIOD,
                MarketDataFile.data_version == data_version,
            )
        )
        if market_file is None:
            market_file = MarketDataFile(
                provider=PROVIDER,
                data_type=data_type,
                instrument_symbol=spec.product,
                contract_code=spec.contract_code,
                period=PERIOD,
                data_version=data_version,
            )
            self.session.add(market_file)
        market_file.start_time = start_time
        market_file.end_time = end_time
        market_file.task_id = task.id
        market_file.file_path = str(path)
        market_file.row_count = row_count
        market_file.file_size_bytes = path.stat().st_size if path.exists() else None
        market_file.checksum = sha256_file(path) if path.exists() else None
        market_file.quality_status = quality_status
        self.session.flush()
        return market_file

    def _replace_quality_report(
        self,
        *,
        task: DataDownloadTask,
        market_file: MarketDataFile,
        spec: ProductSpec,
        quality: QualityResult,
        canonical_frame: pd.DataFrame,
        source_csv: Path,
        chunk_start: date,
        chunk_end: date,
    ) -> None:
        self.session.execute(
            delete(DataQualityReport).where(
                DataQualityReport.file_id == market_file.id,
            )
        )
        details = {
            **quality.details,
            "data_layer": "canonical",
            "source_role": "main",
            "download_symbol": spec.download_symbol,
            "source_csv": str(source_csv),
            "chunk_start": chunk_start.isoformat(),
            "chunk_end": chunk_end.isoformat(),
            "rows": len(canonical_frame),
            "columns": list(canonical_frame.columns),
        }
        self.session.add(
            DataQualityReport(
                file_id=market_file.id,
                task_id=task.id,
                provider=PROVIDER,
                data_type=CANONICAL_DATA_TYPE,
                instrument_symbol=spec.product,
                contract_code=spec.contract_code,
                period=PERIOD,
                start_time=market_file.start_time,
                end_time=market_file.end_time,
                status=quality.status,
                missing_bars=quality.missing_bars,
                duplicated_bars=quality.duplicated_bars,
                abnormal_price_count=quality.abnormal_price_count,
                abnormal_volume_count=quality.abnormal_volume_count,
                details=details,
            )
        )

    def _ensure_reference_rows(self, spec: ProductSpec) -> None:
        source = self.session.scalar(select(DataSource).where(DataSource.provider == PROVIDER))
        if source is None:
            self.session.add(
                DataSource(
                    name="天勤 TqSdk",
                    provider=PROVIDER,
                    status="enabled",
                    priority=5,
                    config={"credential_env": ["TQSDK_USERNAME", "TQSDK_PASSWORD"], "storage": "parquet"},
                    remark="TqSdk 主连 1m V0 数据源",
                )
            )
        else:
            source.status = "enabled"
            source.priority = min(source.priority, 5)
            source.config = {**(source.config or {}), "storage": "parquet"}
        exchange = self.session.scalar(select(Exchange).where(Exchange.code == spec.exchange))
        if exchange is None:
            self.session.add(Exchange(code=spec.exchange, name=spec.exchange, country="CN"))
        instrument = self.session.scalar(select(Instrument).where(Instrument.symbol == spec.product))
        if instrument is None:
            self.session.add(
                Instrument(
                    symbol=spec.product,
                    name=spec.name,
                    exchange_code=spec.exchange,
                    sector=spec.sector,
                    category="futures",
                )
            )
        contract = self.session.scalar(select(Contract).where(Contract.contract_code == spec.contract_code))
        if contract is None:
            self.session.add(
                Contract(
                    contract_code=spec.contract_code,
                    instrument_symbol=spec.product,
                    exchange_code=spec.exchange,
                    name=f"{spec.name}主力连续",
                    product=spec.product.lower(),
                    status="research",
                    raw_symbol=spec.download_symbol,
                    provider=PROVIDER,
                )
            )
