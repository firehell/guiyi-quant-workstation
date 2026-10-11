"""LMS 4.0.5 evidence replay v0.1: no inferred fills or private formula claims."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
import re

VERSION = "lms405-evidence-v0.1"
ZERO = Decimal(0)


def physical_contract(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[A-Z]{1,3}\d{4}", value) is None:
        raise ValueError("PHYSICAL_CONTRACT_REQUIRED")


def number(value: Decimal, *, positive: bool = False) -> None:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value < ZERO
        or (positive and value == ZERO)
    ):
        raise ValueError("INVALID_DECIMAL")


def timestamp(value: datetime) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("AWARE_TIMESTAMP_REQUIRED")


@dataclass(frozen=True)
class Bar:
    contract: str
    end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    completed: bool = True
    start: datetime | None = None

    def __post_init__(self):
        physical_contract(self.contract)
        timestamp(self.end)
        if self.start is not None:
            timestamp(self.start)
            if self.start >= self.end:
                raise ValueError("INVALID_BAR_INTERVAL")
        for x in (self.open, self.high, self.low, self.close):
            number(x, positive=True)
        if (
            not self.contract
            or not self.completed
            or not self.low
            <= min(self.open, self.close)
            <= max(self.open, self.close)
            <= self.high
        ):
            raise ValueError("COMPLETED_PHYSICAL_OHLC_REQUIRED")


@dataclass(frozen=True)
class Zone:
    id: str
    contract: str
    lower: Decimal
    upper: Decimal
    known_at: datetime
    source: str
    expires_at: datetime | None = None

    def __post_init__(self):
        physical_contract(self.contract)
        timestamp(self.known_at)
        number(self.lower, positive=True)
        number(self.upper, positive=True)
        if (
            not self.id
            or not self.contract
            or not self.source
            or self.lower > self.upper
        ):
            raise ValueError("INVALID_ZONE")
        if self.expires_at is not None:
            timestamp(self.expires_at)
            if self.expires_at <= self.known_at:
                raise ValueError("INVALID_ZONE_EXPIRY")


@dataclass(frozen=True)
class Position:
    contract: str
    long: Decimal = ZERO
    short: Decimal = ZERO

    def __post_init__(self):
        physical_contract(self.contract)
        number(self.long)
        number(self.short)


@dataclass(frozen=True)
class Action:
    kind: str
    quantity: Decimal

    def __post_init__(self):
        number(self.quantity, positive=True)
        if self.kind not in {
            "ENTER_LONG",
            "ENTER_SHORT",
            "REENTER_LONG",
            "REENTER_SHORT",
            "LOCK",
            "UNLOCK_LONG",
            "UNLOCK_SHORT",
            "EXIT_LONG",
            "EXIT_SHORT",
            "CLEAR",
        }:
            raise ValueError("UNKNOWN_ACTION")


def apply_action(p: Position, a: Action) -> Position:
    """Normalize a disclosed action; never predicts author action or creates a Fill.

    Quantity is the original directional leg for LOCK and equal legs for UNLOCK.
    CLEAR quantity must equal gross quantity, so implicit partial clear is rejected.
    """
    long, short, quantity = p.long, p.short, a.quantity
    flat = long == short == ZERO
    if a.kind in {"ENTER_LONG", "REENTER_LONG"} and flat:
        return Position(p.contract, quantity, ZERO)
    if a.kind in {"ENTER_SHORT", "REENTER_SHORT"} and flat:
        return Position(p.contract, ZERO, quantity)
    if a.kind == "LOCK" and (
        (long == quantity and short == ZERO) or (short == quantity and long == ZERO)
    ):
        return Position(p.contract, quantity, quantity)
    if a.kind == "UNLOCK_LONG" and long == short == quantity:
        return Position(p.contract, quantity, ZERO)
    if a.kind == "UNLOCK_SHORT" and long == short == quantity:
        return Position(p.contract, ZERO, quantity)
    if a.kind == "EXIT_LONG" and long >= quantity:
        return Position(p.contract, long - quantity, short)
    if a.kind == "EXIT_SHORT" and short >= quantity:
        return Position(p.contract, long, short - quantity)
    if a.kind == "CLEAR" and long + short == quantity and not flat:
        return Position(p.contract)
    raise ValueError("ACTION_STATE_CONFLICT")


def inspect_bar(
    bar: Bar, zones: list[Zone], *, mode: Literal["author", "independent"] = "author"
) -> dict:
    """Geometric observations only. A touch is not BBB or stand-firm permission."""
    if mode not in {"author", "independent"}:
        raise ValueError("UNKNOWN_MODE")
    observations = []
    for z in zones if mode == "author" else []:
        if (
            z.contract != bar.contract
            or bar.start is None
            or not z.known_at < bar.start
            or (z.expires_at is not None and bar.end >= z.expires_at)
        ):
            continue
        lo = bar.low <= z.lower <= bar.high
        hi = bar.low <= z.upper <= bar.high
        observations.append(
            {
                "zone_id": z.id,
                "source": z.source,
                "lower_touched": lo,
                "upper_touched": hi,
                "both_endpoints_touched": lo and hi,
                "sequence": "INTRABAR_ORDER_UNKNOWN"
                if lo and hi
                else "NOT_ESTABLISHED",
                "close_location": "ABOVE"
                if bar.close > z.upper
                else "BELOW"
                if bar.close < z.lower
                else "INSIDE",
            }
        )
    return {
        "version": VERSION,
        "contract": bar.contract,
        "bar_end": bar.end.isoformat(),
        "mode": mode,
        "environment": "UNKNOWN",
        "signal": "UNKNOWN",
        "action": "INDETERMINATE",
        "zones": observations,
        "unknown": [
            "BBB_KEYBAR_FORMULA",
            "ENVIRONMENT_CLASSIFIER",
            "STAND_FIRM_PERMISSION",
            "INDEPENDENT_ZONE_GENERATOR",
        ],
        "executable": False,
    }


@dataclass(frozen=True)
class Event:
    id: str
    contract: str
    effective_at: datetime
    known_at: datetime
    action: Action
    source: str
    manual: bool = False

    def __post_init__(self):
        physical_contract(self.contract)
        timestamp(self.effective_at)
        physical_contract(self.contract)
        timestamp(self.known_at)
        if not self.id or not self.contract or not self.source:
            raise ValueError("EVENT_IDENTITY_REQUIRED")


def replay_events(
    contract: str,
    events: list[Event],
    *,
    cutoff: datetime,
    initial: Position | None = None,
) -> Position:
    """Replay explicit observations, never use it as a prediction-match numerator.

    Late disclosures remain evidence only. Simultaneous operations have no order.
    Initial flat is a unit research assumption, not an author's account assertion.
    """
    timestamp(cutoff)
    p = initial if initial is not None else Position(contract)
    if p.contract != contract:
        raise ValueError("CONTRACT_BOUNDARY")
    unique = {}
    for e in events:
        if e.contract != contract:
            raise ValueError("CONTRACT_BOUNDARY")
        if e.id in unique and unique[e.id] != e:
            raise ValueError("EVENT_ID_CONFLICT")
        unique[e.id] = e
    eligible = sorted(
        (e for e in unique.values() if e.known_at < e.effective_at <= cutoff),
        key=lambda e: e.effective_at,
    )
    if len({e.effective_at for e in eligible}) != len(eligible):
        raise ValueError("ACTION_ORDER_UNKNOWN")
    for e in eligible:
        p = apply_action(p, e.action)
    return p
