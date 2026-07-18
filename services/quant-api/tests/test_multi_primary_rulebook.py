from __future__ import annotations

from datetime import UTC, date, datetime

from app.services.multi_primary_rulebook import (
    CandidateEvidence,
    ProfileRuleContext,
    classify_group_for_profile,
    evaluate_candidate_block,
)
from app.services.profile_target_resolver import ProfileTargetRange, ProfileTargetWindow


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
        "checksum": "a" * 64,
        "lineage_verified": True,
    }
    base.update(overrides)
    return CandidateEvidence(**base)  # type: ignore[arg-type]


def _target(*, start: datetime, end: datetime, lineage_required: bool = False) -> ProfileTargetWindow:
    return ProfileTargetWindow(
        profile_id="intraday_research_v1",
        product="jm",
        contract="jm.MAIN",
        period="1d",
        contract_role="dominant_main",
        ranges=(ProfileTargetRange(start.date(), end.date(), "test"),),
        target_start=start.date(),
        target_end=end.date(),
        lineage_required=lineage_required,
        source="test",
    )


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
        end_time=datetime(2026, 7, 10, tzinfo=UTC),
        disposition="duplicate_version_requires_review",
        sealing_db_file_id=50,
    )
    rows = classify_group_for_profile(
        [loser, winner],
        profile=_profile(),
        target=_target(
            start=datetime(2023, 1, 3, tzinfo=UTC),
            end=datetime(2026, 7, 10, tzinfo=UTC),
        ),
    )
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
        sealing_db_file_id=33719,
        is_duplicate_path_member=True,
        canonical_file_id_hint=34059,
    )
    reason = evaluate_candidate_block(candidate, profile=_profile())
    assert reason == "duplicate_path_non_canonical"


def test_missing_physical_is_blocked() -> None:
    candidate = _candidate(physical_exists=False)
    reason = evaluate_candidate_block(candidate, profile=_profile())
    assert reason == "missing_physical_file"


def test_unverified_checksum_is_blocked() -> None:
    candidate = _candidate(checksum_status="")
    reason = evaluate_candidate_block(candidate, profile=_profile())
    assert reason == "checksum_not_verified"


def test_missing_sealing_match_is_blocked() -> None:
    candidate = _candidate(sealing_db_file_id=None)
    reason = evaluate_candidate_block(candidate, profile=_profile())
    assert reason == "sealing_unverified"


def test_frozen_baseline_reference_is_blocked() -> None:
    candidate = _candidate(data_version="rqdata_jm_1d_20260707_v2")
    profile = _profile(frozen_baseline_suffix="20260707_v2")
    reason = evaluate_candidate_block(candidate, profile=profile)
    assert reason == "frozen_baseline_reference"


def test_provider_earliest_target_blocks_narrow_window() -> None:
    narrow = _candidate(start_time=datetime(2023, 1, 3, tzinfo=UTC))
    rows = classify_group_for_profile(
        [narrow],
        profile=_profile(),
        target=_target(
            start=datetime(2010, 1, 4, tzinfo=UTC),
            end=datetime(2026, 7, 10, tzinfo=UTC),
        ),
    )
    assert rows[0].candidate_status == "blocked"
    assert rows[0].block_reason == "target_coverage_incomplete"
    assert rows[0].covers_target is False


def test_wider_start_does_not_win_when_both_cover_target() -> None:
    wider = _candidate(
        market_data_file_id=10,
        start_time=datetime(2010, 1, 4, tzinfo=UTC),
        data_version="wide_20260710_v1",
        sealing_db_file_id=99,
    )
    target_scoped = _candidate(
        market_data_file_id=99,
        start_time=datetime(2023, 1, 3, tzinfo=UTC),
        data_version="target_20260710_v2",
        sealing_db_file_id=99,
    )
    rows = classify_group_for_profile(
        [wider, target_scoped],
        profile=_profile(),
        target=_target(
            start=datetime(2023, 1, 3, tzinfo=UTC),
            end=datetime(2026, 7, 10, tzinfo=UTC),
        ),
    )
    current = next(row for row in rows if row.candidate_status == "current")
    assert current.market_data_file_id == 99
    assert current.selection_reason == "covers_target_canonical_current"


def test_lineage_required_blocks_unverified_derived_candidate() -> None:
    derived = _candidate(period="5m", lineage_verified=False)
    rows = classify_group_for_profile(
        [derived],
        profile=_profile(),
        target=ProfileTargetWindow(
            profile_id="intraday_research_v1",
            product="jm",
            contract="jm.MAIN",
            period="5m",
            contract_role="dominant_main",
            ranges=(ProfileTargetRange(date(2023, 1, 3), date(2026, 7, 10), "test"),),
            target_start=date(2023, 1, 3),
            target_end=date(2026, 7, 10),
            lineage_required=True,
            source="test",
        ),
    )
    assert rows[0].block_reason == "lineage_unverified"


def test_conflicting_top_tier_checksums_fail_closed() -> None:
    first = _candidate(market_data_file_id=1, checksum="a" * 64, sealing_db_file_id=1)
    second = _candidate(market_data_file_id=2, checksum="b" * 64, sealing_db_file_id=2)
    rows = classify_group_for_profile(
        [first, second],
        profile=_profile(),
        target=_target(
            start=datetime(2023, 1, 3, tzinfo=UTC),
            end=datetime(2026, 7, 10, tzinfo=UTC),
        ),
    )
    assert {row.candidate_status for row in rows} == {"blocked"}
    assert {row.block_reason for row in rows} == {"conflicting_duplicate_candidates"}
