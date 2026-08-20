from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path
import traceback
from typing import Any

import pytest

from app.market_data.domain import BarFrequency
from app.market_data.n_structure_policy import (
    NStructurePolicyError,
    load_n_structure_policy,
)


def _valid_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "policy_id": "n_structure_5m_v1",
        "formula_version": "n_structure_v1",
        "research_only": True,
        "source_timeframe": "5m",
        "swing": {
            "breach_basis": "previous_bar_high_low",
            "equal_is_breach": False,
            "outside_bar": "reset_unresolved_epoch",
            "inside_bar": "continue_current_or_stay_unresolved",
            "extreme_tie": "keep_first",
        },
        "n_pattern": {
            "base_origin_equal_allowed": True,
            "completion": "first_strict_n1_extreme_breach",
            "same_boundary_completion_break": (
                "record_both_without_intrabar_order_claim"
            ),
            "completed_identity_immutable": True,
            "n2_break_is_reversal": False,
            "origin_break_is_stronger_direction_break": True,
        },
        "range_band": {
            "definition": "n1_n2_price_span_v1",
            "reentry_starts": "after_completion_boundary",
            "strong_medium_weak_labels": False,
        },
        "structure": {
            "minimum_completed_n": 2,
            "kinds": ["bull", "bear", "range"],
            "outside_bar_preserves_active_direction_unless_defense_breaks": True,
            "defense_break": "strict",
            "break_to": "range",
        },
        "outcome": {
            "entry_price": "completion_bar_close",
            "horizons_bars": [3, 5, 8],
            "may_cross_trading_day": True,
            "may_cross_rank1_segment": False,
        },
    }


def _write_payload(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _nested_mapping(payload: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    target = payload
    for part in path:
        nested = target[part]
        assert isinstance(nested, dict)
        target = nested
    return target


def _set_path(payload: dict[str, Any], path: tuple[str, ...], value: object) -> None:
    _nested_mapping(payload, path[:-1])[path[-1]] = value


def _assert_invalid(path: Path) -> NStructurePolicyError:
    with pytest.raises(NStructurePolicyError) as captured:
        load_n_structure_policy(path)
    error = captured.value
    assert error.code == "N_STRUCTURE_POLICY_INVALID"
    assert str(error) == "N_STRUCTURE_POLICY_INVALID"
    assert error.__cause__ is None
    return error


def _assert_input_details_hidden(
    error: NStructurePolicyError,
    *,
    path: Path,
    underlying_error: str,
) -> None:
    rendered = "".join(traceback.format_exception(error))
    assert str(path) not in rendered
    assert underlying_error not in rendered


def test_load_exact_policy() -> None:
    policy = load_n_structure_policy()

    assert policy.schema_version == 1
    assert policy.policy_id == "n_structure_5m_v1"
    assert policy.formula_version == "n_structure_v1"
    assert policy.research_only is True
    assert policy.source_timeframe is BarFrequency.M5
    assert policy.raw["swing"]["outside_bar"] == "reset_unresolved_epoch"  # type: ignore[index]
    assert policy.raw["n_pattern"]["same_boundary_completion_break"] == (  # type: ignore[index]
        "record_both_without_intrabar_order_claim"
    )
    assert policy.raw["outcome"]["may_cross_trading_day"] is True  # type: ignore[index]
    assert policy.raw["outcome"]["may_cross_rank1_segment"] is False  # type: ignore[index]


def test_policy_dataclass_is_frozen() -> None:
    policy = load_n_structure_policy()

    with pytest.raises(FrozenInstanceError):
        policy.policy_id = "drifted"  # type: ignore[misc]


def test_missing_policy_file_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"

    error = _assert_invalid(path)

    _assert_input_details_hidden(
        error,
        path=path,
        underlying_error="FileNotFoundError",
    )


def test_invalid_json_policy_hides_parser_details(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text("{", encoding="utf-8")

    error = _assert_invalid(path)

    _assert_input_details_hidden(
        error,
        path=path,
        underlying_error="JSONDecodeError",
    )


def test_non_utf8_policy_hides_decoder_details(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_bytes(b"\xff\xfe\x00")

    error = _assert_invalid(path)

    _assert_input_details_hidden(
        error,
        path=path,
        underlying_error="UnicodeDecodeError",
    )


@pytest.mark.parametrize("contents", (b"[]", b"null"))
def test_non_object_policy_fails_closed(tmp_path: Path, contents: bytes) -> None:
    path = tmp_path / "policy.json"
    path.write_bytes(contents)

    _assert_invalid(path)


@pytest.mark.parametrize(
    ("container_path", "key"),
    (
        ((), "formula_version"),
        (("swing",), "outside_bar"),
        (("n_pattern",), "completion"),
        (("range_band",), "reentry_starts"),
        (("structure",), "defense_break"),
        (("outcome",), "may_cross_rank1_segment"),
    ),
)
def test_missing_policy_key_fails_closed(
    tmp_path: Path,
    container_path: tuple[str, ...],
    key: str,
) -> None:
    payload = _valid_payload()
    del _nested_mapping(payload, container_path)[key]
    path = tmp_path / "policy.json"
    _write_payload(path, payload)

    _assert_invalid(path)


@pytest.mark.parametrize(
    "container_path",
    ((), ("swing",), ("n_pattern",), ("range_band",), ("structure",), ("outcome",)),
)
def test_extra_policy_key_fails_closed(
    tmp_path: Path,
    container_path: tuple[str, ...],
) -> None:
    payload = _valid_payload()
    _nested_mapping(payload, container_path)["unexpected"] = True
    path = tmp_path / "policy.json"
    _write_payload(path, payload)

    _assert_invalid(path)


@pytest.mark.parametrize(
    ("field_path", "invalid"),
    (
        (("schema_version",), 2),
        (("schema_version",), True),
        (("policy_id",), "n_structure_5m_v2"),
        (("formula_version",), "n_structure_v2"),
        (("research_only",), False),
        (("source_timeframe",), "15m"),
        (("swing", "breach_basis"), "current_bar_high_low"),
        (("swing", "equal_is_breach"), True),
        (("swing", "outside_bar"), "continue"),
        (("swing", "inside_bar"), "reset"),
        (("swing", "extreme_tie"), "keep_last"),
        (("n_pattern", "base_origin_equal_allowed"), False),
        (("n_pattern", "completion"), "close_breach"),
        (("n_pattern", "same_boundary_completion_break"), "order_completion_first"),
        (("n_pattern", "completed_identity_immutable"), False),
        (("n_pattern", "n2_break_is_reversal"), True),
        (("n_pattern", "origin_break_is_stronger_direction_break"), False),
        (("range_band", "definition"), "n1_origin_price_span"),
        (("range_band", "reentry_starts"), "on_completion_boundary"),
        (("range_band", "strong_medium_weak_labels"), True),
        (("structure", "minimum_completed_n"), 3),
        (("structure", "minimum_completed_n"), True),
        (("structure", "kinds"), ["bull", "range", "bear"]),
        (
            (
                "structure",
                "outside_bar_preserves_active_direction_unless_defense_breaks",
            ),
            False,
        ),
        (("structure", "defense_break"), "inclusive"),
        (("structure", "break_to"), "reverse"),
        (("outcome", "entry_price"), "next_bar_open"),
        (("outcome", "horizons_bars"), [3, 5]),
        (("outcome", "horizons_bars"), [3, 5, 8.0]),
        (("outcome", "may_cross_trading_day"), False),
        (("outcome", "may_cross_rank1_segment"), True),
    ),
)
def test_policy_value_or_type_drift_fails_closed(
    tmp_path: Path,
    field_path: tuple[str, ...],
    invalid: object,
) -> None:
    payload = _valid_payload()
    _set_path(payload, field_path, invalid)
    path = tmp_path / "policy.json"
    _write_payload(path, payload)

    _assert_invalid(path)
