"""Single historical market-data entry point for Data Core V2 consumers."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session

from app.data_core.contracts import BarQuery, BarsResult, DataCoreError


class CanonicalHistoricalReader(Protocol):
    def get_bars(self, query: BarQuery) -> BarsResult: ...


class MarketDataService:
    """Fail-closed facade over the canonical Catalog/Manifest reader.

    Runtime live observation remains a separate service. Historical callers
    must provide a complete ``BarQuery`` and receive the immutable Data Core
    ``BarsResult``; Profile/Binding and filesystem-discovery selectors are not
    accepted.
    """

    def __init__(
        self,
        session: Session,
        *,
        canonical_reader: CanonicalHistoricalReader | None = None,
        **legacy_options: object,
    ) -> None:
        del session
        if legacy_options:
            raise DataCoreError(facts={"reason": "legacy_market_options_retired"})
        self._canonical_reader = canonical_reader

    def get_bars(self, request: BarQuery) -> BarsResult:
        if not isinstance(request, BarQuery):
            raise DataCoreError(facts={"reason": "canonical_bar_query_required"})
        if self._canonical_reader is None:
            raise DataCoreError(facts={"reason": "canonical_reader_unavailable"})
        return self._canonical_reader.get_bars(request)
