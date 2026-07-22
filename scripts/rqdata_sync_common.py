"""RQData 同步脚本的共享 CLI 骨架。

多数 ``scripts/rqdata_*_sync.py`` 薄封装依赖本模块：
- 将 ``services/quant-api`` 加入 ``sys.path``，以便 ``import app.*``
- 统一 argparse（``run`` 子命令、日期/品种/合约、dry-run、manifest 续跑）
- 从 DB 或文件选择品种/合约
- 通过 CSV manifest 做断点续跑与失败重试
- 创建 ``RqDataClient``

真实拉取与落盘逻辑在 ``app.services.rqdata_ingest``，本模块不实现 ingest 算法。
"""

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
    """品种代码统一小写，便于与 DB ``Instrument.symbol`` / ``Contract.product`` 比对。"""
    return symbol.lower()


def core_products_from_db(session) -> list[str]:
    """返回研究默认池中、且已在 DB ``Instrument`` 表存在的品种（保留原始大小写）。"""
    db_symbols = {_normalize_product_key(symbol) for symbol in session.scalars(select(Instrument.symbol))}
    return [product for product in DEFAULT_RESEARCH_PRODUCTS if _normalize_product_key(product) in db_symbols]


def base_parser(description: str) -> argparse.ArgumentParser:
    """构建各 sync 脚本共用的 argparse：必选 ``run`` 子命令 + 标准日期/范围/续跑开关。

    ``parser.run_parser`` 暴露 ``run`` 子解析器，便于个别脚本追加专用参数。
    """
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
    """ISO 日期字符串 ``YYYY-MM-DD`` → ``date``。"""
    return date.fromisoformat(value)


def products_from_file(path: str | Path) -> list[str]:
    """从品种列表文件读取产品代码（跳过空行与 ``#`` 注释行）。相对路径相对仓库根。"""
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = PROJECT_ROOT / file_path
    products: list[str] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        item = line.strip()
        if item and not item.startswith("#"):
            products.append(item)
    return products


def selected_products(
    session,
    explicit: list[str] | None,
    *,
    all_products: bool = False,
    limit: int | None = None,
) -> list[str]:
    """解析本次同步的品种列表。

    优先级：显式 ``--product`` > ``--all-products``（全库 Instrument）> 研究默认池 ∩ DB。
    """
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
    """解析本次同步的合约代码列表。

    若未显式传 ``--contract``，则按品种过滤 ``Contract`` 表；
    未指定品种且非 ``all_products`` 时，默认用研究池。
    """
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
    """打开 ``data/manifests/<name>.csv`` 断点续跑清单。"""
    return CsvManifest(PROJECT_ROOT / "data" / "manifests" / f"{name}.csv")


def run_with_manifest(args, manifest_name: str, keys: list[str], callback: Callable[[str], object]) -> None:
    """按 manifest 状态逐 key 执行 ``callback``。

    - ``--resume`` / ``--retry-failed``：由 ``CsvManifest.should_run`` 决定是否跳过
    - ``--dry-run``：只打印，不调用 callback、不改 manifest
    - 成功/失败写入 manifest；非 ``retry_failed`` 时遇错立即抛出
    - ``--limit``：限制本次实际执行（非 skip）的条数
    """
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
    """创建 RQData 客户端（凭据从环境加载，脚本侧禁止硬编码）。"""
    return RqDataClient()
