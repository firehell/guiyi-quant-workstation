"""Stable active-universe and retired-identity boundary for data consumers."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Sequence


RETIRED_PRODUCTS = frozenset({
    "ad", "bb", "bc", "cy", "fb", "jr", "l_f", "lg", "op", "pm", "pp_f",
    "ri", "rr", "t", "tf", "tl", "ts", "v_f", "wh", "wr", "zc",
})
ACTIVE_PRODUCT_COUNT = 69
_CONTRACT_PRODUCT = re.compile(r"^([A-Z]+(?:_F)?)(?:[0-9]{2,4})?$")


class ProductUniverseError(ValueError):
    """Invalid retained-universe input."""


def normalize_product(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized or None


def contract_product(value: str | None) -> str | None:
    normalized = str(value or "").strip().upper()
    if not normalized:
        return None
    if normalized.endswith(".MAIN"):
        normalized = normalized[: -len(".MAIN")]
    elif "." in normalized:
        normalized = normalized.rsplit(".", maxsplit=1)[-1]
    match = _CONTRACT_PRODUCT.fullmatch(normalized)
    return match.group(1).lower() if match is not None else None


def is_retired_identity(*, product: str | None = None, contract: str | None = None) -> bool:
    return bool(
        normalize_product(product) in RETIRED_PRODUCTS
        or contract_product(contract) in RETIRED_PRODUCTS
    )


def assert_products_active(products: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(str(product).strip().lower() for product in products)
    retired = tuple(product for product in normalized if is_retired_identity(product=product))
    if retired:
        raise ProductUniverseError("PRODUCT_UNIVERSE_PRODUCT_RETIRED:" + ",".join(sorted(set(retired))))
    return normalized


def load_active_products(path: Path) -> tuple[str, ...]:
    if not path.is_file() or path.is_symlink():
        raise ProductUniverseError("PRODUCT_UNIVERSE_ACTIVE_PRODUCTS_INVALID")
    products = tuple(
        normalized for raw in path.read_text(encoding="utf-8").splitlines()
        if (normalized := normalize_product(raw)) is not None
    )
    if len(products) != ACTIVE_PRODUCT_COUNT or len(set(products)) != len(products):
        raise ProductUniverseError("PRODUCT_UNIVERSE_ACTIVE_PRODUCT_COUNT_MISMATCH")
    if set(products) & RETIRED_PRODUCTS:
        raise ProductUniverseError("PRODUCT_UNIVERSE_ACTIVE_SET_OVERLAP")
    return products
