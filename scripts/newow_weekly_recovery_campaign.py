"""One bounded campaign over native Newow W1 recovery batches."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any, Callable, Literal, Mapping, Sequence, cast

from guiyi_quant.newow.product_contracts import ProductStrategy

from app.market_data.newow import readiness as native_readiness
from app.market_data.newow.product_release import deferred_section_reason
from app.market_data.operational_universe import load_operational_products
from scripts import newow_recovery_partial_exception as partial_exception
from scripts import newow_weekly_recovery as native


RecoveryError = native.RecoveryError

_CAMPAIGN_SCHEMA = "newow_weekly_recovery_campaign_v1"
_HASH = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SYMBOL = re.compile(r"[a-z]{1,8}")
_CONTRACT = re.compile(r"[A-Z]{1,8}[0-9]{3,4}")
_SectionName = Literal["chart", "auxiliary", "reference", "explanation"]
_REPORT_SECTIONS: tuple[_SectionName, ...] = (
    "chart",
    "auxiliary",
    "reference",
    "explanation",
)
_REPORT_REQUIRED = {
    "schema_version": 1,
    "command": "data.newow-readiness",
    "status": "audited",
    "complete": True,
    "budget_exhausted": False,
    "readonly": True,
    "provider_requests": 0,
    "writes": 0,
    "release_stage": "weekly",
    "frequency_scope": ["1w"],
    "matrix": False,
}
_REPORT_STRUCTURAL = {
    "product_count",
    "main_case_count",
    "main_ready_count",
    "work_used",
    "enumerations",
    "dependencies",
    "repair_targets",
    "metadata_proposals",
    "cases",
}
_UNKNOWN_UNIT_ERROR_CODES = {
    "COMMIT_OUTCOME_UNKNOWN",
}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Prepare or execute one bounded Newow W1 recovery campaign."
    )
    commands = value.add_subparsers(dest="mode", required=True)
    prepare = commands.add_parser("prepare", allow_abbrev=False)
    prepare.add_argument("--project-env", required=True)
    prepare.add_argument("--report", required=True)
    prepare.add_argument("--expected-report-sha256", required=True)
    prepare.add_argument("--output-root", required=True)
    prepare.add_argument("--name", required=True)
    prepare.add_argument("--isolate-known-source-quality", action="store_true")
    prepare.add_argument("--prior-campaign")
    prepare.add_argument("--expected-prior-campaign-sha256")
    prepare.add_argument("--prior-attempt")
    prepare.add_argument("--source-only-prepared")
    prepare.add_argument("--expected-source-only-prepared-sha256")
    prepare.add_argument("--source-only-attempt")
    prepare.add_argument("--source-only-unit-index", type=int)
    prepare.add_argument("--source-only-request-index", type=int)
    prepare.add_argument("--expected-source-only-request-sha256")
    prepare.add_argument("--partial-source-exception-attempt")
    apply = commands.add_parser("apply", allow_abbrev=False)
    apply.add_argument("--project-env", required=True)
    apply.add_argument("--campaign", required=True)
    apply.add_argument("--expected-campaign-sha256", required=True)
    apply.add_argument("--output-root", required=True)
    apply.add_argument("--attempt-id", required=True)
    apply.add_argument("--apply", action="store_true", required=True)
    inspect = commands.add_parser("inspect", allow_abbrev=False)
    inspect.add_argument("--attempt", required=True)
    return value


def main(
    argv: list[str] | None = None,
    *,
    stdout=sys.stdout,
) -> int:
    payload: dict[str, Any]
    try:
        args = parser().parse_args(argv)
        if args.mode == "inspect":
            payload = {
                "schema_version": "newow_weekly_recovery_campaign_result_v1",
                "status": "inspected",
                "attempt": _inspect_attempt(Path(args.attempt)),
            }
            code = 0
        elif args.mode == "prepare":
            report = _load_hash_locked_mapping(
                Path(args.report),
                args.expected_report_sha256,
                "CAMPAIGN_REPORT_INVALID",
            )
            identity = _current_execution_identity(Path(args.project_env))
            root = _validated_evidence_root(Path(args.output_root))
            policy = (
                native.source_isolation_policy()
                if args.isolate_known_source_quality
                else None
            )

            def invoke_prepare(
                units: tuple[dict[str, Any], ...],
                batch_id: str,
                evidence_root: Path,
            ) -> Mapping[str, Any]:
                units_path = evidence_root / f"{batch_id}.units.json"
                try:
                    native._write_json_exclusive(units_path, list(units))
                except OSError as exc:
                    raise RecoveryError("CAMPAIGN_CHILD_INPUT_UNAVAILABLE") from exc
                output = io.StringIO()
                native_argv = [
                    "prepare",
                    "--project-env",
                    str(args.project_env),
                    "--units",
                    str(units_path),
                    "--output-root",
                    str(evidence_root),
                    "--name",
                    batch_id,
                ]
                if policy is not None:
                    native_argv.append("--isolate-known-source-quality")
                return_code = native.main(
                    native_argv,
                    stdout=output,
                )
                child_payload = _decoded_mapping(output.getvalue())
                if return_code != 0:
                    raise RecoveryError("CAMPAIGN_CHILD_INVALID")
                return child_payload

            manifest = prepare_campaign(
                report,
                report_sha256=args.expected_report_sha256,
                evidence_root=root,
                execution_identity=identity,
                invoke_batch=invoke_prepare,
                name=args.name,
                continuation_policy=policy,
                prior_campaign_path=(
                    Path(args.prior_campaign) if args.prior_campaign else None
                ),
                expected_prior_campaign_sha256=(args.expected_prior_campaign_sha256),
                prior_attempt_path=(
                    Path(args.prior_attempt) if args.prior_attempt else None
                ),
                source_only_prepared_path=(
                    Path(args.source_only_prepared)
                    if args.source_only_prepared
                    else None
                ),
                expected_source_only_prepared_sha256=(
                    args.expected_source_only_prepared_sha256
                ),
                source_only_attempt_path=(
                    Path(args.source_only_attempt)
                    if args.source_only_attempt
                    else None
                ),
                source_only_unit_index=args.source_only_unit_index,
                source_only_request_index=args.source_only_request_index,
                expected_source_only_request_sha256=(
                    args.expected_source_only_request_sha256
                ),
                partial_source_exception_attempt_path=(
                    Path(args.partial_source_exception_attempt)
                    if args.partial_source_exception_attempt
                    else None
                ),
                observe_partial_committed=(
                    _live_partial_committed_observer(Path(args.project_env))
                    if args.partial_source_exception_attempt
                    else None
                ),
            )
            campaign_path = root / f"{args.name}.prepare.json"
            payload = {
                "schema_version": "newow_weekly_recovery_campaign_result_v1",
                "status": manifest["status"],
                "readonly": True,
                "campaign_file": str(campaign_path),
                "campaign_sha256": hashlib.sha256(
                    campaign_path.read_bytes()
                ).hexdigest(),
                "batch_count": manifest["totals"]["batch_count"],
                "unit_count": manifest["totals"]["unit_count"],
                "provider_requests": 0,
                "writes": 0,
            }
            code = 0
        else:
            root = _validated_evidence_root(Path(args.output_root))
            manifest = _load_hash_locked_mapping(
                Path(args.campaign),
                args.expected_campaign_sha256,
                "CAMPAIGN_MANIFEST_INVALID",
            )
            validate_campaign_manifest(manifest, evidence_root=root)
            current_identity = _current_execution_identity(Path(args.project_env))
            if manifest.get("execution_identity") != current_identity:
                raise RecoveryError("EXECUTION_IDENTITY_CHANGED")

            def invoke_apply(
                child: Path,
                digest: str,
                batch_attempt: Path,
            ) -> Mapping[str, Any]:
                output = io.StringIO()
                return_code = native.main(
                    [
                        "apply",
                        "--project-env",
                        str(args.project_env),
                        "--prepared",
                        str(child),
                        "--expected-prepared-sha256",
                        digest,
                        "--output-root",
                        str(batch_attempt),
                        "--attempt-id",
                        "native",
                        "--apply",
                    ],
                    stdout=output,
                )
                return {
                    "return_code": return_code,
                    "batch_result": _decoded_mapping(output.getvalue()),
                }

            result = execute_campaign(
                manifest,
                attempt_root=root / args.attempt_id,
                invoke_batch=invoke_apply,
                observe_partial_committed=_live_partial_committed_observer(
                    Path(args.project_env)
                ),
            )
            payload = {
                "schema_version": "newow_weekly_recovery_campaign_result_v1",
                **result,
                "readonly": False,
                "attempt_dir": str(root / args.attempt_id),
            }
            code = 0 if result["status"] == "passed" else 1
    except (RecoveryError, ValueError) as exc:
        payload = {
            "schema_version": "newow_weekly_recovery_campaign_error_v1",
            "status": "failed",
            "error_code": native._error_code(exc),
        }
        code = 1
    except Exception:
        payload = {
            "schema_version": "newow_weekly_recovery_campaign_error_v1",
            "status": "failed",
            "error_code": "CAMPAIGN_EXECUTION_FAILED",
        }
        code = 1
    stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    stdout.write("\n")
    return code


def execute_campaign(
    manifest: Mapping[str, Any],
    *,
    attempt_root: Path,
    invoke_batch: Callable[[Path, str, Path], Mapping[str, Any]],
    observe_partial_committed: Callable[
        [Mapping[str, Any], list[dict[str, Any]]], Mapping[str, Any]
    ]
    | None = None,
) -> dict[str, Any]:
    """Execute each frozen native child once, stopping globally on first doubt."""
    attempt = Path(attempt_root)
    root = _validated_evidence_root(attempt.parent)
    if (
        not attempt.is_absolute()
        or attempt.parent.resolve() != root
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", attempt.name) is None
    ):
        raise RecoveryError("CAMPAIGN_ATTEMPT_PATH_INVALID")
    validated = validate_campaign_manifest(manifest, evidence_root=root)
    identity = validated["execution_identity"]
    children = validated["children"]
    guard_binding = validated["writer_guard"]
    with _campaign_writer_guard(root, guard_binding):
        _revalidate_partial_source_exceptions(
            validated,
            evidence_root=root,
            current_identity=identity,
            observe_committed=observe_partial_committed,
        )
        try:
            attempt.mkdir(mode=0o700)
            native._fsync_directory(root)
        except FileExistsError as exc:
            raise RecoveryError("CAMPAIGN_ATTEMPT_EXISTS") from exc
        except OSError as exc:
            raise RecoveryError("CAMPAIGN_ATTEMPT_UNAVAILABLE") from exc
        started = {
            "schema_version": "newow_weekly_recovery_campaign_started_v1",
            "campaign_manifest_sha256": hashlib.sha256(
                native._canonical_json(validated).encode("utf-8")
            ).hexdigest(),
            "execution_identity": identity,
            "batch_count": len(children),
            "retries": 0,
        }
        try:
            native._write_json_exclusive(attempt / "campaign-started.json", started)
        except OSError as exc:
            raise RecoveryError("CAMPAIGN_STARTED_UNAVAILABLE") from exc

        completed: list[dict[str, Any]] = []
        successful_units: list[dict[str, Any]] = []
        isolated_units = [
            _prior_isolated_unit(binding)
            for binding in validated.get("prior_known_isolations", [])
        ]
        isolated_units.extend(
            _source_only_isolated_unit(binding)
            for binding in validated.get("source_only_known_isolations", [])
        )
        partial_source_exception_units = [
            _partial_source_exception_unit(binding)
            for binding in validated.get("prior_partial_source_exceptions", [])
        ]
        failed: dict[str, Any] | None = None
        unknown: dict[str, Any] | None = None
        stopping_failure_unit_count = 0
        unattempted_unit_count = 0
        unknown_unit_count = 0
        stopped_index = len(children)
        for index, child in enumerate(children):
            batch_id = child["batch_id"]
            try:
                _validate_writer_guard(
                    root,
                    guard_binding,
                    identity["canonical_root_sha256"],
                )
            except RecoveryError:
                failed = {
                    "batch_id": batch_id,
                    "error_code": "CAMPAIGN_GUARD_CHANGED",
                }
                stopped_index = index
                break
            try:
                _revalidate_child(child, identity=identity, root=root)
            except RecoveryError:
                failed = {
                    "batch_id": batch_id,
                    "error_code": "CAMPAIGN_CHILD_DRIFT",
                }
                stopped_index = index
                break
            batch_attempt = attempt / batch_id
            try:
                batch_attempt.mkdir(mode=0o700)
                native._fsync_directory(attempt)
                native._write_json_exclusive(
                    batch_attempt / "batch-started.json",
                    {
                        "schema_version": "newow_weekly_recovery_campaign_batch_v1",
                        "state": "started",
                        "batch_id": batch_id,
                        "child_path": child["path"],
                        "child_sha256": child["sha256"],
                    },
                )
            except OSError:
                failed = {
                    "batch_id": batch_id,
                    "error_code": "CAMPAIGN_BATCH_STARTED_UNAVAILABLE",
                }
                stopped_index = index
                break
            try:
                invocation = invoke_batch(
                    root / child["path"],
                    child["sha256"],
                    batch_attempt,
                )
            except Exception:  # noqa: BLE001 - never expose external details
                unknown = {
                    "batch_id": batch_id,
                    "error_code": "CAMPAIGN_BATCH_OUTCOME_UNKNOWN",
                }
                stopped_index = index
                break
            terminal = _validated_batch_invocation(
                invocation,
                child=child,
                child_path=root / child["path"],
                digest=child["sha256"],
                batch_attempt=batch_attempt,
                identity=identity,
            )
            if terminal is None:
                unknown = {
                    "batch_id": batch_id,
                    "error_code": "CAMPAIGN_BATCH_OUTCOME_UNKNOWN",
                }
                stopped_index = index
                break
            try:
                native._write_json_exclusive(
                    batch_attempt / "batch-terminal.json",
                    {
                        "schema_version": "newow_weekly_recovery_campaign_batch_v1",
                        "state": "terminal",
                        "batch_id": batch_id,
                        "native_result": terminal,
                    },
                )
            except OSError:
                unknown = {
                    "batch_id": batch_id,
                    "error_code": "CAMPAIGN_BATCH_OUTCOME_UNKNOWN",
                }
                stopped_index = index
                break
            native_result = terminal["result"]
            successful_units.extend(native_result["completed"])
            isolated_units.extend(native_result.get("isolated", []))
            safely_exhausted = (
                terminal["status"] == "partial"
                and native_result.get("failed") is None
                and native_result.get("unattempted") == []
                and bool(native_result.get("isolated"))
            )
            if terminal["status"] != "passed" and not safely_exhausted:
                failure_outcome = _native_failed_unit_outcome(
                    terminal,
                    child_path=root / child["path"],
                    digest=child["sha256"],
                )
                if failure_outcome == "known":
                    failed = {"batch_id": batch_id, "native_result": terminal}
                    stopping_failure_unit_count = 1
                else:
                    unknown = {
                        "batch_id": batch_id,
                        "error_code": "CAMPAIGN_UNIT_OUTCOME_UNKNOWN",
                        "native_result": terminal,
                    }
                    unknown_unit_count = 1
                unattempted_unit_count = len(native_result["unattempted"])
                stopped_index = index
                break
            completed.append({"batch_id": batch_id, "native_result": terminal})

        unattempted = [child["batch_id"] for child in children[stopped_index + 1 :]]
        if unknown is not None:
            status = "unknown"
        elif failed is not None:
            native_status = (
                failed.get("native_result", {}).get("status")
                if isinstance(failed.get("native_result"), Mapping)
                else None
            )
            status = (
                "partial"
                if completed
                or isolated_units
                or partial_source_exception_units
                or native_status == "partial"
                else "failed"
            )
        else:
            status = (
                "partial"
                if isolated_units or partial_source_exception_units
                else "passed"
            )
            unattempted = []
        later_unattempted_unit_count = sum(
            child["unit_count"]
            for child in children
            if child["batch_id"] in unattempted
        )
        unattempted_unit_count += later_unattempted_unit_count
        if unknown is not None and unknown_unit_count == 0:
            unknown_unit_count = next(
                (
                    child["unit_count"]
                    for child in children
                    if child["batch_id"] == unknown.get("batch_id")
                ),
                0,
            )
        elif failed is not None and "native_result" not in failed:
            unattempted_unit_count += next(
                (
                    child["unit_count"]
                    for child in children
                    if child["batch_id"] == failed.get("batch_id")
                ),
                0,
            )
        anomaly_repair_requirements: dict[str, list[dict[str, Any]]] = {}
        for unit in isolated_units:
            code = unit["classification"]
            anomaly_repair_requirements.setdefault(code, []).append(
                {
                    key: unit[key]
                    for key in (
                        "symbol",
                        "contract",
                        "frequency",
                        "through",
                        "plan_sha256",
                    )
                }
            )
        denominator = validated["scope"].get(
            "denominator_unit_count", validated["totals"]["unit_count"]
        )
        classified = (
            len(successful_units)
            + len(isolated_units)
            + len(partial_source_exception_units)
            + stopping_failure_unit_count
            + unattempted_unit_count
            + unknown_unit_count
        )
        if classified != denominator:
            if classified > denominator:
                raise RecoveryError("CAMPAIGN_SETTLEMENT_INVALID")
            unknown_unit_count += denominator - classified
            unknown = unknown or {
                "batch_id": None,
                "error_code": "CAMPAIGN_SETTLEMENT_UNKNOWN",
            }
            status = "unknown"
        result: dict[str, Any] = {
            "status": status,
            "completed_batch_ids": [item["batch_id"] for item in completed],
            "completed_batches": completed,
            "failed_batch": failed,
            "unknown_batch": unknown,
            "unattempted_batch_ids": unattempted,
            "isolated_units": isolated_units,
            "partial_source_exception_units": partial_source_exception_units,
            "summary": {
                "denominator_unit_count": denominator,
                "success_unit_count": len(successful_units),
                "isolated_unit_count": len(isolated_units),
                "partial_source_exception_unit_count": len(
                    partial_source_exception_units
                ),
                "stopping_failure_unit_count": stopping_failure_unit_count,
                "unattempted_unit_count": unattempted_unit_count,
                "unknown_unit_count": unknown_unit_count,
            },
            "anomaly_repair_requirements": anomaly_repair_requirements,
            "retries": 0,
        }
        try:
            native._write_json_exclusive(attempt / "campaign-result.json", result)
        except OSError:
            return {
                **result,
                "status": "unknown",
                "error_code": "CAMPAIGN_RESULT_UNAVAILABLE",
            }
        return result


def partition_ordinary_units(
    report: Mapping[str, Any],
) -> tuple[tuple[dict[str, Any], ...], ...]:
    """Validate one native audit and split its ordinary W1 units by twenty."""
    targets, _excluded = _validated_report_targets(report)
    units = tuple(
        {
            "symbol": item["symbol"],
            "contract": item["contract"],
            "through": item["through"],
            "frequency": "1w",
            "expected_plan_sha256": item["plan_sha256"],
        }
        for item in targets
        if item["status"] == "PROPOSED"
    )
    return tuple(tuple(units[index : index + 20]) for index in range(0, len(units), 20))


def _prior_isolated_unit(binding: Mapping[str, Any]) -> dict[str, Any]:
    unit = cast(Mapping[str, Any], binding["unit"])
    return {
        **unit,
        "status": "isolated",
        "classification": binding["classification"],
        "source_evidence": binding["source_evidence"],
        "provenance": "prior_known",
        "prior_evidence": {
            key: binding[key]
            for key in (
                "prior_campaign",
                "prior_campaign_result_sha256",
                "prior_attempt_path",
                "batch_id",
                "child_sha256",
                "unit_index",
                "evidence_artifacts",
                "binding_sha256",
            )
        },
    }


def _source_only_isolated_unit(binding: Mapping[str, Any]) -> dict[str, Any]:
    unit = cast(Mapping[str, Any], binding["unit"])
    return {
        **unit,
        "status": "isolated",
        "classification": binding["classification"],
        "source_evidence": binding["source_evidence"],
        "provenance": "source_only_known",
        "source_only_evidence": {
            key: binding[key]
            for key in (
                "source_prepared",
                "source_attempt_path",
                "unit_index",
                "request_index",
                "request_sha256",
                "evidence_artifacts",
                "binding_sha256",
            )
        },
    }


def _partial_source_exception_unit(binding: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "symbol": binding["symbol"],
        "contract": binding["contract"],
        "frequency": binding["frequency"],
        "through": binding["through"],
        "plan_sha256": binding["fresh_replan_sha256"],
        "failed_plan_sha256": binding["failed_plan_sha256"],
        "status": "partial_source_exception",
        "classification": binding["classification"],
        "evidence_sha256": binding["evidence_sha256"],
        "provenance": "prior_partial_source_exception",
        "committed_targets": binding["committed_targets"],
        "remaining_targets": binding["remaining_targets"],
    }


def _revalidate_partial_source_exceptions(
    manifest: Mapping[str, Any],
    *,
    evidence_root: Path,
    current_identity: Mapping[str, str],
    observe_committed: Callable[
        [Mapping[str, Any], list[dict[str, Any]]], Mapping[str, Any]
    ]
    | None,
) -> None:
    bindings = manifest.get("prior_partial_source_exceptions", [])
    if not bindings:
        return
    derived: list[dict[str, Any]] = []
    for binding in bindings:
        derived.extend(
            _derive_partial_source_exceptions(
                evidence_root,
                current_identity=current_identity,
                attempt_path=evidence_root
                / str(binding["failed_attempt_path"]),
                fresh_units=[
                    {
                        "symbol": binding["symbol"],
                        "contract": binding["contract"],
                        "frequency": binding["frequency"],
                        "through": binding["through"],
                        "plan_sha256": binding["fresh_replan_sha256"],
                        "targets": binding["remaining_targets"],
                    }
                ],
                observe_committed=observe_committed,
                stored_bindings=[binding],
            )
        )
    if derived != list(bindings):
        raise RecoveryError(partial_exception.ERROR_CODE)


def _carried_partial_source_exceptions(
    root: Path,
    *,
    prior_campaign_path: Path | None,
    expected_prior_campaign_sha256: str | None,
    current_identity: Mapping[str, str],
    fresh_units: Sequence[Mapping[str, Any]],
    observe_committed: Callable[
        [Mapping[str, Any], list[dict[str, Any]]], Mapping[str, Any]
    ]
    | None,
) -> list[dict[str, Any]]:
    if prior_campaign_path is None:
        return []
    if expected_prior_campaign_sha256 is None:
        raise RecoveryError(partial_exception.ERROR_CODE)
    campaign_path = _direct_root_file(prior_campaign_path, root)
    prior_manifest = _load_hash_locked_mapping(
        campaign_path,
        expected_prior_campaign_sha256,
        partial_exception.ERROR_CODE,
    )
    validated = validate_campaign_manifest(prior_manifest, evidence_root=root)
    bindings = validated.get("prior_partial_source_exceptions", [])
    if not isinstance(bindings, list):
        raise RecoveryError(partial_exception.ERROR_CODE)
    carried: list[dict[str, Any]] = []
    for binding in bindings:
        if not isinstance(binding, Mapping):
            raise RecoveryError(partial_exception.ERROR_CODE)
        carried.extend(
            _derive_partial_source_exceptions(
                root,
                current_identity=current_identity,
                attempt_path=root / str(binding.get("failed_attempt_path", "")),
                fresh_units=fresh_units,
                observe_committed=observe_committed,
                stored_bindings=[binding],
            )
        )
    if carried != bindings:
        raise RecoveryError(partial_exception.ERROR_CODE)
    return carried


def _derive_partial_source_exceptions(
    evidence_root: Path,
    *,
    current_identity: Mapping[str, str],
    attempt_path: Path | None,
    fresh_units: Sequence[Mapping[str, Any]],
    observe_committed: Callable[
        [Mapping[str, Any], list[dict[str, Any]]], Mapping[str, Any]
    ]
    | None,
    stored_bindings: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if attempt_path is None:
        return []
    if observe_committed is None and stored_bindings:
        def observe_committed(
            unit: Mapping[str, Any],
            committed: list[dict[str, Any]],
            *,
            bound: Mapping[str, Any] = stored_bindings[0],
        ) -> Mapping[str, Any]:
            return {
                "catalog_readback": bound["catalog_readback"],
                "parquet_readback": bound["parquet_readback"],
                "mds_readback": bound["mds_readback"],
            }
    if observe_committed is None:
        raise RecoveryError(partial_exception.ERROR_CODE)
    attempt = _direct_root_directory(attempt_path, evidence_root)
    return partial_exception.derive_partial_source_exceptions(
        evidence_root=evidence_root,
        attempt_path=attempt,
        fresh_units=fresh_units,
        current_identity=current_identity,
        observe_committed=observe_committed,
    )


def _live_partial_committed_observer(
    project_env: Path,
) -> Callable[[Mapping[str, Any], list[dict[str, Any]]], Mapping[str, Any]]:
    """Read Catalog/Parquet/MDS for committed targets without initializing RQData."""

    def observe(
        unit: Mapping[str, Any],
        committed: list[dict[str, Any]],
    ) -> Mapping[str, Any]:
        from types import SimpleNamespace

        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from app.db.url import normalize_database_url
        from app.market_data.catalog import MarketCatalog
        from app.market_data.domain import DatasetKey
        from app.market_data.storage import CanonicalMonthlyStore

        settings, _identity = native.load_private_execution_settings(project_env)
        engine = create_engine(
            normalize_database_url(settings["DATABASE_URL"]),
            pool_pre_ping=True,
        )
        session = Session(engine, autoflush=False)
        try:
            root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
            manager = SimpleNamespace(
                catalog=MarketCatalog(session, root),
                store=CanonicalMonthlyStore(root),
            )
            readback = native._post_commit_readback(
                manager,
                {
                    "symbol": unit["symbol"],
                    "contract": unit["contract"],
                    "frequency": unit["frequency"],
                    "targets": committed,
                },
            )
            if not committed:
                raise RecoveryError(partial_exception.ERROR_CODE)
            committed_ids = {
                (tuple(item["dataset"]), item["year"], item["month"])
                for item in committed
            }
            remaining_targets = [
                item
                for item in unit.get("targets", [])
                if isinstance(item, Mapping)
                and (
                    tuple(item.get("dataset", [])),
                    item.get("year"),
                    item.get("month"),
                )
                not in committed_ids
            ]
            for target in remaining_targets:
                dataset = target.get("dataset")
                year = target.get("year")
                month = target.get("month")
                expected_count = target.get("expected_bar_count")
                if not isinstance(dataset, list) or len(dataset) != 4:
                    raise RecoveryError(partial_exception.ERROR_CODE)
                rows = tuple(
                    item
                    for item in manager.catalog.all_partitions(DatasetKey(*dataset))
                    if (item.year, item.month) == (year, month)
                )
                if (
                    len(rows) == 1
                    and isinstance(expected_count, int)
                    and not isinstance(expected_count, bool)
                    and rows[0].row_count == expected_count
                ):
                    raise RecoveryError(partial_exception.ERROR_CODE)
        except RecoveryError as exc:
            raise RecoveryError(partial_exception.ERROR_CODE) from exc
        except Exception as exc:
            raise RecoveryError(partial_exception.ERROR_CODE) from exc
        finally:
            session.close()
            engine.dispose()
        partitions: list[dict[str, object]] = []
        files: list[dict[str, object]] = []
        windows: list[dict[str, object]] = []
        catalog_partitions = readback.get("catalog_partitions")
        if not isinstance(catalog_partitions, list):
            raise RecoveryError(partial_exception.ERROR_CODE)
        for item in catalog_partitions:
            if not isinstance(item, Mapping):
                raise RecoveryError(partial_exception.ERROR_CODE)
            partitions.append(
                {
                    "dataset": item["dataset"],
                    "year": item["year"],
                    "month": item["month"],
                    "row_count": item["catalog_row_count"],
                }
            )
            files.append(
                {
                    "dataset": item["dataset"],
                    "year": item["year"],
                    "month": item["month"],
                    "row_count": item["physical_row_count"],
                    "file_sha256": item["file_sha256"],
                }
            )
            windows.append(
                {
                    "dataset": item["dataset"],
                    "year": item["year"],
                    "month": item["month"],
                    "bar_count": item["mds_bar_count"],
                }
            )
        return {
            "catalog_readback": {"status": "passed", "partitions": partitions},
            "parquet_readback": {"status": "passed", "files": files},
            "mds_readback": {"status": "passed", "windows": windows},
        }

    return observe


def _derive_prior_isolations(
    root: Path,
    *,
    policy: Mapping[str, object] | None,
    prior_campaign_path: Path | None,
    expected_prior_campaign_sha256: str | None,
    prior_attempt_path: Path | None,
) -> list[dict[str, Any]]:
    values = (
        prior_campaign_path,
        expected_prior_campaign_sha256,
        prior_attempt_path,
    )
    if all(value is None for value in values):
        return []
    if policy is None or any(value is None for value in values):
        raise RecoveryError("PRIOR_ISOLATION_INVALID")
    assert prior_campaign_path is not None
    assert expected_prior_campaign_sha256 is not None
    assert prior_attempt_path is not None
    try:
        campaign_path = _direct_root_file(prior_campaign_path, root)
        attempt_path = _direct_root_directory(prior_attempt_path, root)
        prior_manifest = _load_hash_locked_mapping(
            campaign_path,
            expected_prior_campaign_sha256,
            "PRIOR_ISOLATION_INVALID",
        )
        validated = validate_campaign_manifest(prior_manifest, evidence_root=root)
        if campaign_path.name != f"{validated['campaign_name']}.prepare.json":
            raise RecoveryError("PRIOR_ISOLATION_INVALID")
        started = native._read_json_file(attempt_path / "campaign-started.json")
        campaign_result_path = attempt_path / "campaign-result.json"
        campaign_result = native._read_json_file(campaign_result_path)
        expected_started_hash = hashlib.sha256(
            native._canonical_json(validated).encode("utf-8")
        ).hexdigest()
        if (
            not isinstance(started, Mapping)
            or started.get("campaign_manifest_sha256") != expected_started_hash
            or not isinstance(campaign_result, Mapping)
            or campaign_result.get("unknown_batch") is not None
        ):
            raise RecoveryError("PRIOR_ISOLATION_INVALID")
        completed_batches = campaign_result.get("completed_batches")
        failed_batch = campaign_result.get("failed_batch")
        if not isinstance(completed_batches, list) or (
            failed_batch is not None and not isinstance(failed_batch, Mapping)
        ):
            raise RecoveryError("PRIOR_ISOLATION_INVALID")
        terminal_batches = list(completed_batches)
        if isinstance(failed_batch, Mapping):
            terminal_batches.append(failed_batch)
        bindings = [dict(item) for item in validated.get("prior_known_isolations", [])]
        campaign_result_sha256 = _regular_file_sha256(campaign_result_path)
        for batch in terminal_batches:
            if not isinstance(batch, Mapping):
                raise RecoveryError("PRIOR_ISOLATION_INVALID")
            batch_id = batch.get("batch_id")
            terminal = batch.get("native_result")
            child = next(
                (
                    item
                    for item in validated["children"]
                    if item.get("batch_id") == batch_id
                ),
                None,
            )
            if not isinstance(child, Mapping) or not isinstance(terminal, Mapping):
                raise RecoveryError("PRIOR_ISOLATION_INVALID")
            child_path = _manifest_child_path(child.get("path"), root)
            validated_terminal = _validated_batch_invocation(
                {
                    "return_code": 0 if terminal.get("status") == "passed" else 1,
                    "batch_result": terminal,
                },
                child=child,
                child_path=child_path,
                digest=child["sha256"],
                batch_attempt=attempt_path / str(batch_id),
                identity=validated["execution_identity"],
            )
            if validated_terminal is None:
                raise RecoveryError("PRIOR_ISOLATION_INVALID")
            native_result = validated_terminal["result"]
            isolated = native_result.get("isolated", [])
            if not isinstance(isolated, list):
                raise RecoveryError("PRIOR_ISOLATION_INVALID")
            candidates: list[tuple[Mapping[str, Any], bool]] = []
            for item in isolated:
                if not isinstance(item, Mapping):
                    raise RecoveryError("PRIOR_ISOLATION_INVALID")
                candidates.append((item, True))
            stopping = native_result.get("failed")
            if isinstance(stopping, Mapping):
                candidates.append((stopping, False))
            frozen = _load_native_child(child_path, child["sha256"])
            units = frozen.get("units")
            if not isinstance(units, list):
                raise RecoveryError("PRIOR_ISOLATION_INVALID")
            native_attempt = Path(validated_terminal["attempt_dir"])
            for failed, declared_isolated in candidates:
                unit_indexes = [
                    index
                    for index, unit in enumerate(units)
                    if isinstance(unit, Mapping)
                    and _unit_payload_matches(failed, unit)
                ]
                if len(unit_indexes) != 1:
                    raise RecoveryError("PRIOR_ISOLATION_INVALID")
                unit_index = unit_indexes[0]
                unit = units[unit_index]
                assert isinstance(unit, Mapping)
                result = failed.get("result")
                if not isinstance(result, Mapping):
                    raise RecoveryError("PRIOR_ISOLATION_INVALID")
                unit_dir = native_attempt / (
                    f"unit-{unit_index + 1:03d}-{unit['symbol']}-{unit['contract']}"
                )
                safe_unit_dir = native._validated_direct_child_directory(
                    unit_dir,
                    native_attempt,
                    "PRIOR_ISOLATION_INVALID",
                )
                persisted_unit = native._read_json_file(
                    safe_unit_dir / "unit-result.json"
                )
                if persisted_unit != failed:
                    raise RecoveryError("PRIOR_ISOLATION_INVALID")
                try:
                    source_evidence = native._source_isolation_evidence(
                        safe_unit_dir,
                        unit,
                        result,
                        policy,
                        expected_parent=native_attempt,
                    )
                except RecoveryError:
                    if declared_isolated:
                        raise
                    continue
                source_count = cast(int, source_evidence["responses_saved"])
                evidence_artifacts = {
                    "unit_result_sha256": _regular_file_sha256(
                        safe_unit_dir / "unit-result.json"
                    ),
                    "journal_sha256": _regular_file_sha256(
                        safe_unit_dir / "journal.jsonl"
                    ),
                    "source_response_sha256s": {
                        f"source-response-{sequence:04d}.json": (
                            _regular_file_sha256(
                                safe_unit_dir / f"source-response-{sequence:04d}.json"
                            )
                        )
                        for sequence in range(1, source_count + 1)
                    },
                }
                unit_identity = {
                    key: unit[key]
                    for key in (
                        "symbol",
                        "contract",
                        "frequency",
                        "through",
                        "plan_sha256",
                    )
                }
                binding: dict[str, Any] = {
                    "schema_version": "newow_weekly_recovery_prior_isolation_v1",
                    "unit": unit_identity,
                    "classification": source_evidence["classification"],
                    "source_evidence": source_evidence,
                    "evidence_artifacts": evidence_artifacts,
                    "prior_campaign": {
                        "path": campaign_path.name,
                        "sha256": expected_prior_campaign_sha256,
                    },
                    "prior_campaign_result_sha256": campaign_result_sha256,
                    "prior_attempt_path": attempt_path.name,
                    "batch_id": batch_id,
                    "child_sha256": child["sha256"],
                    "unit_index": unit_index + 1,
                }
                binding["binding_sha256"] = _identity_sha256(binding)
                bindings.append(binding)
        if not bindings:
            raise RecoveryError("PRIOR_ISOLATION_INVALID")
        binding_hashes = [item.get("binding_sha256") for item in bindings]
        if len(set(binding_hashes)) != len(binding_hashes):
            raise RecoveryError("PRIOR_ISOLATION_INVALID")
        return bindings
    except (OSError, KeyError, StopIteration, TypeError, RecoveryError) as exc:
        raise RecoveryError("PRIOR_ISOLATION_INVALID") from exc


def _derive_source_only_isolations(
    root: Path,
    *,
    policy: Mapping[str, object] | None,
    source_prepared_path: Path | None,
    expected_source_prepared_sha256: str | None,
    source_attempt_path: Path | None,
    unit_index: int | None,
    request_index: int | None,
    expected_request_sha256: str | None,
) -> list[dict[str, Any]]:
    values = (
        source_prepared_path,
        expected_source_prepared_sha256,
        source_attempt_path,
        unit_index,
        request_index,
        expected_request_sha256,
    )
    if all(value is None for value in values):
        return []
    if policy is None or any(value is None for value in values):
        raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID")
    assert source_prepared_path is not None
    assert expected_source_prepared_sha256 is not None
    assert source_attempt_path is not None
    assert unit_index is not None
    assert request_index is not None
    assert expected_request_sha256 is not None
    try:
        if (
            isinstance(unit_index, bool)
            or unit_index < 0
            or isinstance(request_index, bool)
            or request_index < 0
            or _HASH.fullmatch(expected_request_sha256) is None
            or policy.get("allowed_error_codes") != ["RQDATA_ZERO_OHL_INVALID"]
        ):
            raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID")
        prepared_path = _direct_root_file(source_prepared_path, root)
        attempt_path = _direct_root_directory(source_attempt_path, root)
        prepared = native.load_prepared_manifest(
            prepared_path, expected_source_prepared_sha256
        )
        units = prepared.get("units")
        if not isinstance(units, list) or unit_index >= len(units):
            raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID")
        unit = units[unit_index]
        if not isinstance(unit, Mapping):
            raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID")
        source_payloads = unit.get("source_requests")
        if not isinstance(source_payloads, list) or request_index >= len(source_payloads):
            raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID")
        selected_request = native._source_request_from_payload(
            source_payloads[request_index]
        )
        request_payload = native._request_payload(selected_request)
        request_sha256 = hashlib.sha256(
            native._canonical_json(request_payload).encode("utf-8")
        ).hexdigest()
        if request_sha256 != expected_request_sha256:
            raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID")

        invocation_path = attempt_path / "invocation-receipt.json"
        result_path = attempt_path / "source-only-result.json"
        journal_path = attempt_path / "journal.jsonl"
        response_path = attempt_path / "source-response-0001.json"
        invocation = native._read_json_file(invocation_path)
        result = native._read_json_file(result_path)
        if not isinstance(invocation, Mapping) or not isinstance(result, Mapping):
            raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID")
        expected_identity = {
            key: prepared[key]
            for key in (
                "code_commit",
                "execution_code_sha256",
                "config_sha256",
                "canonical_root_sha256",
            )
        }
        expected_runner_sha256 = _source_runner_sha256_at_commit(
            cast(str, expected_identity["code_commit"])
        )
        if (
            invocation
            != {
                "schema_version": "newow_weekly_source_only_invocation_v1",
                "prepared_path": prepared_path.name,
                "prepared_sha256": expected_source_prepared_sha256,
                "request_sha256": expected_request_sha256,
                "attempt_id": attempt_path.name,
                **expected_identity,
                "runner_sha256": expected_runner_sha256,
                "provider_request_limit": 1,
                "retries_allowed": 0,
                "canonical_writes_allowed": False,
                "database_writes_allowed": False,
                "manager_apply_allowed": False,
            }
        ):
            raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID")
        outcome = native._validated_source_attempt_outcome(
            attempt_path, (selected_request,)
        )
        expected_unit = {
            key: unit[key]
            for key in ("symbol", "contract", "frequency", "through", "plan_sha256")
        }
        if (
            result.get("schema_version") != "newow_weekly_source_only_result_v1"
            or result.get("status") != "completed"
            or result.get("classification")
            != "SOURCE_RESPONSE_SAVED_REVIEW_REQUIRED"
            or result.get("source_error_code") != "RQDATA_ZERO_OHL_INVALID"
            or result.get("prepared_sha256") != expected_source_prepared_sha256
            or result.get("request_sha256") != expected_request_sha256
            or result.get("unit_identity") != expected_unit
            or native._canonical_json(result.get("attempt"))
            != native._canonical_json(outcome)
            or type(result.get("provider_request_limit")) is not int
            or result.get("provider_request_limit") != 1
            or type(result.get("retries")) is not int
            or result.get("retries") != 0
            or type(result.get("canonical_writes")) is not int
            or result.get("canonical_writes") != 0
            or type(result.get("database_writes")) is not int
            or result.get("database_writes") != 0
            or result.get("manager_apply") is not False
            or outcome
            != {
                "state": "failed",
                "outcome_unknown": False,
                "retry_allowed": False,
                "requests_started": 1,
                "responses_saved": 1,
            }
        ):
            raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID")
        response = native._read_source_payload(
            response_path, _regular_file_sha256(response_path)
        )
        rows = response.get("rows")
        if (
            set(response) != {"schema_version", "request", "rows"}
            or response.get("schema_version") != 1
            or response.get("request") != request_payload
            or not isinstance(rows, list)
            or any(not isinstance(row, dict) for row in rows)
        ):
            raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID")
        typed_rows = tuple(cast(dict[str, Any], row) for row in rows)
        native._validate_response_identity(selected_request, typed_rows)
        anomaly_rows: list[dict[str, Any]] = []
        replayed_codes: set[str] = set()
        for row in typed_rows:
            try:
                native._normalize_exchange_daily_zero_volume_row(row)
            except Exception as exc:  # noqa: BLE001 - exact allowlist replay only
                code = native._error_code(exc)
                if code != "RQDATA_ZERO_OHL_INVALID":
                    raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID") from exc
                replayed_codes.add(code)
                anomaly_rows.append(dict(row))
        if replayed_codes != {"RQDATA_ZERO_OHL_INVALID"} or not anomaly_rows:
            raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID")
        source_evidence: dict[str, Any] = {
            "classification": "RQDATA_ZERO_OHL_INVALID",
            "requests_started": 1,
            "responses_saved": 1,
            "request_sha256": expected_request_sha256,
            "response_sha256": _regular_file_sha256(response_path),
            "anomaly_rows": anomaly_rows,
        }
        source_evidence["evidence_sha256"] = _identity_sha256(source_evidence)
        binding: dict[str, Any] = {
            "schema_version": "newow_weekly_source_only_isolation_v1",
            "unit": expected_unit,
            "classification": "RQDATA_ZERO_OHL_INVALID",
            "source_evidence": source_evidence,
            "source_prepared": {
                "path": prepared_path.name,
                "sha256": expected_source_prepared_sha256,
            },
            "source_attempt_path": attempt_path.name,
            "unit_index": unit_index,
            "request_index": request_index,
            "request_sha256": expected_request_sha256,
            "evidence_artifacts": {
                "invocation_receipt_sha256": _regular_file_sha256(invocation_path),
                "journal_sha256": _regular_file_sha256(journal_path),
                "source_result_sha256": _regular_file_sha256(result_path),
                "source_response_sha256": _regular_file_sha256(response_path),
            },
        }
        binding["binding_sha256"] = _identity_sha256(binding)
        return [binding]
    except (OSError, KeyError, TypeError, RecoveryError) as exc:
        raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID") from exc


def _source_runner_sha256_at_commit(code_commit: str) -> str:
    if _COMMIT.fullmatch(code_commit) is None:
        raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID")
    project_root = Path(__file__).resolve().parents[1]
    try:
        completed = subprocess.run(
            [
                "git",
                "show",
                f"{code_commit}:scripts/newow_weekly_source_verify.py",
            ],
            cwd=project_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID") from exc
    return hashlib.sha256(completed.stdout).hexdigest()


def _direct_root_file(value: Path, root: Path) -> Path:
    path = Path(value)
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise RecoveryError("PRIOR_ISOLATION_INVALID") from exc
    if (
        not path.is_absolute()
        or resolved.parent != root
        or not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
    ):
        raise RecoveryError("PRIOR_ISOLATION_INVALID")
    return resolved


def _direct_root_directory(value: Path, root: Path) -> Path:
    path = Path(value)
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise RecoveryError("PRIOR_ISOLATION_INVALID") from exc
    if (
        not path.is_absolute()
        or resolved.parent != root
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
    ):
        raise RecoveryError("PRIOR_ISOLATION_INVALID")
    return resolved


def _regular_file_sha256(path: Path) -> str:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024 * 1024:
                raise OSError
            content = os.read(fd, 16 * 1024 * 1024 + 1)
            if len(content) != info.st_size:
                raise OSError
        finally:
            os.close(fd)
    except OSError as exc:
        raise RecoveryError("PRIOR_ISOLATION_INVALID") from exc
    return hashlib.sha256(content).hexdigest()


def prepare_campaign(
    report: Mapping[str, Any],
    *,
    report_sha256: str,
    evidence_root: Path,
    execution_identity: Mapping[str, str],
    invoke_batch: Callable[[tuple[dict[str, Any], ...], str, Path], Mapping[str, Any]],
    name: str = "campaign",
    continuation_policy: Mapping[str, Any] | None = None,
    prior_campaign_path: Path | None = None,
    expected_prior_campaign_sha256: str | None = None,
    prior_attempt_path: Path | None = None,
    source_only_prepared_path: Path | None = None,
    expected_source_only_prepared_sha256: str | None = None,
    source_only_attempt_path: Path | None = None,
    source_only_unit_index: int | None = None,
    source_only_request_index: int | None = None,
    expected_source_only_request_sha256: str | None = None,
    partial_source_exception_attempt_path: Path | None = None,
    observe_partial_committed: Callable[
        [Mapping[str, Any], list[dict[str, Any]]], Mapping[str, Any]
    ]
    | None = None,
) -> dict[str, Any]:
    """Prepare every native child and exclusively freeze their campaign index."""
    root = _validated_evidence_root(evidence_root)
    if _HASH.fullmatch(report_sha256) is None:
        raise RecoveryError("CAMPAIGN_REPORT_INVALID")
    identity = _validated_execution_identity(execution_identity)
    policy = native._validated_continuation_policy(continuation_policy)
    prior_isolations = _derive_prior_isolations(
        root,
        policy=policy,
        prior_campaign_path=prior_campaign_path,
        expected_prior_campaign_sha256=expected_prior_campaign_sha256,
        prior_attempt_path=prior_attempt_path,
    )
    source_only_isolations = _derive_source_only_isolations(
        root,
        policy=policy,
        source_prepared_path=source_only_prepared_path,
        expected_source_prepared_sha256=expected_source_only_prepared_sha256,
        source_attempt_path=source_only_attempt_path,
        unit_index=source_only_unit_index,
        request_index=source_only_request_index,
        expected_request_sha256=expected_source_only_request_sha256,
    )
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name) is None:
        raise RecoveryError("CAMPAIGN_PATH_INVALID")
    campaign_path = root / f"{name}.prepare.json"
    if campaign_path.exists() or campaign_path.is_symlink():
        raise RecoveryError("CAMPAIGN_MANIFEST_EXISTS")

    targets, excluded = _validated_report_targets(report)
    prior_keys = {
        (
            item["unit"]["symbol"],
            item["unit"]["contract"],
            item["unit"]["frequency"],
            item["unit"]["through"],
            item["unit"]["plan_sha256"],
        )
        for item in prior_isolations
    }
    source_only_keys = {
        (
            item["unit"]["symbol"],
            item["unit"]["contract"],
            item["unit"]["frequency"],
            item["unit"]["through"],
            item["unit"]["plan_sha256"],
        )
        for item in source_only_isolations
    }
    proposed = [item for item in targets if item["status"] == "PROPOSED"]
    fresh_keys = [
        (
            item["symbol"],
            item["contract"],
            item["frequency"],
            item["through"],
            item["plan_sha256"],
        )
        for item in proposed
    ]
    if not prior_keys.issubset(fresh_keys) or len(prior_keys) != len(prior_isolations):
        raise RecoveryError("PRIOR_ISOLATION_INVALID")
    if (
        not source_only_keys.issubset(fresh_keys)
        or len(source_only_keys) != len(source_only_isolations)
        or prior_keys & source_only_keys
    ):
        raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID")
    isolation_keys = prior_keys | source_only_keys
    carried_partial_exceptions = _carried_partial_source_exceptions(
        root,
        prior_campaign_path=prior_campaign_path,
        expected_prior_campaign_sha256=expected_prior_campaign_sha256,
        current_identity=identity,
        fresh_units=proposed,
        observe_committed=observe_partial_committed,
    )
    partial_exceptions = carried_partial_exceptions + _derive_partial_source_exceptions(
        root,
        current_identity=identity,
        attempt_path=partial_source_exception_attempt_path,
        fresh_units=proposed,
        observe_committed=observe_partial_committed,
    )
    partial_keys = {
        (
            item["symbol"],
            item["contract"],
            item["frequency"],
            item["through"],
        )
        for item in partial_exceptions
    }
    if len(partial_keys) != len(partial_exceptions):
        raise RecoveryError(partial_exception.ERROR_CODE)
    isolation_identities = {
        (symbol, contract, frequency, through)
        for symbol, contract, frequency, through, _plan in isolation_keys
    }
    if partial_keys & isolation_identities:
        raise RecoveryError(partial_exception.ERROR_CODE)
    executable_units = tuple(
        {
            "symbol": item["symbol"],
            "contract": item["contract"],
            "through": item["through"],
            "frequency": "1w",
            "expected_plan_sha256": item["plan_sha256"],
        }
        for item, key in zip(proposed, fresh_keys, strict=True)
        if key not in isolation_keys
        and (item["symbol"], item["contract"], item["frequency"], item["through"])
        not in partial_keys
    )
    batches = tuple(
        tuple(executable_units[index : index + 20])
        for index in range(0, len(executable_units), 20)
    )
    children: list[dict[str, Any]] = []
    artifact_prefix = _campaign_artifact_prefix(name, report_sha256)
    writer_guard = _prepare_writer_guard(root, identity["canonical_root_sha256"])
    for index, units in enumerate(batches, start=1):
        batch_id = f"batch-{index:03d}"
        artifact_id = f"{artifact_prefix}-{batch_id}"
        response = invoke_batch(units, artifact_id, root)
        if not isinstance(response, Mapping):
            raise RecoveryError("CAMPAIGN_CHILD_INVALID")
        if (
            response.get("status") != "prepared"
            or response.get("readonly") is not True
            or response.get("provider_requests") != 0
            or response.get("writes") != 0
            or response.get("unit_count") != len(units)
        ):
            raise RecoveryError("CAMPAIGN_CHILD_INVALID")
        child_path = _callback_child_path(
            response.get("prepared_file"), root, artifact_id
        )
        digest = response.get("prepared_sha256")
        if not isinstance(digest, str) or _HASH.fullmatch(digest) is None:
            raise RecoveryError("CAMPAIGN_CHILD_INVALID")
        child = _load_native_child(child_path, digest)
        if child.get("continuation_policy") != policy:
            raise RecoveryError("CONTINUATION_POLICY_INVALID")
        summaries = _validate_native_child(
            child,
            expected_units=units,
            expected_identity=identity,
        )
        children.append(
            {
                "batch_id": batch_id,
                "artifact_id": artifact_id,
                "path": child_path.relative_to(root).as_posix(),
                "sha256": digest,
                "unit_count": len(summaries),
                "target_count": sum(item["target_count"] for item in summaries),
                "expected_bar_count": sum(
                    item["expected_bar_count"] for item in summaries
                ),
                "units": summaries,
            }
        )

    manifest: dict[str, Any] = {
        "schema_version": _CAMPAIGN_SCHEMA,
        "status": "prepared" if proposed else "completed",
        "readonly": True,
        "provider_requests": 0,
        "writes": 0,
        "evidence_root_sha256": _path_sha256(root),
        "campaign_name": name,
        "artifact_prefix": artifact_prefix,
        "writer_guard": writer_guard,
        "execution_identity": identity,
        "audit": {
            "sha256": report_sha256,
            "schema_version": report["schema_version"],
            "as_of": report["as_of"],
            "frequency_scope": list(report["frequency_scope"]),
            "matrix": report["matrix"],
        },
        "scope": {
            "included_status_counts": {
                "PROPOSED": sum(item["status"] == "PROPOSED" for item in targets)
            },
            "excluded_status_counts": dict(sorted(excluded.items())),
            "metadata_proposal_count": len(report["metadata_proposals"]),
            "denominator_unit_count": len(proposed),
            "execution_unit_count": len(executable_units),
            "prior_known_isolation_count": len(prior_isolations),
            "source_only_known_isolation_count": len(source_only_isolations),
            "prior_partial_source_exception_count": len(partial_exceptions),
            "unit_identity_sha256": _identity_sha256(
                [unit for child in children for unit in child["units"]]
            ),
            "target_identity_sha256": _identity_sha256(
                [
                    unit["target_identity_sha256"]
                    for child in children
                    for unit in child["units"]
                ]
            ),
        },
        "children": children,
        "prior_known_isolations": prior_isolations,
        "source_only_known_isolations": source_only_isolations,
        "prior_partial_source_exceptions": partial_exceptions,
        "totals": {
            "batch_count": len(children),
            "unit_count": sum(child["unit_count"] for child in children),
            "target_count": sum(child["target_count"] for child in children),
            "expected_bar_count": sum(
                child["expected_bar_count"] for child in children
            ),
        },
    }
    if policy is not None:
        manifest["continuation_policy"] = policy
    validate_campaign_manifest(manifest, evidence_root=root)
    try:
        native._write_json_exclusive(campaign_path, manifest)
    except FileExistsError as exc:
        raise RecoveryError("CAMPAIGN_MANIFEST_EXISTS") from exc
    except OSError as exc:
        raise RecoveryError("CAMPAIGN_MANIFEST_UNAVAILABLE") from exc
    return manifest


def validate_campaign_manifest(
    manifest: Mapping[str, Any],
    *,
    evidence_root: Path,
) -> dict[str, Any]:
    """Verify the complete ordered child set without opening any data source."""
    root = _validated_evidence_root(evidence_root)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != _CAMPAIGN_SCHEMA
    ):
        raise RecoveryError("CAMPAIGN_MANIFEST_INVALID")
    if (
        manifest.get("readonly") is not True
        or manifest.get("provider_requests") != 0
        or manifest.get("writes") != 0
        or manifest.get("evidence_root_sha256") != _path_sha256(root)
    ):
        raise RecoveryError("CAMPAIGN_MANIFEST_INVALID")
    identity = _validated_execution_identity(manifest.get("execution_identity"))
    policy = native._validated_continuation_policy(manifest.get("continuation_policy"))
    prior_isolations = manifest.get("prior_known_isolations", [])
    source_only_isolations = manifest.get("source_only_known_isolations", [])
    partial_exceptions = manifest.get("prior_partial_source_exceptions", [])
    children = manifest.get("children")
    totals = manifest.get("totals")
    audit = manifest.get("audit")
    scope = manifest.get("scope")
    campaign_name = manifest.get("campaign_name")
    artifact_prefix = manifest.get("artifact_prefix")
    if (
        not isinstance(audit, dict)
        or not isinstance(campaign_name, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", campaign_name) is None
        or artifact_prefix
        != _campaign_artifact_prefix(campaign_name, str(audit.get("sha256", "")))
    ):
        raise RecoveryError("CAMPAIGN_MANIFEST_INVALID")
    _validate_writer_guard(
        root,
        manifest.get("writer_guard"),
        identity["canonical_root_sha256"],
    )
    if (
        not isinstance(children, list)
        or not isinstance(totals, dict)
        or not isinstance(audit, dict)
        or not isinstance(scope, dict)
        or not isinstance(prior_isolations, list)
        or not isinstance(source_only_isolations, list)
        or not isinstance(partial_exceptions, list)
        or ((prior_isolations or source_only_isolations) and policy is None)
        or _HASH.fullmatch(str(audit.get("sha256", ""))) is None
        or audit.get("frequency_scope") != ["1w"]
        or audit.get("matrix") is not False
        or not isinstance(scope.get("included_status_counts"), dict)
        or not isinstance(scope.get("excluded_status_counts"), dict)
        or not isinstance(scope.get("metadata_proposal_count"), int)
        or _HASH.fullmatch(str(scope.get("unit_identity_sha256", ""))) is None
        or _HASH.fullmatch(str(scope.get("target_identity_sha256", ""))) is None
    ):
        raise RecoveryError("CAMPAIGN_MANIFEST_INVALID")
    expected_ids = [f"batch-{index:03d}" for index in range(1, len(children) + 1)]
    if [
        child.get("batch_id") if isinstance(child, dict) else None for child in children
    ] != expected_ids:
        raise RecoveryError("CAMPAIGN_CHILD_INVALID")

    seen: set[tuple[str, str, str]] = set()
    actual_totals = {
        "batch_count": len(children),
        "unit_count": 0,
        "target_count": 0,
        "expected_bar_count": 0,
    }
    for child_index in children:
        batch_id = child_index.get("batch_id")
        artifact_id = child_index.get("artifact_id")
        if artifact_id != f"{artifact_prefix}-{batch_id}":
            raise RecoveryError("CAMPAIGN_CHILD_INVALID")
        child_path = _manifest_child_path(child_index.get("path"), root)
        if child_path.name != f"{artifact_id}.prepare.json":
            raise RecoveryError("CAMPAIGN_CHILD_INVALID")
        digest = child_index.get("sha256")
        if not isinstance(digest, str) or _HASH.fullmatch(digest) is None:
            raise RecoveryError("CAMPAIGN_CHILD_INVALID")
        native_child = _load_native_child(child_path, digest)
        if native_child.get("continuation_policy") != policy:
            raise RecoveryError("CONTINUATION_POLICY_INVALID")
        expected_units = child_index.get("units")
        if not isinstance(expected_units, list):
            raise RecoveryError("CAMPAIGN_CHILD_INVALID")
        summaries = _validate_native_child(
            native_child,
            expected_units=tuple(expected_units),
            expected_identity=identity,
            summaries_are_campaign_units=True,
        )
        if summaries != expected_units:
            raise RecoveryError("CAMPAIGN_CHILD_INVALID")
        for unit in summaries:
            unit_key = (unit["symbol"], unit["contract"], unit["frequency"])
            if unit_key in seen:
                raise RecoveryError("CAMPAIGN_SCOPE_CONFLICT")
            seen.add(unit_key)
        derived = {
            "unit_count": len(summaries),
            "target_count": sum(item["target_count"] for item in summaries),
            "expected_bar_count": sum(item["expected_bar_count"] for item in summaries),
        }
        if any(child_index.get(key) != value for key, value in derived.items()):
            raise RecoveryError("CAMPAIGN_CHILD_INVALID")
        for key, value in derived.items():
            actual_totals[key] += value
    if totals != actual_totals:
        raise RecoveryError("CAMPAIGN_MANIFEST_INVALID")
    validated_prior: list[dict[str, Any]] = []
    validated_source_only: list[dict[str, Any]] = []
    derived_prior_hashes: set[str] = set()
    isolated_unit_keys: set[tuple[str, str, str, str, str]] = set()
    executable_unit_keys = {
        (
            unit["symbol"],
            unit["contract"],
            unit["frequency"],
            unit["through"],
            unit["plan_sha256"],
        )
        for child in children
        for unit in child["units"]
    }
    for binding in prior_isolations:
        if not isinstance(binding, Mapping):
            raise RecoveryError("PRIOR_ISOLATION_INVALID")
        prior_campaign = binding.get("prior_campaign")
        if not isinstance(prior_campaign, Mapping):
            raise RecoveryError("PRIOR_ISOLATION_INVALID")
        derived_prior = _derive_prior_isolations(
            root,
            policy=policy,
            prior_campaign_path=root / str(prior_campaign.get("path")),
            expected_prior_campaign_sha256=cast(str, prior_campaign.get("sha256")),
            prior_attempt_path=root / str(binding.get("prior_attempt_path")),
        )
        if binding not in derived_prior:
            raise RecoveryError("PRIOR_ISOLATION_INVALID")
        derived_prior_hashes.update(
            str(item.get("binding_sha256")) for item in derived_prior
        )
        prior_unit = binding.get("unit")
        if not isinstance(prior_unit, Mapping):
            raise RecoveryError("PRIOR_ISOLATION_INVALID")
        prior_key_values = tuple(
            prior_unit.get(key)
            for key in ("symbol", "contract", "frequency", "through", "plan_sha256")
        )
        if (
            not all(isinstance(value, str) for value in prior_key_values)
            or prior_key_values in isolated_unit_keys
            or prior_key_values in executable_unit_keys
        ):
            raise RecoveryError("PRIOR_ISOLATION_INVALID")
        isolated_unit_keys.add(
            cast(tuple[str, str, str, str, str], prior_key_values)
        )
        validated_prior.append(dict(binding))
    if derived_prior_hashes != {
        str(item.get("binding_sha256"))
        for item in prior_isolations
        if isinstance(item, Mapping)
    }:
        raise RecoveryError("PRIOR_ISOLATION_INVALID")
    for binding in source_only_isolations:
        if not isinstance(binding, Mapping):
            raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID")
        source_prepared = binding.get("source_prepared")
        if not isinstance(source_prepared, Mapping):
            raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID")
        derived_source = _derive_source_only_isolations(
            root,
            policy=policy,
            source_prepared_path=root / str(source_prepared.get("path")),
            expected_source_prepared_sha256=cast(
                str, source_prepared.get("sha256")
            ),
            source_attempt_path=root / str(binding.get("source_attempt_path")),
            unit_index=cast(int, binding.get("unit_index")),
            request_index=cast(int, binding.get("request_index")),
            expected_request_sha256=cast(str, binding.get("request_sha256")),
        )
        if derived_source != [binding]:
            raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID")
        source_unit = binding.get("unit")
        if not isinstance(source_unit, Mapping):
            raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID")
        source_key_values = tuple(
            source_unit.get(key)
            for key in ("symbol", "contract", "frequency", "through", "plan_sha256")
        )
        if (
            not all(isinstance(value, str) for value in source_key_values)
            or source_key_values in isolated_unit_keys
            or source_key_values in executable_unit_keys
        ):
            raise RecoveryError("SOURCE_ONLY_ISOLATION_INVALID")
        isolated_unit_keys.add(
            cast(tuple[str, str, str, str, str], source_key_values)
        )
        validated_source_only.extend(derived_source)
    validated_partial: list[dict[str, Any]] = []
    if partial_exceptions:
        if any(not isinstance(item, Mapping) for item in partial_exceptions):
            raise RecoveryError(partial_exception.ERROR_CODE)
        derived_partial = _derive_partial_source_exceptions(
            root,
            current_identity=identity,
            attempt_path=root / str(partial_exceptions[0].get("failed_attempt_path")),
            fresh_units=[
                {
                    "symbol": item.get("symbol"),
                    "contract": item.get("contract"),
                    "frequency": item.get("frequency"),
                    "through": item.get("through"),
                    "plan_sha256": item.get("fresh_replan_sha256"),
                    "targets": item.get("remaining_targets"),
                }
                for item in partial_exceptions
            ],
            observe_committed=None,
            stored_bindings=partial_exceptions,
        )
        if derived_partial != list(partial_exceptions):
            raise RecoveryError(partial_exception.ERROR_CODE)
        executable_identities = {
            (
                unit["symbol"],
                unit["contract"],
                unit["frequency"],
                unit["through"],
            )
            for child in children
            for unit in child["units"]
        }
        seen_partial: set[tuple[object, object, object, object]] = set()
        for binding in derived_partial:
            identity_key = (
                binding["symbol"],
                binding["contract"],
                binding["frequency"],
                binding["through"],
            )
            if (
                identity_key in seen_partial
                or identity_key in executable_identities
                or binding.get("classification")
                != partial_exception.CLASSIFICATION
                or binding.get("frequency") != "1w"
            ):
                raise RecoveryError(partial_exception.ERROR_CODE)
            seen_partial.add(identity_key)
        validated_partial = derived_partial
    included = scope["included_status_counts"]
    denominator = (
        len(seen)
        + len(validated_prior)
        + len(validated_source_only)
        + len(validated_partial)
    )
    if included != {"PROPOSED": denominator}:
        raise RecoveryError("CAMPAIGN_MANIFEST_INVALID")
    expected_status = "prepared" if denominator else "completed"
    if manifest.get("status") != expected_status:
        raise RecoveryError("CAMPAIGN_MANIFEST_INVALID")
    if (
        scope.get("denominator_unit_count") != denominator
        or scope.get("execution_unit_count") != len(seen)
        or scope.get("prior_known_isolation_count", 0) != len(validated_prior)
        or scope.get("source_only_known_isolation_count", 0)
        != len(validated_source_only)
        or scope.get("prior_partial_source_exception_count", 0)
        != len(validated_partial)
    ):
        raise RecoveryError("CAMPAIGN_MANIFEST_INVALID")
    flattened = [unit for child in children for unit in child["units"]]
    if scope["unit_identity_sha256"] != _identity_sha256(flattened) or scope[
        "target_identity_sha256"
    ] != _identity_sha256([unit["target_identity_sha256"] for unit in flattened]):
        raise RecoveryError("CAMPAIGN_MANIFEST_INVALID")
    return dict(manifest)


def _validated_report_targets(
    report: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    if not isinstance(report, Mapping):
        raise RecoveryError("CAMPAIGN_REPORT_INVALID")
    if any(report.get(key) != value for key, value in _REPORT_REQUIRED.items()):
        raise RecoveryError("CAMPAIGN_REPORT_INVALID")
    if not _REPORT_STRUCTURAL.issubset(report):
        raise RecoveryError("CAMPAIGN_REPORT_INVALID")
    try:
        as_of = datetime.fromisoformat(report["as_of"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RecoveryError("CAMPAIGN_REPORT_INVALID") from exc
    repair_targets = report.get("repair_targets")
    metadata = report.get("metadata_proposals")
    if (
        as_of.tzinfo is None
        or not isinstance(repair_targets, list)
        or not isinstance(metadata, list)
    ):
        raise RecoveryError("CAMPAIGN_REPORT_INVALID")
    repair_identities: set[tuple[str, str, str]] = set()
    for raw in repair_targets:
        if not isinstance(raw, Mapping):
            continue
        identity = (raw.get("symbol"), raw.get("contract"), raw.get("frequency"))
        if not all(isinstance(item, str) for item in identity):
            continue
        typed_identity = cast(tuple[str, str, str], identity)
        if typed_identity in repair_identities:
            raise RecoveryError("CAMPAIGN_SCOPE_CONFLICT")
        repair_identities.add(typed_identity)
    _validate_native_report_sections(report, as_of=as_of)
    parsed: list[dict[str, Any]] = []
    excluded: Counter[str] = Counter()
    seen: dict[tuple[str, str, str], tuple[str, str]] = {}
    for raw in repair_targets:
        if not isinstance(raw, Mapping):
            raise RecoveryError("CAMPAIGN_REPORT_INVALID")
        try:
            symbol = raw["symbol"]
            contract = raw["contract"]
            frequency = raw["frequency"]
            through = raw["through"]
            requested_through = raw["requested_through"]
            plan_sha256 = raw["plan_sha256"]
            status_value = raw["status"]
            parsed_through = date.fromisoformat(through)
        except (KeyError, TypeError, ValueError) as exc:
            raise RecoveryError("CAMPAIGN_REPORT_INVALID") from exc
        if (
            not isinstance(symbol, str)
            or _SYMBOL.fullmatch(symbol) is None
            or not isinstance(contract, str)
            or _CONTRACT.fullmatch(contract) is None
            or not contract.startswith(symbol.upper())
            or frequency != "1w"
            or not isinstance(through, str)
            or requested_through != through
            or not isinstance(status_value, str)
            or not status_value
            or (
                status_value == "PROPOSED"
                and (
                    not isinstance(plan_sha256, str)
                    or _HASH.fullmatch(plan_sha256) is None
                )
            )
            or (
                status_value != "PROPOSED"
                and plan_sha256 is not None
                and (
                    not isinstance(plan_sha256, str)
                    or _HASH.fullmatch(plan_sha256) is None
                )
            )
            or parsed_through > as_of.date()
        ):
            raise RecoveryError("CAMPAIGN_REPORT_INVALID")
        key = (symbol, contract, frequency)
        value_identity = (through, plan_sha256)
        if key in seen:
            raise RecoveryError("CAMPAIGN_SCOPE_CONFLICT")
        seen[key] = value_identity
        item = dict(raw)
        parsed.append(item)
        if status_value != "PROPOSED":
            excluded[status_value] += 1
    parsed.sort(key=lambda item: (item["symbol"], item["contract"], item["frequency"]))
    return parsed, excluded


def _validate_native_report_sections(
    report: Mapping[str, Any],
    *,
    as_of: datetime,
) -> None:
    """Require the complete native matrix-false readiness payload."""
    try:
        operational = tuple(load_operational_products())
    except (OSError, ValueError, TypeError) as exc:
        raise RecoveryError("CAMPAIGN_REPORT_INVALID") from exc
    enumerations = report.get("enumerations")
    dependencies = report.get("dependencies")
    repairs = report.get("repair_targets")
    cases = report.get("cases")
    product_count = report.get("product_count")
    main_case_count = report.get("main_case_count")
    main_ready_count = report.get("main_ready_count")
    if (
        not operational
        or not isinstance(product_count, int)
        or isinstance(product_count, bool)
        or product_count != len(operational)
        or not isinstance(main_case_count, int)
        or isinstance(main_case_count, bool)
        or main_case_count != 0
        or not isinstance(main_ready_count, int)
        or isinstance(main_ready_count, bool)
        or main_ready_count != 0
        or cases != []
        or not isinstance(enumerations, list)
        or not isinstance(dependencies, list)
        or not isinstance(repairs, list)
    ):
        raise RecoveryError("CAMPAIGN_REPORT_INVALID")
    expected_enumerations = {
        (symbol, "1w", section)
        for symbol in operational
        for section in _REPORT_SECTIONS
    }
    actual_enumerations: set[tuple[str, str, str]] = set()
    enumeration_owner_counts: dict[tuple[str, str], int] = {}
    for raw in enumerations:
        if not isinstance(raw, Mapping):
            raise RecoveryError("CAMPAIGN_REPORT_INVALID")
        key = (raw.get("symbol"), raw.get("frequency"), raw.get("section"))
        if key not in expected_enumerations or key in actual_enumerations:
            raise RecoveryError("CAMPAIGN_REPORT_INVALID")
        actual_enumerations.add(key)
        if raw.get("as_of") != as_of.isoformat():
            raise RecoveryError("CAMPAIGN_REPORT_INVALID")
        deferred_reason = deferred_section_reason(cast(_SectionName, key[2]))
        if deferred_reason is not None:
            if raw.get("status") != "UNOPENED" or raw.get("reason") != deferred_reason:
                raise RecoveryError("CAMPAIGN_REPORT_INVALID")
            continue
        try:
            since = date.fromisoformat(raw["since"])
            through = date.fromisoformat(raw["through"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RecoveryError("CAMPAIGN_REPORT_INVALID") from exc
        owner_count = raw.get("owner_count")
        if (
            raw.get("status") != "ENUMERATED"
            or since > through
            or through > as_of.date()
            or not isinstance(owner_count, int)
            or isinstance(owner_count, bool)
            or owner_count < 0
        ):
            raise RecoveryError("CAMPAIGN_REPORT_INVALID")
        enumeration_owner_counts[(key[0], key[2])] = owner_count
    if actual_enumerations != expected_enumerations:
        raise RecoveryError("CAMPAIGN_REPORT_INVALID")

    dependency_identities: set[tuple[str, str, str, str, str]] = set()
    covered_owners: dict[tuple[str, str], set[tuple[str, str, str]]] = {}
    covered_owner_counts: Counter[tuple[str, str]] = Counter()
    repair_through: dict[tuple[str, str, str], str] = {}
    repair_consumers: dict[tuple[str, str, str], set[tuple[str, str, str]]] = {}
    operational_set = set(operational)
    for raw in dependencies:
        if not isinstance(raw, Mapping):
            raise RecoveryError("CAMPAIGN_REPORT_INVALID")
        try:
            symbol = raw["symbol"]
            contract = raw["contract"]
            through = date.fromisoformat(raw["through"])
            dependency_as_of = datetime.fromisoformat(raw["as_of"])
            consumers = raw["consumers"]
            owners = raw["owners"]
        except (KeyError, TypeError, ValueError) as exc:
            raise RecoveryError("CAMPAIGN_REPORT_INVALID") from exc
        status_value = raw.get("status")
        dependency_identity = (
            symbol,
            contract,
            str(raw.get("frequency")),
            raw["through"],
            raw["as_of"],
        )
        if (
            not isinstance(symbol, str)
            or symbol not in operational_set
            or not isinstance(contract, str)
            or _CONTRACT.fullmatch(contract) is None
            or not contract.startswith(symbol.upper())
            or raw.get("frequency") != "1w"
            or status_value
            not in {
                "DATA_READY",
                "DATA_UNAVAILABLE",
                "NOT_APPLICABLE",
                "SOURCE_EXCEPTION",
            }
            or through > as_of.date()
            or dependency_as_of.tzinfo is None
            or dependency_as_of > as_of
            or not isinstance(consumers, list)
            or not consumers
            or not isinstance(owners, list)
            or not owners
        ):
            raise RecoveryError("CAMPAIGN_REPORT_INVALID")
        if dependency_identity in dependency_identities:
            raise RecoveryError("CAMPAIGN_REPORT_INVALID")
        dependency_identities.add(dependency_identity)
        if status_value == "DATA_READY":
            try:
                cutoff = datetime.fromisoformat(raw["cutoff"])
                actual_count = raw["actual_bar_count"]
                expected_count = raw["expected_bar_count"]
            except (KeyError, TypeError, ValueError) as exc:
                raise RecoveryError("CAMPAIGN_REPORT_INVALID") from exc
            if (
                cutoff.tzinfo is None
                or not isinstance(actual_count, int)
                or isinstance(actual_count, bool)
                or actual_count < 0
                or not isinstance(expected_count, int)
                or isinstance(expected_count, bool)
                or expected_count < 0
            ):
                raise RecoveryError("CAMPAIGN_REPORT_INVALID")
        elif (
            not isinstance(raw.get("reason"), str)
            or not raw.get("reason")
            or (
                status_value in {"DATA_UNAVAILABLE", "SOURCE_EXCEPTION"}
                and (
                    not isinstance(raw.get("error"), Mapping)
                    or not isinstance(raw["error"].get("code"), str)
                    or not raw["error"].get("code")
                )
            )
        ):
            raise RecoveryError("CAMPAIGN_REPORT_INVALID")
        consumer_identities: set[tuple[str, str, str]] = set()
        consumer_sections: set[str] = set()
        for consumer in consumers:
            if (
                not isinstance(consumer, Mapping)
                or consumer.get("frequency") != "1w"
                or consumer.get("section") not in {"chart", "auxiliary", "reference"}
                or not isinstance(consumer.get("strategy"), str)
            ):
                raise RecoveryError("CAMPAIGN_REPORT_INVALID")
            consumer_identity = (
                consumer["strategy"],
                consumer["frequency"],
                consumer["section"],
            )
            if consumer_identity in consumer_identities:
                raise RecoveryError("CAMPAIGN_REPORT_INVALID")
            consumer_identities.add(consumer_identity)
            consumer_sections.add(consumer["section"])
        expected_consumers = {
            (strategy.value, "1w", section)
            for section in consumer_sections
            for strategy in ProductStrategy
        }
        if consumer_identities != expected_consumers:
            raise RecoveryError("CAMPAIGN_REPORT_INVALID")
        owner_identities: set[tuple[str, str, str]] = set()
        for owner in owners:
            if not isinstance(owner, Mapping):
                raise RecoveryError("CAMPAIGN_REPORT_INVALID")
            try:
                owner_since = date.fromisoformat(owner["since"])
                owner_through = date.fromisoformat(owner["through"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RecoveryError("CAMPAIGN_REPORT_INVALID") from exc
            owner_identity = (contract, owner["since"], owner["through"])
            if (
                owner_since > owner_through
                or owner_through != through
                or owner_identity in owner_identities
            ):
                raise RecoveryError("CAMPAIGN_REPORT_INVALID")
            owner_identities.add(owner_identity)
        for section in consumer_sections:
            coverage_key = (symbol, section)
            covered_owners.setdefault(coverage_key, set()).update(owner_identities)
            covered_owner_counts[coverage_key] += len(owner_identities)
        dependency_key = (symbol, contract, "1w")
        if raw.get("reason") in native_readiness._DOWNLOAD:
            previous_through = repair_through.get(dependency_key)
            if previous_through is None or raw["through"] > previous_through:
                repair_through[dependency_key] = raw["through"]
            repair_consumers.setdefault(dependency_key, set()).update(
                consumer_identities
            )

    if any(
        len(covered_owners.get(key, set())) != owner_count
        or covered_owner_counts[key] != owner_count
        for key, owner_count in enumeration_owner_counts.items()
    ):
        raise RecoveryError("CAMPAIGN_REPORT_INVALID")

    actual_repair_keys: set[tuple[str, str, str]] = set()
    for repair in repairs:
        if not isinstance(repair, Mapping):
            raise RecoveryError("CAMPAIGN_REPORT_INVALID")
        repair_key = (
            repair.get("symbol"),
            repair.get("contract"),
            repair.get("frequency"),
        )
        consumers = repair.get("consumers")
        if (
            not all(isinstance(item, str) for item in repair_key)
            or repair_key not in repair_through
            or repair.get("through") != repair_through[repair_key]
            or not isinstance(consumers, list)
        ):
            raise RecoveryError("CAMPAIGN_REPORT_INVALID")
        try:
            actual_consumers = {
                (item["strategy"], item["frequency"], item["section"])
                for item in consumers
                if isinstance(item, Mapping)
            }
        except (KeyError, TypeError) as exc:
            raise RecoveryError("CAMPAIGN_REPORT_INVALID") from exc
        if (
            len(actual_consumers) != len(consumers)
            or actual_consumers != repair_consumers[repair_key]
        ):
            raise RecoveryError("CAMPAIGN_REPORT_INVALID")
        actual_repair_keys.add(cast(tuple[str, str, str], repair_key))
    if actual_repair_keys != set(repair_through):
        raise RecoveryError("CAMPAIGN_REPORT_INVALID")
    expected_work = (
        sum(deferred_section_reason(section) is None for section in _REPORT_SECTIONS)
        * len(operational)
        + len(dependencies)
        + len(repairs)
    )
    work_used = report.get("work_used")
    if (
        not isinstance(work_used, int)
        or isinstance(work_used, bool)
        or work_used != expected_work
    ):
        raise RecoveryError("CAMPAIGN_REPORT_INVALID")


def _validated_execution_identity(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise RecoveryError("CAMPAIGN_IDENTITY_INVALID")
    keys = {
        "code_commit",
        "execution_code_sha256",
        "config_sha256",
        "canonical_root_sha256",
    }
    if set(value) != keys:
        raise RecoveryError("CAMPAIGN_IDENTITY_INVALID")
    result = {key: value[key] for key in keys}
    if (
        not isinstance(result["code_commit"], str)
        or _COMMIT.fullmatch(result["code_commit"]) is None
        or any(
            not isinstance(result[key], str) or _HASH.fullmatch(result[key]) is None
            for key in keys - {"code_commit"}
        )
    ):
        raise RecoveryError("CAMPAIGN_IDENTITY_INVALID")
    return result


def _validated_evidence_root(value: Path) -> Path:
    root = Path(value)
    try:
        info = root.lstat()
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise RecoveryError("CAMPAIGN_OUTPUT_ROOT_UNSAFE") from exc
    if (
        not root.is_absolute()
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or resolved != root
    ):
        raise RecoveryError("CAMPAIGN_OUTPUT_ROOT_UNSAFE")
    return resolved


def _callback_child_path(value: object, root: Path, batch_id: str) -> Path:
    if not isinstance(value, str):
        raise RecoveryError("CAMPAIGN_CHILD_INVALID")
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise RecoveryError("CAMPAIGN_CHILD_INVALID") from exc
    if resolved.parent != root or resolved.name != f"{batch_id}.prepare.json":
        raise RecoveryError("CAMPAIGN_CHILD_INVALID")
    return resolved


def _manifest_child_path(value: object, root: Path) -> Path:
    if not isinstance(value, str):
        raise RecoveryError("CAMPAIGN_CHILD_INVALID")
    relative = Path(value)
    if relative.is_absolute() or len(relative.parts) != 1 or relative.name != value:
        raise RecoveryError("CAMPAIGN_CHILD_INVALID")
    path = root / relative
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise RecoveryError("CAMPAIGN_CHILD_INVALID") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or resolved.parent != root
    ):
        raise RecoveryError("CAMPAIGN_CHILD_INVALID")
    return resolved


def _load_native_child(path: Path, digest: str) -> dict[str, Any]:
    try:
        return native.load_prepared_manifest(path, digest)
    except RecoveryError as exc:
        raise RecoveryError("CAMPAIGN_CHILD_INVALID") from exc


def _validate_native_child(
    child: Mapping[str, Any],
    *,
    expected_units: tuple[dict[str, Any], ...],
    expected_identity: Mapping[str, str],
    summaries_are_campaign_units: bool = False,
) -> list[dict[str, Any]]:
    if child.get("schema_version") != "newow_weekly_recovery_prepare_v1" or any(
        child.get(key) != value for key, value in expected_identity.items()
    ):
        raise RecoveryError("CAMPAIGN_CHILD_INVALID")
    units = child.get("units")
    if (
        not isinstance(units, list)
        or not 1 <= len(units) <= 20
        or child.get("unit_count") != len(units)
        or len(units) != len(expected_units)
    ):
        raise RecoveryError("CAMPAIGN_CHILD_INVALID")
    summaries: list[dict[str, Any]] = []
    for raw, expected in zip(units, expected_units, strict=True):
        if not isinstance(raw, Mapping):
            raise RecoveryError("CAMPAIGN_CHILD_INVALID")
        expected_plan_key = (
            "plan_sha256" if summaries_are_campaign_units else "expected_plan_sha256"
        )
        try:
            target_count = raw["target_count"]
            expected_bar_count = raw["expected_bar_count"]
            targets = raw["targets"]
            target_summaries = _validated_target_summaries(targets, raw)
            summary = {
                "symbol": raw["symbol"],
                "contract": raw["contract"],
                "frequency": raw["frequency"],
                "through": raw["through"],
                "plan_sha256": raw["plan_sha256"],
                "target_count": target_count,
                "expected_bar_count": expected_bar_count,
                "target_identity_sha256": _identity_sha256(target_summaries),
            }
        except (KeyError, TypeError) as exc:
            raise RecoveryError("CAMPAIGN_CHILD_INVALID") from exc
        if (
            not isinstance(target_count, int)
            or isinstance(target_count, bool)
            or target_count < 0
            or not isinstance(expected_bar_count, int)
            or isinstance(expected_bar_count, bool)
            or expected_bar_count < 0
            or not isinstance(targets, list)
            or len(targets) != target_count
            or expected_bar_count
            != sum(item["expected_bar_count"] for item in target_summaries)
            or any(
                summary[key] != expected[key]
                for key in ("symbol", "contract", "frequency", "through")
            )
            or summary["plan_sha256"] != expected[expected_plan_key]
        ):
            raise RecoveryError("CAMPAIGN_CHILD_INVALID")
        summaries.append(summary)
    return summaries


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()


def _campaign_artifact_prefix(name: str, report_sha256: str) -> str:
    digest_prefix = _identity_sha256(
        {"campaign_name": name, "report_sha256": report_sha256}
    )[:16]
    return f"{name[:32]}-{digest_prefix}"


def _identity_sha256(value: object) -> str:
    return hashlib.sha256(native._canonical_json(value).encode("utf-8")).hexdigest()


def _validated_target_summaries(
    targets: object,
    unit: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(targets, list):
        raise RecoveryError("CAMPAIGN_CHILD_INVALID")
    summaries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for target in targets:
        if not isinstance(target, Mapping):
            raise RecoveryError("CAMPAIGN_CHILD_INVALID")
        try:
            dataset = target["dataset"]
            year = target["year"]
            month = target["month"]
            expected_start = target["expected_start"]
            expected_end = target["expected_end"]
            expected_count = target["expected_bar_count"]
            start = datetime.fromisoformat(expected_start)
            end = datetime.fromisoformat(expected_end)
        except (KeyError, TypeError, ValueError) as exc:
            raise RecoveryError("CAMPAIGN_CHILD_INVALID") from exc
        if (
            not isinstance(dataset, list)
            or len(dataset) != 4
            or dataset[:3] != ["contract", unit["symbol"], unit["contract"]]
            or dataset[3] not in {"1d", "1w"}
            or not isinstance(year, int)
            or isinstance(year, bool)
            or not isinstance(month, int)
            or isinstance(month, bool)
            or not 1 <= month <= 12
            or not isinstance(expected_start, str)
            or not isinstance(expected_end, str)
            or start.tzinfo is None
            or end.tzinfo is None
            or start > end
            or not isinstance(expected_count, int)
            or isinstance(expected_count, bool)
            or expected_count <= 0
        ):
            raise RecoveryError("CAMPAIGN_CHILD_INVALID")
        summary = {
            "dataset": dataset,
            "year": year,
            "month": month,
            "expected_start": expected_start,
            "expected_end": expected_end,
            "expected_bar_count": expected_count,
        }
        encoded = native._canonical_json(summary)
        if encoded in seen:
            raise RecoveryError("CAMPAIGN_SCOPE_CONFLICT")
        seen.add(encoded)
        summaries.append(summary)
    return summaries


def _load_hash_locked_mapping(
    path: Path, digest: str, error_code: str
) -> dict[str, Any]:
    try:
        return native.load_prepared_manifest(path, digest)
    except RecoveryError as exc:
        raise RecoveryError(error_code) from exc


def _decoded_mapping(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RecoveryError("CAMPAIGN_CHILD_INVALID") from exc
    if not isinstance(payload, dict):
        raise RecoveryError("CAMPAIGN_CHILD_INVALID")
    return payload


def _validated_batch_invocation(
    value: object,
    *,
    child: Mapping[str, Any],
    child_path: Path,
    digest: str,
    batch_attempt: Path,
    identity: Mapping[str, str],
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return_code = value.get("return_code")
    result = value.get("batch_result")
    if (
        not isinstance(return_code, int)
        or isinstance(return_code, bool)
        or not isinstance(result, Mapping)
        or result.get("schema_version") != "newow_weekly_recovery_result_v1"
        or result.get("readonly") is not False
        or result.get("status") not in {"passed", "partial", "failed"}
        or not isinstance(result.get("result"), Mapping)
        or result["result"].get("status") != result.get("status")
        or result["result"].get("retries") != 0
    ):
        return None
    if (return_code == 0) != (result.get("status") == "passed"):
        return None
    attempt_value = result.get("attempt_dir")
    if not isinstance(attempt_value, str):
        return None
    native_attempt_value = Path(attempt_value)
    try:
        validated_batch_attempt = native._validated_direct_child_directory(
            batch_attempt,
            batch_attempt.parent,
            "CAMPAIGN_EVIDENCE_PATH_INVALID",
        )
        nested_attempt = batch_attempt / "native"
        if native_attempt_value == batch_attempt:
            native_attempt = validated_batch_attempt
        elif native_attempt_value == nested_attempt:
            native_attempt = native._validated_direct_child_directory(
                nested_attempt,
                batch_attempt,
                "CAMPAIGN_EVIDENCE_PATH_INVALID",
            )
        else:
            return None
    except RecoveryError:
        return None
    try:
        receipt = native._read_json_file(native_attempt / "invocation-receipt.json")
        persisted_result = native._read_json_file(native_attempt / "batch-result.json")
        frozen = _load_native_child(child_path, digest)
    except RecoveryError:
        return None
    expected_receipt = {
        "schema_version": "newow_weekly_recovery_invocation_v1",
        "prepared_sha256": digest,
        **identity,
        "unit_count": child.get("unit_count"),
    }
    policy = native._validated_continuation_policy(frozen.get("continuation_policy"))
    if policy is not None:
        expected_receipt["continuation_policy_sha256"] = policy["policy_sha256"]
    native_result = result["result"]
    frozen_units = frozen.get("units")
    if (
        receipt != expected_receipt
        or persisted_result != native_result
        or not isinstance(frozen_units, list)
        or len(frozen_units) != child.get("unit_count")
        or not _validated_native_terminal(
            native_result,
            frozen_units,
            native_attempt=native_attempt,
            continuation_policy=policy,
        )
    ):
        return None
    return dict(result)


def _validated_native_terminal(
    result: Mapping[str, Any],
    frozen_units: list[dict[str, Any]],
    *,
    native_attempt: Path,
    continuation_policy: Mapping[str, object] | None = None,
) -> bool:
    completed = result.get("completed")
    isolated = result.get("isolated", [])
    failed = result.get("failed")
    unattempted = result.get("unattempted")
    status_value = result.get("status")
    if (
        not isinstance(completed, list)
        or not isinstance(isolated, list)
        or not isinstance(unattempted, list)
        or len(completed) + len(isolated) > len(frozen_units)
        or (continuation_policy is None and isolated)
    ):
        return False
    frozen_indexes = {_unit_key(unit): index for index, unit in enumerate(frozen_units)}
    if len(frozen_indexes) != len(frozen_units):
        return False
    settled_indexes: set[int] = set()
    for completed_unit in completed:
        index = frozen_indexes.get(_unit_key(completed_unit))
        if index is None or index in settled_indexes:
            return False
        frozen_unit = frozen_units[index]
        unit_dir = native_attempt / (
            f"unit-{index + 1:03d}-{frozen_unit['symbol']}-{frozen_unit['contract']}"
        )
        if not _completed_unit_matches(completed_unit, frozen_unit, unit_dir):
            return False
        settled_indexes.add(index)
    for isolated_unit in isolated:
        index = frozen_indexes.get(_unit_key(isolated_unit))
        if index is None or index in settled_indexes:
            return False
        frozen_unit = frozen_units[index]
        unit_dir = native_attempt / (
            f"unit-{index + 1:03d}-{frozen_unit['symbol']}-{frozen_unit['contract']}"
        )
        if not _isolated_unit_matches(
            isolated_unit,
            frozen_unit,
            unit_dir,
            continuation_policy,
        ):
            return False
        settled_indexes.add(index)
    if status_value == "passed":
        return (
            settled_indexes == set(range(len(frozen_units)))
            and not isolated
            and failed is None
            and unattempted == []
        )
    if failed is None:
        return (
            status_value == "partial"
            and bool(isolated)
            and settled_indexes == set(range(len(frozen_units)))
            and unattempted == []
        )
    failure_index = len(settled_indexes)
    if (
        not isinstance(failed, Mapping)
        or failure_index >= len(frozen_units)
        or settled_indexes != set(range(failure_index))
    ):
        return False
    failed_unit = frozen_units[failure_index]
    if not _unit_payload_matches(failed, failed_unit):
        return False
    failure_status = failed.get("status")
    nested_result = failed.get("result")
    if not isinstance(failure_status, str) or not failure_status:
        return False
    if "result" in failed and not isinstance(nested_result, Mapping):
        return False
    applied = (
        nested_result.get("applied", 0) if isinstance(nested_result, Mapping) else 0
    )
    if not isinstance(applied, int) or isinstance(applied, bool) or applied < 0:
        return False
    derived = native._batch_result(
        [{} for _item in completed],
        dict(failed),
        [],
        isolated=[{} for _item in isolated],
    )
    if status_value != derived["status"]:
        return False
    expected_unattempted = frozen_units[failure_index + 1 :]
    return len(unattempted) == len(expected_unattempted) and all(
        _unit_payload_matches(actual, expected)
        for actual, expected in zip(unattempted, expected_unattempted, strict=True)
    )


def _native_failed_unit_outcome(
    terminal: Mapping[str, Any],
    *,
    child_path: Path,
    digest: str,
) -> Literal["known", "unknown"] | None:
    native_result = terminal.get("result")
    if not isinstance(native_result, Mapping):
        return None
    completed = native_result.get("completed")
    isolated = native_result.get("isolated", [])
    failed = native_result.get("failed")
    if (
        not isinstance(completed, list)
        or not isinstance(isolated, list)
        or not isinstance(failed, Mapping)
    ):
        return None
    try:
        frozen = _load_native_child(child_path, digest)
        units = frozen["units"]
        unit_index = len(completed) + len(isolated)
        unit = units[unit_index]
        native_attempt = Path(terminal["attempt_dir"])
        unit_dir = native_attempt / (
            f"unit-{unit_index + 1:03d}-{unit['symbol']}-{unit['contract']}"
        )
    except (KeyError, IndexError, TypeError, RecoveryError):
        return None
    return _failed_unit_evidence_outcome(
        failed,
        unit,
        unit_dir=unit_dir,
        native_attempt=native_attempt,
    )


def _failed_unit_evidence_outcome(
    failed: Mapping[str, Any],
    frozen: Mapping[str, Any],
    *,
    unit_dir: Path,
    native_attempt: Path,
) -> Literal["known", "unknown"] | None:
    if not _unit_payload_matches(failed, frozen):
        return None
    attempt = failed.get("attempt")
    if not isinstance(attempt, Mapping) or set(attempt) != {
        "state",
        "outcome_unknown",
        "retry_allowed",
        "requests_started",
        "responses_saved",
    }:
        return None
    started = attempt.get("requests_started")
    saved = attempt.get("responses_saved")
    if (
        not isinstance(started, int)
        or isinstance(started, bool)
        or started < 0
        or not isinstance(saved, int)
        or isinstance(saved, bool)
        or saved < 0
        or saved > started
        or attempt.get("retry_allowed") is not False
        or not isinstance(attempt.get("outcome_unknown"), bool)
    ):
        return None
    try:
        safe_unit = native._validated_direct_child_directory(
            unit_dir,
            native_attempt,
            "CAMPAIGN_EVIDENCE_PATH_INVALID",
        )
        persisted = native._read_json_file(safe_unit / "unit-result.json")
        source_payloads = frozen.get("source_requests")
        if not isinstance(source_payloads, list):
            return None
        frozen_requests = tuple(
            native._source_request_from_payload(item) for item in source_payloads
        )
        actual_attempt = native._validated_source_attempt_outcome(
            safe_unit,
            frozen_requests,
        )
    except (OSError, TypeError, RecoveryError):
        return None
    if persisted != failed or actual_attempt != dict(attempt):
        return None
    if (
        attempt["outcome_unknown"] is True
        or failed.get("error_code") in _UNKNOWN_UNIT_ERROR_CODES
    ):
        return "unknown"
    return "known"


def _unit_key(value: object) -> tuple[object, object, object]:
    if not isinstance(value, Mapping):
        return (None, None, None)
    result = (value.get("symbol"), value.get("contract"), value.get("frequency"))
    if not all(isinstance(item, str) for item in result):
        return (None, None, None)
    return result


def _isolated_unit_matches(
    value: object,
    frozen: Mapping[str, Any],
    unit_dir: Path,
    policy: Mapping[str, object] | None,
) -> bool:
    if (
        policy is None
        or not _unit_payload_matches(value, frozen)
        or not isinstance(value, Mapping)
        or value.get("status") != "isolated"
        or not isinstance(value.get("result"), Mapping)
        or not isinstance(value.get("source_evidence"), Mapping)
        or not isinstance(value.get("readback"), Mapping)
    ):
        return False
    try:
        safe_unit = native._validated_direct_child_directory(
            unit_dir,
            unit_dir.parent,
            "CAMPAIGN_EVIDENCE_PATH_INVALID",
        )
        source_evidence = native._source_isolation_evidence(
            safe_unit,
            frozen,
            value["result"],
            policy,
            expected_parent=unit_dir.parent,
        )
        persisted = native._read_json_file(safe_unit / "unit-result.json")
    except RecoveryError:
        return False
    targets = frozen.get("targets")
    readback = value["readback"]
    expected_readback = {
        "status": "passed",
        "plan_sha256": frozen.get("plan_sha256"),
        "remaining_target_count": frozen.get("target_count"),
        "target_identity_sha256": _identity_sha256(targets),
    }
    return (
        source_evidence == value["source_evidence"]
        and value.get("classification") == source_evidence["classification"]
        and readback == expected_readback
        and persisted == value
    )


def _unit_payload_matches(value: object, frozen: Mapping[str, Any]) -> bool:
    return isinstance(value, Mapping) and all(
        value.get(key) == expected for key, expected in frozen.items()
    )


def _completed_unit_matches(
    value: object,
    frozen: Mapping[str, Any],
    unit_dir: Path,
) -> bool:
    if not _unit_payload_matches(value, frozen):
        return False
    assert isinstance(value, Mapping)
    readback = value.get("readback")
    completion_status = value.get("status")
    result = value.get("result")
    source_requests = frozen.get("source_requests")
    if (
        completion_status not in {"passed", "noop"}
        or not isinstance(result, Mapping)
        or result.get("status") != completion_status
        or not isinstance(source_requests, list)
    ):
        return False
    source_request_count = len(source_requests)
    target_count = frozen.get("target_count")
    if not isinstance(target_count, int) or isinstance(target_count, bool):
        return False
    if completion_status == "noop":
        expected_provider_requests = 0
        expected_source_requests = 0
        if source_requests:
            return False
    else:
        expected_provider_requests = target_count if source_requests else 0
        expected_source_requests = source_request_count
    provider_requests = result.get("provider_requests")
    return (
        isinstance(provider_requests, int)
        and not isinstance(provider_requests, bool)
        and provider_requests == expected_provider_requests
        and _validated_completed_attempt(
            value.get("attempt"),
            unit_dir=unit_dir,
            expected_requests=expected_source_requests,
        )
        and value.get("remaining_target_count") == 0
        and isinstance(readback, Mapping)
        and readback.get("catalog_physical_mds") == "passed"
        and readback.get("mds_target_count") == frozen.get("target_count")
    )


def _validated_completed_attempt(
    value: object,
    *,
    unit_dir: Path,
    expected_requests: int,
) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "state",
        "outcome_unknown",
        "retry_allowed",
        "requests_started",
        "responses_saved",
    }:
        return False
    started = value.get("requests_started")
    saved = value.get("responses_saved")
    expected_state = "not_started" if expected_requests == 0 else "response_saved"
    if (
        value.get("state") != expected_state
        or value.get("outcome_unknown") is not False
        or value.get("retry_allowed") is not False
        or not isinstance(started, int)
        or isinstance(started, bool)
        or started < 0
        or not isinstance(saved, int)
        or isinstance(saved, bool)
        or saved < 0
        or started != saved
        or started != expected_requests
    ):
        return False
    journal_path = unit_dir / "journal.jsonl"
    try:
        unit_info = unit_dir.lstat()
        journal_info = journal_path.lstat()
        resolved_unit = unit_dir.resolve(strict=True)
        actual = native.read_attempt_outcome(unit_dir)
    except (OSError, RecoveryError):
        return False
    return (
        stat.S_ISDIR(unit_info.st_mode)
        and not stat.S_ISLNK(unit_info.st_mode)
        and resolved_unit == unit_dir
        and stat.S_ISREG(journal_info.st_mode)
        and not stat.S_ISLNK(journal_info.st_mode)
        and actual == value
    )


def _revalidate_child(
    child: Mapping[str, Any],
    *,
    identity: Mapping[str, str],
    root: Path,
) -> None:
    child_path = _manifest_child_path(child.get("path"), root)
    digest = child.get("sha256")
    if not isinstance(digest, str) or _HASH.fullmatch(digest) is None:
        raise RecoveryError("CAMPAIGN_CHILD_INVALID")
    native_child = _load_native_child(child_path, digest)
    expected_units = child.get("units")
    if not isinstance(expected_units, list):
        raise RecoveryError("CAMPAIGN_CHILD_INVALID")
    summaries = _validate_native_child(
        native_child,
        expected_units=tuple(expected_units),
        expected_identity=identity,
        summaries_are_campaign_units=True,
    )
    if summaries != expected_units:
        raise RecoveryError("CAMPAIGN_CHILD_INVALID")


def _guard_path(root: Path, canonical_root_sha256: str) -> Path:
    if _HASH.fullmatch(canonical_root_sha256) is None:
        raise RecoveryError("CAMPAIGN_IDENTITY_INVALID")
    return root / f".campaign-writer-{canonical_root_sha256}.lock"


def _guard_binding(path: Path, info: os.stat_result) -> dict[str, Any]:
    return {
        "path": path.name,
        "device": info.st_dev,
        "inode": info.st_ino,
    }


def _prepare_writer_guard(root: Path, canonical_root_sha256: str) -> dict[str, Any]:
    path = _guard_path(root, canonical_root_sha256)
    flags = os.O_RDWR | os.O_NOFOLLOW
    try:
        try:
            fd = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
            native._fsync_directory(root)
        except FileExistsError:
            fd = os.open(path, flags)
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
        ):
            raise OSError
        entry = path.lstat()
        if entry.st_dev != info.st_dev or entry.st_ino != info.st_ino:
            raise OSError
        return _guard_binding(path, info)
    except OSError as exc:
        raise RecoveryError("CAMPAIGN_GUARD_UNAVAILABLE") from exc
    finally:
        if "fd" in locals():
            os.close(fd)


def _validate_writer_guard(
    root: Path,
    value: object,
    canonical_root_sha256: str,
) -> dict[str, Any]:
    expected_path = _guard_path(root, canonical_root_sha256)
    if not isinstance(value, Mapping) or set(value) != {"path", "device", "inode"}:
        raise RecoveryError("CAMPAIGN_GUARD_CHANGED")
    device = value.get("device")
    inode = value.get("inode")
    if (
        value.get("path") != expected_path.name
        or not isinstance(device, int)
        or isinstance(device, bool)
        or not isinstance(inode, int)
        or isinstance(inode, bool)
    ):
        raise RecoveryError("CAMPAIGN_GUARD_CHANGED")
    try:
        info = expected_path.lstat()
    except OSError as exc:
        raise RecoveryError("CAMPAIGN_GUARD_CHANGED") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or info.st_dev != device
        or info.st_ino != inode
    ):
        raise RecoveryError("CAMPAIGN_GUARD_CHANGED")
    return dict(value)


@contextmanager
def _campaign_writer_guard(root: Path, binding: Mapping[str, Any]):
    path = root / str(binding.get("path"))
    try:
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_dev != binding.get("device")
            or info.st_ino != binding.get("inode")
        ):
            raise RecoveryError("CAMPAIGN_GUARD_CHANGED")
        _validate_writer_guard(
            root,
            binding,
            path.name.removeprefix(".campaign-writer-").removesuffix(".lock"),
        )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RecoveryError("CAMPAIGN_ALREADY_RUNNING") from exc
    except RecoveryError:
        if "fd" in locals():
            os.close(fd)
        raise
    except OSError as exc:
        if "fd" in locals():
            os.close(fd)
        raise RecoveryError("CAMPAIGN_GUARD_CHANGED") from exc
    try:
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _inspect_attempt(path: Path) -> dict[str, Any]:
    attempt = Path(path)
    try:
        info = attempt.lstat()
    except OSError as exc:
        raise RecoveryError("CAMPAIGN_ATTEMPT_INVALID") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RecoveryError("CAMPAIGN_ATTEMPT_INVALID")
    result_path = attempt / "campaign-result.json"
    if result_path.exists():
        result = native._read_json_file(result_path)
        if not isinstance(result, dict):
            raise RecoveryError("CAMPAIGN_ATTEMPT_INVALID")
        return result
    started = native._read_json_file(attempt / "campaign-started.json")
    if not isinstance(started, dict):
        raise RecoveryError("CAMPAIGN_ATTEMPT_INVALID")
    return {
        "status": "unknown",
        "error_code": "CAMPAIGN_RESULT_MISSING",
        "started": started,
        "retries": 0,
    }


def _current_execution_identity(project_env: Path) -> dict[str, str]:
    commit = native._current_code_commit()
    native._require_clean_execution_checkout(commit)
    _settings, private_identity = native.load_private_execution_settings(project_env)
    return {
        "code_commit": commit,
        "execution_code_sha256": native._current_execution_code_sha256(),
        **private_identity,
    }


if __name__ == "__main__":
    raise SystemExit(main())
