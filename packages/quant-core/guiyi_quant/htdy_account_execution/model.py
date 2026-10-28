"""Explicit facts and immutable state for the next-stage offline HTDY account profile."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import re
from uuid import UUID
from ..htdy_execution import (
    AccountSnapshot as AccountSnapshot,
    Fill as Fill,
    Owner as Owner,
    Position as Position,
    RecoveryInput as RecoveryInput,
    Signal as Signal,
)

POLICY_VERSION = "htdy_60m_account_execution_v2"
PRODUCT_RECOVERY_POLICY_VERSION = "htdy_60m_product_recovery_v1"
MANAGED_TICK_POLICY_VERSION = "htdy_60m_managed_tick_v1"
CONTINUOUS_TRADE_POLICY_VERSION = "htdy_60m_continuous_trade_v1"
MANUAL_TEST_POLICY_VERSION = "htdy_simnow_rb_manual_long1_hold600_v1"
CORRELATED_NATIVE_FILL_POLICY_VERSION = "simnow_manual_correlated_fill_v1"
STRATEGY_CORRELATED_NATIVE_FILL_POLICY_VERSION = "simnow_strategy_correlated_fill_v1"
RISK_VERSION = "htdy_simnow_margin70_skip_v1"
EXECUTION_VERSION = "htdy_simnow_opponent_reprice180_v1"
FORMULA_VERSION = "huotian_dayou_original_v0"
CAP = Decimal("0.70")


def time(value):
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("TIME_INVALID")


def text(value):
    if type(value) is not str or not value.strip():
        raise ValueError("IDENTITY_INVALID")


def money(value, positive=False):
    if (
        type(value) is not Decimal
        or not value.is_finite()
        or (value <= 0 if positive else value < 0)
    ):
        raise ValueError("DECIMAL_INVALID")


def contract(product, value):
    if (
        type(product) is not str
        or re.fullmatch(r"[A-Z]{1,3}", product) is None
        or type(value) is not str
        or re.fullmatch(
            rf"{product}\d{{3,4}}(?:\.(?:SHFE|DCE|CZCE|INE|CFFEX|GFEX))?", value
        )
        is None
    ):
        raise ValueError("PHYSICAL_CONTRACT_INVALID")


def side(value):
    if type(value) is not int or value not in (-1, 0, 1):
        raise ValueError("QUANTITY_INVALID")


@dataclass(frozen=True)
class NativeFill(Fill):
    """Native second-resolution time, not an invented exact execution instant.

    Order identity proves causality; timestamp is the start of its one-second
    interval. Exact Fill semantics remain unchanged for research/model events.
    """

    request_started_at: datetime
    dispatch_source_id: str
    native_system_id: str
    native_precision_seconds: int = 1

    def __post_init__(self):
        super().__post_init__()
        time(self.request_started_at)
        text(self.dispatch_source_id)
        text(self.native_system_id)
        if (
            type(self.native_precision_seconds) is not int
            or self.native_precision_seconds != 1
            or self.filled_at.microsecond != 0
            or self.recorded_at < self.request_started_at
        ):
            raise ValueError("NATIVE_FILL_PRECISION_INVALID")


@dataclass(frozen=True)
class CorrelatedNativeFillV1(NativeFill):
    """Manual-only native fill whose identity proof spans distinct clock domains."""

    readback_source_id: str = ""
    native_order_ref: str = ""
    native_front_id: int = 0
    native_session_id: int = 0
    correlation_policy_version: str = CORRELATED_NATIVE_FILL_POLICY_VERSION

    def __post_init__(self):
        super().__post_init__()
        text(self.readback_source_id)
        text(self.native_order_ref)
        if (
            re.fullmatch(r"[0-9]+", self.native_order_ref) is None
            or int(self.native_order_ref) <= 0
            or type(self.native_front_id) is not int
            or self.native_front_id <= 0
            or type(self.native_session_id) is not int
            or self.native_session_id <= 0
            or self.correlation_policy_version != CORRELATED_NATIVE_FILL_POLICY_VERSION
        ):
            raise ValueError("CORRELATED_NATIVE_FILL_PROOF_INVALID")


@dataclass(frozen=True)
class StrategyCorrelatedNativeFillV1(NativeFill):
    """Ordinary strategy native fact with full readback identity correlation."""

    readback_source_id: str = ""
    native_order_ref: str = ""
    native_front_id: int = 0
    native_session_id: int = 0
    correlation_policy_version: str = STRATEGY_CORRELATED_NATIVE_FILL_POLICY_VERSION

    def __post_init__(self):
        # Fill/NativeFill's old validation compares broker filled_at to local
        # recorded_at. This version proves causal identity across two clocks;
        # keep the other validations, but compare only local times to each other.
        for value in (
            self.trade_id,
            self.order_id,
            self.account_id,
            self.contract,
            self.dispatch_source_id,
            self.native_system_id,
        ):
            text(value)
        for value in (self.filled_at, self.recorded_at, self.request_started_at):
            time(value)
        money(self.price, True)
        money(self.fee)
        if (
            type(self.quantity) is not int
            or self.quantity != 1
            or type(self.native_precision_seconds) is not int
            or self.native_precision_seconds != 1
            or self.filled_at.microsecond != 0
            or self.recorded_at < self.request_started_at
        ):
            raise ValueError("NATIVE_FILL_PRECISION_INVALID")
        text(self.readback_source_id)
        text(self.native_order_ref)
        if (
            re.fullmatch(r"[0-9]+", self.native_order_ref) is None
            or int(self.native_order_ref) <= 0
            or type(self.native_front_id) is not int
            or self.native_front_id <= 0
            or type(self.native_session_id) is not int
            or self.native_session_id <= 0
            or self.correlation_policy_version
            != STRATEGY_CORRELATED_NATIVE_FILL_POLICY_VERSION
        ):
            raise ValueError("STRATEGY_CORRELATED_NATIVE_FILL_PROOF_INVALID")


@dataclass(frozen=True)
class Coverage:
    order_id: str
    margin: Decimal
    fee: Decimal

    def __post_init__(self):
        text(self.order_id)
        money(self.margin)
        money(self.fee)


@dataclass(frozen=True)
class Readback:
    snapshot: AccountSnapshot
    used_margin: Decimal
    frozen_margin: Decimal
    frozen_fee: Decimal
    coverage: tuple[Coverage, ...]
    confirmed_trade_ids: tuple[str, ...]
    source_id: str
    valid_until: datetime
    complete: bool

    def __post_init__(self):
        if type(self.snapshot) is not AccountSnapshot:
            raise ValueError("SNAPSHOT_INVALID")
        for value in (self.used_margin, self.frozen_margin, self.frozen_fee):
            money(value)
        text(self.source_id)
        time(self.valid_until)
        if type(self.complete) is not bool or self.valid_until <= self.snapshot.at:
            raise ValueError("READBACK_VALIDITY_INVALID")
        if (
            type(self.coverage) is not tuple
            or any(type(c) is not Coverage for c in self.coverage)
            or len({c.order_id for c in self.coverage}) != len(self.coverage)
        ):
            raise ValueError("COVERAGE_INVALID")
        if (
            sum((c.margin for c in self.coverage), Decimal(0)) > self.frozen_margin
            or sum((c.fee for c in self.coverage), Decimal(0)) > self.frozen_fee
        ):
            raise ValueError("COVERAGE_EXCEEDS_NATIVE_FROZEN")
        if type(self.confirmed_trade_ids) is not tuple or len(
            set(self.confirmed_trade_ids)
        ) != len(self.confirmed_trade_ids):
            raise ValueError("TRADE_PROOF_INVALID")
        for identity in self.confirmed_trade_ids:
            text(identity)

    @property
    def at(self):
        return self.snapshot.at


@dataclass(frozen=True)
class Instrument:
    product: str
    contract: str
    at: datetime
    valid_until: datetime
    source_id: str
    tick_size: Decimal
    multiplier: Decimal
    long_margin_rate: Decimal
    short_margin_rate: Decimal
    open_fee: Decimal
    minimum_open_volume: int = 1

    def __post_init__(self):
        contract(self.product, self.contract)
        time(self.at)
        time(self.valid_until)
        text(self.source_id)
        for value in (
            self.tick_size,
            self.multiplier,
            self.long_margin_rate,
            self.short_margin_rate,
        ):
            money(value, True)
        money(self.open_fee)
        if (
            self.valid_until <= self.at
            or max(self.long_margin_rate, self.short_margin_rate) > 1
            or type(self.minimum_open_volume) is not int
            or self.minimum_open_volume < 1
        ):
            raise ValueError("INSTRUMENT_FACT_INVALID")


@dataclass(frozen=True)
class Quote:
    contract: str
    at: datetime
    valid_until: datetime
    source_id: str
    bid: Decimal
    ask: Decimal
    bid_volume: int
    ask_volume: int
    lower_limit: Decimal
    upper_limit: Decimal

    def __post_init__(self):
        text(self.contract)
        time(self.at)
        time(self.valid_until)
        text(self.source_id)
        for v in (self.bid, self.ask, self.lower_limit, self.upper_limit):
            money(v, True)
        if (
            self.valid_until <= self.at
            or not self.lower_limit <= self.bid <= self.ask <= self.upper_limit
            or any(
                type(v) is not int or v < 0 for v in (self.bid_volume, self.ask_volume)
            )
        ):
            raise ValueError("QUOTE_INVALID")


@dataclass(frozen=True)
class Session:
    contract: str
    at: datetime
    valid_until: datetime
    source_id: str
    final_close_at: datetime
    can_trade: bool
    can_cancel: bool

    def __post_init__(self):
        text(self.contract)
        text(self.source_id)
        for v in (self.at, self.valid_until, self.final_close_at):
            time(v)
        if (
            self.valid_until <= self.at
            or type(self.can_trade) is not bool
            or type(self.can_cancel) is not bool
        ):
            raise ValueError("SESSION_INVALID")


@dataclass(frozen=True)
class ExecutionInput:
    instrument: Instrument
    session: Session
    quote: Quote | None

    def __post_init__(self):
        if (
            type(self.instrument) is not Instrument
            or type(self.session) is not Session
            or self.quote is not None
            and type(self.quote) is not Quote
        ):
            raise ValueError("EXECUTION_FACT_INVALID")
        if (
            self.session.contract != self.instrument.contract
            or self.quote is not None
            and self.quote.contract != self.instrument.contract
        ):
            raise ValueError("EXECUTION_CONTRACT_MISMATCH")


@dataclass(frozen=True)
class Tick:
    at: datetime
    inputs: tuple[ExecutionInput, ...]

    def __post_init__(self):
        time(self.at)
        if (
            type(self.inputs) is not tuple
            or any(type(i) is not ExecutionInput for i in self.inputs)
            or len({i.instrument.contract for i in self.inputs}) != len(self.inputs)
        ):
            raise ValueError("EXECUTION_INPUT_INVALID")


@dataclass(frozen=True)
class ManagedTickV1:
    """Manage known obligations without granting any new OPEN intent."""

    at: datetime
    inputs: tuple[ExecutionInput, ...]
    opening_allowed: bool = False
    policy_version: str = MANAGED_TICK_POLICY_VERSION

    def __post_init__(self):
        Tick(self.at, self.inputs)
        if (
            self.opening_allowed is not False
            or self.policy_version != MANAGED_TICK_POLICY_VERSION
        ):
            raise ValueError("MANAGED_TICK_POLICY_INVALID")


@dataclass(frozen=True)
class ContinuousTradeTickV1:
    """Explicit continuous trading, serializing all submissions account-wide."""

    at: datetime
    inputs: tuple[ExecutionInput, ...]
    policy_version: str = CONTINUOUS_TRADE_POLICY_VERSION

    def __post_init__(self):
        Tick(self.at, self.inputs)
        if self.policy_version != CONTINUOUS_TRADE_POLICY_VERSION:
            raise ValueError("CONTINUOUS_TRADE_POLICY_INVALID")


def manual_test_id(value):
    if type(value) is not str or not value.startswith("manual:"):
        raise ValueError("MANUAL_TEST_ID_INVALID")
    try:
        identity = UUID(value.removeprefix("manual:"))
    except (ValueError, AttributeError):
        raise ValueError("MANUAL_TEST_ID_INVALID") from None
    if value != "manual:" + str(identity):
        raise ValueError("MANUAL_TEST_ID_INVALID")


@dataclass(frozen=True)
class ManualBeginV1:
    test_id: str
    product: str
    contract: str
    at: datetime
    open_until: datetime
    side: int = 1
    hold_seconds: int = 600
    policy_version: str = MANUAL_TEST_POLICY_VERSION

    def __post_init__(self):
        manual_test_id(self.test_id)
        contract(self.product, self.contract)
        time(self.at)
        time(self.open_until)
        if (
            self.product != "RB"
            or type(self.side) is not int
            or self.side != 1
            or type(self.hold_seconds) is not int
            or self.hold_seconds != 600
            or not self.at < self.open_until <= self.at + timedelta(seconds=3600)
            or self.policy_version != MANUAL_TEST_POLICY_VERSION
        ):
            raise ValueError("MANUAL_TEST_POLICY_INVALID")


@dataclass(frozen=True)
class ManualTickV1:
    at: datetime
    inputs: tuple[ExecutionInput, ...]
    test_id: str
    policy_version: str = MANUAL_TEST_POLICY_VERSION

    def __post_init__(self):
        Tick(self.at, self.inputs)
        manual_test_id(self.test_id)
        if self.policy_version != MANUAL_TEST_POLICY_VERSION:
            raise ValueError("MANUAL_TEST_POLICY_INVALID")


@dataclass(frozen=True)
class ManualStatusV1:
    phase: str
    due_at: datetime | None
    open_order_id: str | None
    close_order_ids: tuple[str, ...]
    confirmed_at: datetime | None
    complete: bool
    terminal: bool


@dataclass(frozen=True)
class OrderUpdate:
    account_id: str
    order_id: str
    at: datetime
    source_id: str
    status: str
    accepted_at: datetime | None = None

    def __post_init__(self):
        for v in (self.account_id, self.order_id, self.source_id):
            text(v)
        time(self.at)
        if self.status not in ("WORKING", "CANCELLED", "REJECTED", "FILLED", "UNKNOWN"):
            raise ValueError("ORDER_STATUS_INVALID")
        if self.accepted_at is not None:
            time(self.accepted_at)
            if self.accepted_at > self.at:
                raise ValueError("ACCEPTANCE_TIME_INVALID")


@dataclass(frozen=True)
class AbortUnsent:
    account_id: str
    order_id: str
    at: datetime
    source_id: str
    reason: str

    def __post_init__(self):
        for v in (self.account_id, self.order_id, self.source_id, self.reason):
            text(v)
        time(self.at)


@dataclass(frozen=True)
class Disconnect:
    at: datetime

    def __post_init__(self):
        time(self.at)


@dataclass(frozen=True)
class Recover:
    readback: Readback
    inputs: tuple[RecoveryInput, ...]

    def __post_init__(self):
        if (
            type(self.readback) is not Readback
            or type(self.inputs) is not tuple
            or any(type(i) is not RecoveryInput for i in self.inputs)
            or len({i.product for i in self.inputs}) != len(self.inputs)
        ):
            raise ValueError("RECOVERY_INVALID")

    @property
    def at(self):
        return self.readback.at


@dataclass(frozen=True)
class ProductRecoveryV1:
    """Resolve only named blocked products after account readback remains sound."""

    readback: Readback
    inputs: tuple[RecoveryInput, ...]
    products: tuple[str, ...]
    policy_version: str = PRODUCT_RECOVERY_POLICY_VERSION

    def __post_init__(self):
        Recover(self.readback, self.inputs)
        if (
            type(self.products) is not tuple
            or not self.products
            or len(set(self.products)) != len(self.products)
            or any(
                type(product) is not str or re.fullmatch(r"[A-Z]{1,3}", product) is None
                for product in self.products
            )
            or set(item.product for item in self.inputs) - set(self.products)
            or self.policy_version != PRODUCT_RECOVERY_POLICY_VERSION
        ):
            raise ValueError("PRODUCT_RECOVERY_INVALID")

    @property
    def at(self):
        return self.readback.at


@dataclass(frozen=True)
class Product:
    product: str
    owner: str | None = None
    desired: int = 0
    signal_id: str = ""
    signal_at: datetime | None = None
    last_bar: datetime | None = None
    wait_after: datetime | None = None
    opening_consumed: bool = False
    must_close: bool = False
    rolling: bool = False

    def __post_init__(self):
        if (
            type(self.product) is not str
            or re.fullmatch(r"[A-Z]{1,3}", self.product) is None
        ):
            raise ValueError("PRODUCT_INVALID")
        side(self.desired)
        if self.owner is not None:
            contract(self.product, self.owner)
        for v in (self.signal_at, self.last_bar, self.wait_after):
            if v is not None:
                time(v)
        if any(
            type(v) is not bool
            for v in (self.opening_consumed, self.must_close, self.rolling)
        ):
            raise ValueError("PRODUCT_STATE_INVALID")


@dataclass(frozen=True)
class Order:
    order_id: str
    product: str
    contract: str
    side: str
    offset: str
    signal_id: str
    created_at: datetime
    price: Decimal
    instrument_source: str
    quote_source: str
    session_source: str
    predecessor_id: str | None = None
    status: str = "PROPOSED"
    accepted_at: datetime | None = None
    terminal_at: datetime | None = None
    reconciled: bool = False
    cancel_required: bool = False
    cancel_sent: bool = False
    quantity: int = 1

    def __post_init__(self):
        contract(self.product, self.contract)
        time(self.created_at)
        money(self.price, True)
        for v in (
            self.order_id,
            self.signal_id,
            self.instrument_source,
            self.quote_source,
            self.session_source,
        ):
            text(v)
        for v in (self.accepted_at, self.terminal_at):
            if v is not None:
                time(v)
                if v < self.created_at:
                    raise ValueError("ORDER_TIME_INVALID")
        if (
            self.side not in ("BUY", "SELL")
            or self.offset not in ("OPEN", "CLOSE")
            or self.status
            not in (
                "PROPOSED",
                "LOCAL_ABORTED",
                "WORKING",
                "CANCEL_PENDING",
                "CANCELLED",
                "REJECTED",
                "FILLED",
                "UNKNOWN",
            )
            or type(self.quantity) is not int
            or self.quantity != 1
        ):
            raise ValueError("ORDER_INVALID")
        if any(
            type(v) is not bool
            for v in (self.reconciled, self.cancel_required, self.cancel_sent)
        ):
            raise ValueError("ORDER_FLAGS_INVALID")


@dataclass(frozen=True)
class Reservation:
    order_id: str
    margin: Decimal
    fee: Decimal
    source_id: str
    released: bool = False
    release_source: str = ""

    def __post_init__(self):
        text(self.order_id)
        text(self.source_id)
        money(self.margin, True)
        money(self.fee)
        if type(self.released) is not bool or self.released and not self.release_source:
            raise ValueError("RESERVATION_INVALID")


@dataclass(frozen=True)
class Audit:
    command_id: str
    reason: str
    command: object


@dataclass(frozen=True)
class RiskDecision:
    product: str
    signal_id: str
    at: datetime
    approved: bool
    reason: str
    margin: Decimal
    projected_margin: Decimal
    margin_limit: Decimal
    funding_source_id: str

    def __post_init__(self):
        for value in (
            self.product,
            self.signal_id,
            self.reason,
            self.funding_source_id,
        ):
            text(value)
        time(self.at)
        for value in (self.margin, self.projected_margin, self.margin_limit):
            money(value)
        if type(self.approved) is not bool:
            raise ValueError("RISK_DECISION_INVALID")


@dataclass(frozen=True)
class State:
    account_id: str
    activated_at: datetime
    initial_readback: Readback
    readback: Readback
    products: tuple[Product, ...]
    positions: tuple[Position, ...] = ()
    orders: tuple[Order, ...] = ()
    reservations: tuple[Reservation, ...] = ()
    signals: tuple[Signal, ...] = ()
    fills: tuple[Fill, ...] = ()
    updates: tuple[OrderUpdate, ...] = ()
    abandoned: tuple[str, ...] = ()
    risk_decisions: tuple[RiskDecision, ...] = ()
    receipts: tuple[tuple[str, str], ...] = ()
    audit: tuple[Audit, ...] = ()
    phase: str = "READY"
    readback_valid: bool = True
    blocked_products: tuple[str, ...] = ()
    unresolved_fill_ids: tuple[str, ...] = ()
    clock: datetime | None = None


@dataclass(frozen=True)
class Effect:
    kind: str
    order: Order


@dataclass(frozen=True)
class Transition:
    state: State
    effects: tuple[Effect, ...] = ()
