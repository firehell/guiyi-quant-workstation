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
import sys
from typing import Any, Callable, Mapping

from scripts import newow_weekly_recovery as native


RecoveryError = native.RecoveryError

_CAMPAIGN_SCHEMA = "newow_weekly_recovery_campaign_v1"
_HASH = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SYMBOL = re.compile(r"[a-z]{1,8}")
_CONTRACT = re.compile(r"[A-Z]{1,8}[0-9]{3,4}")
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
                return_code = native.main(
                    [
                        "prepare",
                        "--project-env",
                        str(args.project_env),
                        "--units",
                        str(units_path),
                        "--output-root",
                        str(evidence_root),
                        "--name",
                        batch_id,
                    ],
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
    with _campaign_writer_guard(root, identity["canonical_root_sha256"]):
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
        failed: dict[str, Any] | None = None
        unknown: dict[str, Any] | None = None
        stopped_index = len(children)
        for index, child in enumerate(children):
            batch_id = child["batch_id"]
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
            terminal = _validated_batch_invocation(invocation)
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
            if terminal["status"] != "passed":
                failed = {"batch_id": batch_id, "native_result": terminal}
                stopped_index = index
                break
            completed.append({"batch_id": batch_id, "native_result": terminal})

        unattempted = [
            child["batch_id"] for child in children[stopped_index + 1 :]
        ]
        if unknown is not None:
            status = "unknown"
        elif failed is not None:
            native_status = (
                failed.get("native_result", {}).get("status")
                if isinstance(failed.get("native_result"), Mapping)
                else None
            )
            status = "partial" if completed or native_status == "partial" else "failed"
        else:
            status = "passed"
            unattempted = []
        result: dict[str, Any] = {
            "status": status,
            "completed_batch_ids": [item["batch_id"] for item in completed],
            "completed_batches": completed,
            "failed_batch": failed,
            "unknown_batch": unknown,
            "unattempted_batch_ids": unattempted,
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


def prepare_campaign(
    report: Mapping[str, Any],
    *,
    report_sha256: str,
    evidence_root: Path,
    execution_identity: Mapping[str, str],
    invoke_batch: Callable[
        [tuple[dict[str, Any], ...], str, Path], Mapping[str, Any]
    ],
    name: str = "campaign",
) -> dict[str, Any]:
    """Prepare every native child and exclusively freeze their campaign index."""
    root = _validated_evidence_root(evidence_root)
    if _HASH.fullmatch(report_sha256) is None:
        raise RecoveryError("CAMPAIGN_REPORT_INVALID")
    identity = _validated_execution_identity(execution_identity)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name) is None:
        raise RecoveryError("CAMPAIGN_PATH_INVALID")
    campaign_path = root / f"{name}.prepare.json"
    if campaign_path.exists() or campaign_path.is_symlink():
        raise RecoveryError("CAMPAIGN_MANIFEST_EXISTS")

    targets, excluded = _validated_report_targets(report)
    batches = partition_ordinary_units(report)
    children: list[dict[str, Any]] = []
    for index, units in enumerate(batches, start=1):
        batch_id = f"batch-{index:03d}"
        response = invoke_batch(units, batch_id, root)
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
        child_path = _callback_child_path(response.get("prepared_file"), root, batch_id)
        digest = response.get("prepared_sha256")
        if not isinstance(digest, str) or _HASH.fullmatch(digest) is None:
            raise RecoveryError("CAMPAIGN_CHILD_INVALID")
        child = _load_native_child(child_path, digest)
        summaries = _validate_native_child(
            child,
            expected_units=units,
            expected_identity=identity,
        )
        children.append(
            {
                "batch_id": batch_id,
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
        "status": "prepared" if children else "completed",
        "readonly": True,
        "provider_requests": 0,
        "writes": 0,
        "evidence_root_sha256": _path_sha256(root),
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
        "totals": {
            "batch_count": len(children),
            "unit_count": sum(child["unit_count"] for child in children),
            "target_count": sum(child["target_count"] for child in children),
            "expected_bar_count": sum(
                child["expected_bar_count"] for child in children
            ),
        },
    }
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
    if not isinstance(manifest, dict) or manifest.get("schema_version") != _CAMPAIGN_SCHEMA:
        raise RecoveryError("CAMPAIGN_MANIFEST_INVALID")
    if (
        manifest.get("readonly") is not True
        or manifest.get("provider_requests") != 0
        or manifest.get("writes") != 0
        or manifest.get("evidence_root_sha256") != _path_sha256(root)
    ):
        raise RecoveryError("CAMPAIGN_MANIFEST_INVALID")
    identity = _validated_execution_identity(manifest.get("execution_identity"))
    children = manifest.get("children")
    totals = manifest.get("totals")
    audit = manifest.get("audit")
    scope = manifest.get("scope")
    if (
        not isinstance(children, list)
        or not isinstance(totals, dict)
        or not isinstance(audit, dict)
        or not isinstance(scope, dict)
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
    if [child.get("batch_id") if isinstance(child, dict) else None for child in children] != expected_ids:
        raise RecoveryError("CAMPAIGN_CHILD_INVALID")

    seen: set[tuple[str, str, str]] = set()
    actual_totals = {
        "batch_count": len(children),
        "unit_count": 0,
        "target_count": 0,
        "expected_bar_count": 0,
    }
    for child_index in children:
        child_path = _manifest_child_path(child_index.get("path"), root)
        digest = child_index.get("sha256")
        if not isinstance(digest, str) or _HASH.fullmatch(digest) is None:
            raise RecoveryError("CAMPAIGN_CHILD_INVALID")
        native_child = _load_native_child(child_path, digest)
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
            "expected_bar_count": sum(
                item["expected_bar_count"] for item in summaries
            ),
        }
        if any(child_index.get(key) != value for key, value in derived.items()):
            raise RecoveryError("CAMPAIGN_CHILD_INVALID")
        for key, value in derived.items():
            actual_totals[key] += value
    if totals != actual_totals:
        raise RecoveryError("CAMPAIGN_MANIFEST_INVALID")
    expected_status = "prepared" if children else "completed"
    if manifest.get("status") != expected_status:
        raise RecoveryError("CAMPAIGN_MANIFEST_INVALID")
    included = scope["included_status_counts"]
    if included != {"PROPOSED": len(seen)}:
        raise RecoveryError("CAMPAIGN_MANIFEST_INVALID")
    flattened = [unit for child in children for unit in child["units"]]
    if (
        scope["unit_identity_sha256"] != _identity_sha256(flattened)
        or scope["target_identity_sha256"]
        != _identity_sha256(
            [unit["target_identity_sha256"] for unit in flattened]
        )
    ):
        raise RecoveryError("CAMPAIGN_MANIFEST_INVALID")
    return dict(manifest)


def _validated_report_targets(
    report: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    if not isinstance(report, Mapping):
        raise RecoveryError("CAMPAIGN_REPORT_INVALID")
    if any(report.get(key) != value for key, value in _REPORT_REQUIRED.items()):
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


def _load_hash_locked_mapping(path: Path, digest: str, error_code: str) -> dict[str, Any]:
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


def _validated_batch_invocation(value: object) -> dict[str, Any] | None:
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
    return dict(result)


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


@contextmanager
def _campaign_writer_guard(root: Path, canonical_root_sha256: str):
    if _HASH.fullmatch(canonical_root_sha256) is None:
        raise RecoveryError("CAMPAIGN_IDENTITY_INVALID")
    path = root / f".campaign-writer-{canonical_root_sha256}.lock"
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
        ):
            raise OSError
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
        raise RecoveryError("CAMPAIGN_GUARD_UNAVAILABLE") from exc
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
