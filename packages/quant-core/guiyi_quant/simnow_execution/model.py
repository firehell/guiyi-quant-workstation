"""Explicit native facts, bounded per-action intent; no connection or credentials."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import re
from ..htdy_account_execution import model as m
from ..htdy_account_execution.codec import digest

ENVIRONMENT = "SIMNOW_FIRST"
FRONT = "tcp://182.254.243.31:30001"
VERSION = "simnow_ctp_controlled_v2"


def integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError("NATIVE_INTEGER_INVALID")


def valid(at, until, now):
    for value in (at, until, now):
        m.time(value)
    if not at <= now < until:
        raise ValueError("NATIVE_FACT_STALE")


@dataclass(frozen=True)
class Contract:
    canonical: str
    native: str
    exchange: str
    source_id: str
    at: datetime
    valid_until: datetime

    def __post_init__(self):
        if self.exchange not in ("SHFE", "INE", "DCE", "CZCE", "CFFEX", "GFEX"):
            raise ValueError("EXCHANGE_INVALID")
        if re.fullmatch(r"[A-Za-z]{1,3}[0-9]{3,4}", self.native) is None:
            raise ValueError("NATIVE_CONTRACT_INVALID")
        # CZCE native 3-digit month must be explicitly proved by instrument metadata.
        if (
            re.fullmatch(
                r"[A-Z]{1,3}[0-9]{3,4}(?:\." + self.exchange + r")?", self.canonical
            )
            is None
        ):
            raise ValueError("CANONICAL_CONTRACT_INVALID")
        cp = re.match(r"[A-Za-z]+", self.canonical)[0]
        np = re.match(r"[A-Za-z]+", self.native)[0]
        if cp != np.upper():
            raise ValueError("CONTRACT_PRODUCT_MISMATCH")
        cd = self.canonical.split(".")[0][len(cp) :]
        nd = self.native[len(np) :]
        if (self.exchange == "CZCE" and cd[-3:] != nd[-3:]) or (
            self.exchange != "CZCE" and cd != nd
        ):
            raise ValueError("CONTRACT_MONTH_MISMATCH")
        m.text(self.source_id)
        valid(self.at, self.valid_until, self.at)


@dataclass(frozen=True)
class Inventory:
    contract: str
    side: int
    today: int
    yesterday: int
    source_id: str
    at: datetime
    valid_until: datetime

    def __post_init__(self):
        m.text(self.contract)
        m.text(self.source_id)
        integer(self.today)
        integer(self.yesterday)
        if (
            self.side not in (-1, 1)
            or type(self.side) is not int
            or self.today + self.yesterday != 1
        ):
            raise ValueError("ONE_LOT_NATIVE_INVENTORY_REQUIRED")
        valid(self.at, self.valid_until, self.at)


def close_offset(binding, inventory, side, now):
    if (
        type(inventory) is not Inventory
        or inventory.contract != binding.canonical
        or inventory.side != (1 if side == "SELL" else -1)
    ):
        raise ValueError("CLOSE_POSITION_MISMATCH")
    valid(inventory.at, inventory.valid_until, now)
    if binding.exchange in ("SHFE", "INE"):
        return "3" if inventory.today else "4"
    return "1"


@dataclass(frozen=True)
class Session:
    account_id: str
    environment: str
    front: str
    trading_day: str
    front_id: int
    session_id: int
    max_order_ref: int
    login_source_id: str
    settlement_source_id: str
    at: datetime
    valid_until: datetime

    def __post_init__(self):
        for value in (self.account_id, self.login_source_id, self.settlement_source_id):
            m.text(value)
        if (self.environment, self.front) != (ENVIRONMENT, FRONT):
            raise ValueError("SIMNOW_FIRST_REQUIRED")
        if re.fullmatch(r"\d{8}", self.trading_day) is None:
            raise ValueError("TRADING_DAY_INVALID")
        datetime.strptime(self.trading_day, "%Y%m%d")
        if self.trading_day < "20261027":
            raise ValueError("FUNDING_EFFECTIVE_DAY_NOT_REACHED")
        integer(self.front_id, 1)
        integer(self.session_id, 1)
        integer(self.max_order_ref)
        valid(self.at, self.valid_until, self.at)


@dataclass(frozen=True)
class Permit:
    """Owner-controlled intent bound to exact state/request facts; not a signature."""

    intent_id: str
    account_id: str
    trading_day: str
    action_hash: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self):
        for v in (self.intent_id, self.account_id, self.trading_day):
            m.text(v)
        if re.fullmatch(r"[a-f0-9]{64}", self.action_hash) is None:
            raise ValueError("ACTION_HASH_INVALID")
        valid(self.issued_at, self.expires_at, self.issued_at)
        if (self.expires_at - self.issued_at).total_seconds() > 60:
            raise ValueError("PERMIT_WINDOW_TOO_WIDE")


def action_hash(state, effect, session, binding, inventory, execution):
    return digest(
        (VERSION, digest(state), effect, session, binding, inventory, execution)
    )


@dataclass(frozen=True)
class Fee:
    trade_id: str
    amount: Decimal
    source_id: str

    def __post_init__(self):
        m.text(self.trade_id)
        m.text(self.source_id)
        m.money(self.amount)
