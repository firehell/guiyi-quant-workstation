from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.data_center import MarketDataFile


MODE = "duplicate_active_supersede"
CONFIRM_FLAG = "--confirm-duplicate-active-supersede"
SUPERSEDED_ROLE = "superseded"
ACTIVE_ROLE = "primary"


@dataclass(frozen=True)
class SupersedeGroup:
    product: str
    contract_code: str
    period: str
    current_id: int
    superseded_ids: tuple[int, ...]


def build_duplicate_active_supersede_plan(
    *,
    session: Session,
    apply: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    groups = _duplicate_primary_groups(session)
    rows: list[dict[str, Any]] = []
    supersede_groups: list[SupersedeGroup] = []

    for key, items in sorted(groups.items()):
        product, contract_code, period = key
        current = _pick_current(items)
        superseded = [item for item in items if item.id != current.id]
        supersede_groups.append(
            SupersedeGroup(
                product=product,
                contract_code=contract_code,
                period=period,
                current_id=current.id,
                superseded_ids=tuple(item.id for item in superseded),
            )
        )
        for item in items:
            rows.append(
                {
                    "product": product,
                    "contract_code": contract_code,
                    "period": period,
                    "market_data_file_id": item.id,
                    "data_version": item.data_version or "",
                    "quality_status": item.quality_status or "",
                    "file_path": item.file_path or "",
                    "start_time": _iso(item.start_time),
                    "end_time": _iso(item.end_time),
                    "duplicate_group_size": len(items),
                    "decision": "keep_primary" if item.id == current.id else "mark_superseded",
                    "current_market_data_file_id": current.id,
                }
            )

    blockers: list[str] = []
    if apply and not confirm:
        blockers.append("confirmation_required")

    ready_to_apply = not blockers if apply else True

    apply_result: dict[str, Any] | None = None
    if apply and ready_to_apply and supersede_groups:
        apply_result = apply_duplicate_active_supersede(session=session, groups=supersede_groups)
    elif apply and ready_to_apply:
        apply_result = {"superseded_ids": [], "superseded_count": 0, "remaining_duplicate_groups": 0}

    return {
        "mode": MODE,
        "operation": "apply" if apply else "dry-run",
        "confirm": confirm,
        "confirm_flag": CONFIRM_FLAG,
        "duplicate_group_count": len(groups),
        "rows_to_supersede": sum(len(group.superseded_ids) for group in supersede_groups),
        "plan_rows": rows,
        "blocked_reasons": blockers,
        "ready_to_apply": ready_to_apply,
        "writes_database": bool(apply and ready_to_apply),
        "writes_parquet": False,
        "calls_rqdata": False,
        "apply_result": apply_result,
        "decision_counts": dict(Counter(row["decision"] for row in rows)),
    }


def apply_duplicate_active_supersede(*, session: Session, groups: list[SupersedeGroup]) -> dict[str, Any]:
    superseded_ids: list[int] = []
    promoted_ids: list[int] = []
    for group in groups:
        winner_id = group.current_id
        session.execute(
            update(MarketDataFile).where(MarketDataFile.id == winner_id).values(data_role=ACTIVE_ROLE)
        )
        promoted_ids.append(winner_id)
        if group.superseded_ids:
            session.execute(
                update(MarketDataFile)
                .where(MarketDataFile.id.in_(group.superseded_ids))
                .values(data_role=SUPERSEDED_ROLE)
            )
            superseded_ids.extend(group.superseded_ids)
    session.flush()
    remaining = _count_duplicate_groups(session)
    return {
        "promoted_ids": promoted_ids,
        "superseded_ids": superseded_ids,
        "superseded_count": len(superseded_ids),
        "remaining_duplicate_groups": remaining,
    }


def write_duplicate_active_supersede_reports(result: dict[str, Any], *, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "duplicate_active_supersede_plan.csv"
    pd.DataFrame(result["plan_rows"]).to_csv(plan_path, index=False)
    summary_path = output_dir / "duplicate_active_supersede_summary.json"
    payload = {key: value for key, value in result.items() if key != "plan_rows"}
    summary_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return {"plan": plan_path, "summary": summary_path}


def _duplicate_primary_groups(session: Session) -> dict[tuple[str, str, str], list[MarketDataFile]]:
    rows = list(
        session.scalars(
            select(MarketDataFile).where(
                MarketDataFile.data_type == "bars",
                MarketDataFile.data_role.in_((ACTIVE_ROLE, SUPERSEDED_ROLE)),
                MarketDataFile.quality_status != "failed",
            )
        )
    )
    groups: dict[tuple[str, str, str], list[MarketDataFile]] = {}
    for row in rows:
        product = (row.instrument_symbol or "").strip().lower()
        contract = (row.contract_code or "").strip()
        period = (row.period or "").strip().lower()
        if not product or not contract or not period:
            continue
        key = (product, contract, period)
        groups.setdefault(key, []).append(row)
    return {key: items for key, items in groups.items() if len(items) > 1}


def _count_duplicate_groups(session: Session) -> int:
    rows = list(
        session.scalars(
            select(MarketDataFile).where(
                MarketDataFile.data_type == "bars",
                MarketDataFile.data_role == ACTIVE_ROLE,
                MarketDataFile.quality_status != "failed",
            )
        )
    )
    groups: dict[tuple[str, str, str], int] = {}
    for row in rows:
        key = (
            (row.instrument_symbol or "").strip().lower(),
            (row.contract_code or "").strip(),
            (row.period or "").strip().lower(),
        )
        groups[key] = groups.get(key, 0) + 1
    return sum(1 for count in groups.values() if count > 1)


def _pick_current(items: list[MarketDataFile]) -> MarketDataFile:
    def sort_key(item: MarketDataFile) -> tuple:
        end_time = item.end_time or datetime.min.replace(tzinfo=UTC)
        start_time = item.start_time or datetime.max.replace(tzinfo=UTC)
        # Widest historical coverage: latest end_time, then earliest start_time.
        return (end_time, -start_time.timestamp(), item.id or 0)

    return sorted(items, key=sort_key, reverse=True)[0]


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()
