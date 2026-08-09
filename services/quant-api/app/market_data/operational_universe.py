"""市场观察运行品种的显式、受限配置。"""

from __future__ import annotations

from pathlib import Path

from app.core.env import PROJECT_ROOT
from app.market_data.product_retirement import load_retired_products, normalize_symbol


_OPERATIONAL_PATH = PROJECT_ROOT / "data/universe/operational_products.txt"
_ACTIVE_PATH = PROJECT_ROOT / "data/universe/active_products.txt"
_EXPECTED_ACTIVE_COUNT = 60


class OperationalUniverseError(ValueError):
    """运行品种配置不满足 active/retired 宇宙约束。"""

    code = "OPERATIONAL_UNIVERSE_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


def load_operational_products(path: Path | None = None) -> tuple[str, ...]:
    """按文件顺序加载运行品种，并校验为 active universe 的非退役子集。"""
    try:
        products = tuple(
            normalize_symbol(item)
            for item in (path or _OPERATIONAL_PATH).read_text(encoding="utf-8").splitlines()
            if item.strip()
        )
        active = tuple(
            normalize_symbol(item)
            for item in _ACTIVE_PATH.read_text(encoding="utf-8").splitlines()
            if item.strip()
        )
        retired = load_retired_products()
    except (OSError, ValueError) as exc:
        raise OperationalUniverseError() from exc

    if (
        len(active) != _EXPECTED_ACTIVE_COUNT
        or len(set(active)) != _EXPECTED_ACTIVE_COUNT
        or set(active).intersection(retired)
        or len(products) != len(set(products))
        or not set(products).issubset(active)
        or set(products).intersection(retired)
    ):
        raise OperationalUniverseError()
    return products
