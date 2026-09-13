#!/usr/bin/env python3
"""Deterministic, read-only acceptance for the frozen Newow weekly closeout."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Callable, TextIO

from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.product_contracts import (
    ActionKind,
    FeatureRuntimeStatus,
    ProductFrequency,
    ProductStrategy,
    TradeEligibility,
)
from guiyi_quant.newow.product_identity import (
    FUTURES_ADAPTATION_VERSION,
    REFERENCE_MODEL_VERSION,
    utc_timestamp,
)


FROZEN_AS_OF = datetime(2026, 9, 13, 6, 36, 13, tzinfo=UTC)
_PT_PRODUCT = "pt"
_PT_CONTRACT = "PT2610"
_PENDING = frozenset({"UNKNOWN", "UNSTARTED"})
_ENUMERATION_SECTIONS = ("chart", "auxiliary", "reference", "explanation")
_CASE_SECTIONS = frozenset(
    {
        "chart",
        "auxiliary:macd",
        "auxiliary:main_force_control",
        "auxiliary:up_down_energy",
        "auxiliary:zhaoyao_mirror",
        "auxiliary:cup_handle",
        "reference",
        "explanation",
        "comparator",
    }
)
_STRATEGIES = tuple(item.value for item in ProductStrategy)
_HEX64 = re.compile(r"[0-9a-f]{64}")


def _instant(value: datetime | str) -> datetime:
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(value.replace("Z", "+00:00"))
        )
        return utc_timestamp(parsed)
    except (TypeError, ValueError, AttributeError):
        raise ValueError("AS_OF_INVALID") from None


def _json_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_value(item) for item in value]
    return value


def _meta_violations(meta: object, prefix: str, expected_as_of: datetime) -> list[str]:
    from app.market_data.newow.product_service import SCHEMA_VERSION

    violations: list[str] = []
    expected_identity = build_product_identity(
        _PT_PRODUCT, ProductStrategy.MAIN_RISE, ProductFrequency.WEEKLY
    )
    if getattr(meta, "schema_version", None) != SCHEMA_VERSION:
        violations.append(f"{prefix}_SCHEMA_MISMATCH")
    if getattr(meta, "identity", None) != expected_identity:
        violations.append(f"{prefix}_IDENTITY_MISMATCH")
    if getattr(meta, "as_of", None) != expected_as_of:
        violations.append(f"{prefix}_AS_OF_MISMATCH")
    if getattr(meta, "reference_model_version", None) != REFERENCE_MODEL_VERSION:
        violations.append(f"{prefix}_CONTRACT_MISMATCH")
    if getattr(meta, "futures_adaptation_version", None) != FUTURES_ADAPTATION_VERSION:
        violations.append(f"{prefix}_CONTRACT_MISMATCH")
    if getattr(meta, "data_revision_identity", object()) is not None:
        violations.append(f"{prefix}_DATA_REVISION_UNEXPECTED")
    digest = getattr(meta, "input_content_sha256", None)
    if not isinstance(digest, str) or _HEX64.fullmatch(digest) is None:
        violations.append(f"{prefix}_INPUT_HASH_INVALID")
    return violations


def validate_pt_initial_clear(
    chart_result: object,
    reference_result: object,
    *,
    expected_as_of: datetime | str = FROZEN_AS_OF,
) -> dict[str, object]:
    """Validate the typed PT2610 initial-CLEAR result without replaying history."""

    from app.market_data.newow.product_service import (
        NewowProductResult,
        ProductSection,
    )

    expected = _instant(expected_as_of)
    violations: list[str] = []
    if not isinstance(chart_result, NewowProductResult):
        violations.append("CHART_RESULT_TYPE_INVALID")
    if not isinstance(reference_result, NewowProductResult):
        violations.append("REFERENCE_RESULT_TYPE_INVALID")
    if violations:
        return {"schema_version": "newow_weekly_pt_acceptance_v1", "accepted": False, "violations": violations}

    violations.extend(_meta_violations(chart_result.meta, "CHART", expected))
    violations.extend(_meta_violations(reference_result.meta, "REFERENCE", expected))
    if chart_result.section is not ProductSection.CHART:
        violations.append("CHART_SECTION_MISMATCH")
    if reference_result.section is not ProductSection.REFERENCE:
        violations.append("REFERENCE_SECTION_MISMATCH")

    chart = chart_result.chart
    reference = reference_result.reference
    if chart.delivery != "delivered":
        violations.append("CHART_NOT_DELIVERED")
    if chart.status is None or chart.status.status is not FeatureRuntimeStatus.READY:
        violations.append("CHART_NOT_READY")
    if chart.value is None:
        violations.append("CHART_VALUE_MISSING")
    if reference.delivery != "delivered":
        violations.append("REFERENCE_NOT_DELIVERED")
    if (
        reference.status is None
        or reference.status.status is not FeatureRuntimeStatus.READY
    ):
        violations.append("REFERENCE_NOT_READY")
    if reference.value is None:
        violations.append("REFERENCE_VALUE_MISSING")

    chart_token = chart_result.meta.snapshot_token
    reference_token = reference_result.meta.snapshot_token
    if not isinstance(chart_token, str) or not chart_token.strip():
        violations.append("CHART_SNAPSHOT_TOKEN_MISSING")
    if not isinstance(reference_token, str) or not reference_token.strip():
        violations.append("REFERENCE_SNAPSHOT_TOKEN_MISSING")
    if chart_token != reference_token:
        violations.append("SNAPSHOT_TOKEN_MISMATCH")

    initial_clear = None
    trades: tuple[object, ...] = ()
    if chart.value is not None:
        actions = tuple(getattr(getattr(chart.value, "replay", None), "actions", ()))
        candidates = tuple(
            action
            for action in actions
            if getattr(action, "physical_contract", None) == _PT_CONTRACT
            and getattr(action, "trade_eligibility", None)
            is TradeEligibility.INITIAL_CLEAR_NO_ENTRY
        )
        if len(candidates) != 1:
            violations.append("INITIAL_CLEAR_COUNT_INVALID")
        else:
            initial_clear = candidates[0]
            if (
                initial_clear.kind is not ActionKind.CLEAR
                or initial_clear.related_build_id is not None
                or initial_clear.sequence != 0
            ):
                violations.append("INITIAL_CLEAR_FIELDS_INVALID")
            if any(
                action.kind is ActionKind.BUILD
                and action.physical_contract == initial_clear.physical_contract
                and action.segment_id == initial_clear.segment_id
                for action in actions
            ):
                violations.append("TARGET_OWNER_BUILD_PRESENT")
        if "INITIAL_CLEAR_NO_ENTRY" not in tuple(
            getattr(chart.value, "diagnostics", ())
        ):
            violations.append("CHART_INITIAL_CLEAR_DIAGNOSTIC_MISSING")

    if reference.value is not None:
        projection = getattr(reference.value, "projection", None)
        trades = tuple(getattr(projection, "trades", ()))
        diagnostics = tuple(getattr(projection, "diagnostics", ()))
        if "INITIAL_CLEAR_NO_ENTRY" not in diagnostics:
            violations.append("REFERENCE_INITIAL_CLEAR_DIAGNOSTIC_MISSING")
        if initial_clear is not None and any(
            getattr(trade, "entry_signal_id", None) == initial_clear.signal_id
            or getattr(trade, "exit_signal_id", None) == initial_clear.signal_id
            for trade in trades
        ):
            violations.append("INITIAL_CLEAR_REFERENCED_BY_TRADE")
        items = tuple(getattr(reference.value, "items", ()))
        if initial_clear is not None and any(
            getattr(trade, "entry_signal_id", None) == initial_clear.signal_id
            or getattr(trade, "exit_signal_id", None) == initial_clear.signal_id
            for trade in items
        ):
            violations.append("INITIAL_CLEAR_PRESENT_IN_REFERENCE_ITEMS")

    unique_violations = sorted(set(violations))
    result: dict[str, object] = {
        "schema_version": "newow_weekly_pt_acceptance_v1",
        "accepted": not unique_violations,
        "as_of": expected.isoformat(),
        "violations": unique_violations,
        "reference_trade_count": len(trades),
    }
    if initial_clear is not None:
        result["initial_clear"] = {
            "signal_id": initial_clear.signal_id,
            "physical_contract": initial_clear.physical_contract,
            "segment_id": initial_clear.segment_id,
            "bar_end": initial_clear.bar_end.isoformat(),
            "sequence": initial_clear.sequence,
            "related_build_id": initial_clear.related_build_id,
            "trade_eligibility": initial_clear.trade_eligibility.value,
        }
    if not unique_violations:
        result["chart_result"] = _json_value(chart_result)
        result["reference_result"] = _json_value(reference_result)
    return result


def _case_key(case: object) -> tuple[object, object, object]:
    if not isinstance(case, dict):
        return (None, None, None)
    return (case.get("symbol"), case.get("strategy"), case.get("frequency"))


def _pending_row(
    source: str, row: object, *, identity: object = None
) -> dict[str, object] | None:
    if not isinstance(row, dict) or row.get("status") not in _PENDING:
        return None
    return {
        "source": source,
        "identity": identity,
        "status": row.get("status"),
        "reason": row.get("reason"),
    }


def _error_status_violation(row: object) -> bool:
    if not isinstance(row, dict) or not isinstance(row.get("error"), dict):
        return False
    diagnostic = row["error"].get("diagnostic")
    reason = diagnostic.get("reason") if isinstance(diagnostic, dict) else None
    if reason != row.get("reason"):
        return True
    from app.market_data.diagnostics import INTEGRITY_REASONS, MISSING_REASONS

    metadata = MISSING_REASONS - {
        "REPLAY_PREFIX_MISSING",
        "REPLAY_ENDPOINTS_MISSING",
        "DATASET_OR_PARTITION_MISSING",
        "COMPLETE_PERIOD_MISSING",
    }
    expected = (
        "UNKNOWN"
        if reason in metadata
        else "DATA_UNAVAILABLE"
        if reason in MISSING_REASONS
        else "INTEGRITY_ERROR"
        if reason in INTEGRITY_REASONS
        else "SOURCE_EXCEPTION"
        if reason == "SOURCE_NONPOSITIVE_PRICE"
        else "UNKNOWN"
    )
    return row.get("status") != expected


def summarize_readiness(
    report: object,
    expected_products: tuple[str, ...] | list[str],
    expected_as_of: datetime | str,
) -> dict[str, object]:
    """Validate a full native report and derive readiness counts offline."""

    violations: list[str] = []
    try:
        expected = _instant(expected_as_of)
    except ValueError:
        expected = FROZEN_AS_OF
        violations.append("EXPECTED_AS_OF_INVALID")
    products = tuple(expected_products) if not isinstance(expected_products, str) else ()
    if (
        len(products) != 60
        or len(set(products)) != 60
        or any(re.fullmatch(r"[a-z]{1,8}", item or "") is None for item in products)
    ):
        violations.append("EXPECTED_SCOPE_INVALID")
    expected_keys = {
        (product, strategy, ProductFrequency.WEEKLY.value)
        for product in products
        for strategy in _STRATEGIES
    }

    if not isinstance(report, dict):
        return {
            "schema_version": "newow_weekly_readiness_summary_v1",
            "valid": False,
            "violations": sorted(set((*violations, "REPORT_SCHEMA_INVALID"))),
        }
    required_lists = (
        "enumerations",
        "dependencies",
        "repair_targets",
        "metadata_proposals",
        "cases",
    )
    if report.get("schema_version") != 1:
        violations.append("REPORT_SCHEMA_INVALID")
    if report.get("command") != "data.newow-readiness":
        violations.append("REPORT_COMMAND_INVALID")
    if report.get("readonly") is not True:
        violations.append("REPORT_NOT_READONLY")
    if report.get("release_stage") != "weekly":
        violations.append("RELEASE_STAGE_MISMATCH")
    if report.get("matrix") is not True:
        violations.append("MATRIX_REQUIRED")
    if report.get("frequency_scope") != [ProductFrequency.WEEKLY.value]:
        violations.append("FREQUENCY_SCOPE_MISMATCH")
    if report.get("as_of") != expected.isoformat():
        violations.append("AS_OF_MISMATCH")
    if report.get("product_count") != 60:
        violations.append("PRODUCT_COUNT_MISMATCH")
    if report.get("main_case_count") != 180:
        violations.append("MAIN_CASE_COUNT_MISMATCH")
    if type(report.get("provider_requests")) is not int or report.get("provider_requests") != 0:
        violations.append("PROVIDER_REQUESTS_NOT_ZERO")
    if type(report.get("writes")) is not int or report.get("writes") != 0:
        violations.append("WRITES_NOT_ZERO")
    for name in required_lists:
        if not isinstance(report.get(name), list):
            violations.append(f"{name.upper()}_INVALID")

    cases = report.get("cases") if isinstance(report.get("cases"), list) else []
    case_keys = [_case_key(case) for case in cases]
    if len(case_keys) != 180 or len(set(case_keys)) != 180 or set(case_keys) != expected_keys:
        violations.append("CASE_KEYS_INVALID")

    main_ready = 0
    reference_ready = 0
    joint_ready = 0
    non_joint_ready: list[dict[str, object]] = []
    pending: list[dict[str, object]] = []
    reason_counts: Counter[str] = Counter()
    for case in cases:
        if not isinstance(case, dict):
            violations.append("CASE_SCHEMA_INVALID")
            continue
        key = _case_key(case)
        main = case.get("main")
        sections = case.get("sections")
        if not isinstance(main, dict) or not isinstance(sections, dict):
            violations.append("CASE_SCHEMA_INVALID")
            continue
        if set(sections) != _CASE_SECTIONS:
            violations.append("CASE_SECTIONS_INVALID")
        chart = sections.get("chart")
        reference = sections.get("reference")
        if main != chart:
            violations.append("MAIN_CHART_MISMATCH")
        chart_status = chart.get("status") if isinstance(chart, dict) else None
        reference_status = reference.get("status") if isinstance(reference, dict) else None
        if chart_status == "READY":
            main_ready += 1
        if reference_status == "READY":
            reference_ready += 1
        if chart_status == reference_status == "READY":
            joint_ready += 1
        else:
            non_joint_ready.append(
                {
                    "symbol": key[0],
                    "strategy": key[1],
                    "frequency": key[2],
                    "chart_status": chart_status,
                    "chart_reason": chart.get("reason") if isinstance(chart, dict) else None,
                    "reference_status": reference_status,
                    "reference_reason": reference.get("reason") if isinstance(reference, dict) else None,
                }
            )
        for section_name, state in sections.items():
            if isinstance(state, dict):
                reason_counts[
                    f"{section_name}:{state.get('status', 'MISSING')}:{state.get('reason') or '-'}"
                ] += 1
            item = _pending_row("case_section", state, identity=(*key, section_name))
            if item is not None:
                pending.append(item)
            if _error_status_violation(state):
                violations.append("ERROR_STATUS_MISMATCH")

    if type(report.get("main_ready_count")) is not int or report.get("main_ready_count") != main_ready:
        violations.append("MAIN_READY_COUNT_MISMATCH")

    enumerations = report.get("enumerations") if isinstance(report.get("enumerations"), list) else []
    enumeration_keys = []
    for row in enumerations:
        if isinstance(row, dict):
            enumeration_keys.append((row.get("symbol"), row.get("frequency"), row.get("section")))
            if row.get("frequency") != "1w" or row.get("as_of") != expected.isoformat():
                violations.append("ENUMERATION_IDENTITY_INVALID")
        item = _pending_row("enumeration", row, identity=enumeration_keys[-1] if enumeration_keys else None)
        if item is not None:
            pending.append(item)
        if _error_status_violation(row):
            violations.append("ERROR_STATUS_MISMATCH")
    expected_enumerations = {
        (product, "1w", section)
        for product in products
        for section in _ENUMERATION_SECTIONS
    }
    if (
        len(enumeration_keys) != len(expected_enumerations)
        or len(set(enumeration_keys)) != len(expected_enumerations)
        or set(enumeration_keys) != expected_enumerations
    ):
        violations.append("ENUMERATION_KEYS_INVALID")

    for source, rows in (
        ("dependency", report.get("dependencies", [])),
        ("repair", report.get("repair_targets", [])),
        ("metadata", report.get("metadata_proposals", [])),
    ):
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            item = _pending_row(source, row, identity=index)
            if item is not None:
                pending.append(item)
            if _error_status_violation(row):
                violations.append("ERROR_STATUS_MISMATCH")

    exhausted = report.get("budget_exhausted")
    if type(exhausted) is not bool:
        violations.append("BUDGET_FLAG_INVALID")
        exhausted = True
    recomputed_complete = not pending and not exhausted
    if type(report.get("complete")) is not bool or report.get("complete") != recomputed_complete:
        violations.append("COMPLETE_FLAG_MISMATCH")
    expected_status = "audited" if recomputed_complete else "incomplete"
    if report.get("status") != expected_status:
        violations.append("STATUS_MISMATCH")

    unique_violations = sorted(set(violations))
    return {
        "schema_version": "newow_weekly_readiness_summary_v1",
        "valid": not unique_violations,
        "violations": unique_violations,
        "as_of": expected.isoformat(),
        "audit_complete": recomputed_complete,
        "scope_covered": set(case_keys) == expected_keys,
        "matrix_covered": len(case_keys) == 180 and len(set(case_keys)) == 180 and set(case_keys) == expected_keys,
        "counts": {
            "total": len(cases),
            "main_ready": main_ready,
            "reference_ready": reference_ready,
            "joint_ready": joint_ready,
        },
        "pending": pending,
        "non_joint_ready_cases": non_joint_ready,
        "section_outcome_counts": dict(sorted(reason_counts.items())),
        "repair_targets": _json_value(report.get("repair_targets", [])),
        "metadata_proposals": _json_value(report.get("metadata_proposals", [])),
        "provider_requests": report.get("provider_requests"),
        "writes": report.get("writes"),
    }


def _build_pt_service(session: object, as_of: datetime):
    from app.market_data.composition import (
        build_database_coverage_source,
        build_market_data_service,
    )
    from app.market_data.newow.product_reader import NewowProductReader
    from app.market_data.newow.product_service import NewowProductService
    from app.market_data.operational_universe import load_active_products

    market_data = build_market_data_service(session)
    coverage = build_database_coverage_source(session)
    active = load_active_products()

    def reader_factory(context, cancelled):
        return NewowProductReader(
            market_data,
            coverage=coverage,
            active_products=active,
            context_frequencies=context,
            now=lambda: as_of,
            cancelled=cancelled,
        )

    return NewowProductService(reader_factory, now=lambda: as_of)


def run_pt_probe(
    *,
    session_factory: Callable[[], object] | None = None,
    service_factory: Callable[[object, datetime], object] | None = None,
) -> dict[str, object]:
    """Run exactly one chart/reference pair inside one read-only transaction."""

    from app.db.readonly import readonly_transaction
    from app.market_data.newow.product_service import ProductServiceQuery

    if session_factory is None:
        from app.db.session import SessionLocal

        session_factory = SessionLocal
    builder = service_factory or _build_pt_service
    with session_factory() as session, readonly_transaction(session, timeout_seconds=300):
        service = builder(session, FROZEN_AS_OF)
        chart = service.query(
            ProductServiceQuery(
                _PT_PRODUCT,
                ProductStrategy.MAIN_RISE,
                ProductFrequency.WEEKLY,
                as_of=FROZEN_AS_OF,
            )
        )
        reference = service.query(
            ProductServiceQuery(
                _PT_PRODUCT,
                ProductStrategy.MAIN_RISE,
                ProductFrequency.WEEKLY,
                section="reference",
                as_of=FROZEN_AS_OF,
                snapshot_token=chart.meta.snapshot_token,
            )
        )
        return validate_pt_initial_clear(chart, reference)


def _read_bytes(path: str, maximum: int) -> bytes:
    try:
        target = Path(path)
        with target.open("rb") as source:
            content = source.read(maximum + 1)
        if len(content) > maximum:
            raise ValueError
        return content
    except (OSError, ValueError):
        raise ValueError("INPUT_FILE_INVALID") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="mode", required=True)
    commands.add_parser("pt", allow_abbrev=False)
    summary = commands.add_parser("summary", allow_abbrev=False)
    summary.add_argument("--report", required=True)
    summary.add_argument("--scope", required=True)
    summary.add_argument("--expected-as-of", required=True)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    session_factory: Callable[[], object] | None = None,
    service_factory: Callable[[object, datetime], object] | None = None,
) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.mode == "pt":
            payload = run_pt_probe(
                session_factory=session_factory,
                service_factory=service_factory,
            )
            code = 0 if payload["accepted"] is True else 1
        else:
            report_bytes = _read_bytes(args.report, 256 * 1024 * 1024)
            scope_bytes = _read_bytes(args.scope, 1024 * 1024)
            report = json.loads(report_bytes)
            products = tuple(
                line.strip()
                for line in scope_bytes.decode("utf-8").splitlines()
                if line.strip()
            )
            payload = summarize_readiness(report, products, args.expected_as_of)
            normalized = json.dumps(
                sorted(products), ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            payload["report_sha256"] = hashlib.sha256(report_bytes).hexdigest()
            payload["scope_file_sha256"] = hashlib.sha256(scope_bytes).hexdigest()
            payload["normalized_scope_sha256"] = hashlib.sha256(normalized).hexdigest()
            code = 0 if payload["valid"] is True else 1
    except (ValueError, UnicodeError, json.JSONDecodeError):
        payload = {
            "schema_version": "newow_weekly_acceptance_error_v1",
            "accepted": False,
            "violations": ["INPUT_INVALID"],
        }
        code = 1
    except Exception:
        payload = {
            "schema_version": "newow_weekly_acceptance_error_v1",
            "accepted": False,
            "violations": ["PT_PROBE_FAILED"],
        }
        code = 1
    stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    stdout.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
