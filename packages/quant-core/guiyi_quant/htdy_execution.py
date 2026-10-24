"""Offline HTDY 60m execution policy. No transport, market resolver or account PnL.

Effects are proposals, NOT broker orders. A later adapter must durably commit the
command/effect before sending, perform account risk checks and reconcile native
reports. This module has no runtime enable path and never fabricates a fill.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
import re


POLICY_VERSION = "htdy_60m_fixed1_signal_reverse_v1"
FORMULA_VERSION = "huotian_dayou_original_v0"


def _time(value):
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("TIME_INVALID")


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError("IDENTITY_INVALID")


def _side(value):
    if type(value) is not int or value not in (-1, 0, 1):
        raise ValueError("QUANTITY_INVALID")


def _money(value, positive=False):
    if type(value) is not Decimal or not value.is_finite() or (value <= 0 if positive else value < 0):
        raise ValueError("DECIMAL_INVALID")


def _contract(product, contract):
    if (type(product) is not str or re.fullmatch(r"[A-Z]{1,3}", product) is None
            or type(contract) is not str or re.fullmatch(
                rf"{product}\d{{3,4}}(?:\.(?:SHFE|DCE|CZCE|INE|CFFEX|GFEX))?", contract) is None):
        raise ValueError("PHYSICAL_CONTRACT_INVALID")


@dataclass(frozen=True)
class Position:
    product: str
    contract: str
    quantity: int

    def __post_init__(self):
        _contract(self.product, self.contract)
        _side(self.quantity)
        if self.quantity == 0:
            raise ValueError("POSITION_MUST_BE_NONZERO")


@dataclass(frozen=True)
class OrderReport:
    order_id: str
    status: str

    def __post_init__(self):
        _text(self.order_id)
        if self.status not in ("WORKING", "CANCELLED", "REJECTED", "FILLED", "UNKNOWN"):
            raise ValueError("ORDER_STATUS_INVALID")


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str
    at: datetime
    balance: Decimal
    available: Decimal
    positions: tuple[Position, ...] = ()
    orders: tuple[OrderReport, ...] = ()
    settled_order_ids: tuple[str, ...] = ()

    def __post_init__(self):
        _text(self.account_id)
        _time(self.at)
        # Negative native balances are facts, not values to clamp or discard.
        for value in (self.balance, self.available):
            if type(value) is not Decimal or not value.is_finite():
                raise ValueError("ACCOUNT_DECIMAL_INVALID")
        if (type(self.positions) is not tuple or type(self.orders) is not tuple
                or any(type(p) is not Position for p in self.positions)
                or any(type(o) is not OrderReport for o in self.orders)
                or len({p.product for p in self.positions}) != len(self.positions)
                or len({o.order_id for o in self.orders}) != len(self.orders)):
            raise ValueError("ACCOUNT_SNAPSHOT_INVALID")
        if (type(self.settled_order_ids) is not tuple
                or len(set(self.settled_order_ids)) != len(self.settled_order_ids)
                or any(not any(o.order_id == identity and o.status in ("CANCELLED", "REJECTED")
                               for o in self.orders) for identity in self.settled_order_ids)):
            raise ValueError("ACCOUNT_SETTLEMENT_PROOF_INVALID")


@dataclass(frozen=True)
class Signal:
    source_id: str
    product: str
    contract: str
    bar_end: datetime
    observed_at: datetime
    previous_bar_end: datetime | None
    directions: tuple[str, ...]
    input_hash: str

    def __post_init__(self):
        _text(self.source_id)
        _contract(self.product, self.contract)
        _time(self.bar_end)
        _time(self.observed_at)
        if self.observed_at <= self.bar_end:
            raise ValueError("SIGNAL_NOT_COMPLETED")
        if self.previous_bar_end is not None:
            _time(self.previous_bar_end)
            if self.previous_bar_end >= self.bar_end:
                raise ValueError("SIGNAL_PREVIOUS_INVALID")
        if (type(self.directions) is not tuple or len(set(self.directions)) != len(self.directions)
                or any(d not in ("buy", "sell") for d in self.directions)
                or type(self.input_hash) is not str or re.fullmatch(r"[0-9a-f]{64}", self.input_hash) is None):
            raise ValueError("SIGNAL_INVALID")


@dataclass(frozen=True)
class Owner:
    product: str
    contract: str
    at: datetime
    source_id: str

    def __post_init__(self):
        _contract(self.product, self.contract)
        _time(self.at)
        _text(self.source_id)


@dataclass(frozen=True)
class Advance:
    product: str
    at: datetime
    tradable: bool
    opening_allowed: bool
    funding_source_id: str

    def __post_init__(self):
        _time(self.at)
        _text(self.product)
        _text(self.funding_source_id)
        if type(self.tradable) is not bool or type(self.opening_allowed) is not bool:
            raise ValueError("EXECUTION_GATE_INVALID")


@dataclass(frozen=True)
class Disconnect:
    at: datetime

    def __post_init__(self):
        _time(self.at)


@dataclass(frozen=True)
class RecoveryInput:
    product: str
    contract: str
    latest_direction: int
    bar_end: datetime
    source_id: str

    def __post_init__(self):
        _contract(self.product, self.contract)
        _side(self.latest_direction)
        _time(self.bar_end)
        _text(self.source_id)


@dataclass(frozen=True)
class Recover:
    snapshot: AccountSnapshot
    inputs: tuple[RecoveryInput, ...]

    def __post_init__(self):
        if (type(self.snapshot) is not AccountSnapshot or type(self.inputs) is not tuple
                or any(type(i) is not RecoveryInput for i in self.inputs)):
            raise ValueError("RECOVERY_INPUT_INVALID")


@dataclass(frozen=True)
class Fill:
    trade_id: str
    order_id: str
    account_id: str
    contract: str
    filled_at: datetime
    recorded_at: datetime
    price: Decimal
    fee: Decimal
    quantity: int

    def __post_init__(self):
        for value in (self.trade_id, self.order_id, self.account_id, self.contract):
            _text(value)
        _time(self.filled_at)
        _time(self.recorded_at)
        _money(self.price, positive=True)
        _money(self.fee)
        if type(self.quantity) is not int or self.quantity != 1 or self.recorded_at < self.filled_at:
            raise ValueError("FILL_INVALID")


@dataclass(frozen=True)
class Report:
    account_id: str
    at: datetime
    report: OrderReport

    def __post_init__(self):
        _text(self.account_id)
        _time(self.at)
        if type(self.report) is not OrderReport:
            raise ValueError("ORDER_REPORT_INVALID")


@dataclass(frozen=True)
class Order:
    order_id: str
    product: str
    contract: str
    side: str
    offset: str
    created_at: datetime
    signal_id: str
    status: str = "PROPOSED"
    quantity: int = 1
    cancel_required: bool = False
    reconciled: bool = False

    def __post_init__(self):
        _text(self.order_id)
        _text(self.signal_id)
        _contract(self.product, self.contract)
        _time(self.created_at)
        if (self.side not in ("BUY", "SELL") or self.offset not in ("OPEN", "CLOSE")
                or type(self.quantity) is not int or self.quantity != 1
                or type(self.cancel_required) is not bool or type(self.reconciled) is not bool
                or self.status not in ("PROPOSED", "WORKING", "CANCEL_PENDING", "UNKNOWN",
                                       "FILLED", "CANCELLED", "REJECTED")):
            raise ValueError("ORDER_INVALID")


@dataclass(frozen=True)
class ProductState:
    product: str
    owner: str | None = None
    position_contract: str | None = None
    quantity: int = 0
    target: int = 0
    signal_id: str = ""
    eligible_after: datetime | None = None
    last_bar: datetime | None = None
    wait_after: datetime | None = None
    rolling: bool = False

    def __post_init__(self):
        if type(self.product) is not str or re.fullmatch(r"[A-Z]{1,3}", self.product) is None:
            raise ValueError("PRODUCT_INVALID")
        _side(self.quantity)
        _side(self.target)
        if type(self.rolling) is not bool:
            raise ValueError("ROLLOVER_INVALID")
        for contract in (self.owner, self.position_contract):
            if contract is not None:
                _contract(self.product, contract)
        if bool(self.quantity) != (self.position_contract is not None):
            raise ValueError("POSITION_INVALID")
        for at in (self.eligible_after, self.last_bar, self.wait_after):
            if at is not None:
                _time(at)


@dataclass(frozen=True)
class Audit:
    command_id: str
    reason: str
    command: object


@dataclass(frozen=True)
class State:
    account_id: str
    activated_at: datetime
    snapshot: AccountSnapshot
    products: tuple[ProductState, ...]
    phase: str = "READY"
    blocked_products: tuple[str, ...] = ()
    signals: tuple[Signal, ...] = ()
    orders: tuple[Order, ...] = ()
    fills: tuple[Fill, ...] = ()
    receipts: tuple[tuple[str, str], ...] = ()
    audit: tuple[Audit, ...] = ()
    clock: datetime | None = None
    unresolved_fill_ids: tuple[str, ...] = ()
    baseline_orders: tuple[OrderReport, ...] = ()


@dataclass(frozen=True)
class Effect:
    kind: str
    order: Order


@dataclass(frozen=True)
class Transition:
    state: State
    effects: tuple[Effect, ...] = ()


def start(account_id: str, products: tuple[str, ...], at: datetime, snapshot: AccountSnapshot) -> State:
    _text(account_id)
    _time(at)
    if type(snapshot) is not AccountSnapshot or snapshot.account_id != account_id or snapshot.at != at:
        raise ValueError("ACCOUNT_IDENTITY_INVALID")
    if snapshot.positions or any(o.status not in ("FILLED", "CANCELLED", "REJECTED") for o in snapshot.orders):
        raise ValueError("ACCOUNT_MUST_START_FLAT_WITH_NO_WORKING_ORDERS")
    if (type(products) is not tuple or not products or len(set(products)) != len(products)
            or any(type(p) is not str or re.fullmatch(r"[A-Z]{1,3}", p) is None for p in products)):
        raise ValueError("UNIVERSE_INVALID")
    return State(account_id, at, snapshot, tuple(ProductState(p) for p in products), clock=at,
                 baseline_orders=snapshot.orders)


def _encode(value):
    if is_dataclass(value):
        return {"type": type(value).__name__, "fields": {f.name: _encode(getattr(value, f.name)) for f in fields(value)}}
    if type(value) in (datetime, Decimal):
        return {"type": type(value).__name__, "value": str(value)}
    if type(value) is tuple:
        return [_encode(v) for v in value]
    return value


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return sha256(_json(_encode(value)).encode()).hexdigest()


def _product(state, product):
    for item in state.products:
        if item.product == product:
            return item
    raise ValueError("PRODUCT_OUT_OF_SCOPE")


def _replace_product(state, product):
    return replace(state, products=tuple(product if p.product == product.product else p for p in state.products))


def _replace_order(state, order):
    return replace(state, orders=tuple(order if o.order_id == order.order_id else o for o in state.orders))


def _unsettled(state, order):
    if any(f.order_id == order.order_id for f in state.fills):
        return False
    return order.status not in ("REJECTED", "CANCELLED") or not order.reconciled


def _apply_signal(state, signal):
    p = _product(state, signal.product)
    if any(s.source_id == signal.source_id and (s.product, s.bar_end) != (signal.product, signal.bar_end) for s in state.signals):
        raise ValueError("SOURCE_IDENTITY_CONFLICT")
    if any((s.product, s.bar_end) == (signal.product, signal.bar_end) for s in state.signals):
        return state, "FROZEN_BAR_IGNORED"
    state = replace(state, signals=state.signals + (signal,))
    if signal.bar_end <= state.activated_at or p.wait_after is not None and signal.bar_end <= p.wait_after:
        return state, "PRE_START_OR_RECOVERY_SIGNAL_IGNORED"
    if p.owner != signal.contract:
        return replace(state, blocked_products=tuple(sorted(set(state.blocked_products) | {p.product}))), "OWNER_MISMATCH"
    if p.last_bar is not None and (signal.bar_end <= p.last_bar or signal.previous_bar_end != p.last_bar):
        return replace(state, blocked_products=tuple(sorted(set(state.blocked_products) | {p.product}))), "OBSERVATION_GAP"
    p = replace(p, last_bar=signal.bar_end)
    if state.phase != "READY" or p.product in state.blocked_products or p.rolling:
        return _replace_product(state, p), "SIGNAL_BLOCKED"
    if len(signal.directions) > 1:
        state = replace(state, orders=tuple(replace(o, cancel_required=True)
            if o.product == p.product and o.offset == "OPEN" and _unsettled(state, o) else o
            for o in state.orders))
        closing = any(o.product == p.product and o.offset == "CLOSE" and _unsettled(state, o) for o in state.orders)
        return _replace_product(state, replace(p, target=0 if closing else p.quantity, signal_id=signal.source_id,
                                              eligible_after=signal.observed_at)), "SIGNAL_CONFLICT"
    if not signal.directions:
        return _replace_product(state, p), "HOLD"
    return _replace_product(state, replace(p, target=1 if signal.directions == ("buy",) else -1,
        signal_id=signal.source_id, eligible_after=signal.observed_at)), "TARGET_UPDATED"


def _advance(state, cmd, command_id):
    p = _product(state, cmd.product)
    working = [o for o in state.orders if o.product == p.product and _unsettled(state, o)]
    if len(working) > 1:
        raise ValueError("ORDER_CAPACITY_CONFLICT")
    if working:
        order = working[0]
        wanted = 1 if order.side == "BUY" else -1
        if order.offset == "OPEN" and (order.cancel_required or p.rolling or p.product in state.blocked_products or p.target != wanted):
            if order.status in ("PROPOSED", "WORKING"):
                order = replace(order, status="CANCEL_PENDING")
                return _replace_order(state, order), (Effect("CANCEL", order),), "CANCEL_OPEN"
        return state, (), "ORDER_PENDING"
    if state.phase != "READY":
        return state, (), "ACCOUNT_READBACK_REQUIRED"
    if p.rolling and p.quantity == 0:
        p = replace(p, rolling=False, target=0, wait_after=cmd.at)
        return _replace_product(state, p), (), "ROLLOVER_FLAT_WAIT_NEW_SIGNAL"
    if (p.product in state.blocked_products and not p.rolling) or not cmd.tradable:
        return state, (), "INPUT_OR_SESSION_BLOCKED"
    if p.quantity == p.target:
        return state, (), "HOLD"
    if p.eligible_after is None or cmd.at <= p.eligible_after:
        return state, (), "NOT_STRICTLY_AFTER_SIGNAL"
    if p.quantity:
        offset, contract, side = "CLOSE", p.position_contract, "SELL" if p.quantity > 0 else "BUY"
    else:
        if not cmd.opening_allowed or state.snapshot.available <= 0:
            return state, (), "OPENING_NOT_APPROVED"
        offset, contract, side = "OPEN", p.owner, "BUY" if p.target > 0 else "SELL"
    if contract is None:
        raise ValueError("PHYSICAL_CONTRACT_REQUIRED")
    order = Order(sha256(f"{state.account_id}:{POLICY_VERSION}:{command_id}".encode()).hexdigest(),
        p.product, contract, side, offset, cmd.at, p.signal_id)
    return replace(state, orders=state.orders + (order,)), (Effect("SUBMIT", order),), "ORDER_PROPOSED"


def _fill(state, fill):
    previous = next((f for f in state.fills if f.trade_id == fill.trade_id), None)
    if previous is not None:
        if previous != fill:
            raise ValueError("FILL_IDENTITY_CONFLICT")
        return state, "DUPLICATE_FILL"
    order = next((o for o in state.orders if o.order_id == fill.order_id), None)
    if order is None or fill.account_id != state.account_id or fill.contract != order.contract:
        raise ValueError("FILL_ACCOUNT_OR_ORDER_MISMATCH")
    if fill.filled_at <= order.created_at or any(f.order_id == order.order_id for f in state.fills):
        raise ValueError("FILL_TIMING_OR_QUANTITY_INVALID")
    p = _product(state, order.product)
    capacity_conflict = order.offset == "OPEN" and p.quantity != 0
    close_conflict = order.offset == "CLOSE" and (
        p.position_contract != order.contract or p.quantity != (1 if order.side == "SELL" else -1))
    if capacity_conflict or close_conflict:
        state = _replace_order(state, replace(order, status="FILLED"))
        return replace(state, fills=state.fills + (fill,), phase="BLOCKED",
                       unresolved_fill_ids=state.unresolved_fill_ids + (fill.trade_id,)), "NATIVE_FILL_PROJECTION_CONFLICT"
    late_terminal = order.status in ("CANCELLED", "REJECTED")
    if order.offset == "OPEN":
        if p.quantity != 0:
            raise ValueError("POSITION_CAPACITY_CONFLICT")
        p = replace(p, quantity=1 if order.side == "BUY" else -1, position_contract=order.contract)
        if p.rolling:
            p = replace(p, target=0)
    else:
        if (p.position_contract != order.contract or p.quantity != (1 if order.side == "SELL" else -1)):
            raise ValueError("CLOSE_POSITION_CONFLICT")
        p = replace(p, quantity=0, position_contract=None)
    state = _replace_product(state, p)
    state = _replace_order(state, replace(order, status="FILLED"))
    if late_terminal:
        state = replace(state, phase="BLOCKED" if state.unresolved_fill_ids else "RECOVERY_REQUIRED", orders=tuple(
            replace(o, cancel_required=True) if o.offset == "OPEN" and _unsettled(state, o) else o
            for o in state.orders))
    return replace(state, fills=state.fills + (fill,)), "BROKER_FILL_RECORDED"


def _report(state, cmd):
    if cmd.account_id != state.account_id:
        raise ValueError("ORDER_ACCOUNT_MISMATCH")
    order = next((o for o in state.orders if o.order_id == cmd.report.order_id), None)
    if order is None or cmd.at < order.created_at:
        raise ValueError("UNKNOWN_ORDER_REPORT")
    if any(f.order_id == order.order_id for f in state.fills):
        if cmd.report.status != "FILLED":
            raise ValueError("ORDER_REPORT_CONFLICT")
        return state, "ORDER_ALREADY_FILLED"
    if order.status in ("CANCELLED", "REJECTED") and cmd.report.status != order.status:
        raise ValueError("ORDER_REPORT_CONFLICT")
    status = cmd.report.status
    if order.status == "CANCEL_PENDING" and status == "WORKING":
        status = "CANCEL_PENDING"
    state = _replace_order(state, replace(order, status=status))
    if status in ("UNKNOWN", "FILLED", "REJECTED", "CANCELLED") and not state.unresolved_fill_ids:
        state = replace(state, phase="RECOVERY_REQUIRED")
    return state, "ORDER_REPORT_RECORDED"


def _validate_state(state):
    if (type(state) is not State or type(state.products) is not tuple or not state.products
            or len({p.product for p in state.products}) != len(state.products)
            or state.phase not in ("READY", "RECOVERY_REQUIRED", "BLOCKED")
            or state.snapshot.account_id != state.account_id
            or len({o.order_id for o in state.orders}) != len(state.orders)
            or len({f.trade_id for f in state.fills}) != len(state.fills)
            or len(dict(state.receipts)) != len(state.receipts)
            or len(state.receipts) != len(state.audit)
            or any(p not in {s.product for s in state.products} for p in state.blocked_products)):
        raise ValueError("STATE_INVALID")
    _text(state.account_id)
    _time(state.activated_at)
    _time(state.clock)
    positions, filled = {}, set()
    orders = {o.order_id: o for o in state.orders}
    for fill in state.fills:
        if fill.trade_id in state.unresolved_fill_ids:
            if state.phase != "BLOCKED" or fill.account_id != state.account_id:
                raise ValueError("STATE_UNRESOLVED_FILL_CONFLICT")
            continue
        order = orders.get(fill.order_id)
        if (order is None or fill.order_id in filled or fill.account_id != state.account_id
                or fill.contract != order.contract or fill.filled_at <= order.created_at
                or fill.recorded_at > state.clock or order.status != "FILLED"):
            raise ValueError("STATE_FILL_CONFLICT")
        current = positions.get(order.product)
        if order.offset == "OPEN":
            if current is not None:
                raise ValueError("STATE_POSITION_CONFLICT")
            positions[order.product] = (order.contract, 1 if order.side == "BUY" else -1)
        else:
            if current != (order.contract, 1 if order.side == "SELL" else -1):
                raise ValueError("STATE_POSITION_CONFLICT")
            del positions[order.product]
        filled.add(fill.order_id)
    expected = {p.product: (p.position_contract, p.quantity) for p in state.products if p.quantity}
    if positions != expected:
        raise ValueError("STATE_POSITION_REPLAY_CONFLICT")
    for order in state.orders:
        _product(state, order.product)
        if order.created_at <= state.activated_at or order.created_at > state.clock:
            raise ValueError("STATE_ORDER_TIME_INVALID")


def _recover(state, cmd):
    snapshot = cmd.snapshot
    if type(snapshot) is not AccountSnapshot or snapshot.account_id != state.account_id:
        raise ValueError("ACCOUNT_IDENTITY_INVALID")
    if state.unresolved_fill_ids:
        return replace(state, phase="BLOCKED"), "NATIVE_FILL_PROJECTION_REQUIRES_RECONCILIATION"
    expected = tuple(sorted((p.product, p.position_contract, p.quantity) for p in state.products if p.quantity))
    actual = tuple(sorted((p.product, p.contract, p.quantity) for p in snapshot.positions))
    reports = {r.order_id: r for r in snapshot.orders}
    if expected != actual or any(r.order_id not in {o.order_id for o in state.orders}
                                and r not in state.baseline_orders for r in snapshot.orders):
        return replace(state, phase="BLOCKED"), "ACCOUNT_RECONCILIATION_MISMATCH"
    # Missing or ambiguous outcomes never imply a failed order and never free capacity.
    for order in state.orders:
        if _unsettled(state, order):
            report = reports.get(order.order_id)
            if report is None or report.status in ("UNKNOWN", "FILLED"):
                return replace(state, phase="RECOVERY_REQUIRED"), "ORDER_OUTCOME_UNRESOLVED"
            if report.status in ("CANCELLED", "REJECTED") and order.order_id not in snapshot.settled_order_ids:
                return replace(state, phase="RECOVERY_REQUIRED"), "CANCEL_TRADE_RECONCILIATION_REQUIRED"
    for report in snapshot.orders:
        if report not in state.baseline_orders:
            state, _ = _report(state, Report(state.account_id, snapshot.at, report))
    state = replace(state, orders=tuple(replace(o, reconciled=True)
        if o.order_id in snapshot.settled_order_ids else
        replace(o, cancel_required=True) if o.offset == "OPEN" and _unsettled(state, o) else o
        for o in state.orders))
    if type(cmd.inputs) is not tuple or any(type(i) is not RecoveryInput for i in cmd.inputs):
        raise ValueError("RECOVERY_INPUT_INVALID")
    if len({i.product for i in cmd.inputs}) != len(cmd.inputs):
        raise ValueError("RECOVERY_INPUT_INVALID")
    inputs = {i.product: i for i in cmd.inputs}
    for product in inputs:
        _product(state, product)
    blocked, products = [], []
    for p in state.products:
        proof = inputs.get(p.product)
        if proof is None or proof.contract != p.owner:
            blocked.append(p.product)
        elif proof.bar_end >= snapshot.at or p.last_bar is not None and proof.bar_end < p.last_bar:
            raise ValueError("RECOVERY_CUTOFF_INVALID")
        target = p.quantity
        closing = any(o.product == p.product and o.offset == "CLOSE" and _unsettled(state, o) for o in state.orders)
        if p.rolling or closing or proof is not None and proof.latest_direction * p.quantity == -1:
            target = 0
        products.append(replace(p, target=target, signal_id=f"recovery:{proof.source_id}" if proof else "",
            eligible_after=snapshot.at, wait_after=snapshot.at,
            last_bar=proof.bar_end if proof and p.product not in blocked else p.last_bar))
    return replace(state, snapshot=snapshot, products=tuple(products), phase="READY",
                   blocked_products=tuple(blocked)), "RECOVERED_NO_OPEN_BACKFILL"


def apply(state: State, command_id: str, command) -> Transition:
    """Pure command reducer; persist its returned state/effects atomically before I/O."""
    _text(command_id)
    if type(state) is not State:
        raise ValueError("STATE_INVALID")
    if type(command) not in (Signal, Owner, Advance, Disconnect, Recover, Fill, Report):
        raise ValueError("COMMAND_INVALID")
    digest = _digest(command)
    prior = dict(state.receipts).get(command_id)
    if prior is not None:
        if prior != digest:
            raise ValueError("COMMAND_IDENTITY_CONFLICT")
        return Transition(state)
    at = (command.observed_at if type(command) is Signal else command.recorded_at if type(command) is Fill
          else command.snapshot.at if type(command) is Recover else command.at)
    if type(command) is Fill and any(f.trade_id == command.trade_id for f in state.fills):
        # Native trade identity survives redelivery after newer observations.
        state, _ = _fill(state, command)
        if state.clock is not None:
            at = max(at, state.clock)
    if state.clock is not None and at < state.clock:
        raise ValueError("COMMAND_TIME_REGRESSION")
    effects = ()
    if type(command) is Signal:
        state, reason = _apply_signal(state, command)
    elif type(command) is Owner:
        p = _product(state, command.product)
        if p.owner is not None and p.owner != command.contract:
            p = replace(p, owner=command.contract, rolling=True, target=0,
                        signal_id=f"roll:{command.source_id}", eligible_after=command.at)
            reason = "ROLLOVER_CLOSE_OLD_CONTRACT"
        else:
            p, reason = replace(p, owner=command.contract), "OWNER_VERIFIED"
        state = _replace_product(state, p)
    elif type(command) is Advance:
        state, effects, reason = _advance(state, command, command_id)
    elif type(command) is Fill:
        state, reason = _fill(state, command)
    elif type(command) is Report:
        state, reason = _report(state, command)
    elif type(command) is Disconnect:
        state, reason = replace(state, phase="BLOCKED" if state.unresolved_fill_ids else "RECOVERY_REQUIRED"), "DISCONNECTED"
    else:
        state, reason = _recover(state, command)
    state = replace(state, clock=at, receipts=state.receipts + ((command_id, digest),),
                    audit=state.audit + (Audit(command_id, reason, command),))
    _validate_state(state)
    return Transition(state, effects)


def checkpoint(state: State) -> str:
    _validate_state(state)
    body = {"policy": POLICY_VERSION, "formula": FORMULA_VERSION, "state": _encode(state)}
    return _json({"body": body, "sha256": sha256(_json(body).encode()).hexdigest()})


def restore(payload: str) -> State:
    """Decode a local checkpoint; always require native account readback afterwards."""
    classes = {c.__name__: c for c in (Position, OrderReport, AccountSnapshot, Signal, Order, Fill,
               Owner, Advance, Disconnect, Recover, RecoveryInput, Report, ProductState, Audit, State)}

    def decode(value):
        if type(value) is list:
            return tuple(decode(v) for v in value)
        if type(value) is dict:
            if value.get("type") == "datetime":
                result = datetime.fromisoformat(value["value"])
                _time(result)
                return result
            if value.get("type") == "Decimal":
                return Decimal(value["value"])
            return classes[value["type"]](**{k: decode(v) for k, v in value["fields"].items()})
        return value

    try:
        packet = json.loads(payload)
        body = packet["body"]
        if (body["policy"] != POLICY_VERSION or body["formula"] != FORMULA_VERSION
                or sha256(_json(body).encode()).hexdigest() != packet["sha256"]):
            raise ValueError("CHECKPOINT_IDENTITY_INVALID")
        state = decode(body["state"])
        if type(state) is not State:
            raise ValueError("CHECKPOINT_STATE_INVALID")
        _validate_state(state)
        return replace(state, phase="BLOCKED" if state.unresolved_fill_ids else "RECOVERY_REQUIRED")
    except (KeyError, TypeError, ValueError, ArithmeticError):
        raise ValueError("CHECKPOINT_INVALID") from None
