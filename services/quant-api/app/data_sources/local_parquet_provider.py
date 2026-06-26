from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.data_sources.base import MarketDataProvider, MarketDataQuery
from app.data_sources.errors import DataSourceAccessError
from app.data_sources.roles import PRIMARY_PROVIDERS, DataRole
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

    def get_bars(self, query: MarketDataQuery) -> list[dict[str, Any]]:
        self._validate_query(query)
        rows: list[dict[str, Any]] = []
        remaining = query.limit
        for provider in sorted(self.provider_names):
            rows.extend(
                self.reader.load_bars(
                    symbol=query.symbol,
                    contract=query.contract,
                    period=query.period,
                    start=query.start,
                    end=query.end,
                    provider=provider,
                    limit=remaining,
                )
            )
        return self._ordered(rows, limit=query.limit)

    def get_contracts(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in self.reader.get_coverage():
            if item.provider not in self.provider_names:
                continue
            rows.append(
                self._annotate(
                    {
                        "symbol": item.instrument_symbol,
                        "contract": item.contract_code,
                        "period": item.period,
                        "provider": item.provider,
                        "quality_status": item.quality_status,
                        "data_version": item.data_version,
                        "start_time": item.start_time,
                        "end_time": item.end_time,
                    }
                )
            )
        return rows

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


class LocalParquetProvider(ReaderBackedMarketDataProvider):
    """Default formal provider for local standardized primary bars."""

    data_role = DataRole.PRIMARY
    provider_names = PRIMARY_PROVIDERS
