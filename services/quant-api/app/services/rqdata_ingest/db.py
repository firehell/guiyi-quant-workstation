from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import DataDownloadTask, DataQualityReport, MarketDataFile, utc_now
from app.services.rqdata_ingest.parquet import sha256_file
from app.services.rqdata_ingest.quality import QualityResult


def json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "item"):
        return json_safe(value.item())
    return value


def row_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): json_safe(value) for key, value in row.items()}


def as_date(value: Any) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        if pd.isna(value) or value.year < 1:
            return None
        return value.date()
    if isinstance(value, datetime):
        return None if value.year < 1 else value.date()
    if isinstance(value, date):
        return None if value.year < 1 else value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized or normalized.lower() == "nat" or normalized.startswith("0000"):
            return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    result = parsed.date()
    return None if result.year < 1 else result


def as_datetime(value: date | datetime | None, end_of_day: bool = False) -> datetime:
    if value is None:
        return utc_now()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.combine(value, time.max if end_of_day else time.min, tzinfo=UTC)


def as_decimal(value: Any) -> Decimal | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return Decimal(str(value))


def as_int(value: Any) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return int(value)


def upsert_one(session: Session, model: type, keys: dict[str, Any], values: dict[str, Any]) -> Any:
    for pending in session.new:
        if isinstance(pending, model) and all(getattr(pending, key, None) == value for key, value in keys.items()):
            for key, value in values.items():
                setattr(pending, key, value)
            return pending
    instance = session.scalar(select(model).filter_by(**keys))
    if instance is None:
        instance = model(**keys)
        session.add(instance)
    for key, value in values.items():
        setattr(instance, key, value)
    return instance


class IngestRecorder:
    def __init__(self, session: Session, project_root: Path) -> None:
        self.session = session
        self.project_root = project_root

    def start_task(
        self,
        *,
        data_type: str,
        start_date: date,
        end_date: date,
        instrument_symbol: str | None = None,
        contract_code: str | None = None,
        period: str | None = None,
    ) -> DataDownloadTask:
        task = DataDownloadTask(
            task_no=f"rqdata-{data_type}-{uuid4().hex[:12]}",
            provider="rqdata",
            data_type=data_type,
            instrument_symbol=instrument_symbol,
            contract_code=contract_code,
            period=period,
            start_time=as_datetime(start_date),
            end_time=as_datetime(end_date, end_of_day=True),
            status="running",
            progress=0,
            started_at=utc_now(),
            result={},
        )
        self.session.add(task)
        self.session.flush()
        return task

    def finish_task(self, task: DataDownloadTask, *, row_count: int, file_path: Path | None, status: str = "success", error: str | None = None) -> None:
        task.status = status
        task.progress = 100 if status == "success" else 0
        task.error_message = error
        task.finished_at = utc_now()
        task.result = {"row_count": row_count, "file_path": None if file_path is None else str(file_path)}

    def record_file(
        self,
        *,
        task: DataDownloadTask,
        path: Path,
        data_type: str,
        row_count: int,
        data_version: str,
        quality: QualityResult,
        start_date: date,
        end_date: date,
        instrument_symbol: str | None = None,
        contract_code: str | None = None,
        period: str | None = None,
    ) -> MarketDataFile:
        market_file = upsert_one(
            self.session,
            MarketDataFile,
            {
                "provider": "rqdata",
                "data_type": data_type,
                "instrument_symbol": instrument_symbol,
                "contract_code": contract_code,
                "period": period,
                "start_time": as_datetime(start_date),
                "end_time": as_datetime(end_date, end_of_day=True),
                "data_version": data_version,
            },
            {
                "task_id": task.id,
                "file_path": str(path),
                "row_count": row_count,
                "file_size_bytes": path.stat().st_size if path.exists() else None,
                "checksum": sha256_file(path) if path.exists() else None,
                "quality_status": quality.status,
            },
        )
        self.session.flush()
        self.session.add(
            DataQualityReport(
                file_id=market_file.id,
                task_id=task.id,
                provider="rqdata",
                data_type=data_type,
                instrument_symbol=instrument_symbol,
                contract_code=contract_code,
                period=period,
                start_time=as_datetime(start_date),
                end_time=as_datetime(end_date, end_of_day=True),
                status=quality.status,
                missing_bars=0,
                duplicated_bars=quality.duplicate_rows,
                abnormal_price_count=0,
                abnormal_volume_count=0,
                details=quality.details,
            )
        )
        return market_file
