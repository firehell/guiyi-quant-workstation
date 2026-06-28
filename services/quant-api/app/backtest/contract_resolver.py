from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import re
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import Contract, FeeMarginRule, FuturesTradingParameter, MainContractMap, TradingCalendar


DEFAULT_MAIN_CONTRACT_RULE = "volume_open_interest"
DEFAULT_PROVIDER = "rqdata"
DEFAULT_RANK = 1

ParameterSource = Literal["futures_trading_parameters", "fee_margin_rules", "mixed"]
FeeType = Literal["rate", "fixed"]


class ContractResolutionError(ValueError):
    """Base error for strict JM contract resolution failures."""


class MainContractMappingMissingError(ContractResolutionError):
    """Raised when main_contract_map has no exact row for the requested day."""


class ContractMetadataMissingError(ContractResolutionError):
    """Raised when mapped actual contract metadata is missing."""


class TradingParameterMissingError(ContractResolutionError):
    """Raised when trading parameters cannot be resolved without defaults."""


class DeliveryCalendarMissingError(ContractResolutionError):
    """Raised when retail last holding date cannot be calculated from calendars."""


@dataclass(frozen=True)
class CommissionRule:
    fee_type: FeeType
    open_fee: float
    close_fee: float
    close_today_fee: float | None


@dataclass(frozen=True)
class MainContractSource:
    map_id: int
    provider: str
    data_version: str
    rule: str
    rank: int


@dataclass(frozen=True)
class ResolvedContract:
    instrument_symbol: str
    trading_day: date
    actual_contract: str
    contract_month: str
    exchange: str
    contract_multiplier: int
    price_tick: float
    commission_rule: CommissionRule
    margin_ratio: float
    parameter_source: ParameterSource
    main_contract_source: MainContractSource
    last_allowed_holding_date: date


@dataclass(frozen=True)
class ResolvedTradeContractTimeline:
    entry: ResolvedContract
    exit: ResolvedContract

    @property
    def is_contract_changed(self) -> bool:
        return self.entry.actual_contract != self.exit.actual_contract


def resolve_jm_contract(
    session: Session,
    *,
    trading_day: date | None = None,
    moment: datetime | None = None,
    instrument_symbol: str = "jm",
    provider: str = DEFAULT_PROVIDER,
    rule: str = DEFAULT_MAIN_CONTRACT_RULE,
    rank: int = DEFAULT_RANK,
) -> ResolvedContract:
    """Resolve the actual tradable JM contract and trading parameters for one day."""
    day = _resolve_trading_day(trading_day=trading_day, moment=moment)
    symbol = instrument_symbol.strip().lower()
    if symbol != "jm":
        raise ContractResolutionError("JM contract resolver only supports instrument_symbol=jm in V1-Final")

    mapping = _load_main_contract_mapping(session, instrument_symbol=symbol, trading_day=day, provider=provider, rule=rule, rank=rank)
    actual_contract = _normalize_contract_code(mapping.contract_code)
    if "." in actual_contract or actual_contract.lower().endswith(".main"):
        raise MainContractMappingMissingError(
            f"main_contract_map returned non-tradable contract_code={mapping.contract_code!r} for jm on {day}"
        )

    contract = _load_contract_metadata(session, actual_contract=actual_contract, instrument_symbol=symbol)
    exchange = _required_text(contract.exchange_code, f"contracts.exchange_code missing for {actual_contract}")
    contract_month = _contract_month(contract, actual_contract)
    last_allowed_holding_date = _last_allowed_holding_date(session, exchange_code=exchange, contract_month=contract_month)

    params = _load_trading_parameters(session, contract_code=actual_contract, trading_day=day, provider=provider)
    fee_rule = _load_fee_margin_rule(
        session,
        contract_code=actual_contract,
        instrument_symbol=symbol,
        exchange_code=exchange,
        trading_day=day,
        provider=provider,
    )
    resolved = _resolve_parameters(
        contract=contract,
        params=params,
        fee_rule=fee_rule,
        contract_code=actual_contract,
        trading_day=day,
    )

    return ResolvedContract(
        instrument_symbol=symbol,
        trading_day=day,
        actual_contract=actual_contract,
        contract_month=contract_month,
        exchange=exchange,
        contract_multiplier=resolved["contract_multiplier"],
        price_tick=resolved["price_tick"],
        commission_rule=resolved["commission_rule"],
        margin_ratio=resolved["margin_ratio"],
        parameter_source=resolved["parameter_source"],
        main_contract_source=MainContractSource(
            map_id=int(mapping.id),
            provider=mapping.provider,
            data_version=mapping.data_version,
            rule=mapping.rule,
            rank=mapping.rank,
        ),
        last_allowed_holding_date=last_allowed_holding_date,
    )


def resolve_jm_trade_contract_timeline(
    session: Session,
    *,
    entry_time: datetime,
    exit_time: datetime,
    instrument_symbol: str = "jm",
    provider: str = DEFAULT_PROVIDER,
    rule: str = DEFAULT_MAIN_CONTRACT_RULE,
    rank: int = DEFAULT_RANK,
) -> ResolvedTradeContractTimeline:
    if exit_time < entry_time:
        raise ContractResolutionError("exit_time must be greater than or equal to entry_time")
    return ResolvedTradeContractTimeline(
        entry=resolve_jm_contract(
            session,
            moment=entry_time,
            instrument_symbol=instrument_symbol,
            provider=provider,
            rule=rule,
            rank=rank,
        ),
        exit=resolve_jm_contract(
            session,
            moment=exit_time,
            instrument_symbol=instrument_symbol,
            provider=provider,
            rule=rule,
            rank=rank,
        ),
    )


def _resolve_trading_day(*, trading_day: date | None, moment: datetime | None) -> date:
    if trading_day is None and moment is None:
        raise ContractResolutionError("either trading_day or moment is required")
    if trading_day is not None:
        return trading_day
    assert moment is not None
    return moment.date()


def _load_main_contract_mapping(
    session: Session,
    *,
    instrument_symbol: str,
    trading_day: date,
    provider: str,
    rule: str,
    rank: int,
) -> MainContractMap:
    row = session.scalar(
        select(MainContractMap)
        .where(
            MainContractMap.instrument_symbol == instrument_symbol,
            MainContractMap.trade_date == trading_day,
            MainContractMap.rank == rank,
            MainContractMap.rule == rule,
            MainContractMap.provider == provider,
        )
        .order_by(MainContractMap.created_at.desc(), MainContractMap.id.desc())
        .limit(1)
    )
    if row is None:
        raise MainContractMappingMissingError(
            f"main_contract_map missing for instrument_symbol={instrument_symbol}, trade_date={trading_day}, rank={rank}, rule={rule}, provider={provider}"
        )
    return row


def _load_contract_metadata(session: Session, *, actual_contract: str, instrument_symbol: str) -> Contract:
    row = session.scalar(
        select(Contract)
        .where(Contract.contract_code == actual_contract, Contract.instrument_symbol == instrument_symbol)
        .limit(1)
    )
    if row is None:
        raise ContractMetadataMissingError(f"contracts missing for actual_contract={actual_contract}, instrument_symbol={instrument_symbol}")
    return row


def _load_trading_parameters(
    session: Session,
    *,
    contract_code: str,
    trading_day: date,
    provider: str,
) -> FuturesTradingParameter | None:
    return session.scalar(
        select(FuturesTradingParameter)
        .where(
            FuturesTradingParameter.contract_code == contract_code,
            FuturesTradingParameter.trade_date == trading_day,
            FuturesTradingParameter.provider == provider,
        )
        .order_by(FuturesTradingParameter.created_at.desc(), FuturesTradingParameter.id.desc())
        .limit(1)
    )


def _load_fee_margin_rule(
    session: Session,
    *,
    contract_code: str,
    instrument_symbol: str,
    exchange_code: str,
    trading_day: date,
    provider: str,
) -> FeeMarginRule | None:
    rows = list(
        session.scalars(
            select(FeeMarginRule).where(
                FeeMarginRule.provider == provider,
                FeeMarginRule.exchange_code == exchange_code,
                (FeeMarginRule.contract_code == contract_code)
                | ((FeeMarginRule.contract_code.is_(None)) & (FeeMarginRule.instrument_symbol == instrument_symbol)),
                (FeeMarginRule.effective_date.is_(None)) | (FeeMarginRule.effective_date <= trading_day),
            )
        )
    )
    if not rows:
        return None
    rows.sort(key=lambda row: (row.contract_code == contract_code, row.effective_date or date.min, row.id), reverse=True)
    return rows[0]


def _resolve_parameters(
    *,
    contract: Contract,
    params: FuturesTradingParameter | None,
    fee_rule: FeeMarginRule | None,
    contract_code: str,
    trading_day: date,
) -> dict[str, object]:
    if params is None and fee_rule is None:
        raise TradingParameterMissingError(
            f"trading parameters missing for contract={contract_code} on {trading_day}; futures_trading_parameters and fee_margin_rules both absent"
        )

    params_multiplier = _getattr(params, "contract_multiplier")
    params_price_tick = _getattr(params, "price_tick")
    params_margin_ratio = _max_optional(_getattr(params, "long_margin_ratio"), _getattr(params, "short_margin_ratio"))
    params_open_fee = _getattr(params, "open_commission")
    params_close_fee = _getattr(params, "close_commission")
    params_fee_type = _getattr(params, "commission_type")

    used_fee_rule = False
    contract_multiplier = _first_int(params_multiplier)
    if contract_multiplier is None:
        contract_multiplier = _first_int(_getattr(fee_rule, "volume_multiple"))
        used_fee_rule = used_fee_rule or contract_multiplier is not None
    if contract_multiplier is None:
        contract_multiplier = _first_int(contract.contract_multiplier)

    price_tick = _first_float(params_price_tick)
    if price_tick is None:
        price_tick = _first_float(_getattr(fee_rule, "price_tick"))
        used_fee_rule = used_fee_rule or price_tick is not None

    margin_ratio = _first_float(params_margin_ratio)
    if margin_ratio is None:
        margin_ratio = _first_float(_getattr(fee_rule, "margin_rate"))
        used_fee_rule = used_fee_rule or margin_ratio is not None

    open_fee = _first_float(params_open_fee)
    if open_fee is None:
        open_fee = _first_float(_getattr(fee_rule, "open_fee"))
        used_fee_rule = used_fee_rule or open_fee is not None

    close_fee = _first_float(params_close_fee)
    if close_fee is None:
        close_fee = _first_float(_getattr(fee_rule, "close_fee"))
        used_fee_rule = used_fee_rule or close_fee is not None

    close_today_fee = _optional_float(_getattr(params, "close_today_commission"))
    if close_today_fee is None:
        close_today_fee = _optional_float(_getattr(fee_rule, "close_today_fee"))
        used_fee_rule = used_fee_rule or close_today_fee is not None

    fee_type = _normalize_fee_type(params_fee_type)
    if fee_type is None:
        fee_type = _normalize_fee_type(_getattr(fee_rule, "fee_type"))
        used_fee_rule = used_fee_rule or fee_type is not None

    missing = [
        name
        for name, value in (
            ("contract_multiplier", contract_multiplier),
            ("price_tick", price_tick),
            ("margin_ratio", margin_ratio),
            ("open_fee", open_fee),
            ("close_fee", close_fee),
            ("commission_type", fee_type),
        )
        if value is None
    ]
    if missing:
        raise TradingParameterMissingError(f"trading parameters incomplete for contract={contract_code} on {trading_day}: {', '.join(missing)}")

    source = _parameter_source(params=params, used_fee_rule=used_fee_rule)
    return {
        "contract_multiplier": contract_multiplier,
        "price_tick": price_tick,
        "margin_ratio": margin_ratio,
        "commission_rule": CommissionRule(
            fee_type=fee_type,
            open_fee=open_fee,
            close_fee=close_fee,
            close_today_fee=close_today_fee,
        ),
        "parameter_source": source,
    }


def _parameter_source(*, params: FuturesTradingParameter | None, used_fee_rule: bool) -> ParameterSource:
    if params is None:
        return "fee_margin_rules"
    return "mixed" if used_fee_rule else "futures_trading_parameters"


def _last_allowed_holding_date(session: Session, *, exchange_code: str, contract_month: str) -> date:
    year, month = _parse_contract_month(contract_month)
    delivery_month_start = date(year, month, 1)
    row = session.scalar(
        select(TradingCalendar.trade_date)
        .where(
            TradingCalendar.exchange_code == exchange_code,
            TradingCalendar.trade_date < delivery_month_start,
            TradingCalendar.is_trading_day.is_(True),
        )
        .order_by(TradingCalendar.trade_date.desc())
        .limit(1)
    )
    if row is None:
        raise DeliveryCalendarMissingError(
            f"trading_calendars missing last trading day before delivery month for exchange={exchange_code}, contract_month={contract_month}"
        )
    return row


def _contract_month(contract: Contract, contract_code: str) -> str:
    raw = (contract.contract_month or "").strip()
    if raw:
        year, month = _parse_contract_month(raw)
        return f"{year:04d}-{month:02d}"
    match = re.search(r"(\d{4})$", contract_code)
    if not match:
        raise ContractMetadataMissingError(f"cannot infer contract_month from contract_code={contract_code}")
    digits = match.group(1)
    year = 2000 + int(digits[:2])
    month = int(digits[2:])
    if not 1 <= month <= 12:
        raise ContractMetadataMissingError(f"invalid contract_month inferred from contract_code={contract_code}")
    return f"{year:04d}-{month:02d}"


def _parse_contract_month(value: str) -> tuple[int, int]:
    normalized = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}", normalized):
        return int(normalized[:4]), int(normalized[5:])
    digits = "".join(ch for ch in normalized if ch.isdigit())
    if len(digits) == 6:
        year = int(digits[:4])
        month = int(digits[4:])
    elif len(digits) == 4:
        year = 2000 + int(digits[:2])
        month = int(digits[2:])
    else:
        raise ContractMetadataMissingError(f"invalid contract_month={value!r}")
    if not 1 <= month <= 12:
        raise ContractMetadataMissingError(f"invalid contract_month={value!r}")
    return year, month


def _normalize_contract_code(value: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise MainContractMappingMissingError("main_contract_map returned blank contract_code")
    return normalized


def _normalize_fee_type(value: object) -> FeeType | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"by_money", "rate", "ratio", "percent", "percentage"}:
        return "rate"
    if normalized in {"by_volume", "fixed", "fixed_per_lot", "per_lot"}:
        return "fixed"
    raise TradingParameterMissingError(f"unsupported commission_type={value!r}")


def _required_text(value: str | None, message: str) -> str:
    if value is None or not value.strip():
        raise ContractMetadataMissingError(message)
    return value.strip().upper()


def _getattr(row: object | None, name: str) -> object | None:
    if row is None:
        return None
    return getattr(row, name)


def _first_float(*values: object | None) -> float | None:
    for value in values:
        parsed = _optional_float(value)
        if parsed is not None:
            return parsed
    return None


def _optional_float(value: object | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    parsed = float(value)
    return parsed


def _first_int(*values: object | None) -> int | None:
    for value in values:
        if value is not None:
            return int(value)
    return None


def _max_optional(*values: object | None) -> float | None:
    parsed = [_optional_float(value) for value in values]
    numbers = [value for value in parsed if value is not None]
    return max(numbers) if numbers else None
