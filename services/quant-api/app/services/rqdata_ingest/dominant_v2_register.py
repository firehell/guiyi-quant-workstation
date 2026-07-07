from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import DataQualityReport, utc_now
from app.services.rqdata_ingest.bar_sample import _ensure_reference_rows, _record_canonical_file_and_quality, _start_task
from app.services.rqdata_ingest.jm_v2_parquet import evaluate_standard_dominant_quality
from app.services.rqdata_ingest.parquet import sha256_file


def register_dominant_v2_quality(*, session: Session, summary_path: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    symbol = str(summary.get("symbol") or "").lower()
    contract = str(summary.get("contract") or f"{symbol}.MAIN")
    exchange = str(summary.get("exchange") or "DCE").upper()
    periods = summary.get("periods") or {}
    if not isinstance(periods, dict) or not periods:
        raise ValueError(f"dominant v2 parquet summary has no periods: {summary_path}")
    start_token = summary["start_date"].replace("-", "")
    end_token = summary["end_date"].replace("-", "")
    manifest_path = manifest_path or summary_path.parents[3] / "manifests" / f"rqdata_{symbol}_v2_history_{start_token}_{end_token}.csv"
    registered: dict[str, Any] = {}
    manifest_rows: list[dict[str, Any]] = []
    for period, payload in periods.items():
        standard = payload["standard"]
        raw = payload["raw"]
        standard_path = Path(standard["path"])
        raw_path = Path(raw["path"])
        if not standard_path.exists():
            raise FileNotFoundError(f"{symbol} {period} standard parquet not found: {standard_path}")
        frame = pd.read_parquet(standard_path)
        quality = evaluate_standard_dominant_quality(frame, period)
        if quality.status == "failed":
            raise ValueError(f"{symbol} {period} quality failed; refusing DB registration")
        checksum = sha256_file(standard_path)
        if checksum != standard["checksum"]:
            raise ValueError(f"{symbol} {period} checksum mismatch: {checksum} != {standard['checksum']}")
        start_dt = _as_datetime(frame["datetime"].min())
        end_dt = _as_datetime(frame["datetime"].max())
        task = _start_task(
            session=session,
            symbol=symbol,
            contract=contract,
            frequency=period,
            start_date=start_dt.date(),
            end_date=end_dt.date(),
        )
        _ensure_reference_rows(session, symbol=symbol, contract=contract, exchange=exchange)
        market_file = _record_canonical_file_and_quality(
            session=session,
            task=task,
            path=standard_path,
            frame=frame,
            quality=quality,
            symbol=symbol,
            contract=contract,
            frequency=period,
            data_version=payload["data_version"],
        )
        task.status = "success"
        task.progress = 100
        task.finished_at = utc_now()
        task.result = {
            "dominant_v2_register_quality": True,
            "summary_path": str(summary_path),
            "manifest_path": str(manifest_path),
            "raw_path": str(raw_path),
            "standard_path": str(standard_path),
            "row_count": len(frame),
            "quality_status": quality.status,
            "checksum": checksum,
            "data_version": payload["data_version"],
        }
        session.flush()
        report = session.scalar(select(DataQualityReport).where(DataQualityReport.file_id == market_file.id))
        if report is not None:
            report.details = {
                **(report.details or {}),
                "dominant_v2_register_quality": True,
                "summary_path": str(summary_path),
                "manifest_path": str(manifest_path),
                "raw_path": str(raw_path),
                "standard_path": str(standard_path),
                "checksum": checksum,
                "data_version": payload["data_version"],
                "row_count": len(frame),
            }
        session.flush()
        report_id = None if report is None else report.id
        registered[period] = {
            "market_data_file_id": market_file.id,
            "data_quality_report_id": report_id,
            "data_version": payload["data_version"],
            "quality_status": quality.status,
            "row_count": len(frame),
            "checksum": checksum,
            "standard_path": str(standard_path),
            "raw_path": str(raw_path),
        }
        manifest_rows.append(
            {
                "period": period,
                "data_version": payload["data_version"],
                "provider": "rqdata",
                "source": "rqdata",
                "data_role": "primary",
                "quality_status": quality.status,
                "row_count": len(frame),
                "min_datetime": start_dt.isoformat(),
                "max_datetime": end_dt.isoformat(),
                "checksum": checksum,
                "standard_path": str(standard_path),
                "raw_path": str(raw_path),
                "market_data_file_id": market_file.id,
                "data_quality_report_id": report_id,
                "status": "success",
            }
        )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(manifest_rows).sort_values("period").to_csv(manifest_path, index=False)
    return {
        "mode": "dominant-v2-register-quality",
        "symbol": symbol,
        "contract": contract,
        "exchange": exchange,
        "summary_path": str(summary_path),
        "manifest_path": str(manifest_path),
        "writes_database": True,
        "periods": registered,
    }


def _as_datetime(value: Any) -> datetime:
    return pd.Timestamp(value).to_pydatetime()
