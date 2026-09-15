"""Independent read-only settlement for one frozen Newow D1 recovery attempt."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping

from guiyi_quant.newow.product_contracts import ProductFrequency

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
) -> tuple[dict[str, int], bool]:
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
    complete = (
        execution.get("status") == "passed"
        and counts["success"] == denominator
        and not any(counts[name] for name in counts if name != "success")
    )
    return counts, complete


def _validate_replan(
    unit: Mapping[str, Any], value: Mapping[str, Any]
) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or value.get("status") != "passed"
        or value.get("symbol") != unit["symbol"]
        or value.get("contract") != unit["contract"]
        or value.get("frequency") != "1d"
        or value.get("requested_through") != unit["through"]
        or _HASH.fullmatch(str(value.get("plan_sha256", ""))) is None
        or value.get("targets") != []
        or value.get("remaining_target_count") != 0
    ):
        raise native.RecoveryError("FINAL_REPLAN_INVALID")
    return dict(value)


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
    counts, ordinary_complete = _validated_execution(campaign, execution)
    replans: list[dict[str, Any]] = []
    replan_error: str | None = None
    if ordinary_complete:
        try:
            replans = [_validate_replan(unit, replan_unit(unit)) for unit in units]
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
        if inventory_complete and ordinary_complete and replan_error is None:
            availability = _input_availability(audit)
            verification_status = (
                "verified"
                if availability
                and all(row["status"] == "available" for row in availability)
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
        "comparator_evidence": {
            "status": "bounded_to_default_chart_input",
            "custom_or_paginated_windows": "not_verified",
        },
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
        "比较器仅验证默认主图共享输入；自定义和历史翻页窗口未外推。",
    ]
    return "\n".join(lines) + "\n"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Independently verify one frozen Newow D1 recovery attempt."
    )
    value.add_argument("--project-env", required=True)
    value.add_argument("--campaign", required=True)
    value.add_argument("--expected-campaign-sha256", required=True)
    value.add_argument("--execution", required=True)
    value.add_argument("--expected-execution-sha256", required=True)
    value.add_argument("--output-root", required=True)
    value.add_argument("--observation-id", required=True)
    return value


def _run_readonly_verification(
    *,
    campaign: Mapping[str, Any],
    execution: Mapping[str, Any],
    project_env: Path,
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
    from app.market_data.newow.product_service import NewowProductService
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
    settings, current_identity = native.load_private_execution_settings(project_env)
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
        with readonly_transaction(session, timeout_seconds=300):
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
                return NewowReadinessAudit(
                    reader=reader_factory((), None),
                    plan=lambda intent: asdict(planner.plan(intent)),
                    budget=budget,
                    service=NewowProductService(
                        reader_factory,
                        now=lambda: request.as_of,
                        cancelled=budget.expired,
                    ),
                ).run(request)

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

            return verify_daily_campaign(
                campaign=campaign,
                execution=execution,
                run_audit=run_audit,
                replan_unit=replan_unit,
            )
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
        execution_path = Path(args.execution)
        campaign = native.load_prepared_manifest(
            campaign_path, args.expected_campaign_sha256
        )
        execution = native.load_prepared_manifest(
            execution_path, args.expected_execution_sha256
        )
        campaign_module.validate_campaign_manifest(
            campaign, evidence_root=campaign_path.parent
        )
        bound_campaign = {
            **campaign,
            "campaign_sha256": args.expected_campaign_sha256,
        }
        if execution.get("campaign_manifest_sha256") != args.expected_campaign_sha256:
            raise native.RecoveryError("VERIFICATION_IDENTITY_CHANGED")
        observation = native.create_attempt_directory(root, args.observation_id)
        result = _run_readonly_verification(
            campaign=bound_campaign,
            execution=execution,
            project_env=Path(args.project_env),
        )
        native._write_json_exclusive(observation / "verification.json", result)
        summary = render_daily_summary(result).encode("utf-8")
        fd = os.open(
            observation / "summary.md",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        try:
            os.write(fd, summary)
            os.fsync(fd)
        finally:
            os.close(fd)
        native._fsync_directory(observation)
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
