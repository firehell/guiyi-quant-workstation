from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.data_center import FeeMarginRule, FuturesTradingParameter, MainContractMap


PROVIDER = "rqdata"
RULE = "volume_open_interest"
RANK = 1


def load_effective_main_contract_mapping(
    session: Session,
    *,
    instrument_symbol: str,
    trade_date: date | None,
    provider: str = PROVIDER,
    rule: str = RULE,
    rank: int = RANK,
) -> MainContractMap | None:
    query = select(MainContractMap).where(
        func.lower(MainContractMap.instrument_symbol) == instrument_symbol.strip().lower(),
        MainContractMap.provider == provider,
        MainContractMap.rule == rule,
        MainContractMap.rank == rank,
    )
    if trade_date is not None:
        query = query.where(MainContractMap.trade_date == trade_date)
    return session.scalar(
        query.order_by(
            MainContractMap.trade_date.desc(),
            MainContractMap.created_at.desc(),
            MainContractMap.id.desc(),
        ).limit(1)
    )


def load_effective_trading_parameters(
    session: Session,
    *,
    contract_code: str,
    trade_date: date,
    provider: str = PROVIDER,
) -> FuturesTradingParameter | None:
    return session.scalar(
        select(FuturesTradingParameter)
        .where(
            FuturesTradingParameter.contract_code == contract_code,
            FuturesTradingParameter.trade_date == trade_date,
            FuturesTradingParameter.provider == provider,
        )
        .order_by(
            FuturesTradingParameter.created_at.desc(),
            FuturesTradingParameter.id.desc(),
        )
        .limit(1)
    )


def load_effective_fee_margin_rule(
    session: Session,
    *,
    contract_code: str,
    instrument_symbol: str,
    exchange_code: str,
    trade_date: date,
    provider: str = PROVIDER,
) -> FeeMarginRule | None:
    rows = list(
        session.scalars(
            select(FeeMarginRule).where(
                FeeMarginRule.provider == provider,
                FeeMarginRule.exchange_code == exchange_code,
                (FeeMarginRule.contract_code == contract_code)
                | (
                    FeeMarginRule.contract_code.is_(None)
                    & (func.lower(FeeMarginRule.instrument_symbol) == instrument_symbol.strip().lower())
                ),
                FeeMarginRule.effective_date.is_(None)
                | (FeeMarginRule.effective_date <= trade_date),
            )
        )
    )
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: (
            row.contract_code == contract_code,
            row.effective_date or date.min,
            row.created_at,
            row.id,
        ),
    )
