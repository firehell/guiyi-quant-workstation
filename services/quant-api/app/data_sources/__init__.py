"""Data source boundaries for V1 market data reads."""

from app.data_sources.base import MarketDataProvider, MarketDataQuery
from app.data_sources.errors import DataSourceAccessError, DataSourceUnavailableError
from app.data_sources.legacy_data_provider import LegacyDataProvider
from app.data_sources.local_parquet_provider import LocalParquetProvider
from app.data_sources.rqdata_provider import RQDataProvider
from app.data_sources.roles import (
    DataRole,
    LEGACY_REFERENCE_PROVIDERS,
    PRIMARY_PROVIDERS,
    VALIDATION_PROVIDERS,
)

__all__ = [
    "DataRole",
    "DataSourceAccessError",
    "DataSourceUnavailableError",
    "LEGACY_REFERENCE_PROVIDERS",
    "LegacyDataProvider",
    "LocalParquetProvider",
    "MarketDataProvider",
    "MarketDataQuery",
    "PRIMARY_PROVIDERS",
    "RQDataProvider",
    "VALIDATION_PROVIDERS",
]
