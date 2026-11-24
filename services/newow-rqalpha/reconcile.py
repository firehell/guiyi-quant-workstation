"""Verify one-contract RQAlpha execution and project its auditable result."""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from math import isfinite
from typing import Any

from frozen_market import DailyFacts

QUANTUM = Decimal("0.00000001")
MONEY_LIMIT = Decimal("1e20")
ZERO = Decimal(0)
MONEY_POLICY = "cny_8_half_even_v1"


class ReconciliationError(ValueError):
    def __init__(self, code: str, field: str, *, expected: object = None, observed: object = None):
        super().__init__(f"{code} {field}")
        self.code = code
        self.field = field
        self.expected = expected
        self.observed = observed


def _economic_amount(value: Decimal, field: str) -> Decimal:
    if not value.is_finite() or abs(value) >= MONEY_LIMIT:
        raise ReconciliationError("MONEY_RANGE_INVALID", field, observed=value)
    result = value.quantize(QUANTUM, rounding=ROUND_HALF_EVEN)
    if value != result:
        raise ReconciliationError("MONEY_SCALE_UNSUPPORTED", field, expected=result, observed=value)
    return result if result else abs(result)


def _raw_float(value: float, field: str) -> dict[str, str]:
    if type(value) is not float or not isfinite(value):
        raise ReconciliationError("NATIVE_FLOAT_INVALID", field, observed=value)
    return {"repr": repr(value), "hex": value.hex()}


def _native_money(expected: Decimal, actual: float, field: str) -> tuple[str, dict[str, str]]:
    expected = _economic_amount(expected, field)
    raw = _raw_float(actual, field)
    exact = Decimal.from_float(actual)
    # Check the range before quantization so a corrupt native value cannot overflow the context.
    if abs(exact) >= MONEY_LIMIT or exact.quantize(QUANTUM, rounding=ROUND_HALF_EVEN) != expected:
        raise ReconciliationError(
            "NATIVE_MONEY_MISMATCH", field, expected=expected,
            observed={**raw, "exact_decimal": str(exact), "binary_delta": str(exact - expected)},
        )
    return format(expected, "f"), raw


def _native_exact(expected: float, actual: float, field: str) -> dict[str, str]:
    raw = _raw_float(actual, field)
    if expected.hex() != raw["hex"]:
        exact = Decimal.from_float(actual)
        raise ReconciliationError(
            "NATIVE_TRADE_MISMATCH", field, expected=expected.hex(),
            observed={
                **raw, "exact_decimal": str(exact),
                "binary_delta": str(exact - Decimal.from_float(expected)),
            },
        )
    return raw


def _source_price(value: Decimal, tick: Decimal, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0 or value % tick != 0:
        raise ReconciliationError("FROZEN_PRICE_INVALID", field, observed=value)
    return _economic_amount(value, field)


def _decimal_text(value: Decimal) -> str:
    return format(_economic_amount(value, "projection"), "f")


def _daily_facts(raw: dict, tick: Decimal) -> DailyFacts:
    try:
        facts = DailyFacts(**{field.name: raw[field.name] for field in fields(DailyFacts)})
    except KeyError as exc:
        raise ReconciliationError("DAILY_FACTS_MISSING", str(exc.args[0])) from exc
    except (ValueError, TypeError) as exc:
        raise ReconciliationError("DAILY_FACTS_INVALID", "daily_facts") from exc
    if type(facts.day) is not date:
        raise ReconciliationError("DAILY_FACTS_INVALID", "daily_facts.day")
    for name in ("prev_settlement", "settlement", "limit_up", "limit_down"):
        _source_price(getattr(facts, name), tick, f"daily_facts.{name}")
    return facts


@dataclass(slots=True)
class _OpenLot:
    entry_seq: int
    price: Decimal
    basis: Decimal
    fee: Decimal
    direction: str
    day: date

    def pnl_at(self, mark: Decimal, multiplier: int, *, since_entry: bool = True) -> Decimal:
        reference = self.price if since_entry else self.basis
        return (mark - reference) * multiplier * (1 if self.direction == "LONG" else -1)


def _commission(
    facts: DailyFacts, price: Decimal, multiplier: int, *, opening: bool, close_today: int,
) -> tuple[Decimal, float]:
    # Source facts give economic cost. The separate float witness follows the
    # exact operation order in RQAlpha 6.3.0 FuturesTransactionCostDecider.
    if opening:
        terms = ((1, facts.open_fee),)
    else:
        terms = ((1 - close_today, facts.close_fee), (close_today, facts.close_today_fee))
    economic, native = ZERO, 0.0
    for quantity, rate in terms:
        if facts.fee_type == "by_money":
            economic += price * quantity * multiplier * rate
            native += float(price) * quantity * multiplier * float(rate)
        else:
            economic += quantity * rate
            native += quantity * float(rate)
    return _economic_amount(economic, "trade.fee"), native


def _project_trade(
    fill: dict, attempt: dict, decision: dict, facts: DailyFacts, current: _OpenLot | None,
    *, seq: int, contract: str, tick: Decimal, multiplier: int,
) -> tuple[dict, Decimal, Decimal]:
    opening = fill["position_effect"] == "OPEN"
    direction = fill["direction"]
    close_today = 0 if opening or current is None else int(current.day == facts.day)
    side = "BUY" if (direction == "LONG") == opening else "SELL"
    effect = "OPEN" if opening else ("CLOSE_TODAY" if close_today else "CLOSE")
    candidate = attempt.get("frozen_candidate")
    if (
        direction not in ("LONG", "SHORT")
        or (opening and current is not None)
        or (not opening and (current is None or direction != current.direction))
        or fill["contract"] != contract or attempt["contract"] != contract
        or fill["side"] != side or attempt["native_side"] != side
        or fill["position_effect"] != effect or attempt["native_position_effect"] != effect
        or type(fill["quantity"]) is not int or fill["quantity"] != 1 or attempt["native_quantity"] != 1
        or fill["close_today_quantity"] != close_today
        or type(fill["native_close_today_amount"]) is not int
        or fill["native_close_today_amount"] not in ((0, 1) if opening else (close_today,))
        or attempt["action"] != ("BUILD" if opening else "CLEAR")
        or (opening and attempt["direction_requested"] != direction)
        or attempt["native_order_id"] != fill["native_order_id"]
        or attempt["native_status"] != "FILLED"
        or candidate is None
    ):
        raise ReconciliationError("TRADE_TRACE_INVALID", f"trade.{seq}")

    signal_at = attempt["signal_bar_end"]
    available = attempt["signal_available_at"]
    modeled_at = fill["modeled_fill_at"]
    native_at = fill["native_event_at"]
    minute = timedelta(minutes=1)
    if (
        not signal_at <= available < modeled_at
        or modeled_at != attempt["candidate_open_at"]
        or modeled_at != attempt["native_order_at"]
        or native_at != modeled_at + minute
        or native_at != attempt["candidate_bar_end"] or native_at != candidate["end"]
        or fill["native_trading_at"].date() != facts.day or candidate["day"] != facts.day
    ):
        raise ReconciliationError("TRADE_TIMING_INVALID", f"trade.{seq}")

    price = _source_price(candidate["open"], tick, "trade.price")
    if (
        candidate["volume"] <= 0 or not facts.limit_down <= price <= facts.limit_up
        or (side == "BUY" and price == facts.limit_up)
        or (side == "SELL" and price == facts.limit_down)
    ):
        raise ReconciliationError("TRADE_CANDIDATE_INELIGIBLE", f"trade.{seq}")
    fee, expected_fee = _commission(facts, price, multiplier, opening=opening, close_today=close_today)
    native = {
        "price": _native_exact(float(price), fill["price"], "trade.price"),
        "commission": _native_exact(expected_fee, fill["commission"], "trade.commission"),
        "fee": _native_exact(expected_fee, fill["fee"], "trade.fee"),
        "tax": _native_exact(0.0, fill["tax"], "trade.tax"),
        "frozen_price": _native_exact(
            float(attempt["order_reference_price"]), attempt["native_frozen_price"], "trade.frozen_price",
        ),
    }
    row = {
        "seq": seq, "physical_contract": contract, "trading_day": facts.day.isoformat(),
        "side": side, "direction": direction, "position_effect": effect, "quantity": 1,
        "close_today_quantity": close_today, "native_close_today_amount": fill["native_close_today_amount"],
        "price": _decimal_text(price), "commission": _decimal_text(fee),
        "fee": _decimal_text(fee), "tax": _decimal_text(ZERO),
        "signal_id": fill["signal_id"], "signal_bar_end": signal_at.isoformat(),
        "signal_available_at": available.isoformat(), "candidate_open_at": modeled_at.isoformat(),
        "modeled_fill_at": modeled_at.isoformat(), "native_order_at": attempt["native_order_at"].isoformat(),
        "native_order_trading_at": attempt["native_trading_at"].isoformat(),
        "native_fill_event_at": native_at.isoformat(), "native_fill_trading_at": fill["native_trading_at"].isoformat(),
        "native_order_id": str(fill["native_order_id"]), "native_trade_id": str(fill["native_trade_id"]),
        "native_amounts": native, "decision": decision,
        "entry_seq": None, "gross_pnl": None, "net_pnl": None,
    }
    if current is not None:
        gross = current.pnl_at(price, multiplier)
        row.update(entry_seq=current.entry_seq, gross_pnl=_decimal_text(gross),
                   net_pnl=_decimal_text(gross - current.fee - fee))
    return row, price, fee


def _verify_account(
    raw: dict, *, day: date, field: str, contract: str, lot: _OpenLot | None,
    mark: Decimal, basis: Decimal, margin: Decimal, cash: Decimal, equity: Decimal,
    position_equity: Decimal,
) -> tuple[dict[str, str], dict[str, Any]]:
    expected = {"cash": cash, "equity": equity, "margin": margin, "frozen_cash": ZERO}
    amounts, witness = {}, {}
    for key, value in expected.items():
        amounts[key], witness[key] = _native_money(value, raw[key], f"{field}.{key}")
    positions = raw["positions"]
    if len(positions) != int(lot is not None):
        raise ReconciliationError("NATIVE_POSITION_MISMATCH", f"{field}.positions")
    witness["positions"] = []
    if lot is not None:
        pos = positions[0]
        today_quantity = int(lot.day == day)
        if (
            pos["contract"] != contract or pos["direction"] != lot.direction or pos["quantity"] != 1
            or pos["today_quantity"] != today_quantity or pos["old_quantity"] != 1 - today_quantity
        ):
            raise ReconciliationError("NATIVE_POSITION_MISMATCH", f"{field}.position_identity")
        pos_witness = {
            name: pos[name]
            for name in ("contract", "direction", "quantity", "today_quantity", "old_quantity")
        }
        pos_witness.update({
            "average_price": _native_exact(float(basis), pos["average_price"], f"{field}.average_price"),
            "last_price": _native_exact(float(mark), pos["last_price"], f"{field}.last_price"),
            "position_equity": _native_money(
                position_equity, pos["position_equity"], f"{field}.position_equity",
            )[1],
        })
        witness["positions"].append(pos_witness)
    return amounts, witness


def _project_settlement(
    settlement: dict, facts: DailyFacts, lot: _OpenLot | None, *, contract: str, tick: Decimal,
    multiplier: int, realized_cash: Decimal,
) -> tuple[dict[str, str], Decimal, dict[str, Any]]:
    try:
        last = _source_price(settlement["last_bar_close"], tick, "settlement.last_bar_close")
        stamp = settlement["native_event_at"]
        before, after = settlement["before"], settlement["after"]
    except KeyError as exc:
        raise ReconciliationError("SETTLEMENT_TRACE_MISSING", str(exc.args[0])) from exc
    if not isinstance(stamp, datetime) or stamp.utcoffset() is None or stamp.date() != facts.day:
        raise ReconciliationError("SETTLEMENT_TRACE_INVALID", "settlement.native_event_at")

    def check(raw: dict, mark: Decimal, basis: Decimal, field: str):
        if lot is None:
            unrealized = position_equity = margin = ZERO
        else:
            unrealized = lot.pnl_at(mark, multiplier)
            position_equity = (mark - basis) * multiplier * (1 if lot.direction == "LONG" else -1)
            margin_rate = facts.long_margin if lot.direction == "LONG" else facts.short_margin
            margin = mark * multiplier * margin_rate
        equity = realized_cash + unrealized
        cash = equity - position_equity - margin
        amounts, witness = _verify_account(
            raw, day=facts.day, field=field, contract=contract, lot=lot, mark=mark, basis=basis,
            margin=margin, cash=cash, equity=equity, position_equity=position_equity,
        )
        return amounts, unrealized, witness

    _, _, before_witness = check(before, last, lot.basis if lot else last, "pre_settlement")
    amounts, unrealized, after_witness = check(after, facts.settlement, facts.settlement, "post_settlement")
    if lot is not None:
        lot.basis = facts.settlement
    return amounts, unrealized, {"before": before_witness, "after": after_witness}


def _attempt_projection(attempt: dict) -> dict:
    signal_id = attempt["signal_id"]
    clocks = {
        field: attempt[field].isoformat() if attempt.get(field) is not None else None
        for field in ("signal_bar_end", "signal_available_at", "candidate_open_at", "candidate_bar_end", "native_order_at")
    }
    return {
        "signal_id": signal_id, "action": attempt["action"], "reason": attempt["reason"],
        "native_status": attempt.get("native_status"), **clocks,
    }


def reconcile(result: dict, *, decisions: Mapping[str, dict]) -> dict:
    """Return JSON-safe trades and equity after Decimal and raw float reconciliation."""
    with localcontext() as context:
        context.prec = 64
        return _reconcile(result, decisions)


def _reconcile(result: dict, decisions: Mapping[str, dict]) -> dict:
    contract = result["contract"]
    tick, multiplier = result["tick"], result["multiplier"]
    if not isinstance(tick, Decimal) or not tick.is_finite() or tick <= 0 or type(multiplier) is not int or multiplier <= 0:
        raise ReconciliationError("INSTRUMENT_FACTS_INVALID", "instrument")
    expected_config = {
        "matching_type": "NEXT_BAR_OPEN", "signal": False, "slippage": 0,
        "price_limit": True, "volume_limit": False, "inactive_limit": True, "management_fee": [],
    }
    config = result["native"]["config"]
    if result.get("engine_version") != "6.3.0" or any(config.get(key) != value for key, value in expected_config.items()):
        raise ReconciliationError("NATIVE_ACCOUNT_POLICY_MISMATCH", "engine")

    if result["terminal_status"] == "ROLLOVER_INTERRUPTED":
        raise ReconciliationError("ROLLOVER_INTERRUPTED", "terminal_status")
    initial = _economic_amount(result["initial_equity"], "initial_equity")
    if initial <= 0:
        raise ReconciliationError("INITIAL_EQUITY_INVALID", "initial_equity")
    dated = tuple(_daily_facts(raw, tick) for raw in result["daily_facts"])
    settlements = result["settlements"]
    days = [facts.day for facts in dated]
    if (
        not days or days != sorted(set(days)) or days != [entry["day"] for entry in settlements]
        or any(left.settlement != right.prev_settlement for left, right in zip(dated, dated[1:]))
    ):
        raise ReconciliationError("DAILY_SETTLEMENT_SEQUENCE_INVALID", "settlements")

    attempts_by_id = {item["signal_id"]: item for item in result["attempts"]}
    fills = result["fills"]
    fill_ids = {item["signal_id"] for item in fills}
    native_ids = {item["native_trade_id"] for item in fills}
    if (
        len(attempts_by_id) != len(result["attempts"]) or len(fill_ids) != len(fills) or len(native_ids) != len(fills)
        or fill_ids != {key for key, row in attempts_by_id.items() if row.get("native_status") == "FILLED"}
    ):
        raise ReconciliationError("TRADE_IDENTITY_MISMATCH", "fills")
    by_day = defaultdict(list)
    last_time = None
    for fill in fills:
        stamp = fill["native_event_at"]
        trade_clock = fill["native_trading_at"]
        trading_day = trade_clock.date()
        if (stamp.utcoffset() is None or trade_clock.utcoffset() is None or trading_day not in days
                or (last_time is not None and stamp <= last_time)):
            raise ReconciliationError("TRADE_SEQUENCE_INVALID", "fills.native_event_at")
        by_day[trading_day].append(fill)
        last_time = stamp

    trades = []
    equity = [{
        "seq": 0, "kind": "INITIAL", "trading_day": days[0].isoformat(),
        "valuation_at": result["sessions"][0]["start"].isoformat(),
        "equity": _decimal_text(initial), "cash": _decimal_text(initial), "margin": _decimal_text(ZERO), "fees": _decimal_text(ZERO),
        "frozen_cash": _decimal_text(ZERO), "unrealized_pnl": _decimal_text(ZERO), "drawdown": _decimal_text(ZERO),
    }]
    fees = realized_gross = realized_net = max_drawdown = ZERO
    peaks = initial
    closed_trades = 0
    lot = None

    for facts, settlement in zip(dated, settlements, strict=True):
        for fill in by_day[facts.day]:
            signal_id = fill["signal_id"]
            if signal_id not in decisions:
                raise ReconciliationError("TRADE_DECISION_MISSING", signal_id)
            trade, price, fee = _project_trade(
                fill, attempts_by_id[signal_id], decisions[signal_id], facts, lot, seq=len(trades) + 1,
                contract=contract, tick=tick, multiplier=multiplier,
            )
            trades.append(trade)
            fees += fee
            if lot is None:
                lot = _OpenLot(trade["seq"], price, price, fee, trade["direction"], facts.day)
            else:
                realized_gross += Decimal(trade["gross_pnl"])
                realized_net += Decimal(trade["net_pnl"])
                closed_trades += 1
                lot = None
        amounts, unrealized, witness = _project_settlement(
            settlement, facts, lot, contract=contract, tick=tick, multiplier=multiplier,
            realized_cash=initial + realized_gross - fees,
        )
        balance = Decimal(amounts["equity"])
        peaks = max(peaks, balance)
        drawdown = peaks - balance
        max_drawdown = max(max_drawdown, drawdown)
        equity.append({
            "seq": len(equity), "kind": "SETTLED", "trading_day": facts.day.isoformat(),
            "valuation_at": settlement["native_event_at"].isoformat(), **amounts, "fees": _decimal_text(fees),
            "unrealized_pnl": _decimal_text(unrealized), "drawdown": _decimal_text(drawdown),
            "settlement_price": _decimal_text(facts.settlement), "native_settlement": witness,
        })

    terminal_status = "OPEN_MARKED_AT_SETTLEMENT" if lot is not None else "FLAT"
    if result["terminal_status"] != terminal_status:
        raise ReconciliationError("NATIVE_POSITION_MISMATCH", "terminal_status", expected=terminal_status)
    terminal = None
    if lot is not None:
        terminal = {
            "physical_contract": contract, "direction": lot.direction, "quantity": 1,
            "entry_seq": lot.entry_seq, "entry_price": _decimal_text(lot.price), "entry_fee": _decimal_text(lot.fee),
            "settlement_price": _decimal_text(lot.basis),
            "unrealized_pnl": equity[-1]["unrealized_pnl"],
        }
    summary = {
        "physical_contract": contract, "money_policy": MONEY_POLICY,
        "cutoff_trading_day": days[-1].isoformat(),
        "initial_equity": _decimal_text(initial), "final_equity": equity[-1]["equity"],
        "net_equity_change": _decimal_text(Decimal(equity[-1]["equity"]) - initial),
        "fees": _decimal_text(fees), "realized_gross_pnl": _decimal_text(realized_gross),
        "realized_net_pnl": _decimal_text(realized_net), "unrealized_pnl": equity[-1]["unrealized_pnl"],
        "max_drawdown": _decimal_text(max_drawdown), "fill_count": len(trades), "closed_trade_count": closed_trades,
        "terminal_status": terminal_status, "terminal_position": terminal,
        "attempts": [_attempt_projection(attempt) for attempt in result["attempts"]],
    }
    return {"summary": summary, "trades": trades, "equity": equity}
