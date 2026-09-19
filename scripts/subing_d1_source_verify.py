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
from typing import Any, Callable, Mapping

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
    _require_clean_execution_checkout,
    _source_request_from_payload,
    _source_scalar,
    _write_json_exclusive,
    create_attempt_directory,
    load_private_execution_settings,
    read_attempt_outcome,
)


_SCHEMA = "subing-d1-source-verification-candidate-v1"
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


@dataclass(frozen=True, slots=True)
class FrozenBatch:
    candidate: Mapping[str, Any]
    requests: tuple[ExchangeDailySourceRequest, ...]
    symbols: tuple[str, ...]
    request_hashes: tuple[str, ...]


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
    if (
        value.get("schema") != _SCHEMA
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
    requests: list[ExchangeDailySourceRequest] = []
    symbols: list[str] = []
    request_hashes: list[str] = []
    identities: set[tuple[str, date]] = set()
    for raw in raw_requests:
        if not isinstance(raw, Mapping) or set(raw) != _EXPECTED_REQUEST_FIELDS:
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
        requests.append(request)
        symbols.append(symbol)
        request_hashes.append(digest)
    expected_count = budget.get("expected_date_identities")
    if type(expected_count) is not int or expected_count != len(identities):
        raise RecoveryError("SOURCE_CANDIDATE_INVALID")
    return FrozenBatch(
        candidate=value,
        requests=tuple(requests),
        symbols=tuple(symbols),
        request_hashes=tuple(request_hashes),
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


def _validate_response_contract(
    request: ExchangeDailySourceRequest, response: tuple[dict[str, Any], ...]
) -> None:
    seen: set[date] = set()
    for row in response:
        if row.get("order_book_id") != request.contract:
            raise RecoveryError("SOURCE_RESPONSE_CONTRACT_MISMATCH")
        raw_day = row.get("date")
        if isinstance(raw_day, datetime):
            day = raw_day.date()
        elif isinstance(raw_day, date):
            day = raw_day
        elif isinstance(raw_day, str):
            try:
                day = date.fromisoformat(raw_day)
            except ValueError:
                day = datetime.fromisoformat(raw_day).date()
        else:
            try:
                day = raw_day.to_pydatetime().date()
            except (AttributeError, TypeError, ValueError) as exc:
                raise RecoveryError("SOURCE_RESPONSE_IDENTITY_INVALID") from exc
        if day in seen:
            raise RecoveryError("SOURCE_RESPONSE_DUPLICATE")
        seen.add(day)


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


def _classifications(attempt: Path, saved_count: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for sequence in range(1, saved_count + 1):
        path = attempt / f"source-response-{sequence:04d}.json"
        payload = _read_json_regular(path, maximum=16 * 1024 * 1024)
        rows = payload.get("rows")
        request = payload.get("request")
        if not isinstance(rows, list) or not isinstance(request, Mapping):
            raise RecoveryError("SOURCE_EVIDENCE_INVALID")
        for row in rows:
            if not isinstance(row, Mapping):
                raise RecoveryError("SOURCE_EVIDENCE_INVALID")
            result.append(
                {
                    "contract": request.get("contract"),
                    "date": row.get("date"),
                    "classification": _classify_row(row),
                }
            )
    return result


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
    for index, (symbol, request, request_sha256) in enumerate(
        zip(batch.symbols, batch.requests, batch.request_hashes, strict=True)
    ):
        try:
            journal.before_request(request)
            if client is None:
                client = client_factory(settings)
            response = _records(
                client.exchange_daily(request.contract, request.start, request.end)
            )
            journal.after_response(request, response)
            _validate_response_contract(request, response)
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
                "date_count": len(request.expected_dates),
                "status": "response_saved",
            }
        )
    outcome = read_attempt_outcome(attempt)
    classifications = _classifications(attempt, int(outcome["responses_saved"]))
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
        "summary": {
            "requests_planned": len(batch.requests),
            "requests_started": outcome["requests_started"],
            "responses_saved": outcome["responses_saved"],
            "requests_failed": 1 if failed is not None else 0,
            "requests_unexecuted": len(unexecuted),
            "dates_planned": sum(len(item.expected_dates) for item in batch.requests),
            "rows_saved": len(classifications),
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
    _validated_unused_attempt(Path(args.output_root), args.attempt_id)
    _require_unclaimed_plan(Path(args.output_root), args.expected_plan_sha256)
    candidate = _read_json_regular(Path(args.candidate))
    batch = validate_candidate(candidate, args.expected_plan_sha256)
    _require_clean_execution_checkout(_current_code_commit())
    settings, identity = load_private_execution_settings(Path(args.project_env))
    return batch, settings, identity


def main(argv: list[str] | None = None, *, stdout=sys.stdout) -> int:
    try:
        args = parser().parse_args(argv)
        batch, settings, identity = _load_preflight(args)
        if args.mode == "preflight":
            payload: Mapping[str, Any] = {
                "schema_version": "subing_d1_source_only_preflight_v1",
                "status": "source_query_preflight_passed",
                "readonly": True,
                "plan_sha256": args.expected_plan_sha256,
                "provider_requests": 0,
                "writes": 0,
                "request_limit": len(batch.requests),
                "expected_date_identities": sum(
                    len(item.expected_dates) for item in batch.requests
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
