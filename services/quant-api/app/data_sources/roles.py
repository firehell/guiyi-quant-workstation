from __future__ import annotations

from enum import StrEnum


class DataSourceAccessError(ValueError):
    """Raised when a data source role would violate V1 access rules."""


class DataRole(StrEnum):
    PRIMARY = "primary"
    VALIDATION = "validation"
    LEGACY_REFERENCE = "legacy_reference"
    CANDIDATE = "candidate"


PRIMARY_PROVIDERS = frozenset({"local_parquet", "rqdata"})
VALIDATION_PROVIDERS = frozenset({"tq_old", "tqsdk"})
LEGACY_REFERENCE_PROVIDERS = frozenset({"trader_future_data", "trader_trainer"})
