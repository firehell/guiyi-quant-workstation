from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import traceback
from types import MappingProxyType
from typing import Any

import pytest

from app.market_data.domain import BarFrequency
from app.market_data.jdj_policy import (
    JdjPolicyError,
    is_exact_jdj_policy,
    load_jdj_policy,
)


def _policy_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "policy_id": "jdj_1m_policy_v1",
        "formula_version": "jdj_1m_v1",
        "research_only": True,
        "source_timeframe": "1m",
        "trend_context_timeframe": "5m",
        "trend_context": {
            "policy_id": "n_structure_5m_v1",
            "formula_version": "n_structure_v1",
            "strict_before": True,
            "same_epoch_key_level": True,
        },
        "ema": {
            "kind": "ema",
            "period": 20,
            "seed_policy": "sma_window",
            "round_digits": 6,
            "input_field": "close",
        },
        "previous_bar_trigger": {
            "dynamic_reference": True,
            "equal_is_breach": False,
            "fill_model": False,
        },
        "state_boundary": {
            "same_trading_day": True,
            "same_physical_contract": True,
            "same_rank1_segment": True,
        },
        "trend_follow": {
            "reaction": "ema_touch_and_close_on_trend_side",
            "armed_invalidation": "ema_close_failure_or_trend_lost",
            "same_bar_trigger_invalidation": "ambiguous_no_event",
        },
        "trend_reentry_6": {
            "trend_side_prerequisite": True,
            "excursion_reference": "opposite_ema_side_extreme",
            "reclaim": "first_close_back_on_trend_side",
            "reclaim_bar_can_react": False,
            "first_post_reclaim_reaction_only": True,
            "failed_first_reaction_terminal": True,
            "armed_invalidation": "ema_close_failure_or_trend_lost",
        },
        "key_level_breakout": {
            "pivot_source": "latest_same_epoch_confirmed_n_swing",
            "post_confirmation_origin_side_required": True,
            "first_break_basis": "close_cross",
            "first_break_creates_entry": False,
            "first_break_bar_can_retest": False,
            "volume_rule": "all_first_break_do_not_chase",
            "retest": "touch_level_and_close_on_breakout_side",
            "failed_retest": "close_not_on_breakout_side",
            "same_pivot_single_episode": True,
            "armed_invalidation": (
                "close_back_through_frozen_level_or_trend_lost"
            ),
        },
        "outcome": {
            "reference_price": "trigger_bar_close",
            "horizons_bars": [3, 5, 8, 20],
            "trigger_bar_in_future_window": False,
            "same_trading_day": True,
            "same_physical_contract": True,
            "same_rank1_segment": True,
        },
        "parameter_sweep": False,
        "automatic_ranking": False,
        "automatic_promotion": False,
    }


def _mapping_at(payload: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    target = payload
    for part in path:
        nested = target[part]
        assert isinstance(nested, dict)
        target = nested
    return target


def _field_paths(
    payload: dict[str, Any], prefix: tuple[str, ...] = ()
) -> tuple[tuple[str, ...], ...]:
    paths: list[tuple[str, ...]] = []
    for key, value in payload.items():
        path = (*prefix, key)
        paths.append(path)
        if isinstance(value, dict):
            paths.extend(_field_paths(value, path))
    return tuple(paths)


def _mapping_paths(
    payload: dict[str, Any], prefix: tuple[str, ...] = ()
) -> tuple[tuple[str, ...], ...]:
    paths = [prefix]
    for key, value in payload.items():
        if isinstance(value, dict):
            paths.extend(_mapping_paths(value, (*prefix, key)))
    return tuple(paths)


def _leaf_paths(
    payload: dict[str, Any], prefix: tuple[str, ...] = ()
) -> tuple[tuple[str, ...], ...]:
    paths: list[tuple[str, ...]] = []
    for key, value in payload.items():
        path = (*prefix, key)
        if isinstance(value, dict):
            paths.extend(_leaf_paths(value, path))
        else:
            paths.append(path)
    return tuple(paths)


def _get(payload: dict[str, Any], path: tuple[str, ...]) -> object:
    target: object = payload
    for part in path:
        assert isinstance(target, dict)
        target = target[part]
    return target


def _set(payload: dict[str, Any], path: tuple[str, ...], value: object) -> None:
    _mapping_at(payload, path[:-1])[path[-1]] = value


def _wrong_type(value: object) -> object:
    if isinstance(value, dict):
        return []
    if isinstance(value, list):
        return {}
    if type(value) is bool:
        return 0
    if type(value) is int:
        return str(value)
    if type(value) is str:
        return False
    raise AssertionError(f"unsupported fixture value: {type(value)!r}")


def _wrong_value(value: object) -> object:
    if isinstance(value, list):
        return list(reversed(value))
    if type(value) is bool:
        return not value
    if type(value) is int:
        return value + 1
    if type(value) is str:
        return f"{value}_drift"
    raise AssertionError(f"unsupported fixture value: {type(value)!r}")


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _assert_invalid(path: Path) -> JdjPolicyError:
    with pytest.raises(JdjPolicyError) as captured:
        load_jdj_policy(path)
    error = captured.value
    assert error.code == "JDJ_POLICY_INVALID"
    assert str(error) == "JDJ_POLICY_INVALID"
    assert error.__cause__ is None
    return error


def test_loads_exact_jdj_v1_policy() -> None:
    policy = load_jdj_policy()

    assert policy.schema_version == 1
    assert policy.policy_id == "jdj_1m_policy_v1"
    assert policy.formula_version == "jdj_1m_v1"
    assert policy.research_only is True
    assert policy.source_timeframe is BarFrequency.M1
    assert policy.trend_context_timeframe is BarFrequency.M5
    assert policy.ema_period == 20
    assert policy.ema_seed_policy == "sma_window"
    assert policy.ema_round_digits == 6
    assert policy.strict_previous_bar_trigger is True
    assert policy.same_epoch_key_level is True
    assert policy.raw["trend_follow"]["reaction"] == (  # type: ignore[index]
        "ema_touch_and_close_on_trend_side"
    )
    assert policy.raw["trend_reentry_6"][  # type: ignore[index]
        "first_post_reclaim_reaction_only"
    ] is True
    assert policy.raw["key_level_breakout"][  # type: ignore[index]
        "first_break_creates_entry"
    ] is False
    assert policy.raw["outcome"]["horizons_bars"] == (3, 5, 8, 20)  # type: ignore[index]


def test_policy_is_recursively_frozen_and_exactly_validated() -> None:
    policy = load_jdj_policy()

    assert isinstance(policy.raw, MappingProxyType)
    assert isinstance(policy.raw["trend_context"], MappingProxyType)
    assert isinstance(policy.raw["outcome"], MappingProxyType)
    with pytest.raises(FrozenInstanceError):
        policy.policy_id = "drifted"  # type: ignore[misc]
    with pytest.raises(TypeError):
        policy.raw["unexpected"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        policy.raw["outcome"]["horizons_bars"][0] = 2  # type: ignore[index]

    assert is_exact_jdj_policy(policy) is True
    assert is_exact_jdj_policy(replace(policy, schema_version=True)) is False
    assert is_exact_jdj_policy(replace(policy, research_only=False)) is False
    assert is_exact_jdj_policy(replace(policy, raw=MappingProxyType({}))) is False
    assert is_exact_jdj_policy(object()) is False


def test_missing_malformed_and_non_utf8_policy_fail_without_input_details(
    tmp_path: Path,
) -> None:
    sources = (tmp_path / "missing.json", tmp_path / "malformed.json", tmp_path / "bytes.json")
    sources[1].write_text("{", encoding="utf-8")
    sources[2].write_bytes(b"\xff\xfe")

    for source in sources:
        error = _assert_invalid(source)
        rendered = "".join(traceback.format_exception(error))
        assert str(source) not in rendered
        for forbidden in ("FileNotFoundError", "JSONDecodeError", "UnicodeDecodeError"):
            assert forbidden not in rendered


@pytest.mark.parametrize("payload", (None, [], "jdj", 1, True))
def test_non_object_policy_fails_closed(tmp_path: Path, payload: object) -> None:
    path = tmp_path / "policy.json"
    _write(path, payload)

    _assert_invalid(path)


@pytest.mark.parametrize("field_path", _field_paths(_policy_payload()))
def test_every_missing_policy_field_fails_closed(
    tmp_path: Path, field_path: tuple[str, ...]
) -> None:
    payload = _policy_payload()
    del _mapping_at(payload, field_path[:-1])[field_path[-1]]
    path = tmp_path / "policy.json"
    _write(path, payload)

    _assert_invalid(path)


@pytest.mark.parametrize("mapping_path", _mapping_paths(_policy_payload()))
def test_extra_key_in_every_policy_mapping_fails_closed(
    tmp_path: Path, mapping_path: tuple[str, ...]
) -> None:
    payload = _policy_payload()
    _mapping_at(payload, mapping_path)["unexpected"] = True
    path = tmp_path / "policy.json"
    _write(path, payload)

    _assert_invalid(path)


@pytest.mark.parametrize("field_path", _field_paths(_policy_payload()))
def test_every_policy_field_rejects_wrong_type(
    tmp_path: Path, field_path: tuple[str, ...]
) -> None:
    payload = _policy_payload()
    _set(payload, field_path, _wrong_type(_get(payload, field_path)))
    path = tmp_path / "policy.json"
    _write(path, payload)

    _assert_invalid(path)


@pytest.mark.parametrize("field_path", _leaf_paths(_policy_payload()))
def test_every_policy_leaf_rejects_value_drift(
    tmp_path: Path, field_path: tuple[str, ...]
) -> None:
    payload = deepcopy(_policy_payload())
    _set(payload, field_path, _wrong_value(_get(payload, field_path)))
    path = tmp_path / "policy.json"
    _write(path, payload)

    _assert_invalid(path)
