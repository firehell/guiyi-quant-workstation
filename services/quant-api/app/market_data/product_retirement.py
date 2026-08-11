"""退役品种精确拦截与 Catalog/Canonical 清退。

退役名单来自 ``data/universe/retired_products.txt``，与 active universe 互斥。
匹配规则仅为 normalize 后的精确成员，禁止前缀/模糊匹配。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.env import PROJECT_ROOT
from app.models import (
    Contract,
    Instrument,
    MainContractMap,
    MarketDataset,
    MarketPartition,
    TradingSession,
)

_RETIRED_PATH = PROJECT_ROOT / "data/universe/retired_products.txt"
_EXPECTED_RETIRED_COUNT = 9


class ProductRetiredError(ValueError):
    """公开错误：请求命中已退役品种。"""

    code = "PRODUCT_RETIRED"


def normalize_symbol(symbol: str) -> str:
    """品种代码规范化：strip + lower。"""
    return str(symbol or "").strip().lower()


def load_retired_products(path: Path | None = None) -> frozenset[str]:
    """加载退役名单并校验恰好 9 个唯一码。"""
    source = path or _RETIRED_PATH
    products = tuple(
        normalize_symbol(item)
        for item in source.read_text(encoding="utf-8").splitlines()
        if item.strip()
    )
    unique = frozenset(products)
    if len(products) != _EXPECTED_RETIRED_COUNT or len(unique) != _EXPECTED_RETIRED_COUNT:
        raise ValueError("RETIRED_UNIVERSE_INVALID")
    return unique


def is_retired(symbol: str, retired: frozenset[str] | None = None) -> bool:
    """精确成员判断；默认读取退役文件。"""
    codes = retired if retired is not None else load_retired_products()
    return normalize_symbol(symbol) in codes


def assert_not_retired(
    *symbols: str,
    retired: frozenset[str] | None = None,
) -> None:
    """任一 symbol 退役则抛 ``ProductRetiredError``。"""
    codes = retired if retired is not None else load_retired_products()
    for symbol in symbols:
        if normalize_symbol(symbol) in codes:
            raise ProductRetiredError("PRODUCT_RETIRED")


def assert_products_not_retired(
    products: tuple[str, ...],
    *,
    retired: frozenset[str] | None = None,
) -> None:
    """批量品种硬拦截。"""
    if products:
        assert_not_retired(*products, retired=retired)


@dataclass(frozen=True, slots=True)
class RetirementCounts:
    """退役品种在各表与 Canonical 路径上的计数。"""

    market_partitions: int
    market_datasets: int
    main_contract_map: int
    trading_sessions: int
    contracts: int
    instruments: int
    canonical_path_count: int

    def as_dict(self) -> dict[str, int]:
        return {
            "market_partitions": self.market_partitions,
            "market_datasets": self.market_datasets,
            "main_contract_map": self.main_contract_map,
            "trading_sessions": self.trading_sessions,
            "contracts": self.contracts,
            "instruments": self.instruments,
            "canonical_path_count": self.canonical_path_count,
        }

    @property
    def total(self) -> int:
        return (
            self.market_partitions
            + self.market_datasets
            + self.main_contract_map
            + self.trading_sessions
            + self.contracts
            + self.instruments
            + self.canonical_path_count
        )


@dataclass(frozen=True, slots=True)
class RetirementResult:
    """``retire-products`` 统一结果。"""

    action: str
    status: str
    apply: bool
    products: tuple[str, ...]
    inventory: RetirementCounts
    residual: RetirementCounts
    deleted_canonical_dirs: int

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "action": self.action,
            "status": self.status,
            "apply": self.apply,
            "products": list(self.products),
            "inventory": self.inventory.as_dict(),
            "residual": self.residual.as_dict(),
            "deleted_canonical_dirs": self.deleted_canonical_dirs,
        }


def inventory_retirement(
    session: Session,
    canonical_root: Path,
    *,
    products: frozenset[str] | None = None,
) -> RetirementCounts:
    """盘点退役品种的 DB 行与 Canonical 路径数（只读）。"""
    codes = tuple(sorted(products if products is not None else load_retired_products()))
    dataset_ids = list(
        session.scalars(select(MarketDataset.id).where(MarketDataset.symbol.in_(codes)))
    )
    partition_count = 0
    if dataset_ids:
        partition_count = int(
            session.scalar(
                select(func.count())
                .select_from(MarketPartition)
                .where(MarketPartition.dataset_id.in_(dataset_ids))
            )
            or 0
        )
    return RetirementCounts(
        market_partitions=partition_count,
        market_datasets=int(
            session.scalar(
                select(func.count())
                .select_from(MarketDataset)
                .where(MarketDataset.symbol.in_(codes))
            )
            or 0
        ),
        main_contract_map=int(
            session.scalar(
                select(func.count())
                .select_from(MainContractMap)
                .where(MainContractMap.symbol.in_(codes))
            )
            or 0
        ),
        trading_sessions=int(
            session.scalar(
                select(func.count())
                .select_from(TradingSession)
                .where(TradingSession.instrument_symbol.in_(codes))
            )
            or 0
        ),
        contracts=int(
            session.scalar(
                select(func.count())
                .select_from(Contract)
                .where(Contract.instrument_symbol.in_(codes))
            )
            or 0
        ),
        instruments=int(
            session.scalar(
                select(func.count())
                .select_from(Instrument)
                .where(Instrument.symbol.in_(codes))
            )
            or 0
        ),
        canonical_path_count=_count_canonical_paths(canonical_root, frozenset(codes)),
    )


def apply_retirement(
    session: Session,
    canonical_root: Path,
    *,
    products: frozenset[str] | None = None,
) -> RetirementResult:
    """按依赖序硬删 DB 行并删除 Canonical 下退役 symbol 目录。"""
    codes_set = products if products is not None else load_retired_products()
    codes = tuple(sorted(codes_set))
    before = inventory_retirement(session, canonical_root, products=codes_set)

    dataset_ids = list(
        session.scalars(select(MarketDataset.id).where(MarketDataset.symbol.in_(codes)))
    )
    if dataset_ids:
        session.execute(
            delete(MarketPartition).where(MarketPartition.dataset_id.in_(dataset_ids))
        )
    session.execute(delete(MarketDataset).where(MarketDataset.symbol.in_(codes)))
    session.execute(delete(MainContractMap).where(MainContractMap.symbol.in_(codes)))
    session.execute(
        delete(TradingSession).where(TradingSession.instrument_symbol.in_(codes))
    )
    session.execute(delete(Contract).where(Contract.instrument_symbol.in_(codes)))
    session.execute(delete(Instrument).where(Instrument.symbol.in_(codes)))
    session.commit()

    deleted_dirs = _delete_canonical_symbol_dirs(canonical_root, codes_set)
    residual = inventory_retirement(session, canonical_root, products=codes_set)
    status = "ok" if residual.total == 0 else "failed"
    return RetirementResult(
        action="retire-products",
        status=status,
        apply=True,
        products=codes,
        inventory=before,
        residual=residual,
        deleted_canonical_dirs=deleted_dirs,
    )


def plan_retirement(
    session: Session,
    canonical_root: Path,
    *,
    products: frozenset[str] | None = None,
) -> RetirementResult:
    """dry-run：只盘点，不写库、不删文件。"""
    codes_set = products if products is not None else load_retired_products()
    codes = tuple(sorted(codes_set))
    inventory = inventory_retirement(session, canonical_root, products=codes_set)
    return RetirementResult(
        action="retire-products",
        status="planned",
        apply=False,
        products=codes,
        inventory=inventory,
        residual=inventory,
        deleted_canonical_dirs=0,
    )


def _symbol_directories(canonical_root: Path, products: frozenset[str]) -> tuple[Path, ...]:
    """在 canonical 根下定位 ``symbol={code}`` 目录，并强制路径不逃逸。"""
    root = canonical_root.resolve()
    if not root.exists():
        return ()
    found: list[Path] = []
    for path in root.rglob("symbol=*"):
        if not path.is_dir():
            continue
        code = path.name.removeprefix("symbol=").strip().lower()
        if code not in products:
            continue
        resolved = path.resolve()
        if root not in resolved.parents:
            raise ValueError("CANONICAL_ROOT_ESCAPE")
        found.append(resolved)
    return tuple(sorted(found))


def _count_canonical_paths(canonical_root: Path, products: frozenset[str]) -> int:
    """统计退役 symbol 目录下的文件数量。"""
    total = 0
    for directory in _symbol_directories(canonical_root, products):
        total += sum(1 for item in directory.rglob("*") if item.is_file())
    return total


def _delete_canonical_symbol_dirs(canonical_root: Path, products: frozenset[str]) -> int:
    """删除退役 symbol 目录；缺失视为 no-op。"""
    deleted = 0
    for directory in _symbol_directories(canonical_root, products):
        if directory.exists():
            shutil.rmtree(directory)
            deleted += 1
    return deleted
