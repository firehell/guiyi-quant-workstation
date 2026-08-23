"""Strict JSON registry for fixed, Git-tracked RQAlpha strategies."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path, PurePath
from typing import Any, NoReturn

from app.backtest.contracts import BacktestRunRequest, normalize_decimal
from app.backtest.errors import (
    InvalidBacktestRequestError,
    RegistryError,
    StrategyNotFoundError,
)


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_CONFIG_KEYS = frozenset(
    {
        "future_cash",
        "matching_type",
        "margin_multiplier",
        "futures_commission_multiplier",
        "slippage_model",
        "slippage",
    }
)
_DECIMAL_CONFIG_KEYS = frozenset(
    {
        "future_cash",
        "margin_multiplier",
        "futures_commission_multiplier",
        "slippage",
    }
)


class ParameterType(StrEnum):
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    ENUM = "enum"


@dataclass(frozen=True, slots=True)
class ParameterDescriptor:
    name: str
    type: ParameterType
    default: int | str | bool
    minimum: int | str | None = None
    maximum: int | str | None = None
    options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RegisteredStrategy:
    id: str
    name: str
    description: str
    enabled: bool
    entry_file: str
    strategy_file: Path
    supported_frequencies: tuple[str, ...]
    defaults: dict[str, str]
    parameters: tuple[ParameterDescriptor, ...]


@dataclass(frozen=True, slots=True)
class ValidatedBacktestRequest:
    strategy: RegisteredStrategy
    strategy_file: Path
    parameters: dict[str, int | str | bool]
    config: dict[str, str]


def _fail() -> NoReturn:
    raise RegistryError


def _strict_keys(payload: dict[str, Any], expected: set[str]) -> None:
    if set(payload) != expected:
        _fail()


def _decimal_string(value: object) -> tuple[Decimal, str]:
    if not isinstance(value, str) or not value or value != value.strip():
        _fail()
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        _fail()
    if not parsed.is_finite():
        _fail()
    return parsed, normalize_decimal(parsed)


def _parameter_value(
    descriptor: ParameterDescriptor,
    value: object,
    *,
    registry_load: bool,
) -> int | str | bool:
    def invalid() -> NoReturn:
        if registry_load:
            raise RegistryError
        raise InvalidBacktestRequestError

    if descriptor.type is ParameterType.INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            invalid()
        if descriptor.minimum is not None:
            if not isinstance(descriptor.minimum, int):
                invalid()
            if value < descriptor.minimum:
                invalid()
        if descriptor.maximum is not None:
            if not isinstance(descriptor.maximum, int):
                invalid()
            if value > descriptor.maximum:
                invalid()
        return value
    if descriptor.type is ParameterType.DECIMAL:
        if not isinstance(value, str) or not value or value != value.strip():
            invalid()
        try:
            parsed = Decimal(value)
        except InvalidOperation:
            invalid()
        if not parsed.is_finite():
            invalid()
        if descriptor.minimum is not None and not isinstance(descriptor.minimum, str):
            invalid()
        if descriptor.maximum is not None and not isinstance(descriptor.maximum, str):
            invalid()
        minimum = (
            Decimal(descriptor.minimum) if descriptor.minimum is not None else None
        )
        maximum = (
            Decimal(descriptor.maximum) if descriptor.maximum is not None else None
        )
        if minimum is not None and parsed < minimum:
            invalid()
        if maximum is not None and parsed > maximum:
            invalid()
        return normalize_decimal(parsed)
    if descriptor.type is ParameterType.BOOLEAN:
        if not isinstance(value, bool):
            invalid()
        return value
    if not isinstance(value, str) or value not in descriptor.options:
        invalid()
    return value


def _parameter_descriptor(payload: object) -> ParameterDescriptor:
    if not isinstance(payload, dict):
        _fail()
    common = {"name", "type", "default"}
    name = payload.get("name")
    raw_type = payload.get("type")
    if not isinstance(name, str) or _IDENTIFIER.fullmatch(name) is None:
        _fail()
    if not isinstance(raw_type, str):
        _fail()
    try:
        parameter_type = ParameterType(raw_type)
    except (TypeError, ValueError):
        _fail()
    if parameter_type is ParameterType.INTEGER:
        _strict_keys(
            payload, common | {key for key in ("min", "max") if key in payload}
        )
        minimum = payload.get("min")
        maximum = payload.get("max")
        if (
            (
                minimum is not None
                and (isinstance(minimum, bool) or not isinstance(minimum, int))
            )
            or (
                maximum is not None
                and (isinstance(maximum, bool) or not isinstance(maximum, int))
            )
            or (minimum is not None and maximum is not None and minimum > maximum)
        ):
            _fail()
        descriptor = ParameterDescriptor(
            name=name,
            type=parameter_type,
            default=payload["default"],
            minimum=minimum,
            maximum=maximum,
        )
    elif parameter_type is ParameterType.DECIMAL:
        _strict_keys(
            payload, common | {key for key in ("min", "max") if key in payload}
        )
        minimum_value = payload.get("min")
        maximum_value = payload.get("max")
        minimum = (
            _decimal_string(minimum_value)[1] if minimum_value is not None else None
        )
        maximum = (
            _decimal_string(maximum_value)[1] if maximum_value is not None else None
        )
        if (
            minimum is not None
            and maximum is not None
            and Decimal(minimum) > Decimal(maximum)
        ):
            _fail()
        descriptor = ParameterDescriptor(
            name=name,
            type=parameter_type,
            default=payload["default"],
            minimum=minimum,
            maximum=maximum,
        )
    elif parameter_type is ParameterType.BOOLEAN:
        _strict_keys(payload, common)
        descriptor = ParameterDescriptor(
            name=name,
            type=parameter_type,
            default=payload["default"],
        )
    else:
        _strict_keys(payload, common | {"options"})
        options = payload.get("options")
        if (
            not isinstance(options, list)
            or not options
            or not all(isinstance(item, str) and item for item in options)
            or len(set(options)) != len(options)
        ):
            _fail()
        descriptor = ParameterDescriptor(
            name=name,
            type=parameter_type,
            default=payload["default"],
            options=tuple(options),
        )
    normalized_default = _parameter_value(
        descriptor, descriptor.default, registry_load=True
    )
    return ParameterDescriptor(
        name=descriptor.name,
        type=descriptor.type,
        default=normalized_default,
        minimum=descriptor.minimum,
        maximum=descriptor.maximum,
        options=descriptor.options,
    )


def _strategy_file(strategy_root: Path, entry_file: object) -> tuple[str, Path]:
    if not isinstance(entry_file, str):
        _fail()
    pure_path = PurePath(entry_file)
    if (
        pure_path.is_absolute()
        or len(pure_path.parts) != 1
        or pure_path.suffix != ".py"
    ):
        _fail()
    resolved = (strategy_root / entry_file).resolve(strict=False)
    if not resolved.is_relative_to(strategy_root) or not resolved.is_file():
        _fail()
    return entry_file, resolved


def _strategy(payload: object, strategy_root: Path) -> RegisteredStrategy:
    if not isinstance(payload, dict):
        _fail()
    _strict_keys(
        payload,
        {
            "id",
            "name",
            "description",
            "enabled",
            "entry_file",
            "supported_frequencies",
            "defaults",
            "parameters",
        },
    )
    strategy_id = payload["id"]
    if not isinstance(strategy_id, str) or _IDENTIFIER.fullmatch(strategy_id) is None:
        _fail()
    if not isinstance(payload["name"], str) or not payload["name"]:
        _fail()
    if not isinstance(payload["description"], str) or not payload["description"]:
        _fail()
    if not isinstance(payload["enabled"], bool):
        _fail()
    entry_file, strategy_file = _strategy_file(strategy_root, payload["entry_file"])
    frequencies = payload["supported_frequencies"]
    if (
        not isinstance(frequencies, list)
        or not frequencies
        or not all(item in {"1d", "1m"} for item in frequencies)
        or len(set(frequencies)) != len(frequencies)
    ):
        _fail()
    defaults = payload["defaults"]
    if not isinstance(defaults, dict) or set(defaults) != _CONFIG_KEYS:
        _fail()
    normalized_defaults: dict[str, str] = {}
    for key, value in defaults.items():
        if key in _DECIMAL_CONFIG_KEYS:
            parsed, normalized = _decimal_string(value)
            if (key in {"future_cash", "margin_multiplier"} and parsed <= 0) or (
                key in {"futures_commission_multiplier", "slippage"} and parsed < 0
            ):
                _fail()
            normalized_defaults[key] = normalized
        elif key == "matching_type":
            if value not in {"current_bar", "next_bar"}:
                _fail()
            if any(
                value == "next_bar" and frequency == "1d" for frequency in frequencies
            ):
                _fail()
            normalized_defaults[key] = value
        else:
            if value not in {"PriceRatioSlippage", "TickSizeSlippage"}:
                _fail()
            normalized_defaults[key] = value
    raw_parameters = payload["parameters"]
    if not isinstance(raw_parameters, list):
        _fail()
    parameters = tuple(_parameter_descriptor(item) for item in raw_parameters)
    if len({item.name for item in parameters}) != len(parameters):
        _fail()
    return RegisteredStrategy(
        id=strategy_id,
        name=payload["name"],
        description=payload["description"],
        enabled=payload["enabled"],
        entry_file=entry_file,
        strategy_file=strategy_file,
        supported_frequencies=tuple(frequencies),
        defaults=normalized_defaults,
        parameters=parameters,
    )


class StrategyRegistry:
    """Validated immutable collection of registered strategies."""

    def __init__(self, strategies: tuple[RegisteredStrategy, ...]) -> None:
        self._strategies = strategies
        self._by_id = {item.id: item for item in strategies}

    @classmethod
    def load(cls, path: Path, strategy_root: Path) -> StrategyRegistry:
        root = Path(strategy_root).resolve(strict=False)
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RegistryError from exc
        if not isinstance(payload, dict):
            _fail()
        _strict_keys(payload, {"schema_version", "strategies"})
        schema_version = payload["schema_version"]
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != 1
            or not isinstance(payload["strategies"], list)
        ):
            _fail()
        strategies = tuple(_strategy(item, root) for item in payload["strategies"])
        if len({item.id for item in strategies}) != len(strategies):
            _fail()
        return cls(strategies)

    def list_enabled(self) -> tuple[RegisteredStrategy, ...]:
        return tuple(item for item in self._strategies if item.enabled)

    def resolve_enabled(self, strategy_id: str) -> RegisteredStrategy:
        strategy = self._by_id.get(strategy_id)
        if strategy is None or not strategy.enabled:
            raise StrategyNotFoundError
        return strategy

    def validate_request(self, request: BacktestRunRequest) -> ValidatedBacktestRequest:
        strategy = self.resolve_enabled(request.strategy_id)
        if request.frequency not in strategy.supported_frequencies:
            raise InvalidBacktestRequestError
        future_cash = request.future_cash or Decimal(strategy.defaults["future_cash"])
        matching_type = request.matching_type or strategy.defaults["matching_type"]
        margin_multiplier = request.margin_multiplier or Decimal(
            strategy.defaults["margin_multiplier"]
        )
        futures_commission_multiplier = (
            request.futures_commission_multiplier
            if request.futures_commission_multiplier is not None
            else Decimal(strategy.defaults["futures_commission_multiplier"])
        )
        slippage_model = request.slippage_model or strategy.defaults["slippage_model"]
        slippage = (
            request.slippage
            if request.slippage is not None
            else Decimal(strategy.defaults["slippage"])
        )
        descriptors = {item.name: item for item in strategy.parameters}
        if not set(request.parameters).issubset(descriptors):
            raise InvalidBacktestRequestError
        parameters = {
            name: _parameter_value(
                descriptor,
                request.parameters.get(name, descriptor.default),
                registry_load=False,
            )
            for name, descriptor in descriptors.items()
        }
        config = {
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
            "frequency": request.frequency,
            "future_cash": normalize_decimal(future_cash),
            "matching_type": matching_type,
            "margin_multiplier": normalize_decimal(margin_multiplier),
            "futures_commission_multiplier": normalize_decimal(
                futures_commission_multiplier
            ),
            "slippage_model": slippage_model,
            "slippage": normalize_decimal(slippage),
        }
        return ValidatedBacktestRequest(
            strategy=strategy,
            strategy_file=strategy.strategy_file,
            parameters=parameters,
            config=config,
        )
