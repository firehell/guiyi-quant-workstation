from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import MappingProxyType

import pytest


class ExactContractError(ValueError):
    pass


def _contract_module():
    module_name = "app.core.exact_json_contract"
    assert importlib.util.find_spec(module_name) is not None
    return importlib.import_module(module_name)


def test_exact_json_match_is_recursive_and_type_strict() -> None:
    contract = _contract_module()
    expected = {"enabled": True, "values": [1, {"name": "jm"}]}

    assert contract.matches_exact_json(expected, expected) is True
    assert contract.matches_exact_json({"enabled": 1, "values": [1, {"name": "jm"}]}, expected) is False
    assert contract.matches_exact_json({"enabled": True, "values": [1]}, expected) is False
    assert contract.matches_exact_json({**expected, "extra": None}, expected) is False


def test_freeze_and_frozen_match_preserve_exact_json_shape() -> None:
    contract = _contract_module()
    expected = {"items": [{"value": 1}], "enabled": False}

    frozen = contract.freeze_json(expected)

    assert isinstance(frozen, MappingProxyType)
    assert isinstance(frozen["items"], tuple)
    assert contract.matches_exact_frozen(frozen, expected) is True
    assert contract.matches_exact_frozen(frozen, {"items": [{"value": 2}], "enabled": False}) is False


def test_load_exact_json_returns_only_the_expected_contract(tmp_path: Path) -> None:
    contract = _contract_module()
    path = tmp_path / "policy.json"
    path.write_text('{"schema_version": 1, "enabled": true}', encoding="utf-8")

    assert contract.load_exact_json(
        path,
        {"schema_version": 1, "enabled": True},
        ExactContractError,
    ) == {"schema_version": 1, "enabled": True}

    path.write_text('{"schema_version": 1, "enabled": 1}', encoding="utf-8")
    with pytest.raises(ExactContractError):
        contract.load_exact_json(
            path,
            {"schema_version": 1, "enabled": True},
            ExactContractError,
        )

    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ExactContractError):
        contract.load_exact_json(
            path,
            {"schema_version": 1, "enabled": True},
            ExactContractError,
        )
