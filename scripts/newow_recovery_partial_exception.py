"""Pure validation for D1 partial-commit authoritative source exceptions."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable, Mapping, Sequence

from scripts.newow_weekly_recovery import (
    RecoveryError,
    _canonical_json,
    _committed_and_failed_targets,
    _error_code,
    _read_journal_records,
    _read_source_payload,
    _request_payload,
    _source_request_from_payload,
    _validated_direct_child_directory,
    _validate_response_identity,
    read_attempt_outcome,
)
from app.market_data.rqdata_adapter import _normalize_exchange_daily_zero_volume_row


SCHEMA_VERSION = "newow_daily_partial_source_exception_v1"
CLASSIFICATION = "PARTIAL_COMMIT_AUTHORITATIVE_SOURCE_EXCEPTION"
ERROR_CODE = "PARTIAL_SOURCE_EXCEPTION_INVALID"
_ALLOWED_ERROR = "RQDATA_ZERO_OHL_INVALID"
_HASH = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_ATTEMPT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def validate_partial_source_exception(
    *,
    unit_dir: Path,
    expected_parent: Path,
    fresh_unit: Mapping[str, Any],
    failed_attempt_id: str,
    failed_execution_commit: str,
    failed_execution_code_sha256: str,
    catalog_readback: Mapping[str, Any],
    parquet_readback: Mapping[str, Any],
    mds_readback: Mapping[str, Any],
    current_identity: Mapping[str, str],
    expected_identity: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Prove one partial-commit source exception from hash-bound artifacts."""
    try:
        return _validate_partial_source_exception(
            unit_dir=unit_dir,
            expected_parent=expected_parent,
            fresh_unit=fresh_unit,
            failed_attempt_id=failed_attempt_id,
            failed_execution_commit=failed_execution_commit,
            failed_execution_code_sha256=failed_execution_code_sha256,
            catalog_readback=catalog_readback,
            parquet_readback=parquet_readback,
            mds_readback=mds_readback,
            current_identity=current_identity,
            expected_identity=expected_identity,
        )
    except RecoveryError as exc:
        if str(exc) != ERROR_CODE:
            raise RecoveryError(ERROR_CODE) from exc
        raise
    except Exception as exc:
        raise RecoveryError(ERROR_CODE) from exc


def derive_partial_source_exceptions(
    *,
    evidence_root: Path,
    attempt_path: Path,
    fresh_units: Sequence[Mapping[str, Any]],
    current_identity: Mapping[str, str],
    observe_committed: Callable[
        [Mapping[str, Any], list[dict[str, Any]]], Mapping[str, Any]
    ],
) -> list[dict[str, Any]]:
    """Derive at most one partial exception from one failed campaign attempt."""
    root = Path(evidence_root).resolve()
    attempt = Path(attempt_path)
    try:
        if attempt.parent.resolve() != root:
            raise RecoveryError(ERROR_CODE)
        started = _read_mapping(attempt / "campaign-started.json")
        result = _read_mapping(attempt / "campaign-result.json")
    except (OSError, RecoveryError) as exc:
        raise RecoveryError(ERROR_CODE) from exc
    identity = started.get("execution_identity")
    if (
        not isinstance(identity, Mapping)
        or started.get("retries") != 0
        or result.get("retries") != 0
        or result.get("unknown_batch") is not None
        or not isinstance(result.get("failed_batch"), Mapping)
        or not isinstance(failed_attempt_id := attempt.name, str)
        or _ATTEMPT_ID.fullmatch(failed_attempt_id) is None
    ):
        raise RecoveryError(ERROR_CODE)
    failed_batch = result["failed_batch"]
    native = failed_batch.get("native_result")
    if not isinstance(native, Mapping):
        raise RecoveryError(ERROR_CODE)
    native_result = native.get("result")
    failed_unit = (
        native_result.get("failed") if isinstance(native_result, Mapping) else None
    )
    completed = (
        native_result.get("completed") if isinstance(native_result, Mapping) else None
    )
    batch_id = failed_batch.get("batch_id")
    if (
        not isinstance(failed_unit, Mapping)
        or not isinstance(completed, list)
        or not isinstance(batch_id, str)
        or re.fullmatch(r"batch-\d{3}", batch_id) is None
    ):
        raise RecoveryError(ERROR_CODE)
    symbol = failed_unit.get("symbol")
    contract = failed_unit.get("contract")
    if not isinstance(symbol, str) or not isinstance(contract, str):
        raise RecoveryError(ERROR_CODE)
    unit_name = f"unit-{len(completed) + 1:03d}-{symbol}-{contract}"
    native_dir = attempt / batch_id / "native"
    unit_dir = native_dir / unit_name
    committed, _failed_targets = _committed_and_failed_targets(
        failed_unit, failed_unit.get("result") or {}
    )
    if not committed:
        raise RecoveryError(ERROR_CODE)
    observed = observe_committed(failed_unit, committed)
    if not isinstance(observed, Mapping):
        raise RecoveryError(ERROR_CODE)
    fresh_unit = _matching_fresh_unit(failed_unit, fresh_units)
    payload = validate_partial_source_exception(
        unit_dir=unit_dir,
        expected_parent=native_dir,
        fresh_unit=fresh_unit,
        failed_attempt_id=failed_attempt_id,
        failed_execution_commit=str(identity.get("code_commit", "")),
        failed_execution_code_sha256=str(identity.get("execution_code_sha256", "")),
        catalog_readback=_require_mapping(observed.get("catalog_readback")),
        parquet_readback=_require_mapping(observed.get("parquet_readback")),
        mds_readback=_require_mapping(observed.get("mds_readback")),
        current_identity=current_identity,
        expected_identity=current_identity,
    )
    binding = {
        **payload,
        "failed_attempt_path": attempt.name,
        "batch_id": batch_id,
        "unit_dir": f"{batch_id}/native/{unit_name}",
    }
    binding["binding_sha256"] = hashlib.sha256(
        _canonical_json(
            {key: value for key, value in binding.items() if key != "binding_sha256"}
        ).encode("utf-8")
    ).hexdigest()
    return [binding]


def _validate_partial_source_exception(
    *,
    unit_dir: Path,
    expected_parent: Path,
    fresh_unit: Mapping[str, Any],
    failed_attempt_id: str,
    failed_execution_commit: str,
    failed_execution_code_sha256: str,
    catalog_readback: Mapping[str, Any],
    parquet_readback: Mapping[str, Any],
    mds_readback: Mapping[str, Any],
    current_identity: Mapping[str, str],
    expected_identity: Mapping[str, str] | None,
) -> dict[str, Any]:
    if _ATTEMPT_ID.fullmatch(failed_attempt_id) is None:
        raise RecoveryError(ERROR_CODE)
    if _COMMIT.fullmatch(failed_execution_commit) is None:
        raise RecoveryError(ERROR_CODE)
    if _HASH.fullmatch(failed_execution_code_sha256) is None:
        raise RecoveryError(ERROR_CODE)
    _require_identity(current_identity)
    if expected_identity is not None:
        _require_identity(expected_identity)
        if dict(current_identity) != dict(expected_identity):
            raise RecoveryError(ERROR_CODE)
    safe_dir = _validated_direct_child_directory(
        unit_dir,
        expected_parent,
        ERROR_CODE,
    )
    failed_unit = _read_mapping(safe_dir / "unit-result.json")
    if failed_unit.get("frequency") != "1d":
        raise RecoveryError(ERROR_CODE)
    result = failed_unit.get("result")
    if not isinstance(result, Mapping):
        raise RecoveryError(ERROR_CODE)
    applied = result.get("applied")
    if (
        failed_unit.get("status") != "partial"
        or result.get("status") != "partial"
        or not isinstance(applied, int)
        or isinstance(applied, bool)
        or applied <= 0
        or failed_unit.get("status") == "isolated"
    ):
        raise RecoveryError(ERROR_CODE)
    attempt = read_attempt_outcome(safe_dir)
    if attempt != {
        "state": "failed",
        "outcome_unknown": False,
        "retry_allowed": False,
        "requests_started": attempt.get("requests_started"),
        "responses_saved": attempt.get("responses_saved"),
    }:
        raise RecoveryError(ERROR_CODE)
    started = attempt.get("requests_started")
    saved = attempt.get("responses_saved")
    if (
        started != saved
        or not isinstance(started, int)
        or isinstance(started, bool)
        or started < 1
        or attempt.get("outcome_unknown") is not False
        or attempt.get("retry_allowed") is not False
    ):
        raise RecoveryError(ERROR_CODE)
    if failed_unit.get("retries") not in (None, 0):
        raise RecoveryError(ERROR_CODE)
    committed, failed_targets = _committed_and_failed_targets(failed_unit, result)
    if len(committed) != applied or len(failed_targets) != 1:
        raise RecoveryError(ERROR_CODE)
    failed_target = failed_targets[0]
    if failed_target.get("reason_code") not in (None, _ALLOWED_ERROR):
        raise RecoveryError(ERROR_CODE)
    failures = result.get("failures")
    if not isinstance(failures, list) or len(failures) != 1:
        raise RecoveryError(ERROR_CODE)
    failure = failures[0]
    if not isinstance(failure, Mapping) or failure.get("reason_code") != _ALLOWED_ERROR:
        raise RecoveryError(ERROR_CODE)
    if _target_key(failure) != _target_key(failed_target):
        raise RecoveryError(ERROR_CODE)
    source_payloads = failed_unit.get("source_requests")
    if not isinstance(source_payloads, list) or not source_payloads:
        raise RecoveryError(ERROR_CODE)
    replay = _replay_partial_source(
        safe_dir,
        failed_unit,
        started_count=started,
        failed_target=failed_target,
    )
    remaining = _remaining_targets(failed_unit, committed)
    fresh_targets = _unit_targets(fresh_unit)
    if not _same_unit_identity(failed_unit, fresh_unit):
        raise RecoveryError(ERROR_CODE)
    if fresh_unit.get("frequency") != "1d":
        raise RecoveryError(ERROR_CODE)
    failed_plan = failed_unit.get("plan_sha256")
    fresh_plan = fresh_unit.get("plan_sha256")
    if (
        not isinstance(failed_plan, str)
        or not isinstance(fresh_plan, str)
        or _HASH.fullmatch(failed_plan) is None
        or _HASH.fullmatch(fresh_plan) is None
        or failed_plan == fresh_plan
    ):
        raise RecoveryError(ERROR_CODE)
    remaining_keys = [_target_key(item) for item in remaining]
    fresh_keys = [_target_key(item) for item in fresh_targets]
    old_keys = [_target_key(item) for item in _unit_targets(failed_unit)]
    committed_keys = [_target_key(item) for item in committed]
    if (
        not remaining_keys
        or set(remaining_keys) != set(fresh_keys)
        or len(remaining_keys) != len(fresh_keys)
        or set(remaining_keys) | set(committed_keys) != set(old_keys)
        or set(committed_keys) & set(remaining_keys)
        or not set(committed_keys)
        or _target_key(failed_target) not in set(remaining_keys)
        or not set(remaining_keys).issubset(old_keys)
        or set(remaining_keys) == set(old_keys)
    ):
        raise RecoveryError(ERROR_CODE)
    _require_committed_readback(
        catalog_readback,
        parquet_readback,
        mds_readback,
        committed,
    )
    journal_sha256 = _file_sha256(safe_dir / "journal.jsonl")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "symbol": failed_unit["symbol"],
        "contract": failed_unit["contract"],
        "frequency": "1d",
        "through": failed_unit["through"],
        "failed_plan_sha256": failed_plan,
        "fresh_replan_sha256": fresh_plan,
        "failed_attempt_id": failed_attempt_id,
        "failed_execution_commit": failed_execution_commit,
        "failed_execution_code_sha256": failed_execution_code_sha256,
        "committed_targets": committed,
        "remaining_targets": remaining,
        "source_request_identity": replay["source_request_identity"],
        "source_response_sha256": replay["source_response_sha256"],
        "journal_sha256": journal_sha256,
        "error_code": _ALLOWED_ERROR,
        "requests_started": started,
        "responses_saved": saved,
        "retries": 0,
        "outcome_unknown": False,
        "catalog_readback": dict(catalog_readback),
        "parquet_readback": dict(parquet_readback),
        "mds_readback": dict(mds_readback),
        "classification": CLASSIFICATION,
    }
    payload["evidence_sha256"] = hashlib.sha256(
        _canonical_json(
            {key: value for key, value in payload.items() if key != "evidence_sha256"}
        ).encode("utf-8")
    ).hexdigest()
    return payload


def _replay_partial_source(
    unit_dir: Path,
    unit: Mapping[str, Any],
    *,
    started_count: int,
    failed_target: Mapping[str, Any],
) -> dict[str, Any]:
    source_payloads = unit.get("source_requests")
    if not isinstance(source_payloads, list):
        raise RecoveryError(ERROR_CODE)
    try:
        frozen_requests = tuple(
            _source_request_from_payload(value) for value in source_payloads
        )
        records = _read_journal_records(unit_dir)
    except RecoveryError as exc:
        raise RecoveryError(ERROR_CODE) from exc
    if len(records) < 3 or records[-1] != {
        "schema_version": 1,
        "sequence": None,
        "state": "failed",
        "error_code": "RECOVERY_RESULT_NOT_PASSED",
    }:
        raise RecoveryError(ERROR_CODE)
    request_records = records[:-1]
    if len(request_records) != started_count * 2:
        raise RecoveryError(ERROR_CODE)
    if not 1 <= started_count <= len(frozen_requests):
        raise RecoveryError(ERROR_CODE)
    expected_files: set[str] = set()
    failed_request_payload: Mapping[str, Any] | None = None
    failed_response_sha256: str | None = None
    for offset in range(started_count):
        sequence = offset + 1
        started = request_records[offset * 2]
        saved = request_records[offset * 2 + 1]
        request = frozen_requests[offset]
        request_payload = _request_payload(request)
        expected_file = f"source-response-{sequence:04d}.json"
        if started != {
            "schema_version": 1,
            "sequence": sequence,
            "state": "started",
            "request": request_payload,
        }:
            raise RecoveryError(ERROR_CODE)
        payload_sha256 = saved.get("payload_sha256")
        row_count = saved.get("row_count")
        if (
            saved.get("schema_version") != 1
            or saved.get("sequence") != sequence
            or saved.get("state") != "response_saved"
            or saved.get("payload_file") != expected_file
            or not isinstance(row_count, int)
            or isinstance(row_count, bool)
            or row_count < 0
            or not isinstance(payload_sha256, str)
            or _HASH.fullmatch(payload_sha256) is None
        ):
            raise RecoveryError(ERROR_CODE)
        source_payload = _read_source_payload(unit_dir / expected_file, payload_sha256)
        rows = source_payload.get("rows")
        if (
            set(source_payload) != {"schema_version", "request", "rows"}
            or source_payload.get("schema_version") != 1
            or source_payload.get("request") != request_payload
            or not isinstance(rows, list)
            or len(rows) != row_count
            or any(not isinstance(row, dict) for row in rows)
        ):
            raise RecoveryError(ERROR_CODE)
        _validate_response_identity(request, tuple(rows))
        replayed: set[str] = set()
        for row in rows:
            try:
                _normalize_exchange_daily_zero_volume_row(row)
            except Exception as exc:  # noqa: BLE001 - only an exact known code qualifies
                code = _error_code(exc)
                if code != _ALLOWED_ERROR:
                    raise RecoveryError(ERROR_CODE) from exc
                replayed.add(code)
        matches_failed = (
            request.start.year,
            request.start.month,
        ) == (failed_target.get("year"), failed_target.get("month"))
        if matches_failed:
            if replayed != {_ALLOWED_ERROR}:
                raise RecoveryError(ERROR_CODE)
            failed_request_payload = request_payload
            failed_response_sha256 = payload_sha256
        elif replayed:
            raise RecoveryError(ERROR_CODE)
        expected_files.add(expected_file)
    actual_files = {path.name for path in unit_dir.glob("source-response-*.json")}
    if (
        actual_files != expected_files
        or failed_request_payload is None
        or failed_response_sha256 is None
    ):
        raise RecoveryError(ERROR_CODE)
    return {
        "source_request_identity": dict(failed_request_payload),
        "source_response_sha256": failed_response_sha256,
    }


def _require_committed_readback(
    catalog_readback: Mapping[str, Any],
    parquet_readback: Mapping[str, Any],
    mds_readback: Mapping[str, Any],
    committed: Sequence[Mapping[str, Any]],
) -> None:
    catalog_items = _readback_items(catalog_readback, "partitions", "row_count")
    parquet_items = _readback_items(parquet_readback, "files", "row_count")
    mds_items = _readback_items(mds_readback, "windows", "bar_count")
    expected = []
    for target in committed:
        key = _target_key(target)
        count = target.get("expected_bar_count")
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            raise RecoveryError(ERROR_CODE)
        expected.append((key, count))
    if (
        catalog_items != expected
        or parquet_items != expected
        or mds_items != expected
        or catalog_readback.get("status") != "passed"
        or parquet_readback.get("status") != "passed"
        or mds_readback.get("status") != "passed"
    ):
        raise RecoveryError(ERROR_CODE)
    parquet_files = parquet_readback.get("files")
    if not isinstance(parquet_files, list):
        raise RecoveryError(ERROR_CODE)
    for item in parquet_files:
        digest = item.get("file_sha256") if isinstance(item, Mapping) else None
        if not isinstance(digest, str) or _HASH.fullmatch(digest) is None:
            raise RecoveryError(ERROR_CODE)


def _readback_items(
    readback: Mapping[str, Any],
    collection: str,
    count_field: str,
) -> list[tuple[tuple[object, object, object], int]]:
    if not isinstance(readback, Mapping):
        raise RecoveryError(ERROR_CODE)
    values = readback.get(collection)
    if not isinstance(values, list):
        raise RecoveryError(ERROR_CODE)
    items: list[tuple[tuple[object, object, object], int]] = []
    seen: set[tuple[object, object, object]] = set()
    for raw in values:
        if not isinstance(raw, Mapping):
            raise RecoveryError(ERROR_CODE)
        try:
            key = _target_key(raw)
            count = raw[count_field]
        except (KeyError, TypeError, ValueError) as exc:
            raise RecoveryError(ERROR_CODE) from exc
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or count <= 0
            or key in seen
        ):
            raise RecoveryError(ERROR_CODE)
        seen.add(key)
        items.append((key, count))
    return items


def _matching_fresh_unit(
    failed_unit: Mapping[str, Any],
    fresh_units: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    matches = [
        item
        for item in fresh_units
        if isinstance(item, Mapping) and _same_unit_identity(failed_unit, item)
    ]
    if len(matches) != 1:
        raise RecoveryError(ERROR_CODE)
    return matches[0]


def _same_unit_identity(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return all(
        left.get(key) == right.get(key)
        for key in ("symbol", "contract", "frequency", "through")
    )


def _unit_targets(unit: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = unit.get("targets")
    if not isinstance(raw, list):
        raw = unit.get("target_windows")
    if not isinstance(raw, list) or not raw:
        raise RecoveryError(ERROR_CODE)
    targets: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise RecoveryError(ERROR_CODE)
        targets.append(dict(item))
    return targets


def _remaining_targets(
    failed_unit: Mapping[str, Any],
    committed: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    committed_keys = {_target_key(item) for item in committed}
    remaining = [
        dict(item)
        for item in _unit_targets(failed_unit)
        if _target_key(item) not in committed_keys
    ]
    if not remaining:
        raise RecoveryError(ERROR_CODE)
    return remaining


def _target_key(value: Mapping[str, Any]) -> tuple[object, object, object]:
    dataset = value.get("dataset")
    if not isinstance(dataset, (list, tuple)) or len(dataset) != 4:
        raise RecoveryError(ERROR_CODE)
    try:
        year = int(value["year"])
        month = int(value["month"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RecoveryError(ERROR_CODE) from exc
    raw_year = value.get("year")
    raw_month = value.get("month")
    if (
        isinstance(raw_year, bool)
        or isinstance(raw_month, bool)
        or year != raw_year
        or month != raw_month
        or year < 1990
        or not 1 <= month <= 12
    ):
        raise RecoveryError(ERROR_CODE)
    return (tuple(dataset), year, month)


def _require_identity(value: Mapping[str, str]) -> None:
    if (
        not isinstance(value, Mapping)
        or _COMMIT.fullmatch(str(value.get("code_commit", ""))) is None
        or _HASH.fullmatch(str(value.get("execution_code_sha256", ""))) is None
        or _HASH.fullmatch(str(value.get("config_sha256", ""))) is None
        or _HASH.fullmatch(str(value.get("canonical_root_sha256", ""))) is None
    ):
        raise RecoveryError(ERROR_CODE)


def _require_mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RecoveryError(ERROR_CODE)
    return value


def _read_mapping(path: Path) -> dict[str, Any]:
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
        value = json.loads(content)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RecoveryError(ERROR_CODE) from exc
    if not isinstance(value, dict):
        raise RecoveryError(ERROR_CODE)
    return value


def _file_sha256(path: Path) -> str:
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
        raise RecoveryError(ERROR_CODE) from exc
    return hashlib.sha256(content).hexdigest()
