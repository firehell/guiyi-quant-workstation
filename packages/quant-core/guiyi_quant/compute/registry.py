"""Static compute registry and one dependency traversal per validated prefix."""

from collections.abc import Callable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import json
from math import isfinite
from types import MappingProxyType

import numpy as np
from numpy.typing import NDArray

from .contracts import (
    EMPTY_DEPENDENCY_HASH,
    FREQUENCIES,
    BarSeries,
    CompletedBar,
    FeatureIdentity,
    FeatureMarker,
    FeaturePoint,
    FeatureResult,
    InputField,
    ParameterValue,
    Status,
    hash_parameters,
)


@dataclass(frozen=True, slots=True)
class Parameter:
    default: ParameterValue | None
    minimum: float
    maximum: float
    integral: bool = True

    def validate(self, value: ParameterValue) -> None:
        if (
            type(value) not in (int, float)
            or (self.integral and type(value) is not int)
            or not self.minimum <= value <= self.maximum
        ):
            raise ValueError("INVALID_FEATURE_PARAMETER")


@dataclass(frozen=True, slots=True)
class FeatureRequest:
    feature_id: str
    parameters: Mapping[str, ParameterValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True, slots=True)
class CalculationInput:
    bars: tuple[CompletedBar, ...]
    available_at: tuple[datetime, ...]
    columns: Mapping[str, NDArray[np.float64]]
    quality_valid: NDArray[np.bool_]
    dependencies: tuple[FeatureResult, ...]


Calculation = Callable[
    [CalculationInput, Mapping[str, ParameterValue]],
    tuple[tuple[FeaturePoint, ...], tuple[FeatureMarker, ...]],
]


@dataclass(frozen=True, slots=True)
class IndicatorDefinition:
    feature_id: str
    category: str
    formula_version: str
    backend_version: str
    input_fields: tuple[InputField, ...]
    parameters: Mapping[str, Parameter]
    outputs: tuple[str, ...]
    calculate: Calculation
    lookback: Callable[[Mapping[str, ParameterValue]], int]
    dependencies: tuple[FeatureRequest, ...] = ()
    optional_dependencies: tuple[tuple[str, FeatureRequest], ...] = ()
    supported_frequencies: frozenset[str] = FREQUENCIES
    modes: frozenset[str] = frozenset(("batch",))
    allowed_uses: frozenset[str] = frozenset(("web", "research"))
    repainting: bool = False
    output_schema_version: str = "aligned_points_v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))

    def resolve(self, request: FeatureRequest) -> dict[str, ParameterValue]:
        if request.parameters.keys() - self.parameters.keys():
            raise ValueError("UNKNOWN_FEATURE_PARAMETER")
        resolved: dict[str, ParameterValue] = {}
        for name, parameter in self.parameters.items():
            value = request.parameters.get(name, parameter.default)
            if value is None:
                raise ValueError(f"FEATURE_PARAMETER_REQUIRED: {name}")
            parameter.validate(value)
            resolved[name] = value
        return resolved


class ComputeRegistry:
    def __init__(self, definitions: Iterable[IndicatorDefinition]) -> None:
        indexed: dict[str, IndicatorDefinition] = {}
        for definition in definitions:
            if definition.feature_id in indexed:
                raise ValueError("DUPLICATE_FEATURE_ID")
            indexed[definition.feature_id] = definition
        checked: set[str] = set()

        def check(feature_id: str, trail: frozenset[str]) -> None:
            if feature_id in checked:
                return
            if feature_id in trail:
                raise ValueError("CYCLIC_FEATURE_DEPENDENCY")
            definition = indexed[feature_id]
            for parameter, _ in definition.optional_dependencies:
                if parameter not in definition.parameters:
                    raise ValueError("UNKNOWN_DEPENDENCY_PARAMETER")
            dependencies = (
                *definition.dependencies,
                *(dependency for _, dependency in definition.optional_dependencies),
            )
            for dependency in dependencies:
                if dependency.feature_id not in indexed:
                    raise ValueError("UNKNOWN_FEATURE_DEPENDENCY")
                indexed[dependency.feature_id].resolve(dependency)
                check(dependency.feature_id, trail | {feature_id})
            checked.add(feature_id)

        for feature_id in indexed:
            check(feature_id, frozenset())
        self.definitions: Mapping[str, IndicatorDefinition] = MappingProxyType(indexed)

    def definition(self, feature_id: str) -> IndicatorDefinition:
        try:
            return self.definitions[feature_id]
        except KeyError:
            raise ValueError(f"UNSUPPORTED_FEATURE: {feature_id}") from None

    def result_identity(
        self, series: BarSeries, request: FeatureRequest, as_of: datetime
    ) -> FeatureIdentity:
        definition = self.definition(request.feature_id)
        count = series.available_count(as_of)
        return self._identity(series, definition, definition.resolve(request), as_of, count)

    def _identity(self, series, definition, parameters, as_of, count) -> FeatureIdentity:
        return self._make_identity(
            series.identity, definition, parameters, as_of,
            series.bars[0].bar_end if count else None,
            series.bars[count - 1].bar_end if count else None,
            count, series.prefix_digest(count),
        )

    @staticmethod
    def _required(definition, parameters):
        return (
            *definition.dependencies,
            *(dependency for parameter, dependency in definition.optional_dependencies
              if parameters[parameter]),
        )

    def _fingerprint(self, request: FeatureRequest):
        definition = self.definition(request.feature_id)
        parameters = definition.resolve(request)
        return (
            definition.feature_id, definition.formula_version, definition.backend_version,
            definition.output_schema_version, hash_parameters(parameters),
            tuple(self._fingerprint(dep) for dep in self._required(definition, parameters)),
        )

    def request_identity(
        self, source, request: FeatureRequest, *, as_of: datetime,
        first_bar_end: datetime | None, last_bar_end: datetime | None,
        bar_count: int, input_digest: str,
    ) -> FeatureIdentity:
        definition = self.definition(request.feature_id)
        parameters = definition.resolve(request)
        return self._make_identity(
            source, definition, parameters, as_of, first_bar_end, last_bar_end, bar_count, input_digest,
        )

    def _make_identity(self, source, definition, parameters, as_of, first, last, count, input_digest):
        dependencies = tuple(self._fingerprint(dep) for dep in self._required(definition, parameters))
        signature = (
            sha256(json.dumps(dependencies, separators=(",", ":")).encode()).hexdigest()
            if dependencies else EMPTY_DEPENDENCY_HASH
        )
        return FeatureIdentity(
            source, definition.feature_id, definition.formula_version, hash_parameters(parameters),
            definition.backend_version, as_of, first, last, count, input_digest, signature,
        )

    def _resolve_request(self, request: FeatureRequest, *, frequency: str, use: str, mode: str):
        definition = self.definition(request.feature_id)
        if (
            use not in definition.allowed_uses or mode not in definition.modes
            or (mode == "live" and use != "simulation")
            or frequency not in definition.supported_frequencies
        ):
            raise ValueError(f"FEATURE_USE_NOT_ALLOWED: {definition.feature_id}")
        parameters = definition.resolve(request)
        dependencies = self._required(definition, parameters)
        for dependency in dependencies:
            self._resolve_request(dependency, frequency=frequency, use=use, mode=mode)
        return definition, parameters, dependencies

    def validate_request(
        self, request: FeatureRequest, *, frequency: str, use: str, mode: str,
    ) -> IndicatorDefinition:
        definition, _, _ = self._resolve_request(request, frequency=frequency, use=use, mode=mode)
        return definition

    def calculate(
        self, series: BarSeries, requests: Iterable[FeatureRequest], *, as_of: datetime, use: str,
        mode: str = "batch", result_cache: MutableMapping[FeatureIdentity, FeatureResult] | None = None,
    ) -> tuple[FeatureResult, ...]:
        count = series.available_count(as_of)
        bars = series.bars[:count]
        available_at = series.point_availability(count)
        columns: dict[str, NDArray[np.float64]] = {}
        results: dict[FeatureIdentity, FeatureResult] = {}
        quality_valid = None

        def run(request: FeatureRequest) -> FeatureResult:
            nonlocal quality_valid
            definition, parameters, required = self._resolve_request(
                request, frequency=series.identity.frequency, use=use, mode=mode,
            )
            identity = self._identity(series, definition, parameters, as_of, count)
            if identity in results:
                return results[identity]
            cached = result_cache.get(identity) if result_cache is not None else None
            if cached is not None:
                if cached.identity != identity or cached.output_schema_version != definition.output_schema_version:
                    raise ValueError("FEATURE_CACHE_IDENTITY_MISMATCH")
                results[identity] = cached
                return cached
            dependencies = tuple(run(dependency) for dependency in required)
            for name in definition.input_fields:
                if name not in columns:
                    columns[name] = np.fromiter(
                        (getattr(bar, name) for bar in bars), dtype=np.float64, count=count,
                    )
                    columns[name].setflags(write=False)
            if quality_valid is None:
                quality_valid = np.fromiter(
                    (bar.quality_status == "VALID" for bar in bars), dtype=np.bool_, count=count,
                )
                quality_valid.setflags(write=False)
            input_data = CalculationInput(bars, available_at, MappingProxyType(columns), quality_valid, dependencies)
            points, markers = definition.calculate(input_data, parameters)
            if len(points) != count:
                raise ValueError("FEATURE_RESULT_LENGTH_MISMATCH")
            result = FeatureResult(identity, parameters, points, markers, definition.output_schema_version)
            results[identity] = result
            if result_cache is not None:
                result_cache[identity] = result
            return result

        return tuple(run(request) for request in requests)


def input_problem(
    bar: CompletedBar, names: tuple[InputField, ...],
) -> tuple[Status, str] | None:
    if bar.quality_status == "INVALID":
        return Status.INVALID, "INPUT_QUALITY_INVALID"
    if bar.quality_status == "MISSING" or any(getattr(bar, name) is None for name in names):
        return Status.UNKNOWN, "INPUT_MISSING"
    if any(not isfinite(getattr(bar, name)) for name in names):
        return Status.INVALID, "INPUT_NONFINITE"
    if "volume" in names and bar.volume is not None and bar.volume < 0:
        return Status.INVALID, "VOLUME_NEGATIVE"
    if "high" in names and "low" in names:
        low, high, close = bar.low, bar.high, bar.close
        if low is not None and high is not None and (
            high < low or ("close" in names and close is not None and not low <= close <= high)
        ):
            return Status.INVALID, "PRICE_RANGE_INVALID"
    return None


def first_invalid(data: CalculationInput, fields: tuple[InputField, ...]) -> int:
    # The verified contiguous prefix is the common case. Inspect a bad row only for diagnostics.
    valid = data.quality_valid.copy()
    for name in fields:
        valid &= np.isfinite(data.columns[name])
    if "volume" in fields:
        valid &= data.columns["volume"] >= 0
    if "high" in fields and "low" in fields:
        high, low = data.columns["high"], data.columns["low"]
        valid &= low <= high
        if "close" in fields:
            close = data.columns["close"]
            valid &= (low <= close) & (close <= high)
    return int(valid.argmin()) if valid.size and not valid.all() else len(data.bars)
