from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.core.env import PROJECT_ROOT
from app.research.subing import candidate_validation_policy as policy_module
from app.research.subing.candidate_validation_policy import (
    CandidateValidationAuthority,
    CandidateManifestError,
    CandidateValidationProtocolError,
    load_candidate_validation_authority,
)


_CANDIDATE_SOURCE = (
    PROJECT_ROOT / "data/research_candidates/subing_lifecycle_v2_candidate_v1.json"
)
_PROTOCOL_SOURCE = PROJECT_ROOT / "data/research_protocols/candidate_validation_v1.json"


def _json_payload(source: Path) -> dict[str, Any]:
    value = json.loads(source.read_text(encoding="utf-8"))
    assert type(value) is dict
    return value


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _candidate_copy(tmp_path: Path) -> Path:
    path = tmp_path / _CANDIDATE_SOURCE.name
    path.write_bytes(_CANDIDATE_SOURCE.read_bytes())
    return path


def _protocol_copy(tmp_path: Path) -> Path:
    path = tmp_path / _PROTOCOL_SOURCE.name
    path.write_bytes(_PROTOCOL_SOURCE.read_bytes())
    return path


def test_loads_candidate_validation_as_one_pinned_authority() -> None:
    authority = load_candidate_validation_authority()

    assert authority.manifest.candidate_id == "subing_lifecycle_v2_candidate_v1"
    assert authority.manifest.policy_id == "subing_lifecycle_v2_research_v1"
    assert authority.protocol.protocol_id == "candidate_validation_v1"
    assert authority.protocol.retrospective_since == date(2023, 1, 1)
    assert authority.protocol.horizons_bars == (3, 5, 8)
    assert authority.manifest_sha256 == (
        "c597d7821cf98e933f9d818fa7995d4f2c2628d69afe122d4fdb644fcbdac78c"
    )
    assert authority.protocol_sha256 == (
        "8da442e75b315a2684d5353cc2977afc8af839df153cb677b311a35d5d8cf438"
    )


def test_authority_and_its_contracts_are_immutable() -> None:
    authority = load_candidate_validation_authority()

    with pytest.raises(FrozenInstanceError):
        authority.manifest.candidate_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        authority.protocol.retrospective_through = date(2026, 8, 19)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        authority.manifest_sha256 = "0" * 64  # type: ignore[misc]


def test_authority_rejects_manual_construction() -> None:
    authority = load_candidate_validation_authority()

    with pytest.raises(TypeError):
        CandidateValidationAuthority(
            manifest=authority.manifest,
            protocol=authority.protocol,
            manifest_sha256=authority.manifest_sha256,
            protocol_sha256=authority.protocol_sha256,
        )


@pytest.mark.parametrize(
    ("argument", "error_type"),
    (
        ("manifest_path", CandidateManifestError),
        ("protocol_path", CandidateValidationProtocolError),
    ),
)
def test_missing_malformed_and_non_utf8_files_fail_closed(
    tmp_path: Path,
    argument: str,
    error_type: type[ValueError],
) -> None:
    for name, content in (
        ("missing.json", None),
        ("malformed.json", b"{"),
        ("non-utf8.json", b"\xff\xfe"),
    ):
        source = tmp_path / name
        if content is not None:
            source.write_bytes(content)
        with pytest.raises(error_type):
            load_candidate_validation_authority(**{argument: source})


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload.__setitem__("schema_version", True),
        lambda payload: payload.__setitem__("source_kind", ""),
        lambda payload: payload.__setitem__("research_only", False),
        lambda payload: payload.__setitem__("policy_id", "different_policy"),
    ),
)
def test_candidate_schema_or_semantic_drift_fails_closed(
    tmp_path: Path,
    mutation: Any,
) -> None:
    source = _candidate_copy(tmp_path)
    payload = _json_payload(source)
    mutation(payload)
    _write_payload(source, payload)

    with pytest.raises(CandidateManifestError, match="CANDIDATE_MANIFEST_INVALID"):
        load_candidate_validation_authority(manifest_path=source)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload.__setitem__("schema_version", True),
        lambda payload: payload.__setitem__("research_only", False),
        lambda payload: payload.__setitem__(
            "candidate_frozen_at", "2026-08-19T20:57:00"
        ),
        lambda payload: payload["retrospective"].__setitem__("since", "2026-08-19"),
        lambda payload: payload["horizons_bars"].__setitem__(1, 3),
    ),
)
def test_protocol_schema_or_semantic_drift_fails_closed(
    tmp_path: Path,
    mutation: Any,
) -> None:
    source = _protocol_copy(tmp_path)
    payload = _json_payload(source)
    mutation(payload)
    _write_payload(source, payload)

    with pytest.raises(
        CandidateValidationProtocolError,
        match="CANDIDATE_VALIDATION_PROTOCOL_INVALID",
    ):
        load_candidate_validation_authority(protocol_path=source)


@pytest.mark.parametrize(
    ("path", "argument", "error_type"),
    (
        (("unexpected",), "manifest_path", CandidateManifestError),
        (
            ("retrospective", "unexpected"),
            "protocol_path",
            CandidateValidationProtocolError,
        ),
        (
            ("rolling_stability", "unexpected"),
            "protocol_path",
            CandidateValidationProtocolError,
        ),
        (
            ("prospective_oos", "unexpected"),
            "protocol_path",
            CandidateValidationProtocolError,
        ),
    ),
)
def test_extra_keys_fail_closed(
    tmp_path: Path,
    path: tuple[str, ...],
    argument: str,
    error_type: type[ValueError],
) -> None:
    source = (
        _candidate_copy(tmp_path)
        if argument == "manifest_path"
        else _protocol_copy(tmp_path)
    )
    payload = _json_payload(source)
    target = payload
    for part in path[:-1]:
        nested = target[part]
        assert type(nested) is dict
        target = nested
    target[path[-1]] = True
    _write_payload(source, payload)

    with pytest.raises(error_type):
        load_candidate_validation_authority(**{argument: source})


@pytest.mark.parametrize(
    ("source_factory", "argument", "error_type"),
    (
        (_candidate_copy, "manifest_path", CandidateManifestError),
        (_protocol_copy, "protocol_path", CandidateValidationProtocolError),
    ),
)
def test_missing_keys_fail_closed(
    tmp_path: Path,
    source_factory: Any,
    argument: str,
    error_type: type[ValueError],
) -> None:
    source = source_factory(tmp_path)
    payload = _json_payload(source)
    del payload[next(iter(payload))]
    _write_payload(source, payload)

    with pytest.raises(error_type):
        load_candidate_validation_authority(**{argument: source})


@pytest.mark.parametrize(
    "container",
    (
        "retrospective",
        "rolling_stability",
        "prospective_oos",
    ),
)
def test_nested_protocol_missing_keys_fail_closed(
    tmp_path: Path,
    container: str,
) -> None:
    source = _protocol_copy(tmp_path)
    payload = _json_payload(source)
    nested = payload[container]
    assert type(nested) is dict
    del nested[next(iter(nested))]
    _write_payload(source, payload)

    with pytest.raises(CandidateValidationProtocolError):
        load_candidate_validation_authority(protocol_path=source)


@pytest.mark.parametrize(
    ("source_factory", "argument", "error_type"),
    (
        (_candidate_copy, "manifest_path", CandidateManifestError),
        (_protocol_copy, "protocol_path", CandidateValidationProtocolError),
    ),
)
def test_filename_stem_must_match_parsed_id(
    tmp_path: Path,
    source_factory: Any,
    argument: str,
    error_type: type[ValueError],
) -> None:
    source = source_factory(tmp_path)
    renamed = tmp_path / "different_name.json"
    renamed.write_bytes(source.read_bytes())

    with pytest.raises(error_type):
        load_candidate_validation_authority(**{argument: renamed})


@pytest.mark.parametrize(
    ("source_factory", "argument", "error_type"),
    (
        (_candidate_copy, "manifest_path", CandidateManifestError),
        (_protocol_copy, "protocol_path", CandidateValidationProtocolError),
    ),
)
def test_same_id_raw_byte_drift_fails_closed_after_typed_validation(
    tmp_path: Path,
    source_factory: Any,
    argument: str,
    error_type: type[ValueError],
) -> None:
    source = source_factory(tmp_path)
    source.write_bytes(source.read_bytes() + b"\n")

    with pytest.raises(error_type):
        load_candidate_validation_authority(**{argument: source})


def test_typed_validation_happens_before_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _candidate_copy(tmp_path)
    payload = _json_payload(source)
    payload["research_only"] = False
    _write_payload(source, payload)
    calls = 0

    def record_digest(*_args: object) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(policy_module, "_verify_digest", record_digest)

    with pytest.raises(CandidateManifestError):
        load_candidate_validation_authority(manifest_path=source)

    assert calls == 0
