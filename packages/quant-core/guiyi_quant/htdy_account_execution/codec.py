"""Version-bound local serialization; hashes detect damage, not privileged forgery."""

from dataclasses import fields, is_dataclass, replace
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from . import model as m


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
    return sha256(json_text(encode(value)).encode()).hexdigest()


def decode(value):
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
            m.Fill,
            m.NativeFill,
            m.CorrelatedNativeFillV1,
            m.Signal,
            m.Owner,
            m.RecoveryInput,
        )
    }
    from ..htdy_execution import OrderReport

    classes["OrderReport"] = OrderReport
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
