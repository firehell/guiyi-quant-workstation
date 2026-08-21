from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.core.env import PROJECT_ROOT

from .exact_json_contract import load_exact_json as _load_exact
from .n_structure_policy import NStructurePolicyError, load_n_structure_policy


_CANDIDATE_PATH = (
    PROJECT_ROOT / "data/research_candidates/n_structure_5m_candidate_v1.json"
)
_PROTOCOL_PATH = PROJECT_ROOT / "data/research_protocols/n_structure_validation_v1.json"
_CANDIDATE_ID = "n_structure_5m_candidate_v1"
_SOURCE_KIND = "n_structure"
_POLICY_ID = "n_structure_5m_v1"
_FORMULA_VERSION = "n_structure_v1"
_PROTOCOL_ID = "n_structure_validation_v1"
_FROZEN_AT = datetime.fromisoformat("2026-08-20T00:22:00+08:00")
_RETROSPECTIVE_SINCE = date(2023, 1, 1)
_RETROSPECTIVE_THROUGH = date(2026, 8, 19)
_EMBARGO_TRADING_DAYS = (date(2026, 8, 20),)
_FIRST_TEST_SINCE = date(2024, 1, 1)
_LAST_TEST_THROUGH = date(2026, 6, 30)
_PROSPECTIVE_FIRST_TRADING_DAY = date(2026, 8, 21)
_HORIZONS = (3, 5, 8)
_EXPECTED_CANDIDATE: dict[str, Any] = {
    "schema_version": 1,
    "candidate_id": _CANDIDATE_ID,
    "source_kind": _SOURCE_KIND,
    "policy_id": _POLICY_ID,
    "formula_version": _FORMULA_VERSION,
    "research_only": True,
}
_EXPECTED_PROTOCOL: dict[str, Any] = {
    "schema_version": 1,
    "protocol_id": _PROTOCOL_ID,
    "research_only": True,
    "candidate_frozen_at": "2026-08-20T00:22:00+08:00",
    "retrospective": {
        "since": "2023-01-01",
        "through": "2026-08-19",
    },
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


class NCandidateManifestError(ValueError):
    code = "N_CANDIDATE_MANIFEST_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class NCandidateValidationProtocolError(ValueError):
    code = "N_CANDIDATE_PROTOCOL_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class NCandidateManifest:
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
            or self.candidate_id != _CANDIDATE_ID
            or self.source_kind != _SOURCE_KIND
            or self.policy_id != _POLICY_ID
            or self.formula_version != _FORMULA_VERSION
            or self.research_only is not True
        ):
            raise NCandidateManifestError()


@dataclass(frozen=True, slots=True)
class NCandidateValidationProtocol:
    schema_version: int
    protocol_id: str
    research_only: bool
    candidate_frozen_at: datetime
    retrospective_since: date
    retrospective_through: date
    embargo_trading_days: tuple[date, ...]
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
            or self.protocol_id != _PROTOCOL_ID
            or self.research_only is not True
            or type(self.candidate_frozen_at) is not datetime
            or self.candidate_frozen_at != _FROZEN_AT
            or type(self.retrospective_since) is not date
            or self.retrospective_since != _RETROSPECTIVE_SINCE
            or type(self.retrospective_through) is not date
            or self.retrospective_through != _RETROSPECTIVE_THROUGH
            or self.embargo_trading_days != _EMBARGO_TRADING_DAYS
            or type(self.reference_months) is not int
            or self.reference_months != 12
            or type(self.test_months) is not int
            or self.test_months != 3
            or type(self.step_months) is not int
            or self.step_months != 3
            or type(self.first_test_since) is not date
            or self.first_test_since != _FIRST_TEST_SINCE
            or type(self.last_test_through) is not date
            or self.last_test_through != _LAST_TEST_THROUGH
            or type(self.prospective_oos_first_trading_day) is not date
            or self.prospective_oos_first_trading_day != _PROSPECTIVE_FIRST_TRADING_DAY
            or self.horizons_bars != _HORIZONS
        ):
            raise NCandidateValidationProtocolError()


def load_n_candidate_manifest(path: Path | None = None) -> NCandidateManifest:
    payload = _load_exact(
        path if path is not None else _CANDIDATE_PATH,
        _EXPECTED_CANDIDATE,
        NCandidateManifestError,
    )
    try:
        policy = load_n_structure_policy()
    except NStructurePolicyError:
        raise NCandidateManifestError() from None
    if (
        policy.policy_id != payload["policy_id"]
        or policy.formula_version != payload["formula_version"]
        or policy.research_only is not True
    ):
        raise NCandidateManifestError()
    return NCandidateManifest(
        schema_version=payload["schema_version"],
        candidate_id=payload["candidate_id"],
        source_kind=payload["source_kind"],
        policy_id=payload["policy_id"],
        formula_version=payload["formula_version"],
        research_only=payload["research_only"],
    )


def load_n_candidate_validation_protocol(
    path: Path | None = None,
) -> NCandidateValidationProtocol:
    payload = _load_exact(
        path if path is not None else _PROTOCOL_PATH,
        _EXPECTED_PROTOCOL,
        NCandidateValidationProtocolError,
    )
    return NCandidateValidationProtocol(
        schema_version=payload["schema_version"],
        protocol_id=payload["protocol_id"],
        research_only=payload["research_only"],
        candidate_frozen_at=datetime.fromisoformat(payload["candidate_frozen_at"]),
        retrospective_since=date.fromisoformat(payload["retrospective"]["since"]),
        retrospective_through=date.fromisoformat(payload["retrospective"]["through"]),
        embargo_trading_days=tuple(
            date.fromisoformat(value) for value in payload["embargo_trading_days"]
        ),
        reference_months=payload["rolling_stability"]["reference_months"],
        test_months=payload["rolling_stability"]["test_months"],
        step_months=payload["rolling_stability"]["step_months"],
        first_test_since=date.fromisoformat(
            payload["rolling_stability"]["first_test_since"]
        ),
        last_test_through=date.fromisoformat(
            payload["rolling_stability"]["last_test_through"]
        ),
        prospective_oos_first_trading_day=date.fromisoformat(
            payload["prospective_oos"]["first_trading_day"]
        ),
        horizons_bars=tuple(payload["horizons_bars"]),
    )
