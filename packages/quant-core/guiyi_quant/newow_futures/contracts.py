"""Independent owner-approved futures research contracts; no runtime or broker I/O."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Mapping

from guiyi_quant.new_subing import ExecutionFacts

D = Decimal
MODEL = "futures_bidir_v1"
FREQUENCIES = ("5m", "15m", "30m", "60m", "1d", "1w")
PRODUCTS = ("jm", "rb", "al", "ta")
VERSIONS = {
    "formula": "newow_futures_formula_v1", "position": "newow_futures_holding_v1",
    "risk": "newow_futures_risk_v1", "execution": "newow_futures_next_1m_v1",
    "account": "newow_futures_layers_v1", "reference": "newow_futures_reference_v1",
}
LADDERS = {
    "5m": ("30m", "60m", "1d", "1w"), "15m": ("30m", "60m", "1d", "1w"),
    "30m": ("60m", "1d", "1w"), "60m": ("1d", "1w"), "1d": ("1w",), "1w": (),
}


class Variant(StrEnum):
    TREND = "trend"
    OSCILLATION = "oscillation"
    DUAL = "dual_fusion"
    MAIN_RISE = "main_rise"
    TEST1 = "osc-test"
    TEST2 = "osc-test2"
    TEST3 = "osc-test3"
    TEST4 = "osc-test4"


@dataclass(frozen=True, slots=True)
class Bar:
    product: str
    physical_contract: str
    frequency: str
    bar_end: datetime
    trading_day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    source_identity: str
    confirmed_at: datetime
    observation_eligible: bool = True
    open_interest: Decimal | None = None
    session_open_at: datetime | None = None
    session_close_at: datetime | None = None
    owner_segment_id: str = ""
    calculation_segment_id: str = ""

    def __post_init__(self) -> None:
        if self.frequency not in ("1m", *FREQUENCIES):
            raise ValueError("FUTURES_FREQUENCY_INVALID")
        if not all(isinstance(value, str) and value.strip() for value in (
            self.product, self.physical_contract, self.source_identity,
            self.owner_segment_id, self.calculation_segment_id,
        )):
            raise ValueError("FUTURES_BAR_IDENTITY_INVALID")
        for value in (self.bar_end, self.confirmed_at, self.session_open_at, self.session_close_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("FUTURES_BAR_TIME_INVALID")
        if self.confirmed_at < self.bar_end or type(self.observation_eligible) is not bool:
            raise ValueError("FUTURES_BAR_CONFIRMATION_INVALID")
        if type(self.trading_day) is not date:
            raise ValueError("FUTURES_BAR_DAY_INVALID")
        for value in (self.open, self.high, self.low, self.close, self.volume):
            if type(value) is not Decimal or not value.is_finite():
                raise ValueError("FUTURES_BAR_NUMBER_INVALID")
        if min(self.open, self.high, self.low, self.close) <= 0 or self.volume < 0:
            raise ValueError("FUTURES_BAR_NUMBER_INVALID")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("FUTURES_BAR_OHLC_INVALID")

    @property
    def owner(self) -> tuple[str, str, str]:
        return (self.physical_contract, self.owner_segment_id, self.calculation_segment_id)


@dataclass(frozen=True, slots=True)
class ExecutionBar:
    bar: Bar
    facts: ExecutionFacts

    def __post_init__(self) -> None:
        if (self.bar.frequency != "1m" or self.bar.physical_contract != self.facts.physical_contract
                or self.bar.trading_day != self.facts.trading_day):
            raise ValueError("FUTURES_EXECUTION_FACTS_MISMATCH")


@dataclass(frozen=True, slots=True)
class Feature:
    bar: Bar
    fast: Decimal | None = None
    slow: Decimal | None = None
    slow_prev3: Decimal | None = None
    atr: Decimal | None = None
    upper: Decimal | None = None
    lower: Decimal | None = None
    high3: Decimal | None = None
    low3: Decimal | None = None
    high11: Decimal | None = None
    low11: Decimal | None = None
    ma35: Decimal | None = None
    ma45: Decimal | None = None
    ma45_prev3: Decimal | None = None
    regime: int | None = None  # None=unavailable, 0=neutral, +/-1=direction.
    previous_close: Decimal | None = None
    previous_slow: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Position:
    side: int
    entry: Decimal
    initial_stop: Decimal
    stop: Decimal
    r: Decimal
    entry_at: datetime
    stage_at: datetime
    holding_frequency: str
    branch: str
    entry_target: Decimal | None = None
    favorable_close: Decimal | None = None
    earned_r: bool = False
    upgrades: int = 0
    adds: int = 0
    reduced: bool = False
    invalid_closes: int = 0
    last_holding_bar: datetime | None = None
    confirm_reference: Decimal | None = None
    confirm_at: datetime | None = None
    overnight_eligible: bool = False


@dataclass(frozen=True, slots=True)
class Decision:
    action: str  # ENTER / CLOSE / REDUCE / ADD / WAIT; no quantity or money.
    side: int
    reason: str
    position: Position | None
    upgraded: bool = False


@dataclass(frozen=True, slots=True)
class Profile:
    variant: Variant
    frequency: str
    initial_cash: Decimal = D("100000")

    def __post_init__(self) -> None:
        if not isinstance(self.variant, Variant) or self.frequency not in FREQUENCIES:
            raise ValueError("FUTURES_PROFILE_INVALID")
        if type(self.initial_cash) is not Decimal or self.initial_cash != D("100000"):
            raise ValueError("FUTURES_CAPITAL_FROZEN")

    @property
    def profile_id(self) -> str:
        return f"newow_futures_{self.variant.value}_{self.frequency}_100k_v1"


def profile_payload(profile: Profile) -> Mapping[str, object]:
    return {"strategy_model": MODEL, "strategy": profile.variant.value, "frequency": profile.frequency,
            "profile_id": profile.profile_id, "initial_cash": str(profile.initial_cash),
            "versions": dict(VERSIONS), "research_hypothesis": True, "auto_order": False,
            "oos_status": "OOS_NOT_PROVEN"}
