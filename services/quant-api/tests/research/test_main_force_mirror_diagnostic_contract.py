from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal
import importlib
import json
from pathlib import Path

import pytest


PRODUCTS = (
    "a", "ag", "al", "ao", "ap", "au", "b", "bu", "bz", "c",
    "cf", "cj", "cu", "eb", "ec", "eg", "fg", "fu", "hc", "i",
    "j", "jd", "jm", "l", "lc", "lh", "m", "ma", "ni", "oi",
    "p", "pb", "pd", "pf", "pg", "pk", "pl", "pp", "pr", "ps",
    "pt", "px", "rb", "rm", "rs", "ru", "sa", "sc", "sf", "sh",
    "si", "sm", "sn", "sr", "ss", "ta", "ur", "v", "y", "zn",
)
UNIVERSE_SHA256 = "d2f7e8387fa9dd92b8720ed703de3a7bbc1ef79d0d75340b246783bab079fd1d"
PROFILES = ("balanced", "fast", "slow", "loose", "strict")


def _policy():
    try:
        return importlib.import_module(
            "app.research.main_force.main_force_mirror_diagnostic_policy"
        )
    except ModuleNotFoundError:
        pytest.fail("diagnostic protocol module is not implemented")


def _domain():
    try:
        return importlib.import_module(
            "app.research.main_force.main_force_mirror_diagnostic"
        )
    except ModuleNotFoundError:
        pytest.fail("diagnostic report contract module is not implemented")


def test_protocol_loader_freezes_every_binding_and_is_immutable() -> None:
    policy = _policy()

    protocol = policy.load_main_force_mirror_diagnostic_protocol()

    assert protocol.schema_version == 1
    assert protocol.protocol_id == "main_force_mirror_diagnostic_phase_a_v1"
    assert protocol.model_subprotocol == "mfm_v3_readonly_training_probe_v1"
    assert protocol.research_only is True
    assert protocol.readonly is True
    assert protocol.previous_missing_probe_result_inherited is False
    assert protocol.source_mode == "actual_dominant"
    assert protocol.frequency == "60m"
    assert protocol.confirmed_only is True
    assert protocol.jm_since == date(2026, 3, 10)
    assert protocol.jm_through == date(2026, 3, 30)
    assert protocol.active60_since == date(2023, 1, 1)
    assert protocol.active60_through == date(2026, 8, 18)
    assert protocol.known_retrospective_through == date(2026, 8, 20)
    assert protocol.prospective_begins_after == date(2026, 8, 20)
    assert protocol.prospective_consumed is False
    assert protocol.products == PRODUCTS
    assert protocol.active_universe_sha256 == UNIVERSE_SHA256
    assert protocol.label_horizon_bars == 10
    assert protocol.barrier_atr_multiple == Decimal("1.0")
    assert protocol.sequence_profile_ids == PROFILES
    assert protocol.ridge_l2 == Decimal("1.0")
    assert protocol.ridge_max_iterations == 100
    assert protocol.ridge_logit_clip == (Decimal("-35"), Decimal("35"))
    assert protocol.ridge_step_tolerance == Decimal("1e-8")
    assert protocol.cart_depth == 2
    assert protocol.cart_train_quantiles == (
        Decimal("0.25"), Decimal("0.50"), Decimal("0.75")
    )
    assert protocol.cart_min_leaf == 50
    assert protocol.cart_impurity == "weighted_gini"
    assert protocol.cart_leaf_smoothing == "laplace"
    assert protocol.bootstrap_resamples == 2000
    assert protocol.bootstrap_seed == 20260823
    assert protocol.bootstrap_minimum_valid == 1900
    assert protocol.bootstrap_ci == Decimal("0.95")
    assert tuple(
        (fold.fit_since, fold.fit_through, fold.evaluate_since, fold.evaluate_through)
        for fold in protocol.folds
    ) == (
        (date(2023, 1, 1), date(2024, 12, 31), date(2025, 1, 1), date(2025, 12, 31)),
        (date(2023, 1, 1), date(2025, 12, 31), date(2026, 1, 1), date(2026, 8, 18)),
    )
    assert protocol.available_products_floor == 48
    assert protocol.fit_binary_floor == 500
    assert protocol.fit_each_class_floor == 100
    assert protocol.evaluate_binary_floor == 200
    assert protocol.evaluate_each_class_floor == 50
    assert protocol.evaluate_each_side_floor == 50
    assert protocol.evaluate_products_floor == 20
    assert protocol.resolved_coverage_floor == Decimal("0.50")
    assert protocol.ambiguous_rate_maximum == Decimal("0.15")
    assert protocol.unknown_failures_maximum == 0
    assert protocol.sequence_required_profiles == 3
    assert protocol.sequence_peak_then_decay_pooled_floor == 200
    assert protocol.sequence_each_side_floor == 50
    assert protocol.sequence_products_floor == 20
    assert protocol.sequence_years_floor == 3
    assert protocol.sequence_top_product_share_maximum == Decimal("0.20")
    assert protocol.sequence_median_delay_maximum_bars == Decimal("2")
    assert protocol.sequence_h3_h5_reversal_hit_floor == Decimal("0.55")
    assert protocol.sequence_yearly_side_median_floor == Decimal("0")
    assert protocol.ridge_score_delta_floor == Decimal("0.02")
    assert protocol.full_tree_ridge_delta_floor == Decimal("0.02")
    assert protocol.full_tree_current_tree_delta_floor == Decimal("0.01")
    assert protocol.full_tree_auc_floor == Decimal("0.60")
    assert protocol.supported_side_auc_floor == Decimal("0.55")
    assert protocol.supported_side_point_delta_floor == Decimal("0")
    assert protocol.member_unique_key == (
        "symbol", "physical_contract", "anchor_trading_day"
    )
    assert protocol.member_t_minus_1_coverage_floor == Decimal("0.80")
    assert protocol.member_products_floor == 20
    assert protocol.member_causal_violations_maximum == 0
    assert protocol.member_identity_violations_maximum == 0
    assert protocol.member_model_allowed is False
    assert protocol.allowed_gates == ("STOP", "ALLOW_PHASE_FREEZE_DESIGN")
    assert protocol.formula_change_allowed is False
    assert protocol.threshold_change_allowed is False
    assert protocol.profile_change_allowed is False
    assert protocol.database_writes_allowed is False
    assert protocol.data_writes_allowed is False
    assert protocol.runtime_writes_allowed is False
    assert protocol.alert_writes_allowed is False
    assert protocol.rqdata_run_allowed is False
    assert protocol.real_evidence_run_allowed is False
    assert protocol.new_dependency_allowed is False
    assert protocol.trading_output_allowed is False
    assert protocol.performance_output_allowed is False
    assert protocol.ranking_output_allowed is False
    assert protocol.promotion_output_allowed is False

    with pytest.raises(FrozenInstanceError):
        protocol.frequency = "1d"
    with pytest.raises(policy.MainForceMirrorDiagnosticProtocolError):
        replace(protocol, frequency="1d")


def test_request_and_protocol_guard_reject_any_other_identity() -> None:
    policy = _policy()
    request = policy.MainForceMirrorDiagnosticRequest(
        protocol_id="main_force_mirror_diagnostic_phase_a_v1"
    )
    assert request.protocol_id == "main_force_mirror_diagnostic_phase_a_v1"
    assert (
        policy.require_exact_main_force_mirror_diagnostic_protocol(
            policy.load_main_force_mirror_diagnostic_protocol()
        ).protocol_id
        == request.protocol_id
    )

    with pytest.raises(
        policy.MainForceMirrorDiagnosticProtocolError,
        match="MFM_DIAGNOSTIC_PROTOCOL_INVALID",
    ):
        policy.MainForceMirrorDiagnosticRequest(protocol_id="main_force_mirror_v2")
    with pytest.raises(policy.MainForceMirrorDiagnosticProtocolError):
        policy.require_exact_main_force_mirror_diagnostic_protocol(object())


@pytest.mark.parametrize(
    "mutation",
    (
        "extra_field",
        "product_order",
        "source_mode",
        "confirmed",
        "prospective_consumed",
        "profile_order",
        "ridge_l2_type",
        "cart_quantile",
        "fold_date",
        "sample_floor",
        "sequence_threshold",
        "model_threshold",
        "member_model",
        "gate_order",
        "exclusion",
    ),
)
def test_protocol_shape_value_type_and_order_drift_fail_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    policy = _policy()
    source = (
        policy.PROTOCOL_PATH
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    mutated = deepcopy(payload)
    if mutation == "extra_field":
        mutated["unexpected"] = True
    elif mutation == "product_order":
        mutated["universe"]["products"][0:2] = reversed(
            mutated["universe"]["products"][0:2]
        )
    elif mutation == "source_mode":
        mutated["source"]["mode"] = "continuous"
    elif mutation == "confirmed":
        mutated["source"]["confirmed_only"] = False
    elif mutation == "prospective_consumed":
        mutated["windows"]["prospective"]["consumed"] = True
    elif mutation == "profile_order":
        mutated["sequence"]["profile_ids"].reverse()
    elif mutation == "ridge_l2_type":
        mutated["models"]["ridge_logistic"]["l2"] = 1
    elif mutation == "cart_quantile":
        mutated["models"]["deterministic_cart"]["train_quantiles"][0] = 0.2
    elif mutation == "fold_date":
        mutated["folds"][1]["evaluate"]["through"] = "2026-08-20"
    elif mutation == "sample_floor":
        mutated["sample_floors"]["available_products"] = 47
    elif mutation == "sequence_threshold":
        mutated["gate_thresholds"]["sequence"]["products"] = 19
    elif mutation == "model_threshold":
        mutated["gate_thresholds"]["model"]["full_tree_auc"] = 0.59
    elif mutation == "member_model":
        mutated["gate_thresholds"]["member_feasibility"]["member_model"] = True
    elif mutation == "gate_order":
        mutated["gate"]["allowed_values"].reverse()
    else:
        mutated["exclusions"]["ranking_output"] = True
    path = tmp_path / f"{mutation}.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")

    with pytest.raises(policy.MainForceMirrorDiagnosticProtocolError):
        policy.load_main_force_mirror_diagnostic_protocol(path)


def test_active_universe_order_or_source_bytes_drift_has_stable_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    policy = _policy()
    monkeypatch.setattr(policy, "load_active_products", lambda _path: PRODUCTS[::-1])
    with pytest.raises(
        policy.MainForceMirrorDiagnosticActiveUniverseError,
        match="MFM_DIAGNOSTIC_ACTIVE_UNIVERSE_DRIFT",
    ):
        policy.load_main_force_mirror_diagnostic_protocol()

    source = tmp_path / "active_products.txt"
    source.write_text("\n".join(PRODUCTS), encoding="utf-8")
    monkeypatch.setattr(policy, "ACTIVE_PRODUCTS_PATH", source)
    monkeypatch.setattr(policy, "load_active_products", lambda _path: PRODUCTS)
    with pytest.raises(policy.MainForceMirrorDiagnosticActiveUniverseError):
        policy.load_main_force_mirror_diagnostic_protocol()


def _breakdown_keys(domain):
    return (
        domain.MainForceMirrorDiagnosticBreakdownKey(
            scope=domain.MainForceMirrorDiagnosticBreakdownScope.GLOBAL,
        ),
        *(
            domain.MainForceMirrorDiagnosticBreakdownKey(
                scope=domain.MainForceMirrorDiagnosticBreakdownScope.PRODUCT,
                product=symbol,
            )
            for symbol in PRODUCTS
        ),
        *(
            domain.MainForceMirrorDiagnosticBreakdownKey(
                scope=domain.MainForceMirrorDiagnosticBreakdownScope.YEAR,
                year=year,
            )
            for year in (2023, 2024, 2025, 2026)
        ),
        *(
            domain.MainForceMirrorDiagnosticBreakdownKey(
                scope=domain.MainForceMirrorDiagnosticBreakdownScope.SIDE,
                side=side,
            )
            for side in (
                domain.MainForceMirrorDiagnosticSide.LONG,
                domain.MainForceMirrorDiagnosticSide.SHORT,
            )
        ),
        *(
            domain.MainForceMirrorDiagnosticBreakdownKey(
                scope=domain.MainForceMirrorDiagnosticBreakdownScope.FOLD,
                fold=fold,
            )
            for fold in (1, 2)
        ),
    )


def _zero_label_breakdowns(domain):
    return tuple(
        domain.MainForceMirrorDiagnosticLabelBreakdown(
            key=key,
            raw_sample_count=0,
            kept_sample_count=0,
            overlap_suppressed_count=0,
            long_sample_count=0,
            short_sample_count=0,
            duplicated_side_sample_count=0,
            binary_evaluable_count=0,
            legacy_long_only_count=0,
            legacy_short_only_count=0,
            legacy_both_count=0,
            legacy_neither_count=0,
            adverse_first_count=0,
            favorable_first_count=0,
            ambiguous_count=0,
            timeout_count=0,
            censored_horizon_count=0,
            censored_contract_change_count=0,
            censored_input_gap_count=0,
            split_boundary_censored_count=0,
        )
        for key in _breakdown_keys(domain)
    )


def _zero_label(domain):
    return domain.MainForceMirrorDiagnosticLabelSection(
        raw_sample_count=0,
        sample_count=0,
        overlap_suppressed_count=0,
        long_sample_count=0,
        short_sample_count=0,
        duplicated_side_sample_count=0,
        binary_evaluable_count=0,
        legacy_long_only_count=0,
        legacy_short_only_count=0,
        legacy_both_count=0,
        legacy_neither_count=0,
        adverse_first_count=0,
        favorable_first_count=0,
        ambiguous_count=0,
        timeout_count=0,
        censored_horizon_count=0,
        censored_contract_change_count=0,
        censored_input_gap_count=0,
        split_boundary_censored_count=0,
        resolved_coverage=Decimal("0"),
        ambiguous_rate=Decimal("0"),
        breakdowns=_zero_label_breakdowns(domain),
    )


def _zero_sequence_breakdowns(domain):
    return tuple(
        domain.MainForceMirrorDiagnosticSequenceBreakdown(
            key=key,
            raw_episode_count=0,
            kept_episode_count=0,
            overlap_suppressed_count=0,
            first_evidence_count=0,
            delay_sample_count=0,
            delay_bars_total=0,
            transitions=(),
            events=(),
            prefix_invariance=domain.MainForceMirrorDiagnosticPrefixInvariance(
                checked_prefix_count=0,
                matching_prefix_count=0,
                mismatch_count=0,
            ),
        )
        for key in _breakdown_keys(domain)
    )


def _zero_sequence(domain):
    return domain.MainForceMirrorDiagnosticSequenceSection(
        profiles=tuple(
            domain.MainForceMirrorDiagnosticSequenceProfileSection(
                profile_id=profile_id,
                peak_then_decay_sample_count=0,
                long_sample_count=0,
                short_sample_count=0,
                product_count=0,
                year_count=0,
                top_product_share=Decimal("0"),
                median_delay_bars=None,
                h3_reversal_hit_rate=None,
                h5_reversal_hit_rate=None,
                yearly_median_reversal_min=None,
                side_median_reversal_min=None,
                breakdowns=_zero_sequence_breakdowns(domain),
            )
            for profile_id in PROFILES
        )
    )


def _zero_funnel_breakdowns(domain):
    return tuple(
        domain.MainForceMirrorDiagnosticScoreLatchBreakdown(
            key=key,
            caution_ready_bar_count=0,
            binary_evaluable_count=0,
            score_not_candidate_count=0,
            long_only_candidate_count=0,
            short_only_candidate_count=0,
            dual_candidate_conflict_count=0,
            high_score_unique_bar_count=0,
            armed_candidate_count=0,
            unarmed_candidate_suppressed_count=0,
            long_caution_count=0,
            short_caution_count=0,
            caution_count=0,
            raw_episode_anchor_count=0,
            kept_episode_anchor_count=0,
            overlap_suppressed_anchor_count=0,
            long_rearm_count=0,
            short_rearm_count=0,
        )
        for key in _breakdown_keys(domain)
    )


def _zero_funnel(domain):
    return domain.MainForceMirrorDiagnosticFunnelSection(
        evaluable_bar_count=0,
        binary_evaluable_count=0,
        high_score_bar_count=0,
        conflict_bar_count=0,
        armed_bar_count=0,
        caution_episode_count=0,
        latched_episode_count=0,
        suppression_count=0,
        raw_episode_anchor_count=0,
        kept_episode_anchor_count=0,
        overlap_suppressed_anchor_count=0,
        breakdowns=_zero_funnel_breakdowns(domain),
    )


def test_funnel_contract_separates_latched_cautions_from_sampling_embargo() -> None:
    """Catches equating kept sampling anchors with raw latched caution events."""
    domain = _domain()
    funnel = _zero_funnel(domain)
    global_breakdown = replace(
        funnel.breakdowns[0],
        caution_ready_bar_count=2,
        long_only_candidate_count=2,
        high_score_unique_bar_count=2,
        armed_candidate_count=2,
        long_caution_count=2,
        caution_count=2,
        raw_episode_anchor_count=2,
        kept_episode_anchor_count=1,
        overlap_suppressed_anchor_count=1,
    )

    audited = replace(
        funnel,
        evaluable_bar_count=2,
        high_score_bar_count=2,
        armed_bar_count=2,
        caution_episode_count=2,
        latched_episode_count=2,
        raw_episode_anchor_count=2,
        kept_episode_anchor_count=1,
        overlap_suppressed_anchor_count=1,
        breakdowns=_consistent_partitions(funnel.breakdowns, global_breakdown),
    )

    assert audited.caution_episode_count == 2
    assert audited.kept_episode_anchor_count == 1
    assert audited.overlap_suppressed_anchor_count == 1


def test_label_split_censor_is_legal_only_in_fold_breakdowns() -> None:
    """Catches leaking a fold boundary into physical/global label outcomes."""
    domain = _domain()
    base = _zero_label_breakdowns(domain)
    values = dict(
        raw_sample_count=1,
        kept_sample_count=1,
        long_sample_count=1,
        short_sample_count=1,
        duplicated_side_sample_count=1,
        legacy_neither_count=1,
        split_boundary_censored_count=1,
    )

    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(base[0], **values)

    fold_one = replace(base[-2], **values)
    assert fold_one.key.fold == 1
    assert fold_one.split_boundary_censored_count == 1


def test_sequence_contract_keeps_installed_peak_denominator_above_decay_samples() -> None:
    """Catches replacing the installed-peak denominator with evaluable decays."""
    domain = _domain()
    sequence = _zero_sequence(domain)
    global_row = replace(
        sequence.profiles[0].breakdowns[0],
        raw_episode_count=13,
        kept_episode_count=13,
        first_evidence_count=1,
        delay_sample_count=1,
        delay_bars_total=1,
    )
    balanced = replace(
        sequence.profiles[0],
        peak_then_decay_sample_count=1,
        long_sample_count=1,
        product_count=1,
        year_count=1,
        top_product_share=Decimal("1"),
        median_delay_bars=Decimal("1"),
        h3_reversal_hit_rate=Decimal("1"),
        h5_reversal_hit_rate=Decimal("1"),
        yearly_median_reversal_min=Decimal("0"),
        side_median_reversal_min=Decimal("0"),
        breakdowns=_consistent_partitions(
            sequence.profiles[0].breakdowns,
            global_row,
        ),
    )

    assert balanced.breakdowns[0].raw_episode_count == 13
    assert balanced.breakdowns[0].first_evidence_count == 1
    assert balanced.peak_then_decay_sample_count == 1


def _zero_model_breakdowns(domain):
    return tuple(
        domain.MainForceMirrorDiagnosticModelBreakdown(
            key=key,
            sample_count=0,
            score_auc=None,
            ridge_auc=None,
            current_tree_auc=None,
            full_tree_auc=None,
        )
        for key in _breakdown_keys(domain)
    )


def _consistent_partitions(breakdowns, global_item):
    rows = list(breakdowns)
    for index in (0, 1, 61, 65):
        rows[index] = replace(global_item, key=rows[index].key)
    return tuple(rows)


def _model(domain):
    windows = (
        (date(2023, 1, 1), date(2024, 12, 31), date(2025, 1, 1), date(2025, 12, 31)),
        (date(2023, 1, 1), date(2025, 12, 31), date(2026, 1, 1), date(2026, 8, 18)),
    )
    folds = []
    for index, (fit_since, fit_through, evaluate_since, evaluate_through) in enumerate(windows, 1):
        folds.append(
            domain.MainForceMirrorDiagnosticModelFoldSection(
                fold=index,
                fit_since=fit_since,
                fit_through=fit_through,
                evaluate_since=evaluate_since,
                evaluate_through=evaluate_through,
                fit_binary_count=500,
                fit_negative_count=250,
                fit_positive_count=250,
                evaluate_binary_count=200,
                evaluate_negative_count=100,
                evaluate_positive_count=100,
                evaluate_long_count=100,
                evaluate_short_count=100,
                evaluate_product_count=20,
                bootstrap_valid_count=1900,
                score_auc=Decimal("0.50"),
                ridge_auc=Decimal("0.53"),
                current_tree_auc=Decimal("0.54"),
                full_tree_auc=Decimal("0.62"),
                ridge_score_delta=Decimal("0.03"),
                ridge_score_ci_lower=Decimal("0.01"),
                full_tree_ridge_delta=Decimal("0.09"),
                full_tree_ridge_ci_lower=Decimal("0.01"),
                full_tree_current_tree_delta=Decimal("0.08"),
                full_tree_current_tree_ci_lower=Decimal("0.01"),
                long_auc=Decimal("0.56"),
                short_auc=Decimal("0.57"),
                long_point_delta=Decimal("0"),
                short_point_delta=Decimal("0.01"),
            )
        )
    return domain.MainForceMirrorDiagnosticModelSection(
        folds=tuple(folds),
        breakdowns=_zero_model_breakdowns(domain),
    )


def _member(domain):
    return domain.MainForceMirrorDiagnosticMemberSection(
        unique_earliest_count=0,
        eligible_count=0,
        t_minus_1_coverage=Decimal("0"),
        product_count=0,
        causal_violation_count=0,
        identity_violation_count=0,
        member_model_present=False,
    )


def _available_row(domain, symbol: str):
    return domain.MainForceMirrorDiagnosticAvailableProductRow(
        symbol=symbol,
        status=domain.MainForceMirrorDiagnosticStatus.AVAILABLE,
        observed_since=date(2023, 1, 1),
        observed_through=date(2026, 8, 18),
        confirmed_bar_count=1,
        physical_contract_count=1,
    )


def _unavailable_row(domain, symbol: str):
    return domain.MainForceMirrorDiagnosticUnavailableProductRow(
        symbol=symbol,
        status=domain.MainForceMirrorDiagnosticStatus.UNAVAILABLE,
        reason_code=(
            domain.MainForceMirrorDiagnosticUnavailableReason.MARKET_SOURCE_UNAVAILABLE
        ),
    )


def _report(domain, rows):
    available = sum(
        row.status is domain.MainForceMirrorDiagnosticStatus.AVAILABLE for row in rows
    )
    unavailable = len(rows) - available
    return domain.MainForceMirrorDiagnosticReport(
        schema_version=1,
        protocol_id="main_force_mirror_diagnostic_phase_a_v1",
        model_subprotocol="mfm_v3_readonly_training_probe_v1",
        research_only=True,
        readonly=True,
        validation=domain.MainForceMirrorDiagnosticValidationMetadata(
            source_mode="actual_dominant",
            frequency="60m",
            confirmed_only=True,
            active_universe_sha256=UNIVERSE_SHA256,
            known_retrospective_through=date(2026, 8, 20),
            prospective_consumed=False,
            available_product_count=available,
            unavailable_product_count=unavailable,
            unknown_failure_count=0,
        ),
        product_rows=tuple(rows),
        label=_zero_label(domain),
        sequence=_zero_sequence(domain),
        funnel=_zero_funnel(domain),
        model=_model(domain),
        member=_member(domain),
        quality_flags=("SOURCE_UNAVAILABLE_PRESENT",) if unavailable else (),
        gate=domain.MainForceMirrorDiagnosticGate.STOP,
        gate_reasons=(
            domain.MainForceMirrorDiagnosticGateReason.SOURCE_UNAVAILABLE_PRESENT
            if unavailable
            else domain.MainForceMirrorDiagnosticGateReason.SAMPLE_FLOOR_FAILED,
        ),
    )


def test_report_rows_are_typed_complete_ordered_and_immutable() -> None:
    domain = _domain()
    rows = [_available_row(domain, symbol) for symbol in PRODUCTS]
    report = _report(domain, rows)

    assert report.product_rows[0].symbol == "a"
    assert report.product_rows[-1].symbol == "zn"
    assert report.validation.available_product_count == 60
    assert report.validation.unknown_failure_count == 0
    assert report.gate.value == "STOP"
    assert tuple(reason.value for reason in report.gate_reasons) == (
        "SAMPLE_FLOOR_FAILED",
    )
    with pytest.raises(FrozenInstanceError):
        report.gate = domain.MainForceMirrorDiagnosticGate.ALLOW_PHASE_FREEZE_DESIGN

    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        _report(domain, list(reversed(rows)))
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(
            report,
            gate_reasons=(
                domain.MainForceMirrorDiagnosticGateReason.SOURCE_UNAVAILABLE_PRESENT,
            ),
        )
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        domain.MainForceMirrorDiagnosticAvailableProductRow(
            symbol="a",
            status=domain.MainForceMirrorDiagnosticStatus.AVAILABLE,
            observed_since=date(2023, 1, 1),
            observed_through=date(2026, 8, 18),
            confirmed_bar_count=None,
            physical_contract_count=1,
        )
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        domain.MainForceMirrorDiagnosticUnavailableProductRow(
            symbol="a",
            status=domain.MainForceMirrorDiagnosticStatus.UNAVAILABLE,
            reason_code="UNKNOWN_FAILURE",
        )


def test_nested_audit_contract_expresses_required_breakdowns_and_conservation() -> None:
    domain = _domain()
    label = _zero_label(domain)
    label_global = replace(
        label.breakdowns[0],
        raw_sample_count=5,
        kept_sample_count=4,
        overlap_suppressed_count=1,
        long_sample_count=2,
        short_sample_count=2,
        binary_evaluable_count=2,
        legacy_long_only_count=1,
        legacy_short_only_count=1,
        legacy_both_count=1,
        legacy_neither_count=2,
        adverse_first_count=1,
        favorable_first_count=1,
        ambiguous_count=1,
        timeout_count=1,
    )
    label = replace(
        label,
        raw_sample_count=5,
        sample_count=4,
        overlap_suppressed_count=1,
        long_sample_count=2,
        short_sample_count=2,
        binary_evaluable_count=2,
        legacy_long_only_count=1,
        legacy_short_only_count=1,
        legacy_both_count=1,
        legacy_neither_count=2,
        adverse_first_count=1,
        favorable_first_count=1,
        ambiguous_count=1,
        timeout_count=1,
        resolved_coverage=Decimal("0.5"),
        ambiguous_rate=Decimal("0.25"),
        breakdowns=_consistent_partitions(label.breakdowns, label_global),
    )
    assert tuple(key.scope.value for key in _breakdown_keys(domain)[-4:]) == (
        "side", "side", "fold", "fold"
    )
    assert label.breakdowns[0].legacy_both_count == 1
    assert label.breakdowns[0].split_boundary_censored_count == 0

    sequence = _zero_sequence(domain)
    prefix = domain.MainForceMirrorDiagnosticPrefixInvariance(
        checked_prefix_count=1,
        matching_prefix_count=1,
        mismatch_count=0,
    )
    transition = domain.MainForceMirrorDiagnosticSequenceTransitionCount(
        from_state=domain.MainForceMirrorDiagnosticSequenceState.BUILD,
        to_state=domain.MainForceMirrorDiagnosticSequenceState.PEAK,
        count=1,
    )
    event = domain.MainForceMirrorDiagnosticSequenceEventCount(
        event_kind=domain.MainForceMirrorDiagnosticSequenceEvent.PEAK,
        raw_count=1,
        kept_count=1,
        overlap_count=0,
    )
    global_sequence = replace(
        sequence.profiles[0].breakdowns[0],
        raw_episode_count=1,
        kept_episode_count=1,
        first_evidence_count=1,
        delay_sample_count=1,
        delay_bars_total=1,
        transitions=(transition,),
        events=(event,),
        prefix_invariance=prefix,
    )
    balanced = replace(
        sequence.profiles[0],
        peak_then_decay_sample_count=1,
        long_sample_count=1,
        product_count=1,
        year_count=1,
        top_product_share=Decimal("1"),
        median_delay_bars=Decimal("1"),
        h3_reversal_hit_rate=Decimal("0.6"),
        h5_reversal_hit_rate=Decimal("0.6"),
        yearly_median_reversal_min=Decimal("0"),
        side_median_reversal_min=Decimal("0"),
        breakdowns=_consistent_partitions(
            sequence.profiles[0].breakdowns,
            global_sequence,
        ),
    )
    sequence = replace(sequence, profiles=(balanced, *sequence.profiles[1:]))
    assert sequence.profiles[0].breakdowns[0].transitions == (transition,)
    assert sequence.profiles[0].breakdowns[0].events == (event,)
    assert sequence.profiles[0].breakdowns[0].prefix_invariance == prefix

    funnel = _zero_funnel(domain)
    global_funnel = replace(
        funnel.breakdowns[0],
        caution_ready_bar_count=5,
        binary_evaluable_count=2,
        score_not_candidate_count=2,
        long_only_candidate_count=1,
        short_only_candidate_count=1,
        dual_candidate_conflict_count=1,
        high_score_unique_bar_count=3,
        armed_candidate_count=2,
        unarmed_candidate_suppressed_count=0,
        long_caution_count=1,
        short_caution_count=1,
        caution_count=2,
        raw_episode_anchor_count=2,
        kept_episode_anchor_count=1,
        overlap_suppressed_anchor_count=1,
    )
    funnel = replace(
        funnel,
        evaluable_bar_count=5,
        binary_evaluable_count=2,
        high_score_bar_count=3,
        conflict_bar_count=1,
        armed_bar_count=2,
        caution_episode_count=2,
        latched_episode_count=2,
        suppression_count=0,
        raw_episode_anchor_count=2,
        kept_episode_anchor_count=1,
        overlap_suppressed_anchor_count=1,
        breakdowns=_consistent_partitions(funnel.breakdowns, global_funnel),
    )
    assert funnel.breakdowns[0].caution_ready_bar_count == 5
    assert funnel.breakdowns[0].high_score_unique_bar_count == 3

    model = _model(domain)
    global_model = replace(
        model.breakdowns[0],
        sample_count=1,
        score_auc=Decimal("0.5"),
        ridge_auc=Decimal("0.5"),
        current_tree_auc=Decimal("0.5"),
        full_tree_auc=Decimal("0.5"),
    )
    model = replace(
        model,
        breakdowns=_consistent_partitions(model.breakdowns, global_model),
    )
    assert tuple(item.key.scope.value for item in model.breakdowns[-2:]) == (
        "fold", "fold"
    )

    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(label_global, kept_sample_count=5)
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(prefix, mismatch_count=1)
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(global_funnel, high_score_unique_bar_count=2)
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(
            label,
            breakdowns=(label_global, *_zero_label_breakdowns(domain)[1:]),
        )
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(
            balanced,
            breakdowns=(global_sequence, *_zero_sequence_breakdowns(domain)[1:]),
        )
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(
            funnel,
            breakdowns=(global_funnel, *_zero_funnel_breakdowns(domain)[1:]),
        )
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(
            model,
            breakdowns=(global_model, *_zero_model_breakdowns(domain)[1:]),
        )


def test_gate_reasons_are_required_only_for_stop() -> None:
    domain = _domain()
    report = _report(domain, [_available_row(domain, symbol) for symbol in PRODUCTS])

    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(report, gate_reasons=())

    allowed = replace(
        report,
        gate=domain.MainForceMirrorDiagnosticGate.ALLOW_PHASE_FREEZE_DESIGN,
        gate_reasons=(),
    )
    assert allowed.gate is domain.MainForceMirrorDiagnosticGate.ALLOW_PHASE_FREEZE_DESIGN
    assert allowed.gate_reasons == ()

    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(
            allowed,
            gate_reasons=(
                domain.MainForceMirrorDiagnosticGateReason.SAMPLE_FLOOR_FAILED,
            ),
        )


def test_member_coverage_uses_unique_earliest_as_denominator() -> None:
    domain = _domain()
    member = domain.MainForceMirrorDiagnosticMemberSection(
        unique_earliest_count=10,
        eligible_count=8,
        t_minus_1_coverage=Decimal("0.8"),
        product_count=5,
        causal_violation_count=0,
        identity_violation_count=0,
        member_model_present=False,
    )
    assert member.eligible_count <= member.unique_earliest_count

    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(member, eligible_count=11, t_minus_1_coverage=Decimal("1.1"))
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(member, t_minus_1_coverage=Decimal("0.7"))
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(_member(domain), t_minus_1_coverage=Decimal("0.1"))
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(
            _member(domain),
            eligible_count=1,
            t_minus_1_coverage=Decimal("1"),
        )


def test_report_count_limits_accept_protocol_boundary_and_reject_overflow() -> None:
    domain = _domain()
    fold = _model(domain).folds[0]
    assert replace(
        fold,
        bootstrap_valid_count=2000,
        evaluate_product_count=60,
    ).bootstrap_valid_count == 2000
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(fold, bootstrap_valid_count=2001)
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(fold, evaluate_product_count=61)

    sequence = _zero_sequence(domain)
    global_breakdown = replace(
        sequence.profiles[0].breakdowns[0],
        raw_episode_count=1,
        kept_episode_count=1,
        first_evidence_count=1,
        delay_sample_count=1,
    )
    profile = replace(
        sequence.profiles[0],
        peak_then_decay_sample_count=1,
        long_sample_count=1,
        product_count=60,
        year_count=4,
        top_product_share=Decimal("1"),
        median_delay_bars=Decimal("0"),
        h3_reversal_hit_rate=Decimal("0"),
        h5_reversal_hit_rate=Decimal("0"),
        yearly_median_reversal_min=Decimal("0"),
        side_median_reversal_min=Decimal("0"),
        breakdowns=_consistent_partitions(
            sequence.profiles[0].breakdowns,
            global_breakdown,
        ),
    )
    assert profile.product_count == 60
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(profile, product_count=61)

    member = replace(_member(domain), product_count=60)
    assert member.product_count == 60
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(member, product_count=61)

    validation = _report(
        domain,
        [_available_row(domain, symbol) for symbol in PRODUCTS],
    ).validation
    assert validation.available_product_count == 60
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(
            validation,
            available_product_count=61,
            unavailable_product_count=0,
        )


def test_model_fold_contract_represents_normal_unavailability_without_fake_auc() -> None:
    """Catches encoding model failure or a one-class side as a fabricated zero AUC."""
    domain = _domain()
    fold = _model(domain).folds[0]
    core_fields = {
        "score_auc": None,
        "ridge_auc": None,
        "current_tree_auc": None,
        "full_tree_auc": None,
        "ridge_score_delta": None,
        "ridge_score_ci_lower": None,
        "full_tree_ridge_delta": None,
        "full_tree_ridge_ci_lower": None,
        "full_tree_current_tree_delta": None,
        "full_tree_current_tree_ci_lower": None,
    }

    convergence = replace(
        fold,
        **core_fields,
        model_unavailable_reason=(
            domain.MainForceMirrorDiagnosticUnavailableReason.MODEL_CONVERGENCE_FAILED
        ),
    )
    assert convergence.full_tree_auc is None

    insufficient = replace(
        fold,
        **core_fields,
        model_unavailable_reason=(
            domain.MainForceMirrorDiagnosticUnavailableReason.SPLIT_CLASS_UNAVAILABLE
        ),
    )
    assert insufficient.score_auc is None

    one_class_long = replace(
        fold,
        evaluate_long_count=0,
        evaluate_short_count=fold.evaluate_binary_count,
        long_auc=None,
        long_point_delta=None,
        long_unavailable_reason=(
            domain.MainForceMirrorDiagnosticUnavailableReason.SPLIT_CLASS_UNAVAILABLE
        ),
    )
    assert one_class_long.long_auc is None
    assert one_class_long.short_auc == fold.short_auc

    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(fold, model_unavailable_reason="UNKNOWN_FAILURE")
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(
            fold,
            score_auc=None,
            model_unavailable_reason=(
                domain.MainForceMirrorDiagnosticUnavailableReason.MODEL_CONVERGENCE_FAILED
            ),
        )
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(
            one_class_long,
            long_auc=Decimal("0"),
        )

    one_class_breakdown = replace(
        _zero_model_breakdowns(domain)[0],
        sample_count=5,
        unavailable_reason=(
            domain.MainForceMirrorDiagnosticUnavailableReason.SPLIT_CLASS_UNAVAILABLE
        ),
    )
    assert one_class_breakdown.score_auc is None
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(one_class_breakdown, score_auc=Decimal("0"))


def test_report_rejects_hidden_unknown_failures_nonfinite_rates_and_partial_sections() -> None:
    domain = _domain()
    rows = [_unavailable_row(domain, symbol) for symbol in PRODUCTS]
    report = _report(domain, rows)

    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(report.validation, unknown_failure_count=1)
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(report.label, resolved_coverage=Decimal("NaN"))
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(report.label, ambiguous_rate=Decimal("1.01"))
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(
            report.sequence.profiles[0],
            peak_then_decay_sample_count=1,
            median_delay_bars=None,
        )
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(report.model.folds[0], full_tree_auc=Decimal("Infinity"))
    with pytest.raises(domain.MainForceMirrorDiagnosticReportError):
        replace(report.member, t_minus_1_coverage=Decimal("-0.01"))


def test_reason_enums_are_complete_and_exact() -> None:
    domain = _domain()
    assert tuple(reason.value for reason in domain.MainForceMirrorDiagnosticUnavailableReason) == (
        "MARKET_SOURCE_UNAVAILABLE",
        "MFM_V2_IDENTITY_CONFLICT",
        "POINT_COVERAGE_INCOMPLETE",
        "NO_CAUTION_EPISODE",
        "LABEL_BARRIER_INVALID",
        "LABEL_HORIZON_INCOMPLETE",
        "PHYSICAL_CONTRACT_CHANGED_BEFORE_LABEL",
        "INPUT_GAP_BEFORE_LABEL",
        "SPLIT_CLASS_UNAVAILABLE",
        "FEATURE_UNAVAILABLE",
        "MODEL_CONVERGENCE_FAILED",
        "MEMBER_DATASET_UNAVAILABLE",
        "MEMBER_T_MINUS_1_UNAVAILABLE",
        "MEMBER_IDENTITY_CONFLICT",
    )
    assert tuple(reason.value for reason in domain.MainForceMirrorDiagnosticGateReason) == (
        "SOURCE_UNAVAILABLE_PRESENT",
        "SAMPLE_FLOOR_FAILED",
        "BINARY_COVERAGE_INSUFFICIENT",
        "AMBIGUOUS_RATE_EXCEEDED",
        "SEQUENCE_UNSTABLE",
        "RIDGE_INCREMENT_INSUFFICIENT",
        "NONLINEAR_INCREMENT_INSUFFICIENT",
        "SEQUENCE_INCREMENT_INSUFFICIENT",
        "NONLINEAR_AUC_INSUFFICIENT",
        "SIDE_GUARDRAIL_FAILED",
        "MEMBER_FEASIBILITY_INSUFFICIENT",
        "MODEL_UNAVAILABLE",
    )
    assert tuple(status.value for status in domain.MainForceMirrorDiagnosticStatus) == (
        "available", "unavailable"
    )
    assert tuple(gate.value for gate in domain.MainForceMirrorDiagnosticGate) == (
        "STOP", "ALLOW_PHASE_FREEZE_DESIGN"
    )
