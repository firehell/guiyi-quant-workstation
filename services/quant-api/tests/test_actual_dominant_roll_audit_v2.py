from __future__ import annotations

import csv
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any

import duckdb
import pytest

import app.services.rqdata_ingest.actual_dominant_roll_audit_v2 as audit_module
from app.services.rqdata_ingest.actual_dominant_roll_audit_v2 import (
    ACTUAL_DOMINANT_ROLL_REPAIR_REQUIRED,
    ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED,
    CSV_SCHEMAS,
    ActualDominantRollAuditConfig,
    ActualDominantRollAuditResult,
    _batched,
    _build_target_coverage,
    _inspect_parquet,
    _inventory_canonical_actual_files,
    _mapping_completeness_residuals,
    _require_read_only_postgresql,
    _residual,
    _resolve_scope,
    audit_consumer_semantics,
    classify_roll_transitions,
    compress_rank1_ranges,
    determine_formal_gate,
    evaluate_mapping_rows,
    resolve_trading_parameters,
    run_actual_dominant_roll_audit,
    write_actual_dominant_roll_reports,
)


def _mapping(
    day: date,
    contract: str,
    *,
    version: str = "v1",
    rule: str = "volume_open_interest",
    row_id: int = 1,
    registered: bool = True,
) -> dict[str, object]:
    return {
        "product": "jm",
        "trade_date": day,
        "contract": contract,
        "version": version,
        "provider": "rqdata",
        "rule": rule,
        "rank": 1,
        "id": row_id,
        "registered": registered,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_parquet(path: Path, rows: list[tuple[str, str, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            "CREATE TABLE bars(datetime TIMESTAMP, trading_day DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, open_interest DOUBLE)"
        )
        connection.executemany(
            "INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, 1, 1)",
            [(timestamp, trading_day, price, price, price, price) for timestamp, trading_day, price in rows],
        )
        escaped = str(path).replace("'", "''")
        connection.execute(f"COPY bars TO '{escaped}' (FORMAT PARQUET)")


def _write_manifest(root: Path, rows: list[dict[str, object]], name: str = "anything.csv") -> None:
    path = root / "data" / "manifests" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({field for row in rows for field in row})
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _file_row(
    *,
    row_id: int,
    path: str,
    period: str,
    start: date,
    end: date,
    checksum: str,
    contract: str = "JM2309",
    data_role: str = "primary",
    quality_status: str = "passed",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=row_id,
        provider="rqdata",
        data_type="bars",
        instrument_symbol="jm",
        contract_code=contract,
        period=period,
        start_time=datetime.combine(start, datetime.min.time()),
        end_time=datetime.combine(end, datetime.max.time()),
        file_path=path,
        checksum=checksum,
        data_version=f"asset-{row_id}",
        data_role=data_role,
        quality_status=quality_status,
    )


def _quality(
    file_id: int,
    status: str = "passed",
    *,
    start: date = date(2023, 6, 28),
    end: date = date(2023, 6, 29),
    period: str = "1m",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=file_id + 100,
        file_id=file_id,
        provider="rqdata",
        data_type="bars",
        instrument_symbol="jm",
        contract_code="JM2309",
        period=period,
        start_time=datetime.combine(start, datetime.min.time()),
        end_time=datetime.combine(end, datetime.max.time()),
        status=status,
    )


def _write_semantic_sources(root: Path, *, valid: bool) -> None:
    if valid:
        historical = '''
def _load_main_contract_mapping():
    return (MainContractMap.provider == provider, MainContractMap.rule == rule, MainContractMap.rank == rank, MainContractMap.trade_date == trading_day)

def resolve_jm_contract():
    if actual_contract.endswith(".MAIN"):
        raise ValueError

def _load_trading_parameters():
    return query.order_by(FuturesTradingParameter.created_at.desc(), FuturesTradingParameter.id.desc())

def _load_fee_margin_rule():
    return ((FeeMarginRule.contract_code == contract_code) | (FeeMarginRule.contract_code.is_(None) & (FeeMarginRule.instrument_symbol == instrument_symbol)), FeeMarginRule.effective_date.is_(None))
'''
        live = '''
class LiveTargetContractResolver:
    def _mapping(self):
        return (MainContractMap.provider == PROVIDER, MainContractMap.rule == RULE, MainContractMap.rank == 1, MainContractMap.trade_date == trade_date)

    def _parameter_gate(self):
        params = query.order_by(FuturesTradingParameter.created_at.desc(), FuturesTradingParameter.id.desc())
        fee = ((FeeMarginRule.contract_code == contract) | (FeeMarginRule.contract_code.is_(None) & (FeeMarginRule.instrument_symbol == product)), FeeMarginRule.effective_date.is_(None))
        return params, fee

def _actual_contract_or_none(value):
    if is_continuous_contract(value):
        return None
    return value
'''
        reader = '''
class LiveMarketReader:
    def get_bars(self, rows):
        return [row for row in rows if row.bar_status == "confirmed"]
'''
        evaluator = '''
class LiveSignalEvaluator:
    def _evaluate_interval(self, last_bar):
        target = resolve_ready_actual_contract()
        return target["actual_contract"], last_bar.get("close")
'''
        events = '''
def _is_eligible(item):
    actual_contract = item.actual_contract
    return not actual_contract.endswith(".MAIN")

def _features():
    return {"confirmed_bar": True}
'''
    else:
        decoy = '''
def unrelated_decoy():
    return (MainContractMap.provider == provider, MainContractMap.rule == rule, MainContractMap.rank == rank, MainContractMap.trade_date == trading_day, MainContractMap.provider == PROVIDER, MainContractMap.rule == RULE, MainContractMap.rank == 1, MainContractMap.trade_date == trade_date, FuturesTradingParameter.created_at.desc(), FuturesTradingParameter.id.desc(), FeeMarginRule.contract_code == contract_code, FeeMarginRule.instrument_symbol == instrument_symbol, FeeMarginRule.effective_date.is_(None), bar_status == "confirmed", target["actual_contract"], last_bar.get("close"), ".MAIN", True)
'''
        historical = decoy + '''
def _load_main_contract_mapping():
    return None
def resolve_jm_contract():
    return None
def _load_trading_parameters():
    return None
def _load_fee_margin_rule():
    return None
'''
        live = decoy + '''
class LiveTargetContractResolver:
    def _mapping(self):
        return None
    def _parameter_gate(self):
        return None
def _actual_contract_or_none(value):
    return value
'''
        reader = decoy + '''
class LiveMarketReader:
    def get_bars(self, rows):
        return rows
'''
        evaluator = decoy + '''
class LiveSignalEvaluator:
    def _evaluate_interval(self, last_bar):
        return None
'''
        events = decoy + '''
def _is_eligible(item):
    return True
def _features():
    return {}
'''
    files = {
        "services/quant-api/app/backtest/contract_resolver.py": historical,
        "services/quant-api/app/services/live_target_contracts.py": live,
        "services/quant-api/app/services/live_market_reader.py": reader,
        "services/quant-api/app/services/live_signal_evaluator.py": evaluator,
        "services/quant-api/app/services/live_signal_events.py": events,
    }
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def test_mapping_keeps_duplicate_versions_and_selects_one_deterministically() -> None:
    rows = [
        _mapping(date(2026, 1, 2), "JM2605", version="v1", row_id=1),
        _mapping(date(2026, 1, 2), "JM2605", version="v2", row_id=2),
        _mapping(date(2026, 1, 3), "JM2609", row_id=3),
        _mapping(date(2026, 1, 3), "JM2610", version="v2", row_id=4),
        _mapping(date(2026, 1, 4), "JM.MAIN", row_id=5),
        _mapping(date(2026, 1, 5), "JM2609", rule="other_rule", row_id=6),
        _mapping(date(2026, 1, 5), "JM2609", row_id=7),
        _mapping(date(2026, 1, 6), "JM2609", row_id=8, registered=False),
    ]

    evidence, residuals = evaluate_mapping_rows(rows)

    duplicates = [row for row in evidence if row["trade_date"] == "2026-01-02"]
    assert {row["status"] for row in duplicates} == {"duplicate_same_contract"}
    assert [row["version"] for row in duplicates if row["selection"] == "selected_effective"] == ["v2"]
    assert [row["selection"] for row in duplicates].count("selected_effective") == 1
    assert {row["status"] for row in evidence} >= {
        "conflict_different_contract",
        "conflict_different_rule",
        "invalid_actual_contract",
    }
    assert {row["category"] for row in residuals} >= {
        "mapping_conflict",
        "invalid_actual_contract",
    }

    without_ids = [_mapping(date(2026, 2, 2), "JM2605", version="v1"), _mapping(date(2026, 2, 2), "JM2605", version="v2")]
    for row in without_ids:
        row["id"] = None
    no_id_evidence, _ = evaluate_mapping_rows(without_ids)
    assert [row["version"] for row in no_id_evidence if row["selection"] == "selected_effective"] == ["v2"]


def test_mapping_calendar_detects_missing_product_dates_and_provider_boundary() -> None:
    evidence, _ = evaluate_mapping_rows(
        [
            _mapping(date(2023, 1, 3), "JM2305", row_id=1),
            _mapping(date(2023, 1, 5), "JM2305", row_id=2),
        ]
    )
    residuals, boundaries = _mapping_completeness_residuals(
        products=("a", "jm"),
        mapping_evidence=evidence,
        trading_days_by_product={
            "a": (date(2023, 1, 3), date(2023, 1, 4), date(2023, 1, 5)),
            "jm": (date(2023, 1, 3), date(2023, 1, 4), date(2023, 1, 5)),
        },
        audit_end=date(2023, 1, 5),
    )

    assert {(row["product"], row["category"], row["trade_date"]) for row in residuals} >= {
        ("a", "mapping_product_missing", ""),
        ("jm", "mapping_date_missing", "2023-01-04"),
    }
    jm = next(row for row in boundaries if row["product"] == "jm")
    assert jm["provider_boundary_source"] == "rank1_mapping_min"
    assert jm["provider_start_inferred_from_physical"] is False

    no_calendar, _ = _mapping_completeness_residuals(
        products=("jm",),
        mapping_evidence=evidence,
        trading_days_by_product={"jm": ()},
        audit_end=date(2023, 1, 5),
    )
    assert "mapping_calendar_missing" in {row["category"] for row in no_calendar}


def test_partial_jm_calendar_cannot_truncate_any_hard_consumer_window() -> None:
    evidence, _ = evaluate_mapping_rows(
        [
            _mapping(JM_SIGNAL_START := date(2023, 1, 3), "JM2305", row_id=1),
            _mapping(date(2026, 7, 10), "JM2609", row_id=2),
        ]
    )
    residuals, _ = _mapping_completeness_residuals(
        products=("jm",),
        mapping_evidence=evidence,
        trading_days_by_product={"jm": (date(2023, 6, 28), date(2026, 6, 26))},
        audit_end=date(2026, 7, 10),
    )

    calendar_rows = [row for row in residuals if row["category"] == "hard_target_calendar_boundary"]
    assert {
        (row["consumer"], row["period"], row["target_start"], row["target_end"])
        for row in calendar_rows
    } == {
        ("signal_live_reference", "1m", JM_SIGNAL_START.isoformat(), "2026-07-10"),
        ("signal_live_reference", "1d", JM_SIGNAL_START.isoformat(), "2026-07-10"),
    }
    assert all(row["scope"] == "jm_hard" for row in calendar_rows)


def test_rank_ranges_split_on_missing_date_and_rolls_include_real_boundary_evidence() -> None:
    rows = [
        {"product": "jm", "trade_date": date(2026, 1, 2), "contract": "JM2605", "selection": "selected_effective"},
        {"product": "jm", "trade_date": date(2026, 1, 4), "contract": "JM2609", "selection": "selected_effective"},
        {"product": "jm", "trade_date": date(2026, 1, 5), "contract": "JM2605", "selection": "selected_effective"},
        {"product": "jm", "trade_date": date(2026, 1, 6), "contract": "JM2601", "selection": "selected_effective"},
    ]
    days = [date(2026, 1, day) for day in range(2, 7)]

    ranges = compress_rank1_ranges(rows, trading_days=days)
    transitions = classify_roll_transitions(
        rows,
        trading_days=days,
        price_evidence={
            ("JM2605", "JM2609", date(2026, 1, 4)): {"previous_close": 100.0, "current_open": 101.25}
        },
    )

    assert [(row["start_date"], row["end_date"]) for row in ranges] == [
        ("2026-01-02", "2026-01-02"),
        ("2026-01-04", "2026-01-04"),
        ("2026-01-05", "2026-01-05"),
        ("2026-01-06", "2026-01-06"),
    ]
    assert transitions[0]["classification"] == "mapping_gap"
    assert transitions[0]["boundary_status"] == "mapping_gap"
    assert transitions[0]["price_difference"] == 1.25
    assert transitions[0]["price_difference_status"] == "computed_informational"
    assert [row["classification"] for row in transitions[1:]] == ["aba_reversal", "backward_month"]

    normal = classify_roll_transitions(
        [
            {"product": "jm", "trade_date": date(2026, 2, 2), "contract": "JM2605"},
            {"product": "jm", "trade_date": date(2026, 2, 3), "contract": "JM2609"},
        ],
        trading_days=(date(2026, 2, 2), date(2026, 2, 3)),
    )
    assert normal[0]["classification"] == "normal_roll"
    assert normal[0]["boundary_status"] == "passed"


def test_coverage_requires_exact_contract_primary_manifest_quality_sha_duckdb_and_1m_trading_days(
    tmp_path: Path,
) -> None:
    project = tmp_path / "checkout"
    parquet = project / "data" / "parquet" / "JM2309_1m.parquet"
    _write_parquet(
        parquet,
        [
            ("2023-06-27 21:01:00", "2023-06-28", 100.0),
            ("2023-06-28 21:01:00", "2023-06-29", 101.0),
        ],
    )
    digest = _sha256(parquet)
    relative_path = parquet.relative_to(project).as_posix()
    _write_manifest(
        project,
        [
            {
                "product": "jm",
                "actual_contract": "JM2309",
                "period": "1m",
                "data_role": "primary",
                "quality_status": "passed",
                "min_datetime": "2023-06-28",
                "max_datetime": "2023-06-29",
                "checksum": digest,
                "standard_path": relative_path,
                "status": "success",
            }
        ],
    )
    ranges = [
        {
            "product": "jm",
            "contract": "JM2309",
            "start_date": "2023-06-28",
            "end_date": "2023-06-29",
        }
    ]
    files = [
        _file_row(
            row_id=1,
            path=str(project.parent / "old-checkout" / relative_path),
            period="1m",
            start=date(2023, 6, 28),
            end=date(2023, 6, 29),
            checksum=digest,
        )
    ]

    coverage = _build_target_coverage(
        ranges,
        files,
        [_quality(1)],
        project,
        trading_days_by_product={"jm": (date(2023, 6, 28), date(2023, 6, 29))},
        full_scan=True,
    )
    row = next(item for item in coverage if item["consumer"] == "backtest_review" and item["period"] == "1m")

    assert row["status"] == "covered"
    assert row["physical_status"] == "passed"
    assert row["manifest_status"] == "passed"
    assert row["database_status"] == "passed"
    assert row["quality_status"] == "passed"
    assert row["checksum_status"] == "passed"
    assert row["duckdb_status"] == "passed"
    assert row["boundary_status"] == "passed"
    assert row["missing_trading_dates"] == "[]"
    assert row["normalized_path_count"] == 1


def test_quick_coverage_uses_existing_path_and_matching_declared_ranges(tmp_path: Path) -> None:
    project = tmp_path / "project"
    parquet = project / "data" / "parquet" / "JM2309_1m.parquet"
    parquet.parent.mkdir(parents=True, exist_ok=True)
    parquet.write_bytes(b"quick mode must not read parquet contents")
    relative = parquet.relative_to(project).as_posix()
    _write_manifest(
        project,
        [
            {
                "product": "jm",
                "actual_contract": "JM2309",
                "period": "1m",
                "data_role": "primary",
                "quality_status": "passed",
                "min_datetime": "2023-06-28",
                "max_datetime": "2023-06-29",
                "standard_path": relative,
                "status": "success",
            }
        ],
    )

    row = next(
        item
        for item in _build_target_coverage(
            [{"product": "jm", "contract": "JM2309", "start_date": "2023-06-28", "end_date": "2023-06-29"}],
            [
                _file_row(
                    row_id=1,
                    path=relative,
                    period="1m",
                    start=date(2023, 6, 28),
                    end=date(2023, 6, 29),
                    checksum="not-checked-in-quick-mode",
                )
            ],
            [_quality(1)],
            project,
            trading_days_by_product={"jm": (date(2023, 6, 28), date(2023, 6, 29))},
            full_scan=False,
        )
        if item["consumer"] == "backtest_review" and item["period"] == "1m"
    )

    assert row["status"] == "covered"
    assert row["physical_status"] == "passed"
    assert row["database_status"] == "passed"
    assert row["manifest_status"] == "passed"
    assert row["quality_status"] == "passed"
    assert row["checksum_status"] == "not_run"
    assert row["duckdb_status"] == "not_run"
    assert row["boundary_status"] == "passed"
    assert row["boundary_evidence"] == "declared_range"
    assert row["missing_trading_dates"] == "[]"


def test_quick_coverage_does_not_expand_partial_manifest_range_to_full_target(tmp_path: Path) -> None:
    project = tmp_path / "project"
    parquet = project / "data" / "parquet" / "JM2309_1m.parquet"
    parquet.parent.mkdir(parents=True, exist_ok=True)
    parquet.write_bytes(b"quick mode must not read parquet contents")
    relative = parquet.relative_to(project).as_posix()
    _write_manifest(
        project,
        [
            {
                "product": "jm",
                "actual_contract": "JM2309",
                "period": "1m",
                "data_role": "primary",
                "quality_status": "passed",
                "min_datetime": "2023-06-28",
                "max_datetime": "2023-06-28",
                "standard_path": relative,
                "status": "success",
            }
        ],
    )

    row = next(
        item
        for item in _build_target_coverage(
            [{"product": "jm", "contract": "JM2309", "start_date": "2023-06-28", "end_date": "2023-06-29"}],
            [
                _file_row(
                    row_id=1,
                    path=relative,
                    period="1m",
                    start=date(2023, 6, 28),
                    end=date(2023, 6, 29),
                    checksum="not-checked-in-quick-mode",
                )
            ],
            [_quality(1)],
            project,
            trading_days_by_product={"jm": (date(2023, 6, 28), date(2023, 6, 29))},
            full_scan=False,
        )
        if item["consumer"] == "backtest_review" and item["period"] == "1m"
    )

    assert row["status"] == "residual"
    assert row["physical_status"] == "failed"
    assert row["database_status"] == "passed"
    assert row["manifest_status"] == "failed"
    assert row["quality_status"] == "passed"
    assert row["checksum_status"] == "not_run"
    assert row["duckdb_status"] == "not_run"
    assert row["boundary_status"] == "failed"
    assert row["missing_trading_dates"] == '["2023-06-29"]'


def test_coverage_blocks_physical_only_db_only_quality_checksum_boundary_and_manifest_overlap(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    first = project / "data" / "parquet" / "first.parquet"
    second = project / "data" / "parquet" / "second.parquet"
    _write_parquet(first, [("2023-06-28 09:01:00", "2023-06-28", 100.0)])
    _write_parquet(second, [("2023-06-28 09:02:00", "2023-06-28", 100.5)])
    first_digest = _sha256(first)
    second_digest = _sha256(second)
    _write_manifest(
        project,
        [
            {
                "product": "jm",
                "actual_contract": "JM2309",
                "period": "1m",
                "data_role": "primary",
                "quality_status": "passed",
                "min_datetime": "2023-06-28",
                "max_datetime": "2023-06-29",
                "checksum": first_digest,
                "standard_path": first.relative_to(project).as_posix(),
                "status": "success",
            },
            {
                "product": "jm",
                "actual_contract": "JM2309",
                "period": "1m",
                "data_role": "primary",
                "quality_status": "passed",
                "min_datetime": "2023-06-28",
                "max_datetime": "2023-06-29",
                "checksum": second_digest,
                "standard_path": second.relative_to(project).as_posix(),
                "status": "success",
            },
        ],
    )
    missing = project / "data" / "parquet" / "missing.parquet"
    ranges = [{"product": "jm", "contract": "JM2309", "start_date": "2023-06-28", "end_date": "2023-06-29"}]
    files = [
        _file_row(
            row_id=1,
            path=first.relative_to(project).as_posix(),
            period="1m",
            start=date(2023, 6, 28),
            end=date(2023, 6, 29),
            checksum="wrong-checksum",
            quality_status="failed",
        ),
        _file_row(
            row_id=2,
            path=missing.relative_to(project).as_posix(),
            period="1m",
            start=date(2023, 6, 28),
            end=date(2023, 6, 29),
            checksum="missing",
        ),
    ]

    row = next(
        item
        for item in _build_target_coverage(
            ranges,
            files,
            [_quality(1, "failed"), _quality(2)],
            project,
            trading_days_by_product={"jm": (date(2023, 6, 28), date(2023, 6, 29))},
            full_scan=True,
        )
        if item["consumer"] == "backtest_review" and item["period"] == "1m"
    )

    assert row["status"] == "residual"
    assert row["manifest_overlap_count"] == 1
    assert row["manifest_status"] == "failed_overlap"
    assert row["quality_status"] == "passed"
    assert row["checksum_status"] == "failed"
    assert row["boundary_status"] == "failed"
    assert row["missing_trading_dates"] == '["2023-06-29"]'
    assert row["physical_only_count"] == 1
    assert row["db_only_count"] == 1


def test_1d_boundary_uses_daily_datetime_dates(tmp_path: Path) -> None:
    project = tmp_path / "project"
    parquet = project / "data" / "parquet" / "JM2309_1d.parquet"
    _write_parquet(
        parquet,
        [
            ("2023-06-28 00:00:00", "2023-06-28", 100.0),
            ("2023-06-29 00:00:00", "2023-06-29", 101.0),
        ],
    )
    digest = _sha256(parquet)
    relative = parquet.relative_to(project).as_posix()
    _write_manifest(
        project,
        [
            {
                "product": "jm",
                "actual_contract": "JM2309",
                "period": "1d",
                "data_role": "primary",
                "quality_status": "passed",
                "min_datetime": "2023-06-28",
                "max_datetime": "2023-06-29",
                "checksum": digest,
                "standard_path": relative,
                "status": "success",
            }
        ],
    )
    ranges = [{"product": "jm", "contract": "JM2309", "start_date": "2023-06-28", "end_date": "2023-06-29"}]
    files = [_file_row(row_id=1, path=relative, period="1d", start=date(2023, 6, 28), end=date(2023, 6, 29), checksum=digest)]

    row = next(
        item
        for item in _build_target_coverage(
            ranges,
            files,
            [_quality(1, period="1d")],
            project,
            trading_days_by_product={"jm": (date(2023, 6, 28), date(2023, 6, 29))},
            full_scan=True,
        )
        if item["consumer"] == "backtest_review" and item["period"] == "1d"
    )
    assert row["status"] == "covered"
    assert row["boundary_evidence"] == "datetime_date"


def test_manifest_quality_and_all_checksum_declarations_use_their_own_evidence(tmp_path: Path) -> None:
    project = tmp_path / "project"
    parquet = project / "data" / "parquet" / "JM2309_1m.parquet"
    _write_parquet(
        parquet,
        [
            ("2023-06-28 09:01:00", "2023-06-28", 100.0),
            ("2023-06-29 09:01:00", "2023-06-29", 101.0),
        ],
    )
    digest = _sha256(parquet)
    relative = parquet.relative_to(project).as_posix()
    manifest_base = {
        "product": "jm",
        "actual_contract": "JM2309",
        "period": "1m",
        "data_role": "primary",
        "quality_status": "passed",
        "min_datetime": "2023-06-28",
        "max_datetime": "2023-06-28",
        "standard_path": relative,
        "status": "success",
    }
    _write_manifest(
        project,
        [
            {**manifest_base, "checksum": digest},
            {**manifest_base, "checksum": ""},
        ],
    )
    files = [
        _file_row(
            row_id=1,
            path=relative,
            period="1m",
            start=date(2023, 6, 28),
            end=date(2023, 6, 29),
            checksum=digest,
        ),
        _file_row(
            row_id=2,
            path=relative,
            period="1m",
            start=date(2023, 6, 28),
            end=date(2023, 6, 29),
            checksum="",
        ),
    ]
    ranges = [{"product": "jm", "contract": "JM2309", "start_date": "2023-06-28", "end_date": "2023-06-29"}]

    row = next(
        item
        for item in _build_target_coverage(
            ranges,
            files,
            [
                _quality(1, start=date(2023, 6, 28), end=date(2023, 6, 28)),
                _quality(2, start=date(2023, 6, 28), end=date(2023, 6, 28)),
            ],
            project,
            trading_days_by_product={"jm": (date(2023, 6, 28), date(2023, 6, 29))},
            full_scan=True,
        )
        if item["consumer"] == "backtest_review" and item["period"] == "1m"
    )

    assert row["physical_status"] == "passed"
    assert row["database_status"] == "passed"
    assert row["manifest_status"] == "failed"
    assert row["quality_status"] == "failed"
    assert row["checksum_status"] == "failed"
    evidence = json.loads(row["path_evidence"])
    assert evidence[0]["db_checksum_declarations_complete"] is False
    assert evidence[0]["manifest_checksum_declarations_complete"] is False


def test_canonical_actual_physical_inventory_exposes_file_without_db_or_manifest(tmp_path: Path) -> None:
    project = tmp_path / "project"
    parquet = (
        project
        / "data/parquet/canonical/bars/provider=rqdata/period=1m/exchange=DCE/symbol=jm/contract=JM2309/orphan.parquet"
    )
    _write_parquet(parquet, [("2023-06-28 09:01:00", "2023-06-28", 100.0)])

    inventory = _inventory_canonical_actual_files(
        project,
        products={"jm"},
        contracts={"JM2309"},
        periods={"1m"},
    )
    assert inventory == [
        {
            "product": "jm",
            "contract": "JM2309",
            "period": "1m",
            "provider": "rqdata",
            "path": parquet.resolve(),
        }
    ]

    row = next(
        item
        for item in _build_target_coverage(
            [{"product": "jm", "contract": "JM2309", "start_date": "2023-06-28", "end_date": "2023-06-28"}],
            [],
            [],
            project,
            trading_days_by_product={"jm": (date(2023, 6, 28),)},
            full_scan=True,
        )
        if item["consumer"] == "backtest_review" and item["period"] == "1m"
    )
    assert row["physical_status"] == "passed"
    assert row["physical_only_count"] == 1
    assert row["normalized_path_count"] == 1
    assert row["database_status"] == "failed"
    assert row["manifest_status"] == "failed"


def test_1m_parquet_without_trading_day_cannot_prove_trading_day_boundary(tmp_path: Path) -> None:
    path = tmp_path / "missing-trading-day.parquet"
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            "CREATE TABLE bars(datetime TIMESTAMP, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, open_interest DOUBLE)"
        )
        connection.execute("INSERT INTO bars VALUES ('2023-06-28 09:01:00', 1, 1, 1, 1, 1, 1)")
        escaped = str(path).replace("'", "''")
        connection.execute(f"COPY bars TO '{escaped}' (FORMAT PARQUET)")

    inspection = _inspect_parquet(path, "1m")
    assert inspection["readable"] is False
    assert "trading_day" in inspection["error"]


def test_parameter_selection_handles_nullable_dates_versions_mixed_fallback_and_missing() -> None:
    exact_old = {
        "id": 1,
        "data_version": "v1",
        "created_at": datetime(2026, 1, 2),
        "trade_date": date(2026, 1, 3),
        "price_tick": 0.5,
        "long_margin_ratio": 0.12,
    }
    exact_new = {
        "id": 2,
        "data_version": "v2",
        "created_at": datetime(2026, 1, 3),
        "trade_date": date(2026, 1, 3),
        "price_tick": 0.8,
        "long_margin_ratio": 0.13,
    }
    resolved = resolve_trading_parameters(
        contract={"id": 9, "contract_multiplier": 60},
        exact=[exact_old, exact_new],
        fee_rules=[
            {
                "id": 10,
                "contract_code": None,
                "instrument_symbol": "jm",
                "effective_date": None,
                "volume_multiple": 80,
                "margin_rate": 0.1,
                "open_fee": 3.0,
            },
            {
                "id": 11,
                "contract_code": "JM2605",
                "instrument_symbol": "jm",
                "effective_date": date(2026, 1, 2),
                "volume_multiple": None,
                "margin_rate": 0.11,
                "open_fee": 4.0,
                "close_fee": 5.0,
            },
        ],
        contract_code="JM2605",
        product="jm",
        trade_date=date(2026, 1, 3),
    )

    assert resolved["values"]["price_tick"] == 0.8
    assert resolved["lineage_details"]["price_tick"]["source_row_id"] == 2
    assert resolved["lineage_details"]["price_tick"]["data_version"] == "v2"
    assert resolved["values"]["contract_multiplier"] == 60
    assert resolved["lineage"]["contract_multiplier"] == "contracts.contract_multiplier"
    assert resolved["values"]["open_commission"] == 4.0
    assert resolved["lineage_details"]["open_commission"]["effective_start"] == "2026-01-02"
    assert resolved["values"]["close_commission"] == 5.0
    assert resolved["values"]["close_today_commission"] is None
    assert resolved["complete"] is False


def test_parameter_precedence_matches_consumer_order_and_rejects_global_fee_rule() -> None:
    created = datetime(2026, 1, 3)
    exact_by_higher_id = resolve_trading_parameters(
        contract={"id": 9, "exchange_code": "DCE", "contract_multiplier": 60},
        exact=[
            {
                "id": 1,
                "data_version": "z-version",
                "created_at": created,
                "trade_date": date(2026, 1, 3),
                "price_tick": 0.5,
            },
            {
                "id": 2,
                "data_version": "a-version",
                "created_at": created,
                "trade_date": date(2026, 1, 3),
                "price_tick": 0.8,
            },
        ],
        fee_rules=[],
        contract_code="JM2605",
        product="jm",
        trade_date=date(2026, 1, 3),
    )
    assert exact_by_higher_id["values"]["price_tick"] == 0.8
    assert exact_by_higher_id["lineage_details"]["price_tick"]["source_row_id"] == 2

    global_only = resolve_trading_parameters(
        contract={"id": 9, "exchange_code": "DCE", "contract_multiplier": 60},
        exact=None,
        fee_rules=[
            {
                "id": 11,
                "exchange_code": "DCE",
                "contract_code": None,
                "instrument_symbol": None,
                "effective_date": None,
                "price_tick": 1.0,
                "volume_multiple": 80,
                "margin_rate": 0.1,
                "open_fee": 3.0,
                "close_fee": 3.0,
                "close_today_fee": 3.0,
            }
        ],
        contract_code="JM2605",
        product="jm",
        trade_date=date(2026, 1, 3),
    )
    assert global_only["lineage"]["price_tick"] == "missing"
    assert global_only["values"]["contract_multiplier"] == 60
    assert global_only["complete"] is False


def test_semantic_audit_detects_live_rule_and_confirmed_bar_mismatch(tmp_path: Path) -> None:
    _write_semantic_sources(tmp_path, valid=False)

    evidence, residuals = audit_consumer_semantics(tmp_path)

    assert evidence["mapping_semantics_status"] == "mismatch"
    assert evidence["trigger_semantics_status"] == "mismatch"
    assert evidence["parameter_semantics_status"] == "mismatch"
    assert {row["category"] for row in residuals} == {
        "historical_live_mapping_semantics",
        "actual_confirmed_trigger_semantics",
        "historical_live_parameter_semantics",
    }
    assert all(row["scope"] == "formal" for row in residuals)


def test_semantic_audit_passes_only_equivalent_mapping_and_actual_confirmed_trigger(tmp_path: Path) -> None:
    _write_semantic_sources(tmp_path, valid=True)

    evidence, residuals = audit_consumer_semantics(tmp_path)
    assert evidence["mapping_semantics_status"] == "passed"
    assert evidence["trigger_semantics_status"] == "passed"
    assert evidence["parameter_semantics_status"] == "passed"
    assert residuals == []


def test_formal_gate_requires_direct_full_unfiltered_canonical_scope_and_no_blockers(tmp_path: Path) -> None:
    universe = tmp_path / "data" / "universe" / "full_products_90.txt"
    universe.parent.mkdir(parents=True)
    universe.write_text("\n".join(["jm", *[f"p{index:02d}" for index in range(89)]]) + "\n", encoding="utf-8")
    products, scope = _resolve_scope(ActualDominantRollAuditConfig(project_root=tmp_path))
    assert len(products) == 90
    assert scope["canonical_product_scope"] is True

    ready, eligibility = determine_formal_gate(
        scan_mode="full",
        filtered=False,
        direct_postgresql=True,
        canonical_product_scope=True,
        residuals=[{"scope": "inventory"}],
    )
    assert ready == ACTUAL_DOMINANT_ROLL_TARGETS_VERIFIED
    assert eligibility is True

    for kwargs in (
        {"scan_mode": "quick", "filtered": False, "direct_postgresql": True, "canonical_product_scope": True},
        {"scan_mode": "full", "filtered": True, "direct_postgresql": True, "canonical_product_scope": True},
        {"scan_mode": "full", "filtered": False, "direct_postgresql": False, "canonical_product_scope": True},
        {"scan_mode": "full", "filtered": False, "direct_postgresql": True, "canonical_product_scope": False},
    ):
        status, eligible = determine_formal_gate(residuals=[], **kwargs)
        assert status == ACTUAL_DOMINANT_ROLL_REPAIR_REQUIRED
        assert eligible is False
    blocked, eligible = determine_formal_gate(
        scan_mode="full",
        filtered=False,
        direct_postgresql=True,
        canonical_product_scope=True,
        residuals=[{"scope": "formal"}],
    )
    assert blocked == ACTUAL_DOMINANT_ROLL_REPAIR_REQUIRED
    assert eligible is True


def test_postgresql_read_only_statement_is_issued_and_sqlite_is_never_formal(tmp_path: Path) -> None:
    class Session:
        def __init__(self, dialect: str) -> None:
            self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect))
            self.statements: list[str] = []

        def get_bind(self) -> object:
            return self.bind

        def execute(self, statement: object) -> None:
            self.statements.append(str(statement))

    postgres = Session("postgresql")
    assert _require_read_only_postgresql(ActualDominantRollAuditConfig(project_root=tmp_path), postgres) is True
    assert postgres.statements == ["SET TRANSACTION READ ONLY"]

    sqlite = Session("sqlite")
    assert (
        _require_read_only_postgresql(
            ActualDominantRollAuditConfig(project_root=tmp_path, require_postgresql=False),
            sqlite,
        )
        is False
    )
    assert sqlite.statements == []
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        _require_read_only_postgresql(ActualDominantRollAuditConfig(project_root=tmp_path), sqlite)


def test_report_schemas_are_stable_when_empty_and_residual_dimensions_are_unique(tmp_path: Path) -> None:
    result = ActualDominantRollAuditResult(
        [],
        [],
        [],
        [],
        [],
        [],
        {"status": ACTUAL_DOMINANT_ROLL_REPAIR_REQUIRED},
        {"source": "test"},
    )
    output = tmp_path / "report"
    outputs = write_actual_dominant_roll_reports(result, output)

    assert set(outputs) == {
        "rank1_uniqueness.csv",
        "rank1_ranges.csv",
        "actual_target_coverage.csv",
        "roll_transition_audit.csv",
        "trading_parameter_lineage.csv",
        "actual_residuals.csv",
        "ACTUAL_DOMINANT_ROLL_SUMMARY.md",
        "audit_evidence.json",
    }
    for name, schema in CSV_SCHEMAS.items():
        assert (output / name).read_text(encoding="utf-8").splitlines()[0] == ",".join(schema)
    with pytest.raises(FileExistsError):
        write_actual_dominant_roll_reports(result, output)

    source = (Path(__file__).parents[1] / "app/services/rqdata_ingest/actual_dominant_roll_audit_v2.py").read_text(
        encoding="utf-8"
    )
    assert "rqdatac" not in source
    assert "import rqdata" not in source
    assert 'legacy_other": 45' not in source

    first = _residual(
        "target_coverage",
        "jm",
        date(2023, 6, 28),
        "failed layers: checksum",
        "repair checksum",
        consumer="backtest_review",
        period="1m",
        contract="JM2309",
        target_start=date(2023, 6, 28),
        target_end=date(2023, 6, 29),
    )
    second = _residual(
        "target_coverage",
        "jm",
        date(2023, 6, 28),
        "failed layers: checksum",
        "repair checksum",
        consumer="signal_live_reference",
        period="1d",
        contract="JM2309",
        target_start=date(2023, 6, 28),
        target_end=date(2023, 6, 29),
    )
    assert first["residual_id"] != second["residual_id"]


def test_query_batching_is_bounded_and_lossless() -> None:
    batches = list(_batched(tuple(range(1201))))
    assert [len(batch) for batch in batches] == [500, 500, 201]
    assert [value for batch in batches for value in batch] == list(range(1201))


def test_git_snapshot_failure_is_explicit_unavailable_and_db_source_is_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_git(*args: object, **kwargs: object) -> object:
        raise subprocess.CalledProcessError(1, ["git"])

    monkeypatch.setattr(subprocess, "run", fail_git)
    assert audit_module._git_snapshot(tmp_path) == {
        "branch": "unavailable",
        "head": "unavailable",
        "dirty": "unavailable",
        "status": "unavailable",
    }
    assert audit_module._db_snapshot_source(True) == "direct_postgresql"
    assert audit_module._db_snapshot_source(False) == "unavailable"


def test_git_snapshot_records_only_local_branch_head_and_dirty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = iter(["codex/audit\n", "abc123\n", "?? local-file\n"])
    commands: list[list[str]] = []

    def fake_git(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, next(outputs), "")

    monkeypatch.setattr(subprocess, "run", fake_git)

    assert audit_module._git_snapshot(tmp_path) == {
        "branch": "codex/audit",
        "head": "abc123",
        "dirty": True,
        "status": "available",
    }
    assert commands == [
        ["git", "-C", str(tmp_path), "branch", "--show-current"],
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        ["git", "-C", str(tmp_path), "status", "--porcelain", "--untracked-files=normal"],
    ]


def test_run_orchestrates_bounded_read_only_loaders_semantics_summary_and_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping = SimpleNamespace(
        instrument_symbol="jm",
        trade_date=date(2023, 1, 3),
        contract_code="JM2305",
        data_version="v1",
        provider="rqdata",
        rule="volume_open_interest",
        rank=1,
        id=1,
        created_at=datetime(2023, 1, 3),
    )
    rank2_mapping = SimpleNamespace(
        instrument_symbol="jm",
        trade_date=date(2023, 1, 3),
        contract_code="JM2309",
        data_version="v1",
        provider="rqdata",
        rule="volume_open_interest",
        rank=2,
        id=2,
        created_at=datetime(2023, 1, 3),
    )
    jm_before_hard_window = SimpleNamespace(
        instrument_symbol="jm",
        trade_date=date(2023, 1, 2),
        contract_code="JM2305",
        data_version="v1",
        provider="rqdata",
        rule="volume_open_interest",
        rank=1,
        id=3,
        created_at=datetime(2023, 1, 2),
    )
    jm_at_audit_end = SimpleNamespace(
        instrument_symbol="jm",
        trade_date=date(2026, 7, 10),
        contract_code="JM2609",
        data_version="v1",
        provider="rqdata",
        rule="volume_open_interest",
        rank=1,
        id=4,
        created_at=datetime(2026, 7, 10),
    )
    jm_after_audit_end = SimpleNamespace(
        instrument_symbol="jm",
        trade_date=date(2026, 7, 11),
        contract_code="JM2609",
        data_version="v1",
        provider="rqdata",
        rule="volume_open_interest",
        rank=1,
        id=5,
        created_at=datetime(2026, 7, 11),
    )
    rb_mapping = SimpleNamespace(
        instrument_symbol="rb",
        trade_date=date(2023, 1, 3),
        contract_code="RB2305",
        data_version="v1",
        provider="rqdata",
        rule="volume_open_interest",
        rank=1,
        id=6,
        created_at=datetime(2023, 1, 3),
    )
    contract = SimpleNamespace(
        id=10,
        contract_code="JM2305",
        instrument_symbol="jm",
        exchange_code="DCE",
        contract_multiplier=60,
    )
    jm_audit_end_contract = SimpleNamespace(
        id=11,
        contract_code="JM2609",
        instrument_symbol="jm",
        exchange_code="DCE",
        contract_multiplier=60,
    )
    rb_contract = SimpleNamespace(
        id=12,
        contract_code="RB2305",
        instrument_symbol="rb",
        exchange_code="SHFE",
        contract_multiplier=10,
    )

    class FakeSession:
        def __init__(self) -> None:
            self.statements: list[str] = []
            self.rollback_count = 0
            self.scalar_calls = 0

        def get_bind(self) -> object:
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement: object) -> None:
            self.statements.append(str(statement))

        def scalars(self, statement: object) -> list[object]:
            self.scalar_calls += 1
            statement_text = str(statement)
            parameters = getattr(statement, "compile")().params
            assert "main_contract_map.trade_date <=" in statement_text
            assert "main_contract_map.rank =" in statement_text
            rank_filter = next(value for key, value in parameters.items() if key.startswith("rank_"))
            assert rank_filter == 1
            products_filter = next(value for key, value in parameters.items() if key.startswith("lower_"))
            audit_end_filter = next(value for key, value in parameters.items() if key.startswith("trade_date_"))
            fixtures = (
                jm_before_hard_window,
                mapping,
                rank2_mapping,
                jm_at_audit_end,
                jm_after_audit_end,
                rb_mapping,
            )
            return [
                row
                for row in fixtures
                if row.rank == rank_filter
                and row.instrument_symbol in products_filter
                and row.trade_date <= audit_end_filter
            ]

        def rollback(self) -> None:
            self.rollback_count += 1

    calls: dict[str, object] = {}
    engine_root = tmp_path / "audit-engine"
    data_git = {"branch": "data-main", "head": "data-head", "dirty": False, "status": "available"}
    engine_git = {"branch": "codex/audit", "head": "engine-head", "dirty": True, "status": "available"}
    monkeypatch.setattr(audit_module, "_audit_engine_repo_root", lambda: engine_root, raising=False)
    monkeypatch.setattr(
        audit_module,
        "_git_snapshot",
        lambda root: data_git if root == tmp_path.resolve(strict=False) else engine_git,
        raising=False,
    )
    monkeypatch.setattr(
        audit_module,
        "_load_contracts",
        lambda session, codes: calls.setdefault("contracts", tuple(codes))
        and [contract, jm_audit_end_contract, rb_contract],
    )
    monkeypatch.setattr(
        audit_module,
        "_load_trading_days",
        lambda session, products, selected, contracts, audit_end: calls.setdefault("calendar_products", tuple(products))
        and {
            "jm": (date(2023, 1, 2), date(2023, 1, 3), date(2026, 7, 10)),
            "rb": (date(2023, 1, 3),),
        },
    )
    monkeypatch.setattr(
        audit_module,
        "_load_target_files",
        lambda session, contracts: calls.setdefault("target_contracts", tuple(contracts)) and [],
    )
    monkeypatch.setattr(audit_module, "_load_quality_rows", lambda session, ids: [])

    original_evaluate = audit_module.evaluate_mapping_rows

    def capture_evaluate(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        calls["evaluated_mapping_ranks"] = tuple(row["rank"] for row in rows)
        return original_evaluate(rows)

    monkeypatch.setattr(audit_module, "evaluate_mapping_rows", capture_evaluate)

    def coverage(*args: object, **kwargs: object) -> list[dict[str, object]]:
        calls["coverage_max_workers"] = kwargs["max_workers"]
        return []

    monkeypatch.setattr(audit_module, "_build_target_coverage", coverage)
    monkeypatch.setattr(audit_module, "_roll_price_evidence", lambda *args: {})
    monkeypatch.setattr(
        audit_module,
        "_load_parameter_rows",
        lambda session, selected: calls.setdefault("parameter_pairs", tuple((row["contract"], row["trade_date"]) for row in selected))
        and ([], []),
    )
    def parameter_lineage(
        selected: list[dict[str, Any]],
        *args: object,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        calls["lineage_pairs"] = tuple((row["contract"], row["trade_date"]) for row in selected)
        return [], []

    monkeypatch.setattr(audit_module, "_parameter_lineage", parameter_lineage)
    semantic_residual = _residual(
        "historical_live_parameter_semantics",
        "jm",
        None,
        "consumer parameter semantics differ",
        "align consumers",
        scope="formal",
    )
    monkeypatch.setattr(
        audit_module,
        "audit_consumer_semantics",
        lambda root: (
            {
                "mapping_semantics_status": "passed",
                "trigger_semantics_status": "passed",
                "parameter_semantics_status": "mismatch",
            },
            [semantic_residual],
        ),
    )
    session = FakeSession()

    result = run_actual_dominant_roll_audit(
        ActualDominantRollAuditConfig(
            project_root=tmp_path,
            products=("jm", "rb"),
            max_workers=3,
        ),
        session,
    )

    assert session.statements == ["SET TRANSACTION READ ONLY"]
    assert session.scalar_calls == 1
    assert session.rollback_count == 1
    assert calls == {
        "contracts": ("JM2305", "JM2609", "RB2305"),
        "calendar_products": ("jm", "rb"),
        "target_contracts": ("JM2305", "JM2609"),
        "evaluated_mapping_ranks": (1, 1, 1, 1),
        "coverage_max_workers": 3,
        "parameter_pairs": (("JM2305", "2023-01-03"), ("JM2609", "2026-07-10")),
        "lineage_pairs": (("JM2305", "2023-01-03"), ("JM2609", "2026-07-10")),
    }
    assert result.summary["status"] == ACTUAL_DOMINANT_ROLL_REPAIR_REQUIRED
    assert result.summary["scope"] == "filtered_smoke"
    assert result.summary["direct_postgresql"] is True
    assert result.summary["db_snapshot_source"] == "direct_postgresql"
    assert result.summary["transaction_read_only"] is True
    assert result.summary["data_environment_git"] == data_git
    assert result.summary["audit_engine_git"] == engine_git
    assert result.summary["parameter_semantics"] == "mismatch"
    assert result.summary["parameter_scope"] == "jm_hard_consumer_window"
    assert result.summary["parameter_mapping_day_count"] == 2
    assert result.summary["formal_residual_count"] == 1
    assert result.summary["max_workers"] == 3
    assert result.evidence["db_snapshot_source"] == "direct_postgresql"
    assert result.evidence["git_snapshots"] == {
        "data_environment": data_git,
        "audit_engine": engine_git,
    }
    assert "historical_live_parameter_semantics" in {row["category"] for row in result.actual_residuals}


def test_run_rolls_back_when_a_bounded_loader_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mapping = SimpleNamespace(
        instrument_symbol="jm",
        trade_date=date(2023, 1, 3),
        contract_code="JM2305",
        data_version="v1",
        provider="rqdata",
        rule="volume_open_interest",
        rank=1,
        id=1,
        created_at=datetime(2023, 1, 3),
    )

    class FakeSession:
        rollback_count = 0

        def get_bind(self) -> object:
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement: object) -> None:
            pass

        def scalars(self, statement: object) -> list[object]:
            return [mapping]

        def rollback(self) -> None:
            self.rollback_count += 1

    def fail_loader(session: object, codes: object) -> list[object]:
        raise RuntimeError("bounded loader failed")

    monkeypatch.setattr(audit_module, "_load_contracts", fail_loader)
    session = FakeSession()
    with pytest.raises(RuntimeError, match="bounded loader failed"):
        run_actual_dominant_roll_audit(
            ActualDominantRollAuditConfig(project_root=tmp_path, products=("jm",)),
            session,
        )
    assert session.rollback_count == 1


def test_report_bundle_is_atomic_on_write_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = ActualDominantRollAuditResult([], [], [], [], [], [], {"status": "blocked"}, {})
    output = tmp_path / "report"

    def fail_write(path: Path, rows: object, fields: object) -> None:
        raise OSError("simulated report failure")

    monkeypatch.setattr(audit_module, "_write_csv", fail_write)
    with pytest.raises(OSError, match="simulated report failure"):
        write_actual_dominant_roll_reports(result, output)

    assert not output.exists()
    assert list(tmp_path.glob(".report.tmp-*")) == []


def test_config_rejects_wrong_audit_end() -> None:
    with pytest.raises(ValueError):
        ActualDominantRollAuditConfig(project_root=Path("."), audit_end=date(2026, 7, 9))
