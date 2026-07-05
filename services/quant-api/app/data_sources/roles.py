from __future__ import annotations

from enum import StrEnum


class DataRole(StrEnum):
    PRIMARY = "primary"
    VALIDATION = "validation"
    LEGACY_REFERENCE = "legacy_reference"
    CANDIDATE = "candidate"


PRIMARY_PROVIDERS = frozenset({"local_parquet", "rqdata"})
VALIDATION_PROVIDERS = frozenset()
LEGACY_REFERENCE_PROVIDERS = frozenset()
