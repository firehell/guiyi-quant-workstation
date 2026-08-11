"""Active 60 的轻量一级研究板块事实。"""

from __future__ import annotations

import csv
from pathlib import Path

from app.core.env import PROJECT_ROOT
from app.market_data.operational_universe import load_active_products
from app.market_data.product_retirement import normalize_symbol


_SECTORS_PATH = PROJECT_ROOT / "data/universe/product_sectors.csv"
_ALLOWED_SECTORS = frozenset(
    {
        "black",
        "steel",
        "building",
        "nonferrous",
        "precious",
        "energy",
        "chemical",
        "new_energy",
        "agriculture",
        "other",
    }
)


class ProductTaxonomyError(ValueError):
    """板块配置与 active 60 不一致。"""

    code = "PRODUCT_TAXONOMY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


def load_product_sectors(path: Path | None = None) -> dict[str, str]:
    """读取并校验每个 active 品种恰好一个一级研究板块。"""
    source = path or _SECTORS_PATH
    try:
        if not source.is_file() or source.is_symlink():
            raise ProductTaxonomyError()
        with source.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != ["product", "sector"]:
                raise ProductTaxonomyError()
            rows = tuple(reader)
        sectors = {
            normalize_symbol(str(row["product"])): str(row["sector"]).strip().lower()
            for row in rows
        }
        active = load_active_products()
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ProductTaxonomyError() from exc
    if (
        len(rows) != len(sectors)
        or set(sectors) != set(active)
        or any(sector not in _ALLOWED_SECTORS for sector in sectors.values())
    ):
        raise ProductTaxonomyError()
    return sectors
