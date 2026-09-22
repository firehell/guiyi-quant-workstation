"""Strict, deterministic planning contracts for historical reference replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from time import monotonic
from typing import Callable, Literal, cast

from guiyi_quant.reference_trading import RecordingMode, StreamIdentity

from app.reference_trading.inputs import HistoricalInputReader


Operation = Literal["build", "advance", "rebuild"]
_CAPABILITIES = {
    "newow-trend": frozenset({"1d", "1w", "60m"}),
    "newow-oscillation": frozenset({"1d", "1w", "60m"}),
    "newow-main-rise": frozenset({"1d", "1w", "60m"}),
    "subing-reference": frozenset({"15m", "30m", "60m", "1d"}),
    "newow_trend": frozenset({"1d", "1w", "60m"}),
    "newow_oscillation": frozenset({"1d", "1w", "60m"}),
    "newow_main_rise": frozenset({"1d", "1w", "60m"}),
    "subing_reference": frozenset({"15m", "30m", "60m", "1d"}),
}


def _canonical_identity(identity: StreamIdentity) -> bool:
    normalized = identity.strategy_code.replace("-", "_")
    if normalized == "subing_reference":
        from guiyi_quant.subing_reference import (
            FORMULA_VERSIONS,
            REFERENCE_MODEL_VERSION,
            REFERENCE_MODEL_VERSION_V2,
        )

        expected_reference = (
            REFERENCE_MODEL_VERSION_V2
            if identity.frequency == "1d"
            else REFERENCE_MODEL_VERSION
        )
        return (
            identity.product == identity.product.upper()
            and identity.formula_versions
            == (FORMULA_VERSIONS.get(identity.frequency),)
            and identity.profile_id == f"subing_reference_{identity.frequency}_v1"
            and identity.reference_model_version == expected_reference
            and identity.futures_adaptation_version == "subing_actual_dominant_v1"
            and identity.observation_policy_version is None
        )
    if normalized.startswith("newow_"):
        from guiyi_quant.newow.product_adapters import build_product_identity
        from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
        from guiyi_quant.newow.product_identity import (
            REFERENCE_MODEL_VERSION,
            futures_adaptation_version,
        )

        try:
            strategy = ProductStrategy(normalized.removeprefix("newow_"))
            frequency = ProductFrequency(identity.frequency)
            expected = build_product_identity(identity.product, strategy, frequency)
        except ValueError:
            return False
        return (
            identity.formula_versions == expected.formula_versions
            and identity.profile_id == expected.profile_id
            and identity.reference_model_version == REFERENCE_MODEL_VERSION
            and identity.futures_adaptation_version
            == futures_adaptation_version(frequency.value)
            and identity.observation_policy_version is None
        )
    return False


def _positive(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _wire(value: object) -> object:
    if value is None or type(value) in (bool, int, str):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, StreamIdentity):
        return {
            "strategy_code": value.strategy_code,
            "formula_versions": list(value.formula_versions),
            "profile_id": value.profile_id,
            "reference_model_version": value.reference_model_version,
            "futures_adaptation_version": value.futures_adaptation_version,
            "product": value.product,
            "frequency": value.frequency,
            "series_kind": value.series_kind,
            "recording_mode": value.recording_mode.value,
            "observation_policy_version": value.observation_policy_version,
        }
    if isinstance(value, tuple | list):
        return [_wire(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("canonical mapping keys must be strings")
        return {key: _wire(value[key]) for key in sorted(value)}
    if hasattr(value, "__dataclass_fields__"):
        return {
            name: _wire(getattr(value, name))
            for name in value.__dataclass_fields__
            if name != "plan_hash"
        }
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        _wire(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )
    return sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class WorkBudget:
    max_streams: int
    max_input_bars: int
    max_elapsed_seconds: int
    max_input_bytes: int

    def __post_init__(self) -> None:
        for name in (
            "max_streams", "max_input_bars", "max_elapsed_seconds", "max_input_bytes",
        ):
            _positive(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class HistoricalStreamRequest:
    identity: StreamIdentity
    since: date
    through: date
    as_of: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.identity, StreamIdentity):
            raise TypeError("identity must be StreamIdentity")
        if type(self.since) is not date or type(self.through) is not date:
            raise ValueError("since and through must be dates")
        if self.since > self.through:
            raise ValueError("since must not exceed through")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")


@dataclass(frozen=True, slots=True)
class HistoricalReferenceRequest:
    operation: Operation
    streams: tuple[HistoricalStreamRequest, ...]
    budget: WorkBudget
    batch_size: int = 256

    def __post_init__(self) -> None:
        if self.operation not in {"build", "advance", "rebuild"}:
            raise ValueError("REFERENCE_OPERATION_INVALID")
        object.__setattr__(self, "streams", tuple(self.streams))
        if not self.streams:
            raise ValueError("streams must not be empty")
        ids = [item.identity.stream_id for item in self.streams]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate streams are not allowed")
        if not isinstance(self.budget, WorkBudget):
            raise TypeError("budget must be WorkBudget")
        _positive(self.batch_size, "batch_size")
        if self.batch_size > 256:
            raise ValueError("batch_size exceeds 256")


@dataclass(frozen=True, slots=True)
class HistoricalStreamPlan:
    request: HistoricalStreamRequest
    storage_start: date
    target_completed_through: datetime
    input_count: int
    input_bytes: int
    input_manifest: dict[str, object]
    input_manifest_sha256: str
    dependency_digest: str
    source_token: str

    def __post_init__(self) -> None:
        if not isinstance(self.request, HistoricalStreamRequest):
            raise ValueError("REFERENCE_PLAN_INVALID")
        if type(self.storage_start) is not date:
            raise ValueError("REFERENCE_PLAN_INVALID")
        if (
            not isinstance(self.target_completed_through, datetime)
            or self.target_completed_through.tzinfo is None
            or self.target_completed_through.utcoffset() is None
            or self.target_completed_through > self.request.as_of
        ):
            raise ValueError("REFERENCE_PLAN_INVALID")
        if type(self.input_count) is not int or self.input_count <= 0:
            raise ValueError("REFERENCE_PLAN_INVALID")
        if type(self.input_bytes) is not int or self.input_bytes < 0:
            raise ValueError("REFERENCE_PLAN_INVALID")
        if not isinstance(self.input_manifest, dict) or not self.input_manifest:
            raise ValueError("REFERENCE_PLAN_INVALID")
        digest = canonical_sha256(self.input_manifest)
        if self.input_manifest_sha256 != digest or self.dependency_digest != digest:
            raise ValueError("REFERENCE_PLAN_INVALID")
        if not isinstance(self.source_token, str) or not self.source_token:
            raise ValueError("REFERENCE_PLAN_INVALID")


@dataclass(frozen=True, slots=True)
class HistoricalReferencePlan:
    schema_version: str
    operation: Operation
    streams: tuple[HistoricalStreamPlan, ...]
    budget: WorkBudget
    batch_size: int
    plan_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != "historical_reference_plan_v1":
            raise ValueError("REFERENCE_PLAN_INVALID")
        if self.operation not in {"build", "advance", "rebuild"}:
            raise ValueError("REFERENCE_PLAN_INVALID")
        object.__setattr__(self, "streams", tuple(self.streams))
        if not self.streams or not all(
            isinstance(item, HistoricalStreamPlan) for item in self.streams
        ):
            raise ValueError("REFERENCE_PLAN_INVALID")
        if len({item.request.identity.stream_id for item in self.streams}) != len(self.streams):
            raise ValueError("REFERENCE_PLAN_INVALID")
        if not isinstance(self.budget, WorkBudget):
            raise ValueError("REFERENCE_PLAN_INVALID")
        _positive(self.batch_size, "batch_size")
        if self.batch_size > 256 or len(self.streams) > self.budget.max_streams:
            raise ValueError("REFERENCE_PLAN_INVALID")
        if (
            sum(item.input_count for item in self.streams) > self.budget.max_input_bars
            or sum(item.input_bytes for item in self.streams) > self.budget.max_input_bytes
        ):
            raise ValueError("REFERENCE_PLAN_INVALID")
        if self.plan_hash and (
            len(self.plan_hash) != 64
            or any(char not in "0123456789abcdef" for char in self.plan_hash)
            or canonical_sha256(self) != self.plan_hash
        ):
            raise ValueError("REFERENCE_PLAN_HASH_CONFLICT")


class HistoricalReferencePlanner:
    def __init__(
        self,
        input_reader: HistoricalInputReader,
        *,
        repository: object | None = None,
        now: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        self._reader = input_reader
        self._repository = repository
        self._now = now or (lambda: datetime.now().astimezone())
        self._clock = monotonic_clock

    def plan(self, request: HistoricalReferenceRequest) -> HistoricalReferencePlan:
        if not isinstance(request, HistoricalReferenceRequest):
            raise TypeError("request must be HistoricalReferenceRequest")
        if len(request.streams) > request.budget.max_streams:
            raise ValueError("REFERENCE_BUDGET_EXCEEDED")
        planned: list[HistoricalStreamPlan] = []
        total_bars = 0
        total_bytes = 0
        now = self._now()
        deadline = self._clock() + request.budget.max_elapsed_seconds
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("planner clock must be timezone-aware")
        for stream_request in request.streams:
            if self._clock() >= deadline:
                raise ValueError("REFERENCE_BUDGET_EXCEEDED")
            identity = stream_request.identity
            if stream_request.as_of > now:
                raise ValueError("REFERENCE_AS_OF_IN_FUTURE")
            if (
                identity.recording_mode is not RecordingMode.HISTORICAL_REPLAY
                or identity.series_kind != "actual_dominant"
                or identity.frequency not in _CAPABILITIES.get(identity.strategy_code, ())
            ):
                raise ValueError("REFERENCE_CAPABILITY_UNSUPPORTED")
            if not _canonical_identity(identity):
                raise ValueError("REFERENCE_IDENTITY_VERSION_UNSUPPORTED")
            estimator = getattr(self._reader, "estimate_stream", None)
            if callable(estimator):
                estimated_bars, estimated_bytes = estimator(stream_request)
                if (
                    total_bars + estimated_bars > request.budget.max_input_bars
                    or total_bytes + estimated_bytes > request.budget.max_input_bytes
                ):
                    raise ValueError("REFERENCE_BUDGET_EXCEEDED")
            snapshot = self._reader.plan_stream(stream_request)
            if self._clock() >= deadline:
                raise ValueError("REFERENCE_BUDGET_EXCEEDED")
            if snapshot.stream != identity:
                raise ValueError("REFERENCE_INPUT_IDENTITY_CONFLICT")
            if not snapshot.bars or snapshot.completed_through is None:
                raise ValueError("REFERENCE_INPUT_INCOMPLETE")
            if snapshot.completed_through > stream_request.as_of:
                raise ValueError("REFERENCE_INPUT_NOT_COMPLETED")
            total_bars += len(snapshot.bars)
            total_bytes += snapshot.input_bytes
            if (
                total_bars > request.budget.max_input_bars
                or total_bytes > request.budget.max_input_bytes
            ):
                raise ValueError("REFERENCE_BUDGET_EXCEEDED")
            digest = canonical_sha256(snapshot.dependency_manifest)
            planned.append(HistoricalStreamPlan(
                request=stream_request,
                storage_start=snapshot.storage_start,
                target_completed_through=snapshot.completed_through,
                input_count=len(snapshot.bars),
                input_bytes=snapshot.input_bytes,
                input_manifest=snapshot.dependency_manifest,
                input_manifest_sha256=digest,
                dependency_digest=digest,
                source_token=snapshot.source_token,
            ))
        draft = HistoricalReferencePlan(
            "historical_reference_plan_v1", request.operation, tuple(planned),
            request.budget, request.batch_size, "",
        )
        return HistoricalReferencePlan(
            draft.schema_version, draft.operation, draft.streams, draft.budget,
            draft.batch_size, canonical_sha256(draft),
        )


def request_from_dict(value: object) -> HistoricalReferenceRequest:
    if not isinstance(value, dict) or set(value) != {
        "operation", "streams", "budget", "batch_size",
    }:
        raise ValueError("REFERENCE_REQUEST_INVALID")
    raw_streams = value["streams"]
    raw_budget = value["budget"]
    if not isinstance(raw_streams, list) or not isinstance(raw_budget, dict):
        raise ValueError("REFERENCE_REQUEST_INVALID")
    if set(raw_budget) != {
        "max_streams", "max_input_bars", "max_elapsed_seconds", "max_input_bytes",
    }:
        raise ValueError("REFERENCE_REQUEST_INVALID")
    streams: list[HistoricalStreamRequest] = []
    identity_fields = {
        "strategy_code", "formula_versions", "profile_id", "reference_model_version",
        "futures_adaptation_version", "product", "frequency", "series_kind",
        "recording_mode", "observation_policy_version",
    }
    for raw in raw_streams:
        if not isinstance(raw, dict) or set(raw) != {"identity", "since", "through", "as_of"}:
            raise ValueError("REFERENCE_REQUEST_INVALID")
        identity = raw["identity"]
        if not isinstance(identity, dict) or set(identity) != identity_fields:
            raise ValueError("REFERENCE_REQUEST_INVALID")
        formulas = identity["formula_versions"]
        if not isinstance(formulas, list) or not all(isinstance(item, str) for item in formulas):
            raise ValueError("REFERENCE_REQUEST_INVALID")
        required_text = (
            "strategy_code", "profile_id", "reference_model_version",
            "futures_adaptation_version", "product", "frequency", "series_kind",
            "recording_mode",
        )
        if (
            any(not isinstance(identity[name], str) for name in required_text)
            or identity["observation_policy_version"] is not None
            and not isinstance(identity["observation_policy_version"], str)
            or not all(isinstance(raw[name], str) for name in ("since", "through", "as_of"))
        ):
            raise ValueError("REFERENCE_REQUEST_INVALID")
        try:
            streams.append(HistoricalStreamRequest(
                StreamIdentity(
                    strategy_code=identity["strategy_code"],
                    formula_versions=tuple(formulas),
                    profile_id=identity["profile_id"],
                    reference_model_version=identity["reference_model_version"],
                    futures_adaptation_version=identity["futures_adaptation_version"],
                    product=identity["product"],
                    frequency=identity["frequency"],
                    series_kind=identity["series_kind"],
                    recording_mode=identity["recording_mode"],
                    observation_policy_version=identity["observation_policy_version"],
                ),
                date.fromisoformat(raw["since"]),
                date.fromisoformat(raw["through"]),
                datetime.fromisoformat(raw["as_of"].replace("Z", "+00:00")),
            ))
        except (TypeError, ValueError) as error:
            raise ValueError("REFERENCE_REQUEST_INVALID") from error
    try:
        return HistoricalReferenceRequest(
            value["operation"],
            tuple(streams),
            WorkBudget(**raw_budget),
            value["batch_size"],
        )
    except (TypeError, ValueError) as error:
        raise ValueError("REFERENCE_REQUEST_INVALID") from error


def plan_to_dict(plan: HistoricalReferencePlan) -> dict[str, object]:
    payload = _wire(plan)
    if not isinstance(payload, dict):
        raise TypeError("plan is invalid")
    payload["plan_hash"] = plan.plan_hash
    return payload


def plan_from_dict(value: object) -> HistoricalReferencePlan:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "operation", "streams", "budget", "batch_size", "plan_hash",
    }:
        raise ValueError("REFERENCE_PLAN_INVALID")
    raw_streams = value["streams"]
    if not isinstance(raw_streams, list):
        raise ValueError("REFERENCE_PLAN_INVALID")
    streams: list[HistoricalStreamPlan] = []
    for raw in raw_streams:
        if not isinstance(raw, dict) or set(raw) != {
            "request", "storage_start", "target_completed_through", "input_count",
            "input_bytes", "input_manifest", "input_manifest_sha256",
            "dependency_digest", "source_token",
        }:
            raise ValueError("REFERENCE_PLAN_INVALID")
        request_payload = {
            "operation": value["operation"],
            "streams": [raw["request"]],
            "budget": value["budget"],
            "batch_size": value["batch_size"],
        }
        request = request_from_dict(request_payload).streams[0]
        manifest = raw["input_manifest"]
        if not isinstance(manifest, dict):
            raise ValueError("REFERENCE_PLAN_INVALID")
        if (
            not all(isinstance(raw[name], str) for name in (
                "storage_start", "target_completed_through", "input_manifest_sha256",
                "dependency_digest", "source_token",
            ))
            or type(raw["input_count"]) is not int
            or type(raw["input_bytes"]) is not int
        ):
            raise ValueError("REFERENCE_PLAN_INVALID")
        try:
            streams.append(HistoricalStreamPlan(
                request,
                date.fromisoformat(raw["storage_start"]),
                datetime.fromisoformat(raw["target_completed_through"].replace("Z", "+00:00")),
                raw["input_count"],
                raw["input_bytes"],
                manifest,
                raw["input_manifest_sha256"],
                raw["dependency_digest"],
                raw["source_token"],
            ))
        except (TypeError, ValueError) as error:
            raise ValueError("REFERENCE_PLAN_INVALID") from error
    raw_budget = value["budget"]
    if not isinstance(raw_budget, dict):
        raise ValueError("REFERENCE_PLAN_INVALID")
    if (
        not isinstance(value["schema_version"], str)
        or not isinstance(value["operation"], str)
        or not isinstance(value["plan_hash"], str)
        or type(value["batch_size"]) is not int
    ):
        raise ValueError("REFERENCE_PLAN_INVALID")
    try:
        plan = HistoricalReferencePlan(
            value["schema_version"],
            cast(Operation, value["operation"]),
            tuple(streams),
            WorkBudget(**raw_budget),
            value["batch_size"],
            value["plan_hash"],
        )
    except (TypeError, ValueError) as error:
        if str(error) == "REFERENCE_PLAN_HASH_CONFLICT":
            raise
        raise ValueError("REFERENCE_PLAN_INVALID") from error
    if canonical_sha256(plan) != plan.plan_hash:
        raise ValueError("REFERENCE_PLAN_HASH_CONFLICT")
    return plan
