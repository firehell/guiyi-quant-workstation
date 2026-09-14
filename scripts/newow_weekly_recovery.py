"""Bounded, auditable Newow W1/D1 recovery orchestration."""

from __future__ import annotations

import argparse
from datetime import date, datetime
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
    "services/quant-api/app/market_data/composition.py",
    "services/quant-api/app/market_data/rqdata_adapter.py",
    "services/quant-api/app/market_data/historical_data_manager.py",
    "services/quant-api/app/market_data/canonical_store.py",
    "services/quant-api/app/market_data/catalog.py",
    "services/quant-api/app/market_data/coverage_source.py",
    "services/quant-api/app/market_data/market_home_projection.py",
)
_T = TypeVar("_T")


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
        description="Prepare or execute one bounded Newow W1/D1 recovery batch."
    )
    commands = value.add_subparsers(dest="mode", required=True)
    prepare = commands.add_parser("prepare", allow_abbrev=False)
    prepare.add_argument("--project-env", required=True)
    prepare.add_argument("--units", required=True)
    prepare.add_argument("--output-root", required=True)
    prepare.add_argument("--name", required=True)
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
        from app.market_data.closeout_binding import literal_settings
        from app.market_data.rqdata_adapter import runtime_provider_settings

        settings = literal_settings(content)
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
        self.allowed_requests = tuple(allowed_requests)
        if len(set(self.allowed_requests)) != len(
            self.allowed_requests
        ):
            raise RecoveryError("SOURCE_SCOPE_INVALID")
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
        fd = os.open(
            self.attempt_dir / "journal.jsonl",
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
        name = f"source-response-{sequence:04d}.json"
        target = self.attempt_dir / name
        temporary = self.attempt_dir / f".{name}.tmp"
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
        _fsync_directory(self.attempt_dir)
        return name, hashlib.sha256(content).hexdigest()


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
    path = Path(attempt_dir) / "journal.jsonl"
    try:
        records = tuple(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        )
    except (OSError, ValueError, TypeError) as exc:
        raise RecoveryError("SOURCE_JOURNAL_INVALID") from exc
    started = {
        record.get("sequence")
        for record in records
        if record.get("state") == "started"
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
) -> dict[str, object]:
    """Freeze native W1 plans and adapter-derived source bounds without a client."""
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
    for request in requests:
        frequency = getattr(request.frequency, "value", request.frequency)
        if request.apply or frequency != "1w":
            raise RecoveryError("RECOVERY_SCOPE_INVALID")

    units: list[dict[str, object]] = []
    for request in requests:
        readonly_request = ContractWarmupRequest(
            request.symbol,
            request.contract,
            request.through,
            frequency="1w",
        )
        plan, targets = manager._contract_warmup_plan(readonly_request)
        if (
            request.expected_plan_sha256 is not None
            and request.expected_plan_sha256 != plan.plan_sha256
        ):
            raise RecoveryError("CONTRACT_WARMUP_PLAN_CHANGED")
        bar_requests = tuple(
            BarFetchRequest(target.key, target.missing)
            for target in targets
            if target.key.frequency.value in {"1d", "1w"}
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
                "frequency": "1w",
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
    return {
        "schema_version": "newow_weekly_recovery_prepare_v1",
        "code_commit": code_commit,
        "execution_code_sha256": execution_code_sha256,
        "config_sha256": config_sha256,
        "canonical_root_sha256": hashlib.sha256(
            str(actual_root).encode("utf-8")
        ).hexdigest(),
        "unit_count": len(units),
        "units": units,
    }


def execute_prepared_batch(
    *,
    manifest: Mapping[str, Any],
    attempt_dir: Path,
    current_code_commit: str,
    current_execution_code_sha256: str,
    current_config_sha256: str,
    current_canonical_root_sha256: str,
    open_unit: Callable[[AttemptJournal, Mapping[str, Any]], tuple[Any, Callable[[], None]]],
) -> dict[str, object]:
    """Execute one frozen batch serially; any failure leaves the tail untouched."""
    if manifest.get("schema_version") != "newow_weekly_recovery_prepare_v1":
        raise RecoveryError("PREPARED_MANIFEST_INVALID")
    if (
        manifest.get("code_commit") != current_code_commit
        or manifest.get("execution_code_sha256")
        != current_execution_code_sha256
        or manifest.get("config_sha256") != current_config_sha256
        or manifest.get("canonical_root_sha256")
        != current_canonical_root_sha256
    ):
        raise RecoveryError("EXECUTION_IDENTITY_CHANGED")
    units = manifest.get("units")
    if not isinstance(units, list) or not 1 <= len(units) <= 20:
        raise RecoveryError("BATCH_SCOPE_INVALID")
    completed: list[dict[str, object]] = []
    for index, raw_unit in enumerate(units):
        if not isinstance(raw_unit, dict):
            raise RecoveryError("PREPARED_MANIFEST_INVALID")
        unit = _validated_unit(raw_unit)
        unit_id = f"unit-{index + 1:03d}-{unit['symbol']}-{unit['contract']}"
        unit_dir = create_attempt_directory(attempt_dir, unit_id)
        observer = AttemptJournal(
            unit_dir,
            tuple(
                _source_request_from_payload(item)
                for item in unit["source_requests"]
            ),
        )
        opened = open_unit(observer, unit)
        manager, invalidate_projection = opened[:2]
        cleanup = opened[2] if len(opened) == 3 else lambda: None
        request = ContractWarmupRequest(
            symbol=unit["symbol"],
            contract=unit["contract"],
            through=date.fromisoformat(unit["through"]),
            expected_plan_sha256=unit["plan_sha256"],
            apply=True,
            frequency="1w",
        )
        try:
            try:
                result = manager.contract_warmup(
                    request,
                    before_apply=invalidate_projection,
                )
            except Exception as exc:  # noqa: BLE001 - raw provider/storage text is forbidden
                observer.mark_failed(_error_code(exc))
                failure = {
                    **unit,
                    "status": "failed",
                    "error_code": _error_code(exc),
                    "attempt": read_attempt_outcome(unit_dir),
                }
                _write_json_exclusive(unit_dir / "unit-result.json", failure)
                return _finish_batch(
                    attempt_dir,
                    _batch_result(completed, failure, units[index + 1 :]),
                )
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
                failure = {
                    **unit,
                    "status": result.status,
                    "result": result_payload,
                    "attempt": read_attempt_outcome(unit_dir),
                }
                _write_json_exclusive(unit_dir / "unit-result.json", failure)
                return _finish_batch(
                    attempt_dir,
                    _batch_result(completed, failure, units[index + 1 :]),
                )
            replan = manager.contract_warmup(
                ContractWarmupRequest(
                    symbol=unit["symbol"],
                    contract=unit["contract"],
                    through=date.fromisoformat(unit["through"]),
                    frequency="1w",
                )
            )
            if replan.plan.target_windows:
                observer.mark_failed("READBACK_REPLAN_REMAINS")
                failure = {
                    **unit,
                    "status": "failed",
                    "error_code": "READBACK_REPLAN_REMAINS",
                    "result": result_payload,
                    "replan_sha256": replan.plan.plan_sha256,
                    "remaining_target_count": len(replan.plan.target_windows),
                    "attempt": read_attempt_outcome(unit_dir),
                }
                _write_json_exclusive(unit_dir / "unit-result.json", failure)
                return _finish_batch(
                    attempt_dir,
                    _batch_result(completed, failure, units[index + 1 :]),
                )
            success = {
                **unit,
                "status": result.status,
                "result": result_payload,
                "replan_sha256": replan.plan.plan_sha256,
                "remaining_target_count": 0,
                "attempt": read_attempt_outcome(unit_dir),
                "readback": {
                    "catalog_physical_replan": "passed",
                    "mds_strict_verify_during_publish": True,
                },
            }
            _write_json_exclusive(unit_dir / "unit-result.json", success)
            completed.append(success)
        finally:
            cleanup()
    batch_result: dict[str, object] = {
        "status": "passed",
        "completed": completed,
        "failed": None,
        "unattempted": [],
        "retries": 0,
    }
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
                parsed = date.fromisoformat(raw)
            else:
                parsed = raw.to_pydatetime().date()
            dates.append(parsed)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise RecoveryError("SOURCE_RESPONSE_IDENTITY_INVALID") from exc
    if tuple(dates) != request.expected_dates or len(set(dates)) != len(dates):
        raise RecoveryError("SOURCE_RESPONSE_IDENTITY_INVALID")


def _canonical_json(value: Mapping[str, Any]) -> str:
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


def _source_request_from_payload(value: Mapping[str, Any]) -> ExchangeDailySourceRequest:
    try:
        if value.get("method") != "futures.get_exchange_daily":
            raise ValueError
        expected_dates = tuple(date.fromisoformat(item) for item in value["expected_dates"])
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


def _validated_unit(value: Mapping[str, Any]) -> dict[str, Any]:
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
        or unit.get("frequency") != "1w"
        or re.fullmatch(r"[0-9a-f]{64}", plan_sha256) is None
        or not isinstance(source_requests, list)
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
) -> dict[str, object]:
    result: dict[str, object] = {
        "status": "partial" if completed else "failed",
        "completed": completed,
        "failed": failure,
        "unattempted": unattempted,
        "retries": 0,
    }
    return result


def _finish_batch(
    attempt_dir: Path,
    result: dict[str, object],
) -> dict[str, object]:
    _write_json_exclusive(Path(attempt_dir) / "batch-result.json", result)
    return result


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> str:
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


def _current_code_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
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
    engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
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
            environment = _open_execution_environment(Path(args.project_env))
            try:
                requests = _unit_requests(_read_json_file(Path(args.units)))
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
                    code_commit=_current_code_commit(),
                    execution_code_sha256=_current_execution_code_sha256(),
                    config_sha256=environment.identity["config_sha256"],
                )
                manifest["maintenance_lock_available"] = maintenance_available
                path, digest = write_prepared_manifest(
                    Path(args.output_root), args.name, manifest
                )
            finally:
                environment.close()
            payload = {
                "schema_version": "newow_weekly_recovery_result_v1",
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
            _settings, identity = load_private_execution_settings(
                Path(args.project_env)
            )
            attempt = create_attempt_directory(Path(args.output_root), args.attempt_id)

            def open_unit(observer, _unit):
                environment = _open_execution_environment(
                    Path(args.project_env), observer
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
                return environment.manager, invalidate, environment.close

            result = execute_prepared_batch(
                manifest=prepared,
                attempt_dir=attempt,
                current_code_commit=_current_code_commit(),
                current_execution_code_sha256=_current_execution_code_sha256(),
                current_config_sha256=identity["config_sha256"],
                current_canonical_root_sha256=identity["canonical_root_sha256"],
                open_unit=open_unit,
            )
            payload = {
                "schema_version": "newow_weekly_recovery_result_v1",
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
