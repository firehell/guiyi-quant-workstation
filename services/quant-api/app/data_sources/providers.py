from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.data_sources.base import MarketDataProvider, MarketDataQuery
from app.data_sources.roles import (
    LEGACY_REFERENCE_PROVIDERS,
    PRIMARY_PROVIDERS,
    VALIDATION_PROVIDERS,
    DataRole,
    DataSourceAccessError,
)
from app.db.session import PROJECT_ROOT
from app.services.market_data_reader import MarketDataReader


class ReaderBackedMarketDataProvider(MarketDataProvider):
    """Adapter over MarketDataReader with explicit role/provider boundaries."""

    data_role = DataRole.PRIMARY
    provider_names = PRIMARY_PROVIDERS

    def __init__(
        self,
        session: Session,
        *,
        reader: MarketDataReader | None = None,
        project_root: Path = PROJECT_ROOT,
    ) -> None:
        self.reader = reader or MarketDataReader(session=session, project_root=project_root)

    def load_bars(self, query: MarketDataQuery) -> list[dict[str, Any]]:
        self._validate_query(query)
        rows: list[dict[str, Any]] = []
        for provider in sorted(self.provider_names):
            rows.extend(
                self.reader.load_bars(
                    symbol=query.symbol,
                    contract=query.contract,
                    period=query.period,
                    start=query.start,
                    end=query.end,
                    provider=provider,
                    limit=query.limit,
                )
            )
        return self._ordered(rows, limit=query.limit)

    def load_latest_bars(self, symbol: str, contract: str, period: str, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            raise DataSourceAccessError("limit must be greater than zero")
        rows: list[dict[str, Any]] = []
        for provider in sorted(self.provider_names):
            rows.extend(self.reader.load_latest_bars(symbol=symbol, contract=contract, period=period, limit=limit, provider=provider))
        return self._ordered(rows)[-limit:]

    def get_quality_status(self, query: MarketDataQuery) -> dict[str, Any]:
        self._validate_query(query)
        statuses = {
            provider: self.reader.get_quality_status(
                symbol=query.symbol,
                contract=query.contract,
                period=query.period,
                start=query.start,
                end=query.end,
                provider=provider,
            )
            for provider in sorted(self.provider_names)
        }
        return {
            "data_role": self.data_role.value,
            "research_only": self.data_role is not DataRole.PRIMARY,
            "providers": statuses,
            "status": self._aggregate_status(status.get("status", "unchecked") for status in statuses.values()),
        }

    def _validate_query(self, query: MarketDataQuery) -> None:
        if query.start > query.end:
            raise DataSourceAccessError("query.start must be earlier than or equal to query.end")

    def _ordered(self, rows: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
        annotated = [self._annotate(row) for row in rows]
        ordered = sorted(annotated, key=lambda row: row.get("datetime") or row.get("time") or datetime.min)
        return ordered if limit is None else ordered[:limit]

    def _annotate(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = dict(row)
        payload["data_role"] = self.data_role.value
        payload["research_only"] = self.data_role is not DataRole.PRIMARY
        return payload

    @staticmethod
    def _aggregate_status(statuses: Any) -> str:
        status_set = set(statuses)
        if "failed" in status_set:
            return "failed"
        if "warning" in status_set:
            return "warning"
        if "passed" in status_set:
            return "passed"
        return "unchecked"


class RQDataProvider(ReaderBackedMarketDataProvider):
    """Reads RQData-origin bars from local standardized storage only."""

    data_role = DataRole.PRIMARY
    provider_names = frozenset({"rqdata"})


class LocalParquetProvider(ReaderBackedMarketDataProvider):
    """Default formal provider for local standardized primary bars."""

    data_role = DataRole.PRIMARY
    provider_names = PRIMARY_PROVIDERS


class LegacyDataProvider(ReaderBackedMarketDataProvider):
    """Explicit-only access to validation or legacy reference data."""

    def __init__(
        self,
        session: Session,
        *,
        data_role: DataRole,
        explicit: bool = False,
        reader: MarketDataReader | None = None,
        project_root: Path = PROJECT_ROOT,
    ) -> None:
        if data_role not in {DataRole.VALIDATION, DataRole.LEGACY_REFERENCE}:
            raise DataSourceAccessError("LegacyDataProvider only supports validation or legacy_reference roles")
        if not explicit:
            raise DataSourceAccessError(f"{data_role.value} data must be explicitly selected")
        self.data_role = data_role
        self.provider_names = self._providers_for_role(data_role)
        super().__init__(session=session, reader=reader, project_root=project_root)

    @classmethod
    def validation(cls, session: Session, *, explicit: bool, reader: MarketDataReader | None = None) -> LegacyDataProvider:
        return cls(session=session, data_role=DataRole.VALIDATION, explicit=explicit, reader=reader)

    @classmethod
    def legacy_reference(cls, session: Session, *, explicit: bool, reader: MarketDataReader | None = None) -> LegacyDataProvider:
        return cls(session=session, data_role=DataRole.LEGACY_REFERENCE, explicit=explicit, reader=reader)

    @staticmethod
    def _providers_for_role(data_role: DataRole) -> frozenset[str]:
        if data_role is DataRole.VALIDATION:
            return VALIDATION_PROVIDERS
        if data_role is DataRole.LEGACY_REFERENCE:
            return LEGACY_REFERENCE_PROVIDERS
        raise DataSourceAccessError(f"Unsupported legacy role: {data_role.value}")
