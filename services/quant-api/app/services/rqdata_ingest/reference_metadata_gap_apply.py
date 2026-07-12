from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.data_center import FuturesContinuousContractMap, FuturesContractUniverse
from app.services.rqdata_ingest.db import as_date, row_payload, upsert_one


PROVIDER = "rqdata"
DATA_VERSION = "rqdata_structured_v1"
DERIVED_CONTINUOUS_DATA_VERSION = "rqdata_contract_universe_derived_v1"
DEFAULT_CONTINUOUS_TYPES = ["front_month", "next_month"]
CONTINUOUS_SORT_ORDER_MAP = {"front_month": 0, "next_month": 1}
SUPPORTED_DATASETS = {"contract_universe", "continuous_contract_map"}


class ReferenceMetadataApplyConfirmationError(RuntimeError):
    pass


def run_reference_metadata_gap_apply(
    *,
    session: Session,
    client: Any,
    candidate_rows_csv: Path,
    output_dir: Path,
    apply: bool,
    confirm_metadata_only: bool,
    batch_id: str | None = None,
    dataset: str | None = None,
    year: int | None = None,
    product: str | None = None,
    limit: int | None = None,
    continuous_types: list[str] | None = None,
    derive_continuous_from_universe: bool = False,
) -> dict[str, Any]:
    if apply and not confirm_metadata_only:
        raise ReferenceMetadataApplyConfirmationError("--apply requires --confirm-metadata-only")

    candidates = _filter_candidates(
        _read_candidates(candidate_rows_csv),
        batch_id=batch_id,
        dataset=dataset,
        year=year,
        product=product,
        limit=limit,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_rows: list[dict[str, Any]] = []
    type_list = continuous_types or DEFAULT_CONTINUOUS_TYPES

    for candidate in candidates:
        if apply:
            row = _apply_candidate(
                session=session,
                client=client,
                candidate=candidate,
                continuous_types=type_list,
                derive_continuous_from_universe=derive_continuous_from_universe,
            )
        else:
            row = _planned_candidate(session=session, candidate=candidate)
        ledger_rows.append(row)

    ledger_path = output_dir / "reference_metadata_gap_apply_ledger.csv"
    summary_path = output_dir / "REFERENCE_METADATA_GAP_APPLY.md"
    pd.DataFrame(ledger_rows).to_csv(ledger_path, index=False, lineterminator="\n")
    result = {
        "apply": apply,
        "candidate_count": len(candidates),
        "status_counts": dict(sorted(Counter(row["status"] for row in ledger_rows).items())),
        "ledger_path": str(ledger_path),
        "summary_path": str(summary_path),
        "writes_database": bool(apply),
        "writes_parquet": False,
        "writes_market_data_files": False,
        "writes_quality_status": False,
        "calls_rqdata": any(row.get("calls_rqdata", False) for row in ledger_rows),
    }
    summary_path.write_text(_render_summary(result), encoding="utf-8")
    return result


def _planned_candidate(*, session: Session, candidate: dict[str, Any]) -> dict[str, Any]:
    before_count = _count_existing(session, candidate)
    return _ledger_base(candidate) | {
        "status": "planned",
        "before_count": before_count,
        "after_count": before_count,
        "rows_fetched": 0,
        "rows_upsert_attempted": 0,
        "calls_rqdata": False,
        "error_type": "",
        "error_message": "",
    }


def _apply_candidate(
    *,
    session: Session,
    client: Any,
    candidate: dict[str, Any],
    continuous_types: list[str],
    derive_continuous_from_universe: bool,
) -> dict[str, Any]:
    before_count = _count_existing(session, candidate)
    base = _ledger_base(candidate) | {"before_count": before_count}
    calls_rqdata = _candidate_calls_rqdata(candidate, derive_continuous_from_universe=derive_continuous_from_universe)
    try:
        dataset = candidate["dataset"]
        if dataset == "contract_universe":
            rows = _apply_contract_universe(session=session, client=client, candidate=candidate)
        elif dataset == "continuous_contract_map":
            if derive_continuous_from_universe:
                rows = _derive_continuous_contract_map_from_universe(
                    session=session,
                    candidate=candidate,
                    continuous_types=continuous_types,
                )
            else:
                rows = _apply_continuous_contract_map(session=session, client=client, candidate=candidate, continuous_types=continuous_types)
        else:
            raise ValueError(f"unsupported dataset: {dataset}")
        session.commit()
        after_count = _count_existing(session, candidate)
        if rows == 0 and after_count == before_count:
            return base | {
                "status": "no_data",
                "after_count": after_count,
                "rows_fetched": rows,
                "rows_upsert_attempted": 0,
                "calls_rqdata": calls_rqdata,
                "error_type": "NoRowsFetched",
                "error_message": f"{candidate['dataset']} fetched zero rows for product={candidate['product']} year={candidate['year']}",
            }
        return base | {
            "status": "success",
            "after_count": after_count,
            "rows_fetched": rows,
            "rows_upsert_attempted": rows,
            "calls_rqdata": calls_rqdata,
            "error_type": "",
            "error_message": "",
        }
    except Exception as exc:
        session.rollback()
        return base | {
            "status": "failed",
            "after_count": _count_existing(session, candidate),
            "rows_fetched": 0,
            "rows_upsert_attempted": 0,
            "calls_rqdata": calls_rqdata,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }


def _apply_contract_universe(*, session: Session, client: Any, candidate: dict[str, Any]) -> int:
    product = candidate["product"]
    start_date = candidate["candidate_start_date"]
    end_date = candidate["candidate_end_date"]
    rows = 0
    for trade_date in client.trading_dates(start_date, end_date):
        frame = _clean_frame(client.listed_contracts(product, trade_date))
        for sort_order, record in enumerate(frame.to_dict("records")):
            contract_code = _contract_from_record(record)
            if not contract_code:
                continue
            upsert_one(
                session,
                FuturesContractUniverse,
                {
                    "instrument_symbol": product,
                    "trade_date": trade_date,
                    "contract_code": contract_code,
                    "provider": PROVIDER,
                    "data_version": DATA_VERSION,
                },
                {"sort_order": sort_order, "raw_payload": row_payload(record)},
            )
            rows += 1
    return rows


def _apply_continuous_contract_map(
    *,
    session: Session,
    client: Any,
    candidate: dict[str, Any],
    continuous_types: list[str],
) -> int:
    product = candidate["product"]
    start_date = candidate["candidate_start_date"]
    end_date = candidate["candidate_end_date"]
    rows = 0
    for continuous_type in continuous_types:
        frame = _clean_frame(client.continuous_contract_by_type(product, start_date, end_date, continuous_type))
        for record in frame.to_dict("records"):
            trade_date = as_date(_value(record, "date", "trade_date", "trading_date", "datetime", "index"))
            contract_code = _contract_from_record(record, continuous_type)
            if trade_date is None or not contract_code:
                continue
            upsert_one(
                session,
                FuturesContinuousContractMap,
                {
                    "instrument_symbol": product,
                    "trade_date": trade_date,
                    "continuous_type": continuous_type,
                    "provider": PROVIDER,
                    "data_version": DATA_VERSION,
                },
                {"contract_code": contract_code, "raw_payload": row_payload(record)},
            )
            rows += 1
    return rows


def _derive_continuous_contract_map_from_universe(
    *,
    session: Session,
    candidate: dict[str, Any],
    continuous_types: list[str],
) -> int:
    product = candidate["product"]
    start_date = candidate["candidate_start_date"]
    end_date = candidate["candidate_end_date"]
    selected_orders = {
        CONTINUOUS_SORT_ORDER_MAP[continuous_type]: continuous_type
        for continuous_type in continuous_types
        if continuous_type in CONTINUOUS_SORT_ORDER_MAP
    }
    if not selected_orders:
        return 0

    rows = session.scalars(
        select(FuturesContractUniverse)
        .where(
            FuturesContractUniverse.instrument_symbol == product,
            FuturesContractUniverse.trade_date >= start_date,
            FuturesContractUniverse.trade_date <= end_date,
            FuturesContractUniverse.provider == PROVIDER,
            FuturesContractUniverse.data_version == DATA_VERSION,
            FuturesContractUniverse.sort_order.in_(selected_orders.keys()),
        )
        .order_by(FuturesContractUniverse.trade_date, FuturesContractUniverse.sort_order)
    ).all()
    for row in rows:
        continuous_type = selected_orders.get(row.sort_order)
        if continuous_type is None:
            continue
        upsert_one(
            session,
            FuturesContinuousContractMap,
            {
                "instrument_symbol": product,
                "trade_date": row.trade_date,
                "continuous_type": continuous_type,
                "provider": PROVIDER,
                "data_version": DERIVED_CONTINUOUS_DATA_VERSION,
            },
            {
                "contract_code": row.contract_code,
                "raw_payload": {
                    "source": "futures_contract_universe",
                    "source_provider": row.provider,
                    "source_data_version": row.data_version,
                    "source_sort_order": row.sort_order,
                    "source_contract_code": row.contract_code,
                },
            },
        )
    return len(rows)


def _candidate_calls_rqdata(candidate: dict[str, Any], *, derive_continuous_from_universe: bool) -> bool:
    return candidate["dataset"] == "contract_universe" or (
        candidate["dataset"] == "continuous_contract_map" and not derive_continuous_from_universe
    )


def _count_existing(session: Session, candidate: dict[str, Any]) -> int:
    product = candidate["product"]
    start_date = candidate["candidate_start_date"]
    end_date = candidate["candidate_end_date"]
    if candidate["dataset"] == "contract_universe":
        return int(
            session.scalar(
                select(func.count())
                .select_from(FuturesContractUniverse)
                .where(
                    FuturesContractUniverse.instrument_symbol == product,
                    FuturesContractUniverse.trade_date >= start_date,
                    FuturesContractUniverse.trade_date <= end_date,
                    FuturesContractUniverse.provider == PROVIDER,
                )
            )
            or 0
        )
    return int(
        session.scalar(
            select(func.count())
            .select_from(FuturesContinuousContractMap)
            .where(
                FuturesContinuousContractMap.instrument_symbol == product,
                FuturesContinuousContractMap.trade_date >= start_date,
                FuturesContinuousContractMap.trade_date <= end_date,
                FuturesContinuousContractMap.provider == PROVIDER,
            )
        )
        or 0
    )


def _read_candidates(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    records = pd.read_csv(path, dtype=str).fillna("").to_dict("records")
    candidates = []
    for row in records:
        dataset = _clean(row.get("dataset"))
        if dataset not in SUPPORTED_DATASETS:
            continue
        candidates.append(
            {
                "classification": _clean(row.get("classification")),
                "dataset": dataset,
                "target_table": _clean(row.get("target_table")),
                "product": _clean(row.get("product")).lower(),
                "year": int(_clean(row.get("year"))),
                "candidate_start_date": date.fromisoformat(_clean(row.get("candidate_start_date"))),
                "candidate_end_date": date.fromisoformat(_clean(row.get("candidate_end_date"))),
                "apply_order": int(_clean(row.get("apply_order")) or 0),
            }
        )
    return sorted(candidates, key=lambda item: (item["apply_order"], item["dataset"], item["product"]))


def _filter_candidates(
    candidates: list[dict[str, Any]],
    *,
    batch_id: str | None,
    dataset: str | None,
    year: int | None,
    product: str | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    selected = candidates
    if batch_id:
        parts = batch_id.split("_")
        if len(parts) < 4:
            raise ValueError(f"invalid batch_id: {batch_id}")
        dataset = "_".join(parts[2:-1])
        year = int(parts[-1])
    if dataset:
        selected = [row for row in selected if row["dataset"] == dataset]
    if year is not None:
        selected = [row for row in selected if row["year"] == year]
    if product:
        selected = [row for row in selected if row["product"] == product.lower()]
    if limit is not None:
        selected = selected[:limit]
    return selected


def _ledger_base(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "classification": candidate["classification"],
        "dataset": candidate["dataset"],
        "target_table": candidate["target_table"],
        "product": candidate["product"],
        "year": candidate["year"],
        "candidate_start_date": candidate["candidate_start_date"],
        "candidate_end_date": candidate["candidate_end_date"],
        "writes_parquet": False,
        "writes_market_data_files": False,
        "writes_quality_status": False,
    }


def _render_summary(result: dict[str, Any]) -> str:
    lines = [
        "# Reference Metadata Gap Apply",
        "",
        f"- apply: {result['apply']}",
        f"- candidate_count: {result['candidate_count']}",
        f"- status_counts: {result['status_counts']}",
        f"- writes_database: {result['writes_database']}",
        "- writes_parquet: False",
        "- writes_market_data_files: False",
        "- writes_quality_status: False",
        f"- calls_rqdata: {result['calls_rqdata']}",
        f"- ledger: {result['ledger_path']}",
    ]
    return "\n".join(lines) + "\n"


def _clean_frame(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    return df.copy().where(pd.notna(df), None)


def _contract_from_record(record: dict[str, Any], *names: str) -> str:
    value = _value(record, *names, "contract", "order_book_id", "dominant", "symbol")
    if value is None:
        for item in record.values():
            if isinstance(item, str) and item:
                value = item
                break
    return str(value or "").upper()


def _value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and not pd.isna(row[name]):
            return row[name]
    return None


def _clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()
