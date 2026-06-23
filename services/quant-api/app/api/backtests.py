from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.engine import BacktestConfig, ContractSpec, run_su_bing_backtest
from app.db.session import get_db
from app.models.data_center import FeeMarginRule
from app.services.market_data_reader import MarketDataReader
from app.strategy.su_bing_ema21 import SuBingParams

router = APIRouter(prefix="/api/backtests", tags=["backtests"])


class BacktestRunRequest(BaseModel):
    symbol: str
    contract: str
    period: str
    start: str
    end: str
    provider: str | None = None
    initial_capital: float = Field(default=100000.0, gt=0)
    risk_per_trade_pct: float = Field(default=0.01, gt=0, le=1)
    max_margin_usage_pct: float = Field(default=0.35, gt=0, le=1)
    slippage_ticks: int = Field(default=1, ge=0)
    take_profit_r: float = Field(default=2.0, gt=0)
    enable_take_profit: bool = True
    allow_warning_quality: bool = False
    strategy_params: dict[str, Any] = Field(default_factory=dict)


@router.post("/run")
def run_backtest(request: BacktestRunRequest, session: Session = Depends(get_db)) -> dict[str, Any]:
    start = _parse_query_datetime(request.start, end_of_day=False)
    end = _parse_query_datetime(request.end, end_of_day=True)
    if start >= end:
        raise HTTPException(status_code=422, detail="start must be before end")

    reader = MarketDataReader(session)
    quality = reader.get_quality_status(
        symbol=request.symbol,
        contract=request.contract,
        period=request.period,
        start=start,
        end=end,
        provider=request.provider,
    )
    if quality["status"] == "failed":
        raise HTTPException(status_code=422, detail="data quality failed; backtest is rejected")
    if quality["status"] == "warning" and not request.allow_warning_quality:
        raise HTTPException(status_code=422, detail="data quality warning requires allow_warning_quality=true")

    bars = reader.load_bars(
        symbol=request.symbol,
        contract=request.contract,
        period=request.period,
        start=start,
        end=end,
        provider=request.provider,
    )
    if not bars:
        raise HTTPException(status_code=422, detail="no bars found for backtest")

    try:
        config = BacktestConfig(
            initial_capital=request.initial_capital,
            risk_per_trade_pct=request.risk_per_trade_pct,
            max_margin_usage_pct=request.max_margin_usage_pct,
            slippage_ticks=request.slippage_ticks,
            take_profit_r=request.take_profit_r,
            enable_take_profit=request.enable_take_profit,
            strategy_params=SuBingParams(**request.strategy_params),
        )
        report = run_su_bing_backtest(
            bars=bars,
            config=config,
            contract_spec=load_contract_spec(session, request.symbol, request.contract),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    payload = report.to_dict()
    payload["quality_status"] = quality
    return payload


def load_contract_spec(session: Session, symbol: str, contract: str) -> ContractSpec:
    rules = list(
        session.scalars(
            select(FeeMarginRule).where(
                (FeeMarginRule.contract_code == contract)
                | ((FeeMarginRule.contract_code.is_(None)) & (FeeMarginRule.instrument_symbol == symbol))
            )
        )
    )
    if not rules:
        return ContractSpec()
    rules.sort(key=lambda rule: (rule.contract_code == contract, rule.effective_date or date.min), reverse=True)
    rule = rules[0]
    return ContractSpec(
        price_tick=_decimal_to_float(rule.price_tick, 1.0),
        volume_multiple=rule.volume_multiple or 10,
        margin_rate=_decimal_to_float(rule.margin_rate, 0.10),
        open_fee=_decimal_to_float(rule.open_fee, 0.0001),
        close_fee=_decimal_to_float(rule.close_fee, 0.0001),
        close_today_fee=None if rule.close_today_fee is None else float(rule.close_today_fee),
        fee_type="fixed" if rule.fee_type in {"fixed", "fixed_per_lot", "per_lot"} else "rate",
        source=rule.source or rule.provider,
    )


def _decimal_to_float(value: Decimal | None, default: float) -> float:
    return default if value is None else float(value)


def _parse_query_datetime(value: str, end_of_day: bool) -> datetime:
    try:
        if len(value) == 10:
            parsed_date = date.fromisoformat(value)
            parsed = datetime.combine(parsed_date, time.max if end_of_day else time.min)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid datetime: {value}") from exc
    return parsed.replace(tzinfo=None)

