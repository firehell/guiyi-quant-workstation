from __future__ import annotations

import re

CONTINUOUS_SUFFIX = ".MAIN"
_PRODUCT_NAME_SUFFIXES = ("指数连续", "主力连续", "连续")


def is_synthetic_futures_contract(contract: str) -> bool:
    """Return True for vn.py *.MAIN and RQData synthetic dominant/index contracts (*88/*99)."""
    normalized = (contract or "").strip().upper()
    if not normalized:
        return True
    if normalized.endswith(CONTINUOUS_SUFFIX.upper()):
        return True

    match = re.fullmatch(r"([A-Z]+)(\d+)", normalized)
    if not match:
        return False

    digits = match.group(2)
    if digits in ("88", "99"):
        return True
    if len(digits) >= 3 and set(digits) <= {"8"}:
        return True
    if len(digits) >= 3 and set(digits) <= {"9"}:
        return True
    return False


def is_continuous_contract(contract: str) -> bool:
    return is_synthetic_futures_contract(contract)


def continuous_contract_for(product: str) -> str:
    return f"{product.strip().lower()}{CONTINUOUS_SUFFIX}"


def normalize_product_name(name: str | None, product: str) -> str:
    cleaned = (name or "").strip()
    for suffix in _PRODUCT_NAME_SUFFIXES:
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    cleaned = cleaned.strip()
    return cleaned or product.upper()


def is_valid_listed_date(value: object) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and text not in {"0000-00-00", "0000/00/00", "NaT", "nat"}
