"""Strict JSON checkpoint codec for the bounded P1 reference state."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json

from .contracts import ReferenceState, ReferenceTrade, Side, StreamIdentity, TradeStatus

_SCHEMA = "reference_state_v1"


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys instead of accepting last-write-wins input."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("checkpoint JSON contains duplicate field")
        result[key] = value
    return result


def _fields(payload: object, expected: set[str], name: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError(f"checkpoint {name} is invalid")
    unknown = set(payload) - expected
    missing = expected - set(payload)
    if unknown:
        raise ValueError(f"checkpoint {name} contains unknown fields")
    if missing:
        raise ValueError(f"checkpoint {name} is missing fields")
    return payload


def _decimal(value: object) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("checkpoint Decimal must be a string")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("checkpoint Decimal is invalid") from error
    if not result.is_finite():
        raise ValueError("checkpoint Decimal must be finite")
    return result


def _instant(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("checkpoint instant must be a string")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("checkpoint instant is invalid") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("checkpoint instant must be timezone-aware")
    return result


def _day(value: object) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("checkpoint day must be a string")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("checkpoint day is invalid") from error


def _stream(payload: object) -> StreamIdentity:
    payload = _fields(payload, set(StreamIdentity.__dataclass_fields__), "stream")
    try:
        return StreamIdentity(
            strategy_code=payload["strategy_code"], formula_versions=tuple(payload["formula_versions"]),
            profile_id=payload["profile_id"], reference_model_version=payload["reference_model_version"],
            futures_adaptation_version=payload["futures_adaptation_version"], product=payload["product"],
            frequency=payload["frequency"], series_kind=payload["series_kind"],
            recording_mode=payload["recording_mode"], observation_policy_version=payload["observation_policy_version"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("checkpoint stream is invalid") from error


def _trade(payload: object, stream: StreamIdentity) -> ReferenceTrade | None:
    if payload is None:
        return None
    payload = _fields(payload, {
        "reference_trade_id", "side", "physical_contract", "owner_segment_id",
        "calculation_segment_id", "entry_action_id", "entry_bar_end", "entry_trading_day",
        "entry_reference_price", "status", "holding_bars", "mark_bar_end",
        "mark_trading_day", "mark_reference_price", "mark_return",
    }, "open_trade")
    try:
        return ReferenceTrade(
            reference_trade_id=payload["reference_trade_id"], stream=stream, side=Side(payload["side"]),
            physical_contract=payload["physical_contract"], owner_segment_id=payload["owner_segment_id"],
            calculation_segment_id=payload["calculation_segment_id"], entry_action_id=payload["entry_action_id"],
            entry_bar_end=_instant(payload["entry_bar_end"]), entry_trading_day=_day(payload["entry_trading_day"]),
            entry_reference_price=_decimal(payload["entry_reference_price"]), status=TradeStatus(payload["status"]),
            holding_bars=payload["holding_bars"], mark_bar_end=_instant(payload.get("mark_bar_end")),
            mark_trading_day=_day(payload.get("mark_trading_day")),
            mark_reference_price=None if payload.get("mark_reference_price") is None else _decimal(payload["mark_reference_price"]),
            mark_return=None if payload.get("mark_return") is None else _decimal(payload["mark_return"]),
        )
    except (KeyError, TypeError) as error:
        raise ValueError("checkpoint open_trade is invalid") from error


def _wire_stream(stream: StreamIdentity) -> dict[str, object]:
    return {name: getattr(stream, name).value if name == "recording_mode" else getattr(stream, name) for name in StreamIdentity.__dataclass_fields__}


def _wire_trade(trade: ReferenceTrade | None) -> dict[str, object] | None:
    if trade is None:
        return None
    return {
        "reference_trade_id": trade.reference_trade_id, "side": trade.side.value,
        "physical_contract": trade.physical_contract, "owner_segment_id": trade.owner_segment_id,
        "calculation_segment_id": trade.calculation_segment_id, "entry_action_id": trade.entry_action_id,
        "entry_bar_end": trade.entry_bar_end.isoformat(), "entry_trading_day": trade.entry_trading_day.isoformat(),
        "entry_reference_price": str(trade.entry_reference_price), "status": trade.status.value,
        "holding_bars": trade.holding_bars, "mark_bar_end": None if trade.mark_bar_end is None else trade.mark_bar_end.isoformat(),
        "mark_trading_day": None if trade.mark_trading_day is None else trade.mark_trading_day.isoformat(),
        "mark_reference_price": None if trade.mark_reference_price is None else str(trade.mark_reference_price),
        "mark_return": None if trade.mark_return is None else str(trade.mark_return),
    }


def checkpoint_to_json(state: ReferenceState) -> str:
    if not isinstance(state, ReferenceState):
        raise TypeError("state must be ReferenceState")
    payload = {
        "schema_version": _SCHEMA, "stream": _wire_stream(state.stream),
        "recording_start": None if state.recording_start is None else state.recording_start.isoformat(),
        "computed_through": None if state.computed_through is None else state.computed_through.isoformat(),
        "last_input_hash": state.last_input_hash,
        "last_event_key": None if state.last_event_key is None else [state.last_event_key[0].isoformat(), state.last_event_key[1], state.last_event_key[2]],
        "open_trade": _wire_trade(state.open_trade),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def checkpoint_from_json(value: str) -> ReferenceState:
    try:
        payload = json.loads(value, object_pairs_hook=_object_pairs)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("checkpoint JSON is invalid") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != _SCHEMA:
        raise ValueError("checkpoint schema is invalid")
    payload = _fields(payload, {
        "schema_version", "stream", "recording_start", "computed_through", "last_input_hash",
        "last_event_key", "open_trade",
    }, "state")
    stream = _stream(payload.get("stream"))
    key = payload.get("last_event_key")
    if key is not None and (not isinstance(key, list) or len(key) != 3 or type(key[1]) is not int or type(key[2]) is not int):
        raise ValueError("checkpoint last_event_key is invalid")
    try:
        return ReferenceState(
            stream=stream, recording_start=_instant(payload.get("recording_start")),
            computed_through=_instant(payload.get("computed_through")), open_trade=_trade(payload.get("open_trade"), stream),
            last_input_hash=payload.get("last_input_hash"),
            last_event_key=None if key is None else (_instant(key[0]), key[1], key[2]),
        )
    except TypeError as error:
        raise ValueError("checkpoint state is invalid") from error
