"""Bounded, auditable Newow W1/60m recovery orchestration."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any, Callable, Mapping, TypeVar

from app.market_data.historical_data_manager import (
    BarFetchRequest,
    ContractWarmupRequest,
)
from app.market_data.rqdata_adapter import ExchangeDailySourceRequest
from app.market_data.rqdata_adapter import _normalize_exchange_daily_zero_volume_row


_ATTEMPT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_SOURCE_FIELDS = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
    "total_turnover",
    "open_interest",
    "settlement",
    "prev_settlement",
)
_EXECUTION_CODE_PATHS = (
    "scripts/newow_weekly_recovery.py",
    "scripts/newow_weekly_recovery_campaign.py",
    "scripts/newow_weekly_source_verify.py",
    "scripts/newow_recovery_partial_exception.py",
    "services/quant-api/app/market_data/composition.py",
    "services/quant-api/app/market_data/rqdata_adapter.py",
    "services/quant-api/app/market_data/historical_data_manager.py",
    "services/quant-api/app/market_data/storage.py",
    "services/quant-api/app/market_data/catalog.py",
    "services/quant-api/app/market_data/closeout_binding.py",
    "services/quant-api/app/market_data/coverage_source.py",
    "services/quant-api/app/market_data/market_home_projection.py",
)
_T = TypeVar("_T")
_SOURCE_ISOLATION_POLICY_SCHEMA = "newow_weekly_recovery_continuation_policy_v1"
_SOURCE_ISOLATION_MODE = "isolate_known_source_quality"
_SOURCE_ISOLATION_ERROR_CODES = ("RQDATA_ZERO_OHL_INVALID",)
_UNIT_FREQUENCIES = frozenset({"1w", "60m"})
_PREPARE_SCHEMA = {
    "1w": "newow_weekly_recovery_prepare_v1",
    "60m": "newow_hourly_recovery_prepare_v1",
}
_RESULT_SCHEMA = {
    "1w": "newow_weekly_recovery_result_v1",
    "60m": "newow_hourly_recovery_result_v1",
}
_INVOCATION_SCHEMA = {
    "1w": "newow_weekly_recovery_invocation_v1",
    "60m": "newow_hourly_recovery_invocation_v1",
}


def _require_unit_frequency(value: object) -> str:
    if value not in _UNIT_FREQUENCIES:
        raise RecoveryError("RECOVERY_SCOPE_INVALID")
    return str(value)


def _allowed_target_frequencies(unit_frequency: str) -> frozenset[str]:
    frequency = _require_unit_frequency(unit_frequency)
    if frequency == "1w":
        return frozenset({"1d", "1w"})
    return frozenset({"1m", "60m"})


def _prepare_schema(unit_frequency: str) -> str:
    return _PREPARE_SCHEMA[_require_unit_frequency(unit_frequency)]


def _frequency_for_prepare_schema(schema: object) -> str:
    for frequency, name in _PREPARE_SCHEMA.items():
        if name == schema:
            return frequency
    raise RecoveryError("PREPARED_MANIFEST_INVALID")


def _result_schema(unit_frequency: str) -> str:
    return _RESULT_SCHEMA[_require_unit_frequency(unit_frequency)]


class RecoveryError(RuntimeError):
    """Sanitized recovery boundary error."""


class _ExecutionEnvironment:
    def __init__(self, manager, adapter, settings, identity, close):
        self.manager = manager
        self.adapter = adapter
        self.settings = settings
        self.identity = identity
        self.close = close


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Prepare or execute one bounded Newow W1/60m recovery batch."
    )
    commands = value.add_subparsers(dest="mode", required=True)
    prepare = commands.add_parser("prepare", allow_abbrev=False)
    prepare.add_argument("--project-env", required=True)
    prepare.add_argument("--units", required=True)
    prepare.add_argument("--output-root", required=True)
    prepare.add_argument("--name", required=True)
    prepare.add_argument("--isolate-known-source-quality", action="store_true")
    apply = commands.add_parser("apply", allow_abbrev=False)
    apply.add_argument("--project-env", required=True)
    apply.add_argument("--prepared", required=True)
    apply.add_argument("--expected-prepared-sha256", required=True)
    apply.add_argument("--output-root", required=True)
    apply.add_argument("--attempt-id", required=True)
    apply.add_argument("--apply", action="store_true", required=True)
    inspect = commands.add_parser("inspect", allow_abbrev=False)
    inspect.add_argument("--attempt", required=True)
    return value


def source_isolation_policy(*, unit_frequency: str = "1w") -> dict[str, object]:
    """Return the one supported, hash-bound continuation policy."""
    frequency = _require_unit_frequency(unit_frequency)
    if frequency != "1w":
        raise RecoveryError("RECOVERY_SCOPE_INVALID")
    body = {
        "schema_version": _SOURCE_ISOLATION_POLICY_SCHEMA,
        "mode": _SOURCE_ISOLATION_MODE,
        "allowed_error_codes": list(_SOURCE_ISOLATION_ERROR_CODES),
    }
    return {
        **body,
        "policy_sha256": hashlib.sha256(
            _canonical_json(body).encode("utf-8")
        ).hexdigest(),
    }


def _validated_continuation_policy(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    expected = source_isolation_policy()
    if not isinstance(value, Mapping) or dict(value) != expected:
        raise RecoveryError("CONTINUATION_POLICY_INVALID")
    return expected


def load_private_execution_settings(
    path: Path,
) -> tuple[dict[str, str], dict[str, str]]:
    """Load the existing literal project.env without exposing private values."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
                or info.st_mode & 0o077
                or info.st_size > 1024 * 1024
            ):
                raise OSError
            content = os.read(fd, 1024 * 1024 + 1)
            if len(content) != info.st_size:
                raise OSError
        finally:
            os.close(fd)
        from app.market_data.closeout_binding import runtime_dependency_settings
        from app.market_data.rqdata_adapter import runtime_provider_settings

        settings = runtime_dependency_settings(content)
        runtime_provider_settings(settings, required=True)
        canonical = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
        if (
            "DATABASE_URL" not in settings
            or not canonical.is_absolute()
            or canonical != canonical.resolve()
            or ".." in canonical.parts
        ):
            raise ValueError
    except (OSError, KeyError, UnicodeError, ValueError) as exc:
        raise RecoveryError("PROJECT_ENV_UNSAFE") from exc
    identity = {
        "config_sha256": hashlib.sha256(content).hexdigest(),
        "canonical_root_sha256": hashlib.sha256(
            str(canonical).encode("utf-8")
        ).hexdigest(),
    }
    return settings, identity


class AttemptJournal:
    def __init__(
        self,
        attempt_dir: Path,
        allowed_requests: tuple[ExchangeDailySourceRequest, ...],
    ) -> None:
        self.attempt_dir = Path(attempt_dir)
        self._expected_parent = self.attempt_dir.parent
        self.allowed_requests = tuple(allowed_requests)
        if len(set(self.allowed_requests)) != len(self.allowed_requests):
            raise RecoveryError("SOURCE_SCOPE_INVALID")
        self._validated_attempt_dir()
        self._started: dict[ExchangeDailySourceRequest, int] = {}
        self._failure_recorded = False
        journal = self.attempt_dir / "journal.jsonl"
        try:
            fd = os.open(
                journal,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            os.fsync(fd)
            os.close(fd)
            _fsync_directory(self.attempt_dir)
        except OSError as exc:
            raise RecoveryError("SOURCE_JOURNAL_UNAVAILABLE") from exc

    def before_request(self, request: ExchangeDailySourceRequest) -> None:
        if request not in self.allowed_requests or request in self._started:
            raise RecoveryError("SOURCE_REQUEST_OUT_OF_SCOPE")
        sequence = len(self._started) + 1
        record = {
            "schema_version": 1,
            "sequence": sequence,
            "state": "started",
            "request": _request_payload(request),
        }
        try:
            self._append(record)
        except OSError as exc:
            raise RecoveryError("SOURCE_JOURNAL_UNAVAILABLE") from exc
        self._started[request] = sequence

    def after_response(
        self,
        request: ExchangeDailySourceRequest,
        response: tuple[dict[str, Any], ...],
    ) -> None:
        sequence = self._started.get(request)
        if sequence is None:
            raise RecoveryError("SOURCE_RESPONSE_WITHOUT_START")
        try:
            payload_file, payload_sha256 = self._write_payload(
                sequence,
                request,
                response,
            )
            self._append(
                {
                    "schema_version": 1,
                    "sequence": sequence,
                    "state": "response_saved",
                    "payload_file": payload_file,
                    "payload_sha256": payload_sha256,
                    "row_count": len(response),
                }
            )
        except OSError as exc:
            raise RecoveryError("SOURCE_RESPONSE_PERSIST_FAILED") from exc
        try:
            _validate_response_identity(request, response)
        except RecoveryError as exc:
            try:
                self.mark_failed(str(exc), sequence=sequence)
            except OSError as journal_exc:
                raise RecoveryError("SOURCE_JOURNAL_UNAVAILABLE") from journal_exc
            raise

    def mark_failed(self, error_code: str, *, sequence: int | None = None) -> None:
        """Persist one sanitized known-failure terminal record."""
        if self._failure_recorded:
            return
        if re.fullmatch(r"[A-Z0-9_]{1,64}", error_code) is None:
            error_code = "RECOVERY_EXECUTION_FAILED"
        try:
            self._append(
                {
                    "schema_version": 1,
                    "sequence": sequence,
                    "state": "failed",
                    "error_code": error_code,
                }
            )
        except OSError as exc:
            raise RecoveryError("SOURCE_JOURNAL_UNAVAILABLE") from exc
        self._failure_recorded = True

    def _append(self, record: Mapping[str, Any]) -> None:
        content = (_canonical_json(record) + "\n").encode("utf-8")
        attempt_dir = self._validated_attempt_dir()
        fd = os.open(
            attempt_dir / "journal.jsonl",
            os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW,
        )
        try:
            os.write(fd, content)
            os.fsync(fd)
        finally:
            os.close(fd)

    def _write_payload(
        self,
        sequence: int,
        request: ExchangeDailySourceRequest,
        response: tuple[dict[str, Any], ...],
    ) -> tuple[str, str]:
        attempt_dir = self._validated_attempt_dir()
        name = f"source-response-{sequence:04d}.json"
        target = attempt_dir / name
        temporary = attempt_dir / f".{name}.tmp"
        payload = {
            "schema_version": 1,
            "request": _request_payload(request),
            "rows": [
                {
                    field: _source_scalar(row[field])
                    for field in _SOURCE_FIELDS
                    if field in row
                }
                for row in response
            ],
        }
        content = (_canonical_json(payload) + "\n").encode("utf-8")
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        try:
            os.write(fd, content)
            os.fsync(fd)
        finally:
            os.close(fd)
        if target.exists() or target.is_symlink():
            temporary.unlink(missing_ok=True)
            raise OSError
        os.replace(temporary, target)
        _fsync_directory(attempt_dir)
        return name, hashlib.sha256(content).hexdigest()

    def _validated_attempt_dir(self) -> Path:
        return _validated_direct_child_directory(
            self.attempt_dir,
            self._expected_parent,
            "SOURCE_EVIDENCE_PATH_INVALID",
        )


def create_attempt_directory(output_root: Path, attempt_id: str) -> Path:
    root = Path(output_root)
    try:
        info = root.lstat()
    except OSError as exc:
        raise RecoveryError("OUTPUT_ROOT_UNSAFE") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RecoveryError("OUTPUT_ROOT_UNSAFE")
    if _ATTEMPT_ID.fullmatch(attempt_id) is None:
        raise RecoveryError("ATTEMPT_PATH_INVALID")
    attempt = root / attempt_id
    try:
        os.mkdir(attempt, mode=0o700)
        _fsync_directory(root)
    except FileExistsError as exc:
        raise RecoveryError("ATTEMPT_EXISTS") from exc
    except OSError as exc:
        raise RecoveryError("ATTEMPT_PATH_UNAVAILABLE") from exc
    return attempt


def read_attempt_outcome(attempt_dir: Path) -> dict[str, object]:
    records = _read_journal_records(attempt_dir)
    started = {
        record.get("sequence") for record in records if record.get("state") == "started"
    }
    saved = {
        record.get("sequence")
        for record in records
        if record.get("state") == "response_saved"
    }
    unknown = bool(started - saved)
    state = (
        "outcome_unknown"
        if unknown
        else str(records[-1].get("state"))
        if records
        else "not_started"
    )
    return {
        "state": state,
        "outcome_unknown": unknown,
        "retry_allowed": False,
        "requests_started": len(started),
        "responses_saved": len(saved),
    }


def _read_journal_records(attempt_dir: Path) -> tuple[dict[str, Any], ...]:
    path = Path(attempt_dir) / "journal.jsonl"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
                raise OSError
            content = os.read(fd, 1024 * 1024 + 1)
            if len(content) != info.st_size:
                raise OSError
        finally:
            os.close(fd)
        values = tuple(
            json.loads(line) for line in content.decode("utf-8").splitlines()
        )
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RecoveryError("SOURCE_JOURNAL_INVALID") from exc
    if any(not isinstance(value, dict) for value in values):
        raise RecoveryError("SOURCE_JOURNAL_INVALID")
    return values


def _read_source_payload(path: Path, expected_sha256: str) -> dict[str, Any]:
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise RecoveryError("SOURCE_EVIDENCE_INVALID")
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
        if hashlib.sha256(content).hexdigest() != expected_sha256:
            raise ValueError
        value = json.loads(content)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RecoveryError("SOURCE_EVIDENCE_INVALID") from exc
    if not isinstance(value, dict):
        raise RecoveryError("SOURCE_EVIDENCE_INVALID")
    return value


def _validated_direct_child_directory(
    path: Path,
    expected_parent: Path,
    error_code: str,
) -> Path:
    child = Path(path)
    parent = Path(expected_parent)
    try:
        parent_info = parent.lstat()
        child_info = child.lstat()
        resolved_parent = parent.resolve(strict=True)
        resolved_child = child.resolve(strict=True)
    except OSError as exc:
        raise RecoveryError(error_code) from exc
    if (
        child.parent != parent
        or not stat.S_ISDIR(parent_info.st_mode)
        or stat.S_ISLNK(parent_info.st_mode)
        or not stat.S_ISDIR(child_info.st_mode)
        or stat.S_ISLNK(child_info.st_mode)
        or resolved_child.parent != resolved_parent
    ):
        raise RecoveryError(error_code)
    return resolved_child


def _validated_source_attempt_outcome(
    unit_dir: Path,
    frozen_requests: tuple[ExchangeDailySourceRequest, ...],
) -> dict[str, object]:
    """Validate a failed attempt journal against its frozen source prefix."""
    records = _read_journal_records(unit_dir)
    if not records:
        raise RecoveryError("SOURCE_JOURNAL_INVALID")
    terminal = records[-1]
    terminal_sequence = terminal.get("sequence")
    if (
        set(terminal) != {"schema_version", "sequence", "state", "error_code"}
        or not isinstance(terminal.get("schema_version"), int)
        or isinstance(terminal.get("schema_version"), bool)
        or terminal.get("schema_version") != 1
        or terminal.get("state") != "failed"
        or not isinstance(terminal.get("error_code"), str)
        or re.fullmatch(r"[A-Z0-9_]{1,64}", terminal["error_code"]) is None
    ):
        raise RecoveryError("SOURCE_JOURNAL_INVALID")
    body = records[:-1]
    offset = 0
    started_count = 0
    saved_count = 0
    expected_files: set[str] = set()
    while offset < len(body):
        sequence = started_count + 1
        if sequence > len(frozen_requests):
            raise RecoveryError("SOURCE_JOURNAL_INVALID")
        request_payload = _request_payload(frozen_requests[started_count])
        started = body[offset]
        if (
            started
            != {
                "schema_version": 1,
                "sequence": sequence,
                "state": "started",
                "request": request_payload,
            }
            or isinstance(started.get("schema_version"), bool)
            or isinstance(started.get("sequence"), bool)
        ):
            raise RecoveryError("SOURCE_JOURNAL_INVALID")
        started_count += 1
        offset += 1
        if offset == len(body):
            break
        saved = body[offset]
        expected_file = f"source-response-{sequence:04d}.json"
        row_count = saved.get("row_count")
        payload_sha256 = saved.get("payload_sha256")
        if (
            set(saved)
            != {
                "schema_version",
                "sequence",
                "state",
                "payload_file",
                "payload_sha256",
                "row_count",
            }
            or not isinstance(saved.get("schema_version"), int)
            or isinstance(saved.get("schema_version"), bool)
            or saved.get("schema_version") != 1
            or not isinstance(saved.get("sequence"), int)
            or isinstance(saved.get("sequence"), bool)
            or saved.get("sequence") != sequence
            or saved.get("state") != "response_saved"
            or saved.get("payload_file") != expected_file
            or not isinstance(payload_sha256, str)
            or not isinstance(row_count, int)
            or isinstance(row_count, bool)
            or row_count < 0
        ):
            raise RecoveryError("SOURCE_JOURNAL_INVALID")
        payload = _read_source_payload(unit_dir / expected_file, payload_sha256)
        rows = payload.get("rows")
        if (
            set(payload) != {"schema_version", "request", "rows"}
            or not isinstance(payload.get("schema_version"), int)
            or isinstance(payload.get("schema_version"), bool)
            or payload.get("schema_version") != 1
            or payload.get("request") != request_payload
            or not isinstance(rows, list)
            or len(rows) != row_count
            or any(not isinstance(row, dict) for row in rows)
        ):
            raise RecoveryError("SOURCE_JOURNAL_INVALID")
        expected_files.add(expected_file)
        saved_count += 1
        offset += 1
    if (
        started_count - saved_count not in {0, 1}
        or terminal_sequence is not None
        and (
            not isinstance(terminal_sequence, int)
            or isinstance(terminal_sequence, bool)
            or terminal_sequence != started_count
            or saved_count != started_count
        )
    ):
        raise RecoveryError("SOURCE_JOURNAL_INVALID")
    actual_files = {path.name for path in unit_dir.glob("source-response-*.json")}
    if actual_files != expected_files:
        raise RecoveryError("SOURCE_JOURNAL_INVALID")
    outcome_unknown = started_count != saved_count
    return {
        "state": "outcome_unknown" if outcome_unknown else "failed",
        "outcome_unknown": outcome_unknown,
        "retry_allowed": False,
        "requests_started": started_count,
        "responses_saved": saved_count,
    }


def _source_isolation_evidence(
    unit_dir: Path,
    unit: Mapping[str, Any],
    result: Mapping[str, Any],
    policy: Mapping[str, object],
    *,
    expected_parent: Path,
) -> dict[str, object]:
    """Re-prove one known source-quality result from its saved raw responses."""
    unit_dir = _validated_direct_child_directory(
        unit_dir,
        expected_parent,
        "SOURCE_EVIDENCE_PATH_INVALID",
    )
    allowed_codes = policy.get("allowed_error_codes")
    source_payloads = unit.get("source_requests")
    targets = unit.get("targets")
    applied = result.get("applied")
    blocked = result.get("blocked")
    failed_count = result.get("failed")
    provider_requests = result.get("provider_requests")
    failures = result.get("failures")
    if (
        allowed_codes != ["RQDATA_ZERO_OHL_INVALID"]
        or not isinstance(source_payloads, list)
        or not source_payloads
        or not isinstance(targets, list)
        or not targets
        or result.get("status") != "failed"
        or not isinstance(applied, int)
        or isinstance(applied, bool)
        or applied != 0
        or not isinstance(blocked, int)
        or isinstance(blocked, bool)
        or blocked != 0
        or not isinstance(failed_count, int)
        or isinstance(failed_count, bool)
        or failed_count <= 0
        or not isinstance(provider_requests, int)
        or isinstance(provider_requests, bool)
        or provider_requests <= 0
        or not isinstance(failures, list)
        or not failures
        or failed_count != len(failures)
    ):
        raise RecoveryError("SOURCE_ISOLATION_UNPROVEN")
    frozen_requests = tuple(
        _source_request_from_payload(value) for value in source_payloads
    )
    records = _read_journal_records(unit_dir)
    if len(records) < 3 or records[-1] != {
        "schema_version": 1,
        "sequence": None,
        "state": "failed",
        "error_code": "RECOVERY_RESULT_NOT_PASSED",
    }:
        raise RecoveryError("SOURCE_ISOLATION_UNPROVEN")
    request_records = records[:-1]
    if len(request_records) % 2:
        raise RecoveryError("SOURCE_ISOLATION_UNPROVEN")
    started_count = len(request_records) // 2
    if not 1 <= started_count <= len(frozen_requests):
        raise RecoveryError("SOURCE_ISOLATION_UNPROVEN")
    response_hashes: list[str] = []
    replayed_codes: set[str] = set()
    expected_files: set[str] = set()
    for offset in range(started_count):
        sequence = offset + 1
        started = request_records[offset * 2]
        saved = request_records[offset * 2 + 1]
        request_payload = _request_payload(frozen_requests[offset])
        expected_file = f"source-response-{sequence:04d}.json"
        if started != {
            "schema_version": 1,
            "sequence": sequence,
            "state": "started",
            "request": request_payload,
        } or (
            saved.get("schema_version") != 1
            or saved.get("sequence") != sequence
            or saved.get("state") != "response_saved"
            or saved.get("payload_file") != expected_file
            or not isinstance(saved.get("row_count"), int)
            or isinstance(saved.get("row_count"), bool)
            or saved["row_count"] < 0
            or not isinstance(saved.get("payload_sha256"), str)
        ):
            raise RecoveryError("SOURCE_ISOLATION_UNPROVEN")
        source_payload = _read_source_payload(
            unit_dir / expected_file,
            saved["payload_sha256"],
        )
        rows = source_payload.get("rows")
        if (
            set(source_payload) != {"schema_version", "request", "rows"}
            or source_payload.get("schema_version") != 1
            or source_payload.get("request") != request_payload
            or not isinstance(rows, list)
            or len(rows) != saved["row_count"]
            or any(not isinstance(row, dict) for row in rows)
        ):
            raise RecoveryError("SOURCE_ISOLATION_UNPROVEN")
        _validate_response_identity(frozen_requests[offset], tuple(rows))
        for row in rows:
            try:
                _normalize_exchange_daily_zero_volume_row(row)
            except Exception as exc:  # noqa: BLE001 - only an exact known code qualifies
                code = _error_code(exc)
                if code not in allowed_codes:
                    raise RecoveryError("SOURCE_ISOLATION_UNPROVEN") from exc
                replayed_codes.add(code)
        expected_files.add(expected_file)
        response_hashes.append(saved["payload_sha256"])
    actual_files = {path.name for path in unit_dir.glob("source-response-*.json")}
    if actual_files != expected_files or not replayed_codes:
        raise RecoveryError("SOURCE_ISOLATION_UNPROVEN")
    allowed_targets = {
        (
            tuple(target.get("dataset", ())),
            target.get("year"),
            target.get("month"),
        )
        for target in targets
        if isinstance(target, Mapping)
    }
    failure_codes: set[str] = set()
    for failure in failures:
        if not isinstance(failure, Mapping):
            raise RecoveryError("SOURCE_ISOLATION_UNPROVEN")
        failure_identity = (
            tuple(failure.get("dataset", ())),
            failure.get("year"),
            failure.get("month"),
        )
        failure_code = failure.get("reason_code")
        if (
            failure_identity not in allowed_targets
            or not isinstance(failure_code, str)
            or failure_code not in allowed_codes
        ):
            raise RecoveryError("SOURCE_ISOLATION_UNPROVEN")
        failure_codes.add(failure_code)
    if failure_codes != replayed_codes:
        raise RecoveryError("SOURCE_ISOLATION_UNPROVEN")
    attempt = read_attempt_outcome(unit_dir)
    if attempt != {
        "state": "failed",
        "outcome_unknown": False,
        "retry_allowed": False,
        "requests_started": started_count,
        "responses_saved": started_count,
    }:
        raise RecoveryError("SOURCE_ISOLATION_UNPROVEN")
    evidence: dict[str, object] = {
        "classification": next(iter(failure_codes)),
        "requests_started": started_count,
        "responses_saved": started_count,
        "response_sha256s": response_hashes,
    }
    evidence["evidence_sha256"] = hashlib.sha256(
        _canonical_json(evidence).encode("utf-8")
    ).hexdigest()
    return evidence


def _zero_commit_readback(
    manager: Any,
    unit: Mapping[str, Any],
) -> dict[str, object]:
    replan = manager.contract_warmup(
        ContractWarmupRequest(
            symbol=unit["symbol"],
            contract=unit["contract"],
            through=date.fromisoformat(unit["through"]),
            frequency=_require_unit_frequency(unit.get("frequency")),
        )
    )
    plan = getattr(replan, "plan", None)
    plan_sha256 = getattr(plan, "plan_sha256", None)
    target_windows = getattr(plan, "target_windows", None)
    frozen_targets = unit.get("targets")
    if not isinstance(target_windows, (list, tuple)) or not isinstance(
        frozen_targets, list
    ):
        raise RecoveryError("SOURCE_ISOLATION_READBACK_FAILED")
    try:
        targets_match = _canonical_json(target_windows) == _canonical_json(
            frozen_targets
        )
    except (TypeError, ValueError):
        targets_match = False
    if not isinstance(plan_sha256, str) or (
        plan_sha256 != unit.get("plan_sha256") or not targets_match
    ):
        raise RecoveryError("SOURCE_ISOLATION_READBACK_FAILED")
    return {
        "status": "passed",
        "plan_sha256": plan_sha256,
        "remaining_target_count": len(frozen_targets),
        "target_identity_sha256": hashlib.sha256(
            _canonical_json(frozen_targets).encode("utf-8")
        ).hexdigest(),
    }


def run_bounded_units(
    units: tuple[_T, ...],
    execute: Callable[[_T], Mapping[str, object]],
) -> dict[str, object]:
    if not units or len(units) > 20:
        raise RecoveryError("BATCH_SCOPE_INVALID")
    completed: list[_T] = []
    for index, unit in enumerate(units):
        try:
            result = execute(unit)
        except Exception:  # noqa: BLE001 - public result never includes raw exception
            result = {"status": "failed"}
        if result.get("status") not in {"passed", "noop"}:
            return {
                "status": "partial" if completed else "failed",
                "completed": tuple(completed),
                "failed": unit,
                "unattempted": tuple(units[index + 1 :]),
                "retries": 0,
            }
        completed.append(unit)
    return {
        "status": "passed",
        "completed": tuple(completed),
        "failed": None,
        "unattempted": (),
        "retries": 0,
    }


def prepare_bounded_units(
    *,
    manager: Any,
    adapter: Any,
    requests: tuple[ContractWarmupRequest, ...],
    expected_data_root: Path,
    code_commit: str,
    execution_code_sha256: str,
    config_sha256: str,
    continuation_policy: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """Freeze native W1 or 60m plans without a client."""
    if not requests or len(requests) > 20:
        raise RecoveryError("BATCH_SCOPE_INVALID")
    if (
        re.fullmatch(r"[0-9a-f]{40}", code_commit) is None
        or re.fullmatch(r"[0-9a-f]{64}", execution_code_sha256) is None
        or re.fullmatch(r"[0-9a-f]{64}", config_sha256) is None
    ):
        raise RecoveryError("EXECUTION_IDENTITY_INVALID")
    actual_root = Path(manager.catalog.canonical_root).resolve()
    if actual_root != Path(expected_data_root).resolve():
        raise RecoveryError("CANONICAL_ROOT_MISMATCH")
    frequencies = {
        getattr(request.frequency, "value", request.frequency)
        for request in requests
    }
    if len(frequencies) != 1:
        raise RecoveryError("RECOVERY_SCOPE_INVALID")
    unit_frequency = _require_unit_frequency(next(iter(frequencies)))
    allowed_targets = _allowed_target_frequencies(unit_frequency)
    for request in requests:
        if request.apply:
            raise RecoveryError("RECOVERY_SCOPE_INVALID")

    policy = _validated_continuation_policy(continuation_policy)
    if policy is not None and unit_frequency != "1w":
        raise RecoveryError("RECOVERY_SCOPE_INVALID")
    units: list[dict[str, object]] = []
    for request in requests:
        readonly_request = ContractWarmupRequest(
            request.symbol,
            request.contract,
            request.through,
            frequency=unit_frequency,
        )
        plan, targets = manager._contract_warmup_plan(readonly_request)
        if (
            request.expected_plan_sha256 is not None
            and request.expected_plan_sha256 != plan.plan_sha256
        ):
            raise RecoveryError("CONTRACT_WARMUP_PLAN_CHANGED")
        target_frequencies = {target.key.frequency.value for target in targets}
        if not target_frequencies <= allowed_targets:
            raise RecoveryError("RECOVERY_SCOPE_INVALID")
        if unit_frequency == "60m":
            source_requests: tuple[ExchangeDailySourceRequest, ...] = ()
        else:
            bar_requests = tuple(
                BarFetchRequest(target.key, target.missing)
                for target in targets
                if target.key.frequency.value in allowed_targets
            )
            source_requests = (
                adapter.exchange_daily_source_requests(bar_requests)
                if bar_requests
                else ()
            )
            if any(item.contract != plan.contract for item in source_requests):
                raise RecoveryError("SOURCE_SCOPE_INVALID")
        units.append(
            {
                "symbol": plan.symbol,
                "contract": plan.contract,
                "through": plan.requested_through.isoformat(),
                "frequency": unit_frequency,
                "plan_sha256": plan.plan_sha256,
                "listed_date": plan.listed_date.isoformat(),
                "expired_date": plan.expired_date.isoformat(),
                "effective_through": plan.effective_through.isoformat(),
                "target_count": len(targets),
                "expected_bar_count": plan.expected_bar_count,
                "provider_request_count": plan.provider_request_count,
                "targets": [dict(item) for item in plan.target_windows],
                "source_requests": [_request_payload(item) for item in source_requests],
            }
        )
    manifest: dict[str, object] = {
        "schema_version": _prepare_schema(unit_frequency),
        "code_commit": code_commit,
        "execution_code_sha256": execution_code_sha256,
        "config_sha256": config_sha256,
        "canonical_root_sha256": hashlib.sha256(
            str(actual_root).encode("utf-8")
        ).hexdigest(),
        "unit_count": len(units),
        "units": units,
    }
    if policy is not None:
        manifest["continuation_policy"] = policy
    return manifest


def execute_prepared_batch(
    *,
    manifest: Mapping[str, Any],
    attempt_dir: Path,
    prepared_sha256: str,
    current_code_commit: str,
    current_execution_code_sha256: str,
    current_config_sha256: str,
    current_canonical_root_sha256: str,
    open_unit: Callable[
        [AttemptJournal, Mapping[str, Any]],
        tuple[
            Any,
            Callable[[], None],
            Callable[[], Mapping[str, object]],
            Callable[[], None],
        ],
    ],
) -> dict[str, object]:
    """Execute one frozen batch serially; any failure leaves the tail untouched."""
    unit_frequency = _frequency_for_prepare_schema(manifest.get("schema_version"))
    if (
        manifest.get("code_commit") != current_code_commit
        or manifest.get("execution_code_sha256") != current_execution_code_sha256
        or manifest.get("config_sha256") != current_config_sha256
        or manifest.get("canonical_root_sha256") != current_canonical_root_sha256
    ):
        raise RecoveryError("EXECUTION_IDENTITY_CHANGED")
    units = manifest.get("units")
    if not isinstance(units, list) or not 1 <= len(units) <= 20:
        raise RecoveryError("BATCH_SCOPE_INVALID")
    if re.fullmatch(r"[0-9a-f]{64}", prepared_sha256) is None:
        raise RecoveryError("PREPARED_MANIFEST_INVALID")
    policy = _validated_continuation_policy(manifest.get("continuation_policy"))
    if policy is not None and unit_frequency != "1w":
        raise RecoveryError("RECOVERY_SCOPE_INVALID")
    receipt = {
        "schema_version": _INVOCATION_SCHEMA[unit_frequency],
        "prepared_sha256": prepared_sha256,
        "code_commit": current_code_commit,
        "execution_code_sha256": current_execution_code_sha256,
        "config_sha256": current_config_sha256,
        "canonical_root_sha256": current_canonical_root_sha256,
        "unit_count": len(units),
    }
    if policy is not None:
        receipt["continuation_policy_sha256"] = policy["policy_sha256"]
    _write_json_exclusive(
        Path(attempt_dir) / "invocation-receipt.json",
        receipt,
    )
    completed: list[dict[str, object]] = []
    isolated: list[dict[str, object]] = []
    for index, raw_unit in enumerate(units):
        if not isinstance(raw_unit, dict):
            raise RecoveryError("PREPARED_MANIFEST_INVALID")
        unit = _validated_unit(raw_unit, unit_frequency=unit_frequency)
        unit_id = f"unit-{index + 1:03d}-{unit['symbol']}-{unit['contract']}"
        unit_dir = create_attempt_directory(attempt_dir, unit_id)

        def validated_unit_dir() -> Path:
            return _validated_direct_child_directory(
                unit_dir,
                Path(attempt_dir),
                "SOURCE_EVIDENCE_PATH_INVALID",
            )

        observer = AttemptJournal(
            unit_dir,
            tuple(
                _source_request_from_payload(item) for item in unit["source_requests"]
            ),
        )
        opened = open_unit(observer, unit)
        manager, invalidate_projection, post_commit_readback, cleanup = opened
        request = ContractWarmupRequest(
            symbol=unit["symbol"],
            contract=unit["contract"],
            through=date.fromisoformat(unit["through"]),
            expected_plan_sha256=unit["plan_sha256"],
            apply=True,
            frequency=unit_frequency,
        )
        try:
            try:
                result = manager.contract_warmup(
                    request,
                    before_apply=invalidate_projection,
                )
            except Exception as exc:  # noqa: BLE001 - raw provider/storage text is forbidden
                safe_unit_dir = validated_unit_dir()
                observer.mark_failed(_error_code(exc))
                failure = {
                    **unit,
                    "status": "failed",
                    "error_code": _error_code(exc),
                    "attempt": read_attempt_outcome(safe_unit_dir),
                }
                _write_json_exclusive(safe_unit_dir / "unit-result.json", failure)
                return _finish_batch(
                    attempt_dir,
                    _batch_result(
                        completed,
                        failure,
                        units[index + 1 :],
                        isolated=isolated,
                    ),
                )
            validated_unit_dir()
            result_payload = {
                "status": result.status,
                "applied": result.applied,
                "blocked": result.blocked,
                "failed": result.failed,
                "provider_requests": result.provider_requests,
                "failures": [dict(item) for item in result.failures],
            }
            if result.status not in {"passed", "noop"}:
                observer.mark_failed("RECOVERY_RESULT_NOT_PASSED")
                safe_unit_dir = validated_unit_dir()
                failure = {
                    **unit,
                    "status": result.status,
                    "result": result_payload,
                    "attempt": read_attempt_outcome(safe_unit_dir),
                }
                if policy is not None:
                    isolation_failure_reason = "SOURCE_ISOLATION_EVIDENCE_FAILED"
                    try:
                        source_evidence = _source_isolation_evidence(
                            safe_unit_dir,
                            unit,
                            result_payload,
                            policy,
                            expected_parent=Path(attempt_dir),
                        )
                        isolation_failure_reason = "SOURCE_ISOLATION_READBACK_FAILED"
                        readback = _zero_commit_readback(manager, unit)
                    except RecoveryError as exc:
                        if str(exc) == "SOURCE_EVIDENCE_PATH_INVALID":
                            raise
                        failure["isolation_failure_reason"] = (
                            isolation_failure_reason
                        )
                    else:
                        isolation = {
                            **failure,
                            "status": "isolated",
                            "classification": source_evidence["classification"],
                            "source_evidence": source_evidence,
                            "readback": readback,
                        }
                        safe_unit_dir = validated_unit_dir()
                        _write_json_exclusive(
                            safe_unit_dir / "unit-result.json", isolation
                        )
                        isolated.append(isolation)
                        continue
                safe_unit_dir = validated_unit_dir()
                _write_json_exclusive(safe_unit_dir / "unit-result.json", failure)
                return _finish_batch(
                    attempt_dir,
                    _batch_result(
                        completed,
                        failure,
                        units[index + 1 :],
                        isolated=isolated,
                    ),
                )
            try:
                replan = manager.contract_warmup(
                    ContractWarmupRequest(
                        symbol=unit["symbol"],
                        contract=unit["contract"],
                        through=date.fromisoformat(unit["through"]),
                        frequency=unit_frequency,
                    )
                )
                if replan.plan.target_windows:
                    raise RecoveryError("READBACK_REPLAN_REMAINS")
                readback = dict(post_commit_readback())
            except Exception as exc:  # noqa: BLE001 - post-commit state is reported, never retried
                code = _error_code(exc)
                if code == "RECOVERY_EXECUTION_FAILED":
                    code = "POST_COMMIT_READBACK_FAILED"
                safe_unit_dir = validated_unit_dir()
                observer.mark_failed(code)
                failure = {
                    **unit,
                    "status": "partial" if result.applied else "failed",
                    "error_code": code,
                    "result": result_payload,
                    "attempt": read_attempt_outcome(safe_unit_dir),
                }
                _write_json_exclusive(safe_unit_dir / "unit-result.json", failure)
                return _finish_batch(
                    attempt_dir,
                    _batch_result(
                        completed,
                        failure,
                        units[index + 1 :],
                        isolated=isolated,
                    ),
                )
            safe_unit_dir = validated_unit_dir()
            success = {
                **unit,
                "status": result.status,
                "result": result_payload,
                "replan_sha256": replan.plan.plan_sha256,
                "remaining_target_count": 0,
                "attempt": read_attempt_outcome(safe_unit_dir),
                "readback": readback,
            }
            _write_json_exclusive(safe_unit_dir / "unit-result.json", success)
            completed.append(success)
        finally:
            cleanup()
    batch_result: dict[str, object] = {
        "status": "partial" if isolated else "passed",
        "completed": completed,
        "failed": None,
        "unattempted": [],
        "retries": 0,
    }
    if isolated:
        batch_result["isolated"] = isolated
    return _finish_batch(attempt_dir, batch_result)


def write_prepared_manifest(
    output_root: Path,
    name: str,
    manifest: Mapping[str, Any],
) -> tuple[Path, str]:
    root = Path(output_root)
    try:
        info = root.lstat()
    except OSError as exc:
        raise RecoveryError("OUTPUT_ROOT_UNSAFE") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RecoveryError("OUTPUT_ROOT_UNSAFE")
    if _ATTEMPT_ID.fullmatch(name) is None:
        raise RecoveryError("ATTEMPT_PATH_INVALID")
    path = root / f"{name}.prepare.json"
    try:
        digest = _write_json_exclusive(path, manifest)
    except FileExistsError as exc:
        raise RecoveryError("PREPARED_MANIFEST_EXISTS") from exc
    except OSError as exc:
        raise RecoveryError("PREPARED_MANIFEST_UNAVAILABLE") from exc
    return path, digest


def load_prepared_manifest(
    path: Path,
    expected_sha256: str,
) -> dict[str, Any]:
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise RecoveryError("PREPARED_MANIFEST_HASH_MISMATCH")
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
        payload = json.loads(content)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RecoveryError("PREPARED_MANIFEST_INVALID") from exc
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise RecoveryError("PREPARED_MANIFEST_HASH_MISMATCH")
    if not isinstance(payload, dict):
        raise RecoveryError("PREPARED_MANIFEST_INVALID")
    return payload


def _request_payload(request: ExchangeDailySourceRequest) -> dict[str, object]:
    return {
        "method": "futures.get_exchange_daily",
        "contract": request.contract,
        "start": request.start.isoformat(),
        "end": request.end.isoformat(),
        "expected_dates": [day.isoformat() for day in request.expected_dates],
    }


def _source_scalar(value: Any) -> str | int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value) if math.isfinite(value) else None
    item = getattr(value, "item", None)
    if callable(item):
        return _source_scalar(item())
    raise RecoveryError("SOURCE_RESPONSE_VALUE_INVALID")


def _validate_response_identity(
    request: ExchangeDailySourceRequest,
    response: tuple[dict[str, Any], ...],
) -> None:
    dates: list[date] = []
    try:
        for row in response:
            raw = row["date"]
            if isinstance(raw, datetime):
                parsed = raw.date()
            elif isinstance(raw, date):
                parsed = raw
            elif isinstance(raw, str):
                try:
                    parsed = date.fromisoformat(raw)
                except ValueError:
                    parsed = datetime.fromisoformat(raw).date()
            else:
                parsed = raw.to_pydatetime().date()
            dates.append(parsed)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise RecoveryError("SOURCE_RESPONSE_IDENTITY_INVALID") from exc
    if tuple(dates) != request.expected_dates or len(set(dates)) != len(dates):
        raise RecoveryError("SOURCE_RESPONSE_IDENTITY_INVALID")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _source_request_from_payload(
    value: Mapping[str, Any],
) -> ExchangeDailySourceRequest:
    try:
        if value.get("method") != "futures.get_exchange_daily":
            raise ValueError
        expected_dates = tuple(
            date.fromisoformat(item) for item in value["expected_dates"]
        )
        request = ExchangeDailySourceRequest(
            contract=str(value["contract"]),
            start=date.fromisoformat(value["start"]),
            end=date.fromisoformat(value["end"]),
            expected_dates=expected_dates,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RecoveryError("PREPARED_MANIFEST_INVALID") from exc
    if (
        not expected_dates
        or request.start != min(expected_dates)
        or request.end != max(expected_dates)
        or tuple(sorted(set(expected_dates))) != expected_dates
    ):
        raise RecoveryError("PREPARED_MANIFEST_INVALID")
    return request


def _validated_unit(
    value: Mapping[str, Any],
    *,
    unit_frequency: str,
) -> dict[str, Any]:
    expected_frequency = _require_unit_frequency(unit_frequency)
    try:
        unit = dict(value)
        symbol = str(unit["symbol"])
        contract = str(unit["contract"])
        through = str(unit["through"])
        plan_sha256 = str(unit["plan_sha256"])
        source_requests = unit["source_requests"]
    except (KeyError, TypeError, ValueError) as exc:
        raise RecoveryError("PREPARED_MANIFEST_INVALID") from exc
    if (
        re.fullmatch(r"[a-z]{1,8}", symbol) is None
        or re.fullmatch(r"[A-Z]{1,8}[0-9]{3,4}", contract) is None
        or unit.get("frequency") != expected_frequency
        or re.fullmatch(r"[0-9a-f]{64}", plan_sha256) is None
        or not isinstance(source_requests, list)
        or (expected_frequency == "60m" and source_requests)
    ):
        raise RecoveryError("PREPARED_MANIFEST_INVALID")
    try:
        date.fromisoformat(through)
    except ValueError as exc:
        raise RecoveryError("PREPARED_MANIFEST_INVALID") from exc
    return unit


def _error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and re.fullmatch(r"[A-Z0-9_]{1,64}", code):
        return code
    if isinstance(exc, RecoveryError) and re.fullmatch(r"[A-Z0-9_]{1,64}", str(exc)):
        return str(exc)
    return "RECOVERY_EXECUTION_FAILED"


def _batch_result(
    completed: list[dict[str, object]],
    failure: dict[str, object],
    unattempted: list[dict[str, Any]],
    *,
    isolated: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    isolated_units = isolated or []
    nested = failure.get("result")
    applied = nested.get("applied", 0) if isinstance(nested, Mapping) else 0
    result: dict[str, object] = {
        "status": (
            "partial"
            if completed
            or isolated_units
            or failure.get("status") == "partial"
            or applied
            else "failed"
        ),
        "completed": completed,
        "failed": failure,
        "unattempted": unattempted,
        "retries": 0,
    }
    if isolated_units:
        result["isolated"] = isolated_units
    return result


def _finish_batch(
    attempt_dir: Path,
    result: dict[str, object],
) -> dict[str, object]:
    _write_json_exclusive(Path(attempt_dir) / "batch-result.json", result)
    return result


def _write_json_exclusive(path: Path, payload: object) -> str:
    content = (_canonical_json(payload) + "\n").encode("utf-8")
    fd = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        os.write(fd, content)
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_directory(path.parent)
    return hashlib.sha256(content).hexdigest()


def _read_json_file(path: Path, *, maximum: int = 16 * 1024 * 1024) -> Any:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
                raise OSError
            content = os.read(fd, maximum + 1)
            if len(content) != info.st_size:
                raise OSError
        finally:
            os.close(fd)
        return json.loads(content)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RecoveryError("INPUT_INVALID") from exc


def _current_code_commit(project_root: Path | None = None) -> str:
    root = project_root or Path(__file__).resolve().parents[1]
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        commit = completed.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise RecoveryError("CODE_IDENTITY_UNAVAILABLE") from exc
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise RecoveryError("CODE_IDENTITY_UNAVAILABLE")
    return commit


def _current_execution_code_sha256() -> str:
    project_root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    try:
        for relative in _EXECUTION_CODE_PATHS:
            path = project_root / relative
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise OSError
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    except OSError as exc:
        raise RecoveryError("CODE_IDENTITY_UNAVAILABLE") from exc
    return digest.hexdigest()


def _require_clean_execution_checkout(
    expected_commit: str,
    *,
    project_root: Path | None = None,
) -> None:
    """Require every tracked/untracked repository input to match one exact commit."""
    root = project_root or Path(__file__).resolve().parents[1]
    current_commit = (
        _current_code_commit()
        if project_root is None
        else _current_code_commit(project_root)
    )
    if current_commit != expected_commit:
        raise RecoveryError("EXECUTION_IDENTITY_CHANGED")
    try:
        completed = subprocess.run(
            [
                "git",
                "-c",
                "core.fsmonitor=false",
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RecoveryError("CODE_IDENTITY_UNAVAILABLE") from exc
    if completed.stdout:
        raise RecoveryError("EXECUTION_CHECKOUT_DIRTY")


def _post_commit_readback(
    manager: Any,
    unit: Mapping[str, Any],
) -> dict[str, object]:
    """Verify committed targets through Catalog, physical files and MDS."""
    from app.market_data.domain import DatasetKey, SeriesKind, SeriesQuery
    from app.market_data.market_data_service import MarketDataService

    targets = unit.get("targets")
    if not isinstance(targets, list) or not targets:
        raise RecoveryError("POST_COMMIT_READBACK_INVALID")
    root = Path(manager.catalog.canonical_root).resolve()
    service = MarketDataService(manager.catalog, manager.store)
    partitions: list[dict[str, object]] = []
    for raw in targets:
        try:
            if not isinstance(raw, Mapping):
                raise ValueError
            dataset = raw["dataset"]
            if not isinstance(dataset, list) or len(dataset) != 4:
                raise ValueError
            key = DatasetKey(*dataset)
            year = int(raw["year"])
            month = int(raw["month"])
            expected_start = datetime.fromisoformat(str(raw["expected_start"]))
            expected_end = datetime.fromisoformat(str(raw["expected_end"]))
            expected_count = int(raw["expected_bar_count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RecoveryError("POST_COMMIT_READBACK_INVALID") from exc
        if (
            key.kind.value != "contract"
            or key.symbol != unit["symbol"]
            or key.series_or_contract != unit["contract"]
            or key.frequency.value not in _allowed_target_frequencies(
                _require_unit_frequency(unit.get("frequency") or "1w")
            )
            or expected_start.tzinfo is None
            or expected_end.tzinfo is None
            or expected_start > expected_end
            or expected_count <= 0
        ):
            raise RecoveryError("POST_COMMIT_READBACK_INVALID")
        rows = tuple(
            item
            for item in manager.catalog.all_partitions(key)
            if (item.year, item.month) == (year, month)
        )
        if len(rows) != 1:
            raise RecoveryError("POST_COMMIT_CATALOG_INVALID")
        partition = rows[0]
        path = Path(partition.file_path)
        try:
            info = path.lstat()
            resolved = path.resolve()
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or not resolved.is_relative_to(root)
            ):
                raise OSError
            physical = manager.store.read_catalog_partition(partition)
            content_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise RecoveryError("POST_COMMIT_PHYSICAL_INVALID") from exc
        if len(physical) != partition.row_count:
            raise RecoveryError("POST_COMMIT_PHYSICAL_INVALID")
        result = service.query(
            SeriesQuery(
                series_kind=SeriesKind.CONTRACT,
                symbol=key.symbol,
                contract=key.series_or_contract,
                frequency=key.frequency,
                start=expected_start - timedelta(microseconds=1),
                end=expected_end,
            )
        )
        if (
            len(result.bars) != expected_count
            or result.bars[0].bar_end != expected_start
            or result.bars[-1].bar_end != expected_end
        ):
            raise RecoveryError("POST_COMMIT_MDS_INVALID")
        partitions.append(
            {
                "dataset": list(key.as_tuple()),
                "year": year,
                "month": month,
                "file_sha256": content_sha256,
                "catalog_row_count": partition.row_count,
                "physical_row_count": len(physical),
                "mds_bar_count": len(result.bars),
            }
        )
    return {
        "catalog_physical_mds": "passed",
        "mds_target_count": len(targets),
        "catalog_partitions": partitions,
    }


def _open_execution_environment(
    project_env: Path,
    observer: AttemptJournal | None = None,
) -> _ExecutionEnvironment:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.core.env import PROJECT_ROOT
    from app.db.url import normalize_database_url
    from app.market_data.composition import build_historical_data_manager

    settings, identity = load_private_execution_settings(project_env)
    engine = create_engine(
        normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True
    )
    session = Session(engine, autoflush=False)
    try:
        manager = build_historical_data_manager(
            session,
            data_root=Path(settings["GUIYI_CANONICAL_DATA_ROOT"]),
            config_root=PROJECT_ROOT,
            provider_settings=settings,
            source_observer=observer,
        )
    except Exception:
        session.close()
        engine.dispose()
        raise

    def close() -> None:
        try:
            session.close()
        finally:
            engine.dispose()

    return _ExecutionEnvironment(
        manager=manager,
        adapter=manager.provider,
        settings=settings,
        identity=identity,
        close=close,
    )


def _require_execution_identity(
    environment: _ExecutionEnvironment,
    expected_identity: Mapping[str, str],
) -> _ExecutionEnvironment:
    if environment.identity != expected_identity:
        environment.close()
        raise RecoveryError("EXECUTION_IDENTITY_CHANGED")
    return environment


def _unit_requests(value: Any) -> tuple[ContractWarmupRequest, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise RecoveryError("BATCH_SCOPE_INVALID")
    result: list[ContractWarmupRequest] = []
    try:
        for item in value:
            if not isinstance(item, dict) or set(item) - {
                "symbol",
                "contract",
                "through",
                "frequency",
                "expected_plan_sha256",
            }:
                raise ValueError
            result.append(
                ContractWarmupRequest(
                    symbol=str(item["symbol"]),
                    contract=str(item["contract"]),
                    through=date.fromisoformat(item["through"]),
                    expected_plan_sha256=item.get("expected_plan_sha256"),
                    frequency=item.get("frequency"),
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise RecoveryError("INPUT_INVALID") from exc
    return tuple(result)


def main(
    argv: list[str] | None = None,
    *,
    stdout=sys.stdout,
) -> int:
    payload: dict[str, object]
    try:
        args = parser().parse_args(argv)
        if args.mode == "inspect":
            payload = {
                "schema_version": "newow_weekly_recovery_result_v1",
                "status": "inspected",
                "attempt": read_attempt_outcome(Path(args.attempt)),
            }
            code = 0
        elif args.mode == "prepare":
            code_commit = _current_code_commit()
            _require_clean_execution_checkout(code_commit)
            environment = _open_execution_environment(Path(args.project_env))
            try:
                requests = _unit_requests(_read_json_file(Path(args.units)))
                unit_frequency = _require_unit_frequency(
                    getattr(requests[0].frequency, "value", requests[0].frequency)
                )
                if args.isolate_known_source_quality and unit_frequency != "1w":
                    raise RecoveryError("RECOVERY_SCOPE_INVALID")
                lease = environment.manager.catalog.acquire_maintenance_lock()
                maintenance_available = lease is not None
                if lease is not None:
                    lease.release()
                manifest = prepare_bounded_units(
                    manager=environment.manager,
                    adapter=environment.adapter,
                    requests=requests,
                    expected_data_root=Path(
                        environment.settings.get(
                            "GUIYI_CANONICAL_DATA_ROOT",
                            environment.manager.catalog.canonical_root,
                        )
                    ),
                    code_commit=code_commit,
                    execution_code_sha256=_current_execution_code_sha256(),
                    config_sha256=environment.identity["config_sha256"],
                    continuation_policy=(
                        source_isolation_policy(unit_frequency=unit_frequency)
                        if args.isolate_known_source_quality
                        else None
                    ),
                )
                manifest["maintenance_lock_available"] = maintenance_available
                path, digest = write_prepared_manifest(
                    Path(args.output_root), args.name, manifest
                )
            finally:
                environment.close()
            payload = {
                "schema_version": _result_schema(unit_frequency),
                "status": "prepared",
                "readonly": True,
                "prepared_file": str(path),
                "prepared_sha256": digest,
                "unit_count": manifest["unit_count"],
                "maintenance_lock_available": maintenance_available,
                "provider_requests": 0,
                "writes": 0,
            }
            code = 0
        else:
            prepared = load_prepared_manifest(
                Path(args.prepared), args.expected_prepared_sha256
            )
            unit_frequency = _frequency_for_prepare_schema(
                prepared.get("schema_version")
            )
            expected_commit = prepared.get("code_commit")
            if not isinstance(expected_commit, str):
                raise RecoveryError("PREPARED_MANIFEST_INVALID")
            _require_clean_execution_checkout(expected_commit)
            _settings, identity = load_private_execution_settings(
                Path(args.project_env)
            )
            attempt = create_attempt_directory(Path(args.output_root), args.attempt_id)

            def open_unit(observer, _unit):
                _require_clean_execution_checkout(expected_commit)
                environment = _require_execution_identity(
                    _open_execution_environment(Path(args.project_env), observer),
                    identity,
                )
                from app.market_data.market_home_projection import (
                    MarketHomeProjectionStore,
                    market_home_projection_path,
                )

                invalidate = MarketHomeProjectionStore(
                    market_home_projection_path(
                        environment.manager.catalog.canonical_root
                    )
                ).invalidate
                return (
                    environment.manager,
                    invalidate,
                    lambda: _post_commit_readback(environment.manager, _unit),
                    environment.close,
                )

            result = execute_prepared_batch(
                manifest=prepared,
                attempt_dir=attempt,
                prepared_sha256=args.expected_prepared_sha256,
                current_code_commit=_current_code_commit(),
                current_execution_code_sha256=_current_execution_code_sha256(),
                current_config_sha256=identity["config_sha256"],
                current_canonical_root_sha256=identity["canonical_root_sha256"],
                open_unit=open_unit,
            )
            payload = {
                "schema_version": _result_schema(unit_frequency),
                "status": result["status"],
                "readonly": False,
                "attempt_dir": str(attempt),
                "result": result,
            }
            code = 0 if result["status"] == "passed" else 1
    except (RecoveryError, ValueError) as exc:
        payload = {
            "schema_version": "newow_weekly_recovery_error_v1",
            "status": "failed",
            "error_code": _error_code(exc),
        }
        code = 1
    except Exception:
        payload = {
            "schema_version": "newow_weekly_recovery_error_v1",
            "status": "failed",
            "error_code": "RECOVERY_EXECUTION_FAILED",
        }
        code = 1
    stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    stdout.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
