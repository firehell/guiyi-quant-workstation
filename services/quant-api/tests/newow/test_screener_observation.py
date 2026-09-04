from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from guiyi_quant.newow import CupHandleState, TrendBandState
from guiyi_quant.newow.screener_observation import (
    CUP_HANDLE_CANDIDATE_V1,
    LEGACY_HOMEPAGE_FILTER_V3282,
    MAINRISE_BUILD_CANDIDATE_V1,
    TREND_BUILD_CANDIDATE_V1,
    CandidateTransitionFacts,
    CupCandidateFacts,
    LegacyFilterId,
    LegacyHomepageStockFacts,
    ScreenerProbeObservation,
    ScreenerRowFacts,
    ScreenerStrategyId,
    compare_screener_observations,
    evaluate_cup_handle_candidate,
    evaluate_mainrise_build_candidate,
    evaluate_trend_build_candidate,
    infer_page_exact_screener_rule,
    observed_legacy_filter_v3_2_82,
)


GOLDEN = Path(__file__).parent / "golden" / "newow_v3_2_82_screener_observations.json"
SCREENER_PAGE_SHA256 = "ccbccc7e02c47f0dc475686d348394980f3b9a5aaa52bc8bf7f949bc10728e72"


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _typed_observation(payload: dict[str, object]) -> ScreenerProbeObservation:
    rows = tuple(ScreenerRowFacts.from_mapping(row) for row in payload["ordered_rows"])
    return ScreenerProbeObservation(
        strategy_id=ScreenerStrategyId(payload["strategy_id"]),
        captured_at=datetime.fromisoformat(payload["captured_at"]),
        request_identity=_sha(payload["request"]),
        response_sha256=payload["response_sha256"],
        product_version="v3.2.82",
        page_asset_sha256=SCREENER_PAGE_SHA256,
        ordered_symbols=tuple(row.symbol for row in rows),
        rows=rows,
    )


def _first_frozen_observation() -> ScreenerProbeObservation:
    payload = json.loads(GOLDEN.read_text(encoding="utf-8"))["observations"][0]
    return _typed_observation(payload)


def _observation(
    symbols: tuple[str, ...],
    *,
    day: int,
    response_char: str,
    page_char: str = "a",
    matching_rule_ids: tuple[str, ...] = (),
) -> ScreenerProbeObservation:
    rows = tuple(
        ScreenerRowFacts.from_mapping(
            {
                "code": symbol,
                "signalDaily": "hold",
                "crossDaily": None,
            }
        )
        for symbol in symbols
    )
    return ScreenerProbeObservation(
        strategy_id=ScreenerStrategyId.TREND_BUILD,
        captured_at=datetime(2026, 9, day, 13, tzinfo=UTC),
        request_identity="b" * 64,
        response_sha256=response_char * 64,
        product_version="v3.2.82",
        page_asset_sha256=page_char * 64,
        ordered_symbols=symbols,
        rows=rows,
        matching_rule_ids=matching_rule_ids,
    )


def test_frozen_first_snapshot_is_typed_without_claiming_formula() -> None:
    frozen = json.loads(GOLDEN.read_text(encoding="utf-8"))
    observation = _first_frozen_observation()
    assert frozen["evidence_gate"] == {
        "status": "UNKNOWN",
        "independent_snapshot_count": 1,
        "required_independent_snapshot_count": 2,
        "second_snapshot": "NOT_AVAILABLE_NO_HISTORICAL_AS_OF_CONTRACT",
        "page_exact_identity_allowed": False,
    }
    assert observation.strategy_id is ScreenerStrategyId.TREND_BUILD
    assert len(observation.rows) == 40
    assert observation.ordered_symbols[0] == "301171.SZ"
    assert observation.matching_rule_ids == ()


def test_all_six_frozen_strategy_snapshots_preserve_full_counts() -> None:
    frozen = json.loads(GOLDEN.read_text(encoding="utf-8"))
    observations = tuple(_typed_observation(item) for item in frozen["observations"])
    assert {item.strategy_id: len(item.rows) for item in observations} == {
        ScreenerStrategyId.TREND_BUILD: 40,
        ScreenerStrategyId.MAINRISE_BUILD: 3,
        ScreenerStrategyId.CUP_HANDLE: 27,
        ScreenerStrategyId.DAILY_BUY: 21,
        ScreenerStrategyId.WEEKLY_BUY: 21,
        ScreenerStrategyId.OSCILLATION_BUILD: 1,
    }
    assert all(item.matching_rule_ids == () for item in observations)


def test_page_exact_factory_rejects_one_snapshot_or_non_unique_rule() -> None:
    one = _first_frozen_observation()
    with pytest.raises(ValueError, match="NEWOW_SCREENER_EVIDENCE_INSUFFICIENT"):
        infer_page_exact_screener_rule((one,))

    observations = (
        _observation(
            ("600519.SH",),
            day=4,
            response_char="c",
            matching_rule_ids=("yellow_holding", "recent_build"),
        ),
        _observation(
            ("600519.SH", "000651.SZ"),
            day=5,
            response_char="d",
            matching_rule_ids=("yellow_holding", "recent_build"),
        ),
    )
    with pytest.raises(ValueError, match="NEWOW_SCREENER_EVIDENCE_INSUFFICIENT"):
        infer_page_exact_screener_rule(observations)


def test_page_exact_factory_requires_distinct_dates_hashes_and_asset_version() -> None:
    left = _observation(
        ("600519.SH",), day=4, response_char="c", matching_rule_ids=("only",)
    )
    assert infer_page_exact_screener_rule(
        (left, replace(left, captured_at=left.captured_at + timedelta(days=1), response_sha256="d" * 64))
    ).rule_id == "only"

    with pytest.raises(ValueError, match="NEWOW_SCREENER_EVIDENCE_INSUFFICIENT"):
        infer_page_exact_screener_rule(
            (left, replace(left, captured_at=left.captured_at + timedelta(hours=1), response_sha256="d" * 64))
        )
    with pytest.raises(ValueError, match="NEWOW_SCREENER_EVIDENCE_INSUFFICIENT"):
        infer_page_exact_screener_rule(
            (left, replace(left, captured_at=left.captured_at + timedelta(days=1)))
        )
    with pytest.raises(ValueError, match="NEWOW_SCREENER_EVIDENCE_INSUFFICIENT"):
        infer_page_exact_screener_rule(
            (
                left,
                replace(
                    left,
                    captured_at=left.captured_at + timedelta(days=1),
                    response_sha256="d" * 64,
                    page_asset_sha256="e" * 64,
                ),
            )
        )


def test_observation_rejects_bad_hash_naive_timestamp_duplicate_or_order_drift() -> None:
    valid = _observation(("600519.SH", "000651.SZ"), day=4, response_char="c")
    with pytest.raises(ValueError, match="NEWOW_SCREENER_OBSERVATION_INVALID"):
        replace(valid, response_sha256="not-a-hash")
    with pytest.raises(ValueError, match="NEWOW_SCREENER_OBSERVATION_INVALID"):
        replace(valid, captured_at=valid.captured_at.replace(tzinfo=None))
    with pytest.raises(ValueError, match="NEWOW_SCREENER_OBSERVATION_INVALID"):
        replace(valid, ordered_symbols=("600519.SH", "600519.SH"))
    with pytest.raises(ValueError, match="NEWOW_SCREENER_OBSERVATION_INVALID"):
        replace(valid, ordered_symbols=tuple(reversed(valid.ordered_symbols)))
    with pytest.raises(ValueError, match="NEWOW_SCREENER_OBSERVATION_INVALID"):
        replace(valid, captured_at="not-a-datetime")  # type: ignore[arg-type]


def test_row_rejects_nested_or_non_finite_values() -> None:
    with pytest.raises(ValueError, match="NEWOW_SCREENER_ROW_INVALID"):
        ScreenerRowFacts.from_mapping({"code": "600519.SH", "nested": {}})
    with pytest.raises(ValueError, match="NEWOW_SCREENER_ROW_INVALID"):
        ScreenerRowFacts.from_mapping({"code": "600519.SH", "price": float("nan")})


def test_row_preserves_missing_separately_from_explicit_null() -> None:
    missing = ScreenerRowFacts.from_mapping({"code": "600519.SH"})
    explicit_null = ScreenerRowFacts.from_mapping(
        {"code": "600519.SH", "crossWeekly": None}
    )
    assert missing.has_field("crossWeekly") is False
    assert explicit_null.has_field("crossWeekly") is True
    assert explicit_null.value("crossWeekly") is None


def test_comparison_preserves_order_and_reports_jaccard_fields_and_version() -> None:
    left = _observation(
        ("600519.SH", "000651.SZ", "300750.SZ"),
        day=4,
        response_char="c",
    )
    right = _observation(
        ("000651.SZ", "600519.SH", "002594.SZ"),
        day=5,
        response_char="d",
        page_char="e",
    )
    comparison = compare_screener_observations(left, right)
    assert comparison.intersection == ("600519.SH", "000651.SZ")
    assert comparison.only_left == ("300750.SZ",)
    assert comparison.only_right == ("002594.SZ",)
    assert comparison.jaccard == Decimal("0.500000")
    assert comparison.stable_field_names == ("code", "crossDaily", "signalDaily")
    assert comparison.intersection_order_stable is False
    assert comparison.page_asset_changed is True


@pytest.mark.parametrize(
    ("rule_id", "expected"),
    (
        (LegacyFilterId.YIJIAN_SAN_DIAO, False),
        (LegacyFilterId.DAILY_BUY, True),
        (LegacyFilterId.WEEKLY_BUY, False),
        (LegacyFilterId.HOT_STRONG, True),
        (LegacyFilterId.START_CONTROL, False),
        (LegacyFilterId.DAILY_ACCUM, True),
        (LegacyFilterId.WEEKLY_ACCUM, False),
        (LegacyFilterId.WAVE_ENTRY, True),
        (LegacyFilterId.TREND_MASTER, True),
    ),
)
def test_nine_legacy_homepage_filters_remain_a_separate_surface(
    rule_id: LegacyFilterId, expected: bool
) -> None:
    facts = LegacyHomepageStockFacts(
        symbol="600519.SH",
        signal_daily="buy",
        signal_weekly="hold",
        trend="bull",
        change_pct=Decimal("3.2"),
    )
    result = observed_legacy_filter_v3_2_82(rule_id, facts)
    assert result.matched is expected
    assert result.surface == "legacy_homepage"
    assert result.formula_version == LEGACY_HOMEPAGE_FILTER_V3282
    assert "screener" not in result.formula_version


def test_three_cleanroom_candidates_have_lineage_without_page_parity() -> None:
    now = datetime(2026, 9, 4, tzinfo=UTC)
    trend = evaluate_trend_build_candidate(
        CandidateTransitionFacts(
            state=TrendBandState.YELLOW,
            latest_build_at=now,
            latest_clear_at=now - timedelta(days=1),
            physical_contract="RB2610",
            segment_id="rb:RB2610:2026",
            formula_version="newow_trend_band_page_v2",
        )
    )
    mainrise = evaluate_mainrise_build_candidate(
        CandidateTransitionFacts(
            state=TrendBandState.YELLOW,
            latest_build_at=now,
            latest_clear_at=None,
            physical_contract="RB2610",
            segment_id="rb:RB2610:2026",
            formula_version="newow_main_rise_ma35_ma45_page_v1",
        )
    )
    cup = evaluate_cup_handle_candidate(
        CupCandidateFacts(
            state=CupHandleState.READY,
            hard_failures=(),
            physical_contract="RB2610",
            segment_id="rb:RB2610:2026",
            formula_version="newow_cup_handle_v1",
        )
    )
    assert (trend.identity, mainrise.identity, cup.identity) == (
        TREND_BUILD_CANDIDATE_V1,
        MAINRISE_BUILD_CANDIDATE_V1,
        CUP_HANDLE_CANDIDATE_V1,
    )
    assert all(result.matched for result in (trend, mainrise, cup))
    assert all(result.page_parity is False for result in (trend, mainrise, cup))
    assert all(result.formula_lineage for result in (trend, mainrise, cup))
    assert all(result.evidence_note == "private_server_logic_unverified" for result in (trend, mainrise, cup))


def test_cleanroom_candidates_reject_cross_segment_or_stale_build() -> None:
    now = datetime(2026, 9, 4, tzinfo=UTC)
    stale = CandidateTransitionFacts(
        state=TrendBandState.YELLOW,
        latest_build_at=now - timedelta(days=2),
        latest_clear_at=now - timedelta(days=1),
        physical_contract="SC2302",
        segment_id="sc:SC2302:owner",
        formula_version="newow_trend_band_page_v2",
    )
    assert evaluate_trend_build_candidate(stale).matched is False
    with pytest.raises(ValueError, match="NEWOW_SCREENER_CANDIDATE_FACTS_INVALID"):
        CandidateTransitionFacts(
            state=TrendBandState.YELLOW,
            latest_build_at=now,
            latest_clear_at=None,
            physical_contract="SC2302",
            segment_id="",
            formula_version="newow_trend_band_page_v2",
        )
