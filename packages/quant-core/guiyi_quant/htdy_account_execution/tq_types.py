"""TqKq execution facts: account-specific per-lot margin, optional per-fill fee.

The remote account commission remains authoritative when its public Trade has no
per-fill commission. None is unknown, never a manufactured zero fee.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import re
from ..htdy_execution import Fill, Signal, _text, _time, _money

TQ_EXECUTION_VERSION = "htdy_tqkq_opponent_reprice180_v1"
TQ_RISK_VERSION = "htdy_tqkq_actual_equity_margin70_v1"


@dataclass(frozen=True)
class TqKqManualClosesV1:
    orders: tuple
    fills: tuple
    readback: object
    evidence_sha256: str
    approval_source: str
    policy_version: str = "tqkq_manual_close_reconciliation_v1"

    @property
    def at(self):
        return self.readback.at

    def __post_init__(self):
        from .model import Order, Readback

        _text(self.approval_source)
        if (type(self.readback) is not Readback
                or re.fullmatch(r"[0-9a-f]{64}", self.evidence_sha256) is None
                or self.policy_version != "tqkq_manual_close_reconciliation_v1"
                or type(self.orders) is not tuple or type(self.fills) is not tuple
                or not 1 <= len(self.orders) <= 60 or len(self.orders) != len(self.fills)):
            raise ValueError("TQ_MANUAL_CLOSE_INVALID")
        if (any(type(o) is not Order or o.offset != "CLOSE" or o.status != "FILLED"
                or o.signal_id != "human:" + self.approval_source
                or o.quantity != 1 for o in self.orders)
                or any(type(f) is not TqKqFill or f.recorded_at != self.at
                       or f.account_id != self.readback.snapshot.account_id for f in self.fills)
                or len({o.product for o in self.orders}) != len(self.orders)
                or len({o.order_id for o in self.orders}) != len(self.orders)
                or len({f.trade_id for f in self.fills}) != len(self.fills)
                or len({f.native_order_id for f in self.fills}) != len(self.fills)
                or any(f.trade_id != "tq-trade:" + f.native_trade_id
                       or f.order_id != "manual-tq:" + f.native_order_id for f in self.fills)
                or {o.order_id for o in self.orders} != {f.order_id for f in self.fills}
                or not {f.trade_id for f in self.fills} <= set(self.readback.confirmed_trade_ids)):
            raise ValueError("TQ_MANUAL_CLOSE_INVALID")
        for order in self.orders:
            fill = next(f for f in self.fills if f.order_id == order.order_id)
            source = "manual-evidence:" + self.evidence_sha256
            if (fill.contract != order.contract or fill.quantity != 1 or fill.fee is not None
                    or not order.created_at < fill.filled_at <= self.at
                    or order.terminal_at != self.at or order.accepted_at is not None
                    or order.reconciled or order.cancel_required or order.cancel_sent
                    or order.predecessor_id is not None
                    or (order.instrument_source, order.quote_source, order.session_source)
                    != (source, source, source)
                    or (fill.price > order.price if order.side == "BUY" else fill.price < order.price)):
                raise ValueError("TQ_MANUAL_CLOSE_INVALID")


@dataclass(frozen=True)
class TqKqObservedSignalV1:
    """Original first receipt and later account processing are distinct facts."""

    signal: Signal
    at: datetime
    policy_version: str = "tqkq_observed_signal_v1"

    def __post_init__(self):
        _time(self.at)
        if (type(self.signal) is not Signal or self.at < self.signal.observed_at
                or self.policy_version != "tqkq_observed_signal_v1"):
            raise ValueError("TQ_SIGNAL_PROCESSING_TIME_INVALID")


@dataclass(frozen=True)
class TqKqClosedSignalV1:
    """Record a first-seen terminal Bar without creating an execution target."""

    signal: Signal
    at: datetime
    session_end: datetime
    policy_version: str = "tqkq_closed_signal_record_only_v1"

    def __post_init__(self):
        _time(self.at)
        _time(self.session_end)
        if (type(self.signal) is not Signal or self.at < self.signal.observed_at
                or self.signal.bar_end != self.session_end
                or not 0 < (self.signal.observed_at - self.session_end).total_seconds() <= 60
                or self.policy_version != "tqkq_closed_signal_record_only_v1"):
            raise ValueError("TQ_CLOSED_SIGNAL_INVALID")


@dataclass(frozen=True)
class TqKqFill(Fill):
    fee: Decimal | None
    native_trade_id: str
    native_order_id: str
    snapshot_sha256: str

    def __post_init__(self):
        for value in (
            self.trade_id,
            self.order_id,
            self.account_id,
            self.contract,
            self.native_trade_id,
            self.native_order_id,
            self.snapshot_sha256,
        ):
            _text(value)
        _time(self.filled_at)
        _time(self.recorded_at)
        _money(self.price, True)
        if self.fee is not None:
            _money(self.fee)
        if (
            re.fullmatch(r"[0-9a-f]{64}", self.snapshot_sha256) is None
            or len(self.native_trade_id) > 256
            or len(self.native_order_id) > 256
            or self.quantity != 1
            or type(self.quantity) is not int
            or self.recorded_at < self.filled_at
        ):
            raise ValueError("TQ_FILL_INVALID")


@dataclass(frozen=True)
class TqKqInstrument:
    product: str
    contract: str
    at: datetime
    valid_until: datetime
    source_id: str
    tick_size: Decimal
    multiplier: Decimal
    margin_per_lot: Decimal | None
    open_fee: Decimal | None
    minimum_open_volume: int = 1

    def __post_init__(self):
        from .model import contract

        contract(self.product, self.contract)
        _time(self.at)
        _time(self.valid_until)
        _text(self.source_id)
        _money(self.tick_size, True)
        _money(self.multiplier, True)
        if self.margin_per_lot is not None:
            _money(self.margin_per_lot, True)
        if self.open_fee is not None:
            _money(self.open_fee)
        if (
            self.valid_until <= self.at
            or type(self.minimum_open_volume) is not int
            or self.minimum_open_volume < 1
        ):
            raise ValueError("TQ_INSTRUMENT_INVALID")


@dataclass(frozen=True)
class TqKqExecutionInput:
    instrument: TqKqInstrument
    session: object
    quote: object

    def __post_init__(self):
        from .model import Session, Quote

        if (
            type(self.instrument) is not TqKqInstrument
            or type(self.session) is not Session
            or self.quote is not None
            and type(self.quote) is not Quote
            or self.instrument.contract != self.session.contract
            or self.quote is not None
            and self.quote.contract != self.instrument.contract
        ):
            raise ValueError("TQ_EXECUTION_INPUT_INVALID")


@dataclass(frozen=True)
class TqKqTick:
    at: datetime
    inputs: tuple[TqKqExecutionInput, ...]
    opening_allowed: bool
    policy_version: str = TQ_EXECUTION_VERSION
    stopping: bool = False

    def __post_init__(self):
        _time(self.at)
        if (
            type(self.inputs) is not tuple
            or any(type(x) is not TqKqExecutionInput for x in self.inputs)
            or len({x.instrument.contract for x in self.inputs}) != len(self.inputs)
            or type(self.stopping) is not bool
            or type(self.opening_allowed) is not bool
            or self.policy_version != TQ_EXECUTION_VERSION
        ):
            raise ValueError("TQ_TICK_INVALID")


@dataclass(frozen=True)
class TqKqResumeEmptyV1:
    readback: object
    claims_sha256: str
    policy_version: str = "tqkq_never_active_resume_v1"

    @property
    def at(self):
        return self.readback.at

    def __post_init__(self):
        from .model import Readback

        if (
            type(self.readback) is not Readback
            or re.fullmatch(r"[0-9a-f]{64}", self.claims_sha256) is None
            or self.policy_version != "tqkq_never_active_resume_v1"
        ):
            raise ValueError("TQ_EMPTY_RECOVERY_PROOF_INVALID")
