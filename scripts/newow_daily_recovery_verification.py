"""Independent read-only settlement for one frozen Newow D1 recovery attempt."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping, cast

from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy

from app.market_data.newow.readiness import ReadinessRequest
from app.market_data.operational_universe import load_operational_products
from scripts import newow_weekly_recovery as native
from scripts import newow_weekly_recovery_campaign as campaign_module


_SCHEMA = "newow_daily_recovery_verification_v1"
_HASH = re.compile(r"[0-9a-f]{64}")
_COUNT_FIELDS = {
    "success": "success_unit_count",
    "isolated": "isolated_unit_count",
    "failed": "stopping_failure_unit_count",
    "unattempted": "unattempted_unit_count",
    "unknown": "unknown_unit_count",
}


def _write_atomic_exclusive(path: Path, content: bytes) -> None:
    """Fully sync bytes before atomically publishing one new result path."""
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        try:
            view = memoryview(content)
            offset = 0
            while offset < len(view):
                written = os.write(fd, view[offset:])
                if written <= 0:
                    raise OSError
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
        os.link(temporary, path, follow_symlinks=False)
        temporary.unlink()
        native._fsync_directory(path.parent)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _campaign_digest(campaign: Mapping[str, Any]) -> str:
    body = dict(campaign)
    body.pop("campaign_sha256", None)
    return hashlib.sha256(native._canonical_json(body).encode("utf-8")).hexdigest()


def _frozen_daily_units(campaign: Mapping[str, Any]) -> list[dict[str, Any]]:
    children = campaign.get("children")
    if not isinstance(children, list):
        raise native.RecoveryError("VERIFICATION_INPUT_INVALID")
    units: list[dict[str, Any]] = []
    for child in children:
        if not isinstance(child, Mapping) or not isinstance(child.get("units"), list):
            raise native.RecoveryError("VERIFICATION_INPUT_INVALID")
        for raw in child["units"]:
            if not isinstance(raw, Mapping):
                raise native.RecoveryError("VERIFICATION_INPUT_INVALID")
            unit = dict(raw)
            if (
                unit.get("frequency") != "1d"
                or not isinstance(unit.get("symbol"), str)
                or not isinstance(unit.get("contract"), str)
                or not isinstance(unit.get("through"), str)
                or _HASH.fullmatch(str(unit.get("plan_sha256", ""))) is None
            ):
                raise native.RecoveryError("VERIFICATION_INPUT_INVALID")
            units.append(unit)
    return units


def _validated_execution(
    campaign: Mapping[str, Any], execution: Mapping[str, Any]
) -> tuple[dict[str, int], bool, list[tuple[str, dict[str, Any]]]]:
    if not isinstance(execution, Mapping):
        raise native.RecoveryError("VERIFICATION_INPUT_INVALID")
    expected_digest = campaign.get("campaign_sha256") or _campaign_digest(campaign)
    if (
        _HASH.fullmatch(str(expected_digest)) is None
        or execution.get("campaign_manifest_sha256") != expected_digest
    ):
        raise native.RecoveryError("VERIFICATION_IDENTITY_CHANGED")
    summary = execution.get("summary")
    scope = campaign.get("scope")
    if not isinstance(summary, Mapping) or not isinstance(scope, Mapping):
        raise native.RecoveryError("VERIFICATION_INPUT_INVALID")
    denominator = summary.get("denominator_unit_count")
    if (
        type(denominator) is not int
        or denominator < 0
        or denominator != scope.get("denominator_unit_count")
        or summary.get("partial_source_exception_unit_count", 0) != 0
    ):
        raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
    counts: dict[str, int] = {}
    for name, field in _COUNT_FIELDS.items():
        value = summary.get(field)
        if type(value) is not int or value < 0:
            raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
        counts[name] = value
    if sum(counts.values()) != denominator:
        raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
    children = campaign.get("children")
    if not isinstance(children, list):
        raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
    frozen_units = _frozen_daily_units(campaign)
    frozen_by_identity = {_unit_identity(unit): unit for unit in frozen_units}
    batch_units: dict[str, set[tuple[str, str, str, str, str]]] = {}
    batch_unit_order: dict[str, list[tuple[str, str, str, str, str]]] = {}
    for child in children:
        if not isinstance(child, Mapping) or not isinstance(child.get("units"), list):
            raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
        batch_id = child.get("batch_id")
        if not isinstance(batch_id, str) or batch_id in batch_units:
            raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
        ordered_keys = [
            _unit_identity(unit)
            for unit in child["units"]
            if isinstance(unit, Mapping)
        ]
        batch_unit_order[batch_id] = ordered_keys
        batch_units[batch_id] = set(ordered_keys)
        if len(batch_units[batch_id]) != len(child["units"]):
            raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
    anomaly_by_identity: dict[
        tuple[str, str, str, str, str], dict[str, Any]
    ] = {}
    for field in ("prior_known_isolations", "source_only_known_isolations"):
        bindings = campaign.get(field, [])
        if not isinstance(bindings, list):
            raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
        for binding in bindings:
            unit = binding.get("unit") if isinstance(binding, Mapping) else None
            if not isinstance(unit, Mapping):
                raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
            key = _unit_identity(unit)
            if key in frozen_by_identity or key in anomaly_by_identity:
                raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
            anomaly_by_identity[key] = dict(unit)
    universe = set(frozen_by_identity) | set(anomaly_by_identity)
    if len(frozen_by_identity) != len(frozen_units) or len(universe) != denominator:
        raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
    completed_batches = execution.get("completed_batches")
    completed_batch_ids = execution.get("completed_batch_ids")
    unattempted_batch_ids = execution.get("unattempted_batch_ids")
    if (
        not isinstance(completed_batches, list)
        or not isinstance(completed_batch_ids, list)
        or not isinstance(unattempted_batch_ids, list)
        or execution.get("partial_source_exception_units") != []
    ):
        raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
    classified: dict[str, set[tuple[str, str, str, str, str]]] = {
        name: set() for name in _COUNT_FIELDS
    }
    processed: list[tuple[str, dict[str, Any]]] = []
    seen_batches: set[str] = set()

    def add_unit(category: str, raw: object) -> None:
        if not isinstance(raw, Mapping):
            raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
        key = _unit_identity(raw)
        if key not in universe or any(key in values for values in classified.values()):
            raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
        classified[category].add(key)
        if category in {"success", "isolated", "failed", "unknown"}:
            processed.append(
                (category, (frozen_by_identity | anomaly_by_identity)[key])
            )

    def classify_terminal(entry: object, *, stopping: str | None) -> None:
        if not isinstance(entry, Mapping):
            raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
        batch_id = entry.get("batch_id")
        if (
            not isinstance(batch_id, str)
            or batch_id not in batch_units
            or batch_id in seen_batches
        ):
            raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
        seen_batches.add(batch_id)
        terminal = entry.get("native_result")
        nested = terminal.get("result") if isinstance(terminal, Mapping) else None
        if not isinstance(nested, Mapping):
            category = "unknown" if stopping == "unknown" else "unattempted"
            for key in batch_unit_order[batch_id]:
                if any(key in values for values in classified.values()):
                    raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
                classified[category].add(key)
                if category == "unknown":
                    processed.append((category, frozen_by_identity[key]))
            return
        completed = nested.get("completed")
        isolated = nested.get("isolated", [])
        unattempted = nested.get("unattempted")
        if (
            not isinstance(completed, list)
            or not isinstance(isolated, list)
            or not isinstance(unattempted, list)
        ):
            raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
        for raw in completed:
            add_unit("success", raw)
        for raw in isolated:
            add_unit("isolated", raw)
        failed = nested.get("failed")
        if failed is not None:
            if stopping not in {"failed", "unknown"}:
                raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
            add_unit(stopping, failed)
        for raw in unattempted:
            add_unit("unattempted", raw)

    for entry in completed_batches:
        classify_terminal(entry, stopping=None)
    if completed_batch_ids != [entry.get("batch_id") for entry in completed_batches]:
        raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
    failed_batch = execution.get("failed_batch")
    if failed_batch is not None:
        classify_terminal(failed_batch, stopping="failed")
    unknown_batch = execution.get("unknown_batch")
    if unknown_batch is not None:
        classify_terminal(unknown_batch, stopping="unknown")
    for batch_id in unattempted_batch_ids:
        if (
            not isinstance(batch_id, str)
            or batch_id not in batch_units
            or batch_id in seen_batches
        ):
            raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
        seen_batches.add(batch_id)
        for key in batch_unit_order[batch_id]:
            if any(key in values for values in classified.values()):
                raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
            classified["unattempted"].add(key)
    top_isolated = execution.get("isolated_units")
    if not isinstance(top_isolated, list):
        raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
    top_isolated_keys = {
        _unit_identity(item)
        for item in top_isolated
        if isinstance(item, Mapping)
    }
    if (
        len(top_isolated_keys) != len(top_isolated)
        or top_isolated_keys != classified["isolated"] | set(anomaly_by_identity)
    ):
        raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
    for key, unit in anomaly_by_identity.items():
        if any(key in values for values in classified.values()):
            raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
        classified["isolated"].add(key)
        processed.append(("isolated", unit))
    if (
        any(len(classified[name]) != counts[name] for name in _COUNT_FIELDS)
        or set().union(*classified.values()) != universe
    ):
        raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
    status = execution.get("status")
    complete = (
        status == "passed"
        and counts["success"] == denominator
        and not any(counts[name] for name in counts if name != "success")
    ) or (status == "not_required" and denominator == 0)
    return counts, complete, processed


def _not_required_execution(
    campaign: Mapping[str, Any], campaign_sha256: str
) -> dict[str, Any]:
    scope = campaign.get("scope")
    if (
        campaign.get("status") != "completed"
        or campaign.get("children") != []
        or not isinstance(scope, Mapping)
        or scope.get("denominator_unit_count") != 0
    ):
        raise native.RecoveryError("VERIFICATION_EXECUTION_REQUIRED")
    return {
        "status": "not_required",
        "campaign_manifest_sha256": campaign_sha256,
        "summary": {
            "denominator_unit_count": 0,
            "success_unit_count": 0,
            "isolated_unit_count": 0,
            "partial_source_exception_unit_count": 0,
            "stopping_failure_unit_count": 0,
            "unattempted_unit_count": 0,
            "unknown_unit_count": 0,
        },
        "completed_batches": [],
        "completed_batch_ids": [],
        "failed_batch": None,
        "unknown_batch": None,
        "unattempted_batch_ids": [],
        "isolated_units": [],
        "partial_source_exception_units": [],
    }


def _unit_identity(value: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    fields = tuple(
        value.get(key)
        for key in ("symbol", "contract", "frequency", "through", "plan_sha256")
    )
    if not all(isinstance(field, str) for field in fields):
        raise native.RecoveryError("VERIFICATION_SETTLEMENT_INVALID")
    return cast(tuple[str, str, str, str, str], fields)


def _validate_replan(
    category: str,
    unit: Mapping[str, Any],
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise native.RecoveryError("FINAL_REPLAN_INVALID")
    targets = value.get("targets")
    remaining = value.get("remaining_target_count")
    status = value.get("status")
    if (
        value.get("symbol") != unit["symbol"]
        or value.get("contract") != unit["contract"]
        or value.get("frequency") != "1d"
        or value.get("requested_through") != unit["through"]
        or _HASH.fullmatch(str(value.get("plan_sha256", ""))) is None
        or not isinstance(targets, list)
        or type(remaining) is not int
        or remaining != len(targets)
        or status not in {"passed", "remaining"}
    ):
        raise native.RecoveryError("FINAL_REPLAN_INVALID")
    if category == "success":
        valid_outcome = status == "passed" and targets == [] and remaining == 0
    elif category == "isolated":
        frozen_targets = unit.get("targets")
        valid_outcome = (
            status == "remaining"
            and remaining > 0
            and value.get("plan_sha256") == unit.get("plan_sha256")
            and (
                not isinstance(frozen_targets, list)
                or targets == frozen_targets
            )
        )
    elif category in {"failed", "unknown"}:
        valid_outcome = (status == "passed") == (remaining == 0)
    else:
        valid_outcome = False
    if not valid_outcome:
        raise native.RecoveryError("FINAL_REPLAN_INVALID")
    return {**dict(value), "execution_category": category}


def _availability_status(status: object, reason: object) -> str:
    if status == "DATA_READY":
        return "available"
    if status == "SOURCE_EXCEPTION":
        return "source_exception"
    if status == "INTEGRITY_ERROR":
        return "integrity_error"
    if status in {"UNKNOWN", "UNSTARTED"}:
        return "review_required"
    if reason in {
        "REPLAY_PREFIX_MISSING",
        "REPLAY_ENDPOINTS_MISSING",
        "DATASET_OR_PARTITION_MISSING",
    }:
        return "missing"
    return "unavailable"


def _input_availability(audit: Mapping[str, Any]) -> list[dict[str, Any]]:
    dependencies = audit.get("dependencies")
    if not isinstance(dependencies, list):
        return []
    combined: dict[tuple[str, str, str], dict[str, Any]] = {}
    precedence = {
        "available": 0,
        "missing": 1,
        "source_exception": 2,
        "integrity_error": 3,
        "unavailable": 4,
        "review_required": 5,
    }
    for dependency in dependencies:
        if not isinstance(dependency, Mapping) or dependency.get("frequency") != "1d":
            continue
        consumers = dependency.get("consumers")
        if not isinstance(consumers, list):
            continue
        status = _availability_status(
            dependency.get("status"), dependency.get("reason")
        )
        for consumer in consumers:
            if not isinstance(consumer, Mapping):
                continue
            key = (
                str(dependency.get("symbol")),
                str(consumer.get("strategy")),
                str(consumer.get("section")),
            )
            row = {
                "symbol": key[0],
                "strategy": key[1],
                "consumer": key[2],
                "frequency": "1d",
                "status": status,
                "reason": dependency.get("reason"),
                "contracts": [dependency.get("contract")],
            }
            previous = combined.get(key)
            if previous is None:
                combined[key] = row
            else:
                previous["contracts"].append(dependency.get("contract"))
                if precedence[status] > precedence[previous["status"]]:
                    previous["status"] = status
                    previous["reason"] = dependency.get("reason")
    return [combined[key] for key in sorted(combined)]


def _provider_request_count(execution: Mapping[str, Any]) -> int:
    total = 0
    batches = execution.get("completed_batches", [])
    if isinstance(batches, list):
        for batch in batches:
            nested = (
                batch.get("native_result", {}).get("result", {})
                if isinstance(batch, Mapping)
                else {}
            )
            completed = (
                nested.get("completed", []) if isinstance(nested, Mapping) else []
            )
            if isinstance(completed, list):
                for unit in completed:
                    result = unit.get("result", {}) if isinstance(unit, Mapping) else {}
                    value = (
                        result.get("provider_requests")
                        if isinstance(result, Mapping)
                        else None
                    )
                    if type(value) is int and value >= 0:
                        total += value
    failed_batch = execution.get("failed_batch")
    if isinstance(failed_batch, Mapping):
        nested = failed_batch.get("native_result", {})
        nested = nested.get("result", {}) if isinstance(nested, Mapping) else {}
        failed = nested.get("failed") if isinstance(nested, Mapping) else None
        result = failed.get("result", {}) if isinstance(failed, Mapping) else {}
        value = result.get("provider_requests") if isinstance(result, Mapping) else None
        if type(value) is int and value >= 0:
            total += value
    return total


def _metrics(
    *,
    campaign: Mapping[str, Any],
    execution: Mapping[str, Any],
    audit: Mapping[str, Any],
    units: list[dict[str, Any]],
) -> dict[str, int]:
    dependencies = audit.get("dependencies", [])
    repairs = audit.get("repair_targets", [])
    missing = 0
    if isinstance(repairs, list):
        for repair in repairs:
            windows = (
                repair.get("target_windows", []) if isinstance(repair, Mapping) else []
            )
            if isinstance(windows, list):
                for window in windows:
                    value = (
                        window.get("missing_bar_count")
                        if isinstance(window, Mapping)
                        else None
                    )
                    if type(value) is int and value >= 0:
                        missing += value
    scope = campaign.get("scope", {})
    denominator = (
        scope.get("denominator_unit_count", len(units))
        if isinstance(scope, Mapping)
        else len(units)
    )
    return {
        "dependency_count": len(dependencies) if isinstance(dependencies, list) else 0,
        "execution_unit_count": denominator if type(denominator) is int else len(units),
        "partition_count": sum(
            unit.get("target_count", 0)
            for unit in units
            if type(unit.get("target_count")) is int
        ),
        "missing_endpoint_count": missing,
        "provider_request_count": _provider_request_count(execution),
    }


def _runtime_default_comparator_evidence(
    *,
    service: Any,
    observations: list[tuple[Any, datetime, Any]],
    products: tuple[str, ...],
    as_of: datetime,
    dependency_proof: Callable[[Any], Mapping[str, str]],
) -> dict[str, Any]:
    from app.market_data.newow.product_service import (
        ProductSection,
        ProductServiceQuery,
    )

    rows: list[dict[str, Any]] = []
    for product in products:
        start = len(observations)
        chart = service.query(
            ProductServiceQuery(
                product,
                ProductStrategy.OSCILLATION,
                ProductFrequency.DAILY,
                section=ProductSection.CHART,
                as_of=as_of,
            )
        )
        if chart.meta.snapshot_token is None:
            raise native.RecoveryError("COMPARATOR_PROOF_INVALID")
        comparator = service.query(
            ProductServiceQuery(
                product,
                ProductStrategy.OSCILLATION,
                ProductFrequency.DAILY,
                section=ProductSection.COMPARATOR,
                as_of=as_of,
                snapshot_token=chart.meta.snapshot_token,
            )
        )
        pair = observations[start:]
        if len(pair) != 2:
            raise native.RecoveryError("COMPARATOR_PROOF_INVALID")
        chart_query, chart_as_of, chart_read = pair[0]
        comparator_query, comparator_as_of, comparator_read = pair[1]
        same_window = (
            chart_query.frequency == comparator_query.frequency
            and chart_query.since == comparator_query.since
            and chart_query.through == comparator_query.through
            and chart_query.performance_since == comparator_query.performance_since
            and chart_query.performance_through == comparator_query.performance_through
        )
        same_as_of = (
            chart_as_of == comparator_as_of == as_of
            and chart.meta.as_of == comparator.meta.as_of == as_of
        )
        same_owner_prefix = (
            chart_read.owners == comparator_read.owners
            and chart_read.replay_bars == comparator_read.replay_bars
            and dependency_proof(chart_read) == dependency_proof(comparator_read)
            and chart.meta.input_content_sha256
            == comparator.meta.input_content_sha256
        )
        token_bound = comparator.meta.snapshot_token == chart.meta.snapshot_token
        if not all((same_window, same_as_of, same_owner_prefix, token_bound)):
            raise native.RecoveryError("COMPARATOR_PROOF_INVALID")
        rows.append(
            {
                "product": product,
                "since": chart_query.since.isoformat(),
                "through": chart_query.through.isoformat(),
                "input_content_sha256": chart.meta.input_content_sha256,
            }
        )
    return {
        "status": "verified",
        "frequency": "1d",
        "strategy": "oscillation",
        "as_of": as_of.isoformat(),
        "product_count": len(products),
        "verified_product_count": len(rows),
        "product_universe_sha256": campaign_module._identity_sha256(list(products)),
        "same_query_window": True,
        "same_as_of": True,
        "same_owner_prefix": True,
        "snapshot_token_bound": True,
        "product_evidence": rows,
    }


def _validated_comparator_evidence(
    audit: Mapping[str, Any],
    *,
    products: tuple[str, ...],
    as_of: datetime,
) -> dict[str, Any]:
    evidence = audit.get("_comparator_evidence")
    expected_universe_sha = campaign_module._identity_sha256(list(products))
    if (
        not isinstance(evidence, Mapping)
        or evidence.get("status") != "verified"
        or evidence.get("frequency") != "1d"
        or evidence.get("strategy") != "oscillation"
        or evidence.get("as_of") != as_of.isoformat()
        or evidence.get("product_count") != len(products)
        or evidence.get("verified_product_count") != len(products)
        or evidence.get("product_universe_sha256") != expected_universe_sha
        or evidence.get("same_query_window") is not True
        or evidence.get("same_as_of") is not True
        or evidence.get("same_owner_prefix") is not True
        or evidence.get("snapshot_token_bound") is not True
    ):
        return {
            "status": "not_verified",
            "frequency": "1d",
            "strategy": "oscillation",
            "as_of": as_of.isoformat(),
            "product_count": len(products),
            "product_universe_sha256": expected_universe_sha,
        }
    return dict(evidence)


def verify_daily_campaign(
    *,
    campaign: Mapping[str, Any],
    execution: Mapping[str, Any],
    run_audit: Callable[[ReadinessRequest], Mapping[str, Any]],
    replan_unit: Callable[[Mapping[str, Any]], Mapping[str, Any]],
) -> dict[str, Any]:
    """Combine verified execution facts with one independent D1 audit."""
    if campaign.get("schema_version") != "newow_daily_recovery_campaign_v1":
        raise native.RecoveryError("VERIFICATION_INPUT_INVALID")
    audit_identity = campaign.get("audit")
    identity = campaign.get("execution_identity")
    if not isinstance(audit_identity, Mapping) or not isinstance(identity, Mapping):
        raise native.RecoveryError("VERIFICATION_INPUT_INVALID")
    try:
        as_of = datetime.fromisoformat(str(audit_identity["as_of"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise native.RecoveryError("VERIFICATION_INPUT_INVALID") from exc
    if as_of.tzinfo is None or audit_identity.get("frequency_scope") != ["1d"]:
        raise native.RecoveryError("VERIFICATION_INPUT_INVALID")
    units = _frozen_daily_units(campaign)
    counts, ordinary_complete, processed_units = _validated_execution(
        campaign, execution
    )
    replans: list[dict[str, Any]] = []
    replan_error: str | None = None
    if processed_units:
        try:
            replans = [
                _validate_replan(category, unit, replan_unit(unit))
                for category, unit in processed_units
            ]
        except Exception:  # noqa: BLE001 - keep private infrastructure text out
            replan_error = "FINAL_REPLAN_FAILED"

    products = tuple(load_operational_products())
    scope = campaign.get("scope")
    if (
        not isinstance(scope, Mapping)
        or scope.get("product_count") != len(products)
        or scope.get("product_universe_sha256")
        != campaign_module._identity_sha256(list(products))
    ):
        raise native.RecoveryError("VERIFICATION_IDENTITY_CHANGED")
    request = ReadinessRequest(
        products=products,
        as_of=as_of,
        matrix=False,
        max_work=10000,
        timeout_seconds=campaign_module._DAILY_VERIFICATION_AUDIT_TIMEOUT_SECONDS,
        frequencies=(ProductFrequency.DAILY,),
    )
    verification_status = "incomplete"
    verification_error: str | None = None
    audit: Mapping[str, Any] = {}
    try:
        audit = run_audit(request)
        if not isinstance(audit, Mapping):
            raise ValueError
        inventory_complete = (
            audit.get("complete") is True
            and audit.get("status") == "audited"
            and audit.get("budget_exhausted") is False
            and audit.get("readonly") is True
            and audit.get("provider_requests") == 0
            and audit.get("writes") == 0
            and audit.get("as_of") == as_of.isoformat()
            and audit.get("frequency_scope") == ["1d"]
        )
        if inventory_complete:
            campaign_module._validated_report_targets(audit, recovery_frequency="1d")
        comparator_evidence = _validated_comparator_evidence(
            audit,
            products=products,
            as_of=as_of,
        )
        if inventory_complete and ordinary_complete and replan_error is None:
            availability = _input_availability(audit)
            verification_status = (
                "verified"
                if availability
                and all(row["status"] == "available" for row in availability)
                and comparator_evidence["status"] == "verified"
                else "incomplete"
            )
        else:
            availability = _input_availability(audit)
            if replan_error is not None:
                verification_status = "failed"
                verification_error = replan_error
    except Exception:  # noqa: BLE001 - output must not contain raw infrastructure text
        inventory_complete = False
        availability = []
        comparator_evidence = _validated_comparator_evidence(
            {}, products=products, as_of=as_of
        )
        verification_status = "failed"
        verification_error = "FINAL_AUDIT_FAILED"

    result: dict[str, Any] = {
        "schema_version": _SCHEMA,
        "inventory_complete": inventory_complete,
        "ordinary_recovery_complete": ordinary_complete,
        "verification_status": verification_status,
        "execution": {
            "status": execution.get("status"),
            "campaign_manifest_sha256": execution.get("campaign_manifest_sha256"),
            "counts": counts,
        },
        "input_availability": availability,
        "metrics": _metrics(
            campaign=campaign,
            execution=execution,
            audit=audit,
            units=units,
        ),
        "replans": replans,
        "comparator_evidence": comparator_evidence,
        "provenance": {
            "prepare_audit_sha256": audit_identity.get("sha256"),
            "final_audit_sha256": (
                hashlib.sha256(
                    native._canonical_json(audit).encode("utf-8")
                ).hexdigest()
                if audit
                else None
            ),
            "campaign_sha256": campaign.get("campaign_sha256")
            or _campaign_digest(campaign),
            "as_of": as_of.isoformat(),
            **dict(identity),
        },
    }
    if verification_error is not None:
        result["verification_error"] = verification_error
    return result


def render_daily_summary(result: Mapping[str, Any]) -> str:
    execution = result.get("execution", {})
    counts = execution.get("counts", {}) if isinstance(execution, Mapping) else {}
    lines = [
        "# 牛哇日线恢复独立结算",
        "",
        f"- 库存盘点完整：{str(bool(result.get('inventory_complete'))).lower()}",
        f"- 普通恢复完成：{str(bool(result.get('ordinary_recovery_complete'))).lower()}",
        f"- 验证状态：{result.get('verification_status')}",
        (
            "- 执行单元："
            f"passed={counts.get('success', 0)}, isolated={counts.get('isolated', 0)}, "
            f"failed={counts.get('failed', 0)}, unattempted={counts.get('unattempted', 0)}, "
            f"unknown={counts.get('unknown', 0)}"
        ),
        "",
        (
            "默认比较器运行核验："
            f"{result.get('comparator_evidence', {}).get('status', 'not_verified')}；"
            "自定义或历史翻页窗口不在本次 D1 恢复范围。"
        ),
    ]
    return "\n".join(lines) + "\n"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Independently verify one frozen Newow D1 recovery attempt."
    )
    value.add_argument("--project-env", required=True)
    value.add_argument("--campaign", required=True)
    value.add_argument("--expected-campaign-sha256", required=True)
    value.add_argument("--execution")
    value.add_argument("--expected-execution-sha256")
    value.add_argument("--execution-not-required", action="store_true")
    value.add_argument("--output-root", required=True)
    value.add_argument("--observation-id", required=True)
    return value


def _validate_persisted_execution_evidence(
    *,
    campaign: Mapping[str, Any],
    execution: Mapping[str, Any],
    campaign_path: Path,
    execution_path: Path,
    evidence_root: Path,
) -> None:
    """Bind the execution summary to immutable campaign and native terminals."""
    root = campaign_module._validated_evidence_root(evidence_root)
    campaign_module._direct_root_file(campaign_path, root)
    attempt = native._validated_direct_child_directory(
        execution_path.parent,
        root,
        "VERIFICATION_EVIDENCE_INVALID",
    )
    if execution_path.name != "campaign-execution.json":
        raise native.RecoveryError("VERIFICATION_EVIDENCE_INVALID")
    persisted_result = native._read_json_file(attempt / "campaign-result.json")
    expected_result = dict(execution)
    expected_result.pop("campaign_manifest_sha256", None)
    if persisted_result != expected_result:
        raise native.RecoveryError("VERIFICATION_EVIDENCE_INVALID")
    started = native._read_json_file(attempt / "campaign-started.json")
    expected_started_sha = hashlib.sha256(
        native._canonical_json(campaign).encode("utf-8")
    ).hexdigest()
    if (
        not isinstance(started, Mapping)
        or started.get("schema_version") != "newow_daily_recovery_campaign_started_v1"
        or started.get("campaign_manifest_sha256") != expected_started_sha
        or started.get("execution_identity") != campaign.get("execution_identity")
    ):
        raise native.RecoveryError("VERIFICATION_EVIDENCE_INVALID")
    children = campaign.get("children")
    identity = campaign.get("execution_identity")
    if not isinstance(children, list) or not isinstance(identity, Mapping):
        raise native.RecoveryError("VERIFICATION_EVIDENCE_INVALID")
    child_by_id = {
        child.get("batch_id"): child for child in children if isinstance(child, Mapping)
    }
    terminal_entries = execution.get("completed_batches")
    if not isinstance(terminal_entries, list):
        raise native.RecoveryError("VERIFICATION_EVIDENCE_INVALID")
    entries = list(terminal_entries)
    for field in ("failed_batch", "unknown_batch"):
        entry = execution.get(field)
        if isinstance(entry, Mapping) and isinstance(
            entry.get("native_result"), Mapping
        ):
            entries.append(entry)
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise native.RecoveryError("VERIFICATION_EVIDENCE_INVALID")
        batch_id = entry.get("batch_id")
        child = child_by_id.get(batch_id)
        terminal = entry.get("native_result")
        if (
            not isinstance(batch_id, str)
            or batch_id in seen
            or not isinstance(child, Mapping)
            or not isinstance(terminal, Mapping)
        ):
            raise native.RecoveryError("VERIFICATION_EVIDENCE_INVALID")
        seen.add(batch_id)
        batch_attempt = native._validated_direct_child_directory(
            attempt / batch_id,
            attempt,
            "VERIFICATION_EVIDENCE_INVALID",
        )
        persisted_terminal = native._read_json_file(
            batch_attempt / "batch-terminal.json"
        )
        if (
            not isinstance(persisted_terminal, Mapping)
            or persisted_terminal.get("schema_version")
            != "newow_daily_recovery_campaign_batch_v1"
            or persisted_terminal.get("batch_id") != batch_id
            or persisted_terminal.get("native_result") != terminal
        ):
            raise native.RecoveryError("VERIFICATION_EVIDENCE_INVALID")
        child_path = campaign_module._manifest_child_path(child.get("path"), root)
        validated_terminal = campaign_module._validated_batch_invocation(
            {
                "return_code": 0 if terminal.get("status") == "passed" else 1,
                "batch_result": terminal,
            },
            child=child,
            child_path=child_path,
            digest=str(child.get("sha256")),
            batch_attempt=batch_attempt,
            identity=identity,
        )
        if validated_terminal != terminal:
            raise native.RecoveryError("VERIFICATION_EVIDENCE_INVALID")


def _run_readonly_verification(
    *,
    campaign: Mapping[str, Any],
    execution: Mapping[str, Any],
    project_env: Path,
    execution_sha256: str | None,
    attempt_identity: str,
) -> dict[str, Any]:
    """Compose only Catalog, Parquet, coverage, planner and strict readers."""
    from dataclasses import asdict
    import time

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.core.env import PROJECT_ROOT
    from app.db.readonly import readonly_transaction
    from app.db.url import normalize_database_url
    from app.market_data.catalog import MarketCatalog
    from app.market_data.coverage_source import DatabaseCoverageSource
    from app.market_data.historical_data_manager import (
        ContractWarmupPlanner,
        ContractWarmupRequest,
    )
    from app.market_data.market_data_service import MarketDataService
    from app.market_data.newow.product_reader import NewowProductReader
    from app.market_data.newow.product_service import (
        NewowProductService,
        _dependency_proof,
    )
    from app.market_data.newow.readiness import AuditBudget, NewowReadinessAudit
    from app.market_data.storage import CanonicalMonthlyStore

    frozen_identity = campaign.get("execution_identity")
    audit_identity = campaign.get("audit")
    if not isinstance(frozen_identity, Mapping) or not isinstance(
        audit_identity, Mapping
    ):
        raise native.RecoveryError("VERIFICATION_INPUT_INVALID")
    expected_commit = frozen_identity.get("code_commit")
    if not isinstance(expected_commit, str):
        raise native.RecoveryError("VERIFICATION_INPUT_INVALID")
    native._require_clean_execution_checkout(expected_commit)
    settings, current_identity = native.load_private_readonly_settings(project_env)
    if (
        current_identity.get("config_sha256") != frozen_identity.get("config_sha256")
        or current_identity.get("canonical_root_sha256")
        != frozen_identity.get("canonical_root_sha256")
        or native._current_execution_code_sha256(recovery_frequency="1d")
        != frozen_identity.get("execution_code_sha256")
    ):
        raise native.RecoveryError("VERIFICATION_IDENTITY_CHANGED")
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    try:
        frozen_as_of = datetime.fromisoformat(str(audit_identity["as_of"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise native.RecoveryError("VERIFICATION_INPUT_INVALID") from exc
    if frozen_as_of.tzinfo is None:
        raise native.RecoveryError("VERIFICATION_INPUT_INVALID")
    engine = create_engine(
        normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True
    )
    session = Session(engine, autoflush=False)
    lease = None
    try:
        lock_catalog = MarketCatalog(session, root)
        lease = lock_catalog.acquire_maintenance_lock()
        if lease is None:
            raise native.RecoveryError("FINAL_AUDIT_BUSY")
        with readonly_transaction(
            session,
            timeout_seconds=campaign_module._DAILY_VERIFICATION_AUDIT_TIMEOUT_SECONDS,
        ):
            catalog = lock_catalog
            market = MarketDataService(catalog, CanonicalMonthlyStore(root))
            products = tuple(load_operational_products())
            coverage = DatabaseCoverageSource(
                session,
                PROJECT_ROOT / "data/universe/product_window_starts.csv",
                now=lambda: frozen_as_of,
            )

            def run_audit(request: ReadinessRequest) -> Mapping[str, Any]:
                budget = AuditBudget(request, time.monotonic)

                def reader_factory(context, cancelled):
                    return NewowProductReader(
                        market,
                        coverage=coverage,
                        active_products=products,
                        context_frequencies=context,
                        now=lambda: request.as_of,
                        cancelled=lambda: (
                            budget.expired() or (cancelled is not None and cancelled())
                        ),
                    )

                planner = ContractWarmupPlanner(
                    catalog=catalog,
                    store=market.store,
                    coverage=coverage,
                    check_budget=budget.checkpoint,
                )
                report = NewowReadinessAudit(
                    reader=reader_factory((), None),
                    plan=lambda intent: asdict(planner.plan(intent)),
                    budget=budget,
                    service=NewowProductService(
                        reader_factory,
                        now=lambda: request.as_of,
                        cancelled=budget.expired,
                    ),
                ).run(request)
                observations: list[tuple[Any, datetime, Any]] = []

                class RecordingReader:
                    def __init__(self, delegate: NewowProductReader) -> None:
                        self._delegate = delegate

                    def __getattr__(self, name: str) -> Any:
                        return getattr(self._delegate, name)

                    def load(self, query: Any, as_of: datetime) -> Any:
                        value = self._delegate.load(query, as_of)
                        observations.append((query, as_of, value))
                        return value

                def recording_factory(context, cancelled):
                    return RecordingReader(reader_factory(context, cancelled))

                comparator_service = NewowProductService(
                    recording_factory,
                    now=lambda: request.as_of,
                    cancelled=budget.expired,
                )
                try:
                    comparator_evidence = _runtime_default_comparator_evidence(
                        service=comparator_service,
                        observations=observations,
                        products=products,
                        as_of=request.as_of,
                        dependency_proof=_dependency_proof,
                    )
                except Exception:  # noqa: BLE001 - evidence stays sanitized
                    comparator_evidence = {
                        "status": "not_verified",
                        "error_code": "COMPARATOR_PROOF_FAILED",
                    }
                return {**dict(report), "_comparator_evidence": comparator_evidence}

            planner = ContractWarmupPlanner(
                catalog=catalog,
                store=market.store,
                coverage=coverage,
            )

            def replan_unit(unit: Mapping[str, Any]) -> Mapping[str, Any]:
                plan = planner.plan(
                    ContractWarmupRequest(
                        symbol=str(unit["symbol"]),
                        contract=str(unit["contract"]),
                        through=datetime.fromisoformat(
                            f"{unit['through']}T00:00:00+00:00"
                        ).date(),
                        frequency="1d",
                    )
                )
                targets = [dict(item) for item in plan.target_windows]
                return {
                    "status": "passed" if not targets else "remaining",
                    "symbol": plan.symbol,
                    "contract": plan.contract,
                    "frequency": "1d",
                    "requested_through": plan.requested_through.isoformat(),
                    "plan_sha256": plan.plan_sha256,
                    "targets": targets,
                    "remaining_target_count": len(targets),
                }

            result = verify_daily_campaign(
                campaign=campaign,
                execution=execution,
                run_audit=run_audit,
                replan_unit=replan_unit,
            )
            observed_at = datetime.now(UTC).isoformat()
            result["execution"].update(
                execution_sha256=execution_sha256,
                attempt_identity=attempt_identity,
            )
            result["provenance"].update(
                execution_sha256=execution_sha256,
                attempt_identity=attempt_identity,
                observed_at=observed_at,
            )
            return result
    finally:
        if lease is not None:
            lease.release()
        session.close()
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        root = campaign_module._validated_evidence_root(Path(args.output_root))
        campaign_path = Path(args.campaign)
        campaign = native.load_prepared_manifest(
            campaign_path, args.expected_campaign_sha256
        )
        campaign = campaign_module.validate_campaign_manifest(
            campaign, evidence_root=root
        )
        bound_campaign = {
            **campaign,
            "campaign_sha256": args.expected_campaign_sha256,
        }
        if args.execution_not_required:
            if args.execution is not None or args.expected_execution_sha256 is not None:
                raise native.RecoveryError("VERIFICATION_INPUT_INVALID")
            execution = _not_required_execution(
                bound_campaign, args.expected_campaign_sha256
            )
            execution_sha256 = None
            attempt_identity = "not_required"
        else:
            if args.execution is None or args.expected_execution_sha256 is None:
                raise native.RecoveryError("VERIFICATION_INPUT_INVALID")
            execution_path = Path(args.execution)
            execution = native.load_prepared_manifest(
                execution_path, args.expected_execution_sha256
            )
            if (
                execution.get("campaign_manifest_sha256")
                != args.expected_campaign_sha256
            ):
                raise native.RecoveryError("VERIFICATION_IDENTITY_CHANGED")
            _validate_persisted_execution_evidence(
                campaign=campaign,
                execution=execution,
                campaign_path=campaign_path,
                execution_path=execution_path,
                evidence_root=root,
            )
            execution_sha256 = args.expected_execution_sha256
            attempt_identity = execution_path.parent.name
        observation = native.create_attempt_directory(root, args.observation_id)
        result = _run_readonly_verification(
            campaign=bound_campaign,
            execution=execution,
            project_env=Path(args.project_env),
            execution_sha256=execution_sha256,
            attempt_identity=attempt_identity,
        )
        try:
            verification_path = observation / "verification.json"
            verification_content = (
                native._canonical_json(result) + "\n"
            ).encode("utf-8")
            _write_atomic_exclusive(verification_path, verification_content)
            if native._read_json_file(verification_path) != result:
                raise OSError
            summary = render_daily_summary(result).encode("utf-8")
            _write_atomic_exclusive(observation / "summary.md", summary)
        except (OSError, native.RecoveryError) as exc:
            raise native.RecoveryError("VERIFICATION_RESULT_SAVE_FAILED") from exc
        payload = {
            "schema_version": _SCHEMA,
            "status": result["verification_status"],
            "observation_dir": str(observation),
            "provider_requests": 0,
            "writes": 0,
        }
        code = (
            0
            if result.get("verification_status") == "verified"
            and result.get("ordinary_recovery_complete") is True
            and result.get("inventory_complete") is True
            else 1
        )
    except native.RecoveryError as exc:
        error_code = native._error_code(exc)
        payload = {
            "schema_version": _SCHEMA,
            "status": (
                "identity_changed"
                if error_code == "VERIFICATION_IDENTITY_CHANGED"
                else "failed"
            ),
            "error_code": error_code,
        }
        code = 2
    except (ValueError, OSError):
        payload = {
            "schema_version": _SCHEMA,
            "status": "failed",
            "error_code": "VERIFICATION_INPUT_INVALID",
        }
        code = 2
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
