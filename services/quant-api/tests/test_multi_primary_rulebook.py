from __future__ import annotations

from datetime import UTC, datetime

from app.services.multi_primary_rulebook import (
    CandidateEvidence,
    ProfileRuleContext,
    classify_group_for_profile,
    evaluate_candidate_block,
)


def _profile(**overrides: object) -> ProfileRuleContext:
    base = {
        "profile_id": "intraday_research_v1",
        "periods": ("1d", "5m"),
        "contract_roles": ("dominant_main",),
        "quality_policy": "passed_only",
        "provider": "rqdata",
    }
    base.update(overrides)
    return ProfileRuleContext(**base)  # type: ignore[arg-type]


def _candidate(**overrides: object) -> CandidateEvidence:
    base = {
        "market_data_file_id": 1,
        "instrument_symbol": "jm",
        "contract_code": "jm.MAIN",
        "period": "1d",
        "contract_role": "dominant_main",
        "data_version": "20260711_v2",
        "file_path": "data/parquet/canonical/bars/jm_MAIN_1d.parquet",
        "quality_status": "passed",
        "provider": "rqdata",
        "data_role": "primary",
        "start_time": datetime(2023, 1, 3, tzinfo=UTC),
        "end_time": datetime(2026, 7, 10, tzinfo=UTC),
        "disposition": "active_passed",
        "checksum_status": "checksum_matched",
        "physical_exists": True,
        "sealing_db_file_id": 1,
    }
    base.update(overrides)
    return CandidateEvidence(**base)  # type: ignore[arg-type]


def test_classify_group_prefers_active_passed_and_wider_coverage() -> None:
    winner = _candidate(
        market_data_file_id=100,
        data_version="20260711_v2",
        end_time=datetime(2026, 7, 10, tzinfo=UTC),
        disposition="active_passed",
        sealing_db_file_id=100,
    )
    loser = _candidate(
        market_data_file_id=50,
        data_version="20260707_v1",
        end_time=datetime(2026, 7, 7, tzinfo=UTC),
        disposition="duplicate_version_requires_review",
        sealing_db_file_id=100,
    )
    rows = classify_group_for_profile([loser, winner], profile=_profile())
    current = [row for row in rows if row.candidate_status == "current"]
    excluded = [row for row in rows if row.candidate_status == "excluded"]
    assert len(current) == 1
    assert current[0].market_data_file_id == 100
    assert len(excluded) == 1
    assert excluded[0].market_data_file_id == 50


def test_warning_blocked_for_passed_only_profile() -> None:
    candidate = _candidate(quality_status="warning", disposition="accepted_warning")
    reason = evaluate_candidate_block(candidate, profile=_profile())
    assert reason == "quality_policy_violation"


def test_duplicate_non_canonical_is_blocked() -> None:
    candidate = _candidate(
        market_data_file_id=33719,
        is_duplicate_path_member=True,
        canonical_file_id_hint=34059,
    )
    reason = evaluate_candidate_block(candidate, profile=_profile())
    assert reason == "duplicate_path_non_canonical"


def test_missing_physical_is_blocked() -> None:
    candidate = _candidate(physical_exists=False)
    reason = evaluate_candidate_block(candidate, profile=_profile())
    assert reason == "missing_physical_file"


def test_frozen_baseline_reference_is_blocked() -> None:
    candidate = _candidate(data_version="rqdata_jm_1d_20260707_v2")
    profile = _profile(frozen_baseline_suffix="20260707_v2")
    reason = evaluate_candidate_block(candidate, profile=profile)
    assert reason == "frozen_baseline_reference"
