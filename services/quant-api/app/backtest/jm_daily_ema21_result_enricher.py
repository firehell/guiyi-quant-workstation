from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy.orm import Session

from app.backtest.contract_resolver import CommissionRule, ResolvedContract, resolve_jm_trade_contract_timeline
from app.backtest.v1b_jm_tasks import JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CODE
from app.schemas.backtest import BacktestTaskConfig
from app.vnpy_integration.errors import BacktestConfigurationError


def should_enrich_jm_daily_ema21_result(config: BacktestTaskConfig) -> bool:
    return config.strategy_code == JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CODE and config.interval == "1d" and config.symbol.lower().startswith("jm")


def enrich_jm_daily_ema21_result(session: Session, config: BacktestTaskConfig, normalized_result: dict[str, Any]) -> dict[str, Any]:
    result = dict(normalized_result)
    trades = [dict(trade) for trade in result.get("trades") or []]
    enriched_trades = [_enrich_trade(session, config, trade) for trade in trades]
    summary = _summary_with_daily_real_contract_costs(dict(result.get("summary") or {}), enriched_trades, config)
    review_context = _strategy_review_context(config)
    if review_context:
        summary["strategy_review_context"] = review_context
    summary.setdefault("real_contract_enrichment", {})
    summary["real_contract_enrichment"].update(
        {
            "enabled": True,
            "strategy_code": JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CODE,
            "research_symbol": config.symbol,
            "continuous_symbol": config.symbol,
            "execution_contract_source": "main_contract_map",
            "parameter_source": "resolver",
            "forced_rollover_exit_policy": "not_applied_for_daily_v0_2_0",
        }
    )

    metadata = dict(result.get("metadata") or {})
    metadata.update(
        {
            "real_contract_enriched": True,
            "strategy_code": JM_DAILY_EMA21_MACD_VOLUME_STRATEGY_CODE,
            "execution_contract_source": "main_contract_map",
        }
    )
    result["summary"] = summary
    result["trades"] = enriched_trades
    result["metadata"] = metadata
    return result


def _enrich_trade(session: Session, config: BacktestTaskConfig, trade: dict[str, Any]) -> dict[str, Any]:
    entry_time = _trade_time(trade, "fill_datetime", "entry_datetime", "entry_time", "open_time", "datetime")
    exit_time = _trade_time(trade, "exit_fill_datetime", "exit_datetime", "exit_time", "close_time", "datetime")
    entry_price = _required_float(trade.get("entry_price") or trade.get("open_price") or trade.get("price"), "entry_price")
    exit_price = _required_float(trade.get("exit_price") or trade.get("close_price") or trade.get("price"), "exit_price")
    volume = _trade_volume(trade)
    direction = str(trade.get("direction") or "").strip().lower()
    direction_sign = _direction_sign(direction)

    timeline = resolve_jm_trade_contract_timeline(session, entry_time=entry_time, exit_time=exit_time)
    entry = timeline.entry
    exit_ = timeline.exit
    multiplier = entry.contract_multiplier
    gross_pnl = direction_sign * (exit_price - entry_price) * volume * multiplier
    commission = _commission(entry, exit_, entry_price=entry_price, exit_price=exit_price, volume=volume, entry_time=entry_time, exit_time=exit_time)
    slippage = 2 * float(config.slippage) * float(entry.price_tick) * volume * multiplier
    net_pnl = gross_pnl - commission - slippage
    turnover = (entry_price + exit_price) * volume * multiplier
    margin_required = entry_price * volume * multiplier * float(entry.margin_ratio)
    contract_code = entry.actual_contract if entry.actual_contract == exit_.actual_contract else f"{entry.actual_contract}->{exit_.actual_contract}"

    enriched = dict(trade)
    enriched.update(
        {
            "symbol": "jm",
            "contract": contract_code,
            "contract_code": contract_code,
            "entry_contract": entry.actual_contract,
            "exit_contract": exit_.actual_contract,
            "entry_contract_month": entry.contract_month,
            "exit_contract_month": exit_.contract_month,
            "contract_multiplier": multiplier,
            "price_tick": float(entry.price_tick),
            "commission": commission,
            "slippage": slippage,
            "margin_ratio": float(entry.margin_ratio),
            "margin_required": margin_required,
            "parameter_source": _parameter_source(entry, exit_),
            "fee_rule_source": {"entry": _commission_rule_payload(entry), "exit": _commission_rule_payload(exit_)},
            "main_contract_source": {"entry": asdict(entry.main_contract_source), "exit": asdict(exit_.main_contract_source)},
            "turnover": turnover,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "return_pct": net_pnl / max(entry_price * volume * multiplier, 1e-9),
            "volume": volume,
            "entry_datetime": entry_time.isoformat(),
            "exit_datetime": exit_time.isoformat(),
            "open_time": entry_time.isoformat(),
            "close_time": exit_time.isoformat(),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "open_price": entry_price,
            "close_price": exit_price,
            "entry_signal_time": trade.get("entry_signal_time") or trade.get("signal_datetime"),
            "exit_signal_time": trade.get("exit_signal_time") or trade.get("exit_signal_datetime"),
            "research_symbol": config.symbol,
            "continuous_symbol": config.symbol,
            "rollover_forced_exit": False,
            "delivery_risk_exit": False,
        }
    )
    return enriched


def _summary_with_daily_real_contract_costs(summary: dict[str, Any], trades: list[dict[str, Any]], config: BacktestTaskConfig) -> dict[str, Any]:
    initial_capital = _summary_float(summary, "initial_capital", "capital", default=config.capital)
    total_commission = sum(_required_float(trade.get("commission"), "commission") for trade in trades)
    total_slippage = sum(_required_float(trade.get("slippage"), "slippage") for trade in trades)
    total_net_pnl = sum(_required_float(trade.get("net_pnl"), "net_pnl") for trade in trades)
    final_equity = initial_capital + total_net_pnl
    max_margin_required = max((_required_float(trade.get("margin_required"), "margin_required") for trade in trades), default=0.0)
    wins = [trade for trade in trades if _required_float(trade.get("net_pnl"), "net_pnl") > 0]
    losses = [trade for trade in trades if _required_float(trade.get("net_pnl"), "net_pnl") < 0]
    average_win = sum(_required_float(trade.get("net_pnl"), "net_pnl") for trade in wins) / len(wins) if wins else 0.0
    average_loss = abs(sum(_required_float(trade.get("net_pnl"), "net_pnl") for trade in losses) / len(losses)) if losses else 0.0

    summary.update(
        {
            "initial_capital": initial_capital,
            "capital": initial_capital,
            "final_equity": final_equity,
            "end_balance": final_equity,
            "ending_equity": final_equity,
            "total_return": total_net_pnl / initial_capital if initial_capital else 0.0,
            "total_commission": total_commission,
            "total_slippage": total_slippage,
            "total_net_pnl": total_net_pnl,
            "trade_count": len(trades),
            "total_trade_count": len(trades),
            "total_trades": len(trades),
            "win_rate": len(wins) / len(trades) if trades else 0.0,
            "profit_loss_ratio": average_win / average_loss if average_loss else 0.0,
            "expectancy": total_net_pnl / len(trades) if trades else 0.0,
            "max_margin_required": max_margin_required,
            "max_margin_usage_pct": max_margin_required / initial_capital if initial_capital else 0.0,
            "rollover_exit_count": 0,
            "delivery_risk_exit_count": 0,
        }
    )
    return summary


def _commission(
    entry: ResolvedContract,
    exit_: ResolvedContract,
    *,
    entry_price: float,
    exit_price: float,
    volume: int,
    entry_time: datetime,
    exit_time: datetime,
) -> float:
    open_fee = _leg_commission(entry.commission_rule, price=entry_price, volume=volume, multiplier=entry.contract_multiplier, close=False)
    close_rule = exit_.commission_rule
    close_fee_value = close_rule.close_today_fee if entry_time.date() == exit_time.date() and close_rule.close_today_fee is not None else close_rule.close_fee
    close_fee = _leg_commission(
        CommissionRule(fee_type=close_rule.fee_type, open_fee=close_rule.open_fee, close_fee=close_fee_value, close_today_fee=close_rule.close_today_fee),
        price=exit_price,
        volume=volume,
        multiplier=exit_.contract_multiplier,
        close=True,
    )
    return open_fee + close_fee


def _leg_commission(rule: CommissionRule, *, price: float, volume: int, multiplier: int, close: bool) -> float:
    fee = rule.close_fee if close else rule.open_fee
    if rule.fee_type == "rate":
        return price * volume * multiplier * float(fee)
    return volume * float(fee)


def _commission_rule_payload(contract: ResolvedContract) -> dict[str, Any]:
    return {
        "parameter_source": contract.parameter_source,
        "fee_type": contract.commission_rule.fee_type,
        "open_fee": float(contract.commission_rule.open_fee),
        "close_fee": float(contract.commission_rule.close_fee),
        "close_today_fee": (
            float(contract.commission_rule.close_today_fee)
            if contract.commission_rule.close_today_fee is not None
            else None
        ),
    }


def _parameter_source(entry: ResolvedContract, exit_: ResolvedContract) -> str:
    if entry.parameter_source == exit_.parameter_source:
        return entry.parameter_source
    return "mixed"


def _strategy_review_context(config: BacktestTaskConfig) -> dict[str, Any] | None:
    context = config.request_payload.get("strategy_review_context")
    return context if isinstance(context, dict) else None


def _trade_time(trade: dict[str, Any], *keys: str) -> datetime:
    for key in keys:
        value = trade.get(key)
        if value not in (None, ""):
            return _parse_datetime(value)
    raise BacktestConfigurationError(f"JM daily EMA21 trade missing time fields: {', '.join(keys)}")


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _trade_volume(trade: dict[str, Any]) -> int:
    volume = int(_required_float(trade.get("volume") or 1, "volume"))
    if volume <= 0:
        raise BacktestConfigurationError("JM daily EMA21 trade volume must be greater than zero")
    return volume


def _direction_sign(direction: str) -> int:
    if direction in {"long", "多", "buy"}:
        return 1
    if direction in {"short", "空", "sell"}:
        return -1
    raise BacktestConfigurationError(f"JM daily EMA21 trade direction is unsupported: {direction!r}")


def _required_float(value: Any, name: str) -> float:
    if value in (None, ""):
        raise BacktestConfigurationError(f"JM daily EMA21 trade missing numeric field: {name}")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise BacktestConfigurationError(f"JM daily EMA21 trade invalid numeric field: {name}={value!r}") from exc


def _summary_float(summary: dict[str, Any], *keys: str, default: float) -> float:
    for key in keys:
        value = summary.get(key)
        if value not in (None, ""):
            return _required_float(value, key)
    return default
