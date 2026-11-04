"""Version-bound local serialization; hashes detect damage, not privileged forgery."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from functools import lru_cache
from hashlib import sha256
from threading import get_ident
from types import MappingProxyType
from zoneinfo import ZoneInfo
import json
from . import model as m


_replay_digest_scope = ContextVar("account_replay_digest_scope", default=None)


def encode(value):
    if is_dataclass(value):
        return {
            "type": type(value).__name__,
            "fields": {f.name: encode(getattr(value, f.name)) for f in fields(value)},
        }
    if type(value) in (datetime, Decimal):
        return {"type": type(value).__name__, "value": str(value)}
    if type(value) is tuple:
        return [encode(v) for v in value]
    return value


def json_text(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    scope = _replay_digest_scope.get()
    if scope is not None and type(value) is m.State and scope.owner == get_ident():
        result = scope.state_digest(value)
        if result is not None:
            return result
    return sha256(json_text(encode(value)).encode()).hexdigest()


@lru_cache(maxsize=1)
def _classes():
    classes = {
        c.__name__: c
        for c in (
            m.Coverage,
            m.Readback,
            m.Instrument,
            m.Quote,
            m.Session,
            m.ExecutionInput,
            m.Tick,
            m.ManagedTickV1,
            m.ContinuousTradeTickV1,
            m.ManualBeginV1,
            m.ManualTickV1,
            m.ManualStatusV1,
            m.OrderUpdate,
            m.AbortUnsent,
            m.Disconnect,
            m.Recover,
            m.ProductRecoveryV1,
            m.Product,
            m.Order,
            m.Reservation,
            m.RiskDecision,
            m.Audit,
            m.State,
            m.Effect,
            m.Transition,
            m.AccountSnapshot,
            m.Position,
            m.TqKqFill,
            m.TqKqInstrument,
            m.TqKqExecutionInput,
            m.TqKqTick,
            m.TqKqResumeEmptyV1,
            m.Fill,
            m.NativeFill,
            m.CorrelatedNativeFillV1,
            m.StrategyCorrelatedNativeFillV1,
            m.StrategyCorrelatedNativeFillV2,
            m.Signal,
            m.Owner,
            m.RecoveryInput,
        )
    }
    from ..htdy_execution import OrderReport

    classes["OrderReport"] = OrderReport
    return MappingProxyType(classes)


def decode(value):
    classes = _classes()
    if type(value) is list:
        return tuple(decode(v) for v in value)
    if type(value) is dict:
        if value.get("type") == "datetime":
            result = datetime.fromisoformat(value["value"])
            m.time(result)
            return result
        if value.get("type") == "Decimal":
            return Decimal(value["value"])
        return classes[value["type"]](
            **{k: decode(v) for k, v in value["fields"].items()}
        )
    return value


def checkpoint(state):
    from .reducer import validate

    validate(state)
    body = {
        "policy": m.POLICY_VERSION,
        "risk": m.RISK_VERSION,
        "execution": m.EXECUTION_VERSION,
        "formula": m.FORMULA_VERSION,
        "state": encode(state),
    }
    return json_text(
        {"body": body, "sha256": sha256(json_text(body).encode()).hexdigest()}
    )


def load(payload, *, recovery_required=False):
    from .reducer import validate

    try:
        packet = json.loads(payload)
        body = packet["body"]
        if (body["policy"], body["risk"], body["execution"], body["formula"]) != (
            m.POLICY_VERSION,
            m.RISK_VERSION,
            m.EXECUTION_VERSION,
            m.FORMULA_VERSION,
        ) or sha256(json_text(body).encode()).hexdigest() != packet["sha256"]:
            raise ValueError("CHECKPOINT_IDENTITY_INVALID")
        state = decode(body["state"])
        validate(state)
        if recovery_required:
            return replace(
                state,
                phase="BLOCKED" if state.unresolved_fill_ids else "RECOVERY_REQUIRED",
                readback_valid=False,
            )
        return state
    except (KeyError, TypeError, ValueError, ArithmeticError, RecursionError):
        raise ValueError("ACCOUNT_CHECKPOINT_INVALID") from None


def restore(payload):
    return load(payload, recovery_required=True)


def _deep_immutable(value, known, visiting=None):
    """Only exact canonical model types and genuinely immutable member graphs."""
    kind = type(value)
    if kind in (str, int, bool, float, Decimal, type(None)):
        return True
    if kind is datetime:
        return type(value.tzinfo) in (timezone, ZoneInfo)
    if kind is not tuple and kind not in known:
        return False
    visiting = set() if visiting is None else visiting
    identity = id(value)
    if identity in visiting:
        return False
    visiting.add(identity)
    try:
        if kind is tuple:
            return all(_deep_immutable(item, known, visiting) for item in value)
        return (kind.__dataclass_params__.frozen
                and all(_deep_immutable(getattr(value, field.name), known, visiting)
                        for field in fields(value)))
    finally:
        visiting.remove(identity)


class _ReplayStateDigest:
    """One current fragment per State field; never a projection/replay shortcut."""
    def __init__(self, max_bytes):
        self.owner = get_ident()
        self.max_bytes = max_bytes
        self.values = {}
        self.cached_bytes = 0
        self.capitals = getcontext().capitals
        self.known = frozenset(_classes().values())
        self.names = tuple(sorted(field.name for field in fields(m.State)))
        self.keys = {name: json_text(name).encode() + b":" for name in self.names}

    def clear(self):
        self.values.clear()
        self.cached_bytes = 0

    def state_digest(self, state):
        if self.capitals != getcontext().capitals:
            self.clear()
            self.capitals = getcontext().capitals
        prepared = {}
        try:
            # Establish deep immutability before encoding anything. Otherwise use
            # the original whole-State path, including its evaluation semantics.
            for name in self.names:
                value = getattr(state, name)
                previous = self.values.get(name)
                if previous is not None and value is previous[0]:
                    prepared[name] = previous
                    continue
                append = (previous is not None and type(value) is tuple
                          and type(previous[0]) is tuple
                          and len(value) == len(previous[0]) + 1
                          and all(left is right for left, right in zip(value, previous[0]))
                          and _deep_immutable(value[-1], self.known))
                if append:
                    prepared[name] = (value, previous[1], True)
                elif _deep_immutable(value, self.known):
                    prepared[name] = (value, None)
                else:
                    self.clear()
                    return None
            encoded = {}
            total = 0
            for name in self.names:
                item = prepared[name]
                value, raw = item[:2]
                if len(item) == 3:
                    raw = raw[:-1] + (b"," if len(value) > 1 else b"") + json_text(encode(value[-1])).encode() + b"]"
                elif raw is None:
                    raw = json_text(encode(value)).encode()
                total += len(raw)
                if total > self.max_bytes:
                    self.clear()
                    return None
                encoded[name] = (value, raw)
            result = sha256()
            result.update(b'{"fields":{')
            for index, name in enumerate(self.names):
                if index:
                    result.update(b",")
                result.update(self.keys[name])
                result.update(encoded[name][1])
            result.update(b'},"type":')
            result.update(json_text(type(state).__name__).encode())
            result.update(b"}")
            self.values = encoded
            self.cached_bytes = total
            return result.hexdigest()
        except Exception:
            self.clear()
            return None


@contextmanager
def replay_digests(*, max_bytes=16 * 1024 * 1024):
    """Private, bounded canonical fragments for one synchronous full replay."""
    scope = _ReplayStateDigest(max_bytes)
    token = _replay_digest_scope.set(scope)
    try:
        yield scope
    finally:
        scope.clear()
        _replay_digest_scope.reset(token)
