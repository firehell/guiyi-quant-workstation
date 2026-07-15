from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

PASSED_ONLY_POLICY = "passed_only"
ACTIVE_ENTRY_POLICY = "active_entry"

DISPOSITION_RANK: dict[str, int] = {
    "active_passed": 0,
    "accepted_warning": 1,
    "duplicate_version_requires_review": 2,
    "not_applicable": 3,
    "metadata_mismatch_requires_review": 8,
    "checksum_mismatch_requires_review": 9,
    "orphan_requires_disposition": 9,
    "failed_requires_redownload": 10,
    "unclassified": 10,
    "": 5,
}

DATE_TOKEN_RE = re.compile(r"(20\d{6})")


@dataclass(frozen=True)
class GroupKey:
    instrument_symbol: str
    contract_code: str
    period: str

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.instrument_symbol, self.contract_code, self.period)


@dataclass
class CandidateEvidence:
    market_data_file_id: int
    instrument_symbol: str
    contract_code: str
    period: str
    contract_role: str
    data_version: str
    file_path: str
    quality_status: str
    provider: str
    data_role: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    row_count: int | None = None
    disposition: str = ""
    checksum_status: str = ""
    physical_exists: bool = True
    sealing_db_file_id: int | None = None
    duplicate_disposition: str = ""
    canonical_file_id_hint: int | None = None
    metadata_passed: bool = True
    source_interval_verified: bool = False
    is_duplicate_path_member: bool = False

    def group_key(self) -> GroupKey:
        return GroupKey(self.instrument_symbol, self.contract_code, self.period)


@dataclass(frozen=True)
class ProfileRuleContext:
    profile_id: str
    periods: tuple[str, ...]
    contract_roles: tuple[str, ...]
    quality_policy: str
    provider: str
    excluded_path_fragments: tuple[str, ...] = ()
    frozen_baseline_suffix: str | None = None


@dataclass
class ClassifiedCandidate:
    profile_id: str
    instrument_symbol: str
    contract_code: str
    period: str
    contract_role: str
    candidate_status: str
    market_data_file_id: int | None
    data_version: str
    rulebook_rank: int
    block_reason: str = ""
    file_path: str = ""
    quality_status: str = ""
    disposition: str = ""
    evidence_source: str = ""


def infer_contract_role(contract_code: str) -> str:
    if contract_code.endswith(".MAIN"):
        return "dominant_main"
    return "actual_contract"


def _quality_allows(*, quality_policy: str, quality_status: str) -> bool:
    if quality_status == "failed":
        return False
    if quality_policy == PASSED_ONLY_POLICY:
        return quality_status == "passed"
    if quality_policy == ACTIVE_ENTRY_POLICY:
        return quality_status != "failed"
    return quality_status != "failed"


def _latest_date_token(data_version: str) -> int:
    tokens = [int(match) for match in DATE_TOKEN_RE.findall(data_version or "")]
    return max(tokens) if tokens else 0


def _rank_tuple(candidate: CandidateEvidence, *, profile: ProfileRuleContext) -> tuple[Any, ...]:
    disposition_rank = DISPOSITION_RANK.get(candidate.disposition, 5)
    sealing_ok = int(
        candidate.physical_exists
        and candidate.metadata_passed
        and candidate.checksum_status in {"", "checksum_matched"}
    )
    end_ts = candidate.end_time.timestamp() if candidate.end_time else 0.0
    start_ts = -(candidate.start_time.timestamp() if candidate.start_time else 0.0)
    has_v2 = 1 if "_v2" in (candidate.data_version or "") else 0
    date_token = _latest_date_token(candidate.data_version)
    canonical_path = 1 if "canonical/bars" in (candidate.file_path or "") else 0
    jm_v2_batch = 1 if "jm_v2" in (candidate.file_path or "") or "20260711_v2" in (candidate.data_version or "") else 0
    source_interval = 1 if candidate.source_interval_verified or candidate.period == "1m" else 0
    canonical_hint = 1 if candidate.canonical_file_id_hint == candidate.market_data_file_id else 0
    sealing_match = 1 if candidate.sealing_db_file_id == candidate.market_data_file_id else 0
    return (
        disposition_rank,
        -sealing_ok,
        -end_ts,
        start_ts,
        -has_v2,
        -date_token,
        -canonical_path,
        -jm_v2_batch,
        -source_interval,
        -canonical_hint,
        -sealing_match,
        -candidate.market_data_file_id,
    )


def evaluate_candidate_block(
    candidate: CandidateEvidence,
    *,
    profile: ProfileRuleContext,
) -> str | None:
    if not candidate.instrument_symbol or not candidate.contract_code or not candidate.period:
        return "empty_identity"
    if candidate.period not in profile.periods:
        return "period_not_allowed"
    if candidate.contract_role not in profile.contract_roles:
        return "contract_role_not_allowed"
    if candidate.provider != profile.provider:
        return "provider_mismatch"
    if candidate.data_role != "primary":
        return "data_role_not_primary"
    if not _quality_allows(quality_policy=profile.quality_policy, quality_status=candidate.quality_status):
        return "quality_policy_violation"
    if not candidate.physical_exists:
        return "missing_physical_file"
    if candidate.checksum_status == "checksum_mismatch":
        return "checksum_mismatch"
    if candidate.disposition == "checksum_mismatch_requires_review":
        return "checksum_mismatch_requires_review"
    if candidate.disposition == "metadata_mismatch_requires_review":
        return "metadata_mismatch_requires_review"
    for fragment in profile.excluded_path_fragments:
        if fragment and fragment in (candidate.file_path or ""):
            return "excluded_path"
    if (
        profile.frozen_baseline_suffix
        and (candidate.data_version or "").endswith(profile.frozen_baseline_suffix)
    ):
        return "frozen_baseline_reference"
    if candidate.is_duplicate_path_member and candidate.canonical_file_id_hint is None:
        return "duplicate_path_ambiguous"
    if (
        candidate.is_duplicate_path_member
        and candidate.canonical_file_id_hint is not None
        and candidate.market_data_file_id != candidate.canonical_file_id_hint
    ):
        return "duplicate_path_non_canonical"
    return None


def classify_group_for_profile(
    candidates: list[CandidateEvidence],
    *,
    profile: ProfileRuleContext,
) -> list[ClassifiedCandidate]:
    if not candidates:
        return []

    group = candidates[0].group_key()
    contract_role = infer_contract_role(group.contract_code)
    results: list[ClassifiedCandidate] = []

    eligible: list[CandidateEvidence] = []
    for candidate in candidates:
        candidate.contract_role = contract_role
        block_reason = evaluate_candidate_block(candidate, profile=profile)
        if block_reason:
            results.append(
                ClassifiedCandidate(
                    profile_id=profile.profile_id,
                    instrument_symbol=group.instrument_symbol,
                    contract_code=group.contract_code,
                    period=group.period,
                    contract_role=contract_role,
                    candidate_status="blocked",
                    market_data_file_id=candidate.market_data_file_id,
                    data_version=candidate.data_version,
                    rulebook_rank=0,
                    block_reason=block_reason,
                    file_path=candidate.file_path,
                    quality_status=candidate.quality_status,
                    disposition=candidate.disposition,
                    evidence_source="rulebook",
                )
            )
        else:
            eligible.append(candidate)

    if not eligible:
        return results

    ranked = sorted(eligible, key=lambda item: _rank_tuple(item, profile=profile))
    for index, candidate in enumerate(ranked):
        results.append(
            ClassifiedCandidate(
                profile_id=profile.profile_id,
                instrument_symbol=group.instrument_symbol,
                contract_code=group.contract_code,
                period=group.period,
                contract_role=contract_role,
                candidate_status="current" if index == 0 else "excluded",
                market_data_file_id=candidate.market_data_file_id,
                data_version=candidate.data_version,
                rulebook_rank=index + 1,
                file_path=candidate.file_path,
                quality_status=candidate.quality_status,
                disposition=candidate.disposition,
                evidence_source="rulebook",
            )
        )
    return results


def classify_identity_groups(
    grouped_candidates: dict[GroupKey, list[CandidateEvidence]],
    *,
    profile: ProfileRuleContext,
) -> list[ClassifiedCandidate]:
    rows: list[ClassifiedCandidate] = []
    for group_key in sorted(grouped_candidates, key=lambda item: item.as_tuple()):
        rows.extend(classify_group_for_profile(grouped_candidates[group_key], profile=profile))
    return rows


__all__ = [
    "CandidateEvidence",
    "ClassifiedCandidate",
    "GroupKey",
    "ProfileRuleContext",
    "classify_group_for_profile",
    "classify_identity_groups",
    "evaluate_candidate_block",
    "infer_contract_role",
]
