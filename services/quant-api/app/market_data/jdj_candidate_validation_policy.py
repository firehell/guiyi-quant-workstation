from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from app.core.env import PROJECT_ROOT

from .jdj_policy import (
    JdjPolicyError,
    is_exact_jdj_policy,
    load_jdj_policy,
)


_SOURCE_KIND = "jdj_1m"
_POLICY_ID = "jdj_1m_policy_v1"
_FORMULA_VERSION = "jdj_1m_v1"
_PROTOCOL_ID = "jdj_candidate_validation_v1"
_EXPECTED_REFS = (
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
_EXPECTED_CANDIDATES: Mapping[str, dict[str, Any]] = MappingProxyType(
    {
        candidate_id: {
            "schema_version": 1,
            "candidate_id": candidate_id,
            "source_kind": _SOURCE_KIND,
            "policy_id": _POLICY_ID,
            "formula_version": _FORMULA_VERSION,
            "research_only": True,
        }
        for candidate_id, _event_kind in _EXPECTED_REFS
    }
)
_CANDIDATE_PATHS: Mapping[str, Path] = MappingProxyType(
    {
        candidate_id: (
            PROJECT_ROOT / f"data/research_candidates/{candidate_id}.json"
        )
        for candidate_id, _event_kind in _EXPECTED_REFS
    }
)
_PROTOCOL_PATH = (
    PROJECT_ROOT / "data/research_protocols/jdj_candidate_validation_v1.json"
)
_EXPECTED_PROTOCOL: dict[str, Any] = {
    "schema_version": 1,
    "protocol_id": _PROTOCOL_ID,
    "research_only": True,
    "candidates": [
        {"candidate_id": candidate_id, "source_event_kind": event_kind}
        for candidate_id, event_kind in _EXPECTED_REFS
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
_FROZEN_AT = datetime.fromisoformat("2026-08-21T09:34:00+08:00")
_RETROSPECTIVE_SINCE = date(2023, 1, 1)
_RETROSPECTIVE_THROUGH = date(2026, 8, 20)
_EMBARGO_TRADING_DAYS = (date(2026, 8, 21),)
_FIRST_TEST_SINCE = date(2024, 1, 1)
_LAST_TEST_THROUGH = date(2026, 6, 30)
_PROSPECTIVE_FIRST_TRADING_DAY = date(2026, 8, 24)
_BASELINE_REQUEST_THROUGH = date(2026, 8, 21)
_HORIZONS = (3, 5, 8, 20)


class JdjCandidateManifestError(ValueError):
    code = "JDJ_CANDIDATE_MANIFEST_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class JdjCandidateValidationProtocolError(ValueError):
    code = "JDJ_CANDIDATE_PROTOCOL_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class JdjCandidateManifest:
    schema_version: int
    candidate_id: str
    source_kind: str
    policy_id: str
    formula_version: str
    research_only: bool

    def __post_init__(self) -> None:
        expected = _EXPECTED_CANDIDATES.get(self.candidate_id)
        if expected is None or not _matches_exact(
            {
                "schema_version": self.schema_version,
                "candidate_id": self.candidate_id,
                "source_kind": self.source_kind,
                "policy_id": self.policy_id,
                "formula_version": self.formula_version,
                "research_only": self.research_only,
            },
            expected,
        ):
            raise JdjCandidateManifestError()


@dataclass(frozen=True, slots=True)
class JdjCandidateRef:
    candidate_id: str
    source_event_kind: str

    def __post_init__(self) -> None:
        if (
            type(self.candidate_id) is not str
            or type(self.source_event_kind) is not str
            or (self.candidate_id, self.source_event_kind) not in _EXPECTED_REFS
        ):
            raise JdjCandidateValidationProtocolError()


@dataclass(frozen=True, slots=True)
class JdjCandidateValidationProtocol:
    schema_version: int
    protocol_id: str
    research_only: bool
    candidates: tuple[JdjCandidateRef, ...]
    candidate_frozen_at: datetime
    anchor_symbol: str
    retrospective_since: date
    retrospective_through: date
    embargo_trading_days: tuple[date, ...]
    reference_months: int
    test_months: int
    step_months: int
    first_test_since: date
    last_test_through: date
    prospective_oos_first_trading_day: date
    baseline_request_through: date
    horizons_bars: tuple[int, ...]
    automatic_ranking: bool
    automatic_promotion: bool

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or type(self.protocol_id) is not str
            or self.protocol_id != _PROTOCOL_ID
            or type(self.research_only) is not bool
            or self.research_only is not True
            or type(self.candidates) is not tuple
            or tuple(
                (item.candidate_id, item.source_event_kind)
                for item in self.candidates
            )
            != _EXPECTED_REFS
            or type(self.candidate_frozen_at) is not datetime
            or self.candidate_frozen_at != _FROZEN_AT
            or type(self.anchor_symbol) is not str
            or self.anchor_symbol != "jm"
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
            or self.prospective_oos_first_trading_day
            != _PROSPECTIVE_FIRST_TRADING_DAY
            or type(self.baseline_request_through) is not date
            or self.baseline_request_through != _BASELINE_REQUEST_THROUGH
            or self.horizons_bars != _HORIZONS
            or type(self.automatic_ranking) is not bool
            or self.automatic_ranking is not False
            or type(self.automatic_promotion) is not bool
            or self.automatic_promotion is not False
        ):
            raise JdjCandidateValidationProtocolError()


def load_jdj_candidate_manifest(candidate_id: str) -> JdjCandidateManifest:
    if type(candidate_id) is not str:
        raise JdjCandidateManifestError()
    expected = _EXPECTED_CANDIDATES.get(candidate_id)
    path = _CANDIDATE_PATHS.get(candidate_id)
    if expected is None or path is None:
        raise JdjCandidateManifestError()

    payload = _load_exact(path, expected, JdjCandidateManifestError)
    try:
        policy = load_jdj_policy()
    except JdjPolicyError:
        raise JdjCandidateManifestError() from None
    if (
        not is_exact_jdj_policy(policy)
        or policy.policy_id != payload["policy_id"]
        or policy.formula_version != payload["formula_version"]
        or policy.research_only is not True
    ):
        raise JdjCandidateManifestError()

    return JdjCandidateManifest(
        schema_version=payload["schema_version"],
        candidate_id=payload["candidate_id"],
        source_kind=payload["source_kind"],
        policy_id=payload["policy_id"],
        formula_version=payload["formula_version"],
        research_only=payload["research_only"],
    )


def load_jdj_candidate_validation_protocol() -> JdjCandidateValidationProtocol:
    payload = _load_exact(
        _PROTOCOL_PATH,
        _EXPECTED_PROTOCOL,
        JdjCandidateValidationProtocolError,
    )
    try:
        manifests = tuple(
            load_jdj_candidate_manifest(item["candidate_id"])
            for item in payload["candidates"]
        )
    except JdjCandidateManifestError:
        raise JdjCandidateValidationProtocolError() from None
    if tuple(manifest.candidate_id for manifest in manifests) != tuple(
        item["candidate_id"] for item in payload["candidates"]
    ):
        raise JdjCandidateValidationProtocolError()

    return JdjCandidateValidationProtocol(
        schema_version=payload["schema_version"],
        protocol_id=payload["protocol_id"],
        research_only=payload["research_only"],
        candidates=tuple(
            JdjCandidateRef(
                candidate_id=item["candidate_id"],
                source_event_kind=item["source_event_kind"],
            )
            for item in payload["candidates"]
        ),
        candidate_frozen_at=datetime.fromisoformat(payload["candidate_frozen_at"]),
        anchor_symbol=payload["anchor_symbol"],
        retrospective_since=date.fromisoformat(payload["retrospective"]["since"]),
        retrospective_through=date.fromisoformat(
            payload["retrospective"]["through"]
        ),
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
        baseline_request_through=date.fromisoformat(
            payload["baseline_request_through"]
        ),
        horizons_bars=tuple(payload["horizons_bars"]),
        automatic_ranking=payload["automatic_ranking"],
        automatic_promotion=payload["automatic_promotion"],
    )


def _load_exact(
    path: Path,
    expected: dict[str, Any],
    error_type: type[ValueError],
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise error_type() from None
    if not _matches_exact(payload, expected):
        raise error_type()
    assert isinstance(payload, dict)
    return payload


def _matches_exact(value: object, expected: object) -> bool:
    if type(value) is not type(expected):
        return False
    if isinstance(expected, dict):
        return (
            isinstance(value, dict)
            and value.keys() == expected.keys()
            and all(
                _matches_exact(value[key], item)
                for key, item in expected.items()
            )
        )
    if isinstance(expected, list):
        return isinstance(value, list) and len(value) == len(expected) and all(
            _matches_exact(actual, item)
            for actual, item in zip(value, expected, strict=True)
        )
    return value == expected
