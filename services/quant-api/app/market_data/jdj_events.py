"""Immutable source events shared by the JDJ 1m research reducers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
import re

from .domain import normalize_contract_for_symbol
from .jdj_context import JdjContextError


_JDJ_SOURCE_KIND = "jdj_1m"
_JDJ_TREND_FOLLOW_CANDIDATE_ID = "jdj_trend_follow_1m_candidate_v1"
_JDJ_TREND_FOLLOW_SOURCE_EVENT_KIND = "jdj_trend_follow_triggered"
_JDJ_TREND_REENTRY_CANDIDATE_ID = "jdj_trend_reentry_6_1m_candidate_v1"
_JDJ_TREND_REENTRY_SOURCE_EVENT_KIND = "jdj_trend_reentry_6_triggered"
_JDJ_KEY_LEVEL_BREAKOUT_CANDIDATE_ID = (
    "jdj_key_level_breakout_1m_candidate_v1"
)
_JDJ_KEY_LEVEL_BREAKOUT_SOURCE_EVENT_KIND = (
    "jdj_key_level_breakout_triggered"
)
_SYMBOL_PATTERN = re.compile(r"[a-z]+\Z")


class JdjDirection(StrEnum):
    LONG = "long"
    SHORT = "short"


class JdjSetupKind(StrEnum):
    TREND_FOLLOW = "trend_follow"
    TREND_REENTRY_6 = "trend_reentry_6"
    KEY_LEVEL_BREAKOUT = "key_level_breakout"


@dataclass(frozen=True, slots=True)
class JdjTrendFollowTriggerEvent:
    event_id: str
    source_kind: str
    setup_kind: JdjSetupKind
    candidate_id: str
    source_event_kind: str
    direction: JdjDirection
    symbol: str
    contract: str
    segment_start_trading_day: date
    trading_day: date
    observed_at: datetime
    segment_bar_index: int
    trend_snapshot_observed_at: datetime
    reaction_at: datetime
    ema20_at_reaction: Decimal
    trigger_level: Decimal
    observation_close: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.event_id) is not str
            or self.source_kind != _JDJ_SOURCE_KIND
            or self.setup_kind is not JdjSetupKind.TREND_FOLLOW
            or self.candidate_id != _JDJ_TREND_FOLLOW_CANDIDATE_ID
            or self.source_event_kind
            != _JDJ_TREND_FOLLOW_SOURCE_EVENT_KIND
            or not isinstance(self.direction, JdjDirection)
            or not _valid_symbol(self.symbol)
            or normalize_contract_for_symbol(self.symbol, self.contract)
            != self.contract
            or type(self.segment_start_trading_day) is not date
            or type(self.trading_day) is not date
            or self.trading_day < self.segment_start_trading_day
            or not _aware_datetime(self.observed_at)
            or type(self.segment_bar_index) is not int
            or self.segment_bar_index <= 0
            or not _aware_datetime(self.trend_snapshot_observed_at)
            or not _aware_datetime(self.reaction_at)
            or not _finite_decimal(self.ema20_at_reaction)
            or not _finite_decimal(self.trigger_level)
            or not _finite_decimal(self.observation_close)
        ):
            raise JdjContextError()

        observed_at = self.observed_at.astimezone(UTC)
        snapshot_at = self.trend_snapshot_observed_at.astimezone(UTC)
        reaction_at = self.reaction_at.astimezone(UTC)
        if (
            snapshot_at >= reaction_at
            or reaction_at >= observed_at
            or self.event_id
            != _canonical_trend_follow_event_id(
                candidate_id=self.candidate_id,
                symbol=self.symbol,
                contract=self.contract,
                segment_start_trading_day=self.segment_start_trading_day,
                direction=self.direction,
                reaction_at=reaction_at,
                observed_at=observed_at,
                trigger_level=self.trigger_level,
            )
        ):
            raise JdjContextError()

        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "trend_snapshot_observed_at", snapshot_at)
        object.__setattr__(self, "reaction_at", reaction_at)


@dataclass(frozen=True, slots=True)
class JdjTrendReentryTriggerEvent:
    event_id: str
    source_kind: str
    setup_kind: JdjSetupKind
    candidate_id: str
    source_event_kind: str
    direction: JdjDirection
    symbol: str
    contract: str
    segment_start_trading_day: date
    trading_day: date
    observed_at: datetime
    segment_bar_index: int
    trend_snapshot_observed_at: datetime
    excursion_started_at: datetime
    excursion_extreme: Decimal
    reclaimed_at: datetime
    reaction_at: datetime
    trigger_level: Decimal
    observation_close: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.event_id) is not str
            or self.source_kind != _JDJ_SOURCE_KIND
            or self.setup_kind is not JdjSetupKind.TREND_REENTRY_6
            or self.candidate_id != _JDJ_TREND_REENTRY_CANDIDATE_ID
            or self.source_event_kind
            != _JDJ_TREND_REENTRY_SOURCE_EVENT_KIND
            or not isinstance(self.direction, JdjDirection)
            or not _valid_symbol(self.symbol)
            or normalize_contract_for_symbol(self.symbol, self.contract)
            != self.contract
            or type(self.segment_start_trading_day) is not date
            or type(self.trading_day) is not date
            or self.trading_day < self.segment_start_trading_day
            or not _aware_datetime(self.observed_at)
            or type(self.segment_bar_index) is not int
            or self.segment_bar_index <= 0
            or not _aware_datetime(self.trend_snapshot_observed_at)
            or not _aware_datetime(self.excursion_started_at)
            or not _finite_decimal(self.excursion_extreme)
            or not _aware_datetime(self.reclaimed_at)
            or not _aware_datetime(self.reaction_at)
            or not _finite_decimal(self.trigger_level)
            or not _finite_decimal(self.observation_close)
        ):
            raise JdjContextError()

        observed_at = self.observed_at.astimezone(UTC)
        snapshot_at = self.trend_snapshot_observed_at.astimezone(UTC)
        excursion_started_at = self.excursion_started_at.astimezone(UTC)
        reclaimed_at = self.reclaimed_at.astimezone(UTC)
        reaction_at = self.reaction_at.astimezone(UTC)
        if (
            snapshot_at >= reaction_at
            or excursion_started_at >= reclaimed_at
            or reclaimed_at >= reaction_at
            or reaction_at >= observed_at
            or self.event_id
            != _canonical_trend_reentry_event_id(
                candidate_id=self.candidate_id,
                symbol=self.symbol,
                contract=self.contract,
                segment_start_trading_day=self.segment_start_trading_day,
                direction=self.direction,
                excursion_started_at=excursion_started_at,
                excursion_extreme=self.excursion_extreme,
                reclaimed_at=reclaimed_at,
                reaction_at=reaction_at,
                observed_at=observed_at,
                trigger_level=self.trigger_level,
            )
        ):
            raise JdjContextError()

        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "trend_snapshot_observed_at", snapshot_at)
        object.__setattr__(
            self,
            "excursion_started_at",
            excursion_started_at,
        )
        object.__setattr__(self, "reclaimed_at", reclaimed_at)
        object.__setattr__(self, "reaction_at", reaction_at)


@dataclass(frozen=True, slots=True)
class JdjKeyLevelBreakoutTriggerEvent:
    event_id: str
    source_kind: str
    setup_kind: JdjSetupKind
    candidate_id: str
    source_event_kind: str
    direction: JdjDirection
    symbol: str
    contract: str
    segment_start_trading_day: date
    trading_day: date
    observed_at: datetime
    segment_bar_index: int
    trend_snapshot_observed_at: datetime
    trend_epoch: int
    key_level_pivot_id: str
    key_level_price: Decimal
    key_level_confirmed_at: datetime
    first_break_at: datetime
    retest_at: datetime
    trigger_level: Decimal
    observation_close: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.event_id) is not str
            or self.source_kind != _JDJ_SOURCE_KIND
            or self.setup_kind is not JdjSetupKind.KEY_LEVEL_BREAKOUT
            or self.candidate_id != _JDJ_KEY_LEVEL_BREAKOUT_CANDIDATE_ID
            or self.source_event_kind
            != _JDJ_KEY_LEVEL_BREAKOUT_SOURCE_EVENT_KIND
            or not isinstance(self.direction, JdjDirection)
            or not _valid_symbol(self.symbol)
            or normalize_contract_for_symbol(self.symbol, self.contract)
            != self.contract
            or type(self.segment_start_trading_day) is not date
            or type(self.trading_day) is not date
            or self.trading_day < self.segment_start_trading_day
            or not _aware_datetime(self.observed_at)
            or type(self.segment_bar_index) is not int
            or self.segment_bar_index <= 0
            or not _aware_datetime(self.trend_snapshot_observed_at)
            or type(self.trend_epoch) is not int
            or self.trend_epoch < 0
            or type(self.key_level_pivot_id) is not str
            or not self.key_level_pivot_id
            or "|" in self.key_level_pivot_id
            or not _finite_decimal(self.key_level_price)
            or self.key_level_price <= 0
            or not _aware_datetime(self.key_level_confirmed_at)
            or not _valid_key_level_pivot_identity(
                self.key_level_pivot_id,
                direction=self.direction,
                contract=self.contract,
                segment_start_trading_day=(
                    self.segment_start_trading_day
                ),
                trend_epoch=self.trend_epoch,
                confirmed_at=self.key_level_confirmed_at,
            )
            or not _aware_datetime(self.first_break_at)
            or not _aware_datetime(self.retest_at)
            or not _finite_decimal(self.trigger_level)
            or not _finite_decimal(self.observation_close)
        ):
            raise JdjContextError()

        observed_at = self.observed_at.astimezone(UTC)
        snapshot_at = self.trend_snapshot_observed_at.astimezone(UTC)
        confirmed_at = self.key_level_confirmed_at.astimezone(UTC)
        first_break_at = self.first_break_at.astimezone(UTC)
        retest_at = self.retest_at.astimezone(UTC)
        if (
            confirmed_at >= first_break_at
            or snapshot_at >= retest_at
            or first_break_at >= retest_at
            or retest_at >= observed_at
            or self.event_id
            != _canonical_key_level_breakout_event_id(
                candidate_id=self.candidate_id,
                symbol=self.symbol,
                contract=self.contract,
                segment_start_trading_day=self.segment_start_trading_day,
                direction=self.direction,
                trend_epoch=self.trend_epoch,
                key_level_pivot_id=self.key_level_pivot_id,
                key_level_price=self.key_level_price,
                key_level_confirmed_at=confirmed_at,
                first_break_at=first_break_at,
                retest_at=retest_at,
                observed_at=observed_at,
                trigger_level=self.trigger_level,
            )
        ):
            raise JdjContextError()

        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "trend_snapshot_observed_at", snapshot_at)
        object.__setattr__(
            self,
            "key_level_confirmed_at",
            confirmed_at,
        )
        object.__setattr__(self, "first_break_at", first_break_at)
        object.__setattr__(self, "retest_at", retest_at)


def _canonical_trend_follow_event_id(
    *,
    candidate_id: str,
    symbol: str,
    contract: str,
    segment_start_trading_day: date,
    direction: JdjDirection,
    reaction_at: datetime,
    observed_at: datetime,
    trigger_level: Decimal,
) -> str:
    return "|".join(
        (
            candidate_id,
            symbol,
            contract,
            segment_start_trading_day.isoformat(),
            direction.value,
            reaction_at.astimezone(UTC).isoformat(),
            observed_at.astimezone(UTC).isoformat(),
            _decimal_identity(trigger_level),
        )
    )


def _canonical_trend_reentry_event_id(
    *,
    candidate_id: str,
    symbol: str,
    contract: str,
    segment_start_trading_day: date,
    direction: JdjDirection,
    excursion_started_at: datetime,
    excursion_extreme: Decimal,
    reclaimed_at: datetime,
    reaction_at: datetime,
    observed_at: datetime,
    trigger_level: Decimal,
) -> str:
    return "|".join(
        (
            candidate_id,
            symbol,
            contract,
            segment_start_trading_day.isoformat(),
            direction.value,
            excursion_started_at.astimezone(UTC).isoformat(),
            _decimal_identity(excursion_extreme),
            reclaimed_at.astimezone(UTC).isoformat(),
            reaction_at.astimezone(UTC).isoformat(),
            observed_at.astimezone(UTC).isoformat(),
            _decimal_identity(trigger_level),
        )
    )


def _canonical_key_level_breakout_event_id(
    *,
    candidate_id: str,
    symbol: str,
    contract: str,
    segment_start_trading_day: date,
    direction: JdjDirection,
    trend_epoch: int,
    key_level_pivot_id: str,
    key_level_price: Decimal,
    key_level_confirmed_at: datetime,
    first_break_at: datetime,
    retest_at: datetime,
    observed_at: datetime,
    trigger_level: Decimal,
) -> str:
    return "|".join(
        (
            candidate_id,
            symbol,
            contract,
            segment_start_trading_day.isoformat(),
            direction.value,
            str(trend_epoch),
            key_level_pivot_id,
            _decimal_identity(key_level_price),
            key_level_confirmed_at.astimezone(UTC).isoformat(),
            first_break_at.astimezone(UTC).isoformat(),
            retest_at.astimezone(UTC).isoformat(),
            observed_at.astimezone(UTC).isoformat(),
            _decimal_identity(trigger_level),
        )
    )


def _decimal_identity(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _valid_symbol(value: object) -> bool:
    return (
        type(value) is str
        and _SYMBOL_PATTERN.fullmatch(value) is not None
    )


def _aware_datetime(value: object) -> bool:
    return (
        type(value) is datetime
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _finite_decimal(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite()


def _valid_key_level_pivot_identity(
    value: str,
    *,
    direction: JdjDirection,
    contract: str,
    segment_start_trading_day: date,
    trend_epoch: int,
    confirmed_at: datetime,
) -> bool:
    parts = value.split(":", 5)
    if len(parts) != 6:
        return False
    expected_kind = (
        "high" if direction is JdjDirection.LONG else "low"
    )
    if parts[:5] != [
        contract,
        segment_start_trading_day.isoformat(),
        "5m",
        str(trend_epoch),
        expected_kind,
    ]:
        return False
    try:
        pivot_at = datetime.fromisoformat(parts[5])
    except ValueError:
        return False
    return _aware_datetime(pivot_at) and pivot_at < confirmed_at
