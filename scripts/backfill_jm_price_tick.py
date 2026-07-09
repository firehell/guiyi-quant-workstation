from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.data_center import FeeMarginRule, FuturesTradingParameter  # noqa: E402


def backfill_jm_price_tick(
    session: Session,
    *,
    product: str,
    contract: str | None = None,
    start_date: date,
    end_date: date,
    price_tick: Decimal,
    source: str,
    provider: str = "rqdata",
    apply: bool = False,
    expected_eligible_null: int | None = None,
) -> dict[str, Any]:
    """Backfill missing JM price_tick rows from an explicit audited source."""
    product_key = product.strip().lower()
    contract_code = _normalize_contract(contract)
    if product_key != "jm":
        raise ValueError("this controlled backfill only supports product=jm")
    if contract_code is not None and not contract_code.startswith("JM"):
        raise ValueError("contract-limited backfill only supports JM contracts")
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    if price_tick <= 0:
        raise ValueError("price_tick must be greater than zero")
    if not source.strip():
        raise ValueError("source is required")

    mode = "apply" if apply else "dry-run"
    result: dict[str, Any] = {
        "mode": mode,
        "product": product_key,
        "contract": contract_code,
        "provider": provider,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "price_tick": str(price_tick),
        "source": source,
        "expected_eligible_null": expected_eligible_null,
        "futures_trading_parameters": _table_counts(
            session,
            FuturesTradingParameter,
            FuturesTradingParameter.trade_date,
            product_key=product_key,
            contract_code=contract_code,
            provider=provider,
            start_date=start_date,
            end_date=end_date,
        ),
        "fee_margin_rules": _table_counts(
            session,
            FeeMarginRule,
            FeeMarginRule.effective_date,
            product_key=product_key,
            contract_code=contract_code,
            provider=provider,
            start_date=start_date,
            end_date=end_date,
        ),
    }
    _check_expected_eligible_null(result, expected_eligible_null)

    if apply:
        result["futures_trading_parameters"]["updated"] = _update_futures_trading_parameters(
            session,
            product_key=product_key,
            contract_code=contract_code,
            provider=provider,
            start_date=start_date,
            end_date=end_date,
            price_tick=price_tick,
            source=source,
        )
        result["fee_margin_rules"]["updated"] = _update_fee_margin_rules(
            session,
            product_key=product_key,
            contract_code=contract_code,
            provider=provider,
            start_date=start_date,
            end_date=end_date,
            price_tick=price_tick,
        )
        session.flush()
    else:
        result["futures_trading_parameters"]["updated"] = 0
        result["fee_margin_rules"]["updated"] = 0

    result["futures_trading_parameters"]["after_non_null"] = _non_null_count(
        session,
        FuturesTradingParameter,
        FuturesTradingParameter.trade_date,
        product_key=product_key,
        contract_code=contract_code,
        provider=provider,
        start_date=start_date,
        end_date=end_date,
    )
    result["fee_margin_rules"]["after_non_null"] = _non_null_count(
        session,
        FeeMarginRule,
        FeeMarginRule.effective_date,
        product_key=product_key,
        contract_code=contract_code,
        provider=provider,
        start_date=start_date,
        end_date=end_date,
    )
    return result


def _table_counts(
    session: Session,
    model: type,
    date_column: Any,
    *,
    product_key: str,
    contract_code: str | None,
    provider: str,
    start_date: date,
    end_date: date,
) -> dict[str, int]:
    total = _count(
        session,
        model,
        date_column,
        product_key=product_key,
        contract_code=contract_code,
        provider=provider,
        start_date=start_date,
        end_date=end_date,
    )
    before_non_null = _non_null_count(
        session,
        model,
        date_column,
        product_key=product_key,
        contract_code=contract_code,
        provider=provider,
        start_date=start_date,
        end_date=end_date,
    )
    eligible_null = _null_count(
        session,
        model,
        date_column,
        product_key=product_key,
        contract_code=contract_code,
        provider=provider,
        start_date=start_date,
        end_date=end_date,
    )
    return {
        "total": total,
        "before_non_null": before_non_null,
        "eligible_null": eligible_null,
    }


def _count(
    session: Session,
    model: type,
    date_column: Any,
    *,
    product_key: str,
    contract_code: str | None,
    provider: str,
    start_date: date,
    end_date: date,
) -> int:
    query = _base_scope_query(
        model,
        date_column,
        product_key=product_key,
        contract_code=contract_code,
        provider=provider,
        start_date=start_date,
        end_date=end_date,
    )
    return int(
        session.scalar(
            query.with_only_columns(func.count()).order_by(None)
        )
        or 0
    )


def _non_null_count(
    session: Session,
    model: type,
    date_column: Any,
    *,
    product_key: str,
    contract_code: str | None,
    provider: str,
    start_date: date,
    end_date: date,
) -> int:
    query = _base_scope_query(
        model,
        date_column,
        product_key=product_key,
        contract_code=contract_code,
        provider=provider,
        start_date=start_date,
        end_date=end_date,
    ).where(model.price_tick.is_not(None))
    return int(
        session.scalar(
            query.with_only_columns(func.count()).order_by(None)
        )
        or 0
    )


def _null_count(
    session: Session,
    model: type,
    date_column: Any,
    *,
    product_key: str,
    contract_code: str | None,
    provider: str,
    start_date: date,
    end_date: date,
) -> int:
    query = _base_scope_query(
        model,
        date_column,
        product_key=product_key,
        contract_code=contract_code,
        provider=provider,
        start_date=start_date,
        end_date=end_date,
    ).where(model.price_tick.is_(None))
    return int(
        session.scalar(
            query.with_only_columns(func.count()).order_by(None)
        )
        or 0
    )


def _base_scope_query(
    model: type,
    date_column: Any,
    *,
    product_key: str,
    contract_code: str | None,
    provider: str,
    start_date: date,
    end_date: date,
):
    query = select(model).where(
        func.lower(model.instrument_symbol) == product_key,
        model.provider == provider,
        date_column.between(start_date, end_date),
    )
    if contract_code is not None:
        query = query.where(model.contract_code == contract_code)
    return query


def _check_expected_eligible_null(result: dict[str, Any], expected_eligible_null: int | None) -> None:
    if expected_eligible_null is None:
        return
    actual = {
        "futures_trading_parameters": result["futures_trading_parameters"]["eligible_null"],
        "fee_margin_rules": result["fee_margin_rules"]["eligible_null"],
    }
    mismatched = {table: value for table, value in actual.items() if value != expected_eligible_null}
    if mismatched:
        raise ValueError(f"eligible_null guard failed: expected={expected_eligible_null}, actual={actual}")


def _update_futures_trading_parameters(
    session: Session,
    *,
    product_key: str,
    contract_code: str | None,
    provider: str,
    start_date: date,
    end_date: date,
    price_tick: Decimal,
    source: str,
) -> int:
    rows = list(
        session.scalars(
            _base_scope_query(
                FuturesTradingParameter,
                FuturesTradingParameter.trade_date,
                product_key=product_key,
                contract_code=contract_code,
                provider=provider,
                start_date=start_date,
                end_date=end_date,
            ).where(FuturesTradingParameter.price_tick.is_(None))
        )
    )
    for row in rows:
        row.price_tick = price_tick
        payload = dict(row.raw_payload or {})
        payload["price_tick_backfill"] = {
            "stage": "13-F",
            "source": source,
            "product": product_key,
            "contract": contract_code,
            "provider": provider,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "price_tick": str(price_tick),
        }
        row.raw_payload = payload
        flag_modified(row, "raw_payload")
    return len(rows)


def _update_fee_margin_rules(
    session: Session,
    *,
    product_key: str,
    contract_code: str | None,
    provider: str,
    start_date: date,
    end_date: date,
    price_tick: Decimal,
) -> int:
    rows = list(
        session.scalars(
            _base_scope_query(
                FeeMarginRule,
                FeeMarginRule.effective_date,
                product_key=product_key,
                contract_code=contract_code,
                provider=provider,
                start_date=start_date,
                end_date=end_date,
            ).where(FeeMarginRule.price_tick.is_(None))
        )
    )
    for row in rows:
        row.price_tick = price_tick
    return len(rows)


def _normalize_contract(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    return normalized or None


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill missing JM price_tick values from an audited contract-spec source.")
    parser.add_argument("--product", default="jm")
    parser.add_argument("--contract", help="Limit repair to one actual contract, e.g. JM2609.")
    parser.add_argument("--start-date", type=_parse_date, required=True)
    parser.add_argument("--end-date", type=_parse_date, required=True)
    parser.add_argument("--price-tick", type=Decimal, required=True)
    parser.add_argument("--source", required=True, help="Audited source identifier, e.g. dce_notice_2015_95")
    parser.add_argument("--provider", default="rqdata")
    parser.add_argument("--expected-eligible-null", type=int, help="Fail unless both repaired tables have this exact null count.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Write missing price_tick values.")
    mode.add_argument("--dry-run", action="store_true", help="Only print counts; this is the default.")
    args = parser.parse_args()

    with SessionLocal() as session:
        result = backfill_jm_price_tick(
            session,
            product=args.product,
            contract=args.contract,
            start_date=args.start_date,
            end_date=args.end_date,
            price_tick=args.price_tick,
            source=args.source,
            provider=args.provider,
            apply=args.apply,
            expected_eligible_null=args.expected_eligible_null,
        )
        if args.apply:
            session.commit()
        else:
            session.rollback()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
