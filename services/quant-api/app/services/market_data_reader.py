"""Deprecated shim: Profile/filesystem historical selector.

Prefer ``MarketDataService`` / ``CanonicalBarLoader`` for historical bars.
This module re-exports the isolated legacy implementation used by Profile-bound
live/HTDY/workbench paths and offline audits until those consumers are retired.
"""

from __future__ import annotations

from app.services.legacy_compat.market_data_reader import (  # noqa: F401
    ACTIVE_DATA_ROLE,
    ACTIVE_PRIMARY_PROVIDERS,
    MarketDataReader,
)

__all__ = [
    "ACTIVE_DATA_ROLE",
    "ACTIVE_PRIMARY_PROVIDERS",
    "MarketDataReader",
]
