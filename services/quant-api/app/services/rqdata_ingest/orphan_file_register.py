from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import MarketDataFile
from app.services.rqdata_ingest.bar_sample import BarQuality, _ensure_reference_rows, _record_canonical_file_and_quality, _start_task
from app.services.rqdata_ingest.jm_v2_parquet import evaluate_standard_dominant_quality


MODE = "orphan_file_register"
CONFIRM_FLAG = "--confirm-orphan-register"
WARNING_PRODUCTS = frozenset({"bb", "rs", "wh", "wr", "zc"})
_FILENAME_RE = re.compile(
    r"^(?P<contract>.+)_(?P<period>1d|1w)_(?P<start>\d{8})_(?P<end>\d{8})_v2\.parquet$"
)


@dataclass(frozen=True)
class OrphanCandidate:
    physical_path: Path
    product: str
    period: str
    contract: str


def build_orphan_file_register_plan(
    *,
    session: Session,
    project_root: Path,
    orphan_csv: Path,
    apply: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    candidates = _load_candidates(orphan_csv)
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []

    for candidate in candidates:
        row = _evaluate_candidate(session=session, project_root=project_root, candidate=candidate)
        rows.append(row)
        if row["blocked_reasons"]:
            blockers.extend(row["blocked_reasons"].split("|"))

    if apply and not confirm:
        blockers.append("confirmation_required")
    if any(row["decision"] == "blocked" for row in rows):
        blockers.append("candidate_blocked")

    ready = not blockers
    apply_rows: list[dict[str, Any]] = []
    if apply and ready:
        for candidate, row in zip(candidates, rows, strict=True):
            if row["decision"] != "ready":
                continue
            apply_rows.append(_register_orphan(session=session, candidate=candidate, row=row))

    return {
        "mode": MODE,
        "operation": "apply" if apply else "dry-run",
        "confirm": confirm,
        "confirm_flag": CONFIRM_FLAG,
        "candidate_count": len(candidates),
        "candidates": rows,
        "apply_rows": apply_rows,
        "blocked_reasons": sorted(set(blockers)),
        "ready_to_apply": ready,
        "writes_database": bool(apply and ready),
        "writes_parquet": False,
        "calls_rqdata": False,
    }


def write_orphan_file_register_reports(result: dict[str, Any], *, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "orphan_file_register_plan.csv"
    pd.DataFrame(result["candidates"]).to_csv(plan_path, index=False)
    summary_path = output_dir / "orphan_file_register_summary.json"
    summary_path.write_text(json.dumps({k: v for k, v in result.items() if k != "candidates"}, indent=2, default=str), encoding="utf-8")
    return {"plan": plan_path, "summary": summary_path}


def _load_candidates(orphan_csv: Path) -> list[OrphanCandidate]:
    frame = pd.read_csv(orphan_csv)
    candidates: list[OrphanCandidate] = []
    for _, row in frame.iterrows():
        path_text = str(row.get("physical_path") or "").strip()
        if not path_text:
            continue
        candidates.append(
            OrphanCandidate(
                physical_path=Path(path_text),
                product=str(row.get("product") or "").strip().lower(),
                period=str(row.get("period") or "").strip().lower(),
                contract=str(row.get("contract") or "").strip(),
            )
        )
    return candidates


def _evaluate_candidate(*, session: Session, project_root: Path, candidate: OrphanCandidate) -> dict[str, Any]:
    path = candidate.physical_path
    blockers: list[str] = []
    if not path.exists():
        blockers.append("file_missing")
    existing = session.scalar(select(MarketDataFile).where(MarketDataFile.file_path == str(path.resolve())))
    if existing is not None:
        blockers.append("already_registered")

    parsed = _parse_filename(path.name)
    exchange = _exchange_from_path(path)
    summary = _duckdb_summary(path) if path.exists() else {}
    expected_quality = "warning" if candidate.product in WARNING_PRODUCTS else "passed"

    decision = "blocked" if blockers else "ready"
    return {
        "physical_path": str(path.resolve()),
        "product": candidate.product,
        "period": candidate.period,
        "contract": candidate.contract,
        "exchange": exchange,
        "expected_quality_status": expected_quality,
        "row_count": summary.get("row_count", ""),
        "min_datetime": summary.get("min_datetime", ""),
        "max_datetime": summary.get("max_datetime", ""),
        "parsed_start": parsed.get("start", "") if parsed else "",
        "parsed_end": parsed.get("end", "") if parsed else "",
        "blocked_reasons": "|".join(sorted(set(blockers))),
        "decision": decision,
    }


def _register_orphan(*, session: Session, candidate: OrphanCandidate, row: dict[str, Any]) -> dict[str, Any]:
    path = candidate.physical_path
    frame = pd.read_parquet(path)
    if candidate.product in WARNING_PRODUCTS:
        register_quality = BarQuality(
            status="warning",
            missing_bars=0,
            duplicated_bars=0,
            abnormal_price_count=0,
            abnormal_volume_count=0,
            abnormal_open_interest_count=0,
            details={"orphan_register_accepted_warning": True, "accepted_warning_product": candidate.product},
        )
    else:
        quality = evaluate_standard_dominant_quality(frame, candidate.period)
        register_quality = quality
        if quality.status == "failed":
            raise ValueError(f"refusing to register failed-quality orphan: {path}")

    parsed = _parse_filename(path.name)
    if parsed is None:
        raise ValueError(f"cannot parse orphan filename: {path.name}")
    start_dt = _as_datetime(frame["datetime"].min())
    end_dt = _as_datetime(frame["datetime"].max())
    data_version = f"rqdata_{candidate.product}_standard_{candidate.period}_{parsed['start']:%Y%m%d}_{parsed['end']:%Y%m%d}_v2"

    task = _start_task(
        session=session,
        symbol=candidate.product,
        contract=candidate.contract,
        frequency=candidate.period,
        start_date=start_dt.date(),
        end_date=end_dt.date(),
    )
    _ensure_reference_rows(session, symbol=candidate.product, contract=candidate.contract, exchange=row["exchange"])
    market_file = _record_canonical_file_and_quality(
        session=session,
        task=task,
        path=path,
        frame=frame,
        quality=register_quality,
        symbol=candidate.product,
        contract=candidate.contract,
        frequency=candidate.period,
        data_version=data_version,
    )
    return {
        "physical_path": str(path.resolve()),
        "market_data_file_id": market_file.id,
        "quality_status": market_file.quality_status,
        "data_version": market_file.data_version,
    }


def _parse_filename(name: str) -> dict[str, Any] | None:
    match = _FILENAME_RE.match(name)
    if not match:
        return None
    return {
        "start": datetime.strptime(match.group("start"), "%Y%m%d").date(),
        "end": datetime.strptime(match.group("end"), "%Y%m%d").date(),
    }


def _exchange_from_path(path: Path) -> str:
    for parent in path.parents:
        if parent.name.startswith("exchange="):
            return parent.name.split("=", 1)[-1].upper()
    return "DCE"


def _duckdb_summary(path: Path) -> dict[str, Any]:
    frame = pd.read_parquet(path, columns=["datetime"])
    datetimes = pd.to_datetime(frame["datetime"], errors="coerce").dropna()
    return {
        "row_count": len(frame),
        "min_datetime": str(datetimes.min()) if not datetimes.empty else "",
        "max_datetime": str(datetimes.max()) if not datetimes.empty else "",
    }


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
