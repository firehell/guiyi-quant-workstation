"""Execute one hash-bound exchange-daily source observation without data writes."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
from typing import Any, Mapping

from app.db.readonly import readonly_transaction
from app.market_data.domain import BarFrequency, DatasetKey, DatasetKind
from app.market_data.historical_data_manager import (
    BarFetchRequest,
    ContractWarmupRequest,
)
from app.market_data.rqdata_adapter import ExchangeDailySourceRequest
from scripts.newow_weekly_recovery import (
    AttemptJournal,
    RecoveryError,
    _canonical_json,
    _current_code_commit,
    _current_execution_code_sha256,
    _error_code,
    _open_execution_environment,
    _request_payload,
    _require_clean_execution_checkout,
    _require_execution_identity,
    _source_request_from_payload,
    _write_json_exclusive,
    create_attempt_directory,
    load_prepared_manifest,
    load_private_execution_settings,
    read_attempt_outcome,
)


_HASH = re.compile(r"[0-9a-f]{64}")
_ATTEMPT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


@dataclass(frozen=True, slots=True)
class SourceSelection:
    unit: Mapping[str, Any]
    request: ExchangeDailySourceRequest
    request_payload: Mapping[str, Any]


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Observe one frozen daily-source request without applying data."
    )
    commands = value.add_subparsers(dest="mode", required=True)
    for name in ("preflight", "execute"):
        command = commands.add_parser(name, allow_abbrev=False)
        command.add_argument("--project-env", required=True)
        command.add_argument("--prepared", required=True)
        command.add_argument("--expected-prepared-sha256", required=True)
        command.add_argument("--unit-index", required=True, type=int)
        command.add_argument("--request-index", required=True, type=int)
        command.add_argument("--expected-request-sha256", required=True)
        command.add_argument("--output-root", required=True)
        command.add_argument("--attempt-id", required=True)
        if name == "execute":
            command.add_argument(
                "--execute-source-query", action="store_true", required=True
            )
    return value


def validate_selection(
    manifest: Mapping[str, Any],
    *,
    current_execution_code_sha256: str,
    unit_index: int,
    request_index: int,
    expected_request_sha256: str,
) -> SourceSelection:
    """Bind one request to the prepared manifest and current execution digest."""
    if manifest.get("execution_code_sha256") != current_execution_code_sha256:
        raise RecoveryError("EXECUTION_IDENTITY_CHANGED")
    if _HASH.fullmatch(expected_request_sha256) is None:
        raise RecoveryError("SOURCE_SCOPE_INVALID")
    units = manifest.get("units")
    if (
        not isinstance(units, list)
        or isinstance(unit_index, bool)
        or unit_index < 0
        or unit_index >= len(units)
    ):
        raise RecoveryError("SOURCE_SCOPE_INVALID")
    unit = units[unit_index]
    if not isinstance(unit, Mapping):
        raise RecoveryError("SOURCE_SCOPE_INVALID")
    source_payloads = unit.get("source_requests")
    if (
        not isinstance(source_payloads, list)
        or isinstance(request_index, bool)
        or request_index < 0
        or request_index >= len(source_payloads)
    ):
        raise RecoveryError("SOURCE_SCOPE_INVALID")
    request = _source_request_from_payload(source_payloads[request_index])
    request_payload = _request_payload(request)
    digest = hashlib.sha256(
        _canonical_json(request_payload).encode("utf-8")
    ).hexdigest()
    if digest != expected_request_sha256:
        raise RecoveryError("SOURCE_SCOPE_INVALID")
    if (
        unit.get("frequency") != "1w"
        or unit.get("contract") != request.contract
        or not isinstance(unit.get("symbol"), str)
        or not isinstance(unit.get("through"), str)
        or not isinstance(unit.get("plan_sha256"), str)
        or _HASH.fullmatch(str(unit["plan_sha256"])) is None
    ):
        raise RecoveryError("SOURCE_SCOPE_INVALID")
    return SourceSelection(unit=unit, request=request, request_payload=request_payload)


def classify_evidence_outcome(
    outcome: Mapping[str, object], *, plan_unchanged: bool
) -> tuple[str, str]:
    """Classify evidence capture only; raw rows decide anomaly semantics offline."""
    responses_saved = outcome.get("responses_saved")
    if (
        outcome.get("outcome_unknown") is True
        or not isinstance(responses_saved, int)
        or isinstance(responses_saved, bool)
        or responses_saved != 1
    ):
        return "unknown", "SOURCE_QUERY_OUTCOME_UNKNOWN"
    if not plan_unchanged:
        return "completed", "SOURCE_RESPONSE_SAVED_PLAN_DRIFT_REVIEW_REQUIRED"
    return "completed", "SOURCE_RESPONSE_SAVED_REVIEW_REQUIRED"


def _current_source_requests(
    environment: Any, unit: Mapping[str, Any]
) -> tuple[str, tuple[ExchangeDailySourceRequest, ...]]:
    request = ContractWarmupRequest(
        symbol=str(unit["symbol"]),
        contract=str(unit["contract"]),
        through=date.fromisoformat(str(unit["through"])),
        frequency="1w",
    )
    with readonly_transaction(environment.manager.catalog.session, timeout_seconds=300):
        plan, targets = environment.manager._contract_warmup_plan(request)
        bar_requests = tuple(
            BarFetchRequest(target.key, target.missing)
            for target in targets
            if target.key.frequency.value in {"1d", "1w"}
        )
        source_requests = environment.adapter.exchange_daily_source_requests(
            bar_requests
        )
    return plan.plan_sha256, source_requests


def _require_current_plan(
    environment: Any,
    selection: SourceSelection,
    identity: Mapping[str, str],
) -> None:
    plan_sha256, source_requests = _current_source_requests(environment, selection.unit)
    if plan_sha256 != selection.unit["plan_sha256"]:
        raise RecoveryError("CONTRACT_WARMUP_PLAN_CHANGED")
    frozen_payloads = selection.unit.get("source_requests")
    if not isinstance(frozen_payloads, list):
        raise RecoveryError("SOURCE_SCOPE_INVALID")
    if tuple(_request_payload(item) for item in source_requests) != tuple(frozen_payloads):
        raise RecoveryError("CONTRACT_WARMUP_PLAN_CHANGED")
    _require_execution_identity(environment, identity)


def _require_frozen_execution(manifest: Mapping[str, Any]) -> None:
    expected_commit = manifest.get("code_commit")
    expected_digest = manifest.get("execution_code_sha256")
    if not isinstance(expected_commit, str) or not isinstance(expected_digest, str):
        raise RecoveryError("PREPARED_MANIFEST_INVALID")
    _require_clean_execution_checkout(expected_commit)
    if _current_execution_code_sha256() != expected_digest:
        raise RecoveryError("EXECUTION_IDENTITY_CHANGED")


def _validated_unused_attempt(output_root: Path, attempt_id: str) -> Path:
    root = Path(output_root)
    try:
        info = root.lstat()
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise RecoveryError("OUTPUT_ROOT_UNSAFE") from exc
    if (
        not root.is_absolute()
        or resolved != root
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or _ATTEMPT_ID.fullmatch(attempt_id) is None
    ):
        raise RecoveryError("OUTPUT_ROOT_UNSAFE")
    attempt = root / attempt_id
    if attempt.exists() or attempt.is_symlink():
        raise RecoveryError("ATTEMPT_EXISTS")
    return attempt


def _load_preflight(
    args: argparse.Namespace,
) -> tuple[Mapping[str, Any], Mapping[str, str], SourceSelection, bool]:
    manifest = load_prepared_manifest(
        Path(args.prepared), args.expected_prepared_sha256
    )
    _validated_unused_attempt(Path(args.output_root), args.attempt_id)
    _require_frozen_execution(manifest)
    selection = validate_selection(
        manifest,
        current_execution_code_sha256=_current_execution_code_sha256(),
        unit_index=args.unit_index,
        request_index=args.request_index,
        expected_request_sha256=args.expected_request_sha256,
    )
    _settings, identity = load_private_execution_settings(Path(args.project_env))
    if (
        identity.get("config_sha256") != manifest.get("config_sha256")
        or identity.get("canonical_root_sha256")
        != manifest.get("canonical_root_sha256")
    ):
        raise RecoveryError("EXECUTION_IDENTITY_CHANGED")
    environment = _require_execution_identity(
        _open_execution_environment(Path(args.project_env)), identity
    )
    try:
        _require_current_plan(environment, selection, identity)
        lease = environment.manager.catalog.acquire_maintenance_lock()
        maintenance_available = lease is not None
        if lease is not None:
            lease.release()
        else:
            raise RecoveryError("MAINTENANCE_LOCK_UNAVAILABLE")
    finally:
        environment.close()
    return manifest, identity, selection, maintenance_available


def _execute(
    args: argparse.Namespace,
    manifest: Mapping[str, Any],
    identity: Mapping[str, str],
    selection: SourceSelection,
) -> Mapping[str, object]:
    attempt = create_attempt_directory(Path(args.output_root), args.attempt_id)
    observer = AttemptJournal(attempt, (selection.request,))
    runner_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    _write_json_exclusive(
        attempt / "invocation-receipt.json",
        {
            "schema_version": "newow_weekly_source_only_invocation_v1",
            "prepared_path": str(Path(args.prepared).name),
            "prepared_sha256": args.expected_prepared_sha256,
            "request_sha256": args.expected_request_sha256,
            "attempt_id": args.attempt_id,
            "code_commit": _current_code_commit(),
            "execution_code_sha256": manifest["execution_code_sha256"],
            "config_sha256": identity["config_sha256"],
            "canonical_root_sha256": identity["canonical_root_sha256"],
            "runner_sha256": runner_sha256,
            "provider_request_limit": 1,
            "retries_allowed": 0,
            "canonical_writes_allowed": False,
            "database_writes_allowed": False,
            "manager_apply_allowed": False,
        },
    )
    environment = _require_execution_identity(
        _open_execution_environment(Path(args.project_env), observer), identity
    )
    lease = None
    source_error_code: str | None = None
    plan_unchanged = False
    try:
        lease = environment.manager.catalog.acquire_maintenance_lock()
        if lease is None:
            raise RecoveryError("MAINTENANCE_LOCK_UNAVAILABLE")
        _require_frozen_execution(manifest)
        _require_current_plan(environment, selection, identity)
        key = DatasetKey(
            DatasetKind.CONTRACT,
            str(selection.unit["symbol"]),
            str(selection.unit["contract"]),
            BarFrequency.D1,
        )
        try:
            environment.adapter._exchange_daily_rows(
                key, selection.request.expected_dates, cache={}
            )
        except Exception as error:  # noqa: BLE001 - sanitize provider/storage errors
            source_error_code = _error_code(error)
            observer.mark_failed(source_error_code)
        current_plan_sha256, current_sources = _current_source_requests(
            environment, selection.unit
        )
        plan_unchanged = (
            current_plan_sha256 == selection.unit["plan_sha256"]
            and tuple(_request_payload(item) for item in current_sources)
            == tuple(selection.unit["source_requests"])
        )
    finally:
        if lease is not None:
            lease.release()
        environment.close()
    outcome = read_attempt_outcome(attempt)
    status, classification = classify_evidence_outcome(
        outcome, plan_unchanged=plan_unchanged
    )
    result: dict[str, object] = {
        "schema_version": "newow_weekly_source_only_result_v1",
        "status": status,
        "classification": classification,
        "source_error_code": source_error_code,
        "prepared_sha256": args.expected_prepared_sha256,
        "request_sha256": args.expected_request_sha256,
        "unit_identity": {
            key: selection.unit[key]
            for key in ("symbol", "contract", "frequency", "through", "plan_sha256")
        },
        "attempt": outcome,
        "provider_request_limit": 1,
        "retries": 0,
        "canonical_writes": 0,
        "database_writes": 0,
        "manager_apply": False,
    }
    _write_json_exclusive(attempt / "source-only-result.json", result)
    return result


def main(argv: list[str] | None = None, *, stdout=sys.stdout) -> int:
    try:
        args = parser().parse_args(argv)
        manifest, identity, selection, maintenance_available = _load_preflight(args)
        if args.mode == "preflight":
            payload: Mapping[str, object] = {
                "schema_version": "newow_weekly_source_only_preflight_v1",
                "status": "source_query_preflight_passed",
                "readonly": True,
                "maintenance_lock_available": maintenance_available,
                "provider_requests": 0,
                "writes": 0,
                "prepared_sha256": args.expected_prepared_sha256,
                "request_sha256": args.expected_request_sha256,
                "output_root": args.output_root,
                "attempt_id": args.attempt_id,
                "request": selection.request_payload,
            }
            code = 0
        else:
            payload = _execute(args, manifest, identity, selection)
            code = 0 if payload["status"] == "completed" else 2
    except Exception as error:  # noqa: BLE001 - CLI boundary must stay sanitized
        payload = {"status": "failed", "error_code": _error_code(error)}
        code = 1
    print(json.dumps(payload, sort_keys=True), file=stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
