from __future__ import annotations

from datetime import UTC, date, datetime

from app.services.rqdata_ingest.full_history_contract import (
    ACTUAL_REQUIRED_PERIODS,
    V1_AUDIT_END,
    ActualRank1Range,
    ProviderEarliestEvidence,
    build_actual_rank1_targets,
    evaluate_profile_eligibility,
    report_mutation_allowed,
    resolve_consumer_decision,
    resolve_expected_window,
    resolve_first_completed_week,
)


def _provider_evidence(
    period: str,
    first_valid_bar: date,
    *,
    authoritative: bool = True,
    source_kind: str | None = None,
) -> ProviderEarliestEvidence:
    return ProviderEarliestEvidence(
        period=period,
        first_valid_bar=first_valid_bar,
        source_kind=source_kind or ("provider_earliest_snapshot" if authoritative else "canonical_manifest"),
        source_ref=f"evidence/{period}.json",
        provider="rqdata",
        data_version="v1",
        captured_at=datetime(2026, 7, 16, tzinfo=UTC),
        checksum="sha256:test",
        authoritative=authoritative,
        completed=True,
    )


def test_continuous_1m_uses_later_provider_first_valid_bar() -> None:
    window = resolve_expected_window(
        product="al",
        contract="al.MAIN",
        contract_role="dominant_main",
        period="1m",
        listed_semantic_start=date(1999, 1, 4),
        provider_evidence=_provider_evidence("1m", date(2010, 1, 4)),
        last_completed_trading_day=V1_AUDIT_END,
    )

    assert window.expected_start == date(2010, 1, 4)
    assert window.expected_end == V1_AUDIT_END
    assert window.resolution_status == "resolved"


def test_new_product_starts_at_first_valid_bar_after_listing() -> None:
    window = resolve_expected_window(
        product="jm",
        contract="jm.MAIN",
        contract_role="dominant_main",
        period="1m",
        listed_semantic_start=date(2013, 3, 22),
        provider_evidence=_provider_evidence("1m", date(2013, 3, 25)),
        last_completed_trading_day=V1_AUDIT_END,
    )

    assert window.expected_start == date(2013, 3, 25)


def test_direct_1d_may_start_before_1m() -> None:
    window = resolve_expected_window(
        product="al",
        contract="al.MAIN",
        contract_role="dominant_main",
        period="1d",
        listed_semantic_start=date(1999, 1, 4),
        provider_evidence=_provider_evidence("1d", date(2000, 1, 5)),
        last_completed_trading_day=V1_AUDIT_END,
    )

    assert window.expected_start == date(2000, 1, 5)
    assert window.source_role == "direct"


def test_physical_manifest_cannot_resolve_provider_earliest_even_if_flagged_authoritative() -> None:
    window = resolve_expected_window(
        product="al",
        contract="al.MAIN",
        contract_role="dominant_main",
        period="1w",
        listed_semantic_start=date(1999, 1, 4),
        provider_evidence=_provider_evidence(
            "1w",
            date(2000, 1, 7),
            authoritative=True,
            source_kind="canonical_manifest",
        ),
        last_completed_week=date(2026, 7, 10),
    )

    assert window.expected_start is None
    assert window.resolution_status == "expected_start_unresolved"


def test_first_completed_week_accepts_listing_week_provider_bar() -> None:
    result = resolve_first_completed_week(
        listed_semantic_start=date(2012, 5, 10),
        provider_first_weekly_bar=date(2012, 5, 11),
        trading_days=[date(2012, 5, 10), date(2012, 5, 11)],
        closed_through=date(2012, 5, 11),
        provider_authoritative=True,
        calendar_complete=True,
    )

    assert result == date(2012, 5, 11)


def test_first_completed_week_uses_last_trading_day_of_holiday_week() -> None:
    result = resolve_first_completed_week(
        listed_semantic_start=date(2026, 10, 12),
        provider_first_weekly_bar=date(2026, 10, 14),
        trading_days=[date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14)],
        closed_through=date(2026, 10, 14),
        provider_authoritative=True,
        calendar_complete=True,
    )

    assert result == date(2026, 10, 14)


def test_first_completed_week_fails_closed_for_incomplete_inputs() -> None:
    base = {
        "listed_semantic_start": date(2026, 7, 6),
        "provider_first_weekly_bar": date(2026, 7, 10),
        "trading_days": [date(2026, 7, 6), date(2026, 7, 7), date(2026, 7, 8), date(2026, 7, 9), date(2026, 7, 10)],
        "closed_through": date(2026, 7, 9),
        "provider_authoritative": True,
        "calendar_complete": True,
    }

    assert resolve_first_completed_week(**base) is None
    assert resolve_first_completed_week(**{**base, "closed_through": date(2026, 7, 10), "calendar_complete": False}) is None
    assert resolve_first_completed_week(**{**base, "closed_through": date(2026, 7, 10), "trading_days": []}) is None


def test_derived_period_inherits_passed_1m_window() -> None:
    source = resolve_expected_window(
        product="jm",
        contract="jm.MAIN",
        contract_role="dominant_main",
        period="1m",
        listed_semantic_start=date(2013, 3, 22),
        provider_evidence=_provider_evidence("1m", date(2013, 3, 22)),
        last_completed_trading_day=V1_AUDIT_END,
    )
    derived = resolve_expected_window(
        product="jm",
        contract="jm.MAIN",
        contract_role="dominant_main",
        period="15m",
        listed_semantic_start=date(2013, 3, 22),
        source_1m_window=source,
        source_1m_quality="passed",
        source_interval="1m",
    )

    assert derived.expected_start == source.expected_start
    assert derived.expected_end == source.expected_end
    assert derived.source_role == "derived_from_1m"


def test_derived_period_rejects_direct_or_non_passed_1m_lineage() -> None:
    source = resolve_expected_window(
        product="jm",
        contract="jm.MAIN",
        contract_role="dominant_main",
        period="1m",
        listed_semantic_start=date(2013, 3, 22),
        provider_evidence=_provider_evidence("1m", date(2013, 3, 22)),
        last_completed_trading_day=V1_AUDIT_END,
    )

    direct = resolve_expected_window(
        product="jm",
        contract="jm.MAIN",
        contract_role="dominant_main",
        period="15m",
        listed_semantic_start=date(2013, 3, 22),
        source_1m_window=source,
        source_1m_quality="passed",
        source_interval="15m",
    )
    warning = resolve_expected_window(
        product="jm",
        contract="jm.MAIN",
        contract_role="dominant_main",
        period="15m",
        listed_semantic_start=date(2013, 3, 22),
        source_1m_window=source,
        source_1m_quality="warning",
        source_interval="1m",
    )

    assert direct.resolution_status == "invalid_source_interval"
    assert warning.resolution_status == "source_1m_not_passed"


def test_actual_targets_only_cover_rank1_ranges_and_required_periods() -> None:
    rows = build_actual_rank1_targets(
        [
            ActualRank1Range(
                product="jm",
                contract="JM2609",
                start=date(2026, 7, 1),
                end=date(2026, 7, 15),
            )
        ]
    )

    assert {row.period for row in rows} == ACTUAL_REQUIRED_PERIODS
    assert {row.contract for row in rows} == {"JM2609"}
    assert {row.expected_start for row in rows} == {date(2026, 7, 1)}
    assert {row.expected_end for row in rows} == {V1_AUDIT_END}


def test_actual_targets_clip_to_supported_period_start_and_deduplicate() -> None:
    ranges = [
        ActualRank1Range(product="jm", contract="JM1305", start=date(2013, 3, 1), end=date(2013, 3, 25)),
        ActualRank1Range(product="jm", contract="JM1305", start=date(2013, 3, 1), end=date(2013, 3, 25)),
    ]

    rows = build_actual_rank1_targets(
        ranges,
        audit_end=date(2013, 3, 25),
        supported_starts={
            ("jm", "1m"): date(2013, 3, 22),
            ("jm", "1d"): date(2013, 3, 20),
        },
    )

    assert [(row.period, row.expected_start) for row in rows] == [
        ("1d", date(2013, 3, 20)),
        ("1m", date(2013, 3, 22)),
    ]


def test_actual_targets_omit_ranges_before_supported_period_start() -> None:
    rows = build_actual_rank1_targets(
        [ActualRank1Range(product="jm", contract="JM1305", start=date(2013, 3, 1), end=date(2013, 3, 10))],
        audit_end=date(2013, 3, 25),
        supported_starts={("jm", "1m"): date(2013, 3, 22), ("jm", "1d"): date(2013, 3, 20)},
    )

    assert rows == ()


def test_five_layer_state_computes_profile_eligibility_without_collapsing_layers() -> None:
    state = evaluate_profile_eligibility(
        physical_coverage="covered",
        registration="registered",
        quality="warning",
        reference_metadata="passed",
        identity_in_profile=True,
        quality_policy="active_entry",
        bar_status="confirmed",
    )

    assert state.physical_coverage == "covered"
    assert state.quality == "warning"
    assert state.profile_eligibility == "eligible"


def test_consumer_warning_and_partial_boundaries() -> None:
    warning_state = evaluate_profile_eligibility(
        physical_coverage="covered",
        registration="registered",
        quality="warning",
        reference_metadata="passed",
        identity_in_profile=True,
        quality_policy="active_entry",
        bar_status="confirmed",
    )
    market = resolve_consumer_decision("Market", warning_state, bar_status="confirmed")
    backtest = resolve_consumer_decision("Backtest", warning_state, bar_status="confirmed")
    backtest_opt_in = resolve_consumer_decision(
        "Backtest", warning_state, bar_status="confirmed", allow_warning_quality=True
    )
    signal = resolve_consumer_decision("Signal", warning_state, bar_status="confirmed")
    review = resolve_consumer_decision("Review", warning_state, bar_status="confirmed")

    assert market.allowed is True and market.warning_visible is True
    assert backtest.allowed is False
    assert backtest_opt_in.allowed is True and backtest_opt_in.mode == "research_warning_opt_in"
    assert signal.allowed is False
    assert review.allowed is True and review.mode == "display_only"

    partial = resolve_consumer_decision("Market", warning_state, bar_status="partial")
    assert partial.allowed is False
    assert "bar_not_confirmed" in partial.block_reasons


def test_failed_registration_and_profile_states_block_all_consumers() -> None:
    state = evaluate_profile_eligibility(
        physical_coverage="covered",
        registration="missing",
        quality="passed",
        reference_metadata="passed",
        identity_in_profile=True,
        quality_policy="passed_only",
        bar_status="confirmed",
    )

    for consumer in ("Market", "Backtest", "Signal", "Review"):
        assert resolve_consumer_decision(consumer, state, bar_status="confirmed").allowed is False


def test_failed_and_unchecked_quality_block_all_consumers() -> None:
    for quality in ("failed", "unchecked"):
        state = evaluate_profile_eligibility(
            physical_coverage="covered",
            registration="registered",
            quality=quality,
            reference_metadata="passed",
            identity_in_profile=True,
            quality_policy="active_entry",
            bar_status="confirmed",
        )
        for consumer in ("Market", "Backtest", "Signal", "Review"):
            assert resolve_consumer_decision(consumer, state, bar_status="confirmed").allowed is False


def test_report_14_is_read_only_reference() -> None:
    assert report_mutation_allowed(14) is False
    assert report_mutation_allowed(15) is True
