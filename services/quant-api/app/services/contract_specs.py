from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import FeeMarginRule


FeeType = Literal["rate", "fixed"]


@dataclass(frozen=True)
class ContractSpec:
    price_tick: float = 1.0
    volume_multiple: int = 10
    margin_rate: float = 0.10
    open_fee: float = 0.0001
    close_fee: float = 0.0001
    close_today_fee: float | None = None
    fee_type: FeeType = "rate"
    source: str = "fallback"


def load_contract_spec(session: Session, symbol: str, contract: str) -> ContractSpec:
    rules = list(
        session.scalars(
            select(FeeMarginRule).where(
                (FeeMarginRule.contract_code == contract)
                | (
                    (FeeMarginRule.contract_code.is_(None))
                    & (FeeMarginRule.instrument_symbol == symbol)
                )
            )
        )
    )
    if not rules:
        return ContractSpec()
    rules.sort(
        key=lambda rule: (
            rule.contract_code == contract,
            rule.effective_date or date.min,
        ),
        reverse=True,
    )
    rule = rules[0]
    return ContractSpec(
        price_tick=_decimal_to_float(rule.price_tick, 1.0),
        volume_multiple=rule.volume_multiple or 10,
        margin_rate=_decimal_to_float(rule.margin_rate, 0.10),
        open_fee=_decimal_to_float(rule.open_fee, 0.0001),
        close_fee=_decimal_to_float(rule.close_fee, 0.0001),
        close_today_fee=(
            None if rule.close_today_fee is None else float(rule.close_today_fee)
        ),
        fee_type=(
            "fixed"
            if rule.fee_type in {"fixed", "fixed_per_lot", "per_lot"}
            else "rate"
        ),
        source=rule.source or rule.provider,
    )


def _decimal_to_float(value: Decimal | None, default: float) -> float:
    return default if value is None else float(value)
