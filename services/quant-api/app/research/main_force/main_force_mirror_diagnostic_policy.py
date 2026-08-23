"""Frozen read-only protocol for Main Force Mirror diagnostic Phase A."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.core.env import PROJECT_ROOT  # type: ignore[import-untyped]
from app.core.exact_json_contract import load_exact_json  # type: ignore[import-untyped]
from app.market_data.operational_universe import (  # type: ignore[import-untyped]
    ActiveUniverseError,
    load_active_products,
)


PROTOCOL_ID = "main_force_mirror_diagnostic_phase_a_v1"
PROTOCOL_PATH = (
    PROJECT_ROOT
    / "data/research_protocols/main_force_mirror_diagnostic_phase_a_v1.json"
)
ACTIVE_PRODUCTS_PATH = PROJECT_ROOT / "data/universe/active_products.txt"
_PRODUCTS = (
    "a", "ag", "al", "ao", "ap", "au", "b", "bu", "bz", "c",
    "cf", "cj", "cu", "eb", "ec", "eg", "fg", "fu", "hc", "i",
    "j", "jd", "jm", "l", "lc", "lh", "m", "ma", "ni", "oi",
    "p", "pb", "pd", "pf", "pg", "pk", "pl", "pp", "pr", "ps",
    "pt", "px", "rb", "rm", "rs", "ru", "sa", "sc", "sf", "sh",
    "si", "sm", "sn", "sr", "ss", "ta", "ur", "v", "y", "zn",
)
_UNIVERSE_SHA256 = "d2f7e8387fa9dd92b8720ed703de3a7bbc1ef79d0d75340b246783bab079fd1d"
_PROFILES = ("balanced", "fast", "slow", "loose", "strict")
_EXPECTED_PROTOCOL: MainForceMirrorDiagnosticProtocol | None = None
_EXPECTED: dict[str, Any] = {
    "schema_version": 1,
    "protocol_id": PROTOCOL_ID,
    "model_subprotocol": "mfm_v3_readonly_training_probe_v1",
    "research_only": True,
    "readonly": True,
    "previous_missing_probe_result_inherited": False,
    "source": {
        "mode": "actual_dominant",
        "frequency": "60m",
        "confirmed_only": True,
    },
    "windows": {
        "jm_view": {"since": "2026-03-10", "through": "2026-03-30"},
        "active60": {"since": "2023-01-01", "through": "2026-08-18"},
        "known_retrospective_through": "2026-08-20",
        "prospective": {"begins_after": "2026-08-20", "consumed": False},
    },
    "universe": {
        "products": list(_PRODUCTS),
        "source_path": "data/universe/active_products.txt",
        "source_sha256": _UNIVERSE_SHA256,
    },
    "label": {"horizon_bars": 10, "barrier_atr_multiple": 1.0},
    "sequence": {"profile_ids": list(_PROFILES)},
    "models": {
        "score_baseline": {"model_id": "score_baseline"},
        "ridge_logistic": {
            "model_id": "ridge_logistic",
            "l2": 1.0,
            "max_iterations": 100,
            "logit_clip": [-35, 35],
            "step_tolerance": 1e-8,
        },
        "deterministic_cart": {
            "model_id": "deterministic_depth_2_cart",
            "depth": 2,
            "train_quantiles": [0.25, 0.50, 0.75],
            "min_leaf": 50,
            "impurity": "weighted_gini",
            "leaf_smoothing": "laplace",
        },
    },
    "bootstrap": {
        "resamples": 2000,
        "seed": 20260823,
        "minimum_valid": 1900,
        "ci": 0.95,
    },
    "folds": [
        {
            "fit": {"since": "2023-01-01", "through": "2024-12-31"},
            "evaluate": {"since": "2025-01-01", "through": "2025-12-31"},
        },
        {
            "fit": {"since": "2023-01-01", "through": "2025-12-31"},
            "evaluate": {"since": "2026-01-01", "through": "2026-08-18"},
        },
    ],
    "sample_floors": {
        "available_products": 48,
        "fit_binary": 500,
        "fit_each_class": 100,
        "evaluate_binary": 200,
        "evaluate_each_class": 50,
        "evaluate_each_side": 50,
        "evaluate_products": 20,
        "resolved_coverage": 0.50,
        "ambiguous_maximum": 0.15,
        "unknown_failures": 0,
    },
    "gate_thresholds": {
        "sequence": {
            "required_profiles": 3,
            "balanced_required": True,
            "peak_then_decay_pooled": 200,
            "each_side": 50,
            "products": 20,
            "years": 3,
            "top_product_share_maximum": 0.20,
            "median_delay_maximum_bars": 2,
            "h3_h5_reversal_hit_minimum": 0.55,
            "yearly_side_median_minimum": 0,
        },
        "model": {
            "both_folds_required": True,
            "ridge_score_delta": 0.02,
            "ridge_score_ci_lower_strictly_positive": True,
            "full_tree_ridge_delta": 0.02,
            "full_tree_ridge_ci_lower_strictly_positive": True,
            "full_tree_current_tree_delta": 0.01,
            "full_tree_current_tree_ci_lower_strictly_positive": True,
            "full_tree_auc": 0.60,
            "supported_side_auc": 0.55,
            "supported_side_point_delta_minimum": 0,
        },
        "member_feasibility": {
            "unique_earliest_key": [
                "symbol", "physical_contract", "anchor_trading_day"
            ],
            "t_minus_1_coverage": 0.80,
            "products": 20,
            "causal_violations": 0,
            "identity_violations": 0,
            "member_model": False,
        },
    },
    "gate": {
        "normal_insufficiency": "STOP",
        "corruption_behavior": "error_no_gate",
        "allowed_values": ["STOP", "ALLOW_PHASE_FREEZE_DESIGN"],
    },
    "exclusions": {
        "formula_change": False,
        "threshold_change": False,
        "profile_change": False,
        "database_writes": False,
        "data_writes": False,
        "runtime_writes": False,
        "alert_writes": False,
        "rqdata_run": False,
        "real_evidence_run": False,
        "sklearn_dependency": False,
        "scipy_dependency": False,
        "new_dependency": False,
        "trading_output": False,
        "performance_output": False,
        "ranking_output": False,
        "promotion_output": False,
    },
}


class MainForceMirrorDiagnosticProtocolError(ValueError):
    code = "MFM_DIAGNOSTIC_PROTOCOL_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class MainForceMirrorDiagnosticActiveUniverseError(ValueError):
    code = "MFM_DIAGNOSTIC_ACTIVE_UNIVERSE_DRIFT"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticFold:
    fit_since: date
    fit_through: date
    evaluate_since: date
    evaluate_through: date


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticProtocol:
    schema_version: int
    protocol_id: str
    model_subprotocol: str
    research_only: bool
    readonly: bool
    previous_missing_probe_result_inherited: bool
    source_mode: str
    frequency: str
    confirmed_only: bool
    jm_since: date
    jm_through: date
    active60_since: date
    active60_through: date
    known_retrospective_through: date
    prospective_begins_after: date
    prospective_consumed: bool
    products: tuple[str, ...]
    active_universe_source_path: str
    active_universe_sha256: str
    label_horizon_bars: int
    barrier_atr_multiple: Decimal
    sequence_profile_ids: tuple[str, ...]
    score_model_id: str
    ridge_model_id: str
    ridge_l2: Decimal
    ridge_max_iterations: int
    ridge_logit_clip: tuple[Decimal, Decimal]
    ridge_step_tolerance: Decimal
    cart_model_id: str
    cart_depth: int
    cart_train_quantiles: tuple[Decimal, ...]
    cart_min_leaf: int
    cart_impurity: str
    cart_leaf_smoothing: str
    bootstrap_resamples: int
    bootstrap_seed: int
    bootstrap_minimum_valid: int
    bootstrap_ci: Decimal
    folds: tuple[MainForceMirrorDiagnosticFold, ...]
    available_products_floor: int
    fit_binary_floor: int
    fit_each_class_floor: int
    evaluate_binary_floor: int
    evaluate_each_class_floor: int
    evaluate_each_side_floor: int
    evaluate_products_floor: int
    resolved_coverage_floor: Decimal
    ambiguous_rate_maximum: Decimal
    unknown_failures_maximum: int
    sequence_required_profiles: int
    sequence_balanced_required: bool
    sequence_peak_then_decay_pooled_floor: int
    sequence_each_side_floor: int
    sequence_products_floor: int
    sequence_years_floor: int
    sequence_top_product_share_maximum: Decimal
    sequence_median_delay_maximum_bars: Decimal
    sequence_h3_h5_reversal_hit_floor: Decimal
    sequence_yearly_side_median_floor: Decimal
    model_both_folds_required: bool
    ridge_score_delta_floor: Decimal
    ridge_score_ci_lower_strictly_positive: bool
    full_tree_ridge_delta_floor: Decimal
    full_tree_ridge_ci_lower_strictly_positive: bool
    full_tree_current_tree_delta_floor: Decimal
    full_tree_current_tree_ci_lower_strictly_positive: bool
    full_tree_auc_floor: Decimal
    supported_side_auc_floor: Decimal
    supported_side_point_delta_floor: Decimal
    member_unique_key: tuple[str, ...]
    member_t_minus_1_coverage_floor: Decimal
    member_products_floor: int
    member_causal_violations_maximum: int
    member_identity_violations_maximum: int
    member_model_allowed: bool
    normal_insufficiency_gate: str
    corruption_behavior: str
    allowed_gates: tuple[str, ...]
    formula_change_allowed: bool
    threshold_change_allowed: bool
    profile_change_allowed: bool
    database_writes_allowed: bool
    data_writes_allowed: bool
    runtime_writes_allowed: bool
    alert_writes_allowed: bool
    rqdata_run_allowed: bool
    real_evidence_run_allowed: bool
    sklearn_dependency_allowed: bool
    scipy_dependency_allowed: bool
    new_dependency_allowed: bool
    trading_output_allowed: bool
    performance_output_allowed: bool
    ranking_output_allowed: bool
    promotion_output_allowed: bool

    def __post_init__(self) -> None:
        if _EXPECTED_PROTOCOL is not None:
            require_exact_main_force_mirror_diagnostic_protocol(self)


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticRequest:
    protocol_id: str

    def __post_init__(self) -> None:
        if self.protocol_id != PROTOCOL_ID:
            raise MainForceMirrorDiagnosticProtocolError()


def require_exact_main_force_mirror_diagnostic_protocol(
    value: object,
) -> MainForceMirrorDiagnosticProtocol:
    if not isinstance(value, MainForceMirrorDiagnosticProtocol):
        raise MainForceMirrorDiagnosticProtocolError()
    if _EXPECTED_PROTOCOL is None or value != _EXPECTED_PROTOCOL:
        raise MainForceMirrorDiagnosticProtocolError()
    return value


def load_main_force_mirror_diagnostic_protocol(
    path: Path | None = None,
) -> MainForceMirrorDiagnosticProtocol:
    payload = load_exact_json(
        path or PROTOCOL_PATH,
        _EXPECTED,
        MainForceMirrorDiagnosticProtocolError,
    )
    protocol = _protocol_from_payload(payload)
    _require_current_active_universe(protocol)
    return protocol


def _protocol_from_payload(payload: dict[str, Any]) -> MainForceMirrorDiagnosticProtocol:
    source = payload["source"]
    windows = payload["windows"]
    universe = payload["universe"]
    label = payload["label"]
    models = payload["models"]
    ridge = models["ridge_logistic"]
    cart = models["deterministic_cart"]
    bootstrap = payload["bootstrap"]
    floors = payload["sample_floors"]
    thresholds = payload["gate_thresholds"]
    sequence = thresholds["sequence"]
    model = thresholds["model"]
    member = thresholds["member_feasibility"]
    gate = payload["gate"]
    exclusions = payload["exclusions"]
    return MainForceMirrorDiagnosticProtocol(
        schema_version=payload["schema_version"],
        protocol_id=payload["protocol_id"],
        model_subprotocol=payload["model_subprotocol"],
        research_only=payload["research_only"],
        readonly=payload["readonly"],
        previous_missing_probe_result_inherited=payload[
            "previous_missing_probe_result_inherited"
        ],
        source_mode=source["mode"],
        frequency=source["frequency"],
        confirmed_only=source["confirmed_only"],
        jm_since=date.fromisoformat(windows["jm_view"]["since"]),
        jm_through=date.fromisoformat(windows["jm_view"]["through"]),
        active60_since=date.fromisoformat(windows["active60"]["since"]),
        active60_through=date.fromisoformat(windows["active60"]["through"]),
        known_retrospective_through=date.fromisoformat(
            windows["known_retrospective_through"]
        ),
        prospective_begins_after=date.fromisoformat(
            windows["prospective"]["begins_after"]
        ),
        prospective_consumed=windows["prospective"]["consumed"],
        products=tuple(universe["products"]),
        active_universe_source_path=universe["source_path"],
        active_universe_sha256=universe["source_sha256"],
        label_horizon_bars=label["horizon_bars"],
        barrier_atr_multiple=Decimal(str(label["barrier_atr_multiple"])),
        sequence_profile_ids=tuple(payload["sequence"]["profile_ids"]),
        score_model_id=models["score_baseline"]["model_id"],
        ridge_model_id=ridge["model_id"],
        ridge_l2=Decimal(str(ridge["l2"])),
        ridge_max_iterations=ridge["max_iterations"],
        ridge_logit_clip=(
            Decimal(str(ridge["logit_clip"][0])),
            Decimal(str(ridge["logit_clip"][1])),
        ),
        ridge_step_tolerance=Decimal(str(ridge["step_tolerance"])),
        cart_model_id=cart["model_id"],
        cart_depth=cart["depth"],
        cart_train_quantiles=tuple(
            Decimal(str(item)) for item in cart["train_quantiles"]
        ),
        cart_min_leaf=cart["min_leaf"],
        cart_impurity=cart["impurity"],
        cart_leaf_smoothing=cart["leaf_smoothing"],
        bootstrap_resamples=bootstrap["resamples"],
        bootstrap_seed=bootstrap["seed"],
        bootstrap_minimum_valid=bootstrap["minimum_valid"],
        bootstrap_ci=Decimal(str(bootstrap["ci"])),
        folds=tuple(
            MainForceMirrorDiagnosticFold(
                fit_since=date.fromisoformat(fold["fit"]["since"]),
                fit_through=date.fromisoformat(fold["fit"]["through"]),
                evaluate_since=date.fromisoformat(fold["evaluate"]["since"]),
                evaluate_through=date.fromisoformat(fold["evaluate"]["through"]),
            )
            for fold in payload["folds"]
        ),
        available_products_floor=floors["available_products"],
        fit_binary_floor=floors["fit_binary"],
        fit_each_class_floor=floors["fit_each_class"],
        evaluate_binary_floor=floors["evaluate_binary"],
        evaluate_each_class_floor=floors["evaluate_each_class"],
        evaluate_each_side_floor=floors["evaluate_each_side"],
        evaluate_products_floor=floors["evaluate_products"],
        resolved_coverage_floor=Decimal(str(floors["resolved_coverage"])),
        ambiguous_rate_maximum=Decimal(str(floors["ambiguous_maximum"])),
        unknown_failures_maximum=floors["unknown_failures"],
        sequence_required_profiles=sequence["required_profiles"],
        sequence_balanced_required=sequence["balanced_required"],
        sequence_peak_then_decay_pooled_floor=sequence["peak_then_decay_pooled"],
        sequence_each_side_floor=sequence["each_side"],
        sequence_products_floor=sequence["products"],
        sequence_years_floor=sequence["years"],
        sequence_top_product_share_maximum=Decimal(
            str(sequence["top_product_share_maximum"])
        ),
        sequence_median_delay_maximum_bars=Decimal(
            str(sequence["median_delay_maximum_bars"])
        ),
        sequence_h3_h5_reversal_hit_floor=Decimal(
            str(sequence["h3_h5_reversal_hit_minimum"])
        ),
        sequence_yearly_side_median_floor=Decimal(
            str(sequence["yearly_side_median_minimum"])
        ),
        model_both_folds_required=model["both_folds_required"],
        ridge_score_delta_floor=Decimal(str(model["ridge_score_delta"])),
        ridge_score_ci_lower_strictly_positive=model[
            "ridge_score_ci_lower_strictly_positive"
        ],
        full_tree_ridge_delta_floor=Decimal(str(model["full_tree_ridge_delta"])),
        full_tree_ridge_ci_lower_strictly_positive=model[
            "full_tree_ridge_ci_lower_strictly_positive"
        ],
        full_tree_current_tree_delta_floor=Decimal(
            str(model["full_tree_current_tree_delta"])
        ),
        full_tree_current_tree_ci_lower_strictly_positive=model[
            "full_tree_current_tree_ci_lower_strictly_positive"
        ],
        full_tree_auc_floor=Decimal(str(model["full_tree_auc"])),
        supported_side_auc_floor=Decimal(str(model["supported_side_auc"])),
        supported_side_point_delta_floor=Decimal(
            str(model["supported_side_point_delta_minimum"])
        ),
        member_unique_key=tuple(member["unique_earliest_key"]),
        member_t_minus_1_coverage_floor=Decimal(str(member["t_minus_1_coverage"])),
        member_products_floor=member["products"],
        member_causal_violations_maximum=member["causal_violations"],
        member_identity_violations_maximum=member["identity_violations"],
        member_model_allowed=member["member_model"],
        normal_insufficiency_gate=gate["normal_insufficiency"],
        corruption_behavior=gate["corruption_behavior"],
        allowed_gates=tuple(gate["allowed_values"]),
        formula_change_allowed=exclusions["formula_change"],
        threshold_change_allowed=exclusions["threshold_change"],
        profile_change_allowed=exclusions["profile_change"],
        database_writes_allowed=exclusions["database_writes"],
        data_writes_allowed=exclusions["data_writes"],
        runtime_writes_allowed=exclusions["runtime_writes"],
        alert_writes_allowed=exclusions["alert_writes"],
        rqdata_run_allowed=exclusions["rqdata_run"],
        real_evidence_run_allowed=exclusions["real_evidence_run"],
        sklearn_dependency_allowed=exclusions["sklearn_dependency"],
        scipy_dependency_allowed=exclusions["scipy_dependency"],
        new_dependency_allowed=exclusions["new_dependency"],
        trading_output_allowed=exclusions["trading_output"],
        performance_output_allowed=exclusions["performance_output"],
        ranking_output_allowed=exclusions["ranking_output"],
        promotion_output_allowed=exclusions["promotion_output"],
    )


def _require_current_active_universe(
    protocol: MainForceMirrorDiagnosticProtocol,
) -> None:
    try:
        products = load_active_products(ACTIVE_PRODUCTS_PATH)
        digest = sha256(ACTIVE_PRODUCTS_PATH.read_bytes()).hexdigest()
    except (ActiveUniverseError, OSError):
        raise MainForceMirrorDiagnosticActiveUniverseError() from None
    if products != protocol.products or digest != protocol.active_universe_sha256:
        raise MainForceMirrorDiagnosticActiveUniverseError()


_EXPECTED_PROTOCOL = _protocol_from_payload(_EXPECTED)
