from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import date
import json
from pathlib import Path
import traceback
from types import MappingProxyType
from typing import Any

import pytest

import app.market_data.jdj_policy as jdj_policy_module
import app.market_data.jdj_candidate_validation_policy as policy_module
from app.market_data.jdj_candidate_validation_policy import (
    JdjCandidateManifest,
    JdjCandidateManifestError,
    JdjCandidateRef,
    JdjCandidateValidationProtocolError,
    load_jdj_candidate_manifest,
    load_jdj_candidate_validation_protocol,
)


EXPECTED_PAIRS = (
    (
        "jdj_trend_follow_1m_candidate_v1",
        "jdj_trend_follow_triggered",
    ),
    (
        "jdj_trend_reentry_6_1m_candidate_v1",
        "jdj_trend_reentry_6_triggered",
    ),
    (
        "jdj_key_level_breakout_1m_candidate_v1",
        "jdj_key_level_breakout_triggered",
    ),
)


def _manifest_payload(candidate_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "source_kind": "jdj_1m",
        "policy_id": "jdj_1m_policy_v1",
        "formula_version": "jdj_1m_v1",
        "research_only": True,
    }


def _protocol_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_id": "jdj_candidate_validation_v1",
        "research_only": True,
        "candidates": [
            {"candidate_id": candidate_id, "source_event_kind": event_kind}
            for candidate_id, event_kind in EXPECTED_PAIRS
        ],
        "candidate_frozen_at": "2026-08-21T09:34:00+08:00",
        "anchor_symbol": "jm",
        "retrospective": {
            "since": "2023-01-01",
            "through": "2026-08-20",
        },
        "embargo_trading_days": ["2026-08-21"],
        "rolling_stability": {
            "reference_months": 12,
            "test_months": 3,
            "step_months": 3,
            "first_test_since": "2024-01-01",
            "last_test_through": "2026-06-30",
        },
        "prospective_oos": {"first_trading_day": "2026-08-24"},
        "baseline_request_through": "2026-08-21",
        "horizons_bars": [3, 5, 8, 20],
        "automatic_ranking": False,
        "automatic_promotion": False,
    }


JsonPath = tuple[str | int, ...]


def _value_at(payload: object, path: JsonPath) -> object:
    target = payload
    for part in path:
        if isinstance(part, str):
            assert isinstance(target, dict)
        else:
            assert isinstance(target, list)
        target = target[part]
    return target


def _set(payload: object, path: JsonPath, value: object) -> None:
    parent = _value_at(payload, path[:-1])
    part = path[-1]
    if isinstance(part, str):
        assert isinstance(parent, dict)
    else:
        assert isinstance(parent, list)
    parent[part] = value


def _dict_paths(payload: object, prefix: JsonPath = ()) -> tuple[JsonPath, ...]:
    paths: list[JsonPath] = []
    if isinstance(payload, dict):
        paths.append(prefix)
        for key, value in payload.items():
            paths.extend(_dict_paths(value, (*prefix, key)))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            paths.extend(_dict_paths(value, (*prefix, index)))
    return tuple(paths)


def _field_paths(payload: object, prefix: JsonPath = ()) -> tuple[JsonPath, ...]:
    paths: list[JsonPath] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = (*prefix, key)
            paths.append(path)
            paths.extend(_field_paths(value, path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            paths.extend(_field_paths(value, (*prefix, index)))
    return tuple(paths)


def _leaf_paths(payload: object, prefix: JsonPath = ()) -> tuple[JsonPath, ...]:
    paths: list[JsonPath] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            paths.extend(_leaf_paths(value, (*prefix, key)))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            paths.extend(_leaf_paths(value, (*prefix, index)))
    else:
        paths.append(prefix)
    return tuple(paths)


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
    if type(value) is bool:
        return not value
    if type(value) is int:
        return value + 1
    if type(value) is str:
        return f"{value}_drift"
    raise AssertionError(f"unsupported fixture value: {type(value)!r}")


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _patch_candidate_path(
    monkeypatch: pytest.MonkeyPatch, candidate_id: str, path: Path
) -> None:
    paths = dict(policy_module._CANDIDATE_PATHS)
    paths[candidate_id] = path
    monkeypatch.setattr(
        policy_module,
        "_CANDIDATE_PATHS",
        MappingProxyType(paths),
    )


def _assert_manifest_error(candidate_id: str) -> JdjCandidateManifestError:
    with pytest.raises(JdjCandidateManifestError) as captured:
        load_jdj_candidate_manifest(candidate_id)
    error = captured.value
    assert error.code == "JDJ_CANDIDATE_MANIFEST_INVALID"
    assert str(error) == "JDJ_CANDIDATE_MANIFEST_INVALID"
    assert error.__cause__ is None
    return error


def _assert_protocol_error() -> JdjCandidateValidationProtocolError:
    with pytest.raises(JdjCandidateValidationProtocolError) as captured:
        load_jdj_candidate_validation_protocol()
    error = captured.value
    assert error.code == "JDJ_CANDIDATE_PROTOCOL_INVALID"
    assert str(error) == "JDJ_CANDIDATE_PROTOCOL_INVALID"
    assert error.__cause__ is None
    return error


def test_loads_three_exact_candidate_manifests() -> None:
    manifests = tuple(
        load_jdj_candidate_manifest(candidate_id)
        for candidate_id, _event_kind in EXPECTED_PAIRS
    )

    assert tuple(manifest.candidate_id for manifest in manifests) == tuple(
        candidate_id for candidate_id, _event_kind in EXPECTED_PAIRS
    )
    assert all(manifest.schema_version == 1 for manifest in manifests)
    assert all(manifest.source_kind == "jdj_1m" for manifest in manifests)
    assert all(manifest.policy_id == "jdj_1m_policy_v1" for manifest in manifests)
    assert all(manifest.formula_version == "jdj_1m_v1" for manifest in manifests)
    assert all(manifest.research_only is True for manifest in manifests)


def test_protocol_freezes_candidate_event_pairs_dates_and_safety_flags() -> None:
    protocol = load_jdj_candidate_validation_protocol()

    assert protocol.schema_version == 1
    assert protocol.protocol_id == "jdj_candidate_validation_v1"
    assert protocol.research_only is True
    assert tuple(
        (item.candidate_id, item.source_event_kind) for item in protocol.candidates
    ) == EXPECTED_PAIRS
    assert protocol.candidate_frozen_at.isoformat() == "2026-08-21T09:34:00+08:00"
    assert protocol.anchor_symbol == "jm"
    assert protocol.retrospective_since == date(2023, 1, 1)
    assert protocol.retrospective_through == date(2026, 8, 20)
    assert protocol.embargo_trading_days == (date(2026, 8, 21),)
    assert protocol.reference_months == 12
    assert protocol.test_months == 3
    assert protocol.step_months == 3
    assert protocol.first_test_since == date(2024, 1, 1)
    assert protocol.last_test_through == date(2026, 6, 30)
    assert protocol.prospective_oos_first_trading_day == date(2026, 8, 24)
    assert protocol.baseline_request_through == date(2026, 8, 21)
    assert protocol.horizons_bars == (3, 5, 8, 20)
    assert protocol.automatic_ranking is False
    assert protocol.automatic_promotion is False


def test_candidate_protocol_types_are_frozen_and_validate_direct_construction() -> None:
    manifest = load_jdj_candidate_manifest(EXPECTED_PAIRS[0][0])
    protocol = load_jdj_candidate_validation_protocol()

    with pytest.raises(FrozenInstanceError):
        manifest.candidate_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        protocol.candidates = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        protocol.candidates[0].source_event_kind = "changed"  # type: ignore[misc]
    with pytest.raises(JdjCandidateManifestError):
        JdjCandidateManifest(
            schema_version=True,
            candidate_id=EXPECTED_PAIRS[0][0],
            source_kind="jdj_1m",
            policy_id="jdj_1m_policy_v1",
            formula_version="jdj_1m_v1",
            research_only=True,
        )
    with pytest.raises(JdjCandidateValidationProtocolError):
        JdjCandidateRef(
            candidate_id=EXPECTED_PAIRS[0][0],
            source_event_kind=EXPECTED_PAIRS[1][1],
        )


def test_unknown_candidate_fails_before_any_file_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_read(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("unknown candidate must not read a path")

    monkeypatch.setattr(Path, "read_text", unexpected_read)

    _assert_manifest_error("jdj_1m_candidate_v1")


@pytest.mark.parametrize("candidate_id", tuple(item[0] for item in EXPECTED_PAIRS))
def test_manifest_file_errors_are_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    candidate_id: str,
) -> None:
    sources = (tmp_path / "missing.json", tmp_path / "malformed.json", tmp_path / "bytes.json")
    sources[1].write_text("{", encoding="utf-8")
    sources[2].write_bytes(b"\xff\xfe")

    for source in sources:
        _patch_candidate_path(monkeypatch, candidate_id, source)
        error = _assert_manifest_error(candidate_id)
        rendered = "".join(traceback.format_exception(error))
        assert str(source) not in rendered
        for forbidden in ("FileNotFoundError", "JSONDecodeError", "UnicodeDecodeError"):
            assert forbidden not in rendered


def test_protocol_file_errors_are_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = (tmp_path / "missing.json", tmp_path / "malformed.json", tmp_path / "bytes.json")
    sources[1].write_text("{", encoding="utf-8")
    sources[2].write_bytes(b"\xff\xfe")

    for source in sources:
        monkeypatch.setattr(policy_module, "_PROTOCOL_PATH", source)
        error = _assert_protocol_error()
        rendered = "".join(traceback.format_exception(error))
        assert str(source) not in rendered
        for forbidden in ("FileNotFoundError", "JSONDecodeError", "UnicodeDecodeError"):
            assert forbidden not in rendered


@pytest.mark.parametrize("candidate_id", tuple(item[0] for item in EXPECTED_PAIRS))
@pytest.mark.parametrize("field_path", _field_paths(_manifest_payload(EXPECTED_PAIRS[0][0])))
def test_manifest_missing_wrong_type_or_value_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    candidate_id: str,
    field_path: JsonPath,
) -> None:
    for mutation in ("missing", "wrong_type", "wrong_value"):
        payload = _manifest_payload(candidate_id)
        if mutation == "missing":
            parent = _value_at(payload, field_path[:-1])
            assert isinstance(parent, dict)
            del parent[field_path[-1]]
        elif mutation == "wrong_type":
            _set(payload, field_path, _wrong_type(_value_at(payload, field_path)))
        else:
            _set(payload, field_path, _wrong_value(_value_at(payload, field_path)))
        source = tmp_path / f"{candidate_id}-{mutation}.json"
        _write(source, payload)
        _patch_candidate_path(monkeypatch, candidate_id, source)

        _assert_manifest_error(candidate_id)


@pytest.mark.parametrize("candidate_id", tuple(item[0] for item in EXPECTED_PAIRS))
def test_manifest_extra_key_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    candidate_id: str,
) -> None:
    payload = _manifest_payload(candidate_id)
    payload["unexpected"] = True
    source = tmp_path / f"{candidate_id}.json"
    _write(source, payload)
    _patch_candidate_path(monkeypatch, candidate_id, source)

    _assert_manifest_error(candidate_id)


@pytest.mark.parametrize("field_path", _field_paths(_protocol_payload()))
def test_every_missing_protocol_field_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field_path: JsonPath,
) -> None:
    payload = _protocol_payload()
    parent = _value_at(payload, field_path[:-1])
    part = field_path[-1]
    if isinstance(part, str):
        assert isinstance(parent, dict)
        del parent[part]
    else:
        raise AssertionError("list members are values, not named fields")
    source = tmp_path / "protocol.json"
    _write(source, payload)
    monkeypatch.setattr(policy_module, "_PROTOCOL_PATH", source)

    _assert_protocol_error()


@pytest.mark.parametrize("mapping_path", _dict_paths(_protocol_payload()))
def test_extra_key_in_every_protocol_mapping_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mapping_path: JsonPath,
) -> None:
    payload = _protocol_payload()
    target = _value_at(payload, mapping_path)
    assert isinstance(target, dict)
    target["unexpected"] = True
    source = tmp_path / "protocol.json"
    _write(source, payload)
    monkeypatch.setattr(policy_module, "_PROTOCOL_PATH", source)

    _assert_protocol_error()


@pytest.mark.parametrize("field_path", _field_paths(_protocol_payload()))
def test_every_protocol_field_rejects_wrong_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field_path: JsonPath,
) -> None:
    payload = _protocol_payload()
    _set(payload, field_path, _wrong_type(_value_at(payload, field_path)))
    source = tmp_path / "protocol.json"
    _write(source, payload)
    monkeypatch.setattr(policy_module, "_PROTOCOL_PATH", source)

    _assert_protocol_error()


@pytest.mark.parametrize("field_path", _leaf_paths(_protocol_payload()))
def test_every_protocol_leaf_rejects_value_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field_path: JsonPath,
) -> None:
    payload = deepcopy(_protocol_payload())
    _set(payload, field_path, _wrong_value(_value_at(payload, field_path)))
    source = tmp_path / "protocol.json"
    _write(source, payload)
    monkeypatch.setattr(policy_module, "_PROTOCOL_PATH", source)

    _assert_protocol_error()


def test_manifest_policy_drift_maps_to_manifest_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy_payload = json.loads(
        (
            Path(__file__).parents[3]
            / "data/research_policies/jdj_1m_policy_v1.json"
        ).read_text(encoding="utf-8")
    )
    policy_payload["automatic_promotion"] = True
    source = tmp_path / "jdj-policy.json"
    _write(source, policy_payload)
    monkeypatch.setattr(jdj_policy_module, "_JDJ_POLICY_PATH", source)

    _assert_manifest_error(EXPECTED_PAIRS[0][0])


def test_protocol_fails_when_a_referenced_manifest_is_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate_id = EXPECTED_PAIRS[1][0]
    payload = _manifest_payload(candidate_id)
    payload["policy_id"] = "jdj_1m_policy_v2"
    source = tmp_path / "candidate.json"
    _write(source, payload)
    _patch_candidate_path(monkeypatch, candidate_id, source)

    _assert_protocol_error()
