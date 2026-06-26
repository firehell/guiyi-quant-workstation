from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.models.data_center import FuturesExFactor
from app.services.rqdata_ingest.db import as_date, as_decimal, row_payload, upsert_one
from app.services.rqdata_ingest.ingestors import DATA_VERSION, PROVIDER


DATE_FIELDS = ("date", "trade_date", "trading_date", "datetime", "index", "ex_date")


def _value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and not pd.isna(row[name]):
            return row[name]
    return None


def _contract(value: Any) -> str:
    return str(value or "").upper()


def _product_from_path(path: Path) -> str:
    for part in path.parts:
        if part.startswith("product="):
            return part.split("=", 1)[1]
    return path.stem.split("_", 1)[0]


def _raw_ex_factor_files(project_root: Path, products: list[str] | None) -> list[Path]:
    root = project_root / "data" / "raw" / "rqdata" / "futures_ex_factor"
    if not root.exists():
        return []
    allowed = {item.lower() for item in products} if products else None
    files = []
    for path in sorted(root.glob("product=*/*.parquet")):
        product = _product_from_path(path)
        if allowed is not None and product.lower() not in allowed:
            continue
        files.append(path)
    return files


def backfill_ex_factors_from_raw(
    session: Session,
    project_root: Path,
    *,
    products: list[str] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    files = _raw_ex_factor_files(project_root, products)
    if limit is not None:
        files = files[:limit]
    rows = 0
    for path in files:
        product = _product_from_path(path)
        raw = pd.read_parquet(path)
        frame = raw.where(pd.notna(raw), None)
        for record in frame.to_dict("records"):
            trade_date = as_date(_value(record, *DATE_FIELDS))
            if trade_date is None:
                continue
            rows += 1
            if dry_run:
                continue
            upsert_one(
                session,
                FuturesExFactor,
                {
                    "instrument_symbol": product,
                    "trade_date": trade_date,
                    "contract_code": _contract(_value(record, "contract", "order_book_id")) or None,
                    "provider": PROVIDER,
                    "data_version": DATA_VERSION,
                },
                {
                    "prev_close_spread": as_decimal(_value(record, "prev_close_spread", "ex_factor")),
                    "open_spread": as_decimal(_value(record, "open_spread")),
                    "prev_close_ratio": as_decimal(_value(record, "prev_close_ratio", "ex_cum_factor")),
                    "open_ratio": as_decimal(_value(record, "open_ratio")),
                    "raw_payload": row_payload(record),
                },
            )
    return rows, len(files)
