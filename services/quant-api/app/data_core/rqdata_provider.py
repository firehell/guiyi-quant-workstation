from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import pandas as pd

from app.data_core.bar_schema import CanonicalBar
from app.data_core.contracts import ContractValidationError, DatasetKind
from app.data_core.rqdata_adapter import (
    MainMapRequest,
    MainMapRow,
    ProviderBarBatch,
    ProviderBarRequest,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


class RQDataClient(Protocol):
    @staticmethod
    def rqdatac_version() -> str: ...

    def contract_bars(
        self,
        contract: str,
        start_date: date,
        end_date: date,
        frequency: str,
    ) -> pd.DataFrame: ...

    def dominant_contracts(
        self,
        product: str,
        start_date: date,
        end_date: date,
        rank: int,
    ) -> pd.DataFrame: ...


class CanonicalRQDataAdapter:
    """Normalize existing RqDataClient responses into frozen data-core contracts."""

    def __init__(self, client: RQDataClient) -> None:
        self._client = client

    def fetch_bars(self, request: ProviderBarRequest) -> ProviderBarBatch:
        if not isinstance(request, ProviderBarRequest):
            raise ContractValidationError(
                facts={"field": "request", "reason": "invalid"}
            )
        trading_days = tuple(session.trading_day for session in request.sessions)
        frame = self._client.contract_bars(
            _provider_order_book_id(request),
            min(trading_days),
            max(trading_days),
            request.dataset.frequency.value,
        )
        rows = _records(frame)
        expected_bar_ends = {
            bar_end
            for session in request.sessions
            for bar_end in session.expected_bar_ends
        }
        bars = tuple(
            sorted(
                (
                    bar
                    for row in rows
                    if (
                        bar := _canonical_bar(request, row)
                    ).bar_end in expected_bar_ends
                ),
                key=lambda bar: bar.bar_end,
            )
        )
        return ProviderBarBatch(
            request=request,
            bars=bars,
            data_version=(
                f"rqdata-{self._client.rqdatac_version()}-"
                f"{request.dataset.frequency.value}-"
                f"{min(trading_days):%Y%m%d}-{max(trading_days):%Y%m%d}"
            ),
        )

    def fetch_rank1_map(self, request: MainMapRequest) -> tuple[MainMapRow, ...]:
        if not isinstance(request, MainMapRequest):
            raise ContractValidationError(
                facts={"field": "request", "reason": "invalid"}
            )
        frame = self._client.dominant_contracts(
            request.symbol,
            request.start_day,
            request.end_day,
            1,
        )
        version = (
            f"rqdata-{self._client.rqdatac_version()}-rank1-"
            f"{request.start_day:%Y%m%d}-{request.end_day:%Y%m%d}"
        )
        mapping: dict[date, str] = {}
        for row in _records(frame):
            trading_day = _date_value(
                row,
                "date",
                "trade_date",
                "trading_date",
                "index",
            )
            contract = _text_value(
                row,
                "contract",
                "dominant",
                "order_book_id",
                "symbol",
                "dominant_contract",
                0,
                "0",
            ).upper()
            existing = mapping.get(trading_day)
            if existing is not None and existing != contract:
                raise ContractValidationError(
                    facts={"field": "mapping_rows", "reason": "conflict"}
                )
            mapping[trading_day] = contract
        return tuple(
            MainMapRow(
                symbol=request.symbol,
                trading_day=trading_day,
                actual_contract=contract,
                rank=1,
                data_version=version,
            )
            for trading_day, contract in sorted(mapping.items())
        )


def _provider_order_book_id(request: ProviderBarRequest) -> str:
    dataset = request.dataset
    if (
        dataset.dataset_kind is DatasetKind.CONTINUOUS
        and dataset.contract_or_series == f"{dataset.symbol.upper()}.MAIN"
    ):
        # RQData 88 is the unadjusted splice; 888 is back-adjusted and would
        # violate adjustment=none in the frozen DatasetKey.
        return f"{dataset.symbol.upper()}88"
    return dataset.contract_or_series


def _records(frame: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(frame, pd.DataFrame):
        raise ContractValidationError(
            facts={"field": "provider_frame", "reason": "invalid"}
        )
    normalized = frame.copy()
    if not isinstance(normalized.index, pd.RangeIndex):
        normalized = normalized.reset_index()
    return tuple(normalized.to_dict("records"))


def _canonical_bar(request: ProviderBarRequest, row: dict[str, Any]) -> CanonicalBar:
    bar_end = _utc_datetime(request, row, "datetime", "date", "index")
    return CanonicalBar(
        provider="rqdata",
        dataset_kind=request.dataset.dataset_kind,
        symbol=request.dataset.symbol,
        contract_or_series=request.dataset.contract_or_series,
        frequency=request.dataset.frequency,
        bar_end=bar_end,
        trading_day=_trading_day(request, row, bar_end),
        open=_decimal_value(row, "open"),
        high=_decimal_value(row, "high"),
        low=_decimal_value(row, "low"),
        close=_decimal_value(row, "close"),
        volume=_decimal_value(row, "volume"),
        turnover=_optional_decimal_value(row, "turnover", "total_turnover", "amount"),
        open_interest=_optional_decimal_value(
            row,
            "open_interest",
            "open_oi",
            "close_oi",
        ),
        adjustment=request.dataset.adjustment,
        schema_version=request.dataset.schema_version,
    )


def _trading_day(
    request: ProviderBarRequest,
    row: dict[str, Any],
    bar_end: datetime,
) -> date:
    explicit = _first_value(
        row,
        ("trading_date", "trade_date"),
        required=False,
    )
    if explicit is not None:
        return _date_value(row, "trading_date", "trade_date")
    if request.dataset.frequency.value in {"1d", "1w"}:
        return bar_end.astimezone(SHANGHAI).date()
    matching = tuple(
        session.trading_day
        for session in request.sessions
        if session.start < bar_end <= session.end
    )
    if len(matching) != 1:
        raise ContractValidationError(
            facts={
                "field": "trading_day",
                "reason": "session_resolution_not_unique",
            }
        )
    return matching[0]


def _utc_datetime(
    request: ProviderBarRequest,
    row: dict[str, Any],
    *fields: str,
) -> datetime:
    value = _first_value(row, fields)
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(
            facts={"field": "bar_end", "reason": "invalid"}
        ) from exc
    if pd.isna(parsed):
        raise ContractValidationError(
            facts={"field": "bar_end", "reason": "invalid"}
        )
    if parsed.tzinfo is None:
        timezone = (
            UTC
            if request.dataset.frequency.value in {"1d", "1w"}
            else SHANGHAI
        )
        parsed = parsed.tz_localize(timezone)
    return parsed.tz_convert(UTC).to_pydatetime()


def _date_value(row: dict[str, Any], *fields: object) -> date:
    value = _first_value(row, fields)
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(
            facts={"field": "trading_day", "reason": "invalid"}
        ) from exc
    if pd.isna(parsed):
        raise ContractValidationError(
            facts={"field": "trading_day", "reason": "invalid"}
        )
    return parsed.date()


def _text_value(row: dict[str, Any], *fields: object) -> str:
    value = _first_value(row, fields)
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(
            facts={"field": fields[0], "reason": "invalid"}
        )
    return value.strip()


def _decimal_value(row: dict[str, Any], *fields: str) -> Decimal:
    value = _optional_decimal_value(row, *fields)
    if value is None:
        raise ContractValidationError(
            facts={"field": fields[0], "reason": "missing"}
        )
    return value


def _optional_decimal_value(row: dict[str, Any], *fields: str) -> Decimal | None:
    value = _first_value(row, fields, required=False)
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ContractValidationError(
            facts={"field": fields[0], "reason": "invalid"}
        ) from exc


def _first_value(
    row: dict[str, Any],
    fields: tuple[object, ...],
    *,
    required: bool = True,
) -> Any:
    for field in fields:
        if field in row and row[field] is not None:
            return row[field]
    if required:
        raise ContractValidationError(
            facts={"field": str(fields[0]), "reason": "missing"}
        )
    return None
