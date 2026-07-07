from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.services.rqdata_ingest.actual_contract_bars_pilot import (
    ActualContractBarsClient,
    ActualContractBarsGateError,
    ActualContractBarsQualityError,
    build_actual_contract_bars_dry_run_payload,
    plan_actual_contract_bars_pilot,
    run_actual_contract_bars_pilot_write,
)

DEFAULT_PERIODS = ("1m", "5m", "15m", "30m", "60m", "1d")
STAGE = "DATA-UNIVERSE-8_5G-ACTUAL-CONTRACT-BARS-BATCH"


def build_actual_contract_bars_batch_dry_run_payload(
    *,
    products: Iterable[str],
    trade_date: date,
    start_date: date,
    end_date: date,
    periods: tuple[str, ...],
    output_root: Path,
) -> dict[str, Any]:
    normalized_products = [_normalize_product(product) for product in products]
    return {
        "mode": "dry-run",
        "stage": STAGE,
        "provider": "rqdata",
        "trade_date": trade_date.isoformat(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "periods": list(periods),
        "products": normalized_products,
        "product_count": len(normalized_products),
        "output_root": str(output_root),
        "would_construct_rqdata_client": False,
        "would_open_database_session": False,
        "would_call_rqdata": False,
        "would_write_parquet": False,
        "would_write_manifest": False,
        "would_write_database": False,
        "would_register_primary": False,
        "would_send_wechat": False,
        "would_trigger_strategy": False,
        "would_run_backtest": False,
    }


def plan_actual_contract_bars_batch_product(
    *,
    session: Session,
    output_root: Path,
    product: str,
    trade_date: date,
    start_date: date,
    end_date: date,
    periods: tuple[str, ...],
) -> dict[str, Any]:
    return plan_actual_contract_bars_pilot(
        session=session,
        output_root=output_root,
        product=product,
        trade_date=trade_date,
        start_date=start_date,
        end_date=end_date,
        periods=periods,
    )


def run_actual_contract_bars_batch(
    *,
    session: Session,
    client: ActualContractBarsClient | None,
    output_root: Path,
    products: Iterable[str],
    trade_date: date,
    start_date: date,
    end_date: date,
    periods: tuple[str, ...],
    dry_run: bool = True,
    on_product_complete: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    normalized_products = [_normalize_product(product) for product in products]
    if dry_run:
        plans: list[dict[str, Any]] = []
        for product in normalized_products:
            plans.append(
                {
                    "product": product,
                    "plan": build_actual_contract_bars_dry_run_payload(
                        product=product,
                        trade_date=trade_date,
                        start_date=start_date,
                        end_date=end_date,
                        periods=periods,
                        output_root=output_root,
                    ),
                }
            )
        return {
            **build_actual_contract_bars_batch_dry_run_payload(
                products=normalized_products,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
                periods=periods,
                output_root=output_root,
            ),
            "plans": plans,
        }

    if client is None:
        raise RuntimeError("RQData client is required for batch write mode")

    results: dict[str, Any] = {}
    failures: dict[str, str] = {}
    for product in normalized_products:
        try:
            result = run_actual_contract_bars_pilot_write(
                session=session,
                client=client,
                output_root=output_root,
                product=product,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
                periods=periods,
            )
            results[product] = result
            if on_product_complete is not None:
                on_product_complete(product, result)
        except (ActualContractBarsGateError, ActualContractBarsQualityError, RuntimeError, ValueError) as exc:
            failures[product] = str(exc)
    return {
        "mode": "write",
        "stage": STAGE,
        "trade_date": trade_date.isoformat(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "periods": list(periods),
        "success_count": len(results),
        "failure_count": len(failures),
        "results": results,
        "failures": failures,
    }


def _normalize_product(product: str) -> str:
    return product.strip().lower()
