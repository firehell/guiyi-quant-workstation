"""Capture one frozen SuBing D1 provider batch without publishing market data."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable, Mapping, Sequence

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.env import PROJECT_ROOT
from app.db.readonly import readonly_transaction
from app.db.url import normalize_database_url
from app.market_data.catalog import MarketCatalog
from app.market_data.composition import build_database_coverage_source

from app.market_data.rqdata_adapter import (
    ExchangeDailySourceRequest,
    RQDataClient,
    _is_rqdata_quota_error,
    _records,
)
from scripts.newow_weekly_recovery import (
    AttemptJournal,
    RecoveryError,
    _canonical_json,
    _current_code_commit,
    _error_code,
    _fsync_directory,
    _request_payload,
    _read_journal_records,
    _require_clean_execution_checkout,
    _source_request_from_payload,
    _source_scalar,
    _write_json_exclusive,
    create_attempt_directory,
    load_private_execution_settings,
    load_private_readonly_settings,
    read_attempt_outcome,
)


_SCHEMA_V1 = "subing-d1-source-verification-candidate-v1"
_SCHEMA_V2 = "subing-d1-source-verification-candidate-v2"
_SCHEMA_RECOVERY = "subing-d1-source-response-recovery-candidate-v1"
_VALIDATOR_VERSION = "subing-d1-response-validator-v2"
_CONTINUATION_ORDER = (13, 14, 11, 12, 9, 10, 15)
_EVIDENCE_ROOT = PROJECT_ROOT / "outputs/subing-four-period-readiness-20260918"
_HASH = re.compile(r"[0-9a-f]{64}")
_ATTEMPT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_CONTRACT = re.compile(r"[A-Z]{1,8}[0-9]{3,4}")
_SYMBOL = re.compile(r"[a-z]{1,8}")
_RAW_FIELDS = (
    "order_book_id",
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
_EXPECTED_TOP_LEVEL = {
    "schema",
    "execute",
    "fixed_cutoff",
    "provider",
    "method",
    "requests",
    "budget",
    "execution_contract",
    "plan_sha256",
}
_EXPECTED_REQUEST_FIELDS = {
    "symbol",
    "contract",
    "frequency",
    "month",
    "expected_dates",
    "reason_codes",
    "request_sha256",
}
_EXPECTED_REQUEST_FIELDS_V2 = {
    "symbol",
    "contract",
    "frequency",
    "month",
    "start",
    "end",
    "target_dates",
    "allowed_response_dates",
    "calendar_authority",
    "reason_codes",
    "request_sha256",
}


@dataclass(frozen=True, slots=True)
class FrozenRequest:
    symbol: str
    transport: ExchangeDailySourceRequest
    target_dates: tuple[date, ...]
    allowed_response_dates: tuple[date, ...]
    calendar_authority: Mapping[str, Any] | None
    request_sha256: str


@dataclass(frozen=True, slots=True)
class FrozenBatch:
    candidate: Mapping[str, Any]
    selections: tuple[FrozenRequest, ...]

    @property
    def requests(self) -> tuple[ExchangeDailySourceRequest, ...]:
        return tuple(item.transport for item in self.selections)

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(item.symbol for item in self.selections)

    @property
    def request_hashes(self) -> tuple[str, ...]:
        return tuple(item.request_sha256 for item in self.selections)


class D1SourceAttemptJournal(AttemptJournal):
    """Persist contract identity with the unmodified source scalars."""

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
                    field: (
                        row[field]
                        if field == "order_book_id" and isinstance(row[field], str)
                        else _source_scalar(row[field])
                    )
                    for field in _RAW_FIELDS
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
            if os.write(fd, content) != len(content):
                raise OSError("RECEIPT_SHORT_WRITE")
            os.fsync(fd)
        finally:
            os.close(fd)
        if target.exists() or target.is_symlink():
            temporary.unlink(missing_ok=True)
            raise OSError
        os.replace(temporary, target)
        _fsync_directory(attempt_dir)
        return name, hashlib.sha256(content).hexdigest()

    def after_response(
        self,
        request: ExchangeDailySourceRequest,
        response: tuple[dict[str, Any], ...],
    ) -> None:
        """Save the full transport response before target-aware validation."""
        sequence = self._started.get(request)
        if sequence is None:
            raise RecoveryError("SOURCE_RESPONSE_WITHOUT_START")
        try:
            payload_file, payload_sha256 = self._write_payload(
                sequence, request, response
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


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Capture a frozen D1 source-only batch without data writes."
    )
    commands = value.add_subparsers(dest="mode", required=True)
    for name in ("preflight", "execute"):
        command = commands.add_parser(name, allow_abbrev=False)
        command.add_argument("--project-env", required=True)
        command.add_argument("--candidate", required=True)
        command.add_argument("--expected-plan-sha256", required=True)
        command.add_argument("--output-root", required=True)
        command.add_argument("--attempt-id", required=True)
        if name == "execute":
            command.add_argument(
                "--execute-source-query", action="store_true", required=True
            )
    offline = commands.add_parser("offline-validate", allow_abbrev=False)
    offline.add_argument("--project-env", required=True)
    offline.add_argument("--candidate", required=True)
    offline.add_argument("--expected-plan-sha256", required=True)
    offline.add_argument("--attempt-dir", required=True)
    offline.add_argument("--output", required=True)
    continuation = commands.add_parser("prepare-continuation", allow_abbrev=False)
    continuation.add_argument("--project-env", required=True)
    continuation.add_argument("--candidate", required=True)
    continuation.add_argument("--expected-plan-sha256", required=True)
    continuation.add_argument("--attempt-dir", required=True)
    continuation.add_argument("--output", required=True)
    return value


def _read_json_regular(path: Path, *, maximum: int = 2 * 1024 * 1024) -> dict[str, Any]:
    try:
        if not path.is_absolute() or path.resolve(strict=True) != path:
            raise OSError
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
        value = json.loads(content)
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RecoveryError("SOURCE_CANDIDATE_INVALID") from exc
    if not isinstance(value, dict):
        raise RecoveryError("SOURCE_CANDIDATE_INVALID")
    return value


def _request_digest(request: ExchangeDailySourceRequest) -> str:
    payload = {
        "contract": request.contract,
        "start": request.start.isoformat(),
        "end": request.end.isoformat(),
        "expected_dates": [day.isoformat() for day in request.expected_dates],
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _v2_request_digest(raw: Mapping[str, Any]) -> str:
    payload = {
        key: raw[key]
        for key in (
            "contract",
            "start",
            "end",
            "target_dates",
            "allowed_response_dates",
            "calendar_authority",
        )
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _parse_dates(value: object) -> tuple[date, ...]:
    if not isinstance(value, list) or not value:
        raise RecoveryError("SOURCE_CANDIDATE_INVALID")
    try:
        result = tuple(date.fromisoformat(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise RecoveryError("SOURCE_CANDIDATE_INVALID") from exc
    if tuple(sorted(set(result))) != result:
        raise RecoveryError("SOURCE_CANDIDATE_INVALID")
    return result


def _sha256_file(path: Path) -> str:
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError
        data = path.read_bytes()
    except OSError as exc:
        raise RecoveryError("SOURCE_EVIDENCE_INVALID") from exc
    return hashlib.sha256(data).hexdigest()


def _validated_existing_attempt(path: Path, expected_root: Path) -> Path:
    try:
        root = expected_root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        info = path.lstat()
    except OSError as exc:
        raise RecoveryError("SOURCE_EVIDENCE_PATH_INVALID") from exc
    if (
        not path.is_absolute()
        or path.parent != expected_root
        or resolved.parent != root
        or stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
    ):
        raise RecoveryError("SOURCE_EVIDENCE_PATH_INVALID")
    return resolved


def _validated_evidence_output(
    path: Path, attempt: Path, mode: str, canonical_root: Path
) -> Path:
    expected_name = {
        "offline-validate": "d1-17-source-verification-offline-v2.json",
        "prepare-continuation": "d1-17-source-verification-continuation-candidate.json",
    }[mode]
    root = attempt.parent
    try:
        resolved_root = root.resolve(strict=True)
        resolved_canonical = canonical_root.resolve()
    except OSError as exc:
        raise RecoveryError("SOURCE_EVIDENCE_PATH_INVALID") from exc
    if (
        not path.is_absolute()
        or path.parent != root
        or root != resolved_root
        or path.name != expected_name
        or path.exists()
        or path.is_symlink()
        or path == resolved_canonical
        or resolved_canonical in path.parents
    ):
        raise RecoveryError("SOURCE_EVIDENCE_PATH_INVALID")
    return path


def _authority_selections(
    settings: Mapping[str, str], selections: Sequence[FrozenRequest]
) -> tuple[FrozenRequest, ...]:
    """Bind transport windows to the read-only Catalog/Calendar/Session facts."""
    try:
        engine = create_engine(normalize_database_url(settings["DATABASE_URL"]), pool_pre_ping=True)
        canonical_root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RecoveryError("PROJECT_ENV_UNSAFE") from exc
    result: list[FrozenRequest] = []
    try:
        with Session(engine) as session, readonly_transaction(session):
            catalog = MarketCatalog(session, canonical_root)
            coverage = build_database_coverage_source(session)
            for item in selections:
                request = item.transport
                fact = catalog.contract_fact(item.symbol, request.contract)
                allowed = coverage.contract_trading_days(fact, request.start, request.end)
                authority = _calendar_authority_body(
                    symbol=item.symbol,
                    contract=request.contract,
                    exchange=fact.exchange,
                    listed_date=fact.listed_date,
                    expired_date=fact.expired_date,
                    allowed_dates=allowed,
                )
                if not set(item.target_dates) <= set(allowed):
                    raise RecoveryError("SOURCE_TARGET_DATE_UNPROVEN")
                if item.calendar_authority is not None and (
                    tuple(item.allowed_response_dates) != tuple(allowed)
                    or dict(item.calendar_authority) != authority
                ):
                    raise RecoveryError("SOURCE_CALENDAR_AUTHORITY_DRIFT")
                result.append(
                    FrozenRequest(
                        symbol=item.symbol,
                        transport=request,
                        target_dates=item.target_dates,
                        allowed_response_dates=tuple(allowed),
                        calendar_authority=authority,
                        request_sha256=item.request_sha256,
                    )
                )
    finally:
        engine.dispose()
    return tuple(result)


def _validate_historical_failed_prefix(
    batch: FrozenBatch, attempt: Path
) -> tuple[dict[str, Any], ...]:
    records = _read_journal_records(attempt)
    expected_saved = min(9, len(batch.selections))
    if len(records) != expected_saved * 2 + 1 or records[-1] != {
        "schema_version": 1,
        "sequence": expected_saved,
        "state": "failed",
        "error_code": "SOURCE_RESPONSE_IDENTITY_INVALID",
    }:
        raise RecoveryError("SOURCE_JOURNAL_INVALID")
    saved: list[dict[str, Any]] = []
    for sequence in range(1, expected_saved + 1):
        started = records[(sequence - 1) * 2]
        response = records[(sequence - 1) * 2 + 1]
        if started != {
            "schema_version": 1,
            "sequence": sequence,
            "state": "started",
            "request": _request_payload(batch.requests[sequence - 1]),
        }:
            raise RecoveryError("SOURCE_JOURNAL_INVALID")
        if (
            response.get("schema_version") != 1
            or response.get("sequence") != sequence
            or response.get("state") != "response_saved"
        ):
            raise RecoveryError("SOURCE_JOURNAL_INVALID")
        saved.append(response)
    return tuple(saved)


def offline_validate_attempt(
    batch: FrozenBatch,
    attempt: Path,
    settings: Mapping[str, str],
) -> Mapping[str, Any]:
    """Validate saved response bytes without constructing a provider client."""
    immutable_names = ("invocation-receipt.json", "journal.jsonl", "source-only-result.json")
    before = {name: _sha256_file(attempt / name) for name in immutable_names}
    records = _validate_historical_failed_prefix(batch, attempt)
    raw_before = {
        str(record["payload_file"]): _sha256_file(attempt / str(record["payload_file"]))
        for record in records
    }
    authorities = _authority_selections(settings, batch.selections[: len(records)])
    reports: list[dict[str, Any]] = []
    target_classifications: list[dict[str, Any]] = []
    for sequence, (record, selection) in enumerate(zip(records, authorities, strict=True), 1):
        if record.get("sequence") != sequence:
            raise RecoveryError("SOURCE_JOURNAL_INVALID")
        filename = record.get("payload_file")
        expected_hash = record.get("payload_sha256")
        if filename != f"source-response-{sequence:04d}.json" or not isinstance(expected_hash, str):
            raise RecoveryError("SOURCE_JOURNAL_INVALID")
        raw_path = attempt / filename
        if _sha256_file(raw_path) != expected_hash:
            raise RecoveryError("SOURCE_EVIDENCE_INVALID")
        payload = _read_json_regular(raw_path, maximum=16 * 1024 * 1024)
        if payload.get("request") != _request_payload(selection.transport):
            raise RecoveryError("SOURCE_EVIDENCE_INVALID")
        rows = payload.get("rows")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise RecoveryError("SOURCE_RESPONSE_STRUCTURE_INVALID")
        counts = _validate_response_contract(selection, tuple(rows))
        targets = set(selection.target_dates)
        for row in rows:
            if _response_day(row.get("date")) in targets:
                target_classifications.append(
                    {
                        "contract": selection.transport.contract,
                        "date": row.get("date"),
                        "classification": _classify_row(row),
                    }
                )
        reports.append(
            {
                "sequence": sequence,
                "original_request_index": sequence - 1,
                "contract": selection.transport.contract,
                "raw_file": filename,
                "raw_sha256": expected_hash,
                "response_rows": len(rows),
                "target_rows": counts["target_rows"],
                "context_rows": counts["context_rows"],
                "verdict": "TRANSPORT_RESPONSE_VALID",
            }
        )
    after = {name: _sha256_file(attempt / name) for name in immutable_names}
    raw_after = {
        name: _sha256_file(attempt / name) for name in raw_before
    }
    if before != after or raw_before != raw_after:
        raise RecoveryError("SOURCE_EVIDENCE_MUTATED")
    return {
        "schema_version": "subing-d1-saved-response-offline-verdict-v2",
        "validator_version": _VALIDATOR_VERSION,
        "validator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "status": "offline_validation_passed",
        "readonly": True,
        "provider_requests": 0,
        "data_writes": 0,
        "original_plan_sha256": batch.candidate["plan_sha256"],
        "original_artifact_hashes_before": before,
        "original_artifact_hashes_after": after,
        "original_raw_hashes_before": raw_before,
        "original_raw_hashes_after": raw_after,
        "responses": reports,
        "summary": {
            "responses_validated": len(reports),
            "response_rows": sum(item["response_rows"] for item in reports),
            "target_rows": sum(item["target_rows"] for item in reports),
            "context_rows": sum(item["context_rows"] for item in reports),
        },
        "target_classifications": target_classifications,
        "original_execution_status_preserved": "failed",
        "note": "This is an offline validator verdict, not a provider retry or execution success.",
    }


def prepare_continuation_candidate(
    batch: FrozenBatch,
    attempt: Path,
    settings: Mapping[str, str],
) -> Mapping[str, Any]:
    records = _read_journal_records(attempt)
    started_indexes = sorted(
        int(record["sequence"]) - 1
        for record in records
        if record.get("state") == "started"
    )
    if started_indexes != list(range(9)):
        raise RecoveryError("SOURCE_CONTINUATION_PREFIX_INVALID")
    order = _continuation_order(started_indexes, len(batch.selections))
    if len(order) != 7:
        raise RecoveryError("SOURCE_CONTINUATION_OVERLAP")
    selected = _authority_selections(settings, tuple(batch.selections[index] for index in order))
    raw_requests: list[dict[str, Any]] = []
    context_count = 0
    for original_index, item in zip(order, selected, strict=True):
        request = item.transport
        context_count += len(item.allowed_response_dates) - len(item.target_dates)
        raw: dict[str, Any] = {
            "symbol": item.symbol,
            "contract": request.contract,
            "frequency": "1d",
            "month": item.target_dates[0].strftime("%Y-%m"),
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
            "target_dates": [day.isoformat() for day in item.target_dates],
            "allowed_response_dates": [day.isoformat() for day in item.allowed_response_dates],
            "calendar_authority": item.calendar_authority,
            "reason_codes": sorted(
                set(batch.candidate["requests"][original_index]["reason_codes"])
                | {"continuation_after_fail_stop"}
            ),
        }
        raw["request_sha256"] = _v2_request_digest(raw)
        raw_requests.append(raw)
    original_result = attempt / "source-only-result.json"
    offline_verdict = attempt.parent / "d1-17-source-verification-offline-v2.json"
    if not offline_verdict.is_file():
        raise RecoveryError("SOURCE_OFFLINE_VERDICT_MISSING")
    body: dict[str, Any] = {
        "schema": _SCHEMA_V2,
        "execute": False,
        "fixed_cutoff": batch.candidate["fixed_cutoff"],
        "provider": "rqdata",
        "method": "futures.get_exchange_daily",
        "requests": raw_requests,
        "budget": {
            "max_provider_requests": 7,
            "expected_date_identities": 21,
            "allowed_response_context_dates": context_count,
            "concurrency": 1,
            "retries": 0,
            "canonical_writes": 0,
            "database_writes": 0,
        },
        "execution_contract": {
            "exclusive_attempt_directory": True,
            "save_raw_response_before_classification": True,
            "journal_each_request": True,
            "verify_contract_and_date_identity": True,
            "target_and_context_counts_are_isolated": True,
            "automatic_retry": False,
            "production_publish": False,
            "fail_stop_codes": [
                "UNKNOWN", "CONTRACT_MISMATCH", "DATE_MISMATCH", "DUPLICATE",
                "ARTIFACT_WRITE_UNCERTAIN", "PLAN_DRIFT",
            ],
            "continuation_of_plan_sha256": batch.candidate["plan_sha256"],
            "continuation_of_attempt_id": attempt.name,
            "continuation_of_result_sha256": _sha256_file(original_result),
            "continuation_of_journal_sha256": _sha256_file(attempt / "journal.jsonl"),
            "offline_verdict_sha256": _sha256_file(offline_verdict),
            "validator_version": _VALIDATOR_VERSION,
            "excluded_started_request_indexes": started_indexes,
            "excluded_failed_request_index": 8,
            "stopping_failure_error_code": "SOURCE_RESPONSE_IDENTITY_INVALID",
            "original_request_indexes": list(order),
            "priority": "RS2609 rank1 dates first",
            "replay_prevention": "new plan claim plus disjoint original request indexes",
            "attempt_id": "d1-source-only-continuation-20260919-001",
            "output_root": "outputs/subing-four-period-readiness-20260918",
        },
    }
    body["plan_sha256"] = hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()
    validate_candidate(body, str(body["plan_sha256"]))
    return body


def _continuation_order(started_indexes: Sequence[int], request_count: int) -> tuple[int, ...]:
    if (
        request_count != 16
        or tuple(started_indexes) != tuple(range(9))
        or set(_CONTINUATION_ORDER) & set(started_indexes)
        or any(index < 0 or index >= request_count for index in _CONTINUATION_ORDER)
    ):
        raise RecoveryError("SOURCE_CONTINUATION_OVERLAP")
    return _CONTINUATION_ORDER


def _validate_continuation_evidence(
    batch: FrozenBatch, output_root: Path
) -> None:
    contract = batch.candidate.get("execution_contract")
    if not isinstance(contract, Mapping):
        raise RecoveryError("SOURCE_CONTINUATION_EVIDENCE_INVALID")
    old_attempt_id = contract.get("continuation_of_attempt_id")
    if not isinstance(old_attempt_id, str) or _ATTEMPT_ID.fullmatch(old_attempt_id) is None:
        raise RecoveryError("SOURCE_CONTINUATION_EVIDENCE_INVALID")
    old_attempt = _validated_existing_attempt(output_root / old_attempt_id, output_root)
    expected_hashes = {
        "source-only-result.json": contract.get("continuation_of_result_sha256"),
        "journal.jsonl": contract.get("continuation_of_journal_sha256"),
    }
    if any(
        not isinstance(expected, str) or _sha256_file(old_attempt / name) != expected
        for name, expected in expected_hashes.items()
    ):
        raise RecoveryError("SOURCE_CONTINUATION_EVIDENCE_INVALID")
    offline_path = output_root / "d1-17-source-verification-offline-v2.json"
    if _sha256_file(offline_path) != contract.get("offline_verdict_sha256"):
        raise RecoveryError("SOURCE_CONTINUATION_EVIDENCE_INVALID")
    offline = _read_json_regular(offline_path, maximum=16 * 1024 * 1024)
    if (
        offline.get("status") != "offline_validation_passed"
        or offline.get("validator_version") != contract.get("validator_version")
        or offline.get("original_plan_sha256") != contract.get("continuation_of_plan_sha256")
        or offline.get("original_artifact_hashes_before")
        != offline.get("original_artifact_hashes_after")
        or offline.get("original_raw_hashes_before")
        != offline.get("original_raw_hashes_after")
    ):
        raise RecoveryError("SOURCE_CONTINUATION_EVIDENCE_INVALID")
    _validate_current_artifact_hashes(old_attempt, offline, contract)
    raw_hashes = offline.get("original_raw_hashes_after")
    if not isinstance(raw_hashes, Mapping) or any(
        _sha256_file(old_attempt / str(name)) != expected
        for name, expected in raw_hashes.items()
    ):
        raise RecoveryError("SOURCE_CONTINUATION_EVIDENCE_INVALID")
    records = _read_journal_records(old_attempt)
    started_indexes = sorted(
        int(record["sequence"]) - 1
        for record in records
        if record.get("state") == "started"
    )
    original_indexes = contract.get("original_request_indexes")
    if (
        started_indexes != contract.get("excluded_started_request_indexes")
        or not isinstance(original_indexes, list)
        or tuple(original_indexes) != _continuation_order(started_indexes, 16)
        or set(original_indexes) & set(started_indexes)
    ):
        raise RecoveryError("SOURCE_CONTINUATION_EVIDENCE_INVALID")
    original_candidate_path = output_root / "d1-17-source-verification-candidate.json"
    original_candidate = _read_json_regular(original_candidate_path)
    old_batch = validate_candidate(
        original_candidate, str(contract.get("continuation_of_plan_sha256"))
    )
    for continuation, original_index in zip(
        batch.selections, original_indexes, strict=True
    ):
        original = old_batch.selections[original_index]
        if (
            continuation.symbol != original.symbol
            or continuation.transport != original.transport
            or continuation.target_dates != original.target_dates
        ):
            raise RecoveryError("SOURCE_CONTINUATION_EVIDENCE_INVALID")


def _validate_current_artifact_hashes(
    old_attempt: Path,
    offline: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> None:
    hashes = offline.get("original_artifact_hashes_after")
    expected_names = {
        "invocation-receipt.json",
        "journal.jsonl",
        "source-only-result.json",
    }
    if not isinstance(hashes, Mapping) or set(hashes) != expected_names:
        raise RecoveryError("SOURCE_CONTINUATION_EVIDENCE_INVALID")
    if any(
        not isinstance(expected, str)
        or _sha256_file(old_attempt / name) != expected
        for name, expected in hashes.items()
    ):
        raise RecoveryError("SOURCE_CONTINUATION_EVIDENCE_INVALID")
    if (
        hashes["journal.jsonl"] != contract.get("continuation_of_journal_sha256")
        or hashes["source-only-result.json"]
        != contract.get("continuation_of_result_sha256")
    ):
        raise RecoveryError("SOURCE_CONTINUATION_EVIDENCE_INVALID")


def _validate_v2_cli_scope(args: argparse.Namespace, batch: FrozenBatch) -> Path:
    contract = batch.candidate["execution_contract"]
    assert isinstance(contract, Mapping)
    expected_root = (PROJECT_ROOT / str(contract["output_root"])).resolve()
    supplied_root = Path(args.output_root)
    try:
        supplied_resolved = supplied_root.resolve(strict=True)
    except OSError as exc:
        raise RecoveryError("OUTPUT_ROOT_UNSAFE") from exc
    if (
        not supplied_root.is_absolute()
        or supplied_resolved != supplied_root
        or supplied_resolved != expected_root
        or args.attempt_id != contract["attempt_id"]
    ):
        raise RecoveryError("SOURCE_EXECUTION_SCOPE_MISMATCH")
    if batch.candidate.get("schema") == _SCHEMA_RECOVERY:
        _validate_response_recovery_evidence(batch, supplied_root)
    else:
        _validate_continuation_evidence(batch, supplied_root)
    return supplied_root


def _validate_response_recovery_evidence(
    batch: FrozenBatch, output_root: Path
) -> None:
    """Prove a recovery batch is exactly the raw evidence missing from blocked targets."""
    contract = batch.candidate.get("execution_contract")
    if not isinstance(contract, Mapping):
        raise RecoveryError("SOURCE_RECOVERY_EVIDENCE_INVALID")
    evidence_names = {
        "parent_plan_file_sha256": "d1-quality-segmentation-production-plan.json",
        "parent_manifest_file_sha256":
            "d1-quality-segmentation-raw-verified-candidate-manifest.json",
        "offline_verdict_file_sha256": "d1-17-source-verification-offline-v2.json",
        "continuation_candidate_file_sha256":
            "d1-17-source-verification-continuation-candidate.json",
        "source_complete_file_sha256": "d1-17-source-verification-complete.json",
    }
    if (
        contract.get("authorization_scope")
        != "MISSING_RAW_RESPONSE_RECOVERY_ONLY"
        or contract.get("recovery_target_count") != 10
        or contract.get("recovery_date_identity_count") != 60
        or _HASH.fullmatch(str(contract.get("parent_plan_sha256"))) is None
        or _HASH.fullmatch(str(contract.get("parent_manifest_sha256"))) is None
        or any(
            not isinstance(contract.get(key), str)
            or _HASH.fullmatch(str(contract[key])) is None
            or _sha256_file(output_root / filename) != contract[key]
            for key, filename in evidence_names.items()
        )
    ):
        raise RecoveryError("SOURCE_RECOVERY_EVIDENCE_INVALID")

    plan = _read_json_regular(
        output_root / evidence_names["parent_plan_file_sha256"],
        maximum=2 * 1024 * 1024,
    )
    manifest = _read_json_regular(
        output_root / evidence_names["parent_manifest_file_sha256"],
        maximum=2 * 1024 * 1024,
    )
    offline = _read_json_regular(
        output_root / evidence_names["offline_verdict_file_sha256"],
        maximum=16 * 1024 * 1024,
    )
    continuation_value = _read_json_regular(
        output_root / evidence_names["continuation_candidate_file_sha256"]
    )
    complete = _read_json_regular(
        output_root / evidence_names["source_complete_file_sha256"],
        maximum=2 * 1024 * 1024,
    )
    if (
        plan.get("plan_sha256") != contract["parent_plan_sha256"]
        or manifest.get("manifest_sha256") != contract["parent_manifest_sha256"]
        or manifest.get("parent_plan_sha256") != plan.get("plan_sha256")
        or manifest.get("blocked_target_count") != 10
        or offline.get("status") != "offline_validation_passed"
        or complete.get("schema") != "subing-d1-source-verification-complete-v1"
        or complete.get("existing_1207_anomaly_source_evidence", {}).get(
            "remaining_without_saved_source_response"
        ) != 0
    ):
        raise RecoveryError("SOURCE_RECOVERY_EVIDENCE_INVALID")
    continuation = validate_candidate(
        continuation_value, str(continuation_value.get("plan_sha256"))
    )

    blocked_ids = {
        (str(item.get("symbol")), str(item.get("contract")), str(item.get("month")))
        for item in manifest.get("blocked_targets", ())
        if isinstance(item, Mapping)
    }
    targets = {
        (str(item.get("symbol")), str(item.get("contract")), str(item.get("month"))): item
        for item in plan.get("targets", ())
        if isinstance(item, Mapping)
    }
    if len(blocked_ids) != 10 or not blocked_ids <= set(targets):
        raise RecoveryError("SOURCE_RECOVERY_EVIDENCE_INVALID")

    expected: dict[tuple[str, str, str], set[date]] = {
        identity: set() for identity in blocked_ids
    }
    for item in offline.get("target_classifications", ()):
        if not isinstance(item, Mapping):
            raise RecoveryError("SOURCE_RECOVERY_EVIDENCE_INVALID")
        contract_code = str(item.get("contract"))
        raw_day = _response_day(item.get("date"))
        identity = (
            contract_code.rstrip("0123456789").lower(),
            contract_code,
            raw_day.strftime("%Y-%m"),
        )
        if identity in expected:
            expected[identity].add(raw_day)
    for selection in continuation.selections:
        for raw_day in selection.target_dates:
            identity = (
                selection.symbol,
                selection.transport.contract,
                raw_day.strftime("%Y-%m"),
            )
            if identity in expected:
                expected[identity].add(raw_day)
    for identity, target in targets.items():
        if identity not in expected:
            continue
        affected = {date.fromisoformat(str(item)) for item in target.get("affected_dates", ())}
        if not expected[identity] or not expected[identity] <= affected:
            raise RecoveryError("SOURCE_RECOVERY_EVIDENCE_INVALID")
        if target.get("operation") == "CREATE_MIXED_UNION_PARTITION" and expected[identity] != affected:
            raise RecoveryError("SOURCE_RECOVERY_EVIDENCE_INVALID")

    actual = {
        (
            selection.symbol,
            selection.transport.contract,
            selection.target_dates[0].strftime("%Y-%m"),
        ): set(selection.target_dates)
        for selection in batch.selections
    }
    if (
        len(actual) != len(batch.selections)
        or actual != expected
        or sum(len(days) for days in actual.values()) != 60
    ):
        raise RecoveryError("SOURCE_RECOVERY_SCOPE_MISMATCH")


def _calendar_authority_body(
    *, symbol: str, contract: str, exchange: str, listed_date: date,
    expired_date: date, allowed_dates: Sequence[date]
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema": "rqdata-catalog-calendar-session-v1",
        "provider": "rqdata",
        "symbol": symbol,
        "contract": contract,
        "exchange": exchange,
        "listed_date": listed_date.isoformat(),
        "expired_date_exclusive": expired_date.isoformat(),
        "allowed_response_dates_sha256": hashlib.sha256(
            _canonical_json([item.isoformat() for item in allowed_dates]).encode("utf-8")
        ).hexdigest(),
    }
    return {
        **body,
        "authority_sha256": hashlib.sha256(
            _canonical_json(body).encode("utf-8")
        ).hexdigest(),
    }


def _validate_authority_shape(
    authority: object, *, symbol: str, contract: str, allowed_dates: Sequence[date]
) -> Mapping[str, Any]:
    if not isinstance(authority, Mapping):
        raise RecoveryError("SOURCE_CALENDAR_AUTHORITY_INVALID")
    body = dict(authority)
    digest = body.pop("authority_sha256", None)
    if (
        set(body)
        != {
            "schema", "provider", "symbol", "contract", "exchange",
            "listed_date", "expired_date_exclusive", "allowed_response_dates_sha256",
        }
        or body.get("schema") != "rqdata-catalog-calendar-session-v1"
        or body.get("provider") != "rqdata"
        or body.get("symbol") != symbol
        or body.get("contract") != contract
        or not isinstance(body.get("exchange"), str)
        or _HASH.fullmatch(str(body.get("allowed_response_dates_sha256"))) is None
        or body["allowed_response_dates_sha256"]
        != hashlib.sha256(
            _canonical_json([item.isoformat() for item in allowed_dates]).encode("utf-8")
        ).hexdigest()
        or digest != hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()
    ):
        raise RecoveryError("SOURCE_CALENDAR_AUTHORITY_INVALID")
    try:
        listed = date.fromisoformat(str(body["listed_date"]))
        expired = date.fromisoformat(str(body["expired_date_exclusive"]))
    except ValueError as exc:
        raise RecoveryError("SOURCE_CALENDAR_AUTHORITY_INVALID") from exc
    if listed >= expired or any(not listed <= item < expired for item in allowed_dates):
        raise RecoveryError("SOURCE_CALENDAR_AUTHORITY_INVALID")
    return dict(authority)


def validate_candidate(
    value: Mapping[str, Any], expected_plan_sha256: str
) -> FrozenBatch:
    """Validate every authorized identity before constructing a provider client."""
    if _HASH.fullmatch(expected_plan_sha256) is None:
        raise RecoveryError("SOURCE_PLAN_HASH_INVALID")
    if set(value) != _EXPECTED_TOP_LEVEL:
        raise RecoveryError("SOURCE_CANDIDATE_INVALID")
    body = dict(value)
    plan_sha256 = body.pop("plan_sha256", None)
    actual_plan_sha256 = hashlib.sha256(
        _canonical_json(body).encode("utf-8")
    ).hexdigest()
    if (
        plan_sha256 != expected_plan_sha256
        or actual_plan_sha256 != expected_plan_sha256
    ):
        raise RecoveryError("SOURCE_PLAN_HASH_MISMATCH")
    schema = value.get("schema")
    if (
        schema not in {_SCHEMA_V1, _SCHEMA_V2, _SCHEMA_RECOVERY}
        or value.get("execute") is not False
        or value.get("provider") != "rqdata"
        or value.get("method") != "futures.get_exchange_daily"
        or not isinstance(value.get("fixed_cutoff"), str)
    ):
        raise RecoveryError("SOURCE_CANDIDATE_INVALID")
    try:
        cutoff = datetime.fromisoformat(str(value["fixed_cutoff"]))
    except ValueError as exc:
        raise RecoveryError("SOURCE_CANDIDATE_INVALID") from exc
    if cutoff.tzinfo is None:
        raise RecoveryError("SOURCE_CANDIDATE_INVALID")
    raw_requests = value.get("requests")
    budget = value.get("budget")
    contract = value.get("execution_contract")
    if not isinstance(raw_requests, list) or not raw_requests:
        raise RecoveryError("SOURCE_CANDIDATE_INVALID")
    if not isinstance(budget, Mapping) or not isinstance(contract, Mapping):
        raise RecoveryError("SOURCE_CANDIDATE_INVALID")
    if (
        type(budget.get("max_provider_requests")) is not int
        or budget.get("max_provider_requests") != len(raw_requests)
        or type(budget.get("concurrency")) is not int
        or budget.get("concurrency") != 1
        or type(budget.get("retries")) is not int
        or budget.get("retries") != 0
        or type(budget.get("canonical_writes")) is not int
        or budget.get("canonical_writes") != 0
        or type(budget.get("database_writes")) is not int
        or budget.get("database_writes") != 0
        or contract.get("exclusive_attempt_directory") is not True
        or contract.get("save_raw_response_before_classification") is not True
        or contract.get("journal_each_request") is not True
        or contract.get("verify_contract_and_date_identity") is not True
        or contract.get("automatic_retry") is not False
        or contract.get("production_publish") is not False
        or contract.get("fail_stop_codes")
        != [
            "UNKNOWN",
            "CONTRACT_MISMATCH",
            "DATE_MISMATCH",
            "DUPLICATE",
            "ARTIFACT_WRITE_UNCERTAIN",
            "PLAN_DRIFT",
        ]
    ):
        raise RecoveryError("SOURCE_CANDIDATE_INVALID")
    selections: list[FrozenRequest] = []
    identities: set[tuple[str, date]] = set()
    for raw in raw_requests:
        expected_fields = (
            _EXPECTED_REQUEST_FIELDS_V2
            if schema in {_SCHEMA_V2, _SCHEMA_RECOVERY}
            else _EXPECTED_REQUEST_FIELDS
        )
        if not isinstance(raw, Mapping) or set(raw) != expected_fields:
            raise RecoveryError("SOURCE_CANDIDATE_INVALID")
        symbol = raw.get("symbol")
        contract_code = raw.get("contract")
        month = raw.get("month")
        reasons = raw.get("reason_codes")
        if (
            not isinstance(symbol, str)
            or _SYMBOL.fullmatch(symbol) is None
            or not isinstance(contract_code, str)
            or _CONTRACT.fullmatch(contract_code) is None
            or not contract_code.startswith(symbol.upper())
            or raw.get("frequency") != "1d"
            or not isinstance(month, str)
            or re.fullmatch(r"[0-9]{4}-[0-9]{2}", month) is None
            or not isinstance(reasons, list)
            or not reasons
            or any(not isinstance(item, str) or not item for item in reasons)
            or reasons != sorted(set(reasons))
        ):
            raise RecoveryError("SOURCE_CANDIDATE_INVALID")
        if schema in {_SCHEMA_V2, _SCHEMA_RECOVERY}:
            target_dates = _parse_dates(raw.get("target_dates"))
            allowed_dates = _parse_dates(raw.get("allowed_response_dates"))
            try:
                start = date.fromisoformat(str(raw.get("start")))
                end = date.fromisoformat(str(raw.get("end")))
            except ValueError as exc:
                raise RecoveryError("SOURCE_CANDIDATE_INVALID") from exc
            if (
                start > end
                or any(not start <= item <= end for item in allowed_dates)
                or not set(target_dates) <= set(allowed_dates)
                or any(not start <= item <= end for item in target_dates)
            ):
                raise RecoveryError("SOURCE_CANDIDATE_INVALID")
            authority = _validate_authority_shape(
                raw.get("calendar_authority"),
                symbol=str(symbol), contract=str(contract_code),
                allowed_dates=allowed_dates,
            )
            request = ExchangeDailySourceRequest(
                contract=str(contract_code), start=start, end=end,
                expected_dates=target_dates,
            )
            digest = _v2_request_digest(raw)
        else:
            request = _source_request_from_payload(
                {
                    "method": "futures.get_exchange_daily",
                    "contract": contract_code,
                    "start": raw["expected_dates"][0]
                    if isinstance(raw.get("expected_dates"), list) and raw["expected_dates"]
                    else None,
                    "end": raw["expected_dates"][-1]
                    if isinstance(raw.get("expected_dates"), list) and raw["expected_dates"]
                    else None,
                    "expected_dates": raw.get("expected_dates"),
                }
            )
            target_dates = request.expected_dates
            allowed_dates = target_dates
            authority = None
            digest = _request_digest(request)
        if raw.get("request_sha256") != digest:
            raise RecoveryError("SOURCE_REQUEST_HASH_MISMATCH")
        if any(day.strftime("%Y-%m") != month for day in request.expected_dates):
            raise RecoveryError("SOURCE_CANDIDATE_INVALID")
        for day in request.expected_dates:
            identity = (request.contract, day)
            if identity in identities:
                raise RecoveryError("SOURCE_IDENTITY_DUPLICATE")
            identities.add(identity)
        selections.append(
            FrozenRequest(
                symbol=str(symbol), transport=request, target_dates=target_dates,
                allowed_response_dates=allowed_dates,
                calendar_authority=authority, request_sha256=digest,
            )
        )
    expected_count = budget.get("expected_date_identities")
    if type(expected_count) is not int or expected_count != len(identities):
        raise RecoveryError("SOURCE_CANDIDATE_INVALID")
    if schema in {_SCHEMA_V2, _SCHEMA_RECOVERY}:
        context_count = sum(
            len(item.allowed_response_dates) - len(item.target_dates)
            for item in selections
        )
        if (
            type(budget.get("allowed_response_context_dates")) is not int
            or budget.get("allowed_response_context_dates") != context_count
            or contract.get("target_and_context_counts_are_isolated") is not True
            or not isinstance(contract.get("output_root"), str)
            or not isinstance(contract.get("attempt_id"), str)
            or _ATTEMPT_ID.fullmatch(contract["attempt_id"]) is None
        ):
            raise RecoveryError("SOURCE_CANDIDATE_INVALID")
    return FrozenBatch(
        candidate=value,
        selections=tuple(selections),
    )


def _validated_unused_attempt(output_root: Path, attempt_id: str) -> Path:
    try:
        info = output_root.lstat()
        resolved = output_root.resolve(strict=True)
    except OSError as exc:
        raise RecoveryError("OUTPUT_ROOT_UNSAFE") from exc
    if (
        not output_root.is_absolute()
        or resolved != output_root
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or _ATTEMPT_ID.fullmatch(attempt_id) is None
    ):
        raise RecoveryError("OUTPUT_ROOT_UNSAFE")
    attempt = output_root / attempt_id
    if attempt.exists() or attempt.is_symlink():
        raise RecoveryError("ATTEMPT_EXISTS")
    return attempt


def _plan_claim_path(output_root: Path, plan_sha256: str) -> Path:
    if _HASH.fullmatch(plan_sha256) is None:
        raise RecoveryError("SOURCE_PLAN_HASH_INVALID")
    return output_root / f"source-plan-{plan_sha256}.claim.json"


def _require_unclaimed_plan(output_root: Path, plan_sha256: str) -> Path:
    marker = _plan_claim_path(output_root, plan_sha256)
    if marker.exists() or marker.is_symlink():
        raise RecoveryError("SOURCE_PLAN_ALREADY_ATTEMPTED")
    return marker


def _response_day(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            try:
                return datetime.fromisoformat(value).date()
            except ValueError as exc:
                raise RecoveryError("SOURCE_RESPONSE_IDENTITY_INVALID") from exc
    try:
        return value.to_pydatetime().date()
    except (AttributeError, TypeError, ValueError) as exc:
        raise RecoveryError("SOURCE_RESPONSE_IDENTITY_INVALID") from exc


def _validate_response_contract(
    selection: FrozenRequest, response: tuple[dict[str, Any], ...]
) -> dict[str, int]:
    request = selection.transport
    seen: set[date] = set()
    ordered: list[date] = []
    for row in response:
        if not isinstance(row, Mapping):
            raise RecoveryError("SOURCE_RESPONSE_STRUCTURE_INVALID")
        if row.get("order_book_id") != request.contract:
            raise RecoveryError("SOURCE_RESPONSE_CONTRACT_MISMATCH")
        day = _response_day(row.get("date"))
        if day in seen:
            raise RecoveryError("SOURCE_RESPONSE_DUPLICATE")
        if not request.start <= day <= request.end:
            raise RecoveryError("SOURCE_RESPONSE_DATE_OUT_OF_RANGE")
        if day not in selection.allowed_response_dates:
            raise RecoveryError("SOURCE_RESPONSE_DATE_UNPROVEN")
        if any(_decimal(row.get(field)) is None for field in ("open", "high", "low", "close", "volume")):
            raise RecoveryError("SOURCE_RESPONSE_STRUCTURE_INVALID")
        seen.add(day)
        ordered.append(day)
    if ordered != sorted(ordered):
        raise RecoveryError("SOURCE_RESPONSE_DATE_ORDER_INVALID")
    missing = set(selection.target_dates) - seen
    if missing:
        raise RecoveryError("SOURCE_RESPONSE_TARGET_MISSING")
    context = seen - set(selection.target_dates)
    return {"target_rows": len(selection.target_dates), "context_rows": len(context)}


def _decimal(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _classify_row(row: Mapping[str, Any]) -> str:
    values = tuple(
        _decimal(row.get(field)) for field in ("open", "high", "low", "close")
    )
    if any(value is None for value in values):
        return "PRICE_FIELDS_INVALID"
    open_, high, low, close = values
    assert (
        open_ is not None and high is not None and low is not None and close is not None
    )
    if close <= 0:
        return "NONPOSITIVE_CLOSE_SOURCE_FACT"
    if open_ <= 0 or high <= 0 or low <= 0:
        return "ZERO_OHL_POSITIVE_CLOSE_SOURCE_FACT"
    return "POSITIVE_OHLC_SOURCE_FACT"


def _classifications(
    attempt: Path, selections: Sequence[FrozenRequest], saved_count: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    result: list[dict[str, Any]] = []
    context: list[dict[str, Any]] = []
    for sequence in range(1, saved_count + 1):
        path = attempt / f"source-response-{sequence:04d}.json"
        payload = _read_json_regular(path, maximum=16 * 1024 * 1024)
        rows = payload.get("rows")
        request = payload.get("request")
        if not isinstance(rows, list) or not isinstance(request, Mapping):
            raise RecoveryError("SOURCE_EVIDENCE_INVALID")
        selection = selections[sequence - 1]
        targets = set(selection.target_dates)
        for row in rows:
            if not isinstance(row, Mapping):
                raise RecoveryError("SOURCE_EVIDENCE_INVALID")
            item = {"contract": request.get("contract"), "date": row.get("date")}
            if _response_day(row.get("date")) in targets:
                result.append({**item, "classification": _classify_row(row)})
            else:
                context.append(item)
    return result, context


def _provider_error(error: Exception) -> str:
    if _is_rqdata_quota_error(error):
        return "PROVIDER_QUOTA_EXHAUSTED"
    return _error_code(error)


def execute_batch(
    args: argparse.Namespace,
    batch: FrozenBatch,
    settings: Mapping[str, str],
    identity: Mapping[str, str],
    *,
    client_factory: Callable[[Mapping[str, str]], Any] = lambda value: RQDataClient(
        settings=value
    ),
) -> Mapping[str, Any]:
    claim = _require_unclaimed_plan(Path(args.output_root), args.expected_plan_sha256)
    _write_json_exclusive(
        claim,
        {
            "schema_version": "subing_d1_source_only_plan_claim_v1",
            "plan_sha256": args.expected_plan_sha256,
            "attempt_id": args.attempt_id,
            "code_commit": _current_code_commit(),
            "retry_allowed": False,
        },
    )
    attempt = create_attempt_directory(Path(args.output_root), args.attempt_id)
    journal = D1SourceAttemptJournal(attempt, batch.requests)
    receipt = {
        "schema_version": "subing_d1_source_only_invocation_v1",
        "candidate_file": Path(args.candidate).name,
        "plan_sha256": args.expected_plan_sha256,
        "attempt_id": args.attempt_id,
        "code_commit": _current_code_commit(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "config_sha256": identity["config_sha256"],
        "canonical_root_sha256": identity["canonical_root_sha256"],
        "provider_request_limit": len(batch.requests),
        "expected_date_identities": sum(
            len(item.expected_dates) for item in batch.requests
        ),
        "concurrency": 1,
        "retries_allowed": 0,
        "canonical_writes_allowed": False,
        "database_writes_allowed": False,
        "manager_apply_allowed": False,
    }
    _write_json_exclusive(attempt / "invocation-receipt.json", receipt)
    completed: list[dict[str, Any]] = []
    failed: dict[str, Any] | None = None
    client: Any | None = None
    for index, selection in enumerate(batch.selections):
        symbol = selection.symbol
        request = selection.transport
        request_sha256 = selection.request_sha256
        try:
            journal.before_request(request)
            if client is None:
                client = client_factory(settings)
            response = _records(
                client.exchange_daily(request.contract, request.start, request.end)
            )
            journal.after_response(request, response)
            counts = _validate_response_contract(selection, response)
        except Exception as error:  # noqa: BLE001 - sanitize provider/storage errors
            error_code = _provider_error(error)
            try:
                journal.mark_failed(error_code, sequence=index + 1)
            except Exception:  # noqa: BLE001 - persistence uncertainty is terminal
                error_code = "SOURCE_JOURNAL_UNAVAILABLE"
            failed = {
                "index": index,
                "symbol": symbol,
                "contract": request.contract,
                "request_sha256": request_sha256,
                "error_code": error_code,
            }
            break
        completed.append(
            {
                "index": index,
                "symbol": symbol,
                "contract": request.contract,
                "request_sha256": request_sha256,
                "target_date_count": len(selection.target_dates),
                "context_row_count": counts["context_rows"],
                "status": "response_saved",
            }
        )
    outcome = read_attempt_outcome(attempt)
    classifications, contexts = _classifications(
        attempt, batch.selections, len(completed)
    )
    unexecuted = [
        {
            "index": index,
            "symbol": batch.symbols[index],
            "contract": batch.requests[index].contract,
            "request_sha256": batch.request_hashes[index],
        }
        for index in range(
            len(completed) + (1 if failed is not None else 0), len(batch.requests)
        )
    ]
    unknown = outcome["outcome_unknown"] is True
    result = {
        "schema_version": "subing_d1_source_only_result_v1",
        "status": "unknown" if unknown else "failed" if failed else "completed",
        "classification": (
            "SOURCE_QUERY_OUTCOME_UNKNOWN"
            if unknown
            else "SOURCE_BATCH_STOPPED"
            if failed
            else "SOURCE_RESPONSES_SAVED_REVIEW_REQUIRED"
        ),
        "plan_sha256": args.expected_plan_sha256,
        "attempt": outcome,
        "completed": completed,
        "failed": failed,
        "unexecuted": unexecuted,
        "row_classifications": classifications,
        "response_context": contexts,
        "summary": {
            "requests_planned": len(batch.requests),
            "requests_started": outcome["requests_started"],
            "responses_saved": outcome["responses_saved"],
            "requests_failed": 1 if failed is not None else 0,
            "requests_unexecuted": len(unexecuted),
            "target_dates_planned": sum(len(item.target_dates) for item in batch.selections),
            "target_rows_saved": len(classifications),
            "context_rows_saved": len(contexts),
            "rows_saved": len(classifications) + len(contexts),
        },
        "retries": 0,
        "canonical_writes": 0,
        "database_writes": 0,
        "manager_apply": False,
    }
    _write_json_exclusive(attempt / "source-only-result.json", result)
    return result


def _load_preflight(
    args: argparse.Namespace,
) -> tuple[FrozenBatch, dict[str, str], dict[str, str]]:
    candidate = _read_json_regular(Path(args.candidate))
    batch = validate_candidate(candidate, args.expected_plan_sha256)
    output_root = (
        _validate_v2_cli_scope(args, batch)
        if candidate.get("schema") in {_SCHEMA_V2, _SCHEMA_RECOVERY}
        else Path(args.output_root)
    )
    _validated_unused_attempt(output_root, args.attempt_id)
    _require_unclaimed_plan(output_root, args.expected_plan_sha256)
    _require_clean_execution_checkout(_current_code_commit())
    settings, identity = load_private_execution_settings(Path(args.project_env))
    if candidate.get("schema") in {_SCHEMA_V2, _SCHEMA_RECOVERY}:
        _authority_selections(settings, batch.selections)
    return batch, settings, identity


def main(argv: list[str] | None = None, *, stdout=sys.stdout) -> int:
    try:
        args = parser().parse_args(argv)
        if args.mode in {"offline-validate", "prepare-continuation"}:
            candidate_path = Path(args.candidate)
            expected_candidate = _EVIDENCE_ROOT / "d1-17-source-verification-candidate.json"
            if candidate_path != expected_candidate or not candidate_path.is_absolute():
                raise RecoveryError("SOURCE_EVIDENCE_PATH_INVALID")
            candidate = _read_json_regular(candidate_path)
            batch = validate_candidate(candidate, args.expected_plan_sha256)
            settings, _identity = load_private_readonly_settings(Path(args.project_env))
            attempt = _validated_existing_attempt(
                Path(args.attempt_dir), _EVIDENCE_ROOT
            )
            output = _validated_evidence_output(
                Path(args.output), attempt, args.mode,
                Path(settings["GUIYI_CANONICAL_DATA_ROOT"]),
            )
            if args.mode == "offline-validate":
                payload = offline_validate_attempt(batch, attempt, settings)
            else:
                payload = prepare_continuation_candidate(
                    batch, attempt, settings
                )
            _write_json_exclusive(output, payload)
            code = 0
        else:
            batch, settings, identity = _load_preflight(args)
            if args.mode == "preflight":
                payload = {
                    "schema_version": "subing_d1_source_only_preflight_v2",
                    "status": "source_query_preflight_passed",
                    "readonly": True,
                    "plan_sha256": args.expected_plan_sha256,
                    "provider_requests": 0,
                    "writes": 0,
                    "request_limit": len(batch.requests),
                    "target_date_identities": sum(
                        len(item.target_dates) for item in batch.selections
                    ),
                    "allowed_context_dates": sum(
                        len(item.allowed_response_dates) - len(item.target_dates)
                        for item in batch.selections
                    ),
                    "output_root": args.output_root,
                    "attempt_id": args.attempt_id,
                }
                code = 0
            else:
                payload = execute_batch(args, batch, settings, identity)
                code = 0 if payload["status"] == "completed" else 2
    except Exception as error:  # noqa: BLE001 - CLI boundary must stay sanitized
        payload = {"status": "failed", "error_code": _error_code(error)}
        code = 1
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
