from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
from typing import Any, Callable

import pytest

from app.market_data.n_candidate_validation_policy import (
    NCandidateManifestError,
    NCandidateValidationProtocolError,
    load_n_candidate_manifest,
    load_n_candidate_validation_protocol,
)


def _manifest_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "candidate_id": "n_structure_5m_candidate_v1",
        "source_kind": "n_structure",
        "policy_id": "n_structure_5m_v1",
        "formula_version": "n_structure_v1",
        "research_only": True,
    }


def _protocol_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "protocol_id": "n_structure_validation_v1",
        "research_only": True,
        "candidate_frozen_at": "2026-08-20T00:22:00+08:00",
        "retrospective": {"since": "2023-01-01", "through": "2026-08-19"},
        "embargo_trading_days": ["2026-08-20"],
        "rolling_stability": {
            "reference_months": 12,
            "test_months": 3,
            "step_months": 3,
            "first_test_since": "2024-01-01",
            "last_test_through": "2026-06-30",
        },
        "prospective_oos": {"first_trading_day": "2026-08-21"},
        "horizons_bars": [3, 5, 8],
    }


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _set(payload: dict[str, Any], path: tuple[str, ...], value: object) -> None:
    target = payload
    for part in path[:-1]:
        nested = target[part]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = value


def test_loads_exact_n_candidate_and_embargo_protocol() -> None:
    manifest = load_n_candidate_manifest()
    protocol = load_n_candidate_validation_protocol()

    assert manifest.candidate_id == "n_structure_5m_candidate_v1"
    assert manifest.source_kind == "n_structure"
    assert manifest.policy_id == "n_structure_5m_v1"
    assert manifest.formula_version == "n_structure_v1"
    assert manifest.research_only is True
    assert protocol.protocol_id == "n_structure_validation_v1"
    assert protocol.candidate_frozen_at.isoformat() == "2026-08-20T00:22:00+08:00"
    assert protocol.retrospective_since == date(2023, 1, 1)
    assert protocol.retrospective_through == date(2026, 8, 19)
    assert protocol.embargo_trading_days == (date(2026, 8, 20),)
    assert protocol.reference_months == 12
    assert protocol.test_months == 3
    assert protocol.step_months == 3
    assert protocol.first_test_since == date(2024, 1, 1)
    assert protocol.last_test_through == date(2026, 6, 30)
    assert protocol.prospective_oos_first_trading_day == date(2026, 8, 21)
    assert protocol.horizons_bars == (3, 5, 8)


def test_n_candidate_and_protocol_are_immutable() -> None:
    manifest = load_n_candidate_manifest()
    protocol = load_n_candidate_validation_protocol()

    with pytest.raises(FrozenInstanceError):
        manifest.candidate_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        protocol.embargo_trading_days = ()  # type: ignore[misc]


@pytest.mark.parametrize(
    ("loader", "error_type"),
    (
        (load_n_candidate_manifest, NCandidateManifestError),
        (load_n_candidate_validation_protocol, NCandidateValidationProtocolError),
    ),
)
def test_missing_malformed_and_non_utf8_files_fail_closed(
    tmp_path: Path,
    loader: Callable[[Path], object],
    error_type: type[ValueError],
) -> None:
    with pytest.raises(error_type):
        loader(tmp_path / "missing.json")

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(error_type):
        loader(malformed)

    non_utf8 = tmp_path / "non-utf8.json"
    non_utf8.write_bytes(b"\xff\xfe")
    with pytest.raises(error_type):
        loader(non_utf8)


@pytest.mark.parametrize(
    ("path", "invalid"),
    (
        (("schema_version",), True),
        (("candidate_id",), "n_structure_5m_candidate_v2"),
        (("source_kind",), "subing_lifecycle"),
        (("policy_id",), "n_structure_15m_v1"),
        (("formula_version",), "n_structure_v2"),
        (("research_only",), False),
    ),
)
def test_n_candidate_identity_or_type_drift_fails_closed(
    tmp_path: Path,
    path: tuple[str, ...],
    invalid: object,
) -> None:
    payload = _manifest_payload()
    _set(payload, path, invalid)
    source = tmp_path / "candidate.json"
    _write(source, payload)

    with pytest.raises(
        NCandidateManifestError,
        match="N_CANDIDATE_MANIFEST_INVALID",
    ):
        load_n_candidate_manifest(source)


@pytest.mark.parametrize(
    ("path", "invalid"),
    (
        (("schema_version",), True),
        (("protocol_id",), "candidate_validation_v1"),
        (("research_only",), False),
        (("candidate_frozen_at",), "2026-08-20T00:23:00+08:00"),
        (("retrospective", "since"), "2023-01-02"),
        (("retrospective", "through"), "2026-08-20"),
        (("embargo_trading_days",), []),
        (("embargo_trading_days",), ["2026-08-19"]),
        (("rolling_stability", "reference_months"), 11),
        (("rolling_stability", "test_months"), 2),
        (("rolling_stability", "step_months"), 2),
        (("rolling_stability", "first_test_since"), "2024-04-01"),
        (("rolling_stability", "last_test_through"), "2026-09-30"),
        (("prospective_oos", "first_trading_day"), "2026-08-20"),
        (("horizons_bars",), [3, 5]),
    ),
)
def test_n_protocol_identity_temporal_or_type_drift_fails_closed(
    tmp_path: Path,
    path: tuple[str, ...],
    invalid: object,
) -> None:
    payload = _protocol_payload()
    _set(payload, path, invalid)
    source = tmp_path / "protocol.json"
    _write(source, payload)

    with pytest.raises(
        NCandidateValidationProtocolError,
        match="N_CANDIDATE_PROTOCOL_INVALID",
    ):
        load_n_candidate_validation_protocol(source)


@pytest.mark.parametrize(
    ("factory", "container", "loader", "error_type"),
    (
        (_manifest_payload, (), load_n_candidate_manifest, NCandidateManifestError),
        (
            _protocol_payload,
            (),
            load_n_candidate_validation_protocol,
            NCandidateValidationProtocolError,
        ),
        (
            _protocol_payload,
            ("retrospective",),
            load_n_candidate_validation_protocol,
            NCandidateValidationProtocolError,
        ),
        (
            _protocol_payload,
            ("rolling_stability",),
            load_n_candidate_validation_protocol,
            NCandidateValidationProtocolError,
        ),
        (
            _protocol_payload,
            ("prospective_oos",),
            load_n_candidate_validation_protocol,
            NCandidateValidationProtocolError,
        ),
    ),
)
def test_n_candidate_and_protocol_extra_or_missing_keys_fail_closed(
    tmp_path: Path,
    factory: Callable[[], dict[str, Any]],
    container: tuple[str, ...],
    loader: Callable[[Path], object],
    error_type: type[ValueError],
) -> None:
    for mutation in ("extra", "missing"):
        payload = factory()
        target = payload
        for part in container:
            nested = target[part]
            assert isinstance(nested, dict)
            target = nested
        if mutation == "extra":
            target["unexpected"] = True
        else:
            del target[next(iter(target))]
        source = tmp_path / f"{mutation}-{len(container)}.json"
        _write(source, payload)
        with pytest.raises(error_type):
            loader(source)
