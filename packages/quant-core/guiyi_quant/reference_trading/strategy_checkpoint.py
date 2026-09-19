"""Strict, versioned JSON checkpoints for bounded strategy adapter state."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from hashlib import sha256
import json
from math import isfinite
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from ..indicators.models import EmaState, MacdState
from ..indicators.subing_ths import SubingThs15mState
from ..newow.escape_d123 import EscapeState
from ..newow.magic11 import Magic11State
from ..newow.main_rise import MainRiseState
from ..newow.models import TrendBandState
from ..newow.oscillation_channel import OscillationState
from ..newow.product_adapters import ProductReplayState, _PairingState
from ..newow.product_contracts import (
    ActionKind as NewowActionKind,
    ProductFrequency,
    ProductIdentity,
    ProductStrategy,
    StrategyAction,
    StrategyHint,
    TradeEligibility,
)
from ..newow.reference_trades import (
    NewowReferenceReplayState,
    ReferenceTrade as NewowReferenceTrade,
    ReferenceTradeStatus as NewowReferenceTradeStatus,
)
from ..newow.trend_band import TrendBandStateValue
from ..subing_reference import ReferenceTrade as SubingReferenceTrade, SubingReplayState
from .adapters import AdapterCheckpoint
from .checkpoint import checkpoint_from_json, checkpoint_to_json
from .contracts import (
    RecordingMode, ReferenceState, ReferenceTrade, Side, StreamIdentity, TradeStatus,
)

_SCHEMA = "strategy_adapter_checkpoint_v1"
_DATACLASSES = {
    f"{cls.__module__}:{cls.__qualname__}": cls
    for cls in (
        EmaState, MacdState, SubingThs15mState, SubingReplayState, SubingReferenceTrade,
        ProductReplayState, _PairingState, TrendBandStateValue, EscapeState,
        OscillationState, MainRiseState, Magic11State, ProductIdentity, StrategyAction,
        StrategyHint, NewowReferenceReplayState, NewowReferenceTrade,
        StreamIdentity, ReferenceState, ReferenceTrade,
    )
}
_DATACLASS_TAGS = {cls: tag for tag, cls in _DATACLASSES.items()}
_ENUMS = {
    f"{cls.__module__}:{cls.__qualname__}": cls
    for cls in (
        TrendBandState, NewowActionKind, ProductFrequency, ProductStrategy, TradeEligibility,
        RecordingMode, Side, TradeStatus,
        NewowReferenceTradeStatus,
    )
}
_ENUM_TAGS = {cls: tag for tag, cls in _ENUMS.items()}
_STRATEGY_STATE_TYPES = {
    "subing_replay_v1": SubingReplayState,
    "newow_product_replay_v1": ProductReplayState,
    "newow_reference_replay_v1": NewowReferenceReplayState,
}


def _pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        if key in result:
            raise ValueError("strategy checkpoint contains duplicate field")
        result[key] = value
    return result


def _constant(_value: str) -> object:
    raise ValueError("strategy checkpoint contains non-finite number")


def _exact(value: object, expected: set[str], name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"strategy checkpoint {name} is invalid")
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown:
        raise ValueError(f"strategy checkpoint {name} contains unknown fields")
    if missing:
        raise ValueError(f"strategy checkpoint {name} is missing fields")
    return value


def _validate_type(value: object, annotation: object, name: str) -> None:
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if annotation is Any:
        return
    if annotation is int:
        if type(value) is not int:
            raise ValueError(f"strategy checkpoint {name} must be an integer")
        return
    if annotation is bool:
        if type(value) is not bool:
            raise ValueError(f"strategy checkpoint {name} must be a boolean")
        return
    if annotation is float:
        if type(value) is not float or not isfinite(value):
            raise ValueError(f"strategy checkpoint {name} must be a finite float")
        return
    if annotation in (str, Decimal, datetime, date):
        if not isinstance(value, annotation):
            raise ValueError(f"strategy checkpoint {name} has invalid type")
        return
    if origin in (Union, UnionType):
        for option in arguments:
            try:
                _validate_type(value, option, name)
                return
            except ValueError:
                continue
        raise ValueError(f"strategy checkpoint {name} has invalid union type")
    if origin is Literal:
        if value not in arguments or not any(type(value) is type(option) for option in arguments):
            raise ValueError(f"strategy checkpoint {name} has invalid literal")
        return
    if origin is tuple:
        if not isinstance(value, tuple):
            raise ValueError(f"strategy checkpoint {name} must be a tuple")
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            for item in value:
                _validate_type(item, arguments[0], name)
        elif len(value) != len(arguments):
            raise ValueError(f"strategy checkpoint {name} tuple length is invalid")
        else:
            for item, item_type in zip(value, arguments, strict=True):
                _validate_type(item, item_type, name)
        return
    if origin is dict:
        if not isinstance(value, dict):
            raise ValueError(f"strategy checkpoint {name} must be a dict")
        for key, item in value.items():
            _validate_type(key, arguments[0], name)
            _validate_type(item, arguments[1], name)
        return
    if isinstance(annotation, type) and not isinstance(value, annotation):
        raise ValueError(f"strategy checkpoint {name} has invalid type")


def _wire(value: object) -> object:
    if value is None or type(value) in (bool, int, str):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("strategy checkpoint float must be finite")
        return {"$float": repr(value)}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("strategy checkpoint Decimal must be finite")
        return {"$decimal": str(value)}
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("strategy checkpoint datetime must be timezone-aware")
        return {"$datetime": value.isoformat()}
    if type(value) is date:
        return {"$date": value.isoformat()}
    if isinstance(value, Enum):
        enum_type = _ENUM_TAGS.get(type(value))
        if enum_type is None:
            raise TypeError(f"unsupported strategy checkpoint enum: {type(value).__name__}")
        return {"$enum": enum_type, "value": value.value}
    if isinstance(value, tuple):
        return {"$tuple": [_wire(item) for item in value]}
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("strategy checkpoint dict keys must be strings")
        return {"$dict": [[key, _wire(value[key])] for key in sorted(value)]}
    if is_dataclass(value) and not isinstance(value, type):
        type_name = _DATACLASS_TAGS.get(type(value))
        if type_name is None:
            raise TypeError(f"unsupported strategy checkpoint state: {type(value).__name__}")
        payload = {
            field.name: _wire(getattr(value, field.name))
            for field in fields(value)
            if field.init
        }
        return {"$type": type_name, "fields": payload}
    raise TypeError(f"unsupported strategy checkpoint value: {type(value).__name__}")


def _restore(value: object) -> object:
    if value is None or type(value) in (bool, int, str):
        return value
    if not isinstance(value, dict):
        raise ValueError("strategy checkpoint value is invalid")
    if set(value) == {"$float"}:
        raw = value["$float"]
        if not isinstance(raw, str):
            raise ValueError("strategy checkpoint float is invalid")
        result = float(raw)
        if not isfinite(result):
            raise ValueError("strategy checkpoint float must be finite")
        return result
    if set(value) == {"$decimal"}:
        raw = value["$decimal"]
        if not isinstance(raw, str):
            raise ValueError("strategy checkpoint Decimal is invalid")
        try:
            result = Decimal(raw)
        except InvalidOperation as error:
            raise ValueError("strategy checkpoint Decimal is invalid") from error
        if not result.is_finite():
            raise ValueError("strategy checkpoint Decimal must be finite")
        return result
    if set(value) == {"$datetime"}:
        raw = value["$datetime"]
        if not isinstance(raw, str):
            raise ValueError("strategy checkpoint datetime is invalid")
        try:
            result = datetime.fromisoformat(raw)
        except ValueError as error:
            raise ValueError("strategy checkpoint datetime is invalid") from error
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("strategy checkpoint datetime must be timezone-aware")
        return result
    if set(value) == {"$date"}:
        raw = value["$date"]
        if not isinstance(raw, str):
            raise ValueError("strategy checkpoint date is invalid")
        try:
            return date.fromisoformat(raw)
        except ValueError as error:
            raise ValueError("strategy checkpoint date is invalid") from error
    if set(value) == {"$enum", "value"}:
        enum_type = value["$enum"]
        if enum_type not in _ENUMS:
            raise ValueError("strategy checkpoint enum is invalid")
        try:
            return _ENUMS[enum_type](value["value"])
        except (TypeError, ValueError) as error:
            raise ValueError("strategy checkpoint enum is invalid") from error
    if set(value) == {"$tuple"}:
        items = value["$tuple"]
        if not isinstance(items, list):
            raise ValueError("strategy checkpoint tuple is invalid")
        return tuple(_restore(item) for item in items)
    if set(value) == {"$dict"}:
        items = value["$dict"]
        if not isinstance(items, list):
            raise ValueError("strategy checkpoint dict is invalid")
        result: dict[str, object] = {}
        for pair in items:
            if not isinstance(pair, list) or len(pair) != 2 or not isinstance(pair[0], str):
                raise ValueError("strategy checkpoint dict is invalid")
            if pair[0] in result:
                raise ValueError("strategy checkpoint dict contains duplicate key")
            result[pair[0]] = _restore(pair[1])
        return result
    tagged = _exact(value, {"$type", "fields"}, "typed state")
    type_name = tagged["$type"]
    cls = _DATACLASSES.get(type_name) if isinstance(type_name, str) else None
    if cls is None:
        raise ValueError("strategy checkpoint state type is invalid")
    raw_fields = tagged["fields"]
    expected = {field.name for field in fields(cls) if field.init}
    values = _exact(raw_fields, expected, f"{type_name} fields")
    restored = {name: _restore(item) for name, item in values.items()}
    hints = get_type_hints(cls)
    for name, item in restored.items():
        _validate_type(item, hints[name], f"{type_name}.{name}")
    try:
        return cls(**restored)
    except (TypeError, ValueError) as error:
        raise ValueError(f"strategy checkpoint {type_name} is invalid") from error


def _canonical(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _validate_subing_state(
    state: SubingReplayState, reference_state: ReferenceState,
) -> None:
    if state.processed_count < 0 or state.entry_index < 0:
        raise ValueError("strategy checkpoint Subing progress is invalid")
    if state.entry_index > state.processed_count:
        raise ValueError("strategy checkpoint Subing progress is invalid")
    kernel = state.kernel_state
    if any(count != state.processed_count for count in (
        kernel.macd.fast.count, kernel.macd.slow.count, kernel.ema21.count,
    )):
        raise ValueError("strategy checkpoint Subing kernel progress is inconsistent")
    current = state.current
    unified = reference_state.open_trade
    if (current is None) != (unified is None):
        raise ValueError("strategy checkpoint Subing current trade is inconsistent")
    if current is None or unified is None:
        return
    if (
        current.side != unified.side.value
        or current.physical_contract != unified.physical_contract
        or current.segment_id != unified.owner_segment_id
        or current.calculation_segment_id != unified.calculation_segment_id
        or current.entry_bar_end != unified.entry_bar_end
        or current.entry_trading_day != unified.entry_trading_day
        or current.entry_reference_price != unified.entry_reference_price
        or current.holding_bars != unified.holding_bars
        or current.mark_bar_end != unified.mark_bar_end
        or current.mark_reference_price != unified.mark_reference_price
        or current.mark_change_pct != unified.mark_return
    ):
        raise ValueError("strategy checkpoint Subing current trade is inconsistent")


def _validate_strategy_state(
    state: object, strategy_schema: str, reference_state: ReferenceState,
) -> None:
    expected_type = _STRATEGY_STATE_TYPES.get(strategy_schema)
    if expected_type is None or type(state) is not expected_type:
        raise ValueError("strategy checkpoint strategy state type is invalid")
    if isinstance(state, SubingReplayState):
        _validate_subing_state(state, reference_state)
    if isinstance(state, NewowReferenceReplayState):
        if state.stream != reference_state.stream:
            raise ValueError("strategy checkpoint Newow reference stream is inconsistent")
        owned_states = {
            (contract, segment): owned
            for contract, segment, owned in state.reference_states
        }
        if len(owned_states) != len(state.reference_states):
            raise ValueError("strategy checkpoint Newow reference owners are duplicated")
        verified_inputs = {
            (contract, segment): values
            for contract, segment, values in state.verified_lifecycle_inputs
        }
        consumed = {
            (contract, segment): count
            for contract, segment, count in state.lifecycle_consumed
        }
        verified_owners = set(state.verified_lifecycle_owners)
        if (
            len(verified_inputs) != len(state.verified_lifecycle_inputs)
            or len(consumed) != len(state.lifecycle_consumed)
            or set(verified_inputs) != verified_owners
            or set(consumed) != verified_owners
        ):
            raise ValueError("strategy checkpoint Newow lifecycle owners are inconsistent")
        for owner, values in verified_inputs.items():
            count = consumed[owner]
            if (
                not values
                or type(count) is not int
                or not 0 <= count <= len(values)
                or len({instant for instant, _digest in values}) != len(values)
                or any(
                    len(digest) != 64
                    or any(character not in "0123456789abcdef" for character in digest)
                    for _instant, digest in values
                )
            ):
                raise ValueError("strategy checkpoint Newow lifecycle progress is invalid")
        if reference_state not in owned_states.values():
            raise ValueError("strategy checkpoint Newow outer reference state is inconsistent")
        open_by_entry = {
            owned.open_trade.entry_action_id: owned.open_trade
            for owned in owned_states.values() if owned.open_trade is not None
        }
        if set(open_by_entry) != {trade.entry_signal_id for trade in state.active_trades}:
            raise ValueError("strategy checkpoint Newow active trades are inconsistent")
        active_actions = {action.signal_id: action for action in state.active_actions}
        if set(open_by_entry) != set(active_actions):
            raise ValueError("strategy checkpoint Newow active actions are inconsistent")
        public_trades = {trade.entry_signal_id: trade for trade in state.active_trades}
        for entry_id, unified in open_by_entry.items():
            public = public_trades[entry_id]
            action = active_actions[entry_id]
            if (
                public.status is not NewowReferenceTradeStatus.OPEN
                or public.physical_contract != unified.physical_contract
                or public.segment_id != unified.owner_segment_id
                or public.calculation_segment_id != unified.calculation_segment_id
                or public.entry_bar_end != unified.entry_bar_end
                or public.entry_trading_day != unified.entry_trading_day
                or public.entry_reference_price != unified.entry_reference_price
                or public.holding_bars != unified.holding_bars
                or public.mark_bar_end != unified.mark_bar_end
                or public.mark_reference_price != unified.mark_reference_price
                or public.mark_change_pct != unified.mark_return
                or action.physical_contract != unified.physical_contract
                or action.segment_id != unified.owner_segment_id
                or action.calculation_segment_id != unified.calculation_segment_id
                or action.bar_end != unified.entry_bar_end
                or action.trading_day != unified.entry_trading_day
                or action.reference_price != unified.entry_reference_price
            ):
                raise ValueError("strategy checkpoint Newow active trades are inconsistent")


def adapter_checkpoint_to_json(
    checkpoint: AdapterCheckpoint[Any], *, strategy_schema: str,
) -> str:
    if not isinstance(checkpoint, AdapterCheckpoint):
        raise TypeError("checkpoint must be AdapterCheckpoint")
    if checkpoint.stream is None or checkpoint.reference_state is None:
        raise ValueError("strategy checkpoint requires stream and reference_state")
    if not isinstance(strategy_schema, str) or not strategy_schema:
        raise ValueError("strategy_schema must be non-empty text")
    body: dict[str, object] = {
        "schema_version": _SCHEMA,
        "strategy_schema": strategy_schema,
        "stream_id": checkpoint.stream.stream_id,
        "strategy_state": _wire(checkpoint.strategy_state),
        "reference_state": json.loads(checkpoint_to_json(checkpoint.reference_state)),
        "computed_through": None if checkpoint.computed_through is None else checkpoint.computed_through.isoformat(),
        "last_fingerprint": checkpoint.last_fingerprint,
        "physical_contract": checkpoint.physical_contract,
        "owner_segment_id": checkpoint.owner_segment_id,
        "calculation_segment_id": checkpoint.calculation_segment_id,
    }
    payload = dict(body)
    payload["checksum_sha256"] = sha256(_canonical(body).encode()).hexdigest()
    return _canonical(payload)


def adapter_checkpoint_from_json(
    value: str, *, expected_stream: StreamIdentity, expected_strategy_schema: str,
) -> AdapterCheckpoint[Any]:
    try:
        payload = json.loads(
            value, object_pairs_hook=_pairs, parse_constant=_constant,
        )
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("strategy checkpoint JSON is invalid") from error
    expected_fields = {
        "schema_version", "strategy_schema", "stream_id", "strategy_state",
        "reference_state", "computed_through", "last_fingerprint", "physical_contract",
        "owner_segment_id", "calculation_segment_id", "checksum_sha256",
    }
    payload = _exact(payload, expected_fields, "envelope")
    checksum = payload.pop("checksum_sha256")
    if not isinstance(checksum, str) or checksum != sha256(_canonical(payload).encode()).hexdigest():
        raise ValueError("strategy checkpoint checksum mismatch")
    if payload["schema_version"] != _SCHEMA:
        raise ValueError("strategy checkpoint schema is invalid")
    if payload["strategy_schema"] != expected_strategy_schema:
        raise ValueError("strategy checkpoint strategy schema is invalid")
    if payload["stream_id"] != expected_stream.stream_id:
        raise ValueError("strategy checkpoint stream is invalid")
    reference_payload = payload["reference_state"]
    reference_state = checkpoint_from_json(_canonical(reference_payload))
    if reference_state.stream != expected_stream:
        raise ValueError("strategy checkpoint reference stream is invalid")
    computed_raw = payload["computed_through"]
    computed = None
    if computed_raw is not None:
        if not isinstance(computed_raw, str):
            raise ValueError("strategy checkpoint computed_through is invalid")
        try:
            computed = datetime.fromisoformat(computed_raw)
        except ValueError as error:
            raise ValueError("strategy checkpoint computed_through is invalid") from error
        if computed.tzinfo is None or computed.utcoffset() is None:
            raise ValueError("strategy checkpoint computed_through must be timezone-aware")
    for name in ("last_fingerprint", "physical_contract", "owner_segment_id", "calculation_segment_id"):
        item = payload[name]
        if item is not None and (not isinstance(item, str) or not item):
            raise ValueError(f"strategy checkpoint {name} is invalid")
    if (computed is None) != (payload["last_fingerprint"] is None):
        raise ValueError("strategy checkpoint progress is inconsistent")
    if computed is not None and any(payload[name] is None for name in (
        "physical_contract", "owner_segment_id", "calculation_segment_id",
    )):
        raise ValueError("strategy checkpoint owner progress is inconsistent")
    if reference_state.computed_through is not None:
        if computed is None or reference_state.computed_through > computed:
            raise ValueError("strategy checkpoint watermarks are inconsistent")
    strategy_state = _restore(payload["strategy_state"])
    _validate_strategy_state(strategy_state, expected_strategy_schema, reference_state)
    embedded_reference_state = getattr(strategy_state, "reference_state", None)
    if embedded_reference_state is not None and embedded_reference_state != reference_state:
        raise ValueError("strategy checkpoint embedded reference state is inconsistent")
    if reference_state.open_trade is not None and (
        payload["physical_contract"] != reference_state.open_trade.physical_contract
        or payload["owner_segment_id"] != reference_state.open_trade.owner_segment_id
        or payload["calculation_segment_id"]
        != reference_state.open_trade.calculation_segment_id
    ):
        raise ValueError("strategy checkpoint open trade owner is inconsistent")
    return AdapterCheckpoint(
        strategy_state=strategy_state,
        computed_through=computed,
        last_fingerprint=payload["last_fingerprint"],
        physical_contract=payload["physical_contract"],
        owner_segment_id=payload["owner_segment_id"],
        calculation_segment_id=payload["calculation_segment_id"],
        stream=expected_stream,
        reference_state=reference_state,
    )
