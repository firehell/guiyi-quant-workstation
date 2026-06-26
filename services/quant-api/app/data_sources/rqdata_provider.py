from __future__ import annotations

from app.data_sources.local_parquet_provider import ReaderBackedMarketDataProvider
from app.data_sources.roles import DataRole


class RQDataProvider(ReaderBackedMarketDataProvider):
    """RQData-origin bars read from local standardized storage only."""

    data_role = DataRole.PRIMARY
    provider_names = frozenset({"rqdata"})
