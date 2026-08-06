"""Read-only evidence audit for actual rank-one dominant-contract rolls.

The module intentionally has no market-data provider client dependency.  A
formal run reads a bounded PostgreSQL snapshot, verifies local evidence, and
writes a new report bundle.  It never promotes or repairs production facts.
"""

from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
import csv
from dataclasses import dataclass
from datetime import date, datetime, time
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Iterable, Iterator, Literal, Sequence

from sqlalchemy import func, or_, select, text, tuple_
from sqlalchemy.orm import Session

from app.models.data_center import (
    Contract,
    DataQualityReport,
    FeeMarginRule,
    FuturesTradingParameter,
    MainContractMap,
    MarketDataFile,
    TradingCalendar,
)


ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED = "ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED"
ACTUAL_DOMINANT_ROLL_REPAIR_REQUIRED = "ACTUAL_DOMINANT_ROLL_REPAIR_REQUIRED"
PROVIDER = "rqdata"
RULE = "volume_open_interest"
RANK = 1
FIXED_AUDIT_END = date(2026, 7, 10)
CANONICAL_PRODUCT_COUNT = 69
CANONICAL_UNIVERSE_PATH = Path("data/universe/active_products.txt")
JM_SIGNAL_START = date(2023, 1, 3)
JM_BACKTEST_START = date(2023, 6, 28)
JM_BACKTEST_END = date(2026, 6, 26)
QUERY_BATCH_SIZE = 500

REQUIRED_REPORTS = (
    "rank1_uniqueness.csv",
    "rank1_ranges.csv",
    "actual_target_coverage.csv",
    "roll_transition_audit.csv",
    "trading_parameter_lineage.csv",
    "actual_residuals.csv",
    "ACTUAL_DOMINANT_ROLL_SUMMARY.md",
    "audit_evidence.json",
)
PARAMETER_FIELDS = (
    "price_tick",
    "contract_multiplier",
    "long_margin_ratio",
    "short_margin_ratio",
    "open_commission",
    "close_commission",
    "close_today_commission",
)
TARGETS = (
    ("backtest_review", "1m", JM_BACKTEST_START, JM_BACKTEST_END),
    ("backtest_review", "1d", JM_BACKTEST_START, JM_BACKTEST_END),
    ("signal_live_reference", "1m", JM_SIGNAL_START, FIXED_AUDIT_END),
    ("signal_live_reference", "1d", JM_SIGNAL_START, FIXED_AUDIT_END),
)

CSV_SCHEMAS: dict[str, tuple[str, ...]] = {
    "rank1_uniqueness.csv": (
        "product",
        "trade_date",
        "contract",
        "version",
        "provider",
        "rule",
        "rank",
        "id",
        "registered",
        "mapping_count",
        "status",
        "selection",
        "selection_reason",
    ),
    "rank1_ranges.csv": (
        "product",
        "contract",
        "start_date",
        "end_date",
        "mapping_days",
        "provider_start_date",
        "provider_boundary_status",
        "provider_boundary_source",
        "provider_start_inferred_from_physical",
    ),
    "actual_target_coverage.csv": (
        "consumer",
        "profile",
        "product",
        "contract",
        "period",
        "start_date",
        "end_date",
        "expected_trading_day_count",
        "calendar_status",
        "physical_status",
        "manifest_status",
        "database_status",
        "quality_status",
        "checksum_status",
        "duckdb_status",
        "boundary_status",
        "boundary_evidence",
        "missing_trading_dates",
        "normalized_path_count",
        "manifest_overlap_count",
        "physical_only_count",
        "db_only_count",
        "mapping_semantics",
        "status",
        "path_evidence",
    ),
    "roll_transition_audit.csv": (
        "product",
        "previous_contract",
        "contract",
        "previous_mapping_date",
        "roll_date",
        "classification",
        "boundary_status",
        "calendar_contiguous",
        "previous_close",
        "current_open",
        "price_difference",
        "price_difference_status",
    ),
    "trading_parameter_lineage.csv": (
        "product",
        "trade_date",
        "contract",
        "field",
        "value",
        "source",
        "source_row_id",
        "data_version",
        "effective_start",
        "effective_end",
        "complete",
    ),
    "actual_residuals.csv": (
        "residual_id",
        "category",
        "scope",
        "product",
        "consumer",
        "period",
        "contract",
        "trade_date",
        "target_start",
        "target_end",
        "root_cause",
        "recommended_repair",
        "write_requirements",
        "risk",
    ),
}


@dataclass(frozen=True)
class ActualDominantRollAuditConfig:
    project_root: Path
    source_code_root: Path | None = None
    audit_end: date = FIXED_AUDIT_END
    scan_mode: Literal["quick", "full"] = "full"
    products: tuple[str, ...] = ()
    max_workers: int = 1
    require_postgresql: bool = True

    def __post_init__(self) -> None:
        if self.audit_end != FIXED_AUDIT_END:
            raise ValueError(f"audit_end must be {FIXED_AUDIT_END.isoformat()}")
        if self.scan_mode not in {"quick", "full"}:
            raise ValueError("scan_mode must be quick or full")
        if self.max_workers < 1:
            raise ValueError("max_workers must be positive")


@dataclass(frozen=True)
class ActualDominantRollAuditResult:
    rank1_uniqueness: list[dict[str, Any]]
    rank1_ranges: list[dict[str, Any]]
    actual_target_coverage: list[dict[str, Any]]
    roll_transition_audit: list[dict[str, Any]]
    trading_parameter_lineage: list[dict[str, Any]]
    actual_residuals: list[dict[str, Any]]
    summary: dict[str, Any]
    evidence: dict[str, Any]


def run_actual_dominant_roll_audit(
    config: ActualDominantRollAuditConfig,
    session: Session,
) -> ActualDominantRollAuditResult:
    """Run the bounded audit without mutating database or data assets."""
    products, scope_evidence = _resolve_scope(config)
    filtered = bool(config.products)
    direct_postgresql = False
    mapping_rows: list[dict[str, Any]] = []
    contracts: dict[str, Any] = {}
    trading_days_by_product: dict[str, tuple[date, ...]] = {product: () for product in products}
    files: list[Any] = []
    quality: list[Any] = []
    params: list[Any] = []
    fees: list[Any] = []
    try:
        direct_postgresql = _require_read_only_postgresql(config, session)
        mappings = list(
            session.scalars(
                select(MainContractMap)
                .where(
                    func.lower(MainContractMap.instrument_symbol).in_(products),
                    MainContractMap.rank == RANK,
                    MainContractMap.trade_date <= config.audit_end,
                )
                .order_by(MainContractMap.instrument_symbol, MainContractMap.trade_date, MainContractMap.id)
            )
        )
        contract_codes = sorted(
            {
                str(row.contract_code or "").strip().upper()
                for row in mappings
                if _valid_actual_contract(str(row.contract_code or "").strip().upper())
            }
        )
        contract_rows = _load_contracts(session, contract_codes)
        contracts = {str(row.contract_code).upper(): row for row in contract_rows}
        mapping_rows = [_mapping_dict(row, registered=str(row.contract_code).upper() in contracts) for row in mappings]
        uniqueness, residuals = evaluate_mapping_rows(mapping_rows)
        selected = [row for row in uniqueness if row["selection"] == "selected_effective"]
        trading_days_by_product = _load_trading_days(session, products, selected, contracts, config.audit_end)
        completeness, boundaries = _mapping_completeness_residuals(
            products=products,
            mapping_evidence=uniqueness,
            trading_days_by_product=trading_days_by_product,
            audit_end=config.audit_end,
        )
        residuals.extend(completeness)
        boundary_by_product = {row["product"]: row for row in boundaries}
        ranges = [
            item
            for product in products
            for item in compress_rank1_ranges(
                [row for row in selected if row["product"] == product],
                trading_days=trading_days_by_product.get(product, ()),
                provider_boundary=boundary_by_product.get(product),
            )
        ]

        jm_contracts = sorted({row["contract"] for row in ranges if row["product"] == "jm"})
        files = _load_target_files(session, jm_contracts)
        quality = _load_quality_rows(session, [_value(row, "id") for row in files])
        coverage = _build_target_coverage(
            ranges,
            files,
            quality,
            config.project_root,
            trading_days_by_product=trading_days_by_product,
            full_scan=config.scan_mode == "full",
            max_workers=config.max_workers,
        )
        residuals.extend(_coverage_residuals(coverage))

        transition_seed = [
            item
            for product in products
            for item in classify_roll_transitions(
                [row for row in selected if row["product"] == product],
                trading_days=trading_days_by_product.get(product, ()),
            )
        ]
        price_evidence = (
            _roll_price_evidence(transition_seed, files, config.project_root)
            if config.scan_mode == "full"
            else {}
        )
        transitions = [
            item
            for product in products
            for item in classify_roll_transitions(
                [row for row in selected if row["product"] == product],
                trading_days=trading_days_by_product.get(product, ()),
                price_evidence=price_evidence,
            )
        ]
        residuals.extend(_transition_residuals(transitions))

        parameter_selected = [
            row
            for row in selected
            if row["product"] == "jm"
            and JM_SIGNAL_START <= _date_or_min(row["trade_date"]) <= config.audit_end
        ]
        params, fees = _load_parameter_rows(session, parameter_selected)
        lineage, parameter_residuals = _parameter_lineage(parameter_selected, contracts, params, fees)
        residuals.extend(parameter_residuals)
    finally:
        rollback = getattr(session, "rollback", None)
        if callable(rollback):
            rollback()

    semantic_evidence, semantic_residuals = audit_consumer_semantics(
        config.source_code_root or config.project_root
    )
    residuals.extend(semantic_residuals)
    residuals = _dedupe_residuals(residuals)
    data_environment_git = _git_snapshot(config.project_root.resolve(strict=False))
    audit_engine_git = _git_snapshot(_audit_engine_repo_root())
    db_snapshot_source = _db_snapshot_source(direct_postgresql)
    status, formal_eligible = determine_formal_gate(
        scan_mode=config.scan_mode,
        filtered=filtered,
        direct_postgresql=direct_postgresql and config.require_postgresql,
        canonical_product_scope=scope_evidence["canonical_product_scope"],
        residuals=residuals,
    )
    hard_jm = [row for row in residuals if row["scope"] == "jm_hard"]
    formal_blockers = [row for row in residuals if row["scope"] == "formal"]
    summary = {
        "status": status,
        "scope": "filtered_smoke" if filtered or config.scan_mode == "quick" else "formal_full",
        "audit_end": config.audit_end.isoformat(),
        "products": list(products),
        "product_count": len(products),
        "canonical_product_scope": scope_evidence["canonical_product_scope"],
        "direct_postgresql": direct_postgresql,
        "direct_postgresql_enforced": direct_postgresql and config.require_postgresql,
        "db_snapshot_source": db_snapshot_source,
        "transaction_read_only": direct_postgresql,
        "data_environment_git": data_environment_git,
        "audit_engine_git": audit_engine_git,
        "writes_database": False,
        "writes_parquet": False,
        "writes_manifest": False,
        "writes_quality": False,
        "calls_provider_api": False,
        "calls_rqdata": False,
        "rank1_mapping_count": len(mapping_rows),
        "residual_count": len(residuals),
        "hard_jm_residual_count": len(hard_jm),
        "formal_residual_count": len(formal_blockers),
        "inventory_residual_count": len(residuals) - len(hard_jm) - len(formal_blockers),
        "formal_gate_eligible": formal_eligible,
        "historical_live_mapping_semantics": semantic_evidence["mapping_semantics_status"],
        "actual_confirmed_trigger_semantics": semantic_evidence["trigger_semantics_status"],
        "parameter_semantics": semantic_evidence["parameter_semantics_status"],
        "parameter_scope": "jm_hard_consumer_window",
        "parameter_mapping_day_count": len(parameter_selected),
        "database_query_scope": "batched_selected_products_dates_contracts",
        "max_workers": config.max_workers,
    }
    return ActualDominantRollAuditResult(
        rank1_uniqueness=uniqueness,
        rank1_ranges=ranges,
        actual_target_coverage=coverage,
        roll_transition_audit=transitions,
        trading_parameter_lineage=lineage,
        actual_residuals=residuals,
        summary=summary,
        evidence={
            "required_reports": list(REQUIRED_REPORTS),
            "mapping_rule": RULE,
            "rank": RANK,
            "provider": PROVIDER,
            "scope": scope_evidence,
            "consumer_semantics": semantic_evidence,
            "db_snapshot_source": db_snapshot_source,
            "git_snapshots": {
                "data_environment": data_environment_git,
                "audit_engine": audit_engine_git,
            },
        },
    )


def evaluate_mapping_rows(
    rows: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Retain every version and select one same-contract duplicate deterministically."""
    normalized = [_normalize_mapping_row(row) for row in rows]
    groups: dict[tuple[str, date], list[dict[str, Any]]] = {}
    for row in normalized:
        groups.setdefault((row["product"], row["trade_date"]), []).append(row)
    evidence: list[dict[str, Any]] = []
    residuals: list[dict[str, Any]] = []
    for product, trade_date in sorted(groups):
        group = sorted(groups[(product, trade_date)], key=_mapping_version_key)
        rules = {row["rule"] for row in group}
        contracts = {row["contract"] for row in group}
        invalid = [row for row in group if not _valid_actual_contract(row["contract"]) or not row["registered"]]
        semantics_bad = [
            row
            for row in group
            if row["provider"] != PROVIDER or row["rule"] != RULE or row["rank"] != RANK
        ]
        selected_index: int | None = None
        category = ""
        if len(rules) > 1:
            status, category = "conflict_different_rule", "mapping_conflict"
        elif len(contracts) > 1:
            status, category = "conflict_different_contract", "mapping_conflict"
        elif invalid:
            status, category = "invalid_actual_contract", "invalid_actual_contract"
        elif semantics_bad:
            status, category = "invalid_mapping_semantics", "mapping_semantics"
        elif len(group) > 1:
            status = "duplicate_same_contract"
            selected_index = len(group) - 1
        else:
            status = "selected"
            selected_index = 0
        for index, row in enumerate(group):
            is_selected = selected_index is not None and index == selected_index
            output = {
                **row,
                "trade_date": trade_date.isoformat(),
                "mapping_count": len(group),
                "status": status,
                "selection": "selected_effective" if is_selected else "evidence_retained",
                "selection_reason": (
                    "latest_created_id_data_version_same_contract"
                    if is_selected and len(group) > 1
                    else "only_valid_row"
                    if is_selected
                    else "conflict_or_older_version"
                ),
            }
            evidence.append(output)
        if category:
            residuals.append(
                _residual(
                    category,
                    product,
                    trade_date,
                    f"rank1 {status}",
                    "repair mapping evidence before formal gate",
                    scope=_scope_for(product, trade_date),
                )
            )
    return evidence, residuals


def compress_rank1_ranges(
    rows: Iterable[dict[str, Any]],
    *,
    trading_days: Iterable[date],
    provider_boundary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    selected = sorted(
        (
            _to_date_row(row)
            for row in rows
            if row.get("selection") == "selected_effective" or row.get("status") == "selected"
        ),
        key=lambda row: row["trade_date"],
    )
    expected = list(sorted(set(trading_days)))
    expected_index = {value: index for index, value in enumerate(expected)}
    boundary = provider_boundary or _boundary_evidence(selected[0]["product"] if selected else "", selected)
    ranges: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    previous: dict[str, Any] | None = None
    for row in selected:
        contiguous = previous is not None and row["contract"] == previous["contract"]
        if contiguous and expected:
            contiguous = expected_index.get(row["trade_date"], -2) == expected_index.get(previous["trade_date"], -3) + 1
        if not contiguous:
            if current:
                ranges.append(current)
            current = {
                "product": row["product"],
                "contract": row["contract"],
                "start_date": row["trade_date"].isoformat(),
                "end_date": row["trade_date"].isoformat(),
                "mapping_days": 1,
                "provider_start_date": boundary.get("provider_start_date", ""),
                "provider_boundary_status": boundary.get("provider_boundary_status", "missing"),
                "provider_boundary_source": boundary.get("provider_boundary_source", "none"),
                "provider_start_inferred_from_physical": False,
            }
        else:
            assert current is not None
            current["end_date"] = row["trade_date"].isoformat()
            current["mapping_days"] += 1
        previous = row
    if current:
        ranges.append(current)
    return ranges


def classify_roll_transitions(
    rows: Iterable[dict[str, Any]],
    *,
    trading_days: Iterable[date],
    price_evidence: dict[tuple[str, str, date], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    values = sorted(
        (
            _to_date_row(row)
            for row in rows
            if row.get("selection") in {None, "selected_effective"}
        ),
        key=lambda row: row["trade_date"],
    )
    expected_index = {value: index for index, value in enumerate(sorted(set(trading_days)))}
    output: list[dict[str, Any]] = []
    for index in range(1, len(values)):
        previous, current = values[index - 1], values[index]
        if previous["contract"] == current["contract"]:
            continue
        contiguous = not expected_index or (
            expected_index.get(current["trade_date"], -2)
            == expected_index.get(previous["trade_date"], -3) + 1
        )
        if not contiguous:
            kind = "mapping_gap"
        elif index > 1 and current["contract"] == values[index - 2]["contract"]:
            kind = "aba_reversal"
        elif _contract_month(current["contract"]) < _contract_month(previous["contract"]):
            kind = "backward_month"
        else:
            kind = "normal_roll"
        price = (price_evidence or {}).get(
            (previous["contract"], current["contract"], current["trade_date"]),
            {},
        )
        previous_close = _as_float(price.get("previous_close"))
        current_open = _as_float(price.get("current_open"))
        difference = current_open - previous_close if current_open is not None and previous_close is not None else None
        output.append(
            {
                "product": current["product"],
                "previous_contract": previous["contract"],
                "contract": current["contract"],
                "previous_mapping_date": previous["trade_date"].isoformat(),
                "roll_date": current["trade_date"].isoformat(),
                "classification": kind,
                "boundary_status": "passed" if kind == "normal_roll" else kind,
                "calendar_contiguous": contiguous,
                "previous_close": previous_close,
                "current_open": current_open,
                "price_difference": difference,
                "price_difference_status": "computed_informational" if difference is not None else "unavailable_informational",
            }
        )
    return output


def resolve_trading_parameters(
    *,
    contract: Any,
    exact: Any | Iterable[Any] | None,
    fee_rules: Iterable[Any],
    contract_code: str,
    product: str,
    trade_date: date,
) -> dict[str, Any]:
    exact_candidates = [] if exact is None else list(exact) if isinstance(exact, (list, tuple, set)) else [exact]
    exact_candidates = [
        row
        for row in exact_candidates
        if str(_value(row, "contract_code") or contract_code).upper() == contract_code.upper()
        and _date_or_none(_value(row, "trade_date")) in {None, trade_date}
    ]
    exact_row = max(exact_candidates, key=_parameter_version_key, default=None)
    exchange_code = _clean_text(_value(contract, "exchange_code")).upper()
    fee_candidates = [
        rule
        for rule in fee_rules
        if (_date_or_none(_value(rule, "effective_date")) is None or _date_or_none(_value(rule, "effective_date")) <= trade_date)
        and (
            str(_value(rule, "contract_code") or "").upper() == contract_code.upper()
            or (
                not _clean_text(_value(rule, "contract_code"))
                and str(_value(rule, "instrument_symbol") or "").lower() == product.lower()
            )
        )
        and (
            not exchange_code
            or not _clean_text(_value(rule, "exchange_code"))
            or _clean_text(_value(rule, "exchange_code")).upper() == exchange_code
        )
    ]
    fee_row = max(fee_candidates, key=lambda row: _fee_rule_key(row, contract_code, product), default=None)
    aliases = {
        "contract_multiplier": "volume_multiple",
        "long_margin_ratio": "margin_rate",
        "short_margin_ratio": "margin_rate",
        "open_commission": "open_fee",
        "close_commission": "close_fee",
        "close_today_commission": "close_today_fee",
    }
    values: dict[str, Any] = {}
    lineage: dict[str, str] = {}
    details: dict[str, dict[str, Any]] = {}
    for field in PARAMETER_FIELDS:
        exact_value = _value(exact_row, field)
        fee_value = _value(fee_row, aliases.get(field, field))
        if exact_value is not None:
            values[field] = exact_value
            lineage[field] = "futures_trading_parameters"
            details[field] = _lineage_detail(
                exact_row,
                source=lineage[field],
                effective_start=_date_or_none(_value(exact_row, "trade_date")),
                effective_end=_date_or_none(_value(exact_row, "trade_date")),
            )
        elif fee_value is not None:
            values[field] = fee_value
            specificity = "contract" if str(_value(fee_row, "contract_code") or "").upper() == contract_code.upper() else "product"
            lineage[field] = f"fee_margin_rules:{specificity}"
            details[field] = _lineage_detail(
                fee_row,
                source=lineage[field],
                effective_start=_date_or_none(_value(fee_row, "effective_date")),
                effective_end=_date_or_none(_value(fee_row, "effective_end")),
            )
        elif field == "contract_multiplier" and _value(contract, "contract_multiplier") is not None:
            values[field] = _value(contract, "contract_multiplier")
            lineage[field] = "contracts.contract_multiplier"
            details[field] = _lineage_detail(contract, source=lineage[field])
        else:
            values[field] = None
            lineage[field] = "missing"
            details[field] = _lineage_detail(None, source="missing")
    return {
        "values": values,
        "lineage": lineage,
        "lineage_details": details,
        "complete": all(values[field] is not None for field in PARAMETER_FIELDS),
    }


def audit_consumer_semantics(project_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = project_root.resolve(strict=False)
    sources = {
        "semantics": _read_source(root / "services/quant-api/app/services/actual_contract_semantics.py"),
        "historical": _read_source(root / "services/quant-api/app/services/active_dataset_resolver.py"),
        "live": _read_source(root / "services/quant-api/app/services/live_target_contracts.py"),
        "reader": _read_source(root / "services/quant-api/app/services/live_market_reader.py"),
        "evaluator": _read_source(root / "services/quant-api/app/services/live_signal_evaluator.py"),
        "events": _read_source(root / "services/quant-api/app/services/live_signal_events.py"),
    }
    targets = {
        "effective_mapping_helper": _ast_target_source(
            sources["semantics"], "load_effective_main_contract_mapping"
        ),
        "strict_mapping_helper": _ast_target_source(
            sources["semantics"], "load_strict_main_contract_mapping"
        ),
        "trading_parameter_helper": _ast_target_source(
            sources["semantics"], "load_effective_trading_parameters"
        ),
        "fee_margin_helper": _ast_target_source(
            sources["semantics"], "load_effective_fee_margin_rule"
        ),
        "historical_init": _ast_target_source(sources["historical"], "ActiveDatasetResolver.__init__"),
        "historical_resolve": _ast_target_source(
            sources["historical"], "ActiveDatasetResolver._resolve_contract"
        ),
        "live_mapping": _ast_target_source(sources["live"], "LiveTargetContractResolver._mapping"),
        "live_actual": _ast_target_source(sources["live"], "_actual_contract_or_none"),
        "live_parameters": _ast_target_source(sources["live"], "LiveTargetContractResolver._parameter_gate"),
        "reader": _ast_target_source(sources["reader"], "LiveMarketReader.get_bars"),
        "evaluator_preview": _ast_target_source(sources["evaluator"], "LiveSignalEvaluator.preview"),
        "evaluator_interval": _ast_target_source(sources["evaluator"], "LiveSignalEvaluator._evaluate_interval"),
        "event_eligibility": _ast_target_source(
            sources["events"], "_eligibility_blocked_reasons"
        ),
        "event_features": _ast_target_source(sources["events"], "_features"),
    }
    compact = {key: re.sub(r"\s+", "", value) for key, value in targets.items()}
    neutral_mapping_checks = {
        "effective_provider": "MainContractMap.provider==provider" in compact["effective_mapping_helper"],
        "effective_rule": "MainContractMap.rule==rule" in compact["effective_mapping_helper"],
        "effective_rank": "MainContractMap.rank==rank" in compact["effective_mapping_helper"],
        "effective_trade_date": (
            "MainContractMap.trade_date==trade_date" in compact["effective_mapping_helper"]
        ),
        "strict_provider": "MainContractMap.provider==provider" in compact["strict_mapping_helper"],
        "strict_rule": "MainContractMap.rule==rule" in compact["strict_mapping_helper"],
        "strict_rank": "MainContractMap.rank==rank" in compact["strict_mapping_helper"],
        "strict_trade_date": "MainContractMap.trade_date==trade_date" in compact["strict_mapping_helper"],
        "strict_actual_contract": ".MAIN" in targets["strict_mapping_helper"],
    }
    historical_checks = {
        "strict_helper_default": (
            "load_strict_main_contract_mapping" in targets["historical_init"]
            and "self._strict_mapping_loader=strict_mapping_loader" in compact["historical_init"]
        ),
        "effective_helper_default": (
            "load_effective_main_contract_mapping" in targets["historical_init"]
            and "self._effective_mapping_loader=effective_mapping_loader" in compact["historical_init"]
        ),
        "strict_helper_usage": (
            "self._strict_mapping_loader(" in targets["historical_resolve"]
            and "instrument_symbol=request.symbol" in compact["historical_resolve"]
            and "trade_date=mapping_date" in compact["historical_resolve"]
        ),
        "effective_helper_usage": (
            "self._effective_mapping_loader(" in targets["historical_resolve"]
            and "instrument_symbol=request.symbol" in compact["historical_resolve"]
            and "trade_date=mapping_date" in compact["historical_resolve"]
        ),
    }
    live_checks = {
        "shared_helper_usage": "load_effective_main_contract_mapping" in targets["live_mapping"],
        "provider": "provider=PROVIDER" in compact["live_mapping"],
        "rule": "rule=RULE" in compact["live_mapping"],
        "rank": "rank=1" in compact["live_mapping"],
        "trade_date": "trade_date=trade_date" in compact["live_mapping"],
        "instrument_symbol": (
            "instrument_symbol=product" in compact["live_mapping"]
        ),
        "actual_contract": (
            ".MAIN" in targets["live_actual"]
            or ".main" in targets["live_actual"]
            or "is_continuous_contract" in targets["live_actual"]
        ),
    }
    shared_mapping = (
        all(neutral_mapping_checks.values())
        and all(historical_checks.values())
        and all(live_checks.values())
    )
    mapping_passed = shared_mapping
    neutral_parameter_checks = {
        "exact_created_id_order": _tokens_in_order(
            compact["trading_parameter_helper"],
            "FuturesTradingParameter.created_at.desc()",
            "FuturesTradingParameter.id.desc()",
        ),
        "contract_fee": "FeeMarginRule.contract_code==contract_code" in compact["fee_margin_helper"],
        "product_fee": (
            "FeeMarginRule.instrument_symbol)==instrument_symbol.strip().lower()"
            in compact["fee_margin_helper"]
            or "FeeMarginRule.instrument_symbol==instrument_symbol" in compact["fee_margin_helper"]
        ),
        "nullable_effective": "FeeMarginRule.effective_date.is_(None)" in compact["fee_margin_helper"],
        "bounded_effective": "FeeMarginRule.effective_date<=trade_date" in compact["fee_margin_helper"],
    }
    live_parameter_checks = {
        "trading_helper": (
            "load_effective_trading_parameters" in targets["live_parameters"]
            and "contract_code=contract" in compact["live_parameters"]
            and "trade_date=trade_date" in compact["live_parameters"]
            and "provider=PROVIDER" in compact["live_parameters"]
        ),
        "fee_helper": (
            "load_effective_fee_margin_rule" in targets["live_parameters"]
            and "contract_code=contract" in compact["live_parameters"]
            and "instrument_symbol=product" in compact["live_parameters"]
            and "exchange_code=exchange_code" in compact["live_parameters"]
            and "trade_date=trade_date" in compact["live_parameters"]
            and "provider=PROVIDER" in compact["live_parameters"]
        ),
    }
    shared_parameters = (
        all(neutral_parameter_checks.values())
        and all(live_parameter_checks.values())
    )
    parameter_passed = shared_parameters
    confirmed_filter = (
        "bar_status=='confirmed'" in compact["reader"] or 'bar_status=="confirmed"' in compact["reader"]
    )
    evaluator_source = compact["evaluator_preview"] + compact["evaluator_interval"]
    evaluator_actual = (
        "resolve_ready_actual_contract" in evaluator_source
        and ("target['actual_contract']" in evaluator_source or 'target["actual_contract"]' in evaluator_source)
        and "live_trigger.get('close')" in evaluator_source.replace('"', "'")
    )
    event_source = targets["event_eligibility"] + targets["event_features"]
    compact_event_source = re.sub(r"\s+", "", event_source)
    event_actual_confirmed = (
        "actual_contract" in event_source
        and ".MAIN" in event_source
        and (
            "confirmed_bar=True" in compact_event_source
            or '"confirmed_bar":True' in compact_event_source
            or (
                "bar_status" in event_source
                and "confirmed" in event_source
                and "SIGNAL_BAR_NOT_CONFIRMED" in event_source
            )
        )
    )
    trigger_passed = confirmed_filter and evaluator_actual and event_actual_confirmed
    evidence = {
        "mapping_semantics_status": "passed" if mapping_passed else "mismatch",
        "trigger_semantics_status": "passed" if trigger_passed else "mismatch",
        "parameter_semantics_status": "passed" if parameter_passed else "mismatch",
        "neutral_mapping_checks": neutral_mapping_checks,
        "historical_mapping_checks": historical_checks,
        "live_mapping_checks": live_checks,
        "shared_mapping_helper": shared_mapping,
        "neutral_parameter_checks": neutral_parameter_checks,
        "live_parameter_checks": live_parameter_checks,
        "shared_parameter_helpers": shared_parameters,
        "confirmed_bar_filter": confirmed_filter,
        "evaluator_actual_trigger_price": evaluator_actual,
        "event_actual_confirmed_contract": event_actual_confirmed,
        "source_files_present": {key: bool(value) for key, value in sources.items()},
        "ast_targets_present": {key: bool(value) for key, value in targets.items()},
    }
    residuals: list[dict[str, Any]] = []
    if not mapping_passed:
        residuals.append(
            _residual(
                "historical_live_mapping_semantics",
                "jm",
                None,
                "surviving historical and live consumers do not prove shared rank1 provider/rule/rank/date/actual semantics",
                "restore neutral mapping helper reuse without bypassing consumer boundaries",
                scope="formal",
            )
        )
    if not trigger_passed:
        residuals.append(
            _residual(
                "actual_confirmed_trigger_semantics",
                "jm",
                None,
                "trigger path does not prove confirmed actual-contract bar close semantics",
                "require confirmed bars and actual-contract trigger evidence",
                scope="formal",
            )
        )
    if not parameter_passed:
        residuals.append(
            _residual(
                "actual_parameter_semantics",
                "jm",
                None,
                "neutral exact/fee parameter semantics or live helper usage is incomplete",
                "restore neutral parameter helper semantics and live consumer reuse",
                scope="formal",
            )
        )
    return evidence, residuals


def _ast_target_source(source: str, qualified_name: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    parts = qualified_name.split(".")
    nodes: list[ast.AST] = list(tree.body)
    target: ast.AST | None = None
    for index, part in enumerate(parts):
        target = next(
            (
                node
                for node in nodes
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == part
            ),
            None,
        )
        if target is None:
            return ""
        if index < len(parts) - 1:
            nodes = list(getattr(target, "body", ()))
    return ast.get_source_segment(source, target) or ""


def _tokens_in_order(source: str, *tokens: str) -> bool:
    positions = [source.find(token) for token in tokens]
    return all(position >= 0 for position in positions) and positions == sorted(positions)


def determine_formal_gate(
    *,
    scan_mode: str,
    filtered: bool,
    direct_postgresql: bool,
    canonical_product_scope: bool,
    residuals: Iterable[dict[str, Any]],
) -> tuple[str, bool]:
    eligible = (
        scan_mode == "full"
        and not filtered
        and direct_postgresql
        and canonical_product_scope
    )
    blockers = [row for row in residuals if row.get("scope") in {"jm_hard", "formal"}]
    status = ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED if eligible and not blockers else ACTUAL_DOMINANT_ROLL_REPAIR_REQUIRED
    return status, eligible


def write_actual_dominant_roll_reports(
    result: ActualDominantRollAuditResult,
    output_dir: Path,
) -> dict[str, Path]:
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite audit output directory: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.tmp-",
            dir=output_dir.parent,
        )
    )
    tables = {
        "rank1_uniqueness.csv": result.rank1_uniqueness,
        "rank1_ranges.csv": result.rank1_ranges,
        "actual_target_coverage.csv": result.actual_target_coverage,
        "roll_transition_audit.csv": result.roll_transition_audit,
        "trading_parameter_lineage.csv": result.trading_parameter_lineage,
        "actual_residuals.csv": result.actual_residuals,
    }
    try:
        for name, rows in tables.items():
            _write_csv(staging / name, rows, CSV_SCHEMAS[name])
        (staging / "ACTUAL_DOMINANT_ROLL_SUMMARY.md").write_text(
            "# Actual dominant roll audit\n\n```json\n"
            + json.dumps(result.summary, indent=2, sort_keys=True, default=str)
            + "\n```\n",
            encoding="utf-8",
        )
        (staging / "audit_evidence.json").write_text(
            json.dumps(
                {"summary": result.summary, "evidence": result.evidence},
                indent=2,
                sort_keys=True,
                default=str,
            )
            + "\n",
            encoding="utf-8",
        )
        if output_dir.exists():
            raise FileExistsError(f"refusing to overwrite audit output directory: {output_dir}")
        staging.replace(output_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {name: output_dir / name for name in REQUIRED_REPORTS}


def _resolve_scope(config: ActualDominantRollAuditConfig) -> tuple[tuple[str, ...], dict[str, Any]]:
    requested = tuple(sorted({item.strip().lower() for item in config.products if item.strip()}))
    if requested:
        return requested, {
            "canonical_product_scope": False,
            "scope_source": "explicit_filtered_products",
            "product_count": len(requested),
        }
    path = config.project_root.resolve(strict=False) / CANONICAL_UNIVERSE_PATH
    if not path.is_file():
        raise RuntimeError(f"FORMAL_SCOPE_BLOCKED: canonical universe missing: {path}")
    products = tuple(
        sorted(
            {
                line.strip().lower()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            }
        )
    )
    if len(products) != CANONICAL_PRODUCT_COUNT or "jm" not in products:
        raise RuntimeError(
            f"FORMAL_SCOPE_BLOCKED: expected canonical {CANONICAL_PRODUCT_COUNT} products including jm, got {len(products)}"
        )
    return products, {
        "canonical_product_scope": True,
        "scope_source": str(CANONICAL_UNIVERSE_PATH),
        "product_count": len(products),
    }


def _require_read_only_postgresql(config: ActualDominantRollAuditConfig, session: Session) -> bool:
    dialect = session.get_bind().dialect.name
    if config.require_postgresql and dialect != "postgresql":
        raise RuntimeError(f"direct PostgreSQL is required, got {dialect}")
    if dialect == "postgresql":
        session.execute(text("SET TRANSACTION READ ONLY"))
        return True
    return False


def _audit_engine_repo_root() -> Path:
    module_path = Path(__file__).resolve()
    for parent in module_path.parents:
        if (parent / ".git").exists() and (parent / "services" / "quant-api").is_dir():
            return parent
    return module_path.parents[5]


def _git_snapshot(repo_root: Path) -> dict[str, Any]:
    unavailable = {
        "branch": "unavailable",
        "head": "unavailable",
        "dirty": "unavailable",
        "status": "unavailable",
    }
    command_prefix = ["git", "-C", str(repo_root)]
    try:
        branch = subprocess.run(
            [*command_prefix, "branch", "--show-current"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).stdout.strip()
        head = subprocess.run(
            [*command_prefix, "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).stdout.strip()
        dirty = subprocess.run(
            [*command_prefix, "status", "--porcelain", "--untracked-files=normal"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return unavailable
    if not branch or not head:
        return unavailable
    return {
        "branch": branch,
        "head": head,
        "dirty": bool(dirty),
        "status": "available",
    }


def _db_snapshot_source(direct_postgresql: bool) -> str:
    return "direct_postgresql" if direct_postgresql else "unavailable"


def _mapping_completeness_residuals(
    *,
    products: Sequence[str],
    mapping_evidence: Iterable[dict[str, Any]],
    trading_days_by_product: dict[str, tuple[date, ...]],
    audit_end: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected = [
        _to_date_row(row)
        for row in mapping_evidence
        if row.get("selection") == "selected_effective"
    ]
    residuals: list[dict[str, Any]] = []
    boundaries: list[dict[str, Any]] = []
    for product in products:
        rows = sorted((row for row in selected if row["product"] == product), key=lambda row: row["trade_date"])
        boundary = _boundary_evidence(product, rows)
        boundaries.append(boundary)
        if not rows:
            residuals.append(
                _residual(
                    "mapping_product_missing",
                    product,
                    None,
                    "no valid rank1 mapping rows",
                    "load canonical rank1 mapping evidence",
                    scope="jm_hard" if product == "jm" else "inventory",
                )
            )
            continue
        if product == "jm" and rows[0]["trade_date"] > JM_SIGNAL_START:
            residuals.append(
                _residual(
                    "provider_boundary_missing",
                    product,
                    rows[0]["trade_date"],
                    f"rank1 provider boundary starts after {JM_SIGNAL_START.isoformat()}",
                    "obtain authoritative mapping evidence for the hard consumer start",
                    scope="jm_hard",
                    target_start=JM_SIGNAL_START,
                    target_end=audit_end,
                )
            )
        if not trading_days_by_product.get(product):
            residuals.append(
                _residual(
                    "mapping_calendar_missing",
                    product,
                    None,
                    "trading calendar evidence is unavailable for mapping completeness",
                    "repair exchange registration or trading calendar evidence",
                    scope="jm_hard" if product == "jm" else "inventory",
                )
            )
        elif product == "jm":
            calendar_days = tuple(sorted(set(trading_days_by_product[product])))
            for consumer, period, hard_start, hard_end in TARGETS:
                target_end = min(hard_end, audit_end)
                if calendar_days[0] <= hard_start and calendar_days[-1] >= target_end:
                    continue
                residuals.append(
                    _residual(
                        "hard_target_calendar_boundary",
                        product,
                        hard_start,
                        (
                            f"calendar bounds {calendar_days[0].isoformat()}..{calendar_days[-1].isoformat()} "
                            f"do not cover {hard_start.isoformat()}..{target_end.isoformat()}"
                        ),
                        "repair authoritative JM calendar boundaries before deriving expected dates",
                        consumer=consumer,
                        period=period,
                        target_start=hard_start,
                        target_end=target_end,
                        scope="jm_hard",
                    )
                )
        present = {row["trade_date"] for row in rows}
        first = max(rows[0]["trade_date"], JM_SIGNAL_START) if product == "jm" else rows[0]["trade_date"]
        expected = {
            day
            for day in trading_days_by_product.get(product, ())
            if first <= day <= audit_end
        }
        for missing in sorted(expected - present):
            residuals.append(
                _residual(
                    "mapping_date_missing",
                    product,
                    missing,
                    "trading calendar date has no valid rank1 mapping",
                    "repair the missing mapping date without selecting a conflicting version",
                    scope=_scope_for(product, missing),
                )
            )
    return residuals, boundaries


def _build_target_coverage(
    ranges: list[dict[str, Any]],
    files: list[Any],
    quality: list[Any],
    root: Path,
    *,
    trading_days_by_product: dict[str, tuple[date, ...]] | None = None,
    full_scan: bool,
    max_workers: int = 1,
) -> list[dict[str, Any]]:
    root = root.resolve(strict=False)
    manifest_rows = _load_manifest_rows(root)
    file_rows = [_file_dict(row, root) for row in files]
    quality_by_file: dict[Any, list[Any]] = {}
    for row in quality:
        quality_by_file.setdefault(_value(row, "file_id"), []).append(row)
    targets = _coverage_targets(ranges)
    physical_inventory = _inventory_canonical_actual_files(
        root,
        products={row["product"] for row in targets},
        contracts={row["contract"] for row in targets if row["contract"]},
        periods={row["period"] for row in targets},
    )
    rows: list[dict[str, Any]] = []
    for target in targets:
        start = _date_or_min(target["start_date"])
        end = _date_or_min(target["end_date"])
        calendar_days = tuple(sorted(set((trading_days_by_product or {}).get(target["product"], ()))))
        calendar_complete = bool(calendar_days and calendar_days[0] <= start and calendar_days[-1] >= end)
        expected_days = {
            day
            for day in calendar_days
            if start <= day <= end
        }
        expected_days.update({start, end})
        db_candidates = [
            row
            for row in file_rows
            if row["product"] == target["product"]
            and row["contract"] == target["contract"]
            and row["period"] == target["period"]
            and _overlaps(row["start_date"], row["end_date"], start, end)
        ]
        manifest_candidates = [
            row
            for row in manifest_rows
            if row["product"] == target["product"]
            and row["contract"] == target["contract"]
            and row["period"] == target["period"]
            and _overlaps(row["start_date"], row["end_date"], start, end)
        ]
        physical_candidates = [
            row
            for row in physical_inventory
            if row["product"] == target["product"]
            and row["contract"] == target["contract"]
            and row["period"] == target["period"]
        ]
        db_by_path = _group_by_path(db_candidates)
        manifest_by_path = _group_by_path(manifest_candidates)
        physical_by_path = _group_by_path(physical_candidates)
        paths = sorted(set(db_by_path) | set(manifest_by_path) | set(physical_by_path), key=str)
        facts = _inspect_asset_paths(
            paths,
            period=target["period"],
            full_scan=full_scan,
            max_workers=max_workers,
        )
        path_records: list[dict[str, Any]] = []
        layer_days = {
            "physical": set(),
            "manifest": set(),
            "database": set(),
            "quality": set(),
            "checksum": set(),
            "duckdb": set(),
        }
        boundary_evidence: set[str] = set()
        qualifying_manifest_evidence: list[dict[str, Any]] = []
        for path in paths:
            db_path_rows = db_by_path.get(path, [])
            manifest_path_rows = manifest_by_path.get(path, [])
            physical = bool(physical_by_path.get(path)) or path.is_file()
            inspection = facts[path]["inspection"]
            actual_checksum = facts[path]["checksum"]
            physical_days = set(inspection["coverage_dates"])
            if inspection["readable"]:
                layer_days["duckdb"].update(physical_days)
                boundary_evidence.add(str(inspection["boundary_evidence"]))
            qualifying_db = [
                row
                for row in db_path_rows
                if row["provider"] == PROVIDER
                and row["data_type"] == "bars"
                and row["data_role"] == "primary"
                and row["quality_status"] == "passed"
            ]
            qualifying_manifest = [
                row
                for row in manifest_path_rows
                if row["provider"] == PROVIDER
                and row["data_role"] == "primary"
                and row["quality_status"] == "passed"
                and row["status"] in {"success", "passed", "complete", ""}
            ]
            qualifying_db_ids = {row["id"] for row in qualifying_db if row["id"] is not None}
            qualifying_manifest = [
                row
                for row in qualifying_manifest
                if (
                    row.get("market_data_file_id") in qualifying_db_ids
                    if row.get("market_data_file_id") is not None
                    else len(qualifying_db) == 1
                )
            ]
            qualifying_manifest_evidence.extend(
                {**row, "coverage_dates": physical_days} for row in qualifying_manifest
            )
            db_days = _metadata_days(qualifying_db, expected_days)
            manifest_days = _metadata_days(qualifying_manifest, expected_days)
            if qualifying_db:
                layer_days["database"].update(db_days)
            if qualifying_manifest and physical:
                layer_days["manifest"].update(manifest_days)
            if physical:
                if full_scan:
                    layer_days["physical"].update(physical_days)
                else:
                    declared_days = db_days & manifest_days
                    layer_days["physical"].update(declared_days)
                    if declared_days:
                        boundary_evidence.add("declared_range")
            quality_passed = bool(qualifying_db)
            quality_days: set[date] = set()
            for db_row in qualifying_db:
                file_quality_passed, file_quality_days = _quality_evidence_days(
                    db_row,
                    quality_by_file.get(db_row["id"], []),
                    expected_days,
                )
                quality_passed = quality_passed and file_quality_passed
                quality_days.update(file_quality_days)
            if quality_passed:
                layer_days["quality"].update(quality_days)
            db_declarations = [row["checksum"] for row in qualifying_db]
            manifest_declarations = [row["checksum"] for row in qualifying_manifest]
            db_checksums_complete = bool(db_declarations) and all(
                value == actual_checksum for value in db_declarations
            )
            manifest_checksums_complete = bool(manifest_declarations) and all(
                value == actual_checksum for value in manifest_declarations
            )
            checksum_passed = bool(
                actual_checksum
                and db_checksums_complete
                and manifest_checksums_complete
            )
            if checksum_passed:
                layer_days["checksum"].update(physical_days)
            path_records.append(
                {
                    "path": str(path),
                    "physical": physical,
                    "duckdb_readable": inspection["readable"],
                    "duckdb_row_count": inspection["row_count"],
                    "duckdb_error": inspection["error"],
                    "actual_checksum": actual_checksum,
                    "db_ids": sorted(row["id"] for row in db_path_rows if row["id"] is not None),
                    "manifest_files": sorted({row["manifest_file"] for row in manifest_path_rows}),
                    "quality_passed": quality_passed,
                    "checksum_passed": checksum_passed,
                    "db_checksum_declarations_complete": db_checksums_complete,
                    "manifest_checksum_declarations_complete": manifest_checksums_complete,
                }
            )
        overlaps = _manifest_overlap_count(qualifying_manifest_evidence)
        missing_days = sorted(expected_days - layer_days["physical"])
        statuses = {
            name: "passed" if expected_days <= days else "failed"
            for name, days in layer_days.items()
        }
        manifest_status = "failed_overlap" if overlaps else statuses["manifest"]
        boundary_passed = not missing_days and (not full_scan or statuses["duckdb"] == "passed")
        required_layers = (
            ("physical", "database", "quality", "checksum", "duckdb")
            if full_scan
            else ("physical", "database", "quality")
        )
        covered = (
            calendar_complete
            and
            all(statuses[name] == "passed" for name in required_layers)
            and manifest_status == "passed"
            and boundary_passed
        )
        physical_only = [path for path in physical_by_path if path not in db_by_path and path.is_file()]
        physical_only.extend(
            path
            for path in manifest_by_path
            if path not in db_by_path and path.is_file() and path not in physical_only
        )
        db_only = [path for path in db_by_path if path not in manifest_by_path or not path.is_file()]
        rows.append(
            {
                **target,
                "expected_trading_day_count": len(expected_days),
                "calendar_status": "passed" if calendar_complete else "failed",
                "physical_status": statuses["physical"],
                "manifest_status": manifest_status,
                "database_status": statuses["database"],
                "quality_status": statuses["quality"],
                "checksum_status": statuses["checksum"] if full_scan else "not_run",
                "duckdb_status": statuses["duckdb"] if full_scan else "not_run",
                "boundary_status": "passed" if boundary_passed else "failed",
                "boundary_evidence": ",".join(sorted(boundary_evidence)) or "none",
                "missing_trading_dates": json.dumps([day.isoformat() for day in missing_days]),
                "normalized_path_count": len(paths),
                "manifest_overlap_count": overlaps,
                "physical_only_count": len(physical_only),
                "db_only_count": len(db_only),
                "mapping_semantics": "actual_confirmed_rank1",
                "status": "covered" if covered else "residual",
                "path_evidence": json.dumps(path_records, sort_keys=True, default=str),
            }
        )
    return rows


def _coverage_targets(ranges: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    jm_ranges = [row for row in ranges if str(row.get("product", "")).lower() == "jm"]
    targets: list[dict[str, Any]] = []
    for consumer, period, hard_start, hard_end in TARGETS:
        found = False
        for row in jm_ranges:
            start = max(_date_or_min(row["start_date"]), hard_start)
            end = min(_date_or_min(row["end_date"]), hard_end)
            if start > end:
                continue
            found = True
            targets.append(
                {
                    "consumer": consumer,
                    "profile": "jm_v1b",
                    "product": "jm",
                    "contract": str(row["contract"]).upper(),
                    "period": period,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                }
            )
        if not found:
            targets.append(
                {
                    "consumer": consumer,
                    "profile": "jm_v1b",
                    "product": "jm",
                    "contract": "",
                    "period": period,
                    "start_date": hard_start.isoformat(),
                    "end_date": hard_end.isoformat(),
                }
            )
    return sorted(targets, key=lambda row: (row["consumer"], row["period"], row["start_date"], row["contract"]))


def _load_manifest_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    manifest_root = root / "data" / "manifests"
    if not manifest_root.is_dir():
        return rows
    for manifest in sorted(manifest_root.rglob("*.csv")):
        try:
            with manifest.open(encoding="utf-8-sig", newline="") as stream:
                for raw in csv.DictReader(stream):
                    period = _clean_text(raw.get("period") or raw.get("frequency")).lower()
                    raw_path = _clean_text(
                        raw.get("standard_path")
                        or raw.get("file_path")
                        or raw.get("path")
                        or raw.get("output_path")
                    )
                    if not period or not raw_path:
                        continue
                    product = _clean_text(raw.get("product") or raw.get("instrument_symbol") or raw.get("symbol")).lower()
                    contract = _clean_text(
                        raw.get("actual_contract")
                        or raw.get("contract_code")
                        or raw.get("contract")
                    ).upper()
                    if not product or not contract:
                        continue
                    rows.append(
                        {
                            "product": product,
                            "contract": contract,
                            "period": period,
                            "provider": _clean_text(raw.get("provider") or raw.get("source") or PROVIDER).lower(),
                            "data_role": _clean_text(raw.get("data_role") or "candidate").lower(),
                            "quality_status": _clean_text(
                                raw.get("quality_status") or raw.get("original_quality_status") or "unchecked"
                            ).lower(),
                            "status": _clean_text(raw.get("status")).lower(),
                            "start_date": _date_or_none(
                                raw.get("min_datetime") or raw.get("start_time") or raw.get("start_date")
                            ),
                            "end_date": _date_or_none(
                                raw.get("max_datetime") or raw.get("end_time") or raw.get("end_date")
                            ),
                            "checksum": _clean_text(raw.get("checksum")).lower(),
                            "market_data_file_id": _int_or_none(
                                raw.get("market_data_file_id") or raw.get("db_file_id")
                            ),
                            "path": _normalize_asset_path(root, raw_path),
                            "manifest_file": str(manifest.relative_to(root)),
                        }
                    )
        except (OSError, csv.Error, UnicodeError):
            continue
    return rows


def _inventory_canonical_actual_files(
    root: Path,
    *,
    products: set[str],
    contracts: set[str],
    periods: set[str],
) -> list[dict[str, Any]]:
    """Inventory target-bounded canonical files independently of metadata."""
    canonical_root = root.resolve(strict=False) / "data" / "parquet" / "canonical" / "bars"
    if not canonical_root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(canonical_root.rglob("*.parquet")):
        attributes: dict[str, str] = {}
        for part in path.relative_to(canonical_root).parts[:-1]:
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            attributes[key.strip().lower()] = value.strip()
        product = attributes.get("symbol", "").lower()
        contract = attributes.get("contract", "").upper()
        period = attributes.get("period", "").lower()
        provider = attributes.get("provider", "").lower()
        if (
            product not in products
            or contract not in contracts
            or period not in periods
            or not _valid_actual_contract(contract)
        ):
            continue
        rows.append(
            {
                "product": product,
                "contract": contract,
                "period": period,
                "provider": provider,
                "path": path.resolve(strict=False),
            }
        )
    return rows


def _inspect_asset_paths(
    paths: Sequence[Path],
    *,
    period: str,
    full_scan: bool,
    max_workers: int,
) -> dict[Path, dict[str, Any]]:
    def inspect(path: Path) -> tuple[Path, dict[str, Any]]:
        physical = path.is_file()
        if physical and full_scan:
            return path, {"inspection": _inspect_parquet(path, period), "checksum": _sha256_file(path)}
        return path, {
            "inspection": {
                "readable": False,
                "coverage_dates": set(),
                "boundary_evidence": "not_run",
                "row_count": None,
                "error": "quick_scan" if physical else "missing_physical",
            },
            "checksum": "",
        }

    if max_workers <= 1 or len(paths) <= 1:
        return dict(inspect(path) for path in paths)
    with ThreadPoolExecutor(max_workers=min(max_workers, len(paths))) as executor:
        return dict(executor.map(inspect, paths))


def _inspect_parquet(path: Path, period: str) -> dict[str, Any]:
    try:
        import duckdb

        escaped = str(path).replace("'", "''")
        with duckdb.connect(database=":memory:") as connection:
            columns = {
                str(row[0]).lower()
                for row in connection.execute(f"DESCRIBE SELECT * FROM read_parquet('{escaped}')").fetchall()
            }
            required = {"datetime", "open", "high", "low", "close", "volume", "open_interest"}
            missing_columns = sorted(required - columns)
            if missing_columns:
                raise ValueError(f"required columns missing: {','.join(missing_columns)}")
            if period == "1m" and "trading_day" not in columns:
                raise ValueError("trading_day column missing for 1m boundary")
            if period == "1m":
                date_expression = "TRY_CAST(trading_day AS DATE)"
                boundary_evidence = "trading_day"
            else:
                date_expression = "CAST(datetime AS DATE)"
                boundary_evidence = "datetime_date"
            values = connection.execute(
                f"SELECT count(*), min({date_expression}), max({date_expression}), "
                f"list_sort(list_distinct(list({date_expression}))) FROM read_parquet('{escaped}')"
            ).fetchone()
        coverage_dates = {_date_or_min(value) for value in (values[3] or []) if value is not None}
        return {
            "readable": True,
            "row_count": int(values[0]),
            "min_date": _date_or_none(values[1]),
            "max_date": _date_or_none(values[2]),
            "coverage_dates": coverage_dates,
            "boundary_evidence": boundary_evidence,
            "error": "",
        }
    except Exception as exc:
        return {
            "readable": False,
            "row_count": None,
            "min_date": None,
            "max_date": None,
            "coverage_dates": set(),
            "boundary_evidence": "unavailable",
            "error": f"{type(exc).__name__}:{exc}",
        }


def _parameter_lineage(
    selected: list[dict[str, Any]],
    contracts: dict[str, Any],
    params: list[Any],
    fees: list[Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    exact_by_key: dict[tuple[str, date], list[Any]] = {}
    for row in params:
        key = (str(_value(row, "contract_code") or "").upper(), _date_or_min(_value(row, "trade_date")))
        exact_by_key.setdefault(key, []).append(row)
    output: list[dict[str, Any]] = []
    residuals: list[dict[str, Any]] = []
    for mapping in selected:
        contract_code = str(mapping["contract"]).upper()
        day = _date_or_min(mapping["trade_date"])
        resolved = resolve_trading_parameters(
            contract=contracts.get(contract_code, {}),
            exact=exact_by_key.get((contract_code, day), []),
            fee_rules=fees,
            contract_code=contract_code,
            product=mapping["product"],
            trade_date=day,
        )
        for field in PARAMETER_FIELDS:
            detail = resolved["lineage_details"][field]
            output.append(
                {
                    "product": mapping["product"],
                    "trade_date": day.isoformat(),
                    "contract": contract_code,
                    "field": field,
                    "value": resolved["values"][field],
                    "source": resolved["lineage"][field],
                    "source_row_id": detail["source_row_id"],
                    "data_version": detail["data_version"],
                    "effective_start": detail["effective_start"],
                    "effective_end": detail["effective_end"],
                    "complete": resolved["complete"],
                }
            )
        if not resolved["complete"]:
            residuals.append(
                _residual(
                    "trading_parameter_missing",
                    mapping["product"],
                    day,
                    f"parameters incomplete for {contract_code}",
                    "load authoritative parameter evidence",
                    contract=contract_code,
                    scope=_scope_for(mapping["product"], day),
                )
            )
    return output, residuals


def _load_contracts(session: Session, contract_codes: Sequence[str]) -> list[Any]:
    rows: list[Any] = []
    for batch in _batched(contract_codes):
        rows.extend(session.scalars(select(Contract).where(Contract.contract_code.in_(batch))))
    return rows


def _load_trading_days(
    session: Session,
    products: Sequence[str],
    selected: list[dict[str, Any]],
    contracts: dict[str, Any],
    audit_end: date,
) -> dict[str, tuple[date, ...]]:
    exchange_by_product: dict[str, str] = {}
    for row in selected:
        contract = contracts.get(row["contract"])
        exchange = _clean_text(_value(contract, "exchange_code"))
        if exchange:
            exchange_by_product[row["product"]] = exchange
    exchanges = sorted(set(exchange_by_product.values()))
    days_by_exchange: dict[str, list[date]] = {exchange: [] for exchange in exchanges}
    for batch in _batched(exchanges):
        rows = session.scalars(
            select(TradingCalendar).where(
                TradingCalendar.exchange_code.in_(batch),
                TradingCalendar.is_trading_day.is_(True),
                TradingCalendar.trade_date <= audit_end,
            )
        )
        for row in rows:
            days_by_exchange.setdefault(row.exchange_code, []).append(row.trade_date)
    return {
        product: tuple(sorted(set(days_by_exchange.get(exchange_by_product.get(product, ""), []))))
        for product in products
    }


def _load_target_files(session: Session, contracts: Sequence[str]) -> list[Any]:
    if not contracts:
        return []
    rows: list[Any] = []
    start_dt = datetime.combine(JM_SIGNAL_START, time.min)
    end_dt = datetime.combine(FIXED_AUDIT_END, time.max)
    for batch in _batched(contracts):
        rows.extend(
            session.scalars(
                select(MarketDataFile).where(
                    func.lower(MarketDataFile.instrument_symbol) == "jm",
                    MarketDataFile.contract_code.in_(batch),
                    MarketDataFile.period.in_(("1m", "1d")),
                    MarketDataFile.start_time <= end_dt,
                    MarketDataFile.end_time >= start_dt,
                )
            )
        )
    return rows


def _load_quality_rows(session: Session, file_ids: Sequence[Any]) -> list[Any]:
    clean_ids = sorted({int(value) for value in file_ids if value is not None})
    rows: list[Any] = []
    for batch in _batched(clean_ids):
        rows.extend(session.scalars(select(DataQualityReport).where(DataQualityReport.file_id.in_(batch))))
    return rows


def _load_parameter_rows(
    session: Session,
    selected: list[dict[str, Any]],
) -> tuple[list[Any], list[Any]]:
    pairs = sorted({(str(row["contract"]).upper(), _date_or_min(row["trade_date"])) for row in selected})
    params: list[Any] = []
    for batch in _batched(pairs):
        params.extend(
            session.scalars(
                select(FuturesTradingParameter).where(
                    FuturesTradingParameter.provider == PROVIDER,
                    tuple_(FuturesTradingParameter.contract_code, FuturesTradingParameter.trade_date).in_(batch),
                )
            )
        )
    if not pairs:
        return params, []
    contracts = sorted({contract for contract, _ in pairs})
    products = sorted({str(row["product"]).lower() for row in selected})
    latest = max(day for _, day in pairs)
    fees: list[Any] = []
    for contract_batch in _batched(contracts):
        fees.extend(
            session.scalars(
                select(FeeMarginRule).where(
                    FeeMarginRule.provider == PROVIDER,
                    or_(
                        FeeMarginRule.contract_code.in_(contract_batch),
                        func.lower(FeeMarginRule.instrument_symbol).in_(products),
                    ),
                    or_(FeeMarginRule.effective_date.is_(None), FeeMarginRule.effective_date <= latest),
                )
            )
        )
    return params, _dedupe_rows(fees)


def _roll_price_evidence(
    transitions: Iterable[dict[str, Any]],
    files: Iterable[Any],
    root: Path,
) -> dict[tuple[str, str, date], dict[str, Any]]:
    usable = [
        _file_dict(row, root.resolve(strict=False))
        for row in files
        if _value(row, "data_role") == "primary" and _value(row, "quality_status") == "passed"
    ]
    result: dict[tuple[str, str, date], dict[str, Any]] = {}
    cache: dict[tuple[str, date, str], float | None] = {}
    for row in transitions:
        previous = row["previous_contract"]
        current = row["contract"]
        roll_date = _date_or_min(row["roll_date"])
        previous_key = (previous, roll_date, "previous")
        current_key = (current, roll_date, "current")
        if previous_key not in cache:
            cache[previous_key] = _find_roll_price(usable, previous, roll_date, previous=True)
        if current_key not in cache:
            cache[current_key] = _find_roll_price(usable, current, roll_date, previous=False)
        result[(previous, current, roll_date)] = {
            "previous_close": cache[previous_key],
            "current_open": cache[current_key],
        }
    return result


def _find_roll_price(
    files: Iterable[dict[str, Any]],
    contract: str,
    roll_date: date,
    *,
    previous: bool,
) -> float | None:
    candidates = sorted(
        (
            row
            for row in files
            if row["contract"] == contract and row["period"] in {"1d", "1m"} and row["path"].is_file()
        ),
        key=lambda row: (0 if row["period"] == "1d" else 1, str(row["path"])),
    )
    values: list[tuple[datetime, float]] = []
    for row in candidates:
        try:
            import duckdb

            escaped = str(row["path"]).replace("'", "''")
            with duckdb.connect(database=":memory:") as connection:
                columns = {
                    str(item[0]).lower()
                    for item in connection.execute(f"DESCRIBE SELECT * FROM read_parquet('{escaped}')").fetchall()
                }
                date_expr = "TRY_CAST(trading_day AS DATE)" if "trading_day" in columns else "CAST(datetime AS DATE)"
                comparator = "<" if previous else "="
                order = "DESC" if previous else "ASC"
                field = "close" if previous else "open"
                query = (
                    f"SELECT datetime, {field} FROM read_parquet('{escaped}') "
                    f"WHERE {date_expr} {comparator} ? AND {field} IS NOT NULL ORDER BY datetime {order} LIMIT 1"
                )
                value = connection.execute(query, [roll_date]).fetchone()
            if value:
                values.append((value[0], float(value[1])))
        except Exception:
            continue
    if not values:
        return None
    return (max(values) if previous else min(values))[1]


def _coverage_residuals(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    residuals: list[dict[str, Any]] = []
    for row in rows:
        if row["status"] == "covered":
            continue
        failed = [
            field.removesuffix("_status")
            for field in (
                "physical_status",
                "manifest_status",
                "database_status",
                "quality_status",
                "checksum_status",
                "duckdb_status",
                "boundary_status",
            )
            if row[field] != "passed"
        ]
        residuals.append(
            _residual(
                "target_coverage",
                row["product"],
                _date_or_min(row["start_date"]),
                "failed layers: " + ",".join(failed),
                "repair only the named evidence layers in a separate approved task",
                consumer=row["consumer"],
                period=row["period"],
                contract=row["contract"],
                target_start=_date_or_min(row["start_date"]),
                target_end=_date_or_min(row["end_date"]),
                scope="jm_hard",
            )
        )
    return residuals


def _transition_residuals(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _residual(
            "roll_transition",
            row["product"],
            _date_or_min(row["roll_date"]),
            row["classification"],
            "repair mapping evidence; price difference remains informational",
            contract=row["contract"],
            scope=_scope_for(row["product"], _date_or_min(row["roll_date"])),
        )
        for row in rows
        if row["classification"] != "normal_roll"
    ]


def _residual(
    category: str,
    product: str,
    when: date | None,
    root_cause: str,
    repair: str,
    *,
    consumer: str = "",
    period: str = "",
    contract: str = "",
    target_start: date | None = None,
    target_end: date | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    actual_scope = scope or _scope_for(product, when)
    dimensions = (
        category,
        product,
        consumer,
        period,
        contract,
        when.isoformat() if when else "",
        target_start.isoformat() if target_start else "",
        target_end.isoformat() if target_end else "",
        root_cause,
    )
    seed = "|".join(dimensions)
    return {
        "residual_id": hashlib.sha256(seed.encode()).hexdigest()[:20],
        "category": category,
        "scope": actual_scope,
        "product": product,
        "consumer": consumer,
        "period": period,
        "contract": contract,
        "trade_date": when.isoformat() if when else "",
        "target_start": target_start.isoformat() if target_start else "",
        "target_end": target_end.isoformat() if target_end else "",
        "root_cause": root_cause,
        "recommended_repair": repair,
        "write_requirements": "separate approved repair task",
        "risk": "hard" if actual_scope in {"jm_hard", "formal"} else "review",
    }


def _dedupe_residuals(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    values = {row["residual_id"]: row for row in rows}
    return sorted(
        values.values(),
        key=lambda row: (
            row["scope"],
            row["category"],
            row["product"],
            row["consumer"],
            row["period"],
            row["contract"],
            row["trade_date"],
            row["target_start"],
        ),
    )


def _mapping_dict(row: MainContractMap, *, registered: bool) -> dict[str, Any]:
    return {
        "product": row.instrument_symbol.lower(),
        "trade_date": row.trade_date,
        "contract": row.contract_code,
        "version": row.data_version,
        "provider": row.provider,
        "rule": row.rule,
        "rank": row.rank,
        "id": row.id,
        "created_at": row.created_at,
        "registered": registered,
    }


def _normalize_mapping_row(row: dict[str, Any]) -> dict[str, Any]:
    value = dict(row)
    value["product"] = str(value.get("product") or value.get("instrument_symbol") or "").lower()
    value["trade_date"] = _date_or_min(value.get("trade_date"))
    value["contract"] = str(value.get("contract") or value.get("contract_code") or "").strip().upper()
    value["version"] = str(value.get("version") or value.get("data_version") or "")
    value["provider"] = str(value.get("provider") or "")
    value["rule"] = str(value.get("rule") or "")
    value["rank"] = int(value.get("rank") or 0)
    value["registered"] = bool(value.get("registered", False))
    return value


def _mapping_version_key(row: dict[str, Any]) -> tuple[datetime, int, str]:
    created = _value(row, "created_at")
    if not isinstance(created, datetime):
        created = datetime.min
    return created, int(row.get("id") or -1), str(row.get("version") or "")


def _valid_actual_contract(value: str) -> bool:
    normalized = value.strip().upper()
    return bool(normalized) and "." not in normalized and not normalized.endswith("MAIN")


def _boundary_evidence(product: str, rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "product": product,
            "provider_start_date": "",
            "provider_boundary_status": "missing",
            "provider_boundary_source": "none",
            "provider_start_inferred_from_physical": False,
        }
    first = min(_date_or_min(row["trade_date"]) for row in rows)
    status = "verified_for_jm_hard" if product == "jm" and first <= JM_SIGNAL_START else "mapping_evidence_only"
    return {
        "product": product,
        "provider_start_date": first.isoformat(),
        "provider_boundary_status": status,
        "provider_boundary_source": "rank1_mapping_min",
        "provider_start_inferred_from_physical": False,
    }


def _to_date_row(row: dict[str, Any]) -> dict[str, Any]:
    value = dict(row)
    value["trade_date"] = _date_or_min(value["trade_date"])
    return value


def _contract_month(contract: str) -> int:
    match = re.search(r"(\d{4})$", contract)
    return int(match.group(1)) if match else -1


def _scope_for(product: str, when: date | None) -> str:
    return "jm_hard" if product == "jm" and (when is None or when >= JM_SIGNAL_START) else "inventory"


def _file_dict(row: Any, root: Path) -> dict[str, Any]:
    return {
        "id": _value(row, "id"),
        "provider": _clean_text(_value(row, "provider")).lower(),
        "data_type": _clean_text(_value(row, "data_type")).lower(),
        "product": _clean_text(_value(row, "instrument_symbol")).lower(),
        "contract": _clean_text(_value(row, "contract_code")).upper(),
        "period": _clean_text(_value(row, "period")).lower(),
        "start_date": _date_or_none(_value(row, "start_time")),
        "end_date": _date_or_none(_value(row, "end_time")),
        "path": _normalize_asset_path(root, _clean_text(_value(row, "file_path"))),
        "checksum": _clean_text(_value(row, "checksum")).lower(),
        "data_version": _clean_text(_value(row, "data_version")),
        "data_role": _clean_text(_value(row, "data_role")).lower(),
        "quality_status": _clean_text(_value(row, "quality_status")).lower(),
    }


def _normalize_asset_path(root: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        return (root / path).resolve(strict=False)
    if path.exists():
        return path.resolve(strict=False)
    parts = path.parts
    if "data" in parts:
        index = parts.index("data")
        return (root / Path(*parts[index:])).resolve(strict=False)
    return path.resolve(strict=False)


def _group_by_path(rows: Iterable[dict[str, Any]]) -> dict[Path, list[dict[str, Any]]]:
    output: dict[Path, list[dict[str, Any]]] = {}
    for row in rows:
        output.setdefault(row["path"], []).append(row)
    return output


def _metadata_days(rows: Iterable[dict[str, Any]], expected_days: set[date]) -> set[date]:
    output: set[date] = set()
    for row in rows:
        start, end = row.get("start_date"), row.get("end_date")
        if start is None or end is None:
            continue
        output.update(day for day in expected_days if start <= day <= end)
    return output


def _quality_evidence_days(
    file_row: dict[str, Any],
    reports: Iterable[Any],
    expected_days: set[date],
) -> tuple[bool, set[date]]:
    values = list(reports)
    if file_row["quality_status"] != "passed" or not values:
        return False, set()
    normalized: list[dict[str, Any]] = []
    for row in values:
        identity_matches = all(
            (
                not _clean_text(_value(row, report_field))
                or _clean_text(_value(row, report_field)).lower()
                == _clean_text(file_row[file_field]).lower()
            )
            for report_field, file_field in (
                ("provider", "provider"),
                ("data_type", "data_type"),
                ("instrument_symbol", "product"),
                ("contract_code", "contract"),
                ("period", "period"),
            )
        )
        if _clean_text(_value(row, "status")).lower() != "passed" or not identity_matches:
            return False, set()
        normalized.append(
            {
                "start_date": _date_or_none(_value(row, "start_time")),
                "end_date": _date_or_none(_value(row, "end_time")),
            }
        )
    return True, _metadata_days(normalized, expected_days)


def _manifest_overlap_count(rows: Iterable[dict[str, Any]]) -> int:
    unique: dict[Path, dict[str, Any]] = {}
    for row in rows:
        unique.setdefault(row["path"], row)
    values = sorted(unique.values(), key=lambda row: str(row["path"]))
    count = 0
    for index, left in enumerate(values):
        for right in values[index + 1 :]:
            if left["path"] == right["path"]:
                continue
            left_days = set(left.get("coverage_dates") or ())
            right_days = set(right.get("coverage_dates") or ())
            if left_days and right_days:
                overlaps = bool(left_days & right_days)
            else:
                overlaps = _overlaps(
                    left["start_date"],
                    left["end_date"],
                    right["start_date"],
                    right["end_date"],
                )
            if overlaps:
                count += 1
    return count


def _overlaps(
    left_start: date | None,
    left_end: date | None,
    right_start: date | None,
    right_end: date | None,
) -> bool:
    if None in {left_start, left_end, right_start, right_end}:
        return True
    assert left_start is not None and left_end is not None and right_start is not None and right_end is not None
    return left_start <= right_end and right_start <= left_end


def _parameter_version_key(row: Any) -> tuple[datetime, int]:
    created = _value(row, "created_at")
    if not isinstance(created, datetime):
        created = datetime.min
    return created, int(_value(row, "id") or -1)


def _fee_rule_key(row: Any, contract_code: str, product: str) -> tuple[int, date, int]:
    contract = _clean_text(_value(row, "contract_code")).upper()
    instrument = _clean_text(_value(row, "instrument_symbol")).lower()
    specificity = 2 if contract == contract_code.upper() else 1 if instrument == product.lower() else 0
    effective = _date_or_none(_value(row, "effective_date")) or date.min
    return specificity, effective, int(_value(row, "id") or -1)


def _lineage_detail(
    row: Any | None,
    *,
    source: str,
    effective_start: date | None = None,
    effective_end: date | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "source_row_id": _value(row, "id") if row is not None else None,
        "data_version": _clean_text(_value(row, "data_version")) if row is not None else "",
        "effective_start": effective_start.isoformat() if effective_start else "",
        "effective_end": effective_end.isoformat() if effective_end else "",
    }


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: Sequence[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _batched(values: Sequence[Any], size: int = QUERY_BATCH_SIZE) -> Iterator[tuple[Any, ...]]:
    for index in range(0, len(values), size):
        yield tuple(values[index : index + size])


def _dedupe_rows(rows: Iterable[Any]) -> list[Any]:
    output: dict[tuple[Any, ...], Any] = {}
    for row in rows:
        key = (
            _value(row, "id"),
            _value(row, "contract_code"),
            _value(row, "instrument_symbol"),
            _value(row, "effective_date"),
        )
        output[key] = row
    return list(output.values())


def _value(row: Any, field: str) -> Any:
    return row.get(field) if isinstance(row, dict) else getattr(row, field, None)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _int_or_none(value: Any) -> int | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _date_or_none(value: Any) -> date | None:
    if value in {None, ""}:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text_value = str(value).strip()
    try:
        return date.fromisoformat(text_value[:10])
    except ValueError:
        return None


def _date_or_min(value: Any) -> date:
    parsed = _date_or_none(value)
    return parsed or date.min


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
