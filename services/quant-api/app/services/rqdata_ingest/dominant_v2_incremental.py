from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import re
from typing import Any

import pandas as pd

from app.services.rqdata_ingest.dominant_v2_parquet import (
    FORMAL_START,
    _data_version,
    _download_dominant_raw,
    _file_summary,
    _filter_by_datetime,
    _standard_path,
)
from app.services.rqdata_ingest.jm_v2_parquet import (
    evaluate_standard_dominant_quality,
    normalize_jm_dominant_raw_frame,
)
from app.services.rqdata_ingest.parquet import write_parquet_atomic

LOOKBACK_DAYS = {"1m": 2, "1d": 5, "1w": 14}
FILENAME_WINDOW_RE = re.compile(r"_(1m|1d|1w|5m|15m|30m|60m)_(\d{8})_(\d{8})_v2\.parquet$")


@dataclass(frozen=True)
class CanonicalBaseline:
    path: Path
    frame: pd.DataFrame
    start_date: date
    end_date_token: date
    last_datetime: pd.Timestamp


@dataclass(frozen=True)
class IncrementalTailResult:
    status: str
    product: str
    period: str
    target_end: date
    baseline_path: str | None = None
    output_path: str | None = None
    summary_path: str | None = None
    delta_start: str | None = None
    delta_end: str | None = None
    baseline_last: str | None = None
    merged_last: str | None = None
    row_count: int | None = None
    quality_status: str | None = None
    error: str | None = None


def find_latest_main_canonical(output_root: Path, symbol: str, period: str) -> CanonicalBaseline | None:
    symbol = symbol.strip().lower()
    contract = f"{symbol}.MAIN"
    root = output_root / "parquet" / "canonical" / "bars" / "provider=rqdata" / f"period={period}"
    if not root.exists():
        return None
    candidates = list(root.glob(f"**/symbol={symbol}/contract={contract}/*_v2.parquet"))
    if not candidates:
        return None
    best_path: Path | None = None
    best_last: pd.Timestamp | None = None
    best_frame: pd.DataFrame | None = None
    for path in candidates:
        frame = pd.read_parquet(path, columns=["datetime"])
        if frame.empty:
            continue
        last_dt = pd.to_datetime(frame["datetime"], errors="coerce").max()
        if pd.isna(last_dt):
            continue
        if best_last is None or last_dt > best_last:
            best_last = pd.Timestamp(last_dt)
            best_path = path
            best_frame = pd.read_parquet(path)
    if best_path is None or best_frame is None or best_last is None:
        return None
    start_date, end_token = _parse_window_from_filename(best_path.name, period)
    if start_date is None:
        start_date = FORMAL_START
    if end_token is None:
        end_token = best_last.date()
    return CanonicalBaseline(
        path=best_path,
        frame=best_frame,
        start_date=start_date,
        end_date_token=end_token,
        last_datetime=best_last,
    )


def last_bar_datetime(frame: pd.DataFrame, period: str) -> pd.Timestamp:
    values = pd.to_datetime(frame["datetime"], errors="coerce")
    if values.empty or values.isna().all():
        raise ValueError(f"frame has no valid datetime for period={period}")
    return pd.Timestamp(values.max())


def compute_delta_start(last_dt: pd.Timestamp, period: str) -> date:
    lookback = LOOKBACK_DAYS.get(period, 2)
    return (pd.Timestamp(last_dt).normalize() - timedelta(days=lookback)).date()


def is_up_to_date(last_dt: pd.Timestamp, target_end: date, period: str) -> bool:
    last = pd.Timestamp(last_dt)
    if period == "1m":
        if last.date() > target_end:
            return True
        if last.date() == target_end:
            return last.hour >= 15
        return False
    return last.date() >= target_end


def merge_dominant_frames(baseline: pd.DataFrame, delta: pd.DataFrame) -> pd.DataFrame:
    if baseline.empty:
        merged = delta.copy()
    elif delta.empty:
        merged = baseline.copy()
    else:
        merged = pd.concat([baseline, delta], ignore_index=True)
    merged["datetime"] = pd.to_datetime(merged["datetime"], errors="coerce")
    merged = merged.dropna(subset=["datetime"]).sort_values("datetime")
    merged = merged.drop_duplicates(subset=["datetime"], keep="last").reset_index(drop=True)
    return merged


def _incremental_raw_path(
    output_root: Path,
    *,
    symbol: str,
    period: str,
    delta_start: date,
    delta_end: date,
) -> Path:
    return (
        output_root
        / "raw"
        / "rqdata"
        / "dominant_contract_bars"
        / f"product={symbol}"
        / f"frequency={period}"
        / "version=v2"
        / f"{symbol}_{period}_incremental_raw_{delta_start:%Y%m%d}_{delta_end:%Y%m%d}.parquet"
    )


def _summary_path(output_root: Path, *, symbol: str, period: str, start_date: date, end_date: date) -> Path:
    return (
        output_root
        / "processed"
        / "v1b"
        / symbol
        / f"{symbol}_v2_incremental_{period}_{start_date:%Y%m%d}_{end_date:%Y%m%d}.json"
    )


def _parse_window_from_filename(name: str, period: str) -> tuple[date | None, date | None]:
    match = FILENAME_WINDOW_RE.search(name)
    if match is None or match.group(1) != period:
        return None, None
    return date.fromisoformat(
        f"{match.group(2)[:4]}-{match.group(2)[4:6]}-{match.group(2)[6:8]}"
    ), date.fromisoformat(f"{match.group(3)[:4]}-{match.group(3)[4:6]}-{match.group(3)[6:8]}")


def append_dominant_v2_tail(
    *,
    client: Any,
    output_root: Path,
    product: str,
    exchange: str,
    period: str,
    target_end: date,
    dry_run: bool = False,
    register: bool = False,
    allow_quality_failed: bool = True,
    session: Any | None = None,
) -> IncrementalTailResult:
    symbol = product.strip().lower()
    contract = f"{symbol}.MAIN"
    exchange_code = str(exchange or "DCE").upper()
    baseline = find_latest_main_canonical(output_root, symbol, period)
    if baseline is None:
        return IncrementalTailResult(
            status="skipped_no_baseline",
            product=symbol,
            period=period,
            target_end=target_end,
        )
    last_dt = baseline.last_datetime
    if is_up_to_date(last_dt, target_end, period):
        return IncrementalTailResult(
            status="skipped_up_to_date",
            product=symbol,
            period=period,
            target_end=target_end,
            baseline_path=str(baseline.path),
            baseline_last=last_dt.isoformat(),
        )
    delta_start = compute_delta_start(last_dt, period)
    if delta_start > target_end:
        return IncrementalTailResult(
            status="skipped_up_to_date",
            product=symbol,
            period=period,
            target_end=target_end,
            baseline_path=str(baseline.path),
            baseline_last=last_dt.isoformat(),
            delta_start=delta_start.isoformat(),
            delta_end=target_end.isoformat(),
        )
    if dry_run:
        return IncrementalTailResult(
            status="dry_run",
            product=symbol,
            period=period,
            target_end=target_end,
            baseline_path=str(baseline.path),
            baseline_last=last_dt.isoformat(),
            delta_start=delta_start.isoformat(),
            delta_end=target_end.isoformat(),
        )
    if client is None:
        raise ValueError("RQData client is required when dry_run=False")

    raw_path = _incremental_raw_path(
        output_root,
        symbol=symbol,
        period=period,
        delta_start=delta_start,
        delta_end=target_end,
    )
    raw_frame = _download_dominant_raw(
        client=client,
        product=symbol,
        exchange=exchange_code,
        period=period,
        start_date=delta_start,
        end_date=target_end,
    )
    write_parquet_atomic(raw_frame, raw_path)

    data_version = _data_version(symbol, period, baseline.start_date, target_end)
    delta_standard = normalize_jm_dominant_raw_frame(
        raw_frame,
        symbol=symbol,
        exchange=exchange_code,
        interval=period,
        data_version=data_version,
    )
    delta_standard = _filter_by_datetime(delta_standard, start_date=delta_start, end_date=target_end)
    merged = merge_dominant_frames(baseline.frame, delta_standard)
    merged = _filter_by_datetime(merged, start_date=baseline.start_date, end_date=target_end)
    if merged.empty:
        return IncrementalTailResult(
            status="failed",
            product=symbol,
            period=period,
            target_end=target_end,
            baseline_path=str(baseline.path),
            error="merged frame is empty",
        )

    quality = evaluate_standard_dominant_quality(merged, period)
    merged["quality_status"] = quality.status
    merged["data_version"] = data_version

    output_path = _standard_path(
        output_root,
        symbol=symbol,
        exchange=exchange_code,
        contract=contract,
        period=period,
        start_date=baseline.start_date,
        end_date=target_end,
    )
    write_parquet_atomic(merged, output_path)

    summary = {
        "mode": "dominant-v2-incremental-tail",
        "symbol": symbol,
        "contract": contract,
        "exchange": exchange_code,
        "start_date": baseline.start_date.isoformat(),
        "end_date": target_end.isoformat(),
        "baseline_path": str(baseline.path),
        "delta_start": delta_start.isoformat(),
        "delta_end": target_end.isoformat(),
        "periods": {
            period: {
                "data_version": data_version,
                "quality_status": quality.status,
                "derivation_mode": "rqdata_direct_incremental",
                "raw": _file_summary(raw_path, raw_frame),
                "standard": _file_summary(output_path, merged),
                "quality": {
                    "status": quality.status,
                    "missing_bars": quality.missing_bars,
                    "duplicated_bars": quality.duplicated_bars,
                    "abnormal_price_count": quality.abnormal_price_count,
                    "abnormal_volume_count": quality.abnormal_volume_count,
                    "abnormal_open_interest_count": quality.abnormal_open_interest_count,
                    "details": quality.details,
                },
            }
        },
        "writes_database": register,
    }
    summary_path = _summary_path(output_root, symbol=symbol, period=period, start_date=baseline.start_date, end_date=target_end)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    import json

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    if register:
        if session is None:
            raise ValueError("session is required when register=True")
        from app.services.rqdata_ingest.dominant_v2_register import register_dominant_v2_quality

        start_token = baseline.start_date.strftime("%Y%m%d")
        end_token = target_end.strftime("%Y%m%d")
        manifest_path = output_root / "manifests" / f"rqdata_{symbol}_v2_history_{start_token}_{end_token}.csv"
        register_dominant_v2_quality(
            session=session,
            summary_path=summary_path,
            manifest_path=manifest_path,
            allow_quality_failed=allow_quality_failed,
        )

    merged_last = last_bar_datetime(merged, period)
    return IncrementalTailResult(
        status="updated",
        product=symbol,
        period=period,
        target_end=target_end,
        baseline_path=str(baseline.path),
        output_path=str(output_path),
        summary_path=str(summary_path),
        delta_start=delta_start.isoformat(),
        delta_end=target_end.isoformat(),
        baseline_last=last_dt.isoformat(),
        merged_last=merged_last.isoformat(),
        row_count=len(merged),
        quality_status=quality.status,
    )
