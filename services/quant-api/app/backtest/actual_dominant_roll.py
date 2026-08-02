from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from sqlalchemy.orm import Session

from app.backtest.contract_resolver import (
    ContractResolutionError,
    ResolvedContract,
    resolve_jm_contract,
)


ROLL_BOUNDARY_REASON = "contract_roll_boundary"
ROLL_REOPEN_REASON = "contract_roll_reopen"
_PENDING_ORDER_STATUSES = {
    "pending",
    "submitting",
    "not_traded",
    "nottraded",
    "part_traded",
    "parttraded",
}


@dataclass(frozen=True, slots=True)
class _RollBoundary:
    old_bar: Mapping[str, Any]
    new_bar: Mapping[str, Any]
    old_contract: ResolvedContract
    new_contract: ResolvedContract


class MainContractMappingKnowledgeError(ContractResolutionError):
    """Raised when a rank-1 mapping lacks decision-time availability evidence."""


def apply_actual_dominant_roll_accounting(
    session: Session,
    normalized_result: Mapping[str, Any],
    *,
    bars: Sequence[Mapping[str, Any]],
    slippage_ticks: Decimal | int | str,
) -> dict[str, Any]:
    """Split open exposure at actual-dominant boundaries using Decimal costs."""
    ordered_bars = sorted((dict(bar) for bar in bars), key=_bar_time)
    if not ordered_bars:
        raise ContractResolutionError("actual_dominant backtest bars are empty")
    ticks = _decimal(slippage_ticks, field="slippage_ticks")
    if ticks < 0:
        raise ContractResolutionError("slippage_ticks cannot be negative")

    resolved_by_day = _resolve_and_validate_contract_days(session, ordered_bars)
    boundaries = _roll_boundaries(ordered_bars, resolved_by_day)
    orders = _cancel_pending_old_contract_orders(
        list(normalized_result.get("orders") or []),
        boundaries,
        runtime_cancellations=list(
            normalized_result.get("contract_roll_cancellations") or []
        ),
    )

    trades: list[dict[str, Any]] = []
    roll_events: list[dict[str, Any]] = []
    for raw_trade in list(normalized_result.get("trades") or []):
        trade = dict(raw_trade)
        entry_time = _trade_time(trade, "entry_datetime", "entry_time", "open_time")
        exit_time = _trade_time(trade, "exit_datetime", "exit_time", "close_time")
        intersecting = [
            boundary
            for boundary in boundaries
            if entry_time <= _bar_time(boundary.old_bar)
            and bar_open_time(boundary.new_bar) <= exit_time
        ]
        if not intersecting:
            trades.append(trade)
            continue
        split, events = _split_trade(
            trade,
            entry_time=entry_time,
            exit_time=exit_time,
            boundaries=intersecting,
            resolved_by_day=resolved_by_day,
            bars=ordered_bars,
            slippage_ticks=ticks,
        )
        trades.extend(split)
        roll_events.extend(events)

    for sequence, trade in enumerate(trades, start=1):
        trade["sequence"] = sequence

    result = dict(normalized_result)
    result["trades"] = trades
    result["orders"] = orders
    result["roll_events"] = roll_events
    metadata = dict(result.get("metadata") or {})
    metadata.update(
        {
            "contract_semantics": "actual_dominant_rank1",
            "roll_policy": "close_last_confirmed_close_reopen_first_confirmed_open_v1",
            "roll_event_count": len(roll_events),
            "monetary_derivation": "decimal",
        }
    )
    result["metadata"] = metadata
    return result


def validate_actual_dominant_inputs(
    session: Session,
    bars: Sequence[Mapping[str, Any]],
) -> None:
    """Fail before strategy execution when roll inputs are not decision-safe."""
    ordered_bars = sorted((dict(bar) for bar in bars), key=_bar_time)
    if not ordered_bars:
        raise ContractResolutionError("actual_dominant backtest bars are empty")
    resolved_by_day = _resolve_and_validate_contract_days(session, ordered_bars)
    _roll_boundaries(ordered_bars, resolved_by_day)


def _resolve_and_validate_contract_days(
    session: Session,
    bars: Sequence[Mapping[str, Any]],
) -> dict[date, ResolvedContract]:
    resolved: dict[date, ResolvedContract] = {}
    for bar in bars:
        trading_day = _bar_trading_day(bar)
        contract = _bar_contract(bar)
        day_contract = resolved.get(trading_day)
        if day_contract is None:
            day_contract = resolve_jm_contract(
                session,
                trading_day=trading_day,
                rank=1,
            )
            known_at = day_contract.main_contract_source.known_at
            decision_time = bar_open_time(bar)
            if known_at is None:
                raise MainContractMappingKnowledgeError(
                    "main_contract_map raw_payload.known_at evidence is required"
                )
            normalized_known_at = _datetime(known_at, field="mapping.known_at")
            if normalized_known_at > decision_time:
                raise MainContractMappingKnowledgeError(
                    "main_contract_map known_at is later than first decision boundary: "
                    f"known_at={normalized_known_at.isoformat()}, "
                    f"decision_time={decision_time.isoformat()}"
                )
            resolved[trading_day] = day_contract
        if day_contract.actual_contract != contract:
            raise ContractResolutionError(
                "actual_dominant bar contract does not match rank=1 mapping: "
                f"trading_day={trading_day}, bar={contract}, "
                f"mapping={day_contract.actual_contract}"
            )
    return resolved


def _roll_boundaries(
    bars: Sequence[Mapping[str, Any]],
    resolved_by_day: Mapping[date, ResolvedContract],
) -> list[_RollBoundary]:
    boundaries: list[_RollBoundary] = []
    for old_bar, new_bar in zip(bars, bars[1:]):
        old_contract = _bar_contract(old_bar)
        new_contract = _bar_contract(new_bar)
        if old_contract == new_contract:
            continue
        _decimal(old_bar.get("close"), field="old_contract_last_confirmed_close")
        _decimal(new_bar.get("open"), field="new_contract_first_confirmed_open")
        boundaries.append(
            _RollBoundary(
                old_bar=old_bar,
                new_bar=new_bar,
                old_contract=resolved_by_day[_bar_trading_day(old_bar)],
                new_contract=resolved_by_day[_bar_trading_day(new_bar)],
            )
        )
    return boundaries


def _split_trade(
    trade: dict[str, Any],
    *,
    entry_time: datetime,
    exit_time: datetime,
    boundaries: Sequence[_RollBoundary],
    resolved_by_day: Mapping[date, ResolvedContract],
    bars: Sequence[Mapping[str, Any]],
    slippage_ticks: Decimal,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    direction = str(trade.get("direction") or "").strip().lower()
    if direction not in {"long", "short"}:
        raise ContractResolutionError("roll trade direction must be long or short")
    direction_sign = Decimal("1") if direction == "long" else Decimal("-1")
    volume = _positive_int(trade.get("volume"), field="trade.volume")
    entry_price = _decimal(
        trade.get("entry_price", trade.get("open_price")), field="trade.entry_price"
    )
    exit_price = _decimal(
        trade.get("exit_price", trade.get("close_price")), field="trade.exit_price"
    )
    entry_contract = _contract_for_time(bars, entry_time)
    exit_contract = _contract_for_time(bars, exit_time)
    entry_params = resolved_by_day[_trading_day_for_time(bars, entry_time)]
    exit_params = resolved_by_day[_trading_day_for_time(bars, exit_time)]
    if entry_params.actual_contract != entry_contract or exit_params.actual_contract != exit_contract:
        raise ContractResolutionError("trade contract does not match rank=1 mapping")

    points: list[tuple[datetime, Decimal, ResolvedContract, str]] = [
        (entry_time, entry_price, entry_params, str(trade.get("entry_reason") or "strategy_entry"))
    ]
    exits: list[tuple[datetime, Decimal, ResolvedContract, str]] = []
    events: list[dict[str, Any]] = []
    for boundary in boundaries:
        close_price = _decimal(
            boundary.old_bar.get("close"), field="old_contract_last_confirmed_close"
        )
        open_price = _decimal(
            boundary.new_bar.get("open"), field="new_contract_first_confirmed_open"
        )
        close_cost = _leg_costs(
            boundary.old_contract,
            price=close_price,
            volume=volume,
            close=True,
            close_today=(
                _trading_day_for_time(bars, points[-1][0])
                == _bar_trading_day(boundary.old_bar)
            ),
            slippage_ticks=slippage_ticks,
        )
        open_cost = _leg_costs(
            boundary.new_contract,
            price=open_price,
            volume=volume,
            close=False,
            close_today=False,
            slippage_ticks=slippage_ticks,
        )
        exits.append(
            (
                _bar_time(boundary.old_bar),
                close_price,
                boundary.old_contract,
                ROLL_BOUNDARY_REASON,
            )
        )
        points.append(
            (
                bar_open_time(boundary.new_bar),
                open_price,
                boundary.new_contract,
                ROLL_REOPEN_REASON,
            )
        )
        events.append(
            {
                "old_contract": boundary.old_contract.actual_contract,
                "new_contract": boundary.new_contract.actual_contract,
                "direction": direction,
                "volume": volume,
                "close_price": close_price,
                "open_price": open_price,
                "close_commission": close_cost["commission"],
                "open_commission": open_cost["commission"],
                "close_slippage": close_cost["slippage"],
                "open_slippage": open_cost["slippage"],
            }
        )
    exits.append(
        (
            exit_time,
            exit_price,
            exit_params,
            str(trade.get("exit_reason") or "strategy_exit"),
        )
    )

    segments: list[dict[str, Any]] = []
    base_trade_id = str(
        trade.get("trade_id") or trade.get("tradeid") or trade.get("trade_no") or "trade"
    )
    for index, (entry_point, exit_point) in enumerate(zip(points, exits), start=1):
        segment_entry_time, segment_entry_price, segment_entry_contract, entry_reason = entry_point
        segment_exit_time, segment_exit_price, segment_exit_contract, exit_reason = exit_point
        if segment_entry_contract.actual_contract != segment_exit_contract.actual_contract:
            raise ContractResolutionError("roll segment spans more than one actual contract")
        entry_cost = _leg_costs(
            segment_entry_contract,
            price=segment_entry_price,
            volume=volume,
            close=False,
            close_today=False,
            slippage_ticks=slippage_ticks,
        )
        exit_cost = _leg_costs(
            segment_exit_contract,
            price=segment_exit_price,
            volume=volume,
            close=True,
            close_today=(
                segment_entry_contract.trading_day
                == segment_exit_contract.trading_day
            ),
            slippage_ticks=slippage_ticks,
        )
        multiplier = Decimal(segment_entry_contract.contract_multiplier)
        gross_pnl = (
            direction_sign
            * (segment_exit_price - segment_entry_price)
            * Decimal(volume)
            * multiplier
        )
        commission = entry_cost["commission"] + exit_cost["commission"]
        slippage = entry_cost["slippage"] + exit_cost["slippage"]
        net_pnl = gross_pnl - commission - slippage
        turnover = (
            segment_entry_price + segment_exit_price
        ) * Decimal(volume) * multiplier
        margin_required = (
            segment_entry_price
            * Decimal(volume)
            * multiplier
            * _decimal(segment_entry_contract.margin_ratio, field="margin_ratio")
        )
        segment = dict(trade)
        segment.update(
            {
                "trade_id": f"{base_trade_id}:roll:{index}",
                "tradeid": f"{base_trade_id}:roll:{index}",
                "entry_datetime": segment_entry_time.isoformat(),
                "exit_datetime": segment_exit_time.isoformat(),
                "entry_time": segment_entry_time.isoformat(),
                "exit_time": segment_exit_time.isoformat(),
                "open_time": segment_entry_time.isoformat(),
                "close_time": segment_exit_time.isoformat(),
                "entry_price": segment_entry_price,
                "exit_price": segment_exit_price,
                "open_price": segment_entry_price,
                "close_price": segment_exit_price,
                "entry_contract": segment_entry_contract.actual_contract,
                "exit_contract": segment_exit_contract.actual_contract,
                "contract": segment_entry_contract.actual_contract,
                "contract_code": segment_entry_contract.actual_contract,
                "contract_multiplier": segment_entry_contract.contract_multiplier,
                "size": segment_entry_contract.contract_multiplier,
                "price_tick": _decimal(segment_entry_contract.price_tick, field="price_tick"),
                "margin_ratio": _decimal(segment_entry_contract.margin_ratio, field="margin_ratio"),
                "margin_required": margin_required,
                "entry_reason": entry_reason,
                "exit_reason": exit_reason,
                "gross_pnl": gross_pnl,
                "commission": commission,
                "slippage": slippage,
                "net_pnl": net_pnl,
                "turnover": turnover,
                "return_pct": net_pnl / (segment_entry_price * Decimal(volume) * multiplier),
                "parameter_source": segment_entry_contract.parameter_source,
                "fee_rule_source": {
                    "entry": _fee_rule_payload(segment_entry_contract),
                    "exit": _fee_rule_payload(segment_exit_contract),
                },
                "main_contract_source": {
                    "entry": asdict(segment_entry_contract.main_contract_source),
                    "exit": asdict(segment_exit_contract.main_contract_source),
                },
                "rollover_forced_exit": exit_reason == ROLL_BOUNDARY_REASON,
                "rollover_reason": (
                    f"{segment_entry_contract.actual_contract}->"
                    f"{points[index][2].actual_contract}"
                    if exit_reason == ROLL_BOUNDARY_REASON
                    else trade.get("rollover_reason")
                ),
            }
        )
        segments.append(segment)
    return segments, events


def _leg_costs(
    contract: ResolvedContract,
    *,
    price: Decimal,
    volume: int,
    close: bool,
    close_today: bool,
    slippage_ticks: Decimal,
) -> dict[str, Decimal]:
    rule = contract.commission_rule
    raw_fee = (
        rule.close_today_fee
        if close and close_today and rule.close_today_fee is not None
        else rule.close_fee if close else rule.open_fee
    )
    fee = _decimal(raw_fee, field="commission")
    multiplier = Decimal(contract.contract_multiplier)
    decimal_volume = Decimal(volume)
    commission = (
        price * decimal_volume * multiplier * fee
        if rule.fee_type == "rate"
        else decimal_volume * fee
    )
    slippage = (
        slippage_ticks
        * _decimal(contract.price_tick, field="price_tick")
        * decimal_volume
        * multiplier
    )
    return {"commission": commission, "slippage": slippage}


def _cancel_pending_old_contract_orders(
    orders: Sequence[Mapping[str, Any]],
    boundaries: Sequence[_RollBoundary],
    *,
    runtime_cancellations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    runtime_by_order: dict[str, dict[str, Any]] = {}
    for item in runtime_cancellations:
        order_no = str(item.get("order_no") or "")
        if not order_no:
            continue
        cancellation = dict(item)
        runtime_by_order[order_no] = cancellation
        runtime_by_order[order_no.rsplit(".", 1)[-1]] = cancellation
    output: list[dict[str, Any]] = []
    for original in orders:
        order = dict(original)
        runtime = runtime_by_order.get(_order_no(order))
        if runtime is not None:
            order["status"] = "cancelled"
            order["cancel_reason"] = ROLL_BOUNDARY_REASON
            order["reject_reason"] = ROLL_BOUNDARY_REASON
            order["cancelled_volume"] = runtime.get("cancelled_volume")
            output.append(order)
            continue
        status = str(order.get("status") or "").strip().lower()
        contract = str(
            order.get("contract")
            or order.get("contract_code")
            or order.get("symbol")
            or ""
        ).strip().upper()
        for boundary in boundaries:
            if (
                status in _PENDING_ORDER_STATUSES
                and contract == boundary.old_contract.actual_contract
            ):
                order["status"] = "cancelled"
                order["cancel_reason"] = ROLL_BOUNDARY_REASON
                order["reject_reason"] = ROLL_BOUNDARY_REASON
                volume = _decimal(order.get("volume") or 0, field="order.volume")
                traded = _decimal(order.get("traded") or 0, field="order.traded")
                order["cancelled_volume"] = max(volume - traded, Decimal("0"))
                break
        output.append(order)
    return output


def _order_no(order: Mapping[str, Any]) -> str:
    return str(
        order.get("order_id")
        or order.get("orderid")
        or order.get("order_no")
        or ""
    )


def _fee_rule_payload(contract: ResolvedContract) -> dict[str, Any]:
    return {
        "fee_type": contract.commission_rule.fee_type,
        "open_fee": _decimal(contract.commission_rule.open_fee, field="open_fee"),
        "close_fee": _decimal(contract.commission_rule.close_fee, field="close_fee"),
        "close_today_fee": (
            _decimal(contract.commission_rule.close_today_fee, field="close_today_fee")
            if contract.commission_rule.close_today_fee is not None
            else None
        ),
        "parameter_source": contract.parameter_source,
    }


def _contract_for_time(bars: Sequence[Mapping[str, Any]], moment: datetime) -> str:
    candidates = [bar for bar in bars if _bar_time(bar) <= moment]
    if not candidates:
        candidates = [bar for bar in bars if _bar_time(bar) >= moment]
    if not candidates:
        raise ContractResolutionError("trade time is outside canonical bars")
    return _bar_contract(candidates[-1] if _bar_time(candidates[-1]) <= moment else candidates[0])


def _trading_day_for_time(
    bars: Sequence[Mapping[str, Any]], moment: datetime
) -> date:
    candidates = [bar for bar in bars if _bar_time(bar) <= moment]
    if not candidates:
        candidates = [bar for bar in bars if _bar_time(bar) >= moment]
    if not candidates:
        raise ContractResolutionError("trade time is outside canonical bars")
    selected = candidates[-1] if _bar_time(candidates[-1]) <= moment else candidates[0]
    return _bar_trading_day(selected)


def _bar_time(bar: Mapping[str, Any]) -> datetime:
    value = bar.get("datetime") or bar.get("bar_end")
    return _datetime(value, field="bar.datetime")


def bar_open_time(bar: Mapping[str, Any]) -> datetime:
    bar_end = _bar_time(bar)
    frequency = str(bar.get("interval") or bar.get("period") or "").strip().lower()
    minutes = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "60m": 60,
        "1h": 60,
    }.get(frequency)
    if minutes is not None:
        return bar_end - timedelta(minutes=minutes)
    if frequency in {"1d", "d", "day", "1w", "w", "week"}:
        return bar_end
    raise ContractResolutionError(
        f"actual_dominant bar frequency cannot derive open time: {frequency!r}"
    )


def _bar_trading_day(bar: Mapping[str, Any]) -> date:
    value = bar.get("trading_day")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ContractResolutionError("bar.trading_day is invalid") from exc


def _bar_contract(bar: Mapping[str, Any]) -> str:
    value = bar.get("actual_contract") or bar.get("contract") or bar.get(
        "contract_or_series"
    )
    contract = str(value or "").strip().upper()
    if not contract:
        raise ContractResolutionError("actual_dominant bar contract is missing")
    return contract


def _trade_time(trade: Mapping[str, Any], *fields: str) -> datetime:
    for field in fields:
        if trade.get(field) not in (None, ""):
            return _datetime(trade[field], field=field)
    raise ContractResolutionError(f"trade time is missing: {', '.join(fields)}")


def _datetime(value: Any, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ContractResolutionError(f"{field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _decimal(value: Any, *, field: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ContractResolutionError(f"{field} is missing or invalid")
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ContractResolutionError(f"{field} is invalid") from exc


def _positive_int(value: Any, *, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ContractResolutionError(f"{field} is invalid") from exc
    if parsed <= 0:
        raise ContractResolutionError(f"{field} must be positive")
    return parsed


__all__ = [
    "ROLL_BOUNDARY_REASON",
    "ROLL_REOPEN_REASON",
    "apply_actual_dominant_roll_accounting",
    "bar_open_time",
    "validate_actual_dominant_inputs",
]
