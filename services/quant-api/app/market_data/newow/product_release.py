"""Explicit public capability boundary for the staged Newow product release."""

from __future__ import annotations

from typing import Literal
from datetime import UTC, datetime

from guiyi_quant.newow.product_contracts import ProductFrequency
from guiyi_quant.newow.product_identity import InputQualityPolicy


INTRADAY_BATCH_PREVIEW_SYMBOLS = frozenset({"rb", "hc", "ss", "i", "j", "jm", "sf", "sm"})

# P7 candidate eligibility only; each non-batch preview selects one product.
INTRADAY_SINGLE_PREVIEW_SYMBOLS = frozenset({
    "fu", "ma", "ur", "ta", "sh", "v", "sa", "au", "ag", "ni", "sf", "sm",
    "cj", "jd", "ap", "c", "lh", "m", "rm", "pk", "sr", "cf", "oi", "p", "lc", "fg", "ao", "cu", "ps", "y", "si", "a", "b", "bz", "eb", "ec", "eg", "l", "pd", "pf", "pg", "pl", "pr", "pt", "px", "rs",
})

# Released read-only historical scope; no forward stream activation.
OPEN_INTRADAY_PRODUCTS = tuple(sorted("rb hc i j jm ma ur ta sh v sa au ag sf sm cj jd ap c lh m rm pk sr cf oi p y lc ps fg a b bz eb ec eg l pd pf pg pl pr pt px".split()))
INTRADAY_HISTORY_AS_OF = datetime(2026, 9, 24, 7, 0, 0, 1, tzinfo=UTC)
INTRADAY_HISTORY_SCHEMA = "newow_intraday_pilot_20260927"
INTRADAY_HISTORY_FREQUENCIES = (ProductFrequency.FIVE_MINUTE, ProductFrequency.QUARTER_HOURLY, ProductFrequency.HALF_HOURLY, ProductFrequency.HOURLY)


def released_intraday_as_of(value: datetime | None) -> datetime:
    if value is None:
        return INTRADAY_HISTORY_AS_OF
    if value.utcoffset() is None or value > INTRADAY_HISTORY_AS_OF:
        raise ValueError("NEWOW_INVALID_AS_OF")
    return value


ProductSectionName = Literal[
    "chart", "auxiliary", "reference", "explanation", "comparator"
]

CAPABILITY_SCHEMA_VERSION: Literal["newow_product_capabilities_v29"] = (
    "newow_product_capabilities_v29"
)
RELEASE_STAGE: Literal["daily_weekly_intraday_history"] = "daily_weekly_intraday_history"
OPEN_FREQUENCIES = (ProductFrequency.DAILY, ProductFrequency.WEEKLY)
OPEN_SECTIONS: tuple[ProductSectionName, ...] = (
    "chart",
    "auxiliary",
    "reference",
    "comparator",
)
DEFERRED_FREQUENCIES = (
    (ProductFrequency.HOURLY, "NEWOW_HOURLY_RELEASE_PENDING"),
)
DEFERRED_SECTIONS: tuple[tuple[ProductSectionName, str], ...] = (
    ("explanation", "NEWOW_CROSS_FREQUENCY_INPUTS_NOT_OPEN"),
)

CANDIDATE_CAPABILITY_SCHEMA_VERSION: Literal["newow_product_capabilities_v9"] = (
    "newow_product_capabilities_v9"
)
CANDIDATE_RELEASE_STAGE: Literal["daily_weekly_candidate"] = "daily_weekly_candidate"
CANDIDATE_OPEN_FREQUENCIES = (ProductFrequency.DAILY, ProductFrequency.WEEKLY)
OPEN_WEEKLY_PRODUCTS = (
    "a", "ag", "al", "ao", "ap", "au", "b", "bu", "bz", "c", "cf", "cj", "cu",
    "eb", "ec", "eg", "fg", "fu", "hc", "i", "j", "jd", "jm", "l", "lc",
    "lh", "m", "ma", "ni", "oi", "p", "pb", "pd", "pf", "pg", "pk", "pl", "pp", "pr", "ps", "pt", "px", "rb",
    "rm", "rs", "ru", "sa", "sc", "sf", "sh", "si", "sm", "sn", "sr", "ss", "ta", "ur", "v", "y", "zn",
)
REMAINING_WEEKLY_V2_PRODUCTS: tuple[str, ...] = ()
FORMAL_WEEKLY_V2_PRODUCTS = ("b", "bz", "cj", "eb", "eg", "j", "oi", "pf", "pg", "pk", "pl", "pr", "px", "rs", "sf", "sh", "si", "sm", "sr")
# v9 is an immutable candidate wire contract. Keep its original ordering even as
# products graduate into later formal capability versions.
CANDIDATE_WEEKLY_PRODUCTS = (
    "a", "ag", "al", "ao", "ap", "au", "b", "bu", "bz", "c", "cf", "cu",
    "eb", "ec", "eg", "fg", "fu", "hc", "i", "j", "jd", "jm", "l", "lc",
    "lh", "m", "ma", "ni", "p", "pb", "pd", "pg", "pp", "ps", "pt", "rb",
    "rm", "ru", "sa", "sc", "si", "sn", "ss", "ta", "ur", "v", "y", "zn",
    "cj", "oi", "pf", "pk", "pl", "pr", "px", "rs", "sf", "sh", "sm", "sr",
)
if (
    len(OPEN_WEEKLY_PRODUCTS) != 60
    or len(REMAINING_WEEKLY_V2_PRODUCTS) != 0
    or len(FORMAL_WEEKLY_V2_PRODUCTS) != 19
    or set(FORMAL_WEEKLY_V2_PRODUCTS) - set(OPEN_WEEKLY_PRODUCTS)
    or set(OPEN_WEEKLY_PRODUCTS) & set(REMAINING_WEEKLY_V2_PRODUCTS)
    or len(CANDIDATE_WEEKLY_PRODUCTS) != 60
    or set(CANDIDATE_WEEKLY_PRODUCTS)
    != set(OPEN_WEEKLY_PRODUCTS) | set(REMAINING_WEEKLY_V2_PRODUCTS)
):
    raise RuntimeError("NEWOW_WEEKLY_PRODUCT_SCOPE_INVALID")
CANDIDATE_DEFERRED_FREQUENCIES = (
    (ProductFrequency.HOURLY, "NEWOW_HOURLY_RELEASE_PENDING"),
)
AU_PERIOD_PREVIEW_SCHEMA_VERSION = "newow_product_capabilities_v5"
AU_PERIOD_PREVIEW_STAGE = "au_daily_weekly_hourly_candidate"
AU_PERIOD_PREVIEW_FREQUENCIES = (
    ProductFrequency.DAILY, ProductFrequency.WEEKLY, ProductFrequency.HOURLY,
)
HOURLY_PRODUCT_PREVIEW_SCHEMA_VERSION = "newow_product_capabilities_v7"
HOURLY_PRODUCT_PREVIEW_STAGE = "ap_hourly_candidate"
PD_PT_HOURLY_PREVIEW_SCHEMA_VERSION = "newow_product_capabilities_v6"
PD_PT_HOURLY_PREVIEW_STAGE = "pd_pt_hourly_candidate"
HOURLY_PRODUCT_PREVIEW_FREQUENCIES = (
    ProductFrequency.DAILY, ProductFrequency.HOURLY,
)
HOURLY_PRODUCT_PREVIEW_DEFERRED = (
    (ProductFrequency.WEEKLY, "NEWOW_WEEKLY_RELEASE_PENDING"),
)
PD_PT_HOURLY_PREVIEW_SYMBOLS = frozenset({"pd", "pt"})
HOURLY_PRODUCT_PREVIEW_SYMBOLS = PD_PT_HOURLY_PREVIEW_SYMBOLS | {"ap"}


def candidate_input_quality_policy(
    product: str,
    frequency: ProductFrequency | str,
    *,
    candidate_weekly: bool,
) -> InputQualityPolicy:
    """Resolve the one immutable input policy for a product-frequency scope."""
    selected = ProductFrequency(frequency)
    if selected is ProductFrequency.DAILY:
        return InputQualityPolicy.DAILY_V2
    if selected is not ProductFrequency.WEEKLY:
        return InputQualityPolicy.V1
    if product in FORMAL_WEEKLY_V2_PRODUCTS:
        return InputQualityPolicy.WEEKLY_V2
    if candidate_weekly and product in REMAINING_WEEKLY_V2_PRODUCTS:
        return InputQualityPolicy.WEEKLY_V2
    return InputQualityPolicy.V1


def require_open_frequency(
    frequency: ProductFrequency,
    *,
    candidate: bool = False,
    hourly_preview: bool = False,
) -> None:
    """Reject product requests outside the currently published frequency scope."""
    if hourly_preview:
        allowed = HOURLY_PRODUCT_PREVIEW_FREQUENCIES
    elif candidate:
        allowed = CANDIDATE_OPEN_FREQUENCIES
    else:
        allowed = OPEN_FREQUENCIES
    if ProductFrequency(frequency) not in allowed:
        raise ValueError("NEWOW_FREQUENCY_NOT_OPEN")


def require_candidate_weekly_product(product: str) -> None:
    if product not in CANDIDATE_WEEKLY_PRODUCTS:
        raise ValueError("NEWOW_PRODUCT_FREQUENCY_NOT_OPEN")


def require_open_weekly_product(product: str) -> None:
    if product not in OPEN_WEEKLY_PRODUCTS:
        raise ValueError("NEWOW_PRODUCT_FREQUENCY_NOT_OPEN")


def require_open_section(section: ProductSectionName) -> None:
    """Reject sections whose authoritative inputs are outside this release."""
    if section not in OPEN_SECTIONS:
        raise ValueError("NEWOW_SECTION_NOT_OPEN")


def deferred_frequency_reason(frequency: ProductFrequency) -> str | None:
    """Return the public staged-release reason without opening data readers."""
    selected = ProductFrequency(frequency)
    if selected in (ProductFrequency.MINUTE, ProductFrequency.FIVE_MINUTE, ProductFrequency.QUARTER_HOURLY, ProductFrequency.HALF_HOURLY):
        return "NEWOW_INTRADAY_RELEASE_PENDING"
    return next(
        (reason for item, reason in DEFERRED_FREQUENCIES if item == selected), None
    )


def deferred_section_reason(section: ProductSectionName) -> str | None:
    """Return the public staged-release reason without opening data readers."""
    return next(
        (reason for item, reason in DEFERRED_SECTIONS if item == section), None
    )
