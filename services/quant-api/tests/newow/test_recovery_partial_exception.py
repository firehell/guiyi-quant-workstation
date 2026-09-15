from __future__ import annotations

from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.newow_recovery_partial_exception import (
    CLASSIFICATION,
    ERROR_CODE,
    SCHEMA_VERSION,
    derive_partial_source_exceptions,
    validate_partial_source_exception,
)
from scripts.newow_weekly_recovery import (
    AttemptJournal,
    RecoveryError,
    _write_json_exclusive,
)
from app.market_data.rqdata_adapter import ExchangeDailySourceRequest


IDENTITY = {
    "code_commit": "b" * 40,
    "execution_code_sha256": "d" * 64,
    "config_sha256": "c" * 64,
    "canonical_root_sha256": "e" * 64,
}


def _target(month: int, *, symbol: str = "b", contract: str = "B2411") -> dict[str, Any]:
    last_day = 30 if month == 11 else 29
    return {
        "dataset": ["contract", symbol, contract, "1d"],
        "year": 2023,
        "month": month,
        "expected_start": f"2023-{month:02d}-01T07:00:00+00:00",
        "expected_end": f"2023-{month:02d}-{last_day}T07:00:00+00:00",
        "expected_bar_count": 2,
        "missing_bar_count": 2,
        "missing_start": f"2023-{month:02d}-01T07:00:00+00:00",
        "missing_end": f"2023-{month:02d}-{last_day}T07:00:00+00:00",
    }


def _source(month: int, *, contract: str = "B2411") -> ExchangeDailySourceRequest:
    last_day = 30 if month == 11 else 29
    return ExchangeDailySourceRequest(
        contract=contract,
        start=date(2023, month, 1),
        end=date(2023, month, last_day),
        expected_dates=(date(2023, month, 1), date(2023, month, last_day)),
    )


def _row(day: date, *, invalid: bool = False) -> dict[str, Any]:
    return {
        "date": day,
        "open": Decimal("0") if invalid else Decimal("100.10"),
        "high": Decimal("0") if invalid else Decimal("101.20"),
        "low": Decimal("0") if invalid else Decimal("99.30"),
        "close": Decimal("100.40"),
        "volume": Decimal("10"),
        "total_turnover": Decimal("1004.00"),
        "open_interest": Decimal("20"),
        "settlement": Decimal("100.50"),
        "prev_settlement": Decimal("100.00"),
    }


def _readbacks(committed: list[dict[str, Any]]) -> dict[str, Any]:
    partitions = [
        {
            "dataset": list(item["dataset"]),
            "year": item["year"],
            "month": item["month"],
            "row_count": item["expected_bar_count"],
            "file_sha256": "a" * 64,
            "bar_count": item["expected_bar_count"],
        }
        for item in committed
    ]
    return {
        "catalog_readback": {"status": "passed", "partitions": partitions},
        "parquet_readback": {"status": "passed", "files": partitions},
        "mds_readback": {"status": "passed", "windows": partitions},
    }


def _write_unit_evidence(parent: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    parent.mkdir(parents=True, exist_ok=True)
    unit_dir = parent / "unit-001-b-B2411"
    unit_dir.mkdir()
    committed = _target(11)
    failed = _target(12)
    remaining = [_target(12), _target(1)]
    remaining[1]["year"] = 2024
    remaining[1]["month"] = 1
    remaining[1]["expected_start"] = "2024-01-01T07:00:00+00:00"
    remaining[1]["expected_end"] = "2024-01-31T07:00:00+00:00"
    remaining[1]["missing_start"] = "2024-01-01T07:00:00+00:00"
    remaining[1]["missing_end"] = "2024-01-31T07:00:00+00:00"
    nov = _source(11)
    dec = _source(12)
    jan = ExchangeDailySourceRequest(
        contract="B2411",
        start=date(2024, 1, 2),
        end=date(2024, 1, 31),
        expected_dates=(date(2024, 1, 2), date(2024, 1, 31)),
    )
    journal = AttemptJournal(unit_dir, (nov, dec, jan))
    journal.before_request(nov)
    journal.after_response(
        nov,
        tuple(_row(day) for day in nov.expected_dates),
    )
    journal.before_request(dec)
    journal.after_response(
        dec,
        tuple(_row(day, invalid=True) for day in dec.expected_dates),
    )
    journal.mark_failed("RECOVERY_RESULT_NOT_PASSED")
    failed_unit = {
        "symbol": "b",
        "contract": "B2411",
        "through": "2024-10-23",
        "frequency": "1d",
        "plan_sha256": "1" * 64,
        "target_count": 3,
        "expected_bar_count": 6,
        "targets": [committed, failed, remaining[1]],
        "source_requests": [
            {
                "method": "futures.get_exchange_daily",
                "contract": "B2411",
                "start": nov.start.isoformat(),
                "end": nov.end.isoformat(),
                "expected_dates": [day.isoformat() for day in nov.expected_dates],
            },
            {
                "method": "futures.get_exchange_daily",
                "contract": "B2411",
                "start": dec.start.isoformat(),
                "end": dec.end.isoformat(),
                "expected_dates": [day.isoformat() for day in dec.expected_dates],
            },
            {
                "method": "futures.get_exchange_daily",
                "contract": "B2411",
                "start": jan.start.isoformat(),
                "end": jan.end.isoformat(),
                "expected_dates": [day.isoformat() for day in jan.expected_dates],
            },
        ],
        "status": "partial",
        "result": {
            "status": "partial",
            "applied": 1,
            "blocked": 0,
            "failed": 1,
            "provider_requests": 2,
            "failures": [
                {
                    "dataset": ["contract", "b", "B2411", "1d"],
                    "year": 2023,
                    "month": 12,
                    "reason_code": "RQDATA_ZERO_OHL_INVALID",
                }
            ],
        },
        "attempt": {
            "state": "failed",
            "outcome_unknown": False,
            "retry_allowed": False,
            "requests_started": 2,
            "responses_saved": 2,
        },
        "retries": 0,
    }
    _write_json_exclusive(unit_dir / "unit-result.json", failed_unit)
    fresh_unit = {
        "symbol": "b",
        "contract": "B2411",
        "through": "2024-10-23",
        "frequency": "1d",
        "plan_sha256": "2" * 64,
        "status": "PROPOSED",
        "targets": [failed, remaining[1]],
    }
    return unit_dir, failed_unit, fresh_unit


def _valid_kwargs(tmp_path: Path) -> dict[str, Any]:
    native_dir = tmp_path / "batch-001" / "native"
    unit_dir, failed_unit, fresh_unit = _write_unit_evidence(native_dir)
    committed = [failed_unit["targets"][0]]
    return {
        "unit_dir": unit_dir,
        "expected_parent": native_dir,
        "fresh_unit": fresh_unit,
        "failed_attempt_id": "apply-001",
        "failed_execution_commit": "a" * 40,
        "failed_execution_code_sha256": "f" * 64,
        **_readbacks(committed),
        "current_identity": IDENTITY,
        "expected_identity": IDENTITY,
    }


def test_partial_source_exception_accepts_strict_subset_and_replay(tmp_path: Path) -> None:
    payload = validate_partial_source_exception(**_valid_kwargs(tmp_path))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["classification"] == CLASSIFICATION
    assert payload["error_code"] == "RQDATA_ZERO_OHL_INVALID"
    assert payload["outcome_unknown"] is False
    assert payload["retries"] == 0
    assert payload["requests_started"] == payload["responses_saved"] == 2
    assert [item["month"] for item in payload["committed_targets"]] == [11]
    assert [item["month"] for item in payload["remaining_targets"]] == [12, 1]
    assert payload["failed_plan_sha256"] != payload["fresh_replan_sha256"]
    assert payload["source_request_identity"]["start"] == "2023-12-01"


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_journal",
        "fresh_not_subset",
        "identity_mismatch",
        "committed_readback_missing",
        "exception_target_disappeared",
        "source_replay_wrong_code",
        "outcome_unknown",
        "retry_recorded",
        "extra_write",
        "identity_drift",
        "weekly_frequency",
        "zero_commit",
        "sha_mismatch",
    ],
)
def test_partial_source_exception_fail_closed(
    tmp_path: Path, mutation: str
) -> None:
    kwargs = _valid_kwargs(tmp_path)
    if mutation == "missing_journal":
        (kwargs["unit_dir"] / "journal.jsonl").unlink()
    elif mutation == "fresh_not_subset":
        kwargs["fresh_unit"] = {
            **kwargs["fresh_unit"],
            "targets": [_target(11), _target(12)],
        }
    elif mutation == "identity_mismatch":
        kwargs["fresh_unit"] = {**kwargs["fresh_unit"], "contract": "B2412"}
    elif mutation == "committed_readback_missing":
        kwargs["catalog_readback"] = {"status": "passed", "partitions": []}
    elif mutation == "exception_target_disappeared":
        kwargs["fresh_unit"] = {
            **kwargs["fresh_unit"],
            "targets": [_target(1)],
        }
        kwargs["fresh_unit"]["targets"][0]["year"] = 2024
        kwargs["fresh_unit"]["targets"][0]["month"] = 1
    elif mutation == "source_replay_wrong_code":
        path = kwargs["unit_dir"] / "source-response-0002.json"
        payload = json.loads(path.read_text())
        for row in payload["rows"]:
            row["open"] = "100.10"
            row["high"] = "101.20"
            row["low"] = "99.30"
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        path.write_text(raw)
        records = [
            json.loads(line)
            for line in (kwargs["unit_dir"] / "journal.jsonl").read_text().splitlines()
        ]
        records[3]["payload_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
        (kwargs["unit_dir"] / "journal.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in records)
        )
    elif mutation == "outcome_unknown":
        journal = kwargs["unit_dir"] / "journal.jsonl"
        lines = journal.read_text().splitlines()
        journal.write_text("\n".join(lines[:3]) + "\n")
    elif mutation == "retry_recorded":
        result = json.loads((kwargs["unit_dir"] / "unit-result.json").read_text())
        result["retries"] = 1
        (kwargs["unit_dir"] / "unit-result.json").write_text(json.dumps(result))
    elif mutation == "extra_write":
        extra = _target(12)
        extra["row_count"] = 2
        extra["bar_count"] = 2
        extra["file_sha256"] = "b" * 64
        kwargs["catalog_readback"]["partitions"].append(extra)
    elif mutation == "identity_drift":
        kwargs["current_identity"] = {**IDENTITY, "config_sha256": "9" * 64}
    elif mutation == "weekly_frequency":
        result = json.loads((kwargs["unit_dir"] / "unit-result.json").read_text())
        result["frequency"] = "1w"
        (kwargs["unit_dir"] / "unit-result.json").write_text(json.dumps(result))
        kwargs["fresh_unit"] = {**kwargs["fresh_unit"], "frequency": "1w"}
    elif mutation == "zero_commit":
        result = json.loads((kwargs["unit_dir"] / "unit-result.json").read_text())
        result["status"] = "failed"
        result["result"]["status"] = "failed"
        result["result"]["applied"] = 0
        (kwargs["unit_dir"] / "unit-result.json").write_text(json.dumps(result))
    else:
        payload = json.loads(
            (kwargs["unit_dir"] / "source-response-0002.json").read_text()
        )
        (kwargs["unit_dir"] / "source-response-0002.json").write_text(
            json.dumps(payload)
        )
        # Corrupt saved hash in journal by rewriting the sha field.
        journal = kwargs["unit_dir"] / "journal.jsonl"
        records = [json.loads(line) for line in journal.read_text().splitlines()]
        records[3]["payload_sha256"] = "c" * 64
        journal.write_text("".join(json.dumps(item) + "\n" for item in records))

    with pytest.raises(RecoveryError, match=f"^{ERROR_CODE}$"):
        validate_partial_source_exception(**kwargs)


def test_derive_partial_exception_from_failed_attempt_excludes_handwritten_list(
    tmp_path: Path,
) -> None:
    kwargs = _valid_kwargs(tmp_path)
    attempt = tmp_path / "apply-001"
    batch = attempt / "batch-001" / "native"
    batch.mkdir(parents=True)
    unit_dir = kwargs["unit_dir"]
    (batch / unit_dir.name).mkdir()
    for name in ("journal.jsonl", "source-response-0001.json", "source-response-0002.json", "unit-result.json"):
        (batch / unit_dir.name / name).write_bytes((unit_dir / name).read_bytes())
    failed_unit = json.loads((batch / unit_dir.name / "unit-result.json").read_text())
    _write_json_exclusive(
        attempt / "campaign-started.json",
        {
            "schema_version": "newow_weekly_recovery_campaign_started_v1",
            "retries": 0,
            "execution_identity": IDENTITY,
            "campaign_manifest_sha256": "3" * 64,
        },
    )
    _write_json_exclusive(
        attempt / "campaign-result.json",
        {
            "status": "partial",
            "retries": 0,
            "unknown_batch": None,
            "failed_batch": {
                "batch_id": "batch-001",
                "native_result": {
                    "status": "partial",
                    "result": {"completed": [], "failed": failed_unit, "unattempted": []},
                },
            },
        },
    )
    observed = _readbacks([failed_unit["targets"][0]])

    bindings = derive_partial_source_exceptions(
        evidence_root=tmp_path,
        attempt_path=attempt,
        fresh_units=[kwargs["fresh_unit"]],
        current_identity=IDENTITY,
        observe_committed=lambda _unit, _committed: observed,
    )

    assert len(bindings) == 1
    assert bindings[0]["contract"] == "B2411"
    assert bindings[0]["classification"] == CLASSIFICATION
    assert bindings[0]["failed_attempt_path"] == "apply-001"


def test_derive_rejects_handwritten_contract_without_evidence(tmp_path: Path) -> None:
    attempt = tmp_path / "apply-001"
    attempt.mkdir()
    _write_json_exclusive(attempt / "campaign-started.json", {"retries": 0})
    _write_json_exclusive(
        attempt / "campaign-result.json",
        {"retries": 0, "failed_batch": {"batch_id": "batch-001"}},
    )
    with pytest.raises(RecoveryError, match=f"^{ERROR_CODE}$"):
        derive_partial_source_exceptions(
            evidence_root=tmp_path,
            attempt_path=attempt,
            fresh_units=[{"symbol": "b", "contract": "B2411", "frequency": "1d"}],
            current_identity=IDENTITY,
            observe_committed=lambda *_args: {},
        )
