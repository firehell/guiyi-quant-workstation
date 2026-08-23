from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import importlib
import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest

from guiyi_quant.indicators.main_force_mirror_v2 import (
    MainForceMirrorV2AuditTraceItem,
    MainForceMirrorV2CautionComponents,
    MainForceMirrorV2LatchSnapshot,
    MainForceMirrorV2Point,
)

from app.market_data.domain import CanonicalBar
from app.research.main_force.main_force_mirror_diagnostic import (
    MainForceMirrorDiagnosticSide,
)
from app.research.main_force.main_force_mirror_diagnostic_analysis import (
    MainForceMirrorDiagnosticFoldLabelOutcome,
    MainForceMirrorDiagnosticLabelEpisode,
    MainForceMirrorDiagnosticLabelOutcome,
    MainForceMirrorDiagnosticLegacyOutcome,
    MainForceMirrorDiagnosticProductInput,
    MainForceMirrorDiagnosticLabelAuditResult,
    MainForceMirrorDiagnosticSequenceFactSet,
)
from app.research.main_force.main_force_mirror_v2_research_service import (
    MainForceMirrorV2SequenceFact,
)


_CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "_mfm_diagnostic_contract_fixtures",
    Path(__file__).with_name("test_main_force_mirror_diagnostic_contract.py"),
)
assert _CONTRACT_SPEC is not None and _CONTRACT_SPEC.loader is not None
contract_fixtures = importlib.util.module_from_spec(_CONTRACT_SPEC)
sys.modules[_CONTRACT_SPEC.name] = contract_fixtures
_CONTRACT_SPEC.loader.exec_module(contract_fixtures)


def _models():
    try:
        return importlib.import_module(
            "app.research.main_force.main_force_mirror_diagnostic_models"
        )
    except ModuleNotFoundError:
        pytest.fail("diagnostic model module is not implemented")


_LATCH = MainForceMirrorV2LatchSnapshot(True, True, 0, 0, 0, 0)
_COMPONENTS = MainForceMirrorV2CautionComponents(
    True, False, True, False, False, True, False, True
)


def _product_and_episode(
    *,
    side: MainForceMirrorDiagnosticSide = MainForceMirrorDiagnosticSide.LONG,
    denominator: float = 4.0,
) -> tuple[
    MainForceMirrorDiagnosticProductInput,
    MainForceMirrorDiagnosticLabelEpisode,
]:
    bar = CanonicalBar(
        bar_end=datetime(2025, 6, 2, 1, tzinfo=UTC),
        trading_day=date(2025, 6, 2),
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("104"),
        volume=Decimal("100"),
        turnover=None,
        open_interest=Decimal("1000"),
    )
    caution = (
        "long_chase_caution"
        if side is MainForceMirrorDiagnosticSide.LONG
        else "short_chase_caution"
    )
    point = MainForceMirrorV2Point(
        bar_end=bar.bar_end,
        trading_day=bar.trading_day,
        physical_contract="JM2609",
        pressure_ready=True,
        pressure_state="long_build",
        instant_pressure=40.0,
        accumulated_ready=True,
        accumulated_pressure=30.0,
        caution_ready=True,
        caution=caution,
        caution_conflict=False,
        long_caution_score=80.0,
        short_caution_score=20.0,
        caution_reason_codes=("fixture",),
        member=None,
        unavailable_reason=None,
        price_impulse=1.5,
        clv=0.4,
        volume_ratio=1.25,
        delta_oi=5.0,
        oi_impulse=0.75,
        range_position=0.8,
    )
    trace = MainForceMirrorV2AuditTraceItem(
        bar_end=bar.bar_end,
        trading_day=bar.trading_day,
        physical_contract="JM2609",
        atr14=5.0,
        volume_mean20=80.0,
        range_high20=120.0,
        range_low20=80.0,
        oi_baseline20=10.0,
        price_impulse=1.5,
        clv=0.4,
        direction=1.2,
        volume_ratio=1.25,
        delta_oi=5.0,
        oi_impulse=0.75,
        range_position=0.8,
        long_open_pressure=2.0,
        short_open_pressure=1.0,
        prior_long_open_pressure_max=denominator,
        prior_short_open_pressure_max=denominator,
        instant_pressure=40.0,
        accumulated_pressure=30.0,
        long_score=80.0,
        short_score=20.0,
        components=_COMPONENTS,
        long_candidate=True,
        short_candidate=False,
        conflict=False,
        latch_before=_LATCH,
        latch_after=_LATCH,
        trigger=caution,
        long_disarmed_suppressed=False,
        short_disarmed_suppressed=False,
        rearm_reasons=(),
        reset_boundary=None,
        unavailable_reason=None,
        prior_high_max=106.0,
        prior_low_min=94.0,
        upper_wick_ratio=0.3,
        lower_wick_ratio=0.2,
    )
    bars = tuple(
        replace(bar, bar_end=bar.bar_end - timedelta(hours=offset))
        for offset in (2, 1, 0)
    )
    points = tuple(
        replace(
            point,
            bar_end=current.bar_end,
            caution=None if index < 2 else point.caution,
            caution_reason_codes=() if index < 2 else point.caution_reason_codes,
            instant_pressure=80.0 if index == 0 else point.instant_pressure,
            accumulated_pressure=(
                60.0 if index == 0 else point.accumulated_pressure
            ),
        )
        for index, current in enumerate(bars)
    )
    traces = tuple(
        replace(
            trace,
            bar_end=current.bar_end,
            trigger=None if index < 2 else trace.trigger,
        )
        for index, current in enumerate(bars)
    )
    episode = MainForceMirrorDiagnosticLabelEpisode(
        symbol="jm",
        anchor_index=2,
        anchor_trading_day=bar.trading_day,
        physical_contract="JM2609",
        side=side,
        kept=True,
        lower_barrier=Decimal("99"),
        upper_barrier=Decimal("109"),
        legacy_outcome=MainForceMirrorDiagnosticLegacyOutcome.LONG_ONLY,
        outcome=MainForceMirrorDiagnosticLabelOutcome.ADVERSE_FIRST,
        first_touch_offset=1,
        binary_target=1,
        fold_outcomes=(
            MainForceMirrorDiagnosticFoldLabelOutcome(
                1,
                "evaluate",
                MainForceMirrorDiagnosticLabelOutcome.ADVERSE_FIRST,
                1,
                True,
            ),
            MainForceMirrorDiagnosticFoldLabelOutcome(
                2,
                "fit",
                MainForceMirrorDiagnosticLabelOutcome.ADVERSE_FIRST,
                1,
                True,
            ),
        ),
    )
    return MainForceMirrorDiagnosticProductInput(
        symbol="jm", bars=bars, points=points, trace=traces
    ), episode


def _sequence(**changes: object) -> MainForceMirrorV2SequenceFact:
    value = MainForceMirrorV2SequenceFact(
        index=2,
        current_side="long",
        pressure_state="long_build",
        instant_pressure=40.0,
        accumulated_pressure=30.0,
        active_peak_index=0,
        active_peak_side="long",
        active_peak_instant_pressure=80.0,
        active_peak_accumulated_pressure=60.0,
        bars_since_active_peak=2,
        decay_ratio=Decimal("0.25"),
        installed_peak_index=2,
        installed_peak_side="short",
        installed_peak_instant_pressure=-999.0,
        installed_peak_accumulated_pressure=-999.0,
        peak_seen=True,
        decay_seen=True,
        liquidation_seen=False,
        opposite_build_seen=True,
        accumulated_reversal_seen=False,
        state_transition="long_build->short_build",
    )
    return replace(value, **changes)


def _balanced_fact_set(
    anchor: MainForceMirrorV2SequenceFact,
) -> MainForceMirrorDiagnosticSequenceFactSet:
    prior = (
        _sequence(
            index=0,
            instant_pressure=80.0,
            accumulated_pressure=60.0,
            active_peak_index=None,
            active_peak_side=None,
            active_peak_instant_pressure=None,
            active_peak_accumulated_pressure=None,
            bars_since_active_peak=None,
            decay_ratio=None,
            installed_peak_index=0,
            installed_peak_side="long",
            installed_peak_instant_pressure=80.0,
            installed_peak_accumulated_pressure=60.0,
            peak_seen=True,
            decay_seen=False,
            liquidation_seen=False,
            opposite_build_seen=False,
            accumulated_reversal_seen=False,
            state_transition=None,
        ),
        _sequence(
            index=1,
            active_peak_index=None,
            active_peak_side=None,
            active_peak_instant_pressure=None,
            active_peak_accumulated_pressure=None,
            bars_since_active_peak=None,
            decay_ratio=None,
            installed_peak_index=None,
            installed_peak_side=None,
            installed_peak_instant_pressure=None,
            installed_peak_accumulated_pressure=None,
            peak_seen=False,
            decay_seen=False,
            liquidation_seen=False,
            opposite_build_seen=False,
            accumulated_reversal_seen=False,
            state_transition=None,
        ),
    )
    return MainForceMirrorDiagnosticSequenceFactSet(
        symbol="jm", profile_id="balanced", facts=(*prior, anchor)
    )


def test_feature_vector_has_exact_frozen_names_order_and_active_peak_values() -> None:
    """Catches feature reorder, installed-peak leakage, or side alignment drift."""
    models = _models()
    product, episode = _product_and_episode()

    row = models.build_main_force_mirror_feature_row(
        product, episode, _sequence()
    )

    assert models.CURRENT_FEATURE_NAMES == models.FEATURE_NAMES[:23]
    assert len(models.FEATURE_NAMES) == 33
    assert models.FEATURE_NAMES == (
        "side_caution_score", "opposite_caution_score",
        "side_aligned_direction", "side_aligned_price_impulse",
        "side_aligned_clv", "volume_ratio", "oi_impulse",
        "side_range_extremity", "side_aligned_instant_pressure",
        "side_aligned_accumulated_pressure", "side_open_pressure_ratio",
        "side_break_distance_atr", "side_rejection_wick_ratio",
        "atr_close_ratio", "side_range_extreme_component",
        "side_liquidation_component",
        "side_open_pressure_divergence_component",
        "side_volume_rejection_component", "state_long_build",
        "state_short_build", "state_long_liquidation", "state_short_cover",
        "state_turnover", "active_peak_present", "active_peak_same_side",
        "bars_since_active_peak", "decay_ratio",
        "side_aligned_active_peak_instant_pressure",
        "side_aligned_active_peak_accumulated_pressure", "decay_seen",
        "liquidation_seen", "opposite_build_seen",
        "accumulated_reversal_seen",
    )
    assert row is not None
    assert row.values == pytest.approx(
        (
            80, 20, 1.2, 1.5, 0.4, 1.25, 0.75, 0.8, 0.4, 0.3,
            0.5, 0.8, 0.3, 5 / 104, 1, 0, 1, 0, 1, 0, 0, 0, 0,
            1, 1, 2, 0.25, 0.8, 0.6, 1, 0, 1, 0,
        )
    )

    changed_installed = replace(
        _sequence(),
        installed_peak_side="long",
        installed_peak_instant_pressure=123456.0,
        installed_peak_accumulated_pressure=654321.0,
    )
    assert models.build_main_force_mirror_feature_row(
        product, episode, changed_installed
    ) == row


def test_feature_vector_zero_fills_only_missing_active_peak_and_types_other_missing() -> None:
    """Catches filling required current evidence or rejecting an absent active peak."""
    models = _models()
    product, episode = _product_and_episode()
    no_peak = _sequence(
        active_peak_index=None,
        active_peak_side=None,
        active_peak_instant_pressure=None,
        active_peak_accumulated_pressure=None,
        bars_since_active_peak=None,
        decay_ratio=None,
        decay_seen=False,
        liquidation_seen=False,
        opposite_build_seen=False,
        accumulated_reversal_seen=False,
    )
    row = models.build_main_force_mirror_feature_row(product, episode, no_peak)
    assert row is not None
    assert row.values[23:] == (0.0,) * 10

    invalid_product, invalid_episode = _product_and_episode(denominator=0.0)
    assert models.build_main_force_mirror_feature_row(
        invalid_product, invalid_episode, no_peak
    ) is None
    labels = MainForceMirrorDiagnosticLabelAuditResult(
        inputs=(invalid_product,),
        section=object(),
        episodes=(invalid_episode,),
        unavailable_products=(),
    )
    unavailable = models.build_main_force_mirror_fold_datasets(
        (invalid_product,), labels, (_balanced_fact_set(no_peak),)
    )
    assert len(unavailable.unavailable_episodes) == 1
    assert unavailable.unavailable_episodes[0].reason.value == "FEATURE_UNAVAILABLE"


def test_fold_dataset_uses_only_eligible_fold_outcomes() -> None:
    """Catches admitting a fold-specific censored outcome into a model split."""
    models = _models()
    product, episode = _product_and_episode()
    episode = replace(
        episode,
        outcome=MainForceMirrorDiagnosticLabelOutcome.FAVORABLE_FIRST,
        binary_target=0,
        fold_outcomes=(
            MainForceMirrorDiagnosticFoldLabelOutcome(
                1,
                "evaluate",
                MainForceMirrorDiagnosticLabelOutcome.FAVORABLE_FIRST,
                0,
                True,
            ),
            MainForceMirrorDiagnosticFoldLabelOutcome(
                2,
                "fit",
                MainForceMirrorDiagnosticLabelOutcome.SPLIT_BOUNDARY_CENSORED,
                None,
                False,
            ),
        ),
    )
    labels = MainForceMirrorDiagnosticLabelAuditResult(
        inputs=(product,),
        section=object(),  # dataset builder binds episodes/inputs, not report aggregation
        episodes=(episode,),
        unavailable_products=(),
    )
    facts = _balanced_fact_set(_sequence())

    result = models.build_main_force_mirror_fold_datasets(
        (product,), labels, (facts,)
    )

    assert result.unavailable_episodes == ()
    assert result.folds[0].fit == ()
    assert len(result.folds[0].evaluate) == 1
    assert result.folds[0].evaluate[0].target == 0
    assert result.folds[1].fit == ()
    assert result.folds[1].evaluate == ()


@pytest.mark.parametrize(
    "changes",
    (
        {"active_peak_index": 2, "bars_since_active_peak": 0},
        {"active_peak_index": 0, "bars_since_active_peak": 1},
        {"active_peak_side": None},
        {"current_side": "short"},
        {"pressure_state": "short_build"},
        {"instant_pressure": 41.0},
        {"accumulated_pressure": 31.0},
    ),
)
def test_feature_builder_rejects_corrupt_strict_prior_fact_identity(
    changes: dict[str, object],
) -> None:
    """Catches treating a contradictory balanced fact as feature unavailability."""
    models = _models()
    product, episode = _product_and_episode()

    with pytest.raises(ValueError, match="MFM_DIAGNOSTIC_ANALYSIS_INVALID"):
        models.build_main_force_mirror_feature_row(
            product,
            episode,
            _sequence(**changes),
        )


@pytest.mark.parametrize(
    "kind",
    (
        "episode_symbol",
        "episode_index",
        "malformed_episode_index",
        "bool_episode_index",
        "episode_day",
        "episode_contract",
        "episode_side",
        "point_identity",
        "trace_identity",
        "bar_identity",
        "active_peak_reference",
        "bool_fact_index",
        "bool_active_peak_index",
        "bool_bars_since_active_peak",
        "bool_installed_peak_index",
        "missing_fold",
        "fold_outcomes_none",
        "fold_outcomes_list",
        "malformed_outcome",
        "bool_fold",
        "bool_fold_target",
        "bool_first_touch",
        "bad_fold",
        "bad_segment_date",
        "bad_outcome_target",
    ),
)
def test_fold_dataset_rejects_episode_fact_and_fold_identity_drift(kind: str) -> None:
    """Catches routing corrupted audit identity into FEATURE_UNAVAILABLE or KeyError."""
    models = _models()
    product, episode = _product_and_episode()
    if kind == "episode_symbol":
        episode = replace(episode, symbol="ag")
    elif kind == "episode_index":
        episode = replace(episode, anchor_index=1)
    elif kind == "malformed_episode_index":
        episode = replace(episode, anchor_index="2")
    elif kind == "bool_episode_index":
        episode = replace(episode, anchor_index=True)
    elif kind == "episode_day":
        episode = replace(episode, anchor_trading_day=date(2025, 6, 3))
    elif kind == "episode_contract":
        episode = replace(episode, physical_contract="JM2701")
    elif kind == "episode_side":
        episode = replace(episode, side=MainForceMirrorDiagnosticSide.SHORT)
    elif kind == "point_identity":
        points = list(product.points)
        points[episode.anchor_index] = replace(
            points[episode.anchor_index],
            bar_end=points[episode.anchor_index].bar_end + timedelta(minutes=1),
        )
        product = replace(product, points=tuple(points))
    elif kind == "trace_identity":
        traces = list(product.trace)
        traces[episode.anchor_index] = replace(
            traces[episode.anchor_index],
            trading_day=date(2025, 6, 3),
        )
        product = replace(product, trace=tuple(traces))
    elif kind == "bar_identity":
        bars = list(product.bars)
        bars[episode.anchor_index] = replace(
            bars[episode.anchor_index],
            trading_day=date(2025, 6, 3),
        )
        product = replace(product, bars=tuple(bars))
    elif kind in {
        "active_peak_reference",
        "bool_fact_index",
        "bool_active_peak_index",
        "bool_bars_since_active_peak",
        "bool_installed_peak_index",
    }:
        pass
    elif kind == "missing_fold":
        episode = replace(episode, fold_outcomes=episode.fold_outcomes[:1])
    elif kind == "fold_outcomes_none":
        episode = replace(episode, fold_outcomes=None)
    elif kind == "fold_outcomes_list":
        episode = replace(episode, fold_outcomes=list(episode.fold_outcomes))
    elif kind == "malformed_outcome":
        episode = replace(episode, fold_outcomes=(object(),))
    elif kind == "bool_fold":
        episode = replace(
            episode,
            fold_outcomes=(
                replace(episode.fold_outcomes[0], fold=True),
                episode.fold_outcomes[1],
            ),
        )
    elif kind == "bool_fold_target":
        episode = replace(
            episode,
            binary_target=True,
            fold_outcomes=(
                replace(episode.fold_outcomes[0], binary_target=True),
                replace(episode.fold_outcomes[1], binary_target=True),
            ),
        )
    elif kind == "bool_first_touch":
        episode = replace(
            episode,
            outcome=MainForceMirrorDiagnosticLabelOutcome.TIMEOUT,
            first_touch_offset=True,
            binary_target=None,
            fold_outcomes=tuple(
                replace(
                    outcome,
                    outcome=MainForceMirrorDiagnosticLabelOutcome.TIMEOUT,
                    binary_target=None,
                    eligible=False,
                )
                for outcome in episode.fold_outcomes
            ),
        )
    elif kind == "bad_fold":
        episode = replace(
            episode,
            fold_outcomes=(replace(episode.fold_outcomes[0], fold=3),),
        )
    elif kind == "bad_segment_date":
        episode = replace(
            episode,
            fold_outcomes=(
                replace(episode.fold_outcomes[0], segment="fit"),
                episode.fold_outcomes[1],
            ),
        )
    else:
        episode = replace(
            episode,
            fold_outcomes=(
                replace(
                    episode.fold_outcomes[0],
                    outcome=MainForceMirrorDiagnosticLabelOutcome.FAVORABLE_FIRST,
                    binary_target=1,
                ),
                episode.fold_outcomes[1],
            ),
        )
    labels = MainForceMirrorDiagnosticLabelAuditResult(
        inputs=(product,),
        section=object(),
        episodes=(episode,),
        unavailable_products=(),
    )
    fact_set = _balanced_fact_set(_sequence())
    if kind == "active_peak_reference":
        facts = list(fact_set.facts)
        facts[0] = replace(facts[0], installed_peak_side="short")
        fact_set = replace(fact_set, facts=tuple(facts))
    elif kind == "bool_fact_index":
        facts = list(fact_set.facts)
        facts[0] = replace(facts[0], index=False)
        fact_set = replace(fact_set, facts=tuple(facts))
    elif kind == "bool_active_peak_index":
        facts = list(fact_set.facts)
        facts[2] = replace(
            facts[2], active_peak_index=True, bars_since_active_peak=1
        )
        fact_set = replace(fact_set, facts=tuple(facts))
    elif kind == "bool_bars_since_active_peak":
        facts = list(fact_set.facts)
        facts[2] = replace(facts[2], bars_since_active_peak=True)
        fact_set = replace(fact_set, facts=tuple(facts))
    elif kind == "bool_installed_peak_index":
        facts = list(fact_set.facts)
        facts[0] = replace(facts[0], installed_peak_index=False)
        fact_set = replace(fact_set, facts=tuple(facts))

    with pytest.raises(ValueError, match="MFM_DIAGNOSTIC_ANALYSIS_INVALID"):
        models.build_main_force_mirror_fold_datasets(
            (product,), labels, (fact_set,)
        )


def test_ridge_uses_train_only_standardization_constant_std_and_exact_class_weights() -> None:
    """Catches evaluation leakage, zero constant scale, or unnormalized class weights."""
    models = _models()
    train = np.array([[1.0, 5.0], [2.0, 5.0], [3.0, 5.0], [4.0, 5.0]])
    targets = np.array([0, 0, 0, 1], dtype=float)

    standardizer = models.fit_main_force_mirror_standardizer(train)
    weights = models.main_force_mirror_class_weights(targets)
    fit = models.fit_main_force_mirror_ridge(train, targets)

    assert standardizer.mean == pytest.approx((2.5, 5.0))
    assert standardizer.std == pytest.approx((np.std(train[:, 0]), 1.0))
    assert weights == pytest.approx((2 / 3, 2 / 3, 2 / 3, 2.0))
    assert np.mean(weights) == pytest.approx(1.0)
    assert fit.unavailable_reason is None
    assert fit.model is not None
    assert fit.model.standardizer == standardizer
    assert fit.model.iterations <= 100
    assert fit.model.step_linf <= 1e-8

    shifted_evaluation = np.array([[1000.0, -999.0]])
    assert models.fit_main_force_mirror_standardizer(train) == standardizer
    assert models.transform_main_force_mirror_features(
        shifted_evaluation, standardizer
    )[0, 0] > 100


def test_ridge_nonfinite_or_one_class_is_typed_without_fallback_solver() -> None:
    """Catches pseudo-inverse/fallback fitting or a fabricated one-class model."""
    models = _models()
    nonfinite = models.fit_main_force_mirror_ridge(
        np.array([[0.0], [np.nan]]), np.array([0.0, 1.0])
    )
    one_class = models.fit_main_force_mirror_ridge(
        np.array([[0.0], [1.0]]), np.array([1.0, 1.0])
    )

    assert nonfinite.model is None
    assert nonfinite.unavailable_reason.value == "MODEL_CONVERGENCE_FAILED"
    assert one_class.model is None
    assert one_class.unavailable_reason.value == "SPLIT_CLASS_UNAVAILABLE"


def test_cart_uses_train_quantiles_min_leaf_tie_order_and_laplace_probabilities() -> None:
    """Catches evaluation-derived thresholds, invalid leaves, or unstable split ties."""
    models = _models()
    base = np.arange(200, dtype=float)
    train = np.column_stack((base, base))
    targets = np.array([0.0] * 100 + [1.0] * 100)

    fit = models.fit_main_force_mirror_cart(train, targets, feature_count=2)

    assert fit.unavailable_reason is None
    assert fit.model is not None
    root = fit.model.root
    assert root.feature_index == 0
    assert root.threshold == pytest.approx(0.0)  # standardized train median
    assert root.left is not None and root.right is not None
    assert root.left.probability == pytest.approx(1 / 102)
    assert root.right.probability == pytest.approx(101 / 102)
    assert models.predict_main_force_mirror_cart(
        fit.model, np.array([[10000.0, -10000.0]])
    ).shape == (1,)

    too_small = models.fit_main_force_mirror_cart(
        np.arange(99, dtype=float).reshape(-1, 1),
        np.array([0.0] * 49 + [1.0] * 50),
        feature_count=1,
    )
    assert too_small.model is not None
    assert too_small.model.root.feature_index is None
    assert too_small.model.root.probability == pytest.approx(50.5 / 101)


def test_cart_rejects_one_class_and_never_exceeds_depth_two() -> None:
    """Catches fitting a fake one-class tree or growing beyond the frozen ceiling."""
    models = _models()
    one_class = models.fit_main_force_mirror_cart(
        np.arange(100, dtype=float).reshape(-1, 1),
        np.ones(100),
        feature_count=1,
    )
    assert one_class.model is None
    assert one_class.unavailable_reason.value == "SPLIT_CLASS_UNAVAILABLE"

    x = np.arange(400, dtype=float).reshape(-1, 1)
    y = np.array(([0.0] * 50 + [1.0] * 50) * 4)
    fitted = models.fit_main_force_mirror_cart(x, y, feature_count=1)
    assert fitted.model is not None

    def depth(node) -> int:
        if node.left is None or node.right is None:
            return 0
        return 1 + max(depth(node.left), depth(node.right))

    assert depth(fitted.model.root) <= 2


def test_auc_uses_unweighted_average_ranks_and_one_class_is_unavailable() -> None:
    """Catches weighted AUC, non-average tie ranks, or a fake one-class value."""
    models = _models()
    assert models.main_force_mirror_auc(
        np.array([0, 1, 0, 1]), np.array([0.1, 0.5, 0.5, 0.9])
    ) == pytest.approx(0.875)
    assert models.main_force_mirror_auc(
        np.array([1, 1]), np.array([0.1, 0.9])
    ) is None


def test_product_cluster_bootstrap_is_paired_deterministic_and_typed_by_valid_count() -> None:
    """Catches row bootstrap, independent comparison resamples, or unstable RNG use."""
    models = _models()
    products = np.array([f"p{index}" for index in range(20) for _ in range(10)])
    targets = np.array(([0, 1] * 5) * 20)
    score = np.tile(np.linspace(0.2, 0.8, 10), 20)
    ridge = score + np.where(targets == 1, 0.1, -0.1)
    full = ridge + np.where(targets == 1, 0.05, -0.05)

    first = models.bootstrap_main_force_mirror_auc_deltas(
        targets,
        products,
        {"score": score, "ridge": ridge, "full": full},
        (("ridge", "score"), ("full", "ridge")),
    )
    second = models.bootstrap_main_force_mirror_auc_deltas(
        targets,
        products,
        {"score": score, "ridge": ridge, "full": full},
        (("ridge", "score"), ("full", "ridge")),
    )
    assert first == second
    assert first.valid_count == 2000
    assert first.intervals[("ridge", "score")] is not None
    assert first.intervals[("full", "ridge")] is not None

    unavailable = models.bootstrap_main_force_mirror_auc_deltas(
        np.array([0] * 5 + [1] * 5),
        np.array(["a"] * 5 + ["b"] * 5),
        {"score": np.arange(10), "ridge": np.arange(10)},
        (("ridge", "score"),),
    )
    assert unavailable.valid_count < 1900
    assert unavailable.intervals[("ridge", "score")] is None


def _member_observation(models, **changes: object):
    value = models.MainForceMirrorDiagnosticMemberObservation(
        symbol="jm",
        physical_contract="JM2609",
        anchor_trading_day=date(2025, 6, 2),
        anchor_bar_end=datetime(2025, 6, 2, 1, tzinfo=UTC),
        expected_prior_trading_day=date(2025, 5, 30),
        expected_dataset_id="pinned-v1",
        available=True,
        observed_dataset_id="pinned-v1",
        observed_trade_date=date(2025, 5, 30),
        observed_symbol="jm",
        observed_physical_contract="JM2609",
        observed_rank=1,
    )
    return replace(value, **changes)


def test_member_feasibility_keeps_earliest_without_replacement_and_validates_t_minus_1() -> None:
    """Catches replacing an unavailable earliest episode with later same-day data."""
    models = _models()
    earliest = _member_observation(
        models,
        available=False,
        observed_dataset_id=None,
        observed_trade_date=None,
        observed_symbol=None,
        observed_physical_contract=None,
        observed_rank=None,
    )
    later = _member_observation(
        models,
        anchor_bar_end=earliest.anchor_bar_end + timedelta(hours=1),
    )

    result = models.audit_main_force_mirror_member_feasibility((later, earliest))

    assert result.section.unique_earliest_count == 1
    assert result.section.eligible_count == 0
    assert result.section.t_minus_1_coverage == Decimal("0")
    assert result.unavailable[0].reason.value == "MEMBER_DATASET_UNAVAILABLE"

    causal = models.audit_main_force_mirror_member_feasibility(
        (_member_observation(models, observed_trade_date=date(2025, 5, 29)),)
    )
    assert causal.section.causal_violation_count == 1
    assert causal.section.eligible_count == 0


def test_member_feasibility_requires_pinned_symbol_contract_rank1_identity() -> None:
    """Catches accepting a different dataset, product, physical contract, or rank."""
    models = _models()
    for field, value in (
        ("observed_dataset_id", "newest-v2"),
        ("observed_symbol", "ag"),
        ("observed_physical_contract", "JM2701"),
        ("observed_rank", 2),
    ):
        result = models.audit_main_force_mirror_member_feasibility(
            (_member_observation(models, **{field: value}),)
        )
        assert result.section.identity_violation_count == 1
        assert result.section.eligible_count == 0
        assert result.unavailable[0].reason.value == "MEMBER_IDENTITY_CONFLICT"

    valid = models.audit_main_force_mirror_member_feasibility(
        (_member_observation(models),)
    )
    assert valid.section.unique_earliest_count == 1
    assert valid.section.eligible_count == 1
    assert valid.section.t_minus_1_coverage == Decimal("1")
    assert valid.section.product_count == 1


def test_member_feasibility_is_order_invariant_and_collapses_exact_earliest_duplicates() -> None:
    """Catches order-sensitive earliest selection or double-counting exact ties."""
    models = _models()
    earliest = _member_observation(models)
    duplicate = replace(earliest)
    later = replace(
        earliest,
        anchor_bar_end=earliest.anchor_bar_end + timedelta(hours=1),
        available=False,
        observed_dataset_id=None,
        observed_trade_date=None,
        observed_symbol=None,
        observed_physical_contract=None,
        observed_rank=None,
    )

    forward = models.audit_main_force_mirror_member_feasibility(
        (earliest, duplicate, later)
    )
    reverse = models.audit_main_force_mirror_member_feasibility(
        (later, duplicate, earliest)
    )

    assert forward == reverse
    assert forward.section.unique_earliest_count == 1
    assert forward.section.eligible_count == 1


def test_member_feasibility_rejects_conflicting_earliest_timestamp_ties_in_any_order() -> None:
    """Catches setdefault choosing one of two contradictory earliest snapshots."""
    models = _models()
    available = _member_observation(models)
    unavailable = replace(
        available,
        available=False,
        observed_dataset_id=None,
        observed_trade_date=None,
        observed_symbol=None,
        observed_physical_contract=None,
        observed_rank=None,
    )

    for observations in ((available, unavailable), (unavailable, available)):
        with pytest.raises(ValueError, match="MFM_DIAGNOSTIC_ANALYSIS_INVALID"):
            models.audit_main_force_mirror_member_feasibility(observations)


def test_member_feasibility_treats_boolean_rank_as_identity_violation() -> None:
    """Catches True comparing equal to the exact rank1 identity."""
    models = _models()

    result = models.audit_main_force_mirror_member_feasibility(
        (_member_observation(models, observed_rank=True),)
    )

    assert result.section.eligible_count == 0
    assert result.section.identity_violation_count == 1
    assert result.unavailable[0].reason.value == "MEMBER_IDENTITY_CONFLICT"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("observed_dataset_id", b"pinned-v1"),
        ("observed_trade_date", datetime(2025, 5, 30, tzinfo=UTC)),
        ("observed_symbol", b"jm"),
        ("observed_physical_contract", b"JM2609"),
        ("observed_rank", "1"),
    ),
)
def test_member_feasibility_rejects_malformed_observed_identity_field_types(
    field: str,
    value: object,
) -> None:
    """Catches malformed identity field types being counted as normal mismatches."""
    models = _models()

    with pytest.raises(ValueError, match="MFM_DIAGNOSTIC_ANALYSIS_INVALID"):
        models.audit_main_force_mirror_member_feasibility(
            (_member_observation(models, **{field: value}),)
        )


@pytest.mark.parametrize("container", (None, [], object()))
def test_member_feasibility_rejects_malformed_observation_containers(
    container: object,
) -> None:
    """Catches tuple coercion or raw TypeError for malformed observation input."""
    models = _models()

    with pytest.raises(ValueError, match="MFM_DIAGNOSTIC_ANALYSIS_INVALID"):
        models.audit_main_force_mirror_member_feasibility(container)


def _passing_gate_inputs():
    domain = contract_fixtures._domain()
    policy = contract_fixtures._policy()
    label = contract_fixtures._zero_label(domain)
    global_label = replace(
        label.breakdowns[0],
        raw_sample_count=1000,
        kept_sample_count=1000,
        long_sample_count=500,
        short_sample_count=500,
        binary_evaluable_count=800,
        legacy_long_only_count=1000,
        adverse_first_count=400,
        favorable_first_count=400,
        ambiguous_count=100,
        timeout_count=100,
    )
    label_breakdowns = list(
        contract_fixtures._consistent_partitions(label.breakdowns, global_label)
    )
    label_breakdowns[-2] = replace(global_label, key=label_breakdowns[-2].key)
    label_breakdowns[-1] = replace(global_label, key=label_breakdowns[-1].key)
    label = replace(
        label,
        raw_sample_count=1000,
        sample_count=1000,
        long_sample_count=500,
        short_sample_count=500,
        binary_evaluable_count=800,
        legacy_long_only_count=1000,
        adverse_first_count=400,
        favorable_first_count=400,
        ambiguous_count=100,
        timeout_count=100,
        resolved_coverage=Decimal("0.8"),
        ambiguous_rate=Decimal("0.1"),
        breakdowns=tuple(label_breakdowns),
    )
    sequence = contract_fixtures._zero_sequence(domain)
    profiles = []
    for profile in sequence.profiles:
        global_row = replace(
            profile.breakdowns[0],
            raw_episode_count=200,
            kept_episode_count=200,
            first_evidence_count=200,
            delay_sample_count=200,
            delay_bars_total=400,
        )
        profiles.append(
            replace(
                profile,
                peak_then_decay_sample_count=200,
                long_sample_count=100,
                short_sample_count=100,
                product_count=20,
                year_count=3,
                top_product_share=Decimal("0.2"),
                median_delay_bars=Decimal("2"),
                h3_reversal_hit_rate=Decimal("0.55"),
                h5_reversal_hit_rate=Decimal("0.55"),
                yearly_median_reversal_min=Decimal("0"),
                side_median_reversal_min=Decimal("0"),
                breakdowns=contract_fixtures._consistent_partitions(
                    profile.breakdowns, global_row
                ),
            )
        )
    validation = domain.MainForceMirrorDiagnosticValidationMetadata(
        source_mode="actual_dominant",
        frequency="60m",
        confirmed_only=True,
        active_universe_sha256=contract_fixtures.UNIVERSE_SHA256,
        known_retrospective_through=date(2026, 8, 20),
        prospective_consumed=False,
        available_product_count=60,
        unavailable_product_count=0,
        unknown_failure_count=0,
    )
    member = domain.MainForceMirrorDiagnosticMemberSection(
        unique_earliest_count=100,
        eligible_count=80,
        t_minus_1_coverage=Decimal("0.8"),
        product_count=20,
        causal_violation_count=0,
        identity_violation_count=0,
        member_model_present=False,
    )
    return (
        policy.load_main_force_mirror_diagnostic_protocol(),
        validation,
        label,
        replace(sequence, profiles=tuple(profiles)),
        contract_fixtures._model(domain),
        member,
    )


def _label_with_outcomes(label, *, resolved: int, ambiguous: int):
    adverse = resolved // 2
    favorable = resolved - adverse
    timeout = label.sample_count - resolved - ambiguous
    global_row = replace(
        label.breakdowns[0],
        binary_evaluable_count=resolved,
        adverse_first_count=adverse,
        favorable_first_count=favorable,
        ambiguous_count=ambiguous,
        timeout_count=timeout,
    )
    return replace(
        label,
        binary_evaluable_count=resolved,
        adverse_first_count=adverse,
        favorable_first_count=favorable,
        ambiguous_count=ambiguous,
        timeout_count=timeout,
        resolved_coverage=Decimal(resolved) / Decimal(label.sample_count),
        ambiguous_rate=Decimal(ambiguous) / Decimal(label.sample_count),
        breakdowns=contract_fixtures._consistent_partitions(
            label.breakdowns, global_row
        ),
    )


def test_gate_accepts_every_threshold_at_equality_and_is_deterministic() -> None:
    """Catches strict comparisons at inclusive floors or result instability."""
    models = _models()
    inputs = _passing_gate_inputs()
    first = models.evaluate_main_force_mirror_diagnostic_gate(*inputs)
    second = models.evaluate_main_force_mirror_diagnostic_gate(*inputs)
    assert first == second
    assert first.gate.value == "ALLOW_PHASE_FREEZE_DESIGN"
    assert first.reasons == ()


@pytest.mark.parametrize(
    ("kind", "expected"),
    (
        ("source", "SOURCE_UNAVAILABLE_PRESENT"),
        ("fit_count", "SAMPLE_FLOOR_FAILED"),
        ("fit_class", "SAMPLE_FLOOR_FAILED"),
        ("evaluate_count", "SAMPLE_FLOOR_FAILED"),
        ("evaluate_class", "SAMPLE_FLOOR_FAILED"),
        ("evaluate_side", "SAMPLE_FLOOR_FAILED"),
        ("evaluate_products", "SAMPLE_FLOOR_FAILED"),
        ("coverage", "BINARY_COVERAGE_INSUFFICIENT"),
        ("fold_coverage", "BINARY_COVERAGE_INSUFFICIENT"),
        ("ambiguous", "AMBIGUOUS_RATE_EXCEEDED"),
        ("fold_ambiguous", "AMBIGUOUS_RATE_EXCEEDED"),
        ("sequence_sample", "SEQUENCE_UNSTABLE"),
        ("sequence_side", "SEQUENCE_UNSTABLE"),
        ("sequence_product", "SEQUENCE_UNSTABLE"),
        ("sequence_year", "SEQUENCE_UNSTABLE"),
        ("sequence_share", "SEQUENCE_UNSTABLE"),
        ("sequence_delay", "SEQUENCE_UNSTABLE"),
        ("sequence_h3", "SEQUENCE_UNSTABLE"),
        ("sequence_h5", "SEQUENCE_UNSTABLE"),
        ("sequence_median", "SEQUENCE_UNSTABLE"),
        ("ridge_delta", "RIDGE_INCREMENT_INSUFFICIENT"),
        ("ridge_ci", "RIDGE_INCREMENT_INSUFFICIENT"),
        ("nonlinear_delta", "NONLINEAR_INCREMENT_INSUFFICIENT"),
        ("nonlinear_ci", "NONLINEAR_INCREMENT_INSUFFICIENT"),
        ("sequence_delta", "SEQUENCE_INCREMENT_INSUFFICIENT"),
        ("sequence_ci", "SEQUENCE_INCREMENT_INSUFFICIENT"),
        ("full_auc", "NONLINEAR_AUC_INSUFFICIENT"),
        ("side_auc", "SIDE_GUARDRAIL_FAILED"),
        ("side_delta", "SIDE_GUARDRAIL_FAILED"),
        ("bootstrap", "MODEL_UNAVAILABLE"),
        ("member_coverage", "MEMBER_FEASIBILITY_INSUFFICIENT"),
        ("member_products", "MEMBER_FEASIBILITY_INSUFFICIENT"),
        ("member_causal", "MEMBER_FEASIBILITY_INSUFFICIENT"),
        ("member_identity", "MEMBER_FEASIBILITY_INSUFFICIENT"),
    ),
)
def test_gate_each_just_below_threshold_adds_the_stable_reason(
    kind: str, expected: str
) -> None:
    """Catches silently weakening any frozen Gate threshold."""
    models = _models()
    protocol, validation, label, sequence, model, member = _passing_gate_inputs()
    if kind == "source":
        validation = replace(
            validation, available_product_count=59, unavailable_product_count=1
        )
    elif kind == "coverage":
        label = _label_with_outcomes(label, resolved=499, ambiguous=100)
    elif kind == "fold_coverage":
        rows = list(label.breakdowns)
        rows[-2] = replace(
            rows[-2],
            binary_evaluable_count=499,
            adverse_first_count=249,
            favorable_first_count=250,
            timeout_count=401,
        )
        label = replace(label, breakdowns=tuple(rows))
    elif kind == "ambiguous":
        label = _label_with_outcomes(label, resolved=800, ambiguous=151)
    elif kind == "fold_ambiguous":
        rows = list(label.breakdowns)
        rows[-2] = replace(
            rows[-2],
            ambiguous_count=151,
            timeout_count=49,
        )
        label = replace(label, breakdowns=tuple(rows))
    elif kind in {
        "sequence_sample", "sequence_side", "sequence_product", "sequence_year",
        "sequence_share", "sequence_delay", "sequence_h3", "sequence_h5",
        "sequence_median",
    }:
        field_values = {
            "sequence_sample": ("peak_then_decay_sample_count", 199),
            "sequence_side": ("long_sample_count", 49),
            "sequence_product": ("product_count", 19),
            "sequence_year": ("year_count", 2),
            "sequence_share": ("top_product_share", Decimal("0.201")),
            "sequence_delay": ("median_delay_bars", Decimal("2.001")),
            "sequence_h3": ("h3_reversal_hit_rate", Decimal("0.549")),
            "sequence_h5": ("h5_reversal_hit_rate", Decimal("0.549")),
            "sequence_median": ("yearly_median_reversal_min", Decimal("-0.001")),
        }
        field, value = field_values[kind]
        extra = {}
        if kind == "sequence_sample":
            extra = {"long_sample_count": 99, "short_sample_count": 100}
        elif kind == "sequence_side":
            extra = {"short_sample_count": 151}
        sequence = replace(
            sequence,
            profiles=tuple(
                replace(item, **{field: value}, **extra)
                for item in sequence.profiles
            ),
        )
    elif kind.startswith("member_"):
        if kind == "member_coverage":
            member = replace(
                member, eligible_count=79, t_minus_1_coverage=Decimal("0.79")
            )
        elif kind == "member_products":
            member = replace(member, product_count=19)
        elif kind == "member_causal":
            member = replace(member, causal_violation_count=1)
        else:
            member = replace(member, identity_violation_count=1)
    else:
        fold = model.folds[0]
        field_values = {
            "fit_count": ("fit_binary_count", 499),
            "fit_class": ("fit_positive_count", 99),
            "evaluate_count": ("evaluate_binary_count", 199),
            "evaluate_class": ("evaluate_positive_count", 49),
            "evaluate_side": ("evaluate_long_count", 49),
            "evaluate_products": ("evaluate_product_count", 19),
            "ridge_delta": ("ridge_score_delta", Decimal("0.019")),
            "ridge_ci": ("ridge_score_ci_lower", Decimal("0")),
            "nonlinear_delta": ("full_tree_ridge_delta", Decimal("0.019")),
            "nonlinear_ci": ("full_tree_ridge_ci_lower", Decimal("0")),
            "sequence_delta": ("full_tree_current_tree_delta", Decimal("0.009")),
            "sequence_ci": ("full_tree_current_tree_ci_lower", Decimal("0")),
            "full_auc": ("full_tree_auc", Decimal("0.599")),
            "side_auc": ("long_auc", Decimal("0.549")),
            "side_delta": ("long_point_delta", Decimal("-0.001")),
            "bootstrap": ("bootstrap_valid_count", 1899),
        }
        field, value = field_values[kind]
        if kind == "fit_count":
            fold = replace(
                fold,
                fit_binary_count=499,
                fit_negative_count=400,
                fit_positive_count=99,
            )
        elif kind == "fit_class":
            fold = replace(fold, fit_negative_count=401, fit_positive_count=99)
        elif kind == "evaluate_count":
            fold = replace(
                fold,
                evaluate_binary_count=199,
                evaluate_negative_count=100,
                evaluate_positive_count=99,
                evaluate_long_count=99,
                evaluate_short_count=100,
            )
        elif kind == "evaluate_class":
            fold = replace(fold, evaluate_negative_count=151, evaluate_positive_count=49)
        elif kind == "evaluate_side":
            fold = replace(fold, evaluate_long_count=49, evaluate_short_count=151)
        else:
            fold = replace(fold, **{field: value})
        model = replace(model, folds=(fold, model.folds[1]))
    decision = models.evaluate_main_force_mirror_diagnostic_gate(
        protocol, validation, label, sequence, model, member
    )
    assert expected in tuple(reason.value for reason in decision.reasons)
    assert decision.gate.value == "STOP"


def test_gate_accumulates_all_reasons_in_enum_order_and_corruption_has_no_gate() -> None:
    """Catches early-return Gate logic or converting protocol corruption into STOP."""
    models = _models()
    protocol, validation, label, sequence, model, member = _passing_gate_inputs()
    validation = replace(
        validation, available_product_count=47, unavailable_product_count=13
    )
    label = _label_with_outcomes(label, resolved=490, ambiguous=160)
    sequence = replace(
        sequence,
        profiles=tuple(
            replace(
                item,
                peak_then_decay_sample_count=199,
                long_sample_count=99,
                short_sample_count=100,
            )
            for item in sequence.profiles
        ),
    )
    fold = replace(
        model.folds[0],
        fit_negative_count=401,
        fit_positive_count=99,
        ridge_score_delta=Decimal("0.01"),
        full_tree_ridge_delta=Decimal("0.01"),
        full_tree_current_tree_delta=Decimal("0"),
        full_tree_auc=Decimal("0.5"),
        long_auc=Decimal("0.5"),
        bootstrap_valid_count=1800,
    )
    model = replace(model, folds=(fold, model.folds[1]))
    member = replace(member, product_count=19)

    decision = models.evaluate_main_force_mirror_diagnostic_gate(
        protocol, validation, label, sequence, model, member
    )
    values = tuple(reason.value for reason in decision.reasons)
    enum_order = tuple(reason.value for reason in contract_fixtures._domain().MainForceMirrorDiagnosticGateReason)
    assert values == tuple(value for value in enum_order if value in values)
    assert len(values) > 8

    with pytest.raises(Exception, match="MFM_DIAGNOSTIC_PROTOCOL_INVALID"):
        models.evaluate_main_force_mirror_diagnostic_gate(
            object(), validation, label, sequence, model, member
        )


def _model_sample(models, index: int, target: int, day: date):
    values = np.zeros(33, dtype=float)
    values[0] = 20.0 + 60.0 * target
    values[1] = float(index % 7)
    values[2:] = np.linspace(0.0, 1.0, 31) + (index % 5) * 0.01
    return models.MainForceMirrorDiagnosticModelSample(
        symbol=f"{contract_fixtures.PRODUCTS[index % 20]}",
        physical_contract="JM2609",
        anchor_trading_day=day,
        side=(
            MainForceMirrorDiagnosticSide.LONG
            if index % 2 == 0
            else MainForceMirrorDiagnosticSide.SHORT
        ),
        target=target,
        features=tuple(values),
    )


def test_model_diagnostic_trains_fixed_variants_and_repeats_exact_output() -> None:
    """Catches model search, shared-fold preprocessing, or nondeterministic output."""
    models = _models()
    folds = []
    for fold, evaluate_day in ((1, date(2025, 6, 2)), (2, date(2026, 6, 2))):
        fit = tuple(
            _model_sample(models, index, index % 2, date(2024, 6, 2))
            for index in range(500)
        )
        evaluate = tuple(
            _model_sample(models, index, index % 2, evaluate_day)
            for index in range(200)
        )
        folds.append(models.MainForceMirrorDiagnosticFoldDataset(fold, fit, evaluate))
    datasets = models.MainForceMirrorDiagnosticFoldDatasets(tuple(folds), ())

    first = models.run_main_force_mirror_model_diagnostics(datasets)
    second = models.run_main_force_mirror_model_diagnostics(datasets)

    assert first == second
    assert tuple(item.fold for item in first.section.folds) == (1, 2)
    assert all(item.fit_binary_count == 500 for item in first.section.folds)
    assert all(item.evaluate_binary_count == 200 for item in first.section.folds)
    assert all(item.bootstrap_valid_count == 2000 for item in first.section.folds)
    assert all(item.score_auc == Decimal("1.0") for item in first.section.folds)
    assert all(item.ridge_auc == Decimal("1.0") for item in first.section.folds)
    assert all(item.current_tree_auc == Decimal("1.0") for item in first.section.folds)
    assert all(item.full_tree_auc == Decimal("1.0") for item in first.section.folds)
    assert first.section.breakdowns[0].sample_count == 400
    assert first.section.breakdowns[-2].sample_count == 200
    assert first.section.breakdowns[-1].sample_count == 200


def test_model_diagnostic_types_insufficient_cluster_bootstrap_without_fake_ci() -> None:
    """Catches emitting a fake CI when fewer than 1900 paired resamples are valid."""
    models = _models()
    fit = tuple(
        _model_sample(models, index, index % 2, date(2024, 6, 2))
        for index in range(500)
    )
    evaluate = tuple(
        replace(
            _model_sample(models, index, index // 100, date(2025, 6, 2)),
            symbol="a" if index < 100 else "ag",
        )
        for index in range(200)
    )
    datasets = models.MainForceMirrorDiagnosticFoldDatasets(
        (
            models.MainForceMirrorDiagnosticFoldDataset(1, fit, evaluate),
            models.MainForceMirrorDiagnosticFoldDataset(
                2,
                fit,
                tuple(
                    replace(item, anchor_trading_day=date(2026, 6, 2))
                    for item in evaluate
                ),
            ),
        ),
        (),
    )

    result = models.run_main_force_mirror_model_diagnostics(datasets)

    assert result.section.folds[0].bootstrap_valid_count < 1900
    assert result.section.folds[0].ridge_score_ci_lower is None
    assert result.section.folds[0].model_unavailable_reason.value == (
        "SPLIT_CLASS_UNAVAILABLE"
    )


def test_one_class_fold_and_same_fold_breakdown_share_split_unavailability() -> None:
    """Catches rewriting a split insufficiency as model convergence failure."""
    models = _models()
    fit = tuple(
        _model_sample(models, index, index % 2, date(2024, 6, 2))
        for index in range(200)
    )
    one_class = tuple(
        _model_sample(models, index, 0, date(2025, 6, 2))
        for index in range(100)
    )
    datasets = models.MainForceMirrorDiagnosticFoldDatasets(
        (
            models.MainForceMirrorDiagnosticFoldDataset(1, fit, one_class),
            models.MainForceMirrorDiagnosticFoldDataset(2, (), ()),
        ),
        (),
    )

    result = models.run_main_force_mirror_model_diagnostics(datasets)
    fold_section = result.section.folds[0]
    fold_breakdown = next(
        item for item in result.section.breakdowns if item.key.fold == 1
    )

    assert fold_section.model_unavailable_reason.value == "SPLIT_CLASS_UNAVAILABLE"
    assert fold_breakdown.unavailable_reason == fold_section.model_unavailable_reason


def test_model_diagnostic_rejects_samples_outside_the_fixed_fold_segment() -> None:
    """Catches relabeling an out-of-window row as fit or evaluate evidence."""
    models = _models()
    fit = tuple(
        _model_sample(models, index, index % 2, date(2024, 6, 2))
        for index in range(100)
    )
    wrong_evaluate = tuple(
        _model_sample(models, index, index % 2, date(2024, 12, 31))
        for index in range(100)
    )
    datasets = models.MainForceMirrorDiagnosticFoldDatasets(
        (
            models.MainForceMirrorDiagnosticFoldDataset(1, fit, wrong_evaluate),
            models.MainForceMirrorDiagnosticFoldDataset(2, fit, ()),
        ),
        (),
    )

    with pytest.raises(ValueError, match="MFM_DIAGNOSTIC_ANALYSIS_INVALID"):
        models.run_main_force_mirror_model_diagnostics(datasets)


def test_model_diagnostic_rejects_non_sample_input_with_stable_analysis_error() -> None:
    """Catches leaking AttributeError for a corrupt fold payload."""
    models = _models()
    datasets = models.MainForceMirrorDiagnosticFoldDatasets(
        (
            models.MainForceMirrorDiagnosticFoldDataset(1, (object(),), ()),
            models.MainForceMirrorDiagnosticFoldDataset(2, (), ()),
        ),
        (),
    )

    with pytest.raises(ValueError, match="MFM_DIAGNOSTIC_ANALYSIS_INVALID"):
        models.run_main_force_mirror_model_diagnostics(datasets)


@pytest.mark.parametrize("kind", ("bool_fold", "bool_target"))
def test_model_diagnostic_rejects_boolean_structural_integers(kind: str) -> None:
    """Catches Python bool values passing exact fold/target integer identity."""
    models = _models()
    fit = tuple(
        _model_sample(models, index, index % 2, date(2024, 6, 2))
        for index in range(100)
    )
    if kind == "bool_target":
        fit = (replace(fit[0], target=True), *fit[1:])
    folds = (
        models.MainForceMirrorDiagnosticFoldDataset(
            True if kind == "bool_fold" else 1,
            fit,
            (),
        ),
        models.MainForceMirrorDiagnosticFoldDataset(2, (), ()),
    )

    with pytest.raises(ValueError, match="MFM_DIAGNOSTIC_ANALYSIS_INVALID"):
        models.run_main_force_mirror_model_diagnostics(
            models.MainForceMirrorDiagnosticFoldDatasets(folds, ())
        )
