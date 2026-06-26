from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import MainContractMap
from app.services.tqsdk_ingest.products import product_spec


def build_contract_download_plan(
    session: Session,
    *,
    products: list[str],
    start_date: date,
    end_date: date,
    ranks: list[int],
    buffer_days: int = 10,
) -> pd.DataFrame:
    normalized = [product_spec(product).product for product in products]
    query = select(MainContractMap).where(
        MainContractMap.instrument_symbol.in_(normalized),
        MainContractMap.trade_date >= start_date,
        MainContractMap.trade_date <= end_date,
        MainContractMap.rank.in_(ranks),
    )
    rows = [row for row in session.scalars(query)]
    if not rows:
        return pd.DataFrame(
            columns=[
                "contract_code",
                "exchange",
                "product",
                "first_trading_day_in_mapping",
                "last_trading_day_in_mapping",
                "download_start",
                "download_end",
                "rank",
                "source_mapping_rule",
                "source_symbol",
                "status",
            ]
        )

    records: dict[tuple[str, str, int, str], list[MainContractMap]] = {}
    for row in rows:
        records.setdefault((row.instrument_symbol, row.contract_code, row.rank, row.rule), []).append(row)

    output = []
    for (product, contract, rank, rule), items in sorted(records.items()):
        spec = product_spec(product)
        first_day = min(item.trade_date for item in items)
        last_day = max(item.trade_date for item in items)
        contract_code = normalize_contract_symbol(contract, spec.exchange, spec.product)
        source_symbol = tqsdk_download_symbol(contract_code, spec.exchange, spec.product)
        output.append(
            {
                "contract_code": contract_code,
                "exchange": spec.exchange,
                "product": spec.product,
                "first_trading_day_in_mapping": first_day.isoformat(),
                "last_trading_day_in_mapping": last_day.isoformat(),
                "download_start": (first_day - timedelta(days=buffer_days)).isoformat(),
                "download_end": (last_day + timedelta(days=buffer_days)).isoformat(),
                "rank": rank,
                "source_mapping_rule": rule,
                "source_symbol": source_symbol,
                "status": "pending",
            }
        )
    return pd.DataFrame(output)


def normalize_contract_symbol(contract: str, exchange: str, product: str) -> str:
    if "." in contract:
        return contract
    suffix = "".join(ch for ch in contract if ch.isdigit())
    if exchange == "CZCE":
        product_code = product.upper()
    else:
        product_code = product.lower()
    return f"{exchange}.{product_code}{suffix}"


def tqsdk_download_symbol(canonical: str, exchange: str, product: str) -> str:
    if exchange != "CZCE":
        return canonical
    return czce_to_tqsdk_symbol(canonical, product)


def czce_to_tqsdk_symbol(canonical: str, product: str) -> str:
    exchange, rest = canonical.split(".", 1)
    product_code = product.upper()
    digits = "".join(ch for ch in rest if ch.isdigit())
    if len(digits) == 4:
        year = 2000 + int(digits[:2])
        month = int(digits[2:])
        return f"{exchange}.{product_code}{year % 10}{month:02d}"
    return canonical
