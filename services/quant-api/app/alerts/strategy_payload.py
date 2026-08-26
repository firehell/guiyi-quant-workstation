"""Exact immutable JSON boundary for SuBing Strategy Action events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from app.market_data.domain import BarFrequency
from app.market_data.subing_lifecycle import ConfirmationSource
from app.market_data.subing_strategy.contracts import (
    SubingStrategyAction,
    SubingStrategyActionKind,
    SubingStrategyEpisode,
    SubingStrategyFillBasis,
    subing_strategy_action_id,
    subing_strategy_episode_id,
)
from app.market_data.subing_structure import ConfirmedPivot, PivotKind


_COMMON_KEYS = frozenset(
    {
        "schema_version",
        "strategy_id",
        "formula_version",
        "action_id",
        "episode_id",
        "kind",
        "symbol",
        "contract",
        "trading_day",
        "segment_start_trading_day",
        "opportunity_id",
        "decision_at",
        "effective_open_at",
        "effective_bar_end",
        "reference_price",
        "fill_basis",
        "confirmation_source",
        "reason_codes",
        "direction_context_source_day",
        "direction_context_target_day",
        "bound_reference_pivot",
        "entry",
        "holding_bar_count",
        "reference_change_percent",
    }
)
_ENTRY_KEYS = frozenset(
    {
        "action_id",
        "kind",
        "effective_bar_end",
        "reference_price",
        "confirmation_source",
    }
)
_PIVOT_KEYS = frozenset(
    {
        "pivot_id",
        "kind",
        "source_timeframe",
        "pivot_time",
        "confirmed_at",
        "price",
        "contract",
        "segment_start_trading_day",
    }
)
_OPEN_KINDS = frozenset(
    {SubingStrategyActionKind.OPEN_LONG, SubingStrategyActionKind.OPEN_SHORT}
)
_CLOSE_KINDS = frozenset(
    {SubingStrategyActionKind.CLOSE_LONG, SubingStrategyActionKind.CLOSE_SHORT}
)
_LONG_EXIT_REASON_CODES = (
    "EMA21_BREACH_LONG",
    "PREVIOUS_BAR_LOW_BREACH",
    "BOUND_LOW_PIVOT_BREACH",
    "MACD_HIGH_DEAD_CROSS",
    "CONTRACT_SEGMENT_END",
)
_SHORT_EXIT_REASON_CODES = (
    "EMA21_BREACH_SHORT",
    "PREVIOUS_BAR_HIGH_BREACH",
    "BOUND_HIGH_PIVOT_BREACH",
    "MACD_LOW_GOLDEN_CROSS",
    "CONTRACT_SEGMENT_END",
)
_IDENTITY_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class StrategyPayloadError(ValueError):
    """The stored Strategy payload is not the exact accepted schema."""

    code = "SUBING_STRATEGY_PAYLOAD_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class SubingStrategyEntryPayload:
    action_id: str
    kind: SubingStrategyActionKind
    effective_bar_end: datetime
    reference_price: Decimal
    confirmation_source: ConfirmationSource

    def to_json(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "kind": self.kind.value,
            "effective_bar_end": _datetime_text(self.effective_bar_end),
            "reference_price": _decimal_text(self.reference_price),
            "confirmation_source": self.confirmation_source.value,
        }


@dataclass(frozen=True, slots=True)
class SubingStrategyActionPayload:
    schema_version: int
    strategy_id: str
    formula_version: str
    action_id: str
    episode_id: str
    kind: SubingStrategyActionKind
    symbol: str
    contract: str
    trading_day: date
    segment_start_trading_day: date
    opportunity_id: str
    decision_at: datetime
    effective_open_at: datetime | None
    effective_bar_end: datetime
    reference_price: Decimal
    fill_basis: SubingStrategyFillBasis
    confirmation_source: ConfirmationSource | None
    reason_codes: tuple[str, ...]
    direction_context_source_day: date | None
    direction_context_target_day: date | None
    bound_reference_pivot: ConfirmedPivot | None
    entry: SubingStrategyEntryPayload | None
    holding_bar_count: int | None
    reference_change_percent: Decimal | None

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "strategy_id": self.strategy_id,
            "formula_version": self.formula_version,
            "action_id": self.action_id,
            "episode_id": self.episode_id,
            "kind": self.kind.value,
            "symbol": self.symbol,
            "contract": self.contract,
            "trading_day": self.trading_day.isoformat(),
            "segment_start_trading_day": self.segment_start_trading_day.isoformat(),
            "opportunity_id": self.opportunity_id,
            "decision_at": _datetime_text(self.decision_at),
            "effective_open_at": (
                _datetime_text(self.effective_open_at)
                if self.effective_open_at is not None
                else None
            ),
            "effective_bar_end": _datetime_text(self.effective_bar_end),
            "reference_price": _decimal_text(self.reference_price),
            "fill_basis": self.fill_basis.value,
            "confirmation_source": (
                self.confirmation_source.value
                if self.confirmation_source is not None
                else None
            ),
            "reason_codes": list(self.reason_codes),
            "direction_context_source_day": (
                self.direction_context_source_day.isoformat()
                if self.direction_context_source_day is not None
                else None
            ),
            "direction_context_target_day": (
                self.direction_context_target_day.isoformat()
                if self.direction_context_target_day is not None
                else None
            ),
            "bound_reference_pivot": _pivot_json(self.bound_reference_pivot),
            "entry": self.entry.to_json() if self.entry is not None else None,
            "holding_bar_count": self.holding_bar_count,
            "reference_change_percent": (
                _decimal_text(self.reference_change_percent)
                if self.reference_change_percent is not None
                else None
            ),
        }


def serialize_subing_strategy_payload(
    action: SubingStrategyAction,
    *,
    episode: SubingStrategyEpisode | None = None,
) -> SubingStrategyActionPayload:
    """Serialize only validated core Action/Episode facts without recalculation."""

    if not isinstance(action, SubingStrategyAction):
        raise StrategyPayloadError()
    is_open = action.kind in _OPEN_KINDS
    if is_open:
        if episode is not None:
            raise StrategyPayloadError()
        entry = None
        holding_bar_count = None
        reference_change_percent = None
    else:
        if (
            not isinstance(episode, SubingStrategyEpisode)
            or episode.exit_action != action
            or episode.episode_id != action.episode_id
            or episode.reference_change_percent is None
            or episode.exit_reason_codes != action.reason_codes
            or episode.entry_action.bound_reference_pivot
            != action.bound_reference_pivot
        ):
            raise StrategyPayloadError()
        source = episode.entry_action
        entry = SubingStrategyEntryPayload(
            action_id=source.action_id,
            kind=source.kind,
            effective_bar_end=source.effective_bar_end,
            reference_price=source.reference_price,
            confirmation_source=_required_confirmation(source.confirmation_source),
        )
        holding_bar_count = episode.holding_bar_count
        reference_change_percent = episode.reference_change_percent

    payload = SubingStrategyActionPayload(
        schema_version=1,
        strategy_id=action.strategy_id,
        formula_version=action.formula_version,
        action_id=action.action_id,
        episode_id=action.episode_id,
        kind=action.kind,
        symbol=action.symbol,
        contract=action.contract,
        trading_day=action.trading_day,
        segment_start_trading_day=action.segment_start_trading_day,
        opportunity_id=action.opportunity_id,
        decision_at=action.decision_at,
        effective_open_at=action.effective_open_at,
        effective_bar_end=action.effective_bar_end,
        reference_price=action.reference_price,
        fill_basis=action.fill_basis,
        confirmation_source=action.confirmation_source,
        reason_codes=action.reason_codes,
        direction_context_source_day=action.direction_context_source_day,
        direction_context_target_day=action.direction_context_target_day,
        bound_reference_pivot=action.bound_reference_pivot,
        entry=entry,
        holding_bar_count=holding_bar_count,
        reference_change_percent=reference_change_percent,
    )
    return parse_subing_strategy_payload(payload.to_json())


def parse_subing_strategy_payload(payload: object) -> SubingStrategyActionPayload:
    """Parse and validate an exact stored Strategy payload."""

    try:
        raw = _exact_dict(payload, _COMMON_KEYS)
        kind = SubingStrategyActionKind(_exact_str(raw["kind"]))
        parsed = SubingStrategyActionPayload(
            schema_version=_exact_int(raw["schema_version"]),
            strategy_id=_exact_str(raw["strategy_id"]),
            formula_version=_exact_str(raw["formula_version"]),
            action_id=_exact_str(raw["action_id"]),
            episode_id=_exact_str(raw["episode_id"]),
            kind=kind,
            symbol=_exact_str(raw["symbol"]),
            contract=_exact_str(raw["contract"]),
            trading_day=_date(raw["trading_day"]),
            segment_start_trading_day=_date(raw["segment_start_trading_day"]),
            opportunity_id=_exact_str(raw["opportunity_id"]),
            decision_at=_datetime(raw["decision_at"]),
            effective_open_at=_optional_datetime(raw["effective_open_at"]),
            effective_bar_end=_datetime(raw["effective_bar_end"]),
            reference_price=_decimal(raw["reference_price"]),
            fill_basis=SubingStrategyFillBasis(_exact_str(raw["fill_basis"])),
            confirmation_source=(
                ConfirmationSource(_exact_str(raw["confirmation_source"]))
                if raw["confirmation_source"] is not None
                else None
            ),
            reason_codes=_string_tuple(raw["reason_codes"]),
            direction_context_source_day=_optional_date(
                raw["direction_context_source_day"]
            ),
            direction_context_target_day=_optional_date(
                raw["direction_context_target_day"]
            ),
            bound_reference_pivot=_parse_pivot(raw["bound_reference_pivot"]),
            entry=_parse_entry(raw["entry"]),
            holding_bar_count=_optional_positive_int(raw["holding_bar_count"]),
            reference_change_percent=_optional_decimal(raw["reference_change_percent"]),
        )
        _validate_payload(parsed)
        if parsed.to_json() != raw:
            raise StrategyPayloadError()
        return parsed
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise StrategyPayloadError() from None


def validate_subing_strategy_event_facts(
    payload: SubingStrategyActionPayload,
    *,
    action_id: str,
    symbol: str,
    contract: str,
    trading_day: date,
    frequency: str,
    bar_end: datetime,
    result_codes: tuple[str, ...],
) -> None:
    """Cross-check the typed payload against immutable AlertEvent columns."""

    if (
        not isinstance(payload, SubingStrategyActionPayload)
        or payload.action_id != action_id
        or payload.symbol != symbol
        or payload.contract != contract
        or payload.trading_day != trading_day
        or frequency != "15m"
        or payload.decision_at != bar_end.astimezone(UTC)
        or result_codes != (payload.kind.value,)
    ):
        raise StrategyPayloadError()


def _validate_payload(payload: SubingStrategyActionPayload) -> None:
    is_open = payload.kind in _OPEN_KINDS
    expected_pivot_kind = (
        PivotKind.LOW
        if payload.kind
        in {SubingStrategyActionKind.OPEN_LONG, SubingStrategyActionKind.CLOSE_LONG}
        else PivotKind.HIGH
    )
    expected_identity = {
        "strategy_id": payload.strategy_id,
        "formula_version": payload.formula_version,
        "symbol": payload.symbol,
        "contract": payload.contract,
        "segment_start_trading_day": payload.segment_start_trading_day.isoformat(),
        "opportunity_id": payload.opportunity_id,
        "kind": payload.kind.value,
        "decision_at": _datetime_text(payload.decision_at),
        "effective_bar_end": _datetime_text(payload.effective_bar_end),
        "fill_basis": payload.fill_basis.value,
    }
    if (
        payload.schema_version != 1
        or payload.strategy_id != "subing_strategy_v1"
        or payload.formula_version != "subing_strategy_15m_v1"
        or payload.action_id != subing_strategy_action_id(expected_identity)
        or not payload.episode_id.startswith("subing-episode:")
        or not payload.symbol.isascii()
        or not payload.symbol.isalpha()
        or payload.symbol != payload.symbol.lower()
        or not payload.contract.startswith(payload.symbol.upper())
        or payload.trading_day < payload.segment_start_trading_day
        or not payload.opportunity_id.startswith("subing-opportunity:")
        or payload.reference_price <= 0
        or payload.effective_bar_end < payload.decision_at
        or (
            payload.bound_reference_pivot is not None
            and (
                payload.bound_reference_pivot.contract != payload.contract
                or payload.bound_reference_pivot.segment_start_trading_day
                != payload.segment_start_trading_day
                or payload.bound_reference_pivot.kind is not expected_pivot_kind
            )
        )
        or len(set(payload.reason_codes)) != len(payload.reason_codes)
        or any(not value for value in payload.reason_codes)
    ):
        raise StrategyPayloadError()

    if payload.fill_basis is SubingStrategyFillBasis.NEXT_BAR_OPEN:
        if (
            payload.effective_open_at is None
            or payload.effective_open_at >= payload.effective_bar_end
            or payload.effective_bar_end <= payload.decision_at
        ):
            raise StrategyPayloadError()
    elif payload.effective_open_at is not None:
        raise StrategyPayloadError()

    if is_open:
        if (
            payload.kind not in _OPEN_KINDS
            or payload.fill_basis is not SubingStrategyFillBasis.NEXT_BAR_OPEN
            or payload.episode_id != subing_strategy_episode_id(expected_identity)
            or payload.confirmation_source is None
            or payload.reason_codes
            or payload.direction_context_source_day is None
            or payload.direction_context_target_day is None
            or payload.entry is not None
            or payload.holding_bar_count is not None
            or payload.reference_change_percent is not None
        ):
            raise StrategyPayloadError()
        return

    expected_entry_kind = (
        SubingStrategyActionKind.OPEN_LONG
        if payload.kind is SubingStrategyActionKind.CLOSE_LONG
        else SubingStrategyActionKind.OPEN_SHORT
    )
    expected_reason_codes = (
        _LONG_EXIT_REASON_CODES
        if payload.kind is SubingStrategyActionKind.CLOSE_LONG
        else _SHORT_EXIT_REASON_CODES
    )
    canonical_reason_codes = tuple(
        reason for reason in expected_reason_codes if reason in payload.reason_codes
    )
    if (
        payload.kind not in _CLOSE_KINDS
        or payload.confirmation_source is not None
        or not payload.reason_codes
        or payload.direction_context_source_day is not None
        or payload.direction_context_target_day is not None
        or payload.entry is None
        or _identity_digest(payload.entry.action_id, "subing-action")
        != _identity_digest(payload.episode_id, "subing-episode")
        or payload.entry.kind is not expected_entry_kind
        or payload.entry.effective_bar_end > payload.decision_at
        or payload.holding_bar_count is None
        or payload.reference_change_percent is None
        or payload.reason_codes != canonical_reason_codes
    ):
        raise StrategyPayloadError()


def _identity_digest(value: str, prefix: str) -> str:
    expected_prefix = f"{prefix}:"
    if not value.startswith(expected_prefix):
        raise StrategyPayloadError()
    digest = value[len(expected_prefix) :]
    if _IDENTITY_DIGEST_PATTERN.fullmatch(digest) is None:
        raise StrategyPayloadError()
    return digest


def _parse_entry(payload: object) -> SubingStrategyEntryPayload | None:
    if payload is None:
        return None
    raw = _exact_dict(payload, _ENTRY_KEYS)
    kind = SubingStrategyActionKind(_exact_str(raw["kind"]))
    if kind not in _OPEN_KINDS:
        raise StrategyPayloadError()
    return SubingStrategyEntryPayload(
        action_id=_exact_str(raw["action_id"]),
        kind=kind,
        effective_bar_end=_datetime(raw["effective_bar_end"]),
        reference_price=_positive_decimal(raw["reference_price"]),
        confirmation_source=ConfirmationSource(_exact_str(raw["confirmation_source"])),
    )


def _parse_pivot(payload: object) -> ConfirmedPivot | None:
    if payload is None:
        return None
    raw = _exact_dict(payload, _PIVOT_KEYS)
    pivot = ConfirmedPivot(
        pivot_id=_exact_str(raw["pivot_id"]),
        kind=PivotKind(_exact_str(raw["kind"])),
        source_timeframe=BarFrequency(_exact_str(raw["source_timeframe"])),
        pivot_time=_datetime(raw["pivot_time"]),
        confirmed_at=_datetime(raw["confirmed_at"]),
        price=_decimal(raw["price"]),
        contract=_exact_str(raw["contract"]),
        segment_start_trading_day=_date(raw["segment_start_trading_day"]),
    )
    if _pivot_json(pivot) != raw:
        raise StrategyPayloadError()
    return pivot


def _pivot_json(pivot: ConfirmedPivot | None) -> dict[str, object] | None:
    if pivot is None:
        return None
    return {
        "pivot_id": pivot.pivot_id,
        "kind": pivot.kind.value,
        "source_timeframe": pivot.source_timeframe.value,
        "pivot_time": _datetime_text(pivot.pivot_time),
        "confirmed_at": _datetime_text(pivot.confirmed_at),
        "price": _decimal_text(pivot.price),
        "contract": pivot.contract,
        "segment_start_trading_day": pivot.segment_start_trading_day.isoformat(),
    }


def _exact_dict(payload: object, keys: frozenset[str]) -> dict[str, Any]:
    if type(payload) is not dict or frozenset(payload) != keys:
        raise StrategyPayloadError()
    return payload


def _exact_str(value: object) -> str:
    if type(value) is not str or not value:
        raise StrategyPayloadError()
    return value


def _exact_int(value: object) -> int:
    if type(value) is not int:
        raise StrategyPayloadError()
    return value


def _optional_positive_int(value: object) -> int | None:
    if value is None:
        return None
    result = _exact_int(value)
    if result < 1:
        raise StrategyPayloadError()
    return result


def _string_tuple(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise StrategyPayloadError()
    return tuple(_exact_str(item) for item in value)


def _date(value: object) -> date:
    text = _exact_str(value)
    result = date.fromisoformat(text)
    if text != result.isoformat():
        raise StrategyPayloadError()
    return result


def _optional_date(value: object) -> date | None:
    return None if value is None else _date(value)


def _datetime(value: object) -> datetime:
    text = _exact_str(value)
    result = datetime.fromisoformat(text)
    offset = result.utcoffset()
    if (
        result.tzinfo is None
        or offset is None
        or offset.total_seconds() != 0
        or text != result.astimezone(UTC).isoformat()
    ):
        raise StrategyPayloadError()
    return result.astimezone(UTC)


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else _datetime(value)


def _datetime_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise StrategyPayloadError()
    return value.astimezone(UTC).isoformat()


def _decimal(value: object) -> Decimal:
    text = _exact_str(value)
    result = Decimal(text)
    if not result.is_finite() or text != _decimal_text(result):
        raise StrategyPayloadError()
    return result


def _positive_decimal(value: object) -> Decimal:
    result = _decimal(value)
    if result <= 0:
        raise StrategyPayloadError()
    return result


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else _decimal(value)


def _decimal_text(value: Decimal) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise StrategyPayloadError()
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"-0", ""}:
        return "0"
    return text


def _required_confirmation(
    value: ConfirmationSource | None,
) -> ConfirmationSource:
    if value is None:
        raise StrategyPayloadError()
    return value
