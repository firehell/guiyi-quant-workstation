from __future__ import annotations

import re

CONTINUOUS_SUFFIX = ".MAIN"
_PRODUCT_NAME_SUFFIXES = ("指数连续", "主力连续", "连续", "价差平滑")
_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")

# RQData 新上市品种可能只有 ad2601 / op2601 这类英文合约名，需人工兜底。
FUTURES_PRODUCT_DISPLAY_NAMES: dict[str, str] = {
    "ad": "铸造铝合金",
    "ao": "氧化铝",
    "br": "丁二烯橡胶",
    "ec": "集运指数(欧线)",
    "op": "胶版印刷纸",
    "pl": "瓶片",
}


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


def has_chinese_text(value: str | None) -> bool:
    return bool(_CHINESE_RE.search(value or ""))


def is_code_like_product_name(name: str | None, product: str) -> bool:
    cleaned = (name or "").strip()
    if not cleaned:
        return True
    product_key = product.strip().lower()
    if cleaned.lower() == product_key or cleaned.upper() == product_key.upper():
        return True
    return not has_chinese_text(cleaned) and cleaned.isascii() and len(cleaned) <= 4


def extract_product_name_from_contract_symbol(symbol: str | None, product: str) -> str:
    cleaned = (symbol or "").strip()
    for suffix in _PRODUCT_NAME_SUFFIXES:
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    cleaned = re.sub(r"\d+月", "", cleaned)
    cleaned = re.sub(r"\d+$", "", cleaned).strip()
    return normalize_product_name(cleaned or product, product)


def should_update_instrument_name(candidate: str, existing: str | None, product: str) -> bool:
    if existing is None:
        return True
    if has_chinese_text(existing) and not has_chinese_text(candidate):
        return False
    if has_chinese_text(candidate):
        return True
    return is_code_like_product_name(existing, product)


def resolve_instrument_display_name(
    product: str,
    contract_symbol: str | None,
    *,
    existing_name: str | None = None,
) -> str:
    candidate = extract_product_name_from_contract_symbol(contract_symbol, product)
    if is_code_like_product_name(candidate, product):
        candidate = FUTURES_PRODUCT_DISPLAY_NAMES.get(product.strip().lower(), candidate)
    if existing_name is not None and not should_update_instrument_name(candidate, existing_name, product):
        return normalize_product_name(existing_name, product)
    return candidate


def display_product_name(name: str | None, product: str) -> str:
    cleaned = normalize_product_name(name, product)
    if is_code_like_product_name(cleaned, product):
        return FUTURES_PRODUCT_DISPLAY_NAMES.get(product.strip().lower(), cleaned)
    return cleaned


def is_valid_listed_date(value: object) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and text not in {"0000-00-00", "0000/00/00", "NaT", "nat"}
