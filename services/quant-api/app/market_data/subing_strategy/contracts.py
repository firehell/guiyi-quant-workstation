"""Immutable SuBing Strategy V1 contracts and stable identities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
import json

from ..domain import CanonicalBar
from ..subing_lifecycle import ConfirmationSource, SubingOpportunityKey
from ..subing_research import SubingDirection
from ..subing_structure import ConfirmedPivot


_STRATEGY_ID = "subing_strategy_v1"
_FORMULA_VERSION = "subing_strategy_15m_v1"
_ALLOWED_CONFIRMATION_SOURCES = frozenset(ConfirmationSource)


class SubingStrategyPositionState(StrEnum):
    FLAT = "flat"
    LONG = "long"
    SHORT = "short"


class SubingStrategyActionKind(StrEnum):
    OPEN_LONG = "open_long"
    OPEN_SHORT = "open_short"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"


class SubingStrategyFillBasis(StrEnum):
    NEXT_BAR_OPEN = "next_bar_open"
    SEGMENT_TERMINAL_CLOSE = "segment_terminal_close"


class SubingStrategyDirection(StrEnum):
    LONG_ONLY = "long_only"
    SHORT_ONLY = "short_only"
    NO_NEW_ENTRY = "no_new_entry"
    UNAVAILABLE = "unavailable"


class SubingStrategyEpisodeState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class SubingStrategyContractError(ValueError):
    code = "SUBING_STRATEGY_CONTRACT_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


def _canonical_id(prefix: str, payload: Mapping[str, object]) -> str:
    try:
        body = json.dumps(
            dict(payload),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise SubingStrategyContractError() from None
    return f"{prefix}:{sha256(body).hexdigest()}"


def subing_opportunity_key_id(key: SubingOpportunityKey) -> str:
    if not isinstance(key, SubingOpportunityKey):
        raise SubingStrategyContractError()
    return _canonical_id(
        "subing-opportunity",
        {
            "policy_id": key.policy_id,
            "symbol": key.symbol,
            "contract": key.contract,
            "segment_start_trading_day": key.segment_start_trading_day.isoformat(),
            "direction": key.direction.value,
            "origin_at": key.origin_at.astimezone(UTC).isoformat(),
        },
    )


def subing_strategy_action_id(identity_fields: Mapping[str, object]) -> str:
    return _canonical_id("subing-action", identity_fields)


def subing_strategy_episode_id(entry_identity_fields: Mapping[str, object]) -> str:
    return _canonical_id("subing-episode", entry_identity_fields)


def _is_aware(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _percent_change(
    *, direction: SubingDirection, entry: Decimal, current: Decimal
) -> Decimal:
    if entry == 0:
        raise SubingStrategyContractError()
    raw = (current - entry) / entry * Decimal("100")
    return raw if direction is SubingDirection.LONG else -raw


@dataclass(frozen=True, slots=True)
class SubingStrategyAction:
    action_id: str
    episode_id: str
    strategy_id: str
    formula_version: str
    kind: SubingStrategyActionKind
    symbol: str
    contract: str
    trading_day: date
    segment_start_trading_day: date
    opportunity_id: str
    decision_at: datetime
    effective_bar_end: datetime
    reference_price: Decimal
    fill_basis: SubingStrategyFillBasis
    confirmation_source: ConfirmationSource | None
    reason_codes: tuple[str, ...]
    direction_context_source_day: date | None
    direction_context_target_day: date | None
    bound_reference_pivot: ConfirmedPivot | None

    def __post_init__(self) -> None:
        is_open = self.kind in {
            SubingStrategyActionKind.OPEN_LONG,
            SubingStrategyActionKind.OPEN_SHORT,
        }
        if (
            self.strategy_id != _STRATEGY_ID
            or self.formula_version != _FORMULA_VERSION
            or not isinstance(self.kind, SubingStrategyActionKind)
            or not isinstance(self.symbol, str)
            or not self.symbol
            or self.symbol != self.symbol.strip().upper()
            or not isinstance(self.contract, str)
            or not self.contract.startswith(self.symbol)
            or type(self.trading_day) is not date
            or type(self.segment_start_trading_day) is not date
            or self.trading_day < self.segment_start_trading_day
            or not isinstance(self.opportunity_id, str)
            or not self.opportunity_id.startswith("subing-opportunity:")
            or not _is_aware(self.decision_at)
            or not _is_aware(self.effective_bar_end)
            or not isinstance(self.reference_price, Decimal)
            or not self.reference_price.is_finite()
            or self.reference_price <= 0
            or not isinstance(self.fill_basis, SubingStrategyFillBasis)
            or type(self.reason_codes) is not tuple
            or any(not isinstance(reason, str) or not reason for reason in self.reason_codes)
            or len(set(self.reason_codes)) != len(self.reason_codes)
        ):
            raise SubingStrategyContractError()

        decision_at = self.decision_at.astimezone(UTC)
        effective_bar_end = self.effective_bar_end.astimezone(UTC)
        if (
            effective_bar_end < decision_at
            or (self.fill_basis is SubingStrategyFillBasis.NEXT_BAR_OPEN and effective_bar_end <= decision_at)
            or (self.fill_basis is SubingStrategyFillBasis.SEGMENT_TERMINAL_CLOSE and is_open)
            or (is_open and self.confirmation_source not in _ALLOWED_CONFIRMATION_SOURCES)
            or (not is_open and self.confirmation_source is not None)
            or (is_open and self.reason_codes)
            or (not is_open and not self.reason_codes)
            or (is_open and type(self.direction_context_source_day) is not date)
            or (is_open and type(self.direction_context_target_day) is not date)
            or (
                self.bound_reference_pivot is not None
                and (
                    self.bound_reference_pivot.contract != self.contract
                    or self.bound_reference_pivot.segment_start_trading_day
                    != self.segment_start_trading_day
                )
            )
        ):
            raise SubingStrategyContractError()

        object.__setattr__(self, "decision_at", decision_at)
        object.__setattr__(self, "effective_bar_end", effective_bar_end)
        expected_action_id = subing_strategy_action_id(self.identity_fields())
        if self.action_id != expected_action_id:
            raise SubingStrategyContractError()
        if (
            not isinstance(self.episode_id, str)
            or not self.episode_id.startswith("subing-episode:")
            or (is_open and self.episode_id != subing_strategy_episode_id(self.identity_fields()))
        ):
            raise SubingStrategyContractError()

    def identity_fields(self) -> dict[str, object]:
        return {
            "strategy_id": self.strategy_id,
            "formula_version": self.formula_version,
            "symbol": self.symbol,
            "contract": self.contract,
            "segment_start_trading_day": self.segment_start_trading_day.isoformat(),
            "opportunity_id": self.opportunity_id,
            "kind": self.kind.value,
            "decision_at": self.decision_at.astimezone(UTC).isoformat(),
            "effective_bar_end": self.effective_bar_end.astimezone(UTC).isoformat(),
            "fill_basis": self.fill_basis.value,
        }


@dataclass(frozen=True, slots=True)
class SubingStrategyEpisode:
    episode_id: str
    direction: SubingDirection
    entry_action: SubingStrategyAction
    exit_action: SubingStrategyAction | None
    state: SubingStrategyEpisodeState
    holding_bar_count: int
    reference_change_percent: Decimal | None
    current_reference_change_percent: Decimal | None
    latest_reference_price: Decimal | None
    exit_reason_codes: tuple[str, ...]
    structure_exit_available: bool

    @classmethod
    def from_actions(
        cls,
        *,
        entry_action: SubingStrategyAction,
        exit_action: SubingStrategyAction | None,
        completed_15m_bars: Sequence[CanonicalBar],
        latest_reference_price: Decimal | None,
    ) -> SubingStrategyEpisode:
        if (
            not isinstance(entry_action, SubingStrategyAction)
            or entry_action.kind
            not in {
                SubingStrategyActionKind.OPEN_LONG,
                SubingStrategyActionKind.OPEN_SHORT,
            }
        ):
            raise SubingStrategyContractError()
        direction = (
            SubingDirection.LONG
            if entry_action.kind is SubingStrategyActionKind.OPEN_LONG
            else SubingDirection.SHORT
        )
        expected_exit_kind = (
            SubingStrategyActionKind.CLOSE_LONG
            if direction is SubingDirection.LONG
            else SubingStrategyActionKind.CLOSE_SHORT
        )
        if exit_action is not None and (
            not isinstance(exit_action, SubingStrategyAction)
            or exit_action.kind is not expected_exit_kind
            or exit_action.episode_id != entry_action.episode_id
            or any(
                getattr(exit_action, field) != getattr(entry_action, field)
                for field in (
                    "strategy_id",
                    "formula_version",
                    "symbol",
                    "contract",
                    "segment_start_trading_day",
                    "opportunity_id",
                )
            )
            or exit_action.decision_at < entry_action.effective_bar_end
            or exit_action.effective_bar_end < entry_action.effective_bar_end
        ):
            raise SubingStrategyContractError()

        bars = tuple(completed_15m_bars)
        if (
            any(not isinstance(bar, CanonicalBar) for bar in bars)
            or any(left.bar_end >= right.bar_end for left, right in zip(bars, bars[1:]))
        ):
            raise SubingStrategyContractError()
        holding_through = exit_action.decision_at if exit_action is not None else None
        holding_bars = tuple(
            bar
            for bar in bars
            if bar.bar_end >= entry_action.effective_bar_end
            and (holding_through is None or bar.bar_end <= holding_through)
        )
        if not holding_bars:
            raise SubingStrategyContractError()

        if exit_action is None:
            expected_latest = holding_bars[-1].close
            if latest_reference_price != expected_latest:
                raise SubingStrategyContractError()
            current_change = _percent_change(
                direction=direction,
                entry=entry_action.reference_price,
                current=expected_latest,
            )
            reference_change = None
            state = SubingStrategyEpisodeState.OPEN
            exit_reasons: tuple[str, ...] = ()
        else:
            if latest_reference_price is not None:
                raise SubingStrategyContractError()
            current_change = None
            reference_change = _percent_change(
                direction=direction,
                entry=entry_action.reference_price,
                current=exit_action.reference_price,
            )
            state = SubingStrategyEpisodeState.CLOSED
            exit_reasons = exit_action.reason_codes

        return cls(
            episode_id=entry_action.episode_id,
            direction=direction,
            entry_action=entry_action,
            exit_action=exit_action,
            state=state,
            holding_bar_count=len(holding_bars),
            reference_change_percent=reference_change,
            current_reference_change_percent=current_change,
            latest_reference_price=latest_reference_price,
            exit_reason_codes=exit_reasons,
            structure_exit_available=entry_action.bound_reference_pivot is not None,
        )
