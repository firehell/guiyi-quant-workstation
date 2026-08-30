from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, TypeVar

from app.core.env import PROJECT_ROOT


_CANDIDATE_PATH = (
    PROJECT_ROOT / "data/research_candidates/subing_lifecycle_v2_candidate_v1.json"
)
_PROTOCOL_PATH = PROJECT_ROOT / "data/research_protocols/candidate_validation_v1.json"
_CANDIDATE_SHA256 = "c597d7821cf98e933f9d818fa7995d4f2c2628d69afe122d4fdb644fcbdac78c"
_PROTOCOL_SHA256 = "8da442e75b315a2684d5353cc2977afc8af839df153cb677b311a35d5d8cf438"
_CANDIDATE_KEYS = frozenset(
    {
        "schema_version",
        "candidate_id",
        "source_kind",
        "policy_id",
        "formula_version",
        "research_only",
    }
)
_PROTOCOL_KEYS = frozenset(
    {
        "schema_version",
        "protocol_id",
        "research_only",
        "candidate_frozen_at",
        "retrospective",
        "rolling_stability",
        "prospective_oos",
        "horizons_bars",
    }
)
_RETROSPECTIVE_KEYS = frozenset({"since", "through"})
_ROLLING_STABILITY_KEYS = frozenset(
    {
        "reference_months",
        "test_months",
        "step_months",
        "first_test_since",
        "last_test_through",
    }
)
_PROSPECTIVE_OOS_KEYS = frozenset({"first_trading_day"})
_AUTHORITY_PROVENANCE = object()


class CandidateManifestError(ValueError):
    code = "CANDIDATE_MANIFEST_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class CandidateValidationProtocolError(ValueError):
    code = "CANDIDATE_VALIDATION_PROTOCOL_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class CandidateManifest:
    schema_version: int
    candidate_id: str
    source_kind: str
    policy_id: str
    formula_version: str
    research_only: bool

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or not _is_nonempty_string(self.candidate_id)
            or not _is_nonempty_string(self.source_kind)
            or not _is_nonempty_string(self.policy_id)
            or not _is_nonempty_string(self.formula_version)
            or self.research_only is not True
        ):
            raise CandidateManifestError()


@dataclass(frozen=True, slots=True)
class CandidateValidationProtocol:
    schema_version: int
    protocol_id: str
    research_only: bool
    candidate_frozen_at: datetime
    retrospective_since: date
    retrospective_through: date
    reference_months: int
    test_months: int
    step_months: int
    first_test_since: date
    last_test_through: date
    prospective_oos_first_trading_day: date
    horizons_bars: tuple[int, ...]

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or not _is_nonempty_string(self.protocol_id)
            or self.research_only is not True
            or type(self.candidate_frozen_at) is not datetime
            or self.candidate_frozen_at.tzinfo is None
            or self.candidate_frozen_at.utcoffset() is None
            or not _is_exact_date(self.retrospective_since)
            or not _is_exact_date(self.retrospective_through)
            or not _is_positive_int(self.reference_months)
            or not _is_positive_int(self.test_months)
            or not _is_positive_int(self.step_months)
            or not _is_exact_date(self.first_test_since)
            or not _is_exact_date(self.last_test_through)
            or not _is_exact_date(self.prospective_oos_first_trading_day)
            or not _are_strictly_increasing_positive_ints(self.horizons_bars)
            or self.retrospective_since > self.retrospective_through
            or self.first_test_since > self.last_test_through
            or self.first_test_since < self.retrospective_since
            or self.last_test_through > self.retrospective_through
            or self.prospective_oos_first_trading_day < self.candidate_frozen_at.date()
        ):
            raise CandidateValidationProtocolError()


@dataclass(frozen=True, slots=True)
class CandidateValidationAuthority:
    manifest: CandidateManifest
    protocol: CandidateValidationProtocol
    manifest_sha256: str
    protocol_sha256: str
    _provenance: object = field(init=False, repr=False, compare=False, default=None)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.manifest, CandidateManifest)
            or not isinstance(self.protocol, CandidateValidationProtocol)
            or self.manifest_sha256 != _CANDIDATE_SHA256
            or self.protocol_sha256 != _PROTOCOL_SHA256
            or self._provenance is not _AUTHORITY_PROVENANCE
        ):
            raise TypeError("authority must use validated Candidate contracts")

    @classmethod
    def _from_verified(
        cls,
        *,
        manifest: CandidateManifest,
        protocol: CandidateValidationProtocol,
    ) -> CandidateValidationAuthority:
        authority = object.__new__(cls)
        object.__setattr__(authority, "manifest", manifest)
        object.__setattr__(authority, "protocol", protocol)
        object.__setattr__(authority, "manifest_sha256", _CANDIDATE_SHA256)
        object.__setattr__(authority, "protocol_sha256", _PROTOCOL_SHA256)
        object.__setattr__(authority, "_provenance", _AUTHORITY_PROVENANCE)
        return authority


_ContractError = TypeVar(
    "_ContractError", CandidateManifestError, CandidateValidationProtocolError
)


def load_candidate_validation_authority(
    *,
    manifest_path: Path | None = None,
    protocol_path: Path | None = None,
) -> CandidateValidationAuthority:
    """Load the pinned Candidate identity and validation schedule as one authority."""
    manifest_source = manifest_path if manifest_path is not None else _CANDIDATE_PATH
    protocol_source = protocol_path if protocol_path is not None else _PROTOCOL_PATH

    manifest_payload, manifest_raw = _read_json_object(
        manifest_source, CandidateManifestError
    )
    protocol_payload, protocol_raw = _read_json_object(
        protocol_source, CandidateValidationProtocolError
    )
    manifest = _parse_manifest(manifest_source, manifest_payload)
    protocol = _parse_protocol(protocol_source, protocol_payload)

    if manifest.research_only is not protocol.research_only:
        raise CandidateValidationProtocolError()
    _verify_digest(manifest_raw, _CANDIDATE_SHA256, CandidateManifestError)
    _verify_digest(protocol_raw, _PROTOCOL_SHA256, CandidateValidationProtocolError)

    return CandidateValidationAuthority._from_verified(
        manifest=manifest,
        protocol=protocol,
    )


def _read_json_object(
    path: Path,
    error_type: type[_ContractError],
) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise error_type() from None
    if type(payload) is not dict:
        raise error_type()
    return payload, raw


def _parse_manifest(path: Path, payload: dict[str, Any]) -> CandidateManifest:
    _require_exact_keys(payload, _CANDIDATE_KEYS, CandidateManifestError)
    manifest = CandidateManifest(
        schema_version=payload["schema_version"],
        candidate_id=payload["candidate_id"],
        source_kind=payload["source_kind"],
        policy_id=payload["policy_id"],
        formula_version=payload["formula_version"],
        research_only=payload["research_only"],
    )
    if path.stem != manifest.candidate_id:
        raise CandidateManifestError()
    return manifest


def _parse_protocol(
    path: Path,
    payload: dict[str, Any],
) -> CandidateValidationProtocol:
    _require_exact_keys(payload, _PROTOCOL_KEYS, CandidateValidationProtocolError)
    retrospective = _require_object(
        payload["retrospective"], _RETROSPECTIVE_KEYS, CandidateValidationProtocolError
    )
    rolling = _require_object(
        payload["rolling_stability"],
        _ROLLING_STABILITY_KEYS,
        CandidateValidationProtocolError,
    )
    prospective = _require_object(
        payload["prospective_oos"],
        _PROSPECTIVE_OOS_KEYS,
        CandidateValidationProtocolError,
    )
    try:
        protocol = CandidateValidationProtocol(
            schema_version=payload["schema_version"],
            protocol_id=payload["protocol_id"],
            research_only=payload["research_only"],
            candidate_frozen_at=datetime.fromisoformat(payload["candidate_frozen_at"]),
            retrospective_since=date.fromisoformat(retrospective["since"]),
            retrospective_through=date.fromisoformat(retrospective["through"]),
            reference_months=rolling["reference_months"],
            test_months=rolling["test_months"],
            step_months=rolling["step_months"],
            first_test_since=date.fromisoformat(rolling["first_test_since"]),
            last_test_through=date.fromisoformat(rolling["last_test_through"]),
            prospective_oos_first_trading_day=date.fromisoformat(
                prospective["first_trading_day"]
            ),
            horizons_bars=tuple(payload["horizons_bars"]),
        )
    except (TypeError, ValueError):
        raise CandidateValidationProtocolError() from None
    if path.stem != protocol.protocol_id:
        raise CandidateValidationProtocolError()
    return protocol


def _require_exact_keys(
    payload: dict[str, Any],
    expected_keys: frozenset[str],
    error_type: type[_ContractError],
) -> None:
    if frozenset(payload) != expected_keys:
        raise error_type()


def _require_object(
    value: object,
    expected_keys: frozenset[str],
    error_type: type[_ContractError],
) -> dict[str, Any]:
    if type(value) is not dict:
        raise error_type()
    _require_exact_keys(value, expected_keys, error_type)
    return value


def _verify_digest(
    raw: bytes,
    expected_digest: str,
    error_type: type[_ContractError],
) -> None:
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise error_type()


def _is_nonempty_string(value: object) -> bool:
    return type(value) is str and bool(value)


def _is_exact_date(value: object) -> bool:
    return type(value) is date


def _is_positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _are_strictly_increasing_positive_ints(values: tuple[int, ...]) -> bool:
    return (
        bool(values)
        and all(_is_positive_int(value) for value in values)
        and values == tuple(sorted(set(values)))
    )
