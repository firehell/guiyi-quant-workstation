"""Active 60 的轻量展示名称与一级研究板块事实。"""

from __future__ import annotations

import csv
from dataclasses import dataclass
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
    """展示 taxonomy 与 active 60 不一致。"""

    code = "PRODUCT_TAXONOMY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class ProductTaxonomyEntry:
    """单个 active 品种的展示事实。"""

    name: str
    sector: str


def load_product_taxonomy(
    path: Path | None = None,
) -> dict[str, ProductTaxonomyEntry]:
    """读取并校验每个 active 品种恰好一个名称和板块。"""
    source = path or _SECTORS_PATH
    try:
        if not source.is_file() or source.is_symlink():
            raise ProductTaxonomyError()
        with source.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != ["product", "name", "sector"]:
                raise ProductTaxonomyError()
            rows = tuple(reader)
        taxonomy = {
            normalize_symbol(str(row["product"])): ProductTaxonomyEntry(
                name=str(row["name"]).strip(),
                sector=str(row["sector"]).strip().lower(),
            )
            for row in rows
        }
        active = load_active_products()
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ProductTaxonomyError() from exc
    if (
        len(rows) != len(taxonomy)
        or set(taxonomy) != set(active)
        or any(not entry.name for entry in taxonomy.values())
        or any(entry.sector not in _ALLOWED_SECTORS for entry in taxonomy.values())
    ):
        raise ProductTaxonomyError()
    return taxonomy
