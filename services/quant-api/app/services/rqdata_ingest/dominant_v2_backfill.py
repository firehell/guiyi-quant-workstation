from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from app.services.rqdata_ingest.dominant_v2_parquet import (
    _data_version,
    _download_dominant_raw,
    _file_summary,
    _filter_by_datetime,
    _raw_path,
    _standard_path,
)
from app.services.rqdata_ingest.jm_v2_parquet import evaluate_standard_dominant_quality, normalize_jm_dominant_raw_frame
from app.services.rqdata_ingest.parquet import write_parquet_atomic

DEFAULT_GLOBAL_END = date(2026, 7, 10)
BACKFILL_PERIODS = ("1d", "1w")
_FILENAME_RE = re.compile(
    r"^(?P<contract>.+)_(?P<period>1d|1w)_(?P<start>\d{8})_(?P<end>\d{8})_v2\.parquet$"
)


@dataclass(frozen=True)
class DominantCoverage:
    product: str
    period: str
    exchange: str
    file_start: date
    file_end: date
    min_datetime: pd.Timestamp
    max_datetime: pd.Timestamp
    quality_status: str
    raw_path: Path
    standard_path: Path


@dataclass(frozen=True)
class BackfillPlan:
    mode: str
    product: str
    period: str
    exchange: str
    target_start: date
    gap_start: date | None
    gap_end: date | None
    output_start: date
    output_end: date
    reason: str = ""
    coverage: DominantCoverage | None = None
    superseded_paths: tuple[str, ...] = ()


def load_product_starts(path: Path) -> dict[str, date]:
    starts: dict[str, date] = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            product = str(row.get("product") or "").strip().lower()
            effective = str(row.get("effective_1d_start") or "").strip()
            if product and effective:
                starts[product] = date.fromisoformat(effective)
    return starts


def resolve_dominant_coverage(*, output_root: Path, product: str, period: str) -> DominantCoverage | None:
    symbol = product.strip().lower()
    normalized_period = period.strip().lower()
    base = (
        output_root
        / "parquet"
        / "canonical"
        / "bars"
        / "provider=rqdata"
        / f"period={normalized_period}"
    )
    candidates: list[DominantCoverage] = []
    for path in base.glob(f"exchange=*/symbol={symbol}/contract={symbol}.MAIN/*_{normalized_period}_*_v2.parquet"):
        parsed = _parse_standard_filename(path.name, period=normalized_period)
        if parsed is None:
            continue
        frame = pd.read_parquet(path, columns=["datetime"])
        datetimes = pd.to_datetime(frame["datetime"], errors="coerce").dropna()
        if datetimes.empty:
            continue
        exchange = path.parents[2].name.split("=", 1)[-1]
        raw_path = _raw_path(
            output_root,
            symbol=symbol,
            period=normalized_period,
            start_date=parsed["start"],
            end_date=parsed["end"],
        )
        quality_status = _manifest_quality(output_root, symbol, normalized_period, parsed["end"]) or "unknown"
        candidates.append(
            DominantCoverage(
                product=symbol,
                period=normalized_period,
                exchange=exchange,
                file_start=parsed["start"],
                file_end=parsed["end"],
                min_datetime=datetimes.min(),
                max_datetime=datetimes.max(),
                quality_status=quality_status,
                raw_path=raw_path,
                standard_path=path,
            )
        )
    if not candidates:
        return None

    def sort_key(item: DominantCoverage) -> tuple[int, date, date]:
        quality_rank = 0 if item.quality_status == "passed" else 1 if item.quality_status == "warning" else 2
        return (quality_rank, -item.file_end.toordinal(), -item.file_start.toordinal())

    return sorted(candidates, key=sort_key)[0]


def plan_dominant_period_backfill(
    *,
    output_root: Path,
    product: str,
    period: str,
    target_start: date,
    global_end: date = DEFAULT_GLOBAL_END,
    exchange: str | None = None,
) -> BackfillPlan:
    symbol = product.strip().lower()
    normalized_period = period.strip().lower()
    if normalized_period not in BACKFILL_PERIODS:
        raise ValueError(f"unsupported backfill period: {period}")

    coverage = resolve_dominant_coverage(output_root=output_root, product=symbol, period=normalized_period)
    coverage, skip_reason = _resolve_prepend_source_coverage(
        output_root=output_root,
        product=symbol,
        period=normalized_period,
        target_start=target_start,
        primary=coverage,
    )
    if skip_reason is not None:
        return BackfillPlan(
            mode="skip",
            product=symbol,
            period=normalized_period,
            exchange=(exchange or (coverage.exchange if coverage else "DCE")).upper(),
            target_start=target_start,
            gap_start=None,
            gap_end=None,
            output_start=coverage.file_start if coverage else target_start,
            output_end=coverage.file_end if coverage else global_end,
            reason=skip_reason,
            coverage=coverage,
        )
    resolved_exchange = (exchange or (coverage.exchange if coverage else "DCE")).upper()

    if coverage is None:
        return BackfillPlan(
            mode="full_missing",
            product=symbol,
            period=normalized_period,
            exchange=resolved_exchange,
            target_start=target_start,
            gap_start=target_start,
            gap_end=global_end,
            output_start=target_start,
            output_end=global_end,
            reason="no existing canonical asset; download full window",
        )

    existing_min = coverage.min_datetime.date()
    if target_start >= existing_min:
        return BackfillPlan(
            mode="skip",
            product=symbol,
            period=normalized_period,
            exchange=resolved_exchange,
            target_start=target_start,
            gap_start=None,
            gap_end=None,
            output_start=coverage.file_start,
            output_end=coverage.file_end,
            reason=f"target_start {target_start} >= existing_min {existing_min}",
            coverage=coverage,
        )

    gap_end = existing_min - timedelta(days=1)
    if gap_end < target_start:
        return BackfillPlan(
            mode="skip",
            product=symbol,
            period=normalized_period,
            exchange=resolved_exchange,
            target_start=target_start,
            gap_start=None,
            gap_end=None,
            output_start=coverage.file_start,
            output_end=coverage.file_end,
            reason="empty gap after boundary adjustment",
            coverage=coverage,
        )
    if normalized_period == "1w" and (gap_end - target_start).days < 7:
        return BackfillPlan(
            mode="skip",
            product=symbol,
            period=normalized_period,
            exchange=resolved_exchange,
            target_start=target_start,
            gap_start=None,
            gap_end=None,
            output_start=coverage.file_start,
            output_end=coverage.file_end,
            reason="weekly gap shorter than one bar",
            coverage=coverage,
        )

    return BackfillPlan(
        mode="prepend",
        product=symbol,
        period=normalized_period,
        exchange=resolved_exchange,
        target_start=target_start,
        gap_start=target_start,
        gap_end=gap_end,
        output_start=target_start,
        output_end=coverage.file_end,
        reason="prepend historical prefix before existing asset",
        coverage=coverage,
        superseded_paths=(str(coverage.raw_path), str(coverage.standard_path)),
    )


def run_dominant_period_backfill(
    *,
    client: Any,
    output_root: Path,
    plan: BackfillPlan,
    exchange: str | None = None,
) -> dict[str, Any]:
    if plan.mode == "skip":
        return {
            "mode": "skip",
            "product": plan.product,
            "period": plan.period,
            "reason": plan.reason,
            "coverage": _coverage_payload(plan.coverage),
        }

    symbol = plan.product
    period = plan.period
    exchange_code = (exchange or plan.exchange or "DCE").upper()
    assert plan.gap_start is not None and plan.gap_end is not None

    gap_raw = _download_dominant_raw(
        client=client,
        product=symbol,
        exchange=exchange_code,
        period=period,
        start_date=plan.gap_start,
        end_date=plan.gap_end,
    )

    data_version = _data_version(symbol, period, plan.output_start, plan.output_end)
    new_raw_path = _raw_path(
        output_root,
        symbol=symbol,
        period=period,
        start_date=plan.output_start,
        end_date=plan.output_end,
    )
    new_standard_path = _standard_path(
        output_root,
        symbol=symbol,
        exchange=exchange_code,
        contract=f"{symbol}.MAIN",
        period=period,
        start_date=plan.output_start,
        end_date=plan.output_end,
    )

    gap_standard = normalize_jm_dominant_raw_frame(
        gap_raw,
        symbol=symbol,
        exchange=exchange_code,
        interval=period,
        data_version=data_version,
    )
    if plan.mode == "prepend" and plan.coverage is not None and plan.coverage.standard_path.exists():
        existing_standard = pd.read_parquet(plan.coverage.standard_path)
        standard_frame = _merge_standard_frames(gap_standard, existing_standard)
    else:
        standard_frame = gap_standard

    merged_raw = gap_raw
    if plan.mode == "prepend" and plan.coverage is not None:
        existing_raw_path = _resolve_existing_raw_path(plan.coverage)
        if existing_raw_path is not None and existing_raw_path.exists():
            merged_raw = _merge_raw_frames(gap_raw, pd.read_parquet(existing_raw_path))

    standard_frame = _filter_by_datetime(standard_frame, start_date=plan.output_start, end_date=plan.output_end)
    if standard_frame.empty:
        raise ValueError(f"{symbol} {period} backfill produced empty standard frame")

    quality = evaluate_standard_dominant_quality(standard_frame, period)
    standard_frame["quality_status"] = quality.status
    write_parquet_atomic(merged_raw, new_raw_path)
    write_parquet_atomic(standard_frame, new_standard_path)

    return {
        "mode": plan.mode,
        "product": symbol,
        "period": period,
        "exchange": exchange_code,
        "gap_start": plan.gap_start.isoformat(),
        "gap_end": plan.gap_end.isoformat(),
        "output_start": plan.output_start.isoformat(),
        "output_end": plan.output_end.isoformat(),
        "data_version": data_version,
        "quality_status": quality.status,
        "superseded_paths": list(plan.superseded_paths),
        "raw": _file_summary(new_raw_path, merged_raw),
        "standard": _file_summary(new_standard_path, standard_frame),
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


def build_dominant_backfill_summary(
    *,
    product: str,
    exchange: str,
    start_date: date,
    end_date: date,
    period_results: dict[str, Any],
) -> dict[str, Any]:
    return {
        "mode": "dominant-v2-backfill",
        "symbol": product.strip().lower(),
        "contract": f"{product.strip().lower()}.MAIN",
        "exchange": exchange.upper(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "periods": period_results,
        "writes_database": False,
    }


def resolve_layer2_backfill_window(
    *,
    output_root: Path,
    product: str,
    period: str,
    target_start: date,
    global_end: date = DEFAULT_GLOBAL_END,
) -> dict[str, Any]:
    layer1_plan = plan_dominant_period_backfill(
        output_root=output_root,
        product=product,
        period=period,
        target_start=target_start,
        global_end=global_end,
    )
    if layer1_plan.mode == "skip":
        return {
            "mode": "skip",
            "product": product,
            "period": period,
            "reason": layer1_plan.reason,
        }
    return {
        "mode": layer1_plan.mode,
        "product": product,
        "period": period,
        "start_date": layer1_plan.gap_start.isoformat() if layer1_plan.gap_start else target_start.isoformat(),
        "end_date": layer1_plan.gap_end.isoformat() if layer1_plan.gap_end else global_end.isoformat(),
        "trade_date": (layer1_plan.gap_end or global_end).isoformat(),
    }


def write_backfill_report(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        pd.DataFrame(columns=["product", "period", "layer", "mode", "status", "detail"]).to_csv(path, index=False)
        return
    pd.DataFrame(rows).to_csv(path, index=False)


def _resolve_prepend_source_coverage(
    *,
    output_root: Path,
    product: str,
    period: str,
    target_start: date,
    primary: DominantCoverage | None,
) -> tuple[DominantCoverage | None, str | None]:
    if primary is None:
        return None, None
    if primary.file_start > target_start:
        return primary, None
    if primary.min_datetime.date() <= target_start and primary.max_datetime.date() >= date(2023, 1, 3):
        return primary, f"already backfilled through {primary.max_datetime.date()}"

    tail = _find_tail_coverage(
        output_root=output_root,
        product=product,
        period=period,
        target_start=target_start,
    )
    if tail is not None:
        return tail, None
    if primary.min_datetime.date() <= target_start:
        return primary, f"incomplete backfill without tail source through {primary.max_datetime.date()}"
    return primary, None


def _find_tail_coverage(
    *,
    output_root: Path,
    product: str,
    period: str,
    target_start: date,
) -> DominantCoverage | None:
    candidates: list[DominantCoverage] = []
    base = (
        output_root
        / "parquet"
        / "canonical"
        / "bars"
        / "provider=rqdata"
        / f"period={period.strip().lower()}"
    )
    pattern = (
        f"exchange=*/symbol={product.strip().lower()}/contract={product.strip().lower()}.MAIN/"
        f"*{product.strip().lower()}_MAIN_{period.strip().lower()}_*_v2.parquet"
    )
    for path in base.glob(pattern):
        parsed = _parse_standard_filename(path.name, period=period.strip().lower())
        if parsed is None or parsed["start"] <= target_start:
            continue
        frame = pd.read_parquet(path, columns=["datetime"])
        datetimes = pd.to_datetime(frame["datetime"], errors="coerce").dropna()
        if datetimes.empty:
            continue
        exchange = path.parents[2].name.split("=", 1)[-1]
        raw_path = _raw_path(
            output_root,
            symbol=product.strip().lower(),
            period=period.strip().lower(),
            start_date=parsed["start"],
            end_date=parsed["end"],
        )
        candidates.append(
            DominantCoverage(
                product=product.strip().lower(),
                period=period.strip().lower(),
                exchange=exchange,
                file_start=parsed["start"],
                file_end=parsed["end"],
                min_datetime=datetimes.min(),
                max_datetime=datetimes.max(),
                quality_status="unknown",
                raw_path=raw_path,
                standard_path=path,
            )
        )
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (-item.file_end.toordinal(), -item.file_start.toordinal()))[0]


def _merge_standard_frames(gap_standard: pd.DataFrame, existing_standard: pd.DataFrame) -> pd.DataFrame:
    frames = [frame for frame in (gap_standard, existing_standard) if frame is not None and not frame.empty]
    merged = pd.concat(frames, ignore_index=True)
    merged["datetime"] = pd.to_datetime(merged["datetime"], errors="coerce")
    merged = merged.dropna(subset=["datetime"]).sort_values(["datetime"]).drop_duplicates(subset=["datetime"], keep="last")
    return merged.reset_index(drop=True)


def _resolve_existing_raw_path(coverage: DominantCoverage) -> Path | None:
    if coverage.raw_path.exists():
        return coverage.raw_path
    raw_dir = coverage.raw_path.parent
    if not raw_dir.exists():
        return None
    candidates = sorted(raw_dir.glob(f"{coverage.product}_{coverage.period}_dominant_raw_*_v2.parquet"))
    if not candidates:
        return None
    return candidates[-1]


def _merge_raw_frames(gap_raw: pd.DataFrame, existing_raw: pd.DataFrame) -> pd.DataFrame:
    frames = [frame for frame in (gap_raw, existing_raw) if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True)
    if "datetime" not in merged.columns:
        merged["datetime"] = pd.to_datetime(merged.get("date", merged.index), errors="coerce")
    merged["datetime"] = pd.to_datetime(merged["datetime"], errors="coerce")
    merged = merged.dropna(subset=["datetime"]).sort_values(["datetime"]).drop_duplicates(subset=["datetime"], keep="last")
    return merged.reset_index(drop=True)


def _parse_standard_filename(name: str, *, period: str) -> dict[str, date] | None:
    match = _FILENAME_RE.match(name)
    if match is None or match.group("period") != period:
        return None
    return {
        "start": date.fromisoformat(f"{match.group('start')[:4]}-{match.group('start')[4:6]}-{match.group('start')[6:8]}"),
        "end": date.fromisoformat(f"{match.group('end')[:4]}-{match.group('end')[4:6]}-{match.group('end')[6:8]}"),
    }


def _manifest_quality(output_root: Path, symbol: str, period: str, file_end: date) -> str | None:
    manifests = sorted((output_root / "manifests").glob(f"rqdata_{symbol}_v2_history_*.csv"))
    for manifest in reversed(manifests):
        with manifest.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("period") != period:
                    continue
                if file_end.isoformat().replace("-", "") in manifest.name or True:
                    return str(row.get("quality_status") or row.get("original_quality_status") or "")
    return None


def _coverage_payload(coverage: DominantCoverage | None) -> dict[str, Any] | None:
    if coverage is None:
        return None
    return {
        "file_start": coverage.file_start.isoformat(),
        "file_end": coverage.file_end.isoformat(),
        "min_datetime": coverage.min_datetime.isoformat(),
        "max_datetime": coverage.max_datetime.isoformat(),
        "quality_status": coverage.quality_status,
        "raw_path": str(coverage.raw_path),
        "standard_path": str(coverage.standard_path),
    }


def summary_path_for_product(output_root: Path, product: str, start_date: date, end_date: date) -> Path:
    symbol = product.strip().lower()
    return output_root / "processed" / "v1b" / symbol / f"{symbol}_v2_parquet_{start_date:%Y%m%d}_{end_date:%Y%m%d}.json"


def persist_backfill_summary(summary: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
