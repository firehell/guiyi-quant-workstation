from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.backtest.contract_resolver import CommissionRule, ResolvedContract, resolve_jm_contract, resolve_jm_trade_contract_timeline
from app.backtest.v1b_jm_tasks import JM_V1B_STRATEGY_CODE, SU_BING_JM_V1B_SHORT_HOLD_STRATEGY_CODE
from app.schemas.backtest import BacktestTaskConfig
from app.vnpy_integration.errors import BacktestConfigurationError

DELIVERY_RISK_EXIT = "delivery_risk_exit"
MAIN_CONTRACT_ROLL_EXIT = "main_contract_roll_exit"
JM_V1B_ENRICHED_STRATEGY_CODES = {JM_V1B_STRATEGY_CODE, SU_BING_JM_V1B_SHORT_HOLD_STRATEGY_CODE}


@dataclass(frozen=True)
class _ResearchBar:
    index: int
    dt: datetime
    open_price: float


@dataclass(frozen=True)
class _ForcedExit:
    dt: datetime
    price: float
    exit_reason: str
    rollover_forced_exit: bool
    delivery_risk_exit: bool
    rollover_reason: str


class _BlockedTradeError(BacktestConfigurationError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def should_enrich_jm_v1b_result(config: BacktestTaskConfig) -> bool:
    return config.strategy_code in JM_V1B_ENRICHED_STRATEGY_CODES and config.symbol.lower().startswith("jm")


def enrich_jm_v1b_result(session: Session, config: BacktestTaskConfig, normalized_result: dict[str, Any]) -> dict[str, Any]:
    result = dict(normalized_result)
    trades = [dict(trade) for trade in result.get("trades") or []]
    summary = dict(result.get("summary") or {})

    enriched_trades = []
    warnings = list(result.get("warnings") or [])
    blocked_entry_count = 0
    research_bars: list[_ResearchBar] | None = None
    for trade in trades:
        try:
            enriched_trades.append(_enrich_trade(session, config, trade, research_bars=research_bars))
        except _BlockedTradeError as exc:
            blocked_entry_count += 1
            warnings.append({"code": exc.reason, "message": str(exc)})
            continue
        except _RequiresResearchBarsError:
            research_bars = _load_research_bars(config)
            enriched_trades.append(_enrich_trade(session, config, trade, research_bars=research_bars))
    summary = _summary_with_real_contract_costs(summary, enriched_trades, config)
    summary["blocked_delivery_window_entry_count"] = blocked_entry_count
    summary.setdefault("real_contract_enrichment", {})
    summary["real_contract_enrichment"].update(
        {
            "enabled": True,
            "strategy_code": config.strategy_code,
            "research_symbol": config.symbol,
            "continuous_symbol": config.symbol,
            "execution_contract_source": "main_contract_map",
            "parameter_source": "resolver",
        }
    )

    metadata = dict(result.get("metadata") or {})
    metadata.update(
        {
            "real_contract_enriched": True,
            "research_symbol": config.symbol,
            "continuous_symbol": config.symbol,
            "execution_contract_source": "main_contract_map",
        }
    )
    result["summary"] = summary
    result["trades"] = enriched_trades
    result["warnings"] = warnings
    result["metadata"] = metadata
    return result


class _RequiresResearchBarsError(Exception):
    pass


def _enrich_trade(
    session: Session,
    config: BacktestTaskConfig,
    trade: dict[str, Any],
    *,
    research_bars: list[_ResearchBar] | None,
) -> dict[str, Any]:
    entry_time = _trade_time(trade, "entry_datetime", "open_time", "datetime")
    exit_time = _trade_time(trade, "exit_datetime", "close_time", "datetime")
    entry_price = _required_float(trade.get("entry_price") or trade.get("open_price") or trade.get("price"), "entry_price")
    exit_price = _required_float(trade.get("exit_price") or trade.get("close_price") or trade.get("price"), "exit_price")
    volume = _trade_volume(trade, config)
    direction = str(trade.get("direction") or "").strip().lower()
    direction_sign = _direction_sign(direction)

    entry_contract = resolve_jm_contract(session, moment=entry_time)
    forced_exit = _forced_exit(session, entry=entry_contract, entry_time=entry_time, planned_exit_time=exit_time, research_bars=research_bars)
    original_exit_reason = trade.get("exit_reason")
    if forced_exit is not None:
        exit_time = forced_exit.dt
        exit_price = forced_exit.price

    timeline = resolve_jm_trade_contract_timeline(session, entry_time=entry_time, exit_time=exit_time)
    entry = timeline.entry
    exit_ = timeline.exit
    multiplier = entry.contract_multiplier

    gross_pnl = direction_sign * (exit_price - entry_price) * volume * multiplier
    commission = _commission(entry, exit_, entry_price=entry_price, exit_price=exit_price, volume=volume, entry_time=entry_time, exit_time=exit_time)
    slippage = 2 * float(config.slippage) * entry.price_tick * volume * multiplier
    net_pnl = gross_pnl - commission - slippage
    turnover = (entry_price + exit_price) * volume * multiplier
    margin_required = entry_price * volume * multiplier * entry.margin_ratio
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
            "price_tick": entry.price_tick,
            "commission": commission,
            "slippage": slippage,
            "margin_ratio": entry.margin_ratio,
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
            "entry_price": entry_price,
            "exit_price": exit_price,
            "research_symbol": config.symbol,
            "continuous_symbol": config.symbol,
            "resolver_last_allowed_holding_date": entry.last_allowed_holding_date.isoformat(),
            "resolver_exit_last_allowed_holding_date": exit_.last_allowed_holding_date.isoformat(),
        }
    )
    if forced_exit is not None:
        enriched.update(
            {
                "exit_reason": forced_exit.exit_reason,
                "rollover_forced_exit": forced_exit.rollover_forced_exit,
                "delivery_risk_exit": forced_exit.delivery_risk_exit,
                "rollover_reason": forced_exit.rollover_reason,
                "original_exit_reason": original_exit_reason,
            }
        )
    else:
        enriched.setdefault("rollover_forced_exit", False)
        enriched.setdefault("delivery_risk_exit", False)
    return enriched


def _forced_exit(
    session: Session,
    *,
    entry: ResolvedContract,
    entry_time: datetime,
    planned_exit_time: datetime,
    research_bars: list[_ResearchBar] | None,
) -> _ForcedExit | None:
    if entry_time.date() >= entry.last_allowed_holding_date:
        raise _BlockedTradeError(
            "blocked_delivery_window_entry",
            (
                f"JM V1-B blocks new entries for {entry.actual_contract} on {entry_time.date()} "
                f"because last_allowed_holding_date is {entry.last_allowed_holding_date}"
            ),
        )
    needs_bars = planned_exit_time.date() > entry.last_allowed_holding_date
    needs_bars = needs_bars or _planned_exit_contract_changes(session, entry=entry, planned_exit_time=planned_exit_time)
    if not needs_bars:
        return None
    if research_bars is None:
        raise _RequiresResearchBarsError

    delivery_candidate = _delivery_forced_exit(entry=entry, entry_time=entry_time, planned_exit_time=planned_exit_time, research_bars=research_bars)
    roll_scan_end = delivery_candidate.dt if delivery_candidate is not None else planned_exit_time
    roll_candidate = _main_roll_forced_exit(
        session,
        entry=entry,
        entry_time=entry_time,
        planned_exit_time=roll_scan_end,
        research_bars=research_bars,
    )
    candidates = [candidate for candidate in (delivery_candidate, roll_candidate) if candidate is not None]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item.dt, item.exit_reason != DELIVERY_RISK_EXIT))
    return candidates[0]


def _planned_exit_contract_changes(session: Session, *, entry: ResolvedContract, planned_exit_time: datetime) -> bool:
    planned_exit = resolve_jm_contract(session, moment=planned_exit_time)
    return planned_exit.actual_contract != entry.actual_contract


def _delivery_forced_exit(
    *,
    entry: ResolvedContract,
    entry_time: datetime,
    planned_exit_time: datetime,
    research_bars: list[_ResearchBar],
) -> _ForcedExit | None:
    if planned_exit_time.date() <= entry.last_allowed_holding_date:
        return None
    bar = _latest_bar_between(
        research_bars,
        after=entry_time,
        before=planned_exit_time,
        max_date=entry.last_allowed_holding_date,
    )
    if bar is None:
        raise BacktestConfigurationError(
            f"JM V1-B cannot force delivery-risk exit for {entry.actual_contract}: no next-open bar before {entry.last_allowed_holding_date}"
        )
    return _ForcedExit(
        dt=bar.dt,
        price=bar.open_price,
        exit_reason=DELIVERY_RISK_EXIT,
        rollover_forced_exit=False,
        delivery_risk_exit=True,
        rollover_reason=f"last_allowed_holding_date={entry.last_allowed_holding_date.isoformat()}",
    )


def _main_roll_forced_exit(
    session: Session,
    *,
    entry: ResolvedContract,
    entry_time: datetime,
    planned_exit_time: datetime,
    research_bars: list[_ResearchBar],
) -> _ForcedExit | None:
    previous_old_bar: _ResearchBar | None = None
    resolved_by_day: dict[date, ResolvedContract] = {entry.trading_day: entry}
    for bar in research_bars:
        if bar.dt <= entry_time or bar.dt > planned_exit_time:
            continue
        resolved = resolved_by_day.get(bar.dt.date())
        if resolved is None:
            resolved = resolve_jm_contract(session, moment=bar.dt)
            resolved_by_day[bar.dt.date()] = resolved
        if resolved.actual_contract == entry.actual_contract:
            previous_old_bar = bar
            continue
        if previous_old_bar is None:
            raise _BlockedTradeError(
                "blocked_main_contract_roll_window_entry",
                (
                    f"JM V1-B blocks new entries for {entry.actual_contract} at {entry_time.isoformat()} "
                    f"because the next research bar is already main contract {resolved.actual_contract}"
                ),
            )
        return _ForcedExit(
            dt=previous_old_bar.dt,
            price=previous_old_bar.open_price,
            exit_reason=MAIN_CONTRACT_ROLL_EXIT,
            rollover_forced_exit=True,
            delivery_risk_exit=False,
            rollover_reason=f"main_contract_changed:{entry.actual_contract}->{resolved.actual_contract}",
        )
    return None


def _latest_bar_between(
    research_bars: list[_ResearchBar],
    *,
    after: datetime,
    before: datetime,
    max_date: date,
) -> _ResearchBar | None:
    eligible = [bar for bar in research_bars if after < bar.dt < before and bar.dt.date() <= max_date]
    return eligible[-1] if eligible else None


def _load_research_bars(config: BacktestTaskConfig) -> list[_ResearchBar]:
    path = Path(config.bar_data_path)
    if not path.exists():
        raise BacktestConfigurationError(f"JM V1-B research bar_data_path missing for forced exits: {path}")
    try:
        frame = pd.read_parquet(path, columns=["datetime", "open"])
    except Exception as exc:
        raise BacktestConfigurationError(f"JM V1-B cannot read research bars for forced exits: {path}") from exc
    missing = {"datetime", "open"} - set(frame.columns)
    if missing:
        raise BacktestConfigurationError(f"JM V1-B research bars missing columns for forced exits: {', '.join(sorted(missing))}")

    bars: list[_ResearchBar] = []
    for index, row in enumerate(frame.sort_values("datetime").itertuples(index=False)):
        bar_time = _parse_datetime(getattr(row, "datetime"))
        bars.append(_ResearchBar(index=index, dt=bar_time, open_price=_required_float(getattr(row, "open"), "bar.open")))
    if not bars:
        raise BacktestConfigurationError("JM V1-B research bars are empty; forced exits cannot be evaluated")
    return bars


def _summary_with_real_contract_costs(summary: dict[str, Any], trades: list[dict[str, Any]], config: BacktestTaskConfig) -> dict[str, Any]:
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
            "rollover_exit_count": sum(1 for trade in trades if trade.get("rollover_forced_exit")),
            "delivery_risk_exit_count": sum(1 for trade in trades if trade.get("delivery_risk_exit")),
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
        return price * volume * multiplier * fee
    return volume * fee


def _commission_rule_payload(contract: ResolvedContract) -> dict[str, Any]:
    return {
        "parameter_source": contract.parameter_source,
        "fee_type": contract.commission_rule.fee_type,
        "open_fee": contract.commission_rule.open_fee,
        "close_fee": contract.commission_rule.close_fee,
        "close_today_fee": contract.commission_rule.close_today_fee,
    }


def _parameter_source(entry: ResolvedContract, exit_: ResolvedContract) -> str:
    if entry.parameter_source == exit_.parameter_source:
        return entry.parameter_source
    return "mixed"


def _trade_time(trade: dict[str, Any], *keys: str) -> datetime:
    for key in keys:
        value = trade.get(key)
        if value not in (None, ""):
            return _parse_datetime(value)
    raise BacktestConfigurationError(f"JM V1-B trade missing time fields: {', '.join(keys)}")


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _trade_volume(trade: dict[str, Any], config: BacktestTaskConfig) -> int:
    value = trade.get("volume") or config.strategy_parameters.get("fixed_size") or 1
    volume = int(_required_float(value, "volume"))
    if volume <= 0:
        raise BacktestConfigurationError("JM V1-B trade volume must be greater than zero")
    return volume


def _direction_sign(direction: str) -> int:
    if direction in {"long", "多", "buy"}:
        return 1
    if direction in {"short", "空", "sell"}:
        return -1
    raise BacktestConfigurationError(f"JM V1-B trade direction is unsupported: {direction!r}")


def _required_float(value: Any, name: str) -> float:
    if value in (None, ""):
        raise BacktestConfigurationError(f"JM V1-B trade missing numeric field: {name}")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise BacktestConfigurationError(f"JM V1-B trade invalid numeric field: {name}={value!r}") from exc


def _summary_float(summary: dict[str, Any], *keys: str, default: float) -> float:
    for key in keys:
        value = summary.get(key)
        if value not in (None, ""):
            return _required_float(value, key)
    return default
