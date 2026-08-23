from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from pydantic import ValidationError

from app.backtest.contracts import BacktestRunRequest, RunStatus
from app.backtest.errors import (
    BacktestHttpErrorCode,
    InvalidBacktestRequestError,
    RegistryError,
    StrategyNotFoundError,
)
from app.backtest.registry import StrategyRegistry
from app.backtest.strategy_params import (
    STRATEGY_PARAMS_FILE_ENV,
    StrategyParamsError,
    load_strategy_params,
)


def _strategy(
    *,
    strategy_id: str = "example",
    entry_file: str = "example.py",
    enabled: bool = True,
    parameters: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "id": strategy_id,
        "name": "Example",
        "description": "Fixture strategy",
        "enabled": enabled,
        "entry_file": entry_file,
        "supported_frequencies": ["1d", "1m"],
        "defaults": {
            "future_cash": "1000000",
            "matching_type": "current_bar",
            "margin_multiplier": "1",
            "futures_commission_multiplier": "1",
            "slippage_model": "PriceRatioSlippage",
            "slippage": "0",
        },
        "parameters": parameters or [],
    }


def _write_registry(
    tmp_path: Path,
    strategies: list[dict[str, object]],
) -> tuple[Path, Path]:
    strategy_root = tmp_path / "strategies"
    strategy_root.mkdir()
    for item in strategies:
        entry_file = item.get("entry_file")
        if isinstance(entry_file, str) and "/" not in entry_file:
            (strategy_root / entry_file).write_text("# fixture\n", encoding="utf-8")
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps({"schema_version": 1, "strategies": strategies}),
        encoding="utf-8",
    )
    return path, strategy_root


def _request(**overrides: object) -> BacktestRunRequest:
    payload: dict[str, object] = {
        "strategy_id": "example",
        "start_date": "2026-01-05",
        "end_date": "2026-01-09",
        "frequency": "1d",
        "future_cash": "1000000.00",
        "matching_type": "current_bar",
        "margin_multiplier": "1.25",
        "futures_commission_multiplier": "1",
        "slippage_model": "PriceRatioSlippage",
        "slippage": "0.0001",
        "parameters": {},
    }
    payload.update(overrides)
    return BacktestRunRequest.model_validate(payload)


def test_contract_enums_are_stable_and_complete() -> None:
    assert tuple(RunStatus) == (
        RunStatus.RUNNING,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.TIMED_OUT,
        RunStatus.INTERRUPTED,
    )
    assert {item.value for item in BacktestHttpErrorCode} == {
        "BACKTEST_LOCAL_UNAVAILABLE",
        "RUNNER_UNAVAILABLE",
        "BUNDLE_UNAVAILABLE",
        "REGISTRY_INVALID",
        "STRATEGY_NOT_FOUND",
        "INVALID_BACKTEST_REQUEST",
        "BACKTEST_ALREADY_RUNNING",
        "BACKTEST_RUN_NOT_FOUND",
        "BACKTEST_ARTIFACT_NOT_FOUND",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("future_cash", "0"),
        ("future_cash", "-1"),
        ("margin_multiplier", "0"),
        ("futures_commission_multiplier", "-0.01"),
        ("slippage", "-0.01"),
        ("future_cash", 1_000_000),
        ("slippage", 0.1),
        ("future_cash", "NaN"),
        ("future_cash", "Infinity"),
    ],
)
def test_request_rejects_invalid_decimal_strings(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _request(**{field: value})


def test_request_rejects_reversed_dates_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _request(start_date="2026-01-10", end_date="2026-01-09")
    with pytest.raises(ValidationError):
        _request(arbitrary_rqalpha_config={"base": {"auto_update_bundle": True}})


@pytest.mark.parametrize("field", ["start_date", "end_date"])
@pytest.mark.parametrize(
    "value",
    [
        1_767_744_000,
        date(2026, 1, 5),
        datetime(2026, 1, 5),
        datetime(2026, 1, 5, tzinfo=timezone.utc),
        "2026-1-5",
        "2026-01-05T00:00:00",
        "2026-01-05T00:00:00+08:00",
        " 2026-01-05 ",
    ],
)
def test_request_dates_require_exact_iso_json_strings(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        _request(**{field: value})


@pytest.mark.parametrize(
    "overrides",
    [
        {"frequency": "tick"},
        {"slippage_model": "CustomPythonSlippage"},
        {"frequency": "1d", "matching_type": "next_bar"},
        {"frequency": "1m", "matching_type": "best_own"},
    ],
)
def test_request_rejects_unsupported_frequency_slippage_or_matching(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _request(**overrides)


def test_request_accepts_minute_next_bar_matching() -> None:
    request = _request(frequency="1m", matching_type="next_bar")

    assert request.start_date == date(2026, 1, 5)
    assert request.future_cash == Decimal("1000000.00")
    assert request.matching_type == "next_bar"


def test_registry_rejects_duplicate_ids(tmp_path: Path) -> None:
    path, root = _write_registry(
        tmp_path,
        [_strategy(), _strategy(entry_file="other.py")],
    )

    with pytest.raises(RegistryError, match="^REGISTRY_INVALID$"):
        StrategyRegistry.load(path, root)


@pytest.mark.parametrize("schema_version", [True, 1.0, "1", 2])
def test_registry_requires_exact_integer_schema_version(
    tmp_path: Path,
    schema_version: object,
) -> None:
    path, root = _write_registry(tmp_path, [_strategy()])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = schema_version
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RegistryError, match="^REGISTRY_INVALID$"):
        StrategyRegistry.load(path, root)


@pytest.mark.parametrize(
    "malformation",
    ["frequency_object", "matching_object", "slippage_model_object"],
)
def test_registry_malformed_json_shapes_fail_with_stable_error(
    tmp_path: Path,
    malformation: str,
) -> None:
    path, root = _write_registry(tmp_path, [_strategy()])
    payload = json.loads(path.read_text(encoding="utf-8"))
    strategy = payload["strategies"][0]
    if malformation == "frequency_object":
        strategy["supported_frequencies"] = [{}]
    elif malformation == "matching_object":
        strategy["defaults"]["matching_type"] = {}
    else:
        strategy["defaults"]["slippage_model"] = []
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RegistryError, match="^REGISTRY_INVALID$"):
        StrategyRegistry.load(path, root)


def test_registry_lists_only_enabled_and_disabled_cannot_resolve(
    tmp_path: Path,
) -> None:
    path, root = _write_registry(
        tmp_path,
        [_strategy(), _strategy(strategy_id="disabled", enabled=False)],
    )
    registry = StrategyRegistry.load(path, root)

    assert [item.id for item in registry.list_enabled()] == ["example"]
    with pytest.raises(StrategyNotFoundError, match="^STRATEGY_NOT_FOUND$"):
        registry.resolve_enabled("disabled")


def test_registry_callers_cannot_mutate_validated_defaults(tmp_path: Path) -> None:
    path, root = _write_registry(tmp_path, [_strategy()])
    registry = StrategyRegistry.load(path, root)

    for exposed in (registry.resolve_enabled("example"), registry.list_enabled()[0]):
        try:
            exposed.defaults["future_cash"] = "0"
        except TypeError:
            pass
        assert registry.resolve_enabled("example").defaults["future_cash"] == "1000000"

    validated = registry.validate_request(
        BacktestRunRequest.model_validate(
            {
                "strategy_id": "example",
                "start_date": "2026-01-05",
                "end_date": "2026-01-09",
                "frequency": "1d",
            }
        )
    )
    assert validated.config["future_cash"] == "1000000"


@pytest.mark.parametrize("entry_file", ["../outside.py", "/tmp/outside.py", "note.txt"])
def test_registry_rejects_path_traversal_and_non_python_entries(
    tmp_path: Path,
    entry_file: str,
) -> None:
    path, root = _write_registry(tmp_path, [_strategy(entry_file=entry_file)])

    with pytest.raises(RegistryError, match="^REGISTRY_INVALID$"):
        StrategyRegistry.load(path, root)


def test_registry_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("# outside\n", encoding="utf-8")
    path, root = _write_registry(tmp_path, [_strategy(entry_file="link.py")])
    (root / "link.py").unlink()
    (root / "link.py").symlink_to(outside)

    with pytest.raises(RegistryError, match="^REGISTRY_INVALID$"):
        StrategyRegistry.load(path, root)


def test_registry_rejects_unregistered_parameters(tmp_path: Path) -> None:
    path, root = _write_registry(tmp_path, [_strategy()])
    registry = StrategyRegistry.load(path, root)

    with pytest.raises(
        InvalidBacktestRequestError,
        match="^INVALID_BACKTEST_REQUEST$",
    ):
        registry.validate_request(_request(parameters={"shell": "rm -rf /"}))


def test_registry_normalizes_parameter_types_ranges_and_defaults(
    tmp_path: Path,
) -> None:
    parameters = [
        {"name": "quantity", "type": "integer", "default": 2, "min": 1, "max": 10},
        {
            "name": "threshold",
            "type": "decimal",
            "default": "0.50",
            "min": "0.10",
            "max": "0.90",
        },
        {"name": "enabled_filter", "type": "boolean", "default": True},
        {
            "name": "order_book_id",
            "type": "enum",
            "default": "IF1606",
            "options": ["IF1606", "IH1606"],
        },
    ]
    path, root = _write_registry(tmp_path, [_strategy(parameters=parameters)])
    registry = StrategyRegistry.load(path, root)

    validated = registry.validate_request(
        _request(parameters={"quantity": 10, "threshold": "0.70"})
    )

    assert validated.strategy.id == "example"
    assert validated.strategy_file == (root / "example.py").resolve()
    assert validated.parameters == {
        "quantity": 10,
        "threshold": "0.7",
        "enabled_filter": True,
        "order_book_id": "IF1606",
    }
    assert validated.config == {
        "start_date": "2026-01-05",
        "end_date": "2026-01-09",
        "frequency": "1d",
        "future_cash": "1000000",
        "matching_type": "current_bar",
        "margin_multiplier": "1.25",
        "futures_commission_multiplier": "1",
        "slippage_model": "PriceRatioSlippage",
        "slippage": "0.0001",
    }


def test_registry_applies_registered_config_defaults(tmp_path: Path) -> None:
    path, root = _write_registry(tmp_path, [_strategy()])
    registry = StrategyRegistry.load(path, root)
    request = BacktestRunRequest.model_validate(
        {
            "strategy_id": "example",
            "start_date": "2026-01-05",
            "end_date": "2026-01-09",
            "frequency": "1d",
        }
    )

    validated = registry.validate_request(request)

    assert validated.config == {
        "start_date": "2026-01-05",
        "end_date": "2026-01-09",
        "frequency": "1d",
        "future_cash": "1000000",
        "matching_type": "current_bar",
        "margin_multiplier": "1",
        "futures_commission_multiplier": "1",
        "slippage_model": "PriceRatioSlippage",
        "slippage": "0",
    }


@pytest.mark.parametrize(
    "parameters",
    [
        {"quantity": True},
        {"quantity": 0},
        {"quantity": 11},
        {"threshold": 0.5},
        {"threshold": "0.09"},
        {"enabled_filter": 1},
        {"order_book_id": "RB1610"},
    ],
)
def test_registry_rejects_wrong_parameter_type_or_range(
    tmp_path: Path,
    parameters: dict[str, object],
) -> None:
    descriptors = [
        {"name": "quantity", "type": "integer", "default": 1, "min": 1, "max": 10},
        {
            "name": "threshold",
            "type": "decimal",
            "default": "0.5",
            "min": "0.1",
            "max": "0.9",
        },
        {"name": "enabled_filter", "type": "boolean", "default": False},
        {
            "name": "order_book_id",
            "type": "enum",
            "default": "IF1606",
            "options": ["IF1606"],
        },
    ]
    path, root = _write_registry(tmp_path, [_strategy(parameters=descriptors)])
    registry = StrategyRegistry.load(path, root)

    with pytest.raises(
        InvalidBacktestRequestError,
        match="^INVALID_BACKTEST_REQUEST$",
    ):
        registry.validate_request(_request(parameters=parameters))


@pytest.mark.parametrize(
    "descriptor",
    [
        {"name": "quantity", "type": "integer", "default": 0, "min": 1},
        {"name": "quantity", "type": "integer", "default": 1, "min": None},
        {"name": "quantity", "type": "integer", "default": 1, "max": None},
        {"name": "ratio", "type": "decimal", "default": 1.0},
        {"name": "ratio", "type": "decimal", "default": "1", "min": None},
        {"name": "ratio", "type": "decimal", "default": "1", "max": None},
        {"name": "flag", "type": "boolean", "default": "yes"},
        {"name": "symbol", "type": "enum", "default": "IF1606", "options": []},
        {"name": "symbol", "type": "path", "default": "/tmp/a.py"},
    ],
)
def test_registry_rejects_invalid_parameter_descriptors(
    tmp_path: Path,
    descriptor: dict[str, object],
) -> None:
    path, root = _write_registry(tmp_path, [_strategy(parameters=[descriptor])])

    with pytest.raises(RegistryError, match="^REGISTRY_INVALID$"):
        StrategyRegistry.load(path, root)


def test_fixed_example_registry_contract() -> None:
    strategy_root = Path(__file__).parents[2] / "app" / "backtest" / "strategies"
    registry = StrategyRegistry.load(strategy_root / "registry.json", strategy_root)

    strategy = registry.resolve_enabled("example_future_smoke_v1")
    descriptors = {item.name: item for item in strategy.parameters}
    assert strategy.supported_frequencies == ("1d", "1m")
    assert descriptors["order_book_id"].options == ("IF1606",)
    assert descriptors["order_book_id"].default == "IF1606"
    assert descriptors["quantity"].default == 1
    assert descriptors["quantity"].minimum == 1
    assert descriptors["quantity"].maximum == 10


def test_strategy_params_loader_reads_only_fixed_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    params_path = tmp_path / "params.json"
    params_path.write_text('{"quantity": 3}', encoding="utf-8")
    ignored_path = tmp_path / "ignored.json"
    ignored_path.write_text('{"quantity": 99}', encoding="utf-8")
    monkeypatch.setenv(STRATEGY_PARAMS_FILE_ENV, str(params_path))
    monkeypatch.setenv("RQALPHA_STRATEGY_PARAMS_FILE", str(ignored_path))

    assert load_strategy_params() == {"quantity": 3}


def test_strategy_params_loader_rejects_missing_or_non_object_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(STRATEGY_PARAMS_FILE_ENV, raising=False)
    with pytest.raises(StrategyParamsError, match="^STRATEGY_PARAMS_INVALID$"):
        load_strategy_params()

    params_path = tmp_path / "params.json"
    params_path.write_text("[]", encoding="utf-8")
    monkeypatch.setenv(STRATEGY_PARAMS_FILE_ENV, str(params_path))
    with pytest.raises(StrategyParamsError, match="^STRATEGY_PARAMS_INVALID$"):
        load_strategy_params()


def test_example_strategy_places_one_simulation_future_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    params_path = tmp_path / "params.json"
    params_path.write_text(
        '{"order_book_id": "IF1606", "quantity": 2}',
        encoding="utf-8",
    )
    monkeypatch.setenv(STRATEGY_PARAMS_FILE_ENV, str(params_path))
    orders: list[tuple[str, int]] = []
    rqalpha = ModuleType("rqalpha")
    rqalpha_api = ModuleType("rqalpha.api")
    rqalpha_api.buy_open = lambda order_book_id, quantity: orders.append(
        (order_book_id, quantity)
    )
    monkeypatch.setitem(sys.modules, "rqalpha", rqalpha)
    monkeypatch.setitem(sys.modules, "rqalpha.api", rqalpha_api)
    strategy_path = (
        Path(__file__).parents[2]
        / "app"
        / "backtest"
        / "strategies"
        / "example_future_smoke_v1.py"
    )
    spec = importlib.util.spec_from_file_location(
        "example_future_smoke_v1", strategy_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = SimpleNamespace()

    module.init(context)
    module.handle_bar(context, {})
    module.handle_bar(context, {})

    assert orders == [("IF1606", 2)]
