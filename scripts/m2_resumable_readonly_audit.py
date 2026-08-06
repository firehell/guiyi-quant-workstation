#!/usr/bin/env python3
"""Resumable, read-only M2 audit runner with dataset-level observability.

The audit never constructs RQData or writer dependencies.  State is atomically
updated before and after every physical verification and MarketDataService probe;
the watchdog records the active dataset and terminates a stalled read so a later
invocation can resume at the next product.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from threading import Event, Thread
import time
from typing import Any

from sqlalchemy import text

from app.data_core.catalog import HistoricalCatalog
from app.data_core.contracts import BarQuery, DatasetKey
from app.data_core.product_retirement import load_active_products
from app.db.session import SessionLocal
from app.services.canonical_market_data import build_canonical_reader
from app.services.data_operations.contracts import AuditRequest, AuditScope
from app.services.data_operations.m2_architecture_audit import build_m2_audit_checker
from app.services.market_data_service import MarketDataService


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _dataset(key: DatasetKey) -> dict[str, str]:
    return {
        "kind": key.dataset_kind.value,
        "symbol": key.symbol,
        "contract_or_series": key.contract_or_series,
        "frequency": key.frequency.value,
    }


def _write_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = _now()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.timeout_seconds < 1:
        raise SystemExit("timeout-seconds must be positive")
    args.state.parent.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = (
        json.loads(args.state.read_text()) if args.state.exists() else {}
    )
    products = tuple(load_active_products(Path("data/universe/active_products.txt")))
    state.setdefault("scope", "m2")
    state.setdefault("products", list(products))
    state.setdefault("completed_products", [])
    state.setdefault("results", {})
    state["status"] = "running"
    _write_state(args.state, state)

    stop = Event()
    last_progress = time.monotonic()

    def progress(key: DatasetKey, stage: str) -> None:
        nonlocal last_progress
        last_progress = time.monotonic()
        state["active"] = {"dataset": _dataset(key), "stage": stage, "at": _now()}
        _write_state(args.state, state)

    def watchdog() -> None:
        while not stop.wait(1):
            elapsed = time.monotonic() - last_progress
            if elapsed > args.timeout_seconds:
                state["status"] = "timeout"
                state["timeout"] = {
                    "seconds": args.timeout_seconds,
                    "active": state.get("active"),
                    "at": _now(),
                }
                _write_state(args.state, state)
                os._exit(124)

    Thread(target=watchdog, daemon=True).start()
    try:
        for symbol in products:
            if symbol in state["completed_products"]:
                continue
            with SessionLocal() as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                reader = build_canonical_reader(session)
                market_data = MarketDataService(session, canonical_reader=reader)

                def verify(key: DatasetKey, partition: object) -> object:
                    progress(key, "physical_metadata_checksum_schema_row_count")
                    result = reader.verify_partition(key, partition)
                    progress(key, "physical_verified")
                    return result

                def readable(key: DatasetKey, start: datetime, end: datetime) -> bool:
                    progress(key, "market_data_sample")
                    result = market_data.get_bars(
                        BarQuery(
                            dataset_kind=key.dataset_kind,
                            symbol=key.symbol,
                            contract_or_series=key.contract_or_series,
                            frequency=key.frequency,
                            start=start,
                            end=end,
                        )
                    )
                    progress(key, "market_data_sample_verified")
                    return bool(result.bars)

                checker = build_m2_audit_checker(
                    catalog=HistoricalCatalog(session),
                    verify_partition=verify,
                    market_data_readable=readable,
                )
                findings = checker(AuditRequest(scope=AuditScope.M2, symbols=(symbol,)))
                session.rollback()
            state["completed_products"].append(symbol)
            state["results"][symbol] = {
                "summary": dict(getattr(checker, "m2_summary", {})),
                "finding_codes": sorted({finding.code for finding in findings}),
                "completed_at": _now(),
            }
            state.pop("active", None)
            _write_state(args.state, state)
    finally:
        stop.set()
    state["status"] = "completed"
    _write_state(args.state, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
