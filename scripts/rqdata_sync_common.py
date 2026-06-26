from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
import argparse
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import select  # noqa: E402

from app.models.data_center import Contract, Instrument  # noqa: E402
from app.services.rqdata_ingest.client import RqDataClient  # noqa: E402
from app.services.rqdata_ingest.manifest import CsvManifest  # noqa: E402


DEFAULT_START = date(2005, 1, 1)
DEFAULT_END = date(2026, 6, 24)
DEFAULT_MARKET_SAMPLE_START = date(2010, 1, 4)

# 黑色 + 化工 + 能源 + 有色；保留 RQData 原始大小写（郑商所大写）
DEFAULT_RESEARCH_PRODUCTS = [
    "rb",
    "hc",
    "i",
    "j",
    "jm",
    "TA",
    "MA",
    "EG",
    "l",
    "pp",
    "v",
    "SA",
    "FG",
    "sc",
    "fu",
    "bu",
    "pg",
    "cu",
    "al",
    "zn",
    "pb",
    "ni",
    "sn",
    "au",
    "ag",
]

DEFAULT_SAMPLE_PRODUCTS = DEFAULT_RESEARCH_PRODUCTS


def _normalize_product_key(symbol: str) -> str:
    return symbol.lower()


def core_products_from_db(session) -> list[str]:
    db_symbols = {_normalize_product_key(symbol) for symbol in session.scalars(select(Instrument.symbol))}
    return [product for product in DEFAULT_RESEARCH_PRODUCTS if _normalize_product_key(product) in db_symbols]


def base_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--start-date", type=parse_date, default=DEFAULT_START)
    run.add_argument("--end-date", type=parse_date, default=DEFAULT_END)
    run.add_argument("--product", action="append", dest="products")
    run.add_argument("--contract", action="append", dest="contracts")
    run.add_argument("--all-products", action="store_true", help="sync all instruments/contracts in DB instead of core research pool")
    run.add_argument("--limit", type=int)
    run.add_argument("--resume", action="store_true")
    run.add_argument("--retry-failed", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    parser.run_parser = run  # type: ignore[attr-defined]
    return parser


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def selected_products(
    session,
    explicit: list[str] | None,
    *,
    all_products: bool = False,
    limit: int | None = None,
) -> list[str]:
    if explicit:
        products = explicit
    elif all_products:
        products = list(session.scalars(select(Instrument.symbol).order_by(Instrument.symbol)))
    else:
        products = core_products_from_db(session)
    if limit is not None:
        return products[:limit]
    return products


def selected_contracts(
    session,
    explicit: list[str] | None,
    products: list[str] | None,
    *,
    all_products: bool = False,
    limit: int | None = None,
) -> list[str]:
    if explicit:
        contracts = explicit
    else:
        product_filter = products
        if product_filter is None and not all_products:
            product_filter = core_products_from_db(session)
        query = select(Contract.contract_code).order_by(Contract.contract_code)
        if product_filter:
            query = query.where(Contract.product.in_([_normalize_product_key(item) for item in product_filter]))
        contracts = list(session.scalars(query))
    if limit is not None:
        return contracts[:limit]
    return contracts


def manifest_for(name: str) -> CsvManifest:
    return CsvManifest(PROJECT_ROOT / "data" / "manifests" / f"{name}.csv")


def run_with_manifest(args, manifest_name: str, keys: list[str], callback: Callable[[str], object]) -> None:
    manifest = manifest_for(manifest_name)
    executed = 0
    for key in keys:
        if args.limit is not None and executed >= args.limit:
            break
        if not manifest.should_run(key, resume=args.resume, retry_failed=args.retry_failed):
            print(f"skip {key}")
            continue
        if args.dry_run:
            print(f"dry-run {key}")
            continue
        try:
            result = callback(key)
            manifest.mark(key, "success")
            print(f"success {key}: {result}")
        except Exception as exc:
            manifest.mark(key, "failed", str(exc))
            print(f"failed {key}: {exc}")
            if not args.retry_failed:
                raise
        executed += 1


def rq_client() -> RqDataClient:
    return RqDataClient()
