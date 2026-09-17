"""Explicit public capability boundary for the staged Newow product release."""

from __future__ import annotations

from typing import Literal

from guiyi_quant.newow.product_contracts import ProductFrequency


ProductSectionName = Literal[
    "chart", "auxiliary", "reference", "explanation", "comparator"
]

CAPABILITY_SCHEMA_VERSION: Literal["newow_product_capabilities_v3"] = (
    "newow_product_capabilities_v3"
)
RELEASE_STAGE: Literal["daily"] = "daily"
OPEN_FREQUENCIES = (ProductFrequency.DAILY,)
OPEN_SECTIONS: tuple[ProductSectionName, ...] = (
    "chart",
    "auxiliary",
    "reference",
    "comparator",
)
DEFERRED_FREQUENCIES = (
    (ProductFrequency.WEEKLY, "NEWOW_WEEKLY_RELEASE_PENDING"),
    (ProductFrequency.HOURLY, "NEWOW_HOURLY_RELEASE_PENDING"),
)
DEFERRED_SECTIONS: tuple[tuple[ProductSectionName, str], ...] = (
    ("explanation", "NEWOW_CROSS_FREQUENCY_INPUTS_NOT_OPEN"),
)


def require_open_frequency(frequency: ProductFrequency) -> None:
    """Reject product requests outside the currently published frequency scope."""
    if ProductFrequency(frequency) not in OPEN_FREQUENCIES:
        raise ValueError("NEWOW_FREQUENCY_NOT_OPEN")


def require_open_section(section: ProductSectionName) -> None:
    """Reject sections whose authoritative inputs are outside this release."""
    if section not in OPEN_SECTIONS:
        raise ValueError("NEWOW_SECTION_NOT_OPEN")


def deferred_frequency_reason(frequency: ProductFrequency) -> str | None:
    """Return the public staged-release reason without opening data readers."""
    selected = ProductFrequency(frequency)
    return next(
        (reason for item, reason in DEFERRED_FREQUENCIES if item == selected), None
    )


def deferred_section_reason(section: ProductSectionName) -> str | None:
    """Return the public staged-release reason without opening data readers."""
    return next(
        (reason for item, reason in DEFERRED_SECTIONS if item == section), None
    )
