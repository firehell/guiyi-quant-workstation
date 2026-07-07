from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class SignalContractContext:
    product: str
    continuous_contract: str | None
    actual_contract: str | None
    dominant_mapping_date: date | None
    bar_start: datetime | None
    bar_end: datetime | None
    trigger_price: float | None
    provider: str | None
    source: str
    data_role: str


def build_signal_contract_context(
    *,
    symbol: str,
    contract: str,
    period: str,
    signal_time: datetime,
    current_price: float | None,
    features: dict[str, Any] | None = None,
    quality_status: dict[str, Any] | None = None,
    research_contract: bool | None = None,
    provider: str | None = None,
    data_role: str | None = None,
    source: str | None = None,
) -> SignalContractContext:
    features = features or {}
    quality_status = quality_status or {}
    contract_value = str(contract).strip()
    is_research_contract = bool(research_contract) or _is_continuous_contract(contract_value)
    bar_end = _datetime_value(features.get("bar_end") or features.get("bar_time")) or _datetime_value(signal_time)
    bar_start = _datetime_value(features.get("bar_start")) or _infer_bar_start(period, bar_end)
    explicit_actual_contract = _string_value(features.get("actual_contract"))
    explicit_continuous_contract = _string_value(features.get("continuous_contract"))

    actual_contract = None
    if explicit_actual_contract and not _is_continuous_contract(explicit_actual_contract):
        actual_contract = explicit_actual_contract
    elif contract_value and not is_research_contract:
        actual_contract = contract_value

    continuous_contract = explicit_continuous_contract
    if not continuous_contract and is_research_contract and contract_value:
        continuous_contract = contract_value

    resolved_provider = (
        _string_value(features.get("provider"))
        or _string_value(features.get("data_provider"))
        or _string_value(provider)
        or _string_value(quality_status.get("provider"))
        or "rqdata"
    )

    return SignalContractContext(
        product=(_string_value(features.get("product")) or str(symbol).lower()).lower(),
        continuous_contract=continuous_contract,
        actual_contract=actual_contract,
        dominant_mapping_date=_date_value(features.get("dominant_mapping_date")),
        bar_start=bar_start,
        bar_end=bar_end,
        trigger_price=_float_value(features.get("trigger_price") or features.get("signal_price") or current_price),
        provider=resolved_provider,
        source=_string_value(features.get("source")) or _string_value(source) or "historical_standard_parquet",
        data_role=_string_value(features.get("data_role")) or _string_value(data_role) or "primary",
    )


def apply_signal_contract_context(signal: Any, context: SignalContractContext) -> None:
    signal.product = context.product
    signal.continuous_contract = context.continuous_contract
    signal.actual_contract = context.actual_contract
    signal.dominant_mapping_date = context.dominant_mapping_date
    signal.bar_start = context.bar_start
    signal.bar_end = context.bar_end
    signal.trigger_price = context.trigger_price
    signal.provider = context.provider
    signal.source = context.source
    signal.data_role = context.data_role


def signal_contract_context_payload(signal: Any) -> dict[str, Any]:
    return {
        "product": signal.product,
        "continuous_contract": signal.continuous_contract,
        "actual_contract": signal.actual_contract,
        "dominant_mapping_date": signal.dominant_mapping_date.isoformat() if signal.dominant_mapping_date else None,
        "bar_start": signal.bar_start.isoformat() if signal.bar_start else None,
        "bar_end": signal.bar_end.isoformat() if signal.bar_end else None,
        "trigger_price": signal.trigger_price,
        "provider": signal.provider,
        "source": signal.source,
        "data_role": signal.data_role,
    }


def _is_continuous_contract(value: str) -> bool:
    return value.strip().lower().endswith(".main")


def _infer_bar_start(period: str, bar_end: datetime | None) -> datetime | None:
    if bar_end is None:
        return None
    delta = _period_delta(period)
    return bar_end - delta if delta is not None else None


def _period_delta(period: str) -> timedelta | None:
    value = str(period).strip().lower()
    if value.endswith("m") and value[:-1].isdigit():
        return timedelta(minutes=int(value[:-1]))
    if value.endswith("min") and value[:-3].isdigit():
        return timedelta(minutes=int(value[:-3]))
    if value.endswith("h") and value[:-1].isdigit():
        return timedelta(hours=int(value[:-1]))
    if value.endswith("d") and value[:-1].isdigit():
        return timedelta(days=int(value[:-1]))
    if value.endswith("w") and value[:-1].isdigit():
        return timedelta(weeks=int(value[:-1]))
    return None


def _datetime_value(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, str) and value.strip():
        return datetime.fromisoformat(value.strip()).replace(tzinfo=None)
    return None


def _date_value(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        return date.fromisoformat(value.strip())
    return None


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _float_value(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
