"""退役品种的永久精确拦截。

退役生产清退已经完成；本模块只保留 active/retired 互斥与请求硬拒绝，不再提供重复删除入口。
"""

from __future__ import annotations

from pathlib import Path

from app.core.env import PROJECT_ROOT


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
