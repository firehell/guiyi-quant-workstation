from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import newow_weekly_recovery as native
from scripts import subing_d1_source_verify as source_verify


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _candidate(*, requests: list[dict[str, object]] | None = None) -> dict[str, object]:
    if requests is None:
        raw = {
            "contract": "RS2609",
            "start": "2026-09-02",
            "end": "2026-09-04",
            "expected_dates": ["2026-09-02", "2026-09-04"],
        }
        requests = [
            {
                "symbol": "rs",
                "contract": "RS2609",
                "frequency": "1d",
                "month": "2026-09",
                "expected_dates": raw["expected_dates"],
                "reason_codes": ["raw_response_missing_for_nonpositive_close"],
                "request_sha256": hashlib.sha256(_canonical(raw).encode()).hexdigest(),
            }
        ]
    value: dict[str, object] = {
        "schema": "subing-d1-source-verification-candidate-v1",
        "execute": False,
        "fixed_cutoff": "2026-09-18T18:30:00+08:00",
        "provider": "rqdata",
        "method": "futures.get_exchange_daily",
        "requests": requests,
        "budget": {
            "max_provider_requests": len(requests),
            "expected_date_identities": sum(
                len(item["expected_dates"]) for item in requests
            ),
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
            "fail_stop_codes": [
                "UNKNOWN",
                "CONTRACT_MISMATCH",
                "DATE_MISMATCH",
                "DUPLICATE",
                "ARTIFACT_WRITE_UNCERTAIN",
                "PLAN_DRIFT",
            ],
            "automatic_retry": False,
            "production_publish": False,
        },
    }
    value["plan_sha256"] = hashlib.sha256(_canonical(value).encode()).hexdigest()
    return value


def _candidate_v2(
    *, allowed: list[str] | None = None, targets: list[str] | None = None
) -> dict[str, object]:
    target_dates = targets or ["2026-09-02", "2026-09-04"]
    allowed_dates = allowed or ["2026-09-02", "2026-09-03", "2026-09-04"]
    authority_body = {
        "schema": "rqdata-catalog-calendar-session-v1",
        "provider": "rqdata",
        "symbol": "rs",
        "contract": "RS2609",
        "exchange": "CZCE",
        "listed_date": "2025-09-01",
        "expired_date_exclusive": "2026-09-16",
        "allowed_response_dates_sha256": hashlib.sha256(
            _canonical(allowed_dates).encode()
        ).hexdigest(),
    }
    authority = {
        **authority_body,
        "authority_sha256": hashlib.sha256(
            _canonical(authority_body).encode()
        ).hexdigest(),
    }
    raw: dict[str, object] = {
        "symbol": "rs",
        "contract": "RS2609",
        "frequency": "1d",
        "month": "2026-09",
        "start": "2026-09-02",
        "end": "2026-09-04",
        "target_dates": target_dates,
        "allowed_response_dates": allowed_dates,
        "calendar_authority": authority,
        "reason_codes": ["continuation_after_fail_stop"],
    }
    digest_body = {
        key: raw[key]
        for key in (
            "contract", "start", "end", "target_dates",
            "allowed_response_dates", "calendar_authority",
        )
    }
    raw["request_sha256"] = hashlib.sha256(
        _canonical(digest_body).encode()
    ).hexdigest()
    value: dict[str, object] = {
        "schema": "subing-d1-source-verification-candidate-v2",
        "execute": False,
        "fixed_cutoff": "2026-09-18T18:30:00+08:00",
        "provider": "rqdata",
        "method": "futures.get_exchange_daily",
        "requests": [raw],
        "budget": {
            "max_provider_requests": 1,
            "expected_date_identities": len(target_dates),
            "allowed_response_context_dates": len(allowed_dates) - len(target_dates),
            "concurrency": 1,
            "retries": 0,
            "canonical_writes": 0,
            "database_writes": 0,
        },
        "execution_contract": {
            **_candidate()["execution_contract"],  # type: ignore[dict-item]
            "target_and_context_counts_are_isolated": True,
            "output_root": "outputs/subing-four-period-readiness-20260918",
            "attempt_id": "attempt-001",
        },
    }
    value["plan_sha256"] = hashlib.sha256(_canonical(value).encode()).hexdigest()
    return value


def _row(day: date, *, contract: str = "RS2609") -> dict[str, object]:
    return {
        "order_book_id": contract,
        "date": day,
        "open": 1,
        "high": 1,
        "low": 1,
        "close": 1,
        "volume": 1,
    }


def _batch(candidate: dict[str, object] | None = None) -> source_verify.FrozenBatch:
    value = candidate or _candidate()
    return source_verify.validate_candidate(value, str(value["plan_sha256"]))


def _args(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        output_root=str(tmp_path),
        attempt_id="attempt-001",
        candidate="candidate.json",
        expected_plan_sha256=str(_candidate()["plan_sha256"]),
    )


def _identity() -> dict[str, str]:
    return {"config_sha256": "a" * 64, "canonical_root_sha256": "b" * 64}


def test_candidate_binds_plan_request_budget_and_unique_dates() -> None:
    candidate = _candidate()
    batch = _batch(candidate)
    assert len(batch.requests) == 1
    assert batch.requests[0].expected_dates == (date(2026, 9, 2), date(2026, 9, 4))

    tampered = deepcopy(candidate)
    tampered["budget"]["concurrency"] = 2  # type: ignore[index]
    with pytest.raises(native.RecoveryError, match="SOURCE_PLAN_HASH_MISMATCH"):
        source_verify.validate_candidate(tampered, str(candidate["plan_sha256"]))

    rehashed = deepcopy(candidate)
    rehashed["budget"]["concurrency"] = 2  # type: ignore[index]
    rehashed.pop("plan_sha256")
    rehashed["plan_sha256"] = hashlib.sha256(_canonical(rehashed).encode()).hexdigest()
    with pytest.raises(native.RecoveryError, match="SOURCE_CANDIDATE_INVALID"):
        source_verify.validate_candidate(rehashed, str(rehashed["plan_sha256"]))

    boolean_budget = deepcopy(candidate)
    boolean_budget["budget"]["concurrency"] = True  # type: ignore[index]
    boolean_budget.pop("plan_sha256")
    boolean_budget["plan_sha256"] = hashlib.sha256(
        _canonical(boolean_budget).encode()
    ).hexdigest()
    with pytest.raises(native.RecoveryError, match="SOURCE_CANDIDATE_INVALID"):
        source_verify.validate_candidate(
            boolean_budget, str(boolean_budget["plan_sha256"])
        )


def test_repository_candidate_is_exactly_frozen_16_requests_and_66_dates() -> None:
    root = Path(__file__).resolve().parents[4]
    candidate = json.loads(
        (
            root
            / "outputs/subing-four-period-readiness-20260918"
            / "d1-17-source-verification-candidate.json"
        ).read_text()
    )
    expected = "2c764158c097919fdb7a87ec3935c364905a122ff95d10cc96bf82b1c1c785bb"
    batch = source_verify.validate_candidate(candidate, expected)
    identities = {
        (request.contract, day)
        for request in batch.requests
        for day in request.expected_dates
    }
    assert len(batch.requests) == 16
    assert sum(len(request.expected_dates) for request in batch.requests) == 66
    assert len(identities) == 66


def test_repository_raw_response_recovery_plan_is_exactly_scoped() -> None:
    root = Path(__file__).resolve().parents[4]
    evidence_root = root / "outputs/subing-four-period-readiness-20260918"
    candidate = json.loads(
        (evidence_root / "d1-17-source-response-recovery-candidate.json").read_text()
    )
    batch = source_verify.validate_candidate(candidate, str(candidate["plan_sha256"]))

    source_verify._validate_response_recovery_evidence(batch, evidence_root)

    identities = {
        (selection.symbol, selection.transport.contract, day)
        for selection in batch.selections
        for day in selection.target_dates
    }
    assert len(batch.requests) == 10
    assert len(identities) == 60
    assert candidate["budget"] == {
        "max_provider_requests": 10,
        "expected_date_identities": 60,
        "allowed_response_context_dates": 28,
        "concurrency": 1,
        "retries": 0,
        "canonical_writes": 0,
        "database_writes": 0,
    }


def test_raw_response_recovery_gate_rejects_reduced_scope() -> None:
    root = Path(__file__).resolve().parents[4]
    evidence_root = root / "outputs/subing-four-period-readiness-20260918"
    candidate = json.loads(
        (evidence_root / "d1-17-source-response-recovery-candidate.json").read_text()
    )
    candidate["requests"][0]["target_dates"] = candidate["requests"][0][
        "target_dates"
    ][1:]
    digest_body = {
        key: candidate["requests"][0][key]
        for key in (
            "contract", "start", "end", "target_dates",
            "allowed_response_dates", "calendar_authority",
        )
    }
    candidate["requests"][0]["request_sha256"] = hashlib.sha256(
        _canonical(digest_body).encode()
    ).hexdigest()
    candidate["budget"]["expected_date_identities"] = 59
    candidate["budget"]["allowed_response_context_dates"] = 29
    candidate.pop("plan_sha256")
    candidate["plan_sha256"] = hashlib.sha256(
        _canonical(candidate).encode()
    ).hexdigest()
    batch = source_verify.validate_candidate(candidate, str(candidate["plan_sha256"]))

    with pytest.raises(native.RecoveryError, match="SOURCE_RECOVERY_SCOPE_MISMATCH"):
        source_verify._validate_response_recovery_evidence(batch, evidence_root)


def test_candidate_rejects_duplicate_identity_even_with_valid_hash() -> None:
    candidate = _candidate()
    duplicate = deepcopy(candidate["requests"][0])  # type: ignore[index]
    candidate["requests"] = [candidate["requests"][0], duplicate]  # type: ignore[index]
    candidate["budget"]["max_provider_requests"] = 2  # type: ignore[index]
    candidate["budget"]["expected_date_identities"] = 4  # type: ignore[index]
    candidate.pop("plan_sha256")
    candidate["plan_sha256"] = hashlib.sha256(
        _canonical(candidate).encode()
    ).hexdigest()
    with pytest.raises(native.RecoveryError, match="SOURCE_IDENTITY_DUPLICATE"):
        source_verify.validate_candidate(candidate, str(candidate["plan_sha256"]))


def test_output_root_and_existing_attempt_are_fail_closed(tmp_path: Path) -> None:
    source_verify._validated_unused_attempt(tmp_path, "attempt-001")
    (tmp_path / "attempt-001").mkdir()
    with pytest.raises(native.RecoveryError, match="ATTEMPT_EXISTS"):
        source_verify._validated_unused_attempt(tmp_path, "attempt-001")

    target = tmp_path / "target"
    target.mkdir()
    symlink = tmp_path / "link"
    symlink.symlink_to(target, target_is_directory=True)
    with pytest.raises(native.RecoveryError, match="OUTPUT_ROOT_UNSAFE"):
        source_verify._validated_unused_attempt(symlink, "attempt-002")

    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(_candidate()))
    with pytest.raises(native.RecoveryError, match="SOURCE_CANDIDATE_INVALID"):
        source_verify._read_json_regular(Path("candidate.json"))


class _Client:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls = 0

    def exchange_daily(self, contract: str, start: date, end: date) -> object:
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_execute_preserves_zero_prices_and_has_no_publish_path(tmp_path: Path) -> None:
    client = _Client(
        [
            {
                "order_book_id": "RS2609",
                "date": date(2026, 9, 2),
                "open": 0,
                "high": 0,
                "low": 0,
                "close": 0,
                "volume": 0,
            },
            {
                "order_book_id": "RS2609",
                "date": date(2026, 9, 4),
                "open": 1,
                "high": 2,
                "low": 1,
                "close": 2,
                "volume": 3,
            },
        ]
    )
    result = source_verify.execute_batch(
        _args(tmp_path),
        _batch(),
        {},
        _identity(),
        client_factory=lambda _settings: client,
    )
    assert result["status"] == "completed"
    assert result["canonical_writes"] == result["database_writes"] == 0
    assert result["manager_apply"] is False
    assert [item["classification"] for item in result["row_classifications"]] == [
        "NONPOSITIVE_CLOSE_SOURCE_FACT",
        "POSITIVE_OHLC_SOURCE_FACT",
    ]
    payload = json.loads(
        (tmp_path / "attempt-001/source-response-0001.json").read_text()
    )
    assert payload["rows"][0]["order_book_id"] == "RS2609"
    assert payload["rows"][0]["close"] == "0"
    receipt = json.loads((tmp_path / "attempt-001/invocation-receipt.json").read_text())
    assert receipt["canonical_writes_allowed"] is False
    assert receipt["database_writes_allowed"] is False
    assert receipt["retries_allowed"] == 0


def test_provider_exception_is_unknown_not_retryable_and_stops_batch(
    tmp_path: Path,
) -> None:
    first = deepcopy(_candidate()["requests"][0])  # type: ignore[index]
    raw = {
        "contract": "PF2609",
        "start": "2026-09-01",
        "end": "2026-09-01",
        "expected_dates": ["2026-09-01"],
    }
    second = {
        "symbol": "pf",
        "contract": "PF2609",
        "frequency": "1d",
        "month": "2026-09",
        "expected_dates": raw["expected_dates"],
        "reason_codes": ["recent_hard_invalid_partition_no_saved_response"],
        "request_sha256": hashlib.sha256(_canonical(raw).encode()).hexdigest(),
    }
    candidate = _candidate(requests=[first, second])
    client = _Client(TimeoutError())
    args = _args(tmp_path)
    args.expected_plan_sha256 = candidate["plan_sha256"]
    result = source_verify.execute_batch(
        args,
        _batch(candidate),
        {},
        _identity(),
        client_factory=lambda _settings: client,
    )
    assert result["status"] == "unknown"
    assert result["attempt"] == {
        "state": "outcome_unknown",
        "outcome_unknown": True,
        "retry_allowed": False,
        "requests_started": 1,
        "responses_saved": 0,
    }
    assert result["summary"]["requests_unexecuted"] == 1
    assert client.calls == 1


def test_client_initialization_failure_is_started_unknown_and_not_retryable(
    tmp_path: Path,
) -> None:
    def fail_factory(_settings: object) -> object:
        raise RuntimeError("private provider initialization detail")

    result = source_verify.execute_batch(
        _args(tmp_path), _batch(), {}, _identity(), client_factory=fail_factory
    )
    assert result["status"] == "unknown"
    assert result["failed"]["error_code"] == "RECOVERY_EXECUTION_FAILED"
    assert result["attempt"] == {
        "state": "outcome_unknown",
        "outcome_unknown": True,
        "retry_allowed": False,
        "requests_started": 1,
        "responses_saved": 0,
    }


def test_contract_or_date_identity_failure_saves_raw_then_stops(tmp_path: Path) -> None:
    client = _Client(
        [
            {
                "order_book_id": "WRONG",
                "date": date(2026, 9, 2),
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
            },
            {
                "order_book_id": "WRONG",
                "date": date(2026, 9, 4),
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
            },
        ]
    )
    result = source_verify.execute_batch(
        _args(tmp_path),
        _batch(),
        {},
        _identity(),
        client_factory=lambda _settings: client,
    )
    assert result["status"] == "failed"
    assert result["failed"]["error_code"] == "SOURCE_RESPONSE_CONTRACT_MISMATCH"
    assert result["attempt"]["responses_saved"] == 1


@pytest.mark.parametrize(
    ("dates", "error_code"),
    [
        ([date(2026, 9, 2)], "SOURCE_RESPONSE_TARGET_MISSING"),
        (
            [date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 4)],
            "SOURCE_RESPONSE_DATE_UNPROVEN",
        ),
        ([date(2026, 9, 4), date(2026, 9, 2)], "SOURCE_RESPONSE_DATE_ORDER_INVALID"),
        ([date(2026, 9, 2), date(2026, 9, 2)], "SOURCE_RESPONSE_DUPLICATE"),
    ],
)
def test_date_identity_failures_save_raw_and_stop(
    tmp_path: Path, dates: list[date], error_code: str
) -> None:
    client = _Client(
        [
            {
                "order_book_id": "RS2609",
                "date": day,
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
            }
            for day in dates
        ]
    )
    result = source_verify.execute_batch(
        _args(tmp_path),
        _batch(),
        {},
        _identity(),
        client_factory=lambda _settings: client,
    )
    assert result["status"] == "failed"
    assert result["failed"]["error_code"] == error_code
    assert result["attempt"]["responses_saved"] == 1


def test_response_persistence_failure_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _Client(
        [
            {
                "order_book_id": "RS2609",
                "date": date(2026, 9, 2),
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
            },
            {
                "order_book_id": "RS2609",
                "date": date(2026, 9, 4),
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
            },
        ]
    )
    monkeypatch.setattr(
        source_verify.D1SourceAttemptJournal,
        "_write_payload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()),
    )
    result = source_verify.execute_batch(
        _args(tmp_path),
        _batch(),
        {},
        _identity(),
        client_factory=lambda _settings: client,
    )
    assert result["status"] == "unknown"
    assert result["attempt"]["responses_saved"] == 0
    assert result["attempt"]["retry_allowed"] is False


def test_final_result_write_failure_keeps_claim_and_raw_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _Client(
        [
            {
                "order_book_id": "RS2609",
                "date": date(2026, 9, 2),
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
            },
            {
                "order_book_id": "RS2609",
                "date": date(2026, 9, 4),
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
            },
        ]
    )
    real_write = source_verify._write_json_exclusive

    def fail_result(path: Path, value: object) -> str:
        if path.name == "source-only-result.json":
            raise OSError("simulated final receipt failure")
        return real_write(path, value)

    monkeypatch.setattr(source_verify, "_write_json_exclusive", fail_result)
    args = _args(tmp_path)
    with pytest.raises(OSError, match="simulated final receipt failure"):
        source_verify.execute_batch(
            args,
            _batch(),
            {},
            _identity(),
            client_factory=lambda _settings: client,
        )
    assert (tmp_path / "attempt-001/source-response-0001.json").exists()
    assert source_verify._plan_claim_path(tmp_path, args.expected_plan_sha256).exists()
    args.attempt_id = "attempt-002"
    with pytest.raises(native.RecoveryError, match="SOURCE_PLAN_ALREADY_ATTEMPTED"):
        source_verify.execute_batch(
            args,
            _batch(),
            {},
            _identity(),
            client_factory=lambda _settings: client,
        )
    assert client.calls == 1


def test_existing_attempt_and_plan_claim_prevent_repeat_before_provider(
    tmp_path: Path,
) -> None:
    (tmp_path / "attempt-001").mkdir()
    with pytest.raises(native.RecoveryError, match="ATTEMPT_EXISTS"):
        source_verify._validated_unused_attempt(tmp_path, "attempt-001")

    args = _args(tmp_path)
    args.attempt_id = "first"
    client = _Client(
        [
            {
                "order_book_id": "RS2609",
                "date": date(2026, 9, 2),
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
            },
            {
                "order_book_id": "RS2609",
                "date": date(2026, 9, 4),
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
            },
        ]
    )
    source_verify.execute_batch(
        args, _batch(), {}, _identity(), client_factory=lambda _settings: client
    )
    args.attempt_id = "different-name"
    with pytest.raises(native.RecoveryError, match="SOURCE_PLAN_ALREADY_ATTEMPTED"):
        source_verify.execute_batch(
            args, _batch(), {}, _identity(), client_factory=lambda _settings: client
        )
    assert client.calls == 1


def test_v2_sparse_targets_accept_proven_context_and_keep_counts_isolated(
    tmp_path: Path,
) -> None:
    candidate = _candidate_v2()
    args = _args(tmp_path)
    args.expected_plan_sha256 = candidate["plan_sha256"]
    client = _Client(
        [_row(date(2026, 9, 2)), _row(date(2026, 9, 3)), _row(date(2026, 9, 4))]
    )
    result = source_verify.execute_batch(
        args,
        _batch(candidate),
        {},
        _identity(),
        client_factory=lambda _settings: client,
    )
    assert result["status"] == "completed"
    assert result["summary"] == {
        "requests_planned": 1,
        "requests_started": 1,
        "responses_saved": 1,
        "requests_failed": 0,
        "requests_unexecuted": 0,
        "target_dates_planned": 2,
        "target_rows_saved": 2,
        "context_rows_saved": 1,
        "rows_saved": 3,
    }
    assert [item["date"] for item in result["row_classifications"]] == [
        "2026-09-02", "2026-09-04"
    ]
    assert result["response_context"] == [
        {"contract": "RS2609", "date": "2026-09-03"}
    ]


def test_v2_rejects_context_budget_drift() -> None:
    candidate = _candidate_v2()
    candidate["budget"]["allowed_response_context_dates"] = 0  # type: ignore[index]
    candidate.pop("plan_sha256")
    candidate["plan_sha256"] = hashlib.sha256(
        _canonical(candidate).encode()
    ).hexdigest()
    with pytest.raises(native.RecoveryError, match="SOURCE_CANDIDATE_INVALID"):
        _batch(candidate)


@pytest.mark.parametrize(
    ("rows", "error_code"),
    [
        ([_row(date(2026, 9, 2))], "SOURCE_RESPONSE_TARGET_MISSING"),
        (
            [_row(date(2026, 9, 2)), _row(date(2026, 9, 4)), _row(date(2026, 9, 5))],
            "SOURCE_RESPONSE_DATE_OUT_OF_RANGE",
        ),
        (
            [_row(date(2026, 9, 2)), _row(date(2026, 9, 3)), _row(date(2026, 9, 4))],
            "SOURCE_RESPONSE_DATE_UNPROVEN",
        ),
        (
            [_row(date(2026, 9, 2), contract="WRONG"), _row(date(2026, 9, 4))],
            "SOURCE_RESPONSE_CONTRACT_MISMATCH",
        ),
        (
            [_row(date(2026, 9, 2)), _row(date(2026, 9, 2)), _row(date(2026, 9, 4))],
            "SOURCE_RESPONSE_DUPLICATE",
        ),
    ],
)
def test_v2_response_identity_fail_closed(
    tmp_path: Path, rows: list[dict[str, object]], error_code: str
) -> None:
    candidate = (
        _candidate_v2(allowed=["2026-09-02", "2026-09-04"])
        if error_code == "SOURCE_RESPONSE_DATE_UNPROVEN"
        else _candidate_v2()
    )
    args = _args(tmp_path)
    args.expected_plan_sha256 = candidate["plan_sha256"]
    result = source_verify.execute_batch(
        args,
        _batch(candidate),
        {},
        _identity(),
        client_factory=lambda _settings: _Client(rows),
    )
    assert result["status"] == "failed"
    assert result["failed"]["error_code"] == error_code
    assert result["attempt"]["responses_saved"] == 1


def test_continuation_order_is_disjoint_from_every_started_request() -> None:
    order = source_verify._continuation_order(tuple(range(9)), 16)
    assert order == (13, 14, 11, 12, 9, 10, 15)
    assert set(order).isdisjoint(range(9))
    with pytest.raises(native.RecoveryError, match="SOURCE_CONTINUATION_OVERLAP"):
        source_verify._continuation_order(tuple(range(8)), 16)


def test_offline_validator_uses_saved_bytes_and_keeps_old_receipts_immutable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = _batch()
    attempt = native.create_attempt_directory(tmp_path, "old-failed-attempt")
    journal = source_verify.D1SourceAttemptJournal(attempt, batch.requests)
    journal.before_request(batch.requests[0])
    journal.after_response(
        batch.requests[0],
        tuple(
            [_row(date(2026, 9, 2)), _row(date(2026, 9, 3)), _row(date(2026, 9, 4))]
        ),
    )
    journal.mark_failed("SOURCE_RESPONSE_IDENTITY_INVALID", sequence=1)
    (attempt / "invocation-receipt.json").write_text('{"status":"old"}\n')
    (attempt / "source-only-result.json").write_text('{"status":"failed"}\n')
    authority_batch = _batch(_candidate_v2())
    monkeypatch.setattr(
        source_verify,
        "_authority_selections",
        lambda _settings, _selections: authority_batch.selections,
    )
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in attempt.iterdir()
    }
    verdict = source_verify.offline_validate_attempt(batch, attempt, {})
    after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in attempt.iterdir()
    }
    assert verdict["status"] == "offline_validation_passed"
    assert verdict["provider_requests"] == verdict["data_writes"] == 0
    assert verdict["summary"] == {
        "responses_validated": 1,
        "response_rows": 3,
        "target_rows": 2,
        "context_rows": 1,
    }
    assert verdict["original_raw_hashes_before"] == verdict["original_raw_hashes_after"]
    assert before == after


def test_v2_cli_scope_rejects_different_output_root_before_execution(
    tmp_path: Path,
) -> None:
    candidate = _candidate_v2()
    args = SimpleNamespace(output_root=str(tmp_path.resolve()), attempt_id="attempt-001")
    with pytest.raises(native.RecoveryError, match="SOURCE_EXECUTION_SCOPE_MISMATCH"):
        source_verify._validate_v2_cli_scope(args, _batch(candidate))


def test_readonly_output_is_restricted_to_exact_evidence_name(tmp_path: Path) -> None:
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    with pytest.raises(native.RecoveryError, match="SOURCE_EVIDENCE_PATH_INVALID"):
        source_verify._validated_evidence_output(
            tmp_path / "arbitrary.json",
            attempt,
            "offline-validate",
            tmp_path / "canonical",
        )


@pytest.mark.parametrize(
    "name",
    ["invocation-receipt.json", "journal.jsonl", "source-only-result.json"],
)
def test_continuation_gate_rejects_changed_old_artifact(
    tmp_path: Path, name: str
) -> None:
    values = {
        "invocation-receipt.json": b"receipt\n",
        "journal.jsonl": b"journal\n",
        "source-only-result.json": b"result\n",
    }
    hashes: dict[str, str] = {}
    for filename, content in values.items():
        (tmp_path / filename).write_bytes(content)
        hashes[filename] = hashlib.sha256(content).hexdigest()
    contract = {
        "continuation_of_journal_sha256": hashes["journal.jsonl"],
        "continuation_of_result_sha256": hashes["source-only-result.json"],
    }
    source_verify._validate_current_artifact_hashes(
        tmp_path, {"original_artifact_hashes_after": hashes}, contract
    )
    (tmp_path / name).write_bytes(b"changed\n")
    with pytest.raises(
        native.RecoveryError, match="SOURCE_CONTINUATION_EVIDENCE_INVALID"
    ):
        source_verify._validate_current_artifact_hashes(
            tmp_path, {"original_artifact_hashes_after": hashes}, contract
        )
