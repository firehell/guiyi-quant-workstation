from __future__ import annotations

import inspect
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import threading
import subprocess
from types import SimpleNamespace
from typing import Any, Mapping

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import CanonicalBar, DatasetKey
from app.market_data.historical_data_manager import (
    BarBatch,
    BarFetchRequest,
    ContractWarmupRequest,
    HistoricalDataManager,
)
from app.market_data.newow.product_release import deferred_section_reason
from app.market_data.operational_universe import load_operational_products
from app.market_data.rqdata_adapter import ExchangeDailySourceRequest
from app.market_data.storage import CanonicalMonthlyStore
from app.models import Contract, Exchange, Instrument, TradingCalendar, TradingSession
from scripts.newow_weekly_recovery import (
    AttemptJournal,
    RecoveryError,
    _post_commit_readback,
    _write_json_exclusive,
    execute_prepared_batch,
    load_prepared_manifest,
    prepare_bounded_units,
    read_attempt_outcome,
    write_prepared_manifest,
)
from scripts import newow_weekly_recovery_campaign as campaign
from scripts.newow_recovery_partial_exception import (
    CLASSIFICATION as PARTIAL_EXCEPTION_CLASSIFICATION,
    ERROR_CODE as PARTIAL_EXCEPTION_INVALID,
)
from scripts.newow_weekly_recovery_campaign import (
    execute_campaign,
    main,
    parser,
    partition_ordinary_units,
    prepare_campaign,
    validate_campaign_manifest,
)
from tests.data_foundation.test_historical_data_manager import (
    FakeCoverage,
    FakeMetadata,
)


IDENTITY = {
    "code_commit": "b" * 40,
    "execution_code_sha256": "d" * 64,
    "config_sha256": "c" * 64,
    "canonical_root_sha256": "e" * 64,
}


def _ordinary_unit(index: int = 0) -> dict[str, Any]:
    return {
        "symbol": "ag",
        "contract": f"AG{1000 + index}",
        "through": "2026-09-11",
        "requested_through": "2026-09-11",
        "frequency": "1w",
        "plan_sha256": f"{index:064x}",
        "status": "PROPOSED",
        "expected_bar_count": index + 1,
        "consumers": [
            {"strategy": strategy, "frequency": "1w", "section": section}
            for section in ("chart", "auxiliary", "reference")
            for strategy in ("trend", "oscillation", "main_rise")
        ],
        "target_windows": [
            {
                "dataset": ["contract", "ag", f"AG{1000 + index}", "1d"],
                "year": 2026,
                "month": 9,
                "expected_bar_count": index + 1,
            },
            {
                "dataset": ["contract", "ag", f"AG{1000 + index}", "1w"],
                "year": 2026,
                "month": 9,
                "expected_bar_count": 1,
            },
        ],
    }


def _report(units: list[dict[str, Any]]) -> dict[str, Any]:
    as_of = "2026-09-13T06:36:13+00:00"
    products = load_operational_products()
    requested: dict[str, dict[str, str]] = {}
    for item in units:
        requested.setdefault(item["symbol"], {})[item["contract"]] = item["through"]
    owners_by_symbol = {
        symbol: (requested.get(symbol) or {f"{symbol.upper()}1000": "2026-09-11"})
        for symbol in products
    }
    enumerations = []
    for symbol in products:
        for section in ("chart", "auxiliary", "reference", "explanation"):
            row: dict[str, Any] = {
                "symbol": symbol,
                "frequency": "1w",
                "section": section,
                "status": "ENUMERATED",
                "as_of": as_of,
            }
            reason = deferred_section_reason(section)
            if reason is not None:
                row.update(status="UNOPENED", reason=reason)
            else:
                row.update(
                    since="2024-01-01",
                    through="2026-09-11",
                    owner_count=len(owners_by_symbol[symbol]),
                )
            enumerations.append(row)
    dependencies = []
    repair_keys = {(item["symbol"], item["contract"]) for item in units}
    for symbol, contracts in owners_by_symbol.items():
        for contract, through in contracts.items():
            for cutoff, sections in (
                (as_of, ("chart", "auxiliary")),
                ("2026-09-11T07:00:00+00:00", ("reference",)),
            ):
                dependency: dict[str, Any] = {
                    "symbol": symbol,
                    "contract": contract,
                    "frequency": "1w",
                    "through": through,
                    "as_of": cutoff,
                    "consumers": [
                        {
                            "strategy": strategy,
                            "frequency": "1w",
                            "section": section,
                        }
                        for section in sections
                        for strategy in ("trend", "oscillation", "main_rise")
                    ],
                    "owners": [{"since": "2024-01-01", "through": through}],
                }
                if (symbol, contract) in repair_keys:
                    dependency.update(
                        status="DATA_UNAVAILABLE",
                        reason="REPLAY_PREFIX_MISSING",
                        error={"code": "NEWOW_DATA_UNAVAILABLE", "diagnostic": {}},
                    )
                else:
                    dependency.update(
                        status="DATA_READY",
                        cutoff=f"{through}T07:00:00+00:00",
                        actual_bar_count=1,
                        expected_bar_count=1,
                        price_unavailable_count=0,
                        source_quality="NORMAL",
                    )
                dependencies.append(dependency)
    return {
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
        "as_of": as_of,
        "product_count": len(products),
        "main_case_count": 0,
        "main_ready_count": 0,
        "work_used": len(products) * 3 + len(dependencies) + len(units),
        "enumerations": enumerations,
        "dependencies": dependencies,
        "cases": [],
        "metadata_proposals": [],
        "repair_targets": units,
    }


def _daily_unit(index: int = 0) -> dict[str, Any]:
    unit = _ordinary_unit(index)
    unit["frequency"] = "1d"
    unit["consumers"] = [
        {**consumer, "frequency": "1d"} for consumer in unit["consumers"]
    ]
    unit["target_windows"] = [
        target for target in unit["target_windows"] if target["dataset"][3] == "1d"
    ]
    return unit


def _daily_report(units: list[dict[str, Any]]) -> dict[str, Any]:
    report = _report(units)
    report["release_stage"] = "daily"
    report["frequency_scope"] = ["1d"]
    for row in report["enumerations"]:
        row["frequency"] = "1d"
    for row in report["dependencies"]:
        row["frequency"] = "1d"
        row["consumers"] = [
            {**consumer, "frequency": "1d"} for consumer in row["consumers"]
        ]
    return report


def _native_child(
    root: Path,
    batch_id: str,
    units: tuple[dict[str, Any], ...],
    *,
    identity: Mapping[str, str] = IDENTITY,
    with_source_requests: bool = False,
    continuation_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    child_units = []
    recovery_frequency = units[0]["frequency"] if units else "1w"
    for item in units:
        targets = [
            {
                "dataset": ["contract", item["symbol"], item["contract"], "1d"],
                "year": 2026,
                "month": 9,
                "expected_start": "2026-09-01T07:00:00+00:00",
                "expected_end": "2026-09-02T07:00:00+00:00",
                "expected_bar_count": 1,
            }
        ]
        if recovery_frequency == "1w":
            targets.append(
                {
                    "dataset": [
                        "contract",
                        item["symbol"],
                        item["contract"],
                        "1w",
                    ],
                    "year": 2026,
                    "month": 9,
                    "expected_start": "2026-09-04T07:00:00+00:00",
                    "expected_end": "2026-09-04T07:00:00+00:00",
                    "expected_bar_count": 1,
                }
            )
        child_units.append(
            {
                "symbol": item["symbol"],
                "contract": item["contract"],
                "through": item["through"],
                "frequency": item["frequency"],
                "plan_sha256": item["expected_plan_sha256"],
                "target_count": len(targets),
                "expected_bar_count": len(targets),
                "targets": targets,
                "source_requests": (
                    [
                        {
                            "method": "futures.get_exchange_daily",
                            "contract": item["contract"],
                            "start": "2026-09-01",
                            "end": "2026-09-01",
                            "expected_dates": ["2026-09-01"],
                        }
                    ]
                    if with_source_requests
                    else []
                ),
            }
        )
    manifest = {
        "schema_version": (
            "newow_daily_recovery_prepare_v1"
            if recovery_frequency == "1d"
            else "newow_weekly_recovery_prepare_v1"
        ),
        **identity,
        "unit_count": len(child_units),
        "units": child_units,
    }
    if continuation_policy is not None:
        manifest["continuation_policy"] = dict(continuation_policy)
    path = root / f"{batch_id}.prepare.json"
    digest = _write_json_exclusive(path, manifest)
    return {
        "status": "prepared",
        "readonly": True,
        "provider_requests": 0,
        "writes": 0,
        "prepared_file": str(path),
        "prepared_sha256": digest,
        "unit_count": len(child_units),
    }


def _campaign(
    tmp_path: Path,
    count: int,
    *,
    with_source_requests: bool = False,
    continuation_policy: Mapping[str, Any] | None = None,
    name: str = "campaign",
) -> dict[str, Any]:
    return prepare_campaign(
        _report([_ordinary_unit(index) for index in range(count)]),
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda units, batch_id, root: _native_child(
            root,
            batch_id,
            units,
            with_source_requests=with_source_requests,
            continuation_policy=continuation_policy,
        ),
        continuation_policy=continuation_policy,
        name=name,
    )


@pytest.mark.parametrize(
    "count,expected_sizes", [(0, []), (1, [1]), (20, [20]), (21, [20, 1])]
)
def test_daily_campaign_partitions_all_native_units_without_empty_children(
    tmp_path: Path,
    count: int,
    expected_sizes: list[int],
) -> None:
    calls: list[int] = []

    def invoke(units, batch_id, root):
        calls.append(len(units))
        return _native_child(root, batch_id, units)

    manifest = prepare_campaign(
        _daily_report([_daily_unit(index) for index in range(count)]),
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=invoke,
        name=f"daily-{count}",
        recovery_frequency="1d",
    )

    assert calls == expected_sizes
    assert manifest["schema_version"] == "newow_daily_recovery_campaign_v1"
    assert manifest["audit"]["frequency_scope"] == ["1d"]
    assert manifest["scope"]["product_count"] == 60
    assert len(manifest["scope"]["product_universe_sha256"]) == 64
    assert manifest["totals"]["unit_count"] == count
    assert [child["unit_count"] for child in manifest["children"]] == expected_sizes


def test_daily_campaign_rejects_weekly_partial_exception_before_child_prepare(
    tmp_path: Path,
) -> None:
    calls: list[object] = []
    prior = tmp_path / "weekly-attempt"
    prior.mkdir()

    with pytest.raises(
        RecoveryError, match="^D1_PARTIAL_SOURCE_EXCEPTION_UNSUPPORTED$"
    ):
        prepare_campaign(
            _daily_report([_daily_unit()]),
            report_sha256="f" * 64,
            evidence_root=tmp_path,
            execution_identity=IDENTITY,
            invoke_batch=lambda *args: calls.append(args),
            name="daily-reject-partial",
            recovery_frequency="1d",
            partial_source_exception_attempt_path=prior,
            observe_partial_committed=lambda _unit, _targets: {},
        )

    assert calls == []


def test_daily_campaign_rejects_weekly_source_only_evidence_before_child_prepare(
    tmp_path: Path,
) -> None:
    calls: list[object] = []

    with pytest.raises(RecoveryError, match="^D1_SOURCE_ONLY_ISOLATION_UNSUPPORTED$"):
        prepare_campaign(
            _daily_report([_daily_unit()]),
            report_sha256="f" * 64,
            evidence_root=tmp_path,
            execution_identity=IDENTITY,
            invoke_batch=lambda *args: calls.append(args),
            name="daily-reject-source-only",
            recovery_frequency="1d",
            source_only_prepared_path=tmp_path / "weekly-source.prepare.json",
        )

    assert calls == []


@pytest.mark.parametrize(
    ("mode", "error_code", "return_code"),
    [
        ("timeout", "DAILY_VERIFICATION_TIMEOUT", None),
        ("failed", "DAILY_VERIFICATION_PROCESS_FAILED", 2),
        ("missing", "DAILY_VERIFICATION_OUTPUT_MISSING", 0),
        ("empty", "DAILY_VERIFICATION_OUTPUT_EMPTY", 0),
        ("truncated", "DAILY_VERIFICATION_OUTPUT_INVALID", 0),
    ],
)
def test_daily_verification_process_failure_preserves_execution_terminal(
    tmp_path: Path,
    mode: str,
    error_code: str,
    return_code: int | None,
) -> None:
    campaign_path = tmp_path / "daily.prepare.json"
    execution_path = tmp_path / "campaign-execution.json"
    campaign_path.write_text("{}", encoding="utf-8")
    execution_path.write_text('{"status":"passed"}\n', encoding="utf-8")
    before = execution_path.read_bytes()

    def run_process(*_args, **_kwargs):
        if mode == "timeout":
            raise subprocess.TimeoutExpired("verify", 300)
        observation = tmp_path / f"verify-{mode}"
        if mode in {"empty", "truncated"}:
            observation.mkdir()
            (observation / "verification.json").write_text(
                "" if mode == "empty" else '{"schema_version":',
                encoding="utf-8",
            )
        return SimpleNamespace(returncode=2 if mode == "failed" else 0)

    result = campaign._run_daily_verification_process(
        project_env=tmp_path / "project.env",
        campaign_path=campaign_path,
        campaign_sha256="a" * 64,
        execution_path=execution_path,
        execution_sha256="b" * 64,
        output_root=tmp_path,
        observation_id=f"verify-{mode}",
        run_process=run_process,
    )

    expected = {
        "status": "incomplete",
        "error_code": error_code,
    }
    if return_code is not None:
        expected["process_return_code"] = return_code
    assert result == expected
    assert execution_path.read_bytes() == before


def test_daily_verification_process_records_success_and_cleanup_budget(
    tmp_path: Path,
) -> None:
    campaign_path = tmp_path / "daily.prepare.json"
    execution_path = tmp_path / "campaign-execution.json"
    campaign_path.write_text("{}", encoding="utf-8")
    execution_path.write_text('{"status":"passed"}\n', encoding="utf-8")
    observed: dict[str, Any] = {}

    def run_process(command, **kwargs):
        observed.update(command=command, **kwargs)
        observation = tmp_path / "verify-success"
        observation.mkdir()
        (observation / "verification.json").write_text(
            json.dumps(
                {
                    "schema_version": "newow_daily_recovery_verification_v1",
                    "verification_status": "verified",
                    "inventory_complete": True,
                    "ordinary_recovery_complete": True,
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0)

    result = campaign._run_daily_verification_process(
        project_env=tmp_path / "project.env",
        campaign_path=campaign_path,
        campaign_sha256="a" * 64,
        execution_path=execution_path,
        execution_sha256="b" * 64,
        output_root=tmp_path,
        observation_id="verify-success",
        run_process=run_process,
    )

    assert result == {
        "status": "verified",
        "inventory_complete": True,
        "ordinary_recovery_complete": True,
        "observation_dir": str(tmp_path / "verify-success"),
        "process_return_code": 0,
    }
    assert observed["command"][:3] == [
        campaign.sys.executable,
        "-m",
        "scripts.newow_daily_recovery_verification",
    ]
    assert observed["cwd"] == campaign.PROJECT_ROOT
    assert observed["timeout"] > campaign._DAILY_VERIFICATION_AUDIT_TIMEOUT_SECONDS


def test_daily_verification_process_preserves_operator_cancellation(
    tmp_path: Path,
) -> None:
    execution_path = tmp_path / "campaign-execution.json"
    execution_path.write_text('{"status":"passed"}\n', encoding="utf-8")
    before = execution_path.read_bytes()

    def cancel(*_args, **_kwargs):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        campaign._run_daily_verification_process(
            project_env=tmp_path / "project.env",
            campaign_path=tmp_path / "daily.prepare.json",
            campaign_sha256="a" * 64,
            execution_path=execution_path,
            execution_sha256="b" * 64,
            output_root=tmp_path,
            observation_id="verify-cancelled",
            run_process=cancel,
        )

    assert execution_path.read_bytes() == before


@pytest.mark.parametrize("inventory_complete", [True, False])
def test_daily_verification_process_rejects_return_code_status_mismatch(
    tmp_path: Path,
    inventory_complete: bool,
) -> None:
    execution_path = tmp_path / "campaign-execution.json"
    execution_path.write_text('{"status":"passed"}\n', encoding="utf-8")

    def run_process(*_args, **_kwargs):
        observation = tmp_path / "verify-mismatch"
        observation.mkdir()
        (observation / "verification.json").write_text(
            json.dumps(
                {
                    "schema_version": "newow_daily_recovery_verification_v1",
                    "verification_status": "verified",
                    "inventory_complete": inventory_complete,
                    "ordinary_recovery_complete": True,
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=1)

    result = campaign._run_daily_verification_process(
        project_env=tmp_path / "project.env",
        campaign_path=tmp_path / "campaign.prepare.json",
        campaign_sha256="a" * 64,
        execution_path=execution_path,
        execution_sha256="b" * 64,
        output_root=tmp_path,
        observation_id="verify-mismatch",
        run_process=run_process,
    )

    assert result == {
        "status": "incomplete",
        "error_code": "DAILY_VERIFICATION_RESULT_MISMATCH",
        "process_return_code": 1,
    }


def test_cli_apply_rejects_zero_target_daily_campaign_without_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import newow_weekly_recovery_campaign as module

    prepare_campaign(
        _daily_report([]),
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda *_args: pytest.fail("zero target cannot create child"),
        name="daily-zero",
        recovery_frequency="1d",
    )
    campaign_path = tmp_path / "daily-zero.prepare.json"
    campaign_sha256 = hashlib.sha256(campaign_path.read_bytes()).hexdigest()
    calls: list[object] = []
    monkeypatch.setattr(module.native, "main", lambda *_args, **_kwargs: calls.append(1))
    output = io.StringIO()

    code = main(
        [
            "apply",
            "--project-env",
            str(tmp_path / "project.env"),
            "--campaign",
            str(campaign_path),
            "--expected-campaign-sha256",
            campaign_sha256,
            "--output-root",
            str(tmp_path),
            "--attempt-id",
            "zero-apply",
            "--apply",
        ],
        stdout=output,
    )

    assert code == 1
    assert json.loads(output.getvalue())["error_code"] == "D1_EXECUTION_NOT_REQUIRED"
    assert calls == []
    assert not (tmp_path / "zero-apply").exists()
    assert not list(tmp_path.glob("**/campaign-execution.json"))


def _native_apply_result(
    child_path: Path,
    digest: str,
    batch_attempt: Path,
    *,
    status: str = "passed",
    return_code: int | None = None,
    completed: list[dict[str, Any]] | None = None,
    failed_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    child = json.loads(child_path.read_text(encoding="utf-8"))
    recovery_frequency = child["units"][0]["frequency"]
    native_attempt = batch_attempt / "native"
    native_attempt.mkdir()
    if completed is None and status == "passed":
        completed = [
            {
                **unit,
                "status": "passed",
                "remaining_target_count": 0,
                "readback": {
                    "catalog_physical_mds": "passed",
                    "mds_target_count": unit["target_count"],
                },
            }
            for unit in child["units"]
        ]
    completed_value = completed if completed is not None else []
    for index, completed_unit in enumerate(completed_value):
        frozen_unit = child["units"][index]
        completed_unit.setdefault(
            "result",
            {
                "status": completed_unit["status"],
                "applied": 0,
                "blocked": 0,
                "failed": 0,
                "provider_requests": (
                    frozen_unit["target_count"] if frozen_unit["source_requests"] else 0
                ),
                "failures": [],
            },
        )
        unit_dir = native_attempt / (
            f"unit-{index + 1:03d}-{frozen_unit['symbol']}-{frozen_unit['contract']}"
        )
        unit_dir.mkdir()
        source_requests = tuple(
            ExchangeDailySourceRequest(
                contract=item["contract"],
                start=date.fromisoformat(item["start"]),
                end=date.fromisoformat(item["end"]),
                expected_dates=tuple(
                    date.fromisoformat(value) for value in item["expected_dates"]
                ),
            )
            for item in frozen_unit["source_requests"]
        )
        journal = AttemptJournal(unit_dir, source_requests)
        for request in source_requests:
            journal.before_request(request)
            journal.after_response(
                request,
                tuple({"date": value} for value in request.expected_dates),
            )
        completed_unit.setdefault("attempt", read_attempt_outcome(unit_dir))
    failure_index = len(completed_value)
    failed_value = None
    if status != "passed":
        failed_unit = child["units"][failure_index]
        failed_unit_dir = native_attempt / (
            f"unit-{failure_index + 1:03d}-{failed_unit['symbol']}-"
            f"{failed_unit['contract']}"
        )
        failed_unit_dir.mkdir()
        source_requests = tuple(
            ExchangeDailySourceRequest(
                contract=item["contract"],
                start=date.fromisoformat(item["start"]),
                end=date.fromisoformat(item["end"]),
                expected_dates=tuple(
                    date.fromisoformat(value) for value in item["expected_dates"]
                ),
            )
            for item in failed_unit["source_requests"]
        )
        journal = AttemptJournal(failed_unit_dir, source_requests)
        journal.mark_failed("PROVIDER_UNAVAILABLE")
        failed_value = {
            **failed_unit,
            "status": status,
            "error_code": "PROVIDER_UNAVAILABLE",
            "attempt": read_attempt_outcome(failed_unit_dir),
        }
        if failed_fields is not None:
            failed_value.update(dict(failed_fields))
        _write_json_exclusive(failed_unit_dir / "unit-result.json", failed_value)
    native_result = {
        "status": status,
        "completed": completed_value,
        "failed": failed_value,
        "unattempted": (
            [] if status == "passed" else child["units"][failure_index + 1 :]
        ),
        "retries": 0,
    }
    receipt = {
        "schema_version": (
            "newow_daily_recovery_invocation_v1"
            if recovery_frequency == "1d"
            else "newow_weekly_recovery_invocation_v1"
        ),
        "prepared_sha256": digest,
        **IDENTITY,
        "unit_count": len(child["units"]),
    }
    _write_json_exclusive(native_attempt / "invocation-receipt.json", receipt)
    _write_json_exclusive(native_attempt / "batch-result.json", native_result)
    return {
        "return_code": (0 if status == "passed" else 1)
        if return_code is None
        else return_code,
        "batch_result": {
            "schema_version": (
                "newow_daily_recovery_result_v1"
                if recovery_frequency == "1d"
                else "newow_weekly_recovery_result_v1"
            ),
            "status": status,
            "readonly": False,
            "attempt_dir": str(native_attempt),
            "result": native_result,
        },
    }


def test_daily_campaign_executes_all_batches_and_closes_five_way_denominator(
    tmp_path: Path,
) -> None:
    manifest = prepare_campaign(
        _daily_report([_daily_unit(index) for index in range(21)]),
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda units, batch_id, root: _native_child(root, batch_id, units),
        name="daily-execute",
        recovery_frequency="1d",
    )

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "daily-attempt",
        invoke_batch=lambda child, digest, attempt: _native_apply_result(
            child, digest, attempt
        ),
    )

    assert result["status"] == "passed"
    assert result["summary"] == {
        "denominator_unit_count": 21,
        "success_unit_count": 21,
        "isolated_unit_count": 0,
        "partial_source_exception_unit_count": 0,
        "stopping_failure_unit_count": 0,
        "unattempted_unit_count": 0,
        "unknown_unit_count": 0,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("complete", False),
        ("budget_exhausted", True),
        ("as_of", "2026-09-13"),
        ("as_of", "not-a-date"),
        ("frequency_scope", ["1d"]),
        ("matrix", True),
        ("readonly", False),
        ("provider_requests", 1),
        ("writes", 1),
    ],
)
def test_partition_rejects_incomplete_exhausted_or_wrong_audit(
    field: str,
    value: object,
) -> None:
    report = _report([_ordinary_unit()])
    report[field] = value

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(report)


def test_partition_rejects_missing_required_report_field() -> None:
    report = _report([_ordinary_unit()])
    del report["repair_targets"]

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(report)


def test_partition_accepts_daily_stage_weekly_report() -> None:
    report = _report([_ordinary_unit()])
    report["release_stage"] = "daily"

    units = partition_ordinary_units(report)

    assert len(units) == 1


def test_daily_partition_rejects_legacy_weekly_release_stage() -> None:
    report = _daily_report([_daily_unit()])
    report["release_stage"] = "weekly"

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(report, recovery_frequency="1d")


@pytest.mark.parametrize(
    "field",
    [
        "product_count",
        "main_case_count",
        "main_ready_count",
        "work_used",
        "enumerations",
        "dependencies",
        "cases",
    ],
)
def test_partition_rejects_cropped_native_report(field: str) -> None:
    report = _report([_ordinary_unit()])
    del report[field]

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(report)


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_product_count",
        "missing_enumeration",
        "bad_deferred_enumeration",
        "missing_owner_count",
        "wrong_dependency_frequency",
        "missing_dependency_consumers",
        "missing_dependency_owners",
        "wrong_main_counts",
        "wrong_work_used",
    ],
)
def test_partition_rejects_inconsistent_native_report_sections(mutation: str) -> None:
    report = _report([_ordinary_unit()])
    if mutation == "wrong_product_count":
        report["product_count"] -= 1
    elif mutation == "missing_enumeration":
        report["enumerations"].pop()
    elif mutation == "bad_deferred_enumeration":
        report["enumerations"][-1]["reason"] = "WRONG"
    elif mutation == "missing_owner_count":
        del report["enumerations"][0]["owner_count"]
    elif mutation == "wrong_dependency_frequency":
        report["dependencies"][0]["frequency"] = "1d"
    elif mutation == "missing_dependency_consumers":
        del report["dependencies"][0]["consumers"]
    elif mutation == "missing_dependency_owners":
        del report["dependencies"][0]["owners"]
    elif mutation == "wrong_main_counts":
        report["main_case_count"] = 1
    elif mutation == "wrong_work_used":
        report["work_used"] += 1

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(report)


def test_partition_rejects_missing_dependency_even_when_work_used_is_synced() -> None:
    report = _report([_ordinary_unit()])
    report["dependencies"].pop(0)
    report["work_used"] -= 1

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(report)


def test_partition_accepts_explained_weekly_interruption_as_complete_dependency() -> None:
    report = _report([])
    dependency = next(row for row in report["dependencies"] if row["status"] == "DATA_READY")
    dependency.update(
        actual_bar_count=0,
        expected_bar_count=1,
        price_unavailable_count=1,
        source_quality="WEEKLY_INTERRUPTED",
    )

    assert partition_ordinary_units(report) == ()


def test_campaign_loads_hash_locked_full_native_report_over_manifest_limit(tmp_path) -> None:
    report = _report([])
    report["_padding"] = "x" * (17 * 1024 * 1024)
    path = tmp_path / "full-readiness.json"
    content = json.dumps(report).encode()
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()

    assert campaign._load_hash_locked_report(path, digest)["status"] == "audited"
    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        campaign._load_hash_locked_report(path, "0" * 64)


@pytest.mark.parametrize(
    "mutation",
    ["missing_quality", "wrong_count", "wrong_label", "bool_count"],
)
def test_partition_rejects_inconsistent_weekly_interruption_proof(mutation: str) -> None:
    report = _report([])
    dependency = next(row for row in report["dependencies"] if row["status"] == "DATA_READY")
    dependency.update(
        actual_bar_count=0,
        expected_bar_count=1,
        price_unavailable_count=1,
        source_quality="WEEKLY_INTERRUPTED",
    )
    if mutation == "missing_quality":
        del dependency["source_quality"]
    elif mutation == "wrong_count":
        dependency["actual_bar_count"] = 1
    elif mutation == "wrong_label":
        dependency["source_quality"] = "NORMAL"
    elif mutation == "bool_count":
        dependency["price_unavailable_count"] = True

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(report)


def test_partition_rejects_duplicate_full_dependency_identity() -> None:
    report = _report([_ordinary_unit()])
    report["dependencies"].append(deepcopy(report["dependencies"][0]))
    report["work_used"] += 1

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(report)


def test_partition_rejects_owner_removed_from_one_section_coverage() -> None:
    report = _report([])
    symbol = load_operational_products()[0]
    rows = [row for row in report["dependencies"] if row["symbol"] == symbol]
    assert len(rows) == 2
    second_owner = {"since": "2024-02-01", "through": rows[0]["through"]}
    for row in rows:
        row["owners"].append(second_owner)
    for enumeration in report["enumerations"]:
        if enumeration["symbol"] == symbol and enumeration["status"] == "ENUMERATED":
            enumeration["owner_count"] = 2
    rows[0]["owners"].remove(second_owner)

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(report)


@pytest.mark.parametrize(
    "mutation",
    ["missing", "extra", "wrong_through", "missing_consumer"],
)
def test_partition_rejects_repair_group_not_exactly_derived_from_dependencies(
    mutation: str,
) -> None:
    report = _report([_ordinary_unit()])
    if mutation == "missing":
        report["repair_targets"].pop()
        report["work_used"] -= 1
    elif mutation == "extra":
        extra = deepcopy(report["repair_targets"][0])
        extra["contract"] = "AG9999"
        extra["plan_sha256"] = "9" * 64
        report["repair_targets"].append(extra)
        report["work_used"] += 1
    elif mutation == "wrong_through":
        report["repair_targets"][0]["through"] = "2026-09-10"
        report["repair_targets"][0]["requested_through"] = "2026-09-10"
    elif mutation == "missing_consumer":
        report["repair_targets"][0]["consumers"].pop()

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(report)


def test_partition_accepts_review_required_with_exact_dependency_provenance() -> None:
    review = {
        **_ordinary_unit(),
        "status": "REVIEW_REQUIRED",
        "plan_sha256": None,
        "reason": "REPAIR_SCOPE_SOURCE_OR_INTEGRITY",
    }

    assert partition_ordinary_units(_report([review])) == ()


@pytest.mark.parametrize("count", [0, 1, 20, 21, 1117])
def test_partition_has_exact_twenty_unit_boundaries_without_loss(count: int) -> None:
    units = [_ordinary_unit(index) for index in range(count)]

    batches = partition_ordinary_units(_report(units))

    expected_sizes = [20] * (count // 20)
    if count % 20:
        expected_sizes.append(count % 20)
    assert [len(group) for group in batches] == expected_sizes
    assert {
        (unit["symbol"], unit["contract"], unit["frequency"])
        for group in batches
        for unit in group
    } == {(unit["symbol"], unit["contract"], "1w") for unit in units}


def test_partition_excludes_nonordinary_statuses_and_campaign_counts_them(
    tmp_path: Path,
) -> None:
    review = {**_ordinary_unit(1), "status": "REVIEW_REQUIRED"}
    source_error = {
        **_ordinary_unit(2),
        "status": "SOURCE_EXCEPTION",
        "plan_sha256": None,
    }
    report = _report([_ordinary_unit(), review, source_error])

    batches = partition_ordinary_units(report)
    manifest = prepare_campaign(
        report,
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda units, batch_id, root: _native_child(root, batch_id, units),
    )

    assert [[unit["contract"] for unit in group] for group in batches] == [["AG1000"]]
    assert manifest["scope"]["included_status_counts"] == {"PROPOSED": 1}
    assert manifest["scope"]["excluded_status_counts"] == {
        "REVIEW_REQUIRED": 1,
        "SOURCE_EXCEPTION": 1,
    }


@pytest.mark.parametrize(
    "change",
    [
        {},
        {"through": "2026-09-10", "requested_through": "2026-09-10"},
        {"plan_sha256": "f" * 64},
    ],
)
def test_partition_rejects_duplicate_or_conflicting_unit_identity(
    change: dict[str, Any],
) -> None:
    first = _ordinary_unit()
    duplicate = {**first, **change}

    with pytest.raises(RecoveryError, match="^CAMPAIGN_SCOPE_CONFLICT$"):
        partition_ordinary_units(_report([first, duplicate]))


def test_partition_rejects_target_through_after_audit_as_of() -> None:
    unit = {
        **_ordinary_unit(),
        "through": "2026-09-14",
        "requested_through": "2026-09-14",
    }

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(_report([unit]))


def test_prepare_builds_all_children_and_one_hash_locked_campaign(
    tmp_path: Path,
) -> None:
    report = _report([_ordinary_unit(index) for index in range(21)])
    calls: list[tuple[str, int]] = []

    def invoke(
        units: tuple[dict[str, Any], ...], batch_id: str, root: Path
    ) -> dict[str, Any]:
        calls.append((batch_id, len(units)))
        return _native_child(root, batch_id, units)

    manifest = prepare_campaign(
        report,
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=invoke,
    )

    assert [child["batch_id"] for child in manifest["children"]] == [
        "batch-001",
        "batch-002",
    ]
    assert calls == [
        (manifest["children"][0]["artifact_id"], 20),
        (manifest["children"][1]["artifact_id"], 1),
    ]
    assert manifest["totals"] == {
        "batch_count": 2,
        "unit_count": 21,
        "target_count": 42,
        "expected_bar_count": 42,
    }
    assert manifest["children"][0]["unit_count"] == 20
    assert manifest["children"][-1]["unit_count"] == 1
    assert len(manifest["children"][0]["sha256"]) == 64
    assert manifest["children"][0]["path"] == (
        manifest["children"][0]["artifact_id"] + ".prepare.json"
    )
    assert manifest["children"][0]["artifact_id"].startswith("campaign-")
    assert manifest["writer_guard"]["path"] == (
        ".campaign-writer-" + IDENTITY["canonical_root_sha256"] + ".lock"
    )
    assert (tmp_path / manifest["writer_guard"]["path"]).is_file()
    assert len(manifest["scope"]["unit_identity_sha256"]) == 64
    assert len(manifest["scope"]["target_identity_sha256"]) == 64
    assert (tmp_path / "campaign.prepare.json").is_file()
    assert validate_campaign_manifest(manifest, evidence_root=tmp_path) == manifest

    with pytest.raises(RecoveryError, match="^CAMPAIGN_MANIFEST_EXISTS$"):
        prepare_campaign(
            report,
            report_sha256="f" * 64,
            evidence_root=tmp_path,
            execution_identity=IDENTITY,
            invoke_batch=invoke,
        )


def test_prepare_two_named_campaigns_share_root_without_overwriting_children(
    tmp_path: Path,
) -> None:
    report = _report([_ordinary_unit()])

    alpha = prepare_campaign(
        report,
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda units, artifact_id, root: _native_child(
            root, artifact_id, units
        ),
        name="alpha",
    )
    beta = prepare_campaign(
        report,
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda units, artifact_id, root: _native_child(
            root, artifact_id, units
        ),
        name="beta",
    )

    assert alpha["children"][0]["batch_id"] == "batch-001"
    assert beta["children"][0]["batch_id"] == "batch-001"
    assert alpha["children"][0]["path"] != beta["children"][0]["path"]
    assert alpha["writer_guard"] == beta["writer_guard"]
    assert (tmp_path / alpha["children"][0]["path"]).is_file()
    assert (tmp_path / beta["children"][0]["path"]).is_file()


def test_prepare_zero_units_creates_only_readonly_completed_campaign(
    tmp_path: Path,
) -> None:
    calls: list[object] = []

    manifest = prepare_campaign(
        _report([]),
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda *_args: calls.append(True),
    )

    assert calls == []
    assert manifest["status"] == "completed"
    assert manifest["readonly"] is True
    assert manifest["children"] == []
    assert manifest["totals"]["unit_count"] == 0
    assert manifest["provider_requests"] == 0
    assert manifest["writes"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_child",
        "extra_child",
        "reordered",
        "duplicate_unit",
        "wrong_hash",
        "wrong_identity",
        "absolute_path",
        "escaped_path",
    ],
)
def test_validate_campaign_rejects_incomplete_or_drifted_children_before_execution(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest = prepare_campaign(
        _report([_ordinary_unit(index) for index in range(21)]),
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda units, batch_id, root: _native_child(root, batch_id, units),
    )
    changed = deepcopy(manifest)
    if mutation == "missing_child":
        changed["children"].pop()
    elif mutation == "extra_child":
        changed["children"].append(deepcopy(changed["children"][-1]))
        changed["children"][-1]["batch_id"] = "batch-003"
    elif mutation == "reordered":
        changed["children"].reverse()
    elif mutation == "duplicate_unit":
        changed["children"][1]["units"] = [deepcopy(changed["children"][0]["units"][0])]
    elif mutation == "wrong_hash":
        changed["children"][0]["sha256"] = "0" * 64
    elif mutation == "wrong_identity":
        changed["execution_identity"]["config_sha256"] = "0" * 64
    elif mutation == "absolute_path":
        changed["children"][0]["path"] = str(
            (tmp_path / "batch-001.prepare.json").resolve()
        )
    elif mutation == "escaped_path":
        changed["children"][0]["path"] = "../batch-001.prepare.json"

    with pytest.raises(RecoveryError):
        validate_campaign_manifest(changed, evidence_root=tmp_path)


def test_validate_campaign_rejects_symlinked_child(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    manifest = prepare_campaign(
        _report([_ordinary_unit()]),
        report_sha256="f" * 64,
        evidence_root=real,
        execution_identity=IDENTITY,
        invoke_batch=lambda units, batch_id, root: _native_child(root, batch_id, units),
    )
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(RecoveryError, match="^CAMPAIGN_OUTPUT_ROOT_UNSAFE$"):
        validate_campaign_manifest(manifest, evidence_root=linked)


def test_validate_campaign_rejects_target_identity_drift_even_with_new_child_hash(
    tmp_path: Path,
) -> None:
    manifest = _campaign(tmp_path, 1)
    child_path = tmp_path / manifest["children"][0]["path"]
    child = json.loads(child_path.read_text())
    child["units"][0]["targets"][0]["dataset"][3] = "60m"
    child_path.write_text(
        json.dumps(child, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    manifest["children"][0]["sha256"] = hashlib.sha256(
        child_path.read_bytes()
    ).hexdigest()

    with pytest.raises(RecoveryError, match="^CAMPAIGN_CHILD_INVALID$"):
        validate_campaign_manifest(manifest, evidence_root=tmp_path)


def test_validate_campaign_rejects_unit_expected_count_not_closed_by_targets(
    tmp_path: Path,
) -> None:
    manifest = _campaign(tmp_path, 1)
    child_path = tmp_path / manifest["children"][0]["path"]
    child = json.loads(child_path.read_text())
    child["units"][0]["expected_bar_count"] = 3
    child_path.write_text(
        json.dumps(child, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    manifest["children"][0]["sha256"] = hashlib.sha256(
        child_path.read_bytes()
    ).hexdigest()
    manifest["children"][0]["units"][0]["expected_bar_count"] = 3
    manifest["children"][0]["expected_bar_count"] = 3
    manifest["totals"]["expected_bar_count"] = 3

    with pytest.raises(RecoveryError, match="^CAMPAIGN_CHILD_INVALID$"):
        validate_campaign_manifest(manifest, evidence_root=tmp_path)


def test_prepare_rejects_wrong_callback_type_without_campaign(tmp_path: Path) -> None:
    with pytest.raises(RecoveryError, match="^CAMPAIGN_CHILD_INVALID$"):
        prepare_campaign(
            _report([_ordinary_unit()]),
            report_sha256="f" * 64,
            evidence_root=tmp_path,
            execution_identity=IDENTITY,
            invoke_batch=lambda *_args: [],
        )

    assert not (tmp_path / "campaign.prepare.json").exists()


def test_validate_campaign_rejects_oversized_child(tmp_path: Path) -> None:
    manifest = _campaign(tmp_path, 1)
    path = tmp_path / manifest["children"][0]["path"]
    path.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    manifest["children"][0]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(RecoveryError, match="^CAMPAIGN_CHILD_INVALID$"):
        validate_campaign_manifest(manifest, evidence_root=tmp_path)


def test_cli_prepare_uses_native_main_in_process_and_one_evidence_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import newow_weekly_recovery_campaign as module

    report = _report([_ordinary_unit(index) for index in range(21)])
    report_path = tmp_path / "full-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    report_sha256 = hashlib.sha256(report_path.read_bytes()).hexdigest()
    project_env = tmp_path / "project.env"
    project_env.write_text("fixture", encoding="utf-8")
    native_calls: list[list[str]] = []

    monkeypatch.setattr(module, "_current_execution_identity", lambda _path: IDENTITY)

    def native_main(argv: list[str], *, stdout: io.StringIO) -> int:
        native_calls.append(argv)
        assert argv[0] == "prepare"
        assert "--isolate-known-source-quality" in argv
        root = Path(argv[argv.index("--output-root") + 1])
        batch_id = argv[argv.index("--name") + 1]
        units_path = Path(argv[argv.index("--units") + 1])
        assert root == tmp_path
        assert units_path.parent == tmp_path
        units = tuple(json.loads(units_path.read_text()))
        payload = _native_child(
            root,
            batch_id,
            units,
            continuation_policy=_campaign_isolation_policy(),
        )
        stdout.write(json.dumps(payload))
        return 0

    monkeypatch.setattr(module.native, "main", native_main)
    output = io.StringIO()

    code = main(
        [
            "prepare",
            "--project-env",
            str(project_env),
            "--report",
            str(report_path),
            "--expected-report-sha256",
            report_sha256,
            "--output-root",
            str(tmp_path),
            "--name",
            "campaign",
            "--isolate-known-source-quality",
        ],
        stdout=output,
    )

    payload = json.loads(output.getvalue())
    assert code == 0
    assert payload["status"] == "prepared"
    assert payload["readonly"] is True
    assert payload["provider_requests"] == 0
    assert payload["writes"] == 0
    assert payload["batch_count"] == 2
    assert len(native_calls) == 2
    assert Path(payload["campaign_file"]) == tmp_path / "campaign.prepare.json"
    assert (
        hashlib.sha256((tmp_path / "campaign.prepare.json").read_bytes()).hexdigest()
        == payload["campaign_sha256"]
    )


def test_cli_prepare_rejects_report_hash_mismatch_before_native_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import newow_weekly_recovery_campaign as module

    report_path = tmp_path / "full-report.json"
    report_path.write_text(json.dumps(_report([_ordinary_unit()])), encoding="utf-8")
    project_env = tmp_path / "project.env"
    project_env.write_text("fixture", encoding="utf-8")
    native_calls: list[object] = []
    monkeypatch.setattr(
        module.native, "main", lambda *_args, **_kwargs: native_calls.append(True)
    )
    output = io.StringIO()

    code = main(
        [
            "prepare",
            "--project-env",
            str(project_env),
            "--report",
            str(report_path),
            "--expected-report-sha256",
            "0" * 64,
            "--output-root",
            str(tmp_path),
            "--name",
            "campaign",
        ],
        stdout=output,
    )

    assert code == 1
    assert json.loads(output.getvalue())["error_code"] == "CAMPAIGN_REPORT_INVALID"
    assert native_calls == []


def test_daily_cli_error_reports_daily_schema_before_identity_open(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "full-report.json"
    report_path.write_text("{}", encoding="utf-8")
    output = io.StringIO()

    code = main(
        [
            "prepare",
            "--project-env",
            str(tmp_path / "project.env"),
            "--report",
            str(report_path),
            "--expected-report-sha256",
            "0" * 64,
            "--output-root",
            str(tmp_path),
            "--name",
            "campaign",
            "--frequency",
            "1d",
        ],
        stdout=output,
    )

    assert code == 1
    assert json.loads(output.getvalue())["schema_version"] == (
        "newow_daily_recovery_campaign_error_v1"
    )


def test_campaign_cli_exposes_prepare_apply_and_inspect_modes() -> None:
    assert "{prepare,apply,inspect}" in parser().format_help()


def test_daily_campaign_inspect_reports_daily_schema(tmp_path: Path) -> None:
    attempt = tmp_path / "daily-attempt"
    attempt.mkdir()
    _write_json_exclusive(
        attempt / "campaign-started.json",
        {"schema_version": "newow_daily_recovery_campaign_started_v1"},
    )
    _write_json_exclusive(attempt / "campaign-result.json", {"status": "passed"})
    output = io.StringIO()

    code = main(["inspect", "--attempt", str(attempt)], stdout=output)

    assert code == 0
    assert json.loads(output.getvalue())["schema_version"] == (
        "newow_daily_recovery_campaign_result_v1"
    )


def test_campaign_cli_exposes_hash_bound_prior_isolation_inputs() -> None:
    args = parser().parse_args(
        [
            "prepare",
            "--project-env",
            "/tmp/project.env",
            "--report",
            "/tmp/report.json",
            "--expected-report-sha256",
            "a" * 64,
            "--output-root",
            "/tmp/evidence",
            "--name",
            "fresh",
            "--isolate-known-source-quality",
            "--prior-campaign",
            "/tmp/evidence/prior.prepare.json",
            "--expected-prior-campaign-sha256",
            "b" * 64,
            "--prior-attempt",
            "/tmp/evidence/prior-attempt",
        ]
    )

    assert args.isolate_known_source_quality is True
    assert args.prior_campaign.endswith("prior.prepare.json")
    assert args.expected_prior_campaign_sha256 == "b" * 64
    assert args.prior_attempt.endswith("prior-attempt")


def test_campaign_cli_exposes_hash_bound_source_only_isolation_inputs() -> None:
    args = parser().parse_args(
        [
            "prepare",
            "--project-env",
            "/tmp/project.env",
            "--report",
            "/tmp/report.json",
            "--expected-report-sha256",
            "a" * 64,
            "--output-root",
            "/tmp/evidence",
            "--name",
            "fresh",
            "--isolate-known-source-quality",
            "--source-only-prepared",
            "/tmp/evidence/source.prepare.json",
            "--expected-source-only-prepared-sha256",
            "b" * 64,
            "--source-only-attempt",
            "/tmp/evidence/source-attempt",
            "--source-only-unit-index",
            "0",
            "--source-only-request-index",
            "0",
            "--expected-source-only-request-sha256",
            "c" * 64,
        ]
    )

    assert args.source_only_prepared.endswith("source.prepare.json")
    assert args.expected_source_only_prepared_sha256 == "b" * 64
    assert args.source_only_attempt.endswith("source-attempt")
    assert args.source_only_unit_index == 0
    assert args.source_only_request_index == 0
    assert args.expected_source_only_request_sha256 == "c" * 64


def test_execute_stops_after_second_batch_failure_without_retry(tmp_path: Path) -> None:
    manifest = _campaign(tmp_path, 41)
    invoked: list[str] = []

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        batch_id = attempt.name
        invoked.append(batch_id)
        return _native_apply_result(
            child,
            digest,
            attempt,
            status="passed" if batch_id == "batch-001" else "failed",
        )

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert invoked == ["batch-001", "batch-002"]
    assert result["status"] == "partial"
    assert result["completed_batch_ids"] == ["batch-001"]
    assert result["failed_batch"]["batch_id"] == "batch-002"
    assert result["unattempted_batch_ids"] == ["batch-003"]
    assert result["summary"] == {
        "denominator_unit_count": 41,
        "success_unit_count": 20,
        "isolated_unit_count": 0,
        "partial_source_exception_unit_count": 0,
        "stopping_failure_unit_count": 1,
        "unattempted_unit_count": 20,
        "unknown_unit_count": 0,
    }
    assert result["retries"] == 0


def test_execute_preserves_native_partial_success_exactly(tmp_path: Path) -> None:
    manifest = _campaign(tmp_path, 22)

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        prepared = json.loads(child.read_text())
        unit = prepared["units"][0]
        completed = [
            {
                **unit,
                "status": "passed",
                "remaining_target_count": 0,
                "readback": {
                    "catalog_physical_mds": "passed",
                    "mds_target_count": unit["target_count"],
                },
            }
        ]
        return _native_apply_result(
            child,
            digest,
            attempt,
            status="partial" if attempt.name == "batch-002" else "passed",
            completed=completed if attempt.name == "batch-002" else None,
        )

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert result["status"] == "partial"
    assert (
        result["failed_batch"]["native_result"]["result"]["completed"][0]["contract"]
        == "AG1020"
    )
    assert result["retries"] == 0


def test_execute_rejects_passed_terminal_without_all_frozen_units(
    tmp_path: Path,
) -> None:
    manifest = _campaign(tmp_path, 1)

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=lambda child, digest, attempt: _native_apply_result(
            child, digest, attempt, completed=[]
        ),
    )

    assert result["status"] == "unknown"
    assert result["unknown_batch"] == {
        "batch_id": "batch-001",
        "error_code": "CAMPAIGN_BATCH_OUTCOME_UNKNOWN",
    }


def test_execute_rejects_terminal_with_wrong_native_receipt(tmp_path: Path) -> None:
    manifest = _campaign(tmp_path, 1)

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        value = _native_apply_result(child, digest, attempt)
        receipt_path = attempt / "native" / "invocation-receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["prepared_sha256"] = "0" * 64
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        return value

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert result["status"] == "unknown"
    assert result["completed_batch_ids"] == []


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_unit_identity",
        "remaining_targets",
        "failed_readback",
        "wrong_readback_count",
        "unexpected_failed",
        "unexpected_unattempted",
    ],
)
def test_execute_rejects_unclosed_passed_native_terminal(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest = _campaign(tmp_path, 1)

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        value = _native_apply_result(child, digest, attempt)
        result = value["batch_result"]["result"]
        if mutation == "wrong_unit_identity":
            result["completed"][0]["contract"] = "AG9999"
        elif mutation == "remaining_targets":
            result["completed"][0]["remaining_target_count"] = 1
        elif mutation == "failed_readback":
            result["completed"][0]["readback"]["catalog_physical_mds"] = "failed"
        elif mutation == "wrong_readback_count":
            result["completed"][0]["readback"]["mds_target_count"] = 1
        elif mutation == "unexpected_failed":
            result["failed"] = {"status": "failed"}
        elif mutation == "unexpected_unattempted":
            result["unattempted"] = [json.loads(child.read_text())["units"][0]]
        (attempt / "native" / "batch-result.json").write_text(
            json.dumps(result), encoding="utf-8"
        )
        return value

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert result["status"] == "unknown"
    assert result["completed_batch_ids"] == []


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_attempt",
        "mismatched_counts",
        "inline_unknown",
        "journal_unknown",
        "cleared_journal",
        "missing_journal",
    ],
)
def test_execute_rejects_completed_unit_without_closed_native_journal(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest = _campaign(tmp_path, 1, with_source_requests=True)

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        value = _native_apply_result(child, digest, attempt)
        native_result = value["batch_result"]["result"]
        completed = native_result["completed"][0]
        unit_dir = attempt / "native" / "unit-001-ag-AG1000"
        if mutation == "missing_attempt":
            del completed["attempt"]
        elif mutation == "mismatched_counts":
            completed["attempt"].update(
                requests_started=2,
                responses_saved=1,
            )
        elif mutation == "inline_unknown":
            completed["attempt"].update(
                state="outcome_unknown",
                outcome_unknown=True,
            )
        elif mutation == "journal_unknown":
            (unit_dir / "journal.jsonl").write_text(
                json.dumps({"schema_version": 1, "sequence": 1, "state": "started"})
                + "\n",
                encoding="utf-8",
            )
            completed["attempt"] = read_attempt_outcome(unit_dir)
        elif mutation == "cleared_journal":
            (unit_dir / "journal.jsonl").write_text("", encoding="utf-8")
            completed["attempt"] = read_attempt_outcome(unit_dir)
        elif mutation == "missing_journal":
            (unit_dir / "journal.jsonl").unlink()
        (attempt / "native" / "batch-result.json").write_text(
            json.dumps(native_result), encoding="utf-8"
        )
        return value

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert result["status"] == "unknown"
    assert result["completed_batch_ids"] == []


def test_execute_accepts_completed_unit_with_closed_native_journal(
    tmp_path: Path,
) -> None:
    manifest = _campaign(tmp_path, 1, with_source_requests=True)

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=_native_apply_result,
    )

    assert result["status"] == "passed"
    assert result["completed_batch_ids"] == ["batch-001"]


def _campaign_isolation_policy() -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": "newow_weekly_recovery_continuation_policy_v1",
        "mode": "isolate_known_source_quality",
        "allowed_error_codes": ["RQDATA_ZERO_OHL_INVALID"],
    }
    return {
        **body,
        "policy_sha256": hashlib.sha256(
            json.dumps(
                body,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }


def _daily_campaign_isolation_policy() -> dict[str, object]:
    return campaign.native.source_isolation_policy(recovery_frequency="1d")


def _native_isolation_invoker(
    isolated_contracts: set[str],
    calls: list[str],
    *,
    stopping_contracts: set[str] | None = None,
    readback_drift_contracts: set[str] | None = None,
):
    stopping = stopping_contracts or set()
    readback_drift = readback_drift_contracts or set()

    def invoke(child_path: Path, digest: str, batch_attempt: Path):
        child = load_prepared_manifest(child_path, digest)

        class Manager:
            def __init__(self, observer, unit):
                self.observer = observer
                self.unit = unit

            def contract_warmup(self, request, *, before_apply=None):
                if request.apply:
                    calls.append(self.unit["contract"])
                    assert before_apply is not None
                    before_apply()
                    raw = self.unit["source_requests"][0]
                    source = ExchangeDailySourceRequest(
                        contract=raw["contract"],
                        start=date.fromisoformat(raw["start"]),
                        end=date.fromisoformat(raw["end"]),
                        expected_dates=tuple(
                            date.fromisoformat(value) for value in raw["expected_dates"]
                        ),
                    )
                    self.observer.before_request(source)
                    invalid = self.unit["contract"] in isolated_contracts
                    stopping_failure = self.unit["contract"] in stopping
                    self.observer.after_response(
                        source,
                        tuple(
                            {
                                "date": value,
                                "open": Decimal("0") if invalid else Decimal("100"),
                                "high": Decimal("0") if invalid else Decimal("101"),
                                "low": Decimal("0") if invalid else Decimal("99"),
                                "close": Decimal("100"),
                                "volume": Decimal("1"),
                                "total_turnover": Decimal("100"),
                                "open_interest": Decimal("10"),
                            }
                            for value in source.expected_dates
                        ),
                    )
                    if invalid or stopping_failure:
                        target = self.unit["targets"][0]
                        return SimpleNamespace(
                            status="failed",
                            applied=0,
                            blocked=0,
                            failed=1,
                            provider_requests=self.unit["target_count"],
                            failures=(
                                {
                                    "dataset": target["dataset"],
                                    "year": target["year"],
                                    "month": target["month"],
                                    "reason_code": (
                                        "RQDATA_ZERO_OHL_INVALID"
                                        if invalid
                                        else "PROVIDER_UNAVAILABLE"
                                    ),
                                },
                            ),
                        )
                    return SimpleNamespace(
                        status="passed",
                        applied=self.unit["target_count"],
                        blocked=0,
                        failed=0,
                        provider_requests=self.unit["target_count"],
                        failures=(),
                    )
                return SimpleNamespace(
                    plan=SimpleNamespace(
                        plan_sha256=(
                            "f" * 64
                            if self.unit["contract"] in readback_drift
                            else self.unit["plan_sha256"]
                        ),
                        target_windows=(
                            tuple(self.unit["targets"])
                            if self.unit["contract"] in isolated_contracts
                            else ()
                        ),
                    )
                )

        def open_unit(observer, unit):
            manager = Manager(observer, unit)
            return (
                manager,
                lambda: None,
                lambda: {
                    "catalog_physical_mds": "passed",
                    "mds_target_count": unit["target_count"],
                    "catalog_partitions": [],
                },
                lambda: None,
            )

        native_attempt = batch_attempt / "native"
        native_attempt.mkdir()
        native_result = execute_prepared_batch(
            manifest=child,
            attempt_dir=native_attempt,
            prepared_sha256=digest,
            current_code_commit=IDENTITY["code_commit"],
            current_execution_code_sha256=IDENTITY["execution_code_sha256"],
            current_config_sha256=IDENTITY["config_sha256"],
            current_canonical_root_sha256=IDENTITY["canonical_root_sha256"],
            open_unit=open_unit,
        )
        return {
            "return_code": 0 if native_result["status"] == "passed" else 1,
            "batch_result": {
                "schema_version": (
                    "newow_daily_recovery_result_v1"
                    if child["units"][0]["frequency"] == "1d"
                    else "newow_weekly_recovery_result_v1"
                ),
                "status": native_result["status"],
                "readonly": False,
                "attempt_dir": str(native_attempt),
                "result": native_result,
            },
        }

    return invoke


def _native_exception_invoker(mode: str, calls: list[str]):
    def invoke(child_path: Path, digest: str, batch_attempt: Path):
        child = load_prepared_manifest(child_path, digest)

        class Manager:
            def __init__(self, observer, unit):
                self.observer = observer
                self.unit = unit

            def contract_warmup(self, request, *, before_apply=None):
                if not request.apply:
                    return SimpleNamespace(
                        plan=SimpleNamespace(
                            plan_sha256=self.unit["plan_sha256"],
                            target_windows=(),
                        )
                    )
                calls.append(self.unit["contract"])
                assert before_apply is not None
                before_apply()
                raw = self.unit["source_requests"][0]
                source = ExchangeDailySourceRequest(
                    contract=raw["contract"],
                    start=date.fromisoformat(raw["start"]),
                    end=date.fromisoformat(raw["end"]),
                    expected_dates=tuple(
                        date.fromisoformat(value) for value in raw["expected_dates"]
                    ),
                )
                self.observer.before_request(source)
                if self.unit["contract"] == "AG1001" and mode != "readback_failed":
                    if mode != "provider_unknown":
                        self.observer.after_response(
                            source,
                            tuple({"date": value} for value in source.expected_dates),
                        )
                    raise RecoveryError(
                        "COMMIT_OUTCOME_UNKNOWN"
                        if mode == "commit_unknown"
                        else "PROVIDER_UNAVAILABLE"
                    )
                self.observer.after_response(
                    source,
                    tuple({"date": value} for value in source.expected_dates),
                )
                return SimpleNamespace(
                    status="passed",
                    applied=self.unit["target_count"],
                    blocked=0,
                    failed=0,
                    provider_requests=self.unit["target_count"],
                    failures=(),
                )

        def open_unit(observer, unit):
            def post_commit_readback():
                if mode == "readback_failed" and unit["contract"] == "AG1001":
                    raise RecoveryError("POST_COMMIT_MDS_INVALID")
                return {
                    "catalog_physical_mds": "passed",
                    "mds_target_count": unit["target_count"],
                    "catalog_partitions": [],
                }

            return (
                Manager(observer, unit),
                lambda: None,
                post_commit_readback,
                lambda: None,
            )

        native_attempt = batch_attempt / "native"
        native_attempt.mkdir()
        native_result = execute_prepared_batch(
            manifest=child,
            attempt_dir=native_attempt,
            prepared_sha256=digest,
            current_code_commit=IDENTITY["code_commit"],
            current_execution_code_sha256=IDENTITY["execution_code_sha256"],
            current_config_sha256=IDENTITY["config_sha256"],
            current_canonical_root_sha256=IDENTITY["canonical_root_sha256"],
            open_unit=open_unit,
        )
        if mode == "missing_unit_result":
            (native_attempt / "unit-002-ag-AG1001" / "unit-result.json").unlink()
        return {
            "return_code": 1,
            "batch_result": {
                "schema_version": "newow_weekly_recovery_result_v1",
                "status": native_result["status"],
                "readonly": False,
                "attempt_dir": str(native_attempt),
                "result": native_result,
            },
        }

    return invoke


@pytest.mark.parametrize(
    "mode", ["provider_unknown", "commit_unknown", "missing_unit_result"]
)
def test_campaign_preserves_prefix_but_counts_unproven_failed_unit_unknown(
    tmp_path: Path,
    mode: str,
) -> None:
    manifest = _campaign(tmp_path, 3, with_source_requests=True)
    calls: list[str] = []

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=_native_exception_invoker(mode, calls),
    )

    assert calls == ["AG1000", "AG1001"]
    assert result["status"] == "unknown"
    assert result["failed_batch"] is None
    assert result["unknown_batch"]["batch_id"] == "batch-001"
    assert result["summary"] == {
        "denominator_unit_count": 3,
        "success_unit_count": 1,
        "isolated_unit_count": 0,
        "partial_source_exception_unit_count": 0,
        "stopping_failure_unit_count": 0,
        "unattempted_unit_count": 1,
        "unknown_unit_count": 1,
    }


def test_campaign_counts_proven_post_commit_readback_failure_as_stopping(
    tmp_path: Path,
) -> None:
    manifest = _campaign(tmp_path, 3, with_source_requests=True)
    calls: list[str] = []

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=_native_exception_invoker("readback_failed", calls),
    )

    assert calls == ["AG1000", "AG1001"]
    assert result["status"] == "partial"
    assert result["unknown_batch"] is None
    assert result["failed_batch"]["batch_id"] == "batch-001"
    assert result["summary"] == {
        "denominator_unit_count": 3,
        "success_unit_count": 1,
        "isolated_unit_count": 0,
        "partial_source_exception_unit_count": 0,
        "stopping_failure_unit_count": 1,
        "unattempted_unit_count": 1,
        "unknown_unit_count": 0,
    }


@pytest.mark.parametrize(
    "mutation",
    ["request", "sequence", "bool_sequence", "bool_schema", "state", "payload"],
)
def test_campaign_treats_same_count_failed_journal_tampering_as_unknown(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest = _campaign(tmp_path, 3, with_source_requests=True)
    calls: list[str] = []
    invoke_native = _native_exception_invoker("readback_failed", calls)

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        value = invoke_native(child, digest, attempt)
        unit_dir = attempt / "native" / "unit-002-ag-AG1001"
        journal_path = unit_dir / "journal.jsonl"
        records = [json.loads(line) for line in journal_path.read_text().splitlines()]
        if mutation == "request":
            records[0]["request"]["contract"] = "AG9999"
        elif mutation == "sequence":
            records[0]["sequence"] = 9
            records[1]["sequence"] = 9
        elif mutation == "bool_sequence":
            records[0]["sequence"] = True
            records[1]["sequence"] = True
        elif mutation == "bool_schema":
            records[0]["schema_version"] = True
        elif mutation == "state":
            records.insert(
                -1,
                {"schema_version": 1, "sequence": 1, "state": "ignored"},
            )
        else:
            payload_path = unit_dir / "source-response-0001.json"
            payload = json.loads(payload_path.read_text())
            payload["request"]["contract"] = "AG9999"
            content = (
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            payload_path.write_text(content)
            records[1]["payload_sha256"] = hashlib.sha256(content.encode()).hexdigest()
        journal_path.write_text(
            "".join(json.dumps(record) + "\n" for record in records)
        )
        return value

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert calls == ["AG1000", "AG1001"]
    assert result["status"] == "unknown"
    assert result["failed_batch"] is None
    assert result["summary"] == {
        "denominator_unit_count": 3,
        "success_unit_count": 1,
        "isolated_unit_count": 0,
        "partial_source_exception_unit_count": 0,
        "stopping_failure_unit_count": 0,
        "unattempted_unit_count": 1,
        "unknown_unit_count": 1,
    }


def test_campaign_accounts_for_known_stopping_failure_as_distinct_partition(
    tmp_path: Path,
) -> None:
    policy = _campaign_isolation_policy()
    manifest = _campaign(
        tmp_path,
        3,
        with_source_requests=True,
        continuation_policy=policy,
    )
    calls: list[str] = []

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=_native_isolation_invoker(
            {"AG1000"},
            calls,
            stopping_contracts={"AG1001"},
        ),
    )

    assert calls == ["AG1000", "AG1001"]
    assert result["status"] == "partial"
    assert result["summary"] == {
        "denominator_unit_count": 3,
        "success_unit_count": 0,
        "isolated_unit_count": 1,
        "partial_source_exception_unit_count": 0,
        "stopping_failure_unit_count": 1,
        "unattempted_unit_count": 1,
        "unknown_unit_count": 0,
    }


def test_campaign_preserves_sanitized_isolation_failure_reason(
    tmp_path: Path,
) -> None:
    manifest = _campaign(
        tmp_path,
        2,
        with_source_requests=True,
        continuation_policy=_campaign_isolation_policy(),
    )
    calls: list[str] = []
    attempt = tmp_path / "attempt-001"

    result = execute_campaign(
        manifest,
        attempt_root=attempt,
        invoke_batch=_native_isolation_invoker(
            {"AG1000"},
            calls,
            readback_drift_contracts={"AG1000"},
        ),
    )

    assert calls == ["AG1000"]
    assert result["status"] == "failed"
    native_failure = result["failed_batch"]["native_result"]["result"]["failed"]
    assert (
        native_failure["isolation_failure_reason"] == "SOURCE_ISOLATION_READBACK_FAILED"
    )
    unit_result = json.loads(
        (
            attempt / "batch-001" / "native" / "unit-001-ag-AG1000" / "unit-result.json"
        ).read_text()
    )
    batch_result = json.loads(
        (attempt / "batch-001" / "native" / "batch-result.json").read_text()
    )
    campaign_result = json.loads((attempt / "campaign-result.json").read_text())
    assert unit_result["isolation_failure_reason"] == (
        "SOURCE_ISOLATION_READBACK_FAILED"
    )
    assert batch_result["failed"]["isolation_failure_reason"] == (
        "SOURCE_ISOLATION_READBACK_FAILED"
    )
    assert (
        campaign_result["failed_batch"]["native_result"]["result"]["failed"][
            "isolation_failure_reason"
        ]
        == "SOURCE_ISOLATION_READBACK_FAILED"
    )


def test_campaign_continues_across_batch_after_proven_source_isolation(
    tmp_path: Path,
) -> None:
    policy = _campaign_isolation_policy()
    manifest = _campaign(
        tmp_path,
        21,
        with_source_requests=True,
        continuation_policy=policy,
    )
    calls: list[str] = []

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=_native_isolation_invoker({"AG1019"}, calls),
    )

    assert calls == [f"AG{1000 + index}" for index in range(21)]
    assert result["status"] == "partial"
    assert result["completed_batch_ids"] == ["batch-001", "batch-002"]
    assert [item["contract"] for item in result["isolated_units"]] == ["AG1019"]
    assert result["summary"] == {
        "denominator_unit_count": 21,
        "success_unit_count": 20,
        "isolated_unit_count": 1,
        "partial_source_exception_unit_count": 0,
        "stopping_failure_unit_count": 0,
        "unattempted_unit_count": 0,
        "unknown_unit_count": 0,
    }
    assert result["anomaly_repair_requirements"] == {
        "RQDATA_ZERO_OHL_INVALID": [
            {
                "symbol": "ag",
                "contract": "AG1019",
                "frequency": "1w",
                "through": "2026-09-11",
                "plan_sha256": f"{19:064x}",
            }
        ]
    }


@pytest.mark.parametrize(
    ("isolated", "success_count"),
    [({"AG1000", "AG1002"}, 1), ({"AG1000", "AG1001", "AG1002"}, 0)],
)
def test_campaign_accounts_for_multiple_and_all_isolated_units(
    tmp_path: Path,
    isolated: set[str],
    success_count: int,
) -> None:
    policy = _campaign_isolation_policy()
    manifest = _campaign(
        tmp_path,
        3,
        with_source_requests=True,
        continuation_policy=policy,
    )
    calls: list[str] = []

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=_native_isolation_invoker(isolated, calls),
    )

    assert calls == ["AG1000", "AG1001", "AG1002"]
    assert result["status"] == "partial"
    assert result["summary"] == {
        "denominator_unit_count": 3,
        "success_unit_count": success_count,
        "isolated_unit_count": len(isolated),
        "partial_source_exception_unit_count": 0,
        "stopping_failure_unit_count": 0,
        "unattempted_unit_count": 0,
        "unknown_unit_count": 0,
    }


def test_campaign_rejects_symlinked_current_isolation_evidence(tmp_path: Path) -> None:
    manifest = _campaign(
        tmp_path,
        1,
        with_source_requests=True,
        continuation_policy=_campaign_isolation_policy(),
    )
    calls: list[str] = []
    invoke_native = _native_isolation_invoker({"AG1000"}, calls)
    escaped = tmp_path.parent / f"{tmp_path.name}-escaped-current-unit"
    unit_dir = tmp_path / "attempt-001" / "batch-001" / "native" / "unit-001-ag-AG1000"

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        value = invoke_native(child, digest, attempt)
        unit_dir.rename(escaped)
        unit_dir.symlink_to(escaped, target_is_directory=True)
        return value

    try:
        result = execute_campaign(
            manifest,
            attempt_root=tmp_path / "attempt-001",
            invoke_batch=invoke,
        )
        assert result["status"] == "unknown"
        assert result["isolated_units"] == []
        assert result["summary"] == {
            "denominator_unit_count": 1,
            "success_unit_count": 0,
            "isolated_unit_count": 0,
            "partial_source_exception_unit_count": 0,
            "stopping_failure_unit_count": 0,
            "unattempted_unit_count": 0,
            "unknown_unit_count": 1,
        }
    finally:
        unit_dir.unlink()
        escaped.rename(unit_dir)
    assert calls == ["AG1000"]


@pytest.mark.parametrize("field", ["mode", "policy_sha256"])
def test_campaign_rejects_tampered_continuation_policy(
    tmp_path: Path,
    field: str,
) -> None:
    policy = _campaign_isolation_policy()
    manifest = _campaign(
        tmp_path,
        1,
        with_source_requests=True,
        continuation_policy=policy,
    )
    manifest["continuation_policy"][field] = "tampered"

    with pytest.raises(RecoveryError, match="^CONTINUATION_POLICY_INVALID$"):
        validate_campaign_manifest(manifest, evidence_root=tmp_path)


def _source_only_isolation_evidence(
    root: Path, unit: dict[str, Any]
) -> tuple[Path, str, Path, str]:
    policy = _campaign_isolation_policy()
    prepared_result = _native_child(
        root,
        "source-only",
        (
            {
                "symbol": unit["symbol"],
                "contract": unit["contract"],
                "through": unit["through"],
                "frequency": unit["frequency"],
                "expected_plan_sha256": unit["plan_sha256"],
            },
        ),
        with_source_requests=True,
        continuation_policy=policy,
    )
    prepared_path = Path(prepared_result["prepared_file"])
    prepared_sha256 = prepared_result["prepared_sha256"]
    prepared = load_prepared_manifest(prepared_path, prepared_sha256)
    frozen_unit = prepared["units"][0]
    raw_request = frozen_unit["source_requests"][0]
    request = ExchangeDailySourceRequest(
        contract=raw_request["contract"],
        start=date.fromisoformat(raw_request["start"]),
        end=date.fromisoformat(raw_request["end"]),
        expected_dates=tuple(
            date.fromisoformat(value) for value in raw_request["expected_dates"]
        ),
    )
    request_sha256 = hashlib.sha256(
        json.dumps(
            raw_request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    attempt = root / "source-only-attempt"
    attempt.mkdir()
    journal = AttemptJournal(attempt, (request,))
    journal.before_request(request)
    journal.after_response(
        request,
        (
            {
                "date": request.expected_dates[0],
                "open": Decimal("0"),
                "high": Decimal("0"),
                "low": Decimal("0"),
                "close": Decimal("100"),
                "volume": Decimal("1"),
                "total_turnover": Decimal("100"),
                "open_interest": Decimal("10"),
            },
        ),
    )
    journal.mark_failed("RQDATA_ZERO_OHL_INVALID")
    _write_json_exclusive(
        attempt / "invocation-receipt.json",
        {
            "schema_version": "newow_weekly_source_only_invocation_v1",
            "prepared_path": prepared_path.name,
            "prepared_sha256": prepared_sha256,
            "request_sha256": request_sha256,
            "attempt_id": attempt.name,
            **IDENTITY,
            "runner_sha256": "a" * 64,
            "provider_request_limit": 1,
            "retries_allowed": 0,
            "canonical_writes_allowed": False,
            "database_writes_allowed": False,
            "manager_apply_allowed": False,
        },
    )
    _write_json_exclusive(
        attempt / "source-only-result.json",
        {
            "schema_version": "newow_weekly_source_only_result_v1",
            "status": "completed",
            "classification": "SOURCE_RESPONSE_SAVED_REVIEW_REQUIRED",
            "source_error_code": "RQDATA_ZERO_OHL_INVALID",
            "prepared_sha256": prepared_sha256,
            "request_sha256": request_sha256,
            "unit_identity": {
                key: frozen_unit[key]
                for key in ("symbol", "contract", "frequency", "through", "plan_sha256")
            },
            "attempt": read_attempt_outcome(attempt),
            "provider_request_limit": 1,
            "retries": 0,
            "canonical_writes": 0,
            "database_writes": 0,
            "manager_apply": False,
        },
    )
    return prepared_path, prepared_sha256, attempt, request_sha256


def test_source_only_isolation_excludes_only_replayed_fresh_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(campaign, "_source_runner_sha256_at_commit", lambda _: "a" * 64)
    policy = _campaign_isolation_policy()
    units = [_ordinary_unit(0), _ordinary_unit(1)]
    prepared_path, prepared_sha256, attempt, request_sha256 = (
        _source_only_isolation_evidence(tmp_path, units[0])
    )
    prepared_contracts: list[str] = []

    def prepare_child(batch, batch_id, root):
        prepared_contracts.extend(item["contract"] for item in batch)
        return _native_child(
            root,
            batch_id,
            batch,
            with_source_requests=True,
            continuation_policy=policy,
        )

    manifest = prepare_campaign(
        _report(units),
        report_sha256="e" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=prepare_child,
        name="fresh",
        continuation_policy=policy,
        source_only_prepared_path=prepared_path,
        expected_source_only_prepared_sha256=prepared_sha256,
        source_only_attempt_path=attempt,
        source_only_unit_index=0,
        source_only_request_index=0,
        expected_source_only_request_sha256=request_sha256,
    )

    assert prepared_contracts == ["AG1001"]
    assert manifest["scope"]["denominator_unit_count"] == 2
    assert manifest["scope"]["execution_unit_count"] == 1
    assert manifest["scope"]["source_only_known_isolation_count"] == 1
    binding = manifest["source_only_known_isolations"][0]
    assert binding["unit"]["contract"] == "AG1000"
    assert binding["classification"] == "RQDATA_ZERO_OHL_INVALID"
    assert binding["source_attempt_path"] == attempt.name

    calls: list[str] = []
    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "fresh-attempt",
        invoke_batch=_native_isolation_invoker(set(), calls),
    )

    assert calls == ["AG1001"]
    assert result["status"] == "partial"
    assert result["summary"] == {
        "denominator_unit_count": 2,
        "success_unit_count": 1,
        "isolated_unit_count": 1,
        "partial_source_exception_unit_count": 0,
        "stopping_failure_unit_count": 0,
        "unattempted_unit_count": 0,
        "unknown_unit_count": 0,
    }
    assert result["isolated_units"][0]["provenance"] == "source_only_known"

    (attempt / "source-response-0001.json").unlink()
    with pytest.raises(RecoveryError, match="^SOURCE_ONLY_ISOLATION_INVALID$"):
        execute_campaign(
            manifest,
            attempt_root=tmp_path / "fresh-after-evidence-drift",
            invoke_batch=lambda *_args: pytest.fail(
                "source-only evidence drift reached native execution"
            ),
        )
    assert not (tmp_path / "fresh-after-evidence-drift").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "response",
        "fresh_plan",
        "without_policy",
        "runner",
        "invocation_not_object",
        "result_not_object",
        "provider_limit_bool",
        "retries_float",
        "canonical_writes_bool",
        "database_writes_float",
        "attempt_started_bool",
        "attempt_saved_float",
        "attempt_outcome_unknown_int",
    ],
)
def test_source_only_isolation_rejects_unproven_or_drifted_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    expected_runner_sha256 = "b" * 64 if mutation == "runner" else "a" * 64
    monkeypatch.setattr(
        campaign,
        "_source_runner_sha256_at_commit",
        lambda _: expected_runner_sha256,
    )
    unit = _ordinary_unit(0)
    prepared_path, prepared_sha256, attempt, request_sha256 = (
        _source_only_isolation_evidence(tmp_path, unit)
    )
    if mutation == "response":
        (attempt / "source-response-0001.json").write_text("not-json")
    elif mutation == "fresh_plan":
        unit["plan_sha256"] = "9" * 64
    elif mutation == "invocation_not_object":
        (attempt / "invocation-receipt.json").write_text("[]")
    elif mutation == "result_not_object":
        (attempt / "source-only-result.json").write_text("[]")
    elif mutation in {
        "provider_limit_bool",
        "retries_float",
        "canonical_writes_bool",
        "database_writes_float",
        "attempt_started_bool",
        "attempt_saved_float",
        "attempt_outcome_unknown_int",
    }:
        result_path = attempt / "source-only-result.json"
        result = json.loads(result_path.read_text())
        if mutation == "provider_limit_bool":
            result["provider_request_limit"] = True
        elif mutation == "retries_float":
            result["retries"] = 0.0
        elif mutation == "canonical_writes_bool":
            result["canonical_writes"] = False
        elif mutation == "database_writes_float":
            result["database_writes"] = 0.0
        elif mutation == "attempt_started_bool":
            result["attempt"]["requests_started"] = True
        elif mutation == "attempt_saved_float":
            result["attempt"]["responses_saved"] = 1.0
        else:
            result["attempt"]["outcome_unknown"] = 0
        result_path.write_text(json.dumps(result))
    policy = None if mutation == "without_policy" else _campaign_isolation_policy()

    with pytest.raises(RecoveryError, match="^SOURCE_ONLY_ISOLATION_INVALID$"):
        prepare_campaign(
            _report([unit]),
            report_sha256="e" * 64,
            evidence_root=tmp_path,
            execution_identity=IDENTITY,
            invoke_batch=lambda *_args: pytest.fail(
                "invalid source-only isolation prepared a child"
            ),
            name="fresh",
            continuation_policy=policy,
            source_only_prepared_path=prepared_path,
            expected_source_only_prepared_sha256=prepared_sha256,
            source_only_attempt_path=attempt,
            source_only_unit_index=0,
            source_only_request_index=0,
            expected_source_only_request_sha256=request_sha256,
        )


def test_prior_known_source_isolation_excludes_only_proven_fresh_identity(
    tmp_path: Path,
) -> None:
    prior = _campaign(tmp_path, 2, with_source_requests=True, name="prior")
    prior_calls: list[str] = []
    prior_attempt = tmp_path / "prior-attempt"
    prior_result = execute_campaign(
        prior,
        attempt_root=prior_attempt,
        invoke_batch=_native_isolation_invoker({"AG1000"}, prior_calls),
    )
    assert prior_result["status"] == "failed"
    prior_path = tmp_path / "prior.prepare.json"
    prior_sha256 = hashlib.sha256(prior_path.read_bytes()).hexdigest()
    prepared_contracts: list[str] = []
    policy = _campaign_isolation_policy()

    def prepare_child(units, batch_id, root):
        prepared_contracts.extend(unit["contract"] for unit in units)
        return _native_child(
            root,
            batch_id,
            units,
            with_source_requests=True,
            continuation_policy=policy,
        )

    fresh = prepare_campaign(
        _report([_ordinary_unit(0), _ordinary_unit(1)]),
        report_sha256="e" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=prepare_child,
        name="fresh",
        continuation_policy=policy,
        prior_campaign_path=prior_path,
        expected_prior_campaign_sha256=prior_sha256,
        prior_attempt_path=prior_attempt,
    )

    assert prepared_contracts == ["AG1001"]
    assert fresh["scope"]["denominator_unit_count"] == 2
    assert fresh["scope"]["execution_unit_count"] == 1
    assert fresh["scope"]["prior_known_isolation_count"] == 1
    binding = fresh["prior_known_isolations"][0]
    assert binding["schema_version"] == "newow_weekly_recovery_prior_isolation_v1"
    assert binding["unit"] == {
        "symbol": "ag",
        "contract": "AG1000",
        "frequency": "1w",
        "through": "2026-09-11",
        "plan_sha256": f"{0:064x}",
    }
    assert binding["prior_campaign"]["sha256"] == prior_sha256
    assert len(binding["prior_campaign_result_sha256"]) == 64

    fresh_calls: list[str] = []
    result = execute_campaign(
        fresh,
        attempt_root=tmp_path / "fresh-attempt",
        invoke_batch=_native_isolation_invoker(set(), fresh_calls),
    )

    assert fresh_calls == ["AG1001"]
    assert result["status"] == "partial"
    assert result["summary"] == {
        "denominator_unit_count": 2,
        "success_unit_count": 1,
        "isolated_unit_count": 1,
        "partial_source_exception_unit_count": 0,
        "stopping_failure_unit_count": 0,
        "unattempted_unit_count": 0,
        "unknown_unit_count": 0,
    }
    assert result["isolated_units"][0]["provenance"] == "prior_known"

    prior_source = (
        prior_attempt
        / "batch-001"
        / "native"
        / "unit-001-ag-AG1000"
        / "source-response-0001.json"
    )
    prior_source.unlink()
    with pytest.raises(RecoveryError, match="^PRIOR_ISOLATION_INVALID$"):
        execute_campaign(
            fresh,
            attempt_root=tmp_path / "fresh-attempt-after-drift",
            invoke_batch=lambda *_args: pytest.fail(
                "prior drift reached native execution"
            ),
        )
    assert not (tmp_path / "fresh-attempt-after-drift").exists()


def test_daily_prior_isolation_reuses_only_same_profile_zero_commit_evidence(
    tmp_path: Path,
) -> None:
    policy = _daily_campaign_isolation_policy()
    prior = prepare_campaign(
        _daily_report([_daily_unit(0), _daily_unit(1)]),
        report_sha256="d" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda units, batch_id, root: _native_child(
            root,
            batch_id,
            units,
            with_source_requests=True,
            continuation_policy=policy,
        ),
        name="daily-prior",
        recovery_frequency="1d",
        continuation_policy=policy,
    )
    prior_attempt = tmp_path / "daily-prior-attempt"
    execute_campaign(
        prior,
        attempt_root=prior_attempt,
        invoke_batch=_native_isolation_invoker({"AG1000"}, []),
    )
    prior_path = tmp_path / "daily-prior.prepare.json"
    prepared_contracts: list[str] = []

    fresh = prepare_campaign(
        _daily_report([_daily_unit(0), _daily_unit(1)]),
        report_sha256="e" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda units, batch_id, root: (
            prepared_contracts.extend(unit["contract"] for unit in units)
            or _native_child(
                root,
                batch_id,
                units,
                with_source_requests=True,
                continuation_policy=policy,
            )
        ),
        name="daily-fresh",
        recovery_frequency="1d",
        continuation_policy=policy,
        prior_campaign_path=prior_path,
        expected_prior_campaign_sha256=hashlib.sha256(
            prior_path.read_bytes()
        ).hexdigest(),
        prior_attempt_path=prior_attempt,
    )

    assert prepared_contracts == ["AG1001"]
    assert fresh["prior_known_isolations"][0]["schema_version"] == (
        "newow_daily_recovery_prior_isolation_v1"
    )
    assert fresh["prior_known_isolations"][0]["unit"]["frequency"] == "1d"


def test_daily_prior_isolation_rejects_weekly_campaign_evidence(
    tmp_path: Path,
) -> None:
    weekly = _campaign(
        tmp_path,
        1,
        with_source_requests=True,
        continuation_policy=_campaign_isolation_policy(),
        name="weekly-prior",
    )
    weekly_attempt = tmp_path / "weekly-prior-attempt"
    execute_campaign(
        weekly,
        attempt_root=weekly_attempt,
        invoke_batch=_native_isolation_invoker({"AG1000"}, []),
    )
    weekly_path = tmp_path / "weekly-prior.prepare.json"

    with pytest.raises(RecoveryError, match="^PRIOR_ISOLATION_INVALID$"):
        prepare_campaign(
            _daily_report([_daily_unit()]),
            report_sha256="e" * 64,
            evidence_root=tmp_path,
            execution_identity=IDENTITY,
            invoke_batch=lambda *_args: pytest.fail(
                "cross-profile evidence prepared a child"
            ),
            name="daily-cross-profile",
            recovery_frequency="1d",
            continuation_policy=_daily_campaign_isolation_policy(),
            prior_campaign_path=weekly_path,
            expected_prior_campaign_sha256=hashlib.sha256(
                weekly_path.read_bytes()
            ).hexdigest(),
            prior_attempt_path=weekly_attempt,
        )


def test_prior_isolation_is_recovered_from_completed_batch_before_later_stop(
    tmp_path: Path,
) -> None:
    units = [_ordinary_unit(index) for index in range(21)]
    policy = _campaign_isolation_policy()
    prior = prepare_campaign(
        _report(units),
        report_sha256="d" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda batch, batch_id, root: _native_child(
            root,
            batch_id,
            batch,
            with_source_requests=True,
            continuation_policy=policy,
        ),
        name="prior-with-later-stop",
        continuation_policy=policy,
    )
    prior_attempt = tmp_path / "prior-with-later-stop-apply"
    result = execute_campaign(
        prior,
        attempt_root=prior_attempt,
        invoke_batch=_native_isolation_invoker(
            {"AG1000"}, [], stopping_contracts={"AG1020"}
        ),
    )
    assert result["completed_batch_ids"] == ["batch-001"]
    assert result["failed_batch"]["batch_id"] == "batch-002"
    assert [item["contract"] for item in result["isolated_units"]] == ["AG1000"]
    prior_path = tmp_path / "prior-with-later-stop.prepare.json"
    prepared_contracts: list[str] = []

    fresh = prepare_campaign(
        _report(units),
        report_sha256="e" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda batch, batch_id, root: (
            prepared_contracts.extend(item["contract"] for item in batch)
            or _native_child(
                root,
                batch_id,
                batch,
                with_source_requests=True,
                continuation_policy=policy,
            )
        ),
        name="fresh-after-later-stop",
        continuation_policy=policy,
        prior_campaign_path=prior_path,
        expected_prior_campaign_sha256=hashlib.sha256(
            prior_path.read_bytes()
        ).hexdigest(),
        prior_attempt_path=prior_attempt,
    )

    assert prepared_contracts == [item["contract"] for item in units[1:]]
    assert fresh["scope"]["prior_known_isolation_count"] == 1
    assert fresh["prior_known_isolations"][0]["unit"]["contract"] == "AG1000"


def test_prepare_with_only_prior_isolated_units_is_anomaly_bearing_not_completed(
    tmp_path: Path,
) -> None:
    prior = _campaign(tmp_path, 1, with_source_requests=True, name="prior")
    prior_attempt = tmp_path / "prior-attempt"
    execute_campaign(
        prior,
        attempt_root=prior_attempt,
        invoke_batch=_native_isolation_invoker({"AG1000"}, []),
    )
    prior_path = tmp_path / "prior.prepare.json"
    policy = _campaign_isolation_policy()

    fresh = prepare_campaign(
        _report([_ordinary_unit(0)]),
        report_sha256="e" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda *_args: pytest.fail("prior-only scope prepared a child"),
        name="fresh",
        continuation_policy=policy,
        prior_campaign_path=prior_path,
        expected_prior_campaign_sha256=hashlib.sha256(
            prior_path.read_bytes()
        ).hexdigest(),
        prior_attempt_path=prior_attempt,
    )

    assert fresh["status"] == "prepared"
    assert fresh["children"] == []
    assert fresh["scope"]["denominator_unit_count"] == 1
    assert fresh["scope"]["execution_unit_count"] == 0
    assert fresh["scope"]["prior_known_isolation_count"] == 1

    result = execute_campaign(
        fresh,
        attempt_root=tmp_path / "fresh-attempt",
        invoke_batch=lambda *_args: pytest.fail("prior-only scope invoked native"),
    )
    assert result["status"] == "partial"
    assert result["summary"] == {
        "denominator_unit_count": 1,
        "success_unit_count": 0,
        "isolated_unit_count": 1,
        "partial_source_exception_unit_count": 0,
        "stopping_failure_unit_count": 0,
        "unattempted_unit_count": 0,
        "unknown_unit_count": 0,
    }


@pytest.mark.parametrize(
    "mutation",
    ["missing_source", "corrupt_source", "mismatched_request", "fresh_plan"],
)
def test_prior_known_source_isolation_rejects_unproven_or_drifted_evidence(
    tmp_path: Path,
    mutation: str,
) -> None:
    prior = _campaign(tmp_path, 1, with_source_requests=True, name="prior")
    prior_attempt = tmp_path / "prior-attempt"
    execute_campaign(
        prior,
        attempt_root=prior_attempt,
        invoke_batch=_native_isolation_invoker({"AG1000"}, []),
    )
    prior_path = tmp_path / "prior.prepare.json"
    prior_sha256 = hashlib.sha256(prior_path.read_bytes()).hexdigest()
    unit_dir = prior_attempt / "batch-001" / "native" / "unit-001-ag-AG1000"
    if mutation == "missing_source":
        (unit_dir / "source-response-0001.json").unlink()
    elif mutation == "corrupt_source":
        (unit_dir / "source-response-0001.json").write_text("not-json")
    elif mutation == "mismatched_request":
        records = [
            json.loads(line)
            for line in (unit_dir / "journal.jsonl").read_text().splitlines()
        ]
        records[0]["request"]["contract"] = "AG9999"
        (unit_dir / "journal.jsonl").write_text(
            "".join(json.dumps(record) + "\n" for record in records)
        )
    fresh_unit = _ordinary_unit(0)
    if mutation == "fresh_plan":
        fresh_unit["plan_sha256"] = "9" * 64

    with pytest.raises(RecoveryError, match="^PRIOR_ISOLATION_INVALID$"):
        prepare_campaign(
            _report([fresh_unit]),
            report_sha256="e" * 64,
            evidence_root=tmp_path,
            execution_identity=IDENTITY,
            invoke_batch=lambda units, batch_id, root: _native_child(
                root,
                batch_id,
                units,
                with_source_requests=True,
                continuation_policy=_campaign_isolation_policy(),
            ),
            name="fresh",
            continuation_policy=_campaign_isolation_policy(),
            prior_campaign_path=prior_path,
            expected_prior_campaign_sha256=prior_sha256,
            prior_attempt_path=prior_attempt,
        )


def test_prior_known_isolation_rejects_symlinked_unit_directory_before_prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import newow_weekly_recovery_campaign as module

    prior = _campaign(tmp_path, 1, with_source_requests=True, name="prior")
    prior_attempt = tmp_path / "prior-attempt"
    execute_campaign(
        prior,
        attempt_root=prior_attempt,
        invoke_batch=_native_isolation_invoker({"AG1000"}, []),
    )
    prior_path = tmp_path / "prior.prepare.json"
    unit_dir = prior_attempt / "batch-001" / "native" / "unit-001-ag-AG1000"
    escaped = tmp_path.parent / f"{tmp_path.name}-escaped-unit"
    unit_dir.rename(escaped)
    unit_dir.symlink_to(escaped, target_is_directory=True)
    escaped_bytes = {
        path.name: path.read_bytes() for path in escaped.iterdir() if path.is_file()
    }
    outside_reads: list[Path] = []
    real_read_json = module.native._read_json_file

    def tracked_read_json(path: Path):
        if Path(path).parent in {unit_dir, escaped}:
            outside_reads.append(Path(path))
        return real_read_json(path)

    monkeypatch.setattr(module.native, "_read_json_file", tracked_read_json)

    try:
        with pytest.raises(RecoveryError, match="^PRIOR_ISOLATION_INVALID$"):
            prepare_campaign(
                _report([_ordinary_unit(0)]),
                report_sha256="e" * 64,
                evidence_root=tmp_path,
                execution_identity=IDENTITY,
                invoke_batch=lambda *_args: pytest.fail(
                    "symlinked prior evidence prepared a child"
                ),
                name="fresh",
                continuation_policy=_campaign_isolation_policy(),
                prior_campaign_path=prior_path,
                expected_prior_campaign_sha256=hashlib.sha256(
                    prior_path.read_bytes()
                ).hexdigest(),
                prior_attempt_path=prior_attempt,
            )
        assert not (tmp_path / "fresh.prepare.json").exists()
        assert outside_reads == []
        assert {
            path.name: path.read_bytes() for path in escaped.iterdir() if path.is_file()
        } == escaped_bytes
    finally:
        unit_dir.unlink()
        escaped.rename(unit_dir)


@pytest.mark.parametrize("contradiction", ["completed", "failure_partial", "applied"])
def test_execute_rejects_failed_status_that_native_would_classify_partial(
    tmp_path: Path,
    contradiction: str,
) -> None:
    manifest = _campaign(tmp_path, 2)

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        prepared = json.loads(child.read_text())
        completed = None
        if contradiction == "completed":
            unit = prepared["units"][0]
            completed = [
                {
                    **unit,
                    "status": "passed",
                    "remaining_target_count": 0,
                    "readback": {
                        "catalog_physical_mds": "passed",
                        "mds_target_count": unit["target_count"],
                    },
                }
            ]
        value = _native_apply_result(
            child,
            digest,
            attempt,
            status="failed",
            completed=completed,
        )
        native_result = value["batch_result"]["result"]
        if contradiction == "failure_partial":
            native_result["failed"]["status"] = "partial"
        elif contradiction == "applied":
            native_result["failed"]["result"] = {"applied": 1}
        (attempt / "native" / "batch-result.json").write_text(
            json.dumps(native_result), encoding="utf-8"
        )
        return value

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert result["status"] == "unknown"
    assert result["completed_batch_ids"] == []


def test_execute_accepts_zero_completed_partial_current_unit_write(
    tmp_path: Path,
) -> None:
    manifest = _campaign(tmp_path, 1)

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        value = _native_apply_result(
            child,
            digest,
            attempt,
            status="partial",
            completed=[],
        )
        native_result = value["batch_result"]["result"]
        native_result["failed"]["result"] = {"applied": 1}
        unit_result = (
            Path(value["batch_result"]["attempt_dir"])
            / "unit-001-ag-AG1000"
            / "unit-result.json"
        )
        unit_result.write_text(json.dumps(native_result["failed"]), encoding="utf-8")
        (attempt / "native" / "batch-result.json").write_text(
            json.dumps(native_result), encoding="utf-8"
        )
        return value

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert result["status"] == "partial"
    assert result["failed_batch"]["native_result"]["result"]["completed"] == []


def test_campaign_started_persistence_failure_invokes_no_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import newow_weekly_recovery_campaign as module

    manifest = _campaign(tmp_path, 1)
    invoked: list[object] = []
    real_write = module.native._write_json_exclusive

    def fail_started(path: Path, payload: object) -> str:
        if path.name == "campaign-started.json":
            raise OSError
        return real_write(path, payload)

    monkeypatch.setattr(module.native, "_write_json_exclusive", fail_started)

    with pytest.raises(RecoveryError, match="^CAMPAIGN_STARTED_UNAVAILABLE$"):
        execute_campaign(
            manifest,
            attempt_root=tmp_path / "attempt-001",
            invoke_batch=lambda *_args: invoked.append(True),
        )

    assert invoked == []


@pytest.mark.parametrize("outcome", ["raises", "unreadable"])
def test_execute_exception_or_unreadable_terminal_is_unknown(
    tmp_path: Path,
    outcome: str,
) -> None:
    manifest = _campaign(tmp_path, 21)
    invoked: list[str] = []

    def invoke(_child: Path, _digest: str, attempt: Path) -> Mapping[str, Any]:
        invoked.append(attempt.name)
        if outcome == "raises":
            raise RuntimeError("private provider detail")
        return {"return_code": 1, "batch_result": None}

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert result["status"] == "unknown"
    assert result["unknown_batch"]["batch_id"] == "batch-001"
    assert "private provider detail" not in json.dumps(result)
    assert result["unattempted_batch_ids"] == ["batch-002"]
    assert invoked == ["batch-001"]
    assert result["summary"] == {
        "denominator_unit_count": 21,
        "success_unit_count": 0,
        "isolated_unit_count": 0,
        "partial_source_exception_unit_count": 0,
        "stopping_failure_unit_count": 0,
        "unattempted_unit_count": 1,
        "unknown_unit_count": 20,
    }
    assert result["retries"] == 0


def test_final_summary_save_failure_cannot_report_completed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import newow_weekly_recovery_campaign as module

    manifest = _campaign(tmp_path, 1)
    real_write = module.native._write_json_exclusive

    def fail_result(path: Path, payload: object) -> str:
        if path.name == "campaign-result.json":
            raise OSError
        return real_write(path, payload)

    monkeypatch.setattr(module.native, "_write_json_exclusive", fail_result)

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=lambda child, digest, attempt: _native_apply_result(
            child, digest, attempt
        ),
    )

    assert result["status"] == "unknown"
    assert result["error_code"] == "CAMPAIGN_RESULT_UNAVAILABLE"


def test_execute_rejects_second_attempt_id_start(tmp_path: Path) -> None:
    manifest = _campaign(tmp_path, 1)
    first = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=lambda child, digest, attempt: _native_apply_result(
            child, digest, attempt
        ),
    )
    assert first["status"] == "passed"

    with pytest.raises(RecoveryError, match="^CAMPAIGN_ATTEMPT_EXISTS$"):
        execute_campaign(
            manifest,
            attempt_root=tmp_path / "attempt-001",
            invoke_batch=lambda *_args: pytest.fail(
                "duplicate attempt invoked a child"
            ),
        )


def test_execute_rejects_concurrent_campaign_under_same_fixed_root(
    tmp_path: Path,
) -> None:
    manifest = _campaign(tmp_path, 1)
    entered = threading.Event()
    release = threading.Event()
    thread_result: list[Mapping[str, Any]] = []

    def blocking(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        entered.set()
        assert release.wait(timeout=5)
        return _native_apply_result(child, digest, attempt)

    worker = threading.Thread(
        target=lambda: thread_result.append(
            execute_campaign(
                manifest,
                attempt_root=tmp_path / "attempt-001",
                invoke_batch=blocking,
            )
        )
    )
    worker.start()
    assert entered.wait(timeout=5)
    try:
        with pytest.raises(RecoveryError, match="^CAMPAIGN_ALREADY_RUNNING$"):
            execute_campaign(
                manifest,
                attempt_root=tmp_path / "attempt-002",
                invoke_batch=lambda *_args: pytest.fail("concurrent child invoked"),
            )
    finally:
        release.set()
        worker.join(timeout=5)

    assert thread_result[0]["status"] == "passed"


def test_execute_stops_if_bound_guard_path_is_replaced_between_batches(
    tmp_path: Path,
) -> None:
    manifest = _campaign(tmp_path, 21)
    guard_path = tmp_path / (
        ".campaign-writer-" + IDENTITY["canonical_root_sha256"] + ".lock"
    )
    if not guard_path.exists():
        guard_path.touch(mode=0o600)
    invoked: list[str] = []

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        invoked.append(attempt.name)
        value = _native_apply_result(child, digest, attempt)
        if attempt.name == "batch-001":
            guard_path.unlink()
            guard_path.touch(mode=0o600)
        return value

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert invoked == ["batch-001"]
    assert result["status"] == "partial"
    assert result["failed_batch"] == {
        "batch_id": "batch-002",
        "error_code": "CAMPAIGN_GUARD_CHANGED",
    }
    assert result["summary"] == {
        "denominator_unit_count": 21,
        "success_unit_count": 20,
        "isolated_unit_count": 0,
        "partial_source_exception_unit_count": 0,
        "stopping_failure_unit_count": 0,
        "unattempted_unit_count": 1,
        "unknown_unit_count": 0,
    }

    with pytest.raises(RecoveryError, match="^CAMPAIGN_GUARD_CHANGED$"):
        execute_campaign(
            manifest,
            attempt_root=tmp_path / "attempt-002",
            invoke_batch=lambda *_args: pytest.fail("replacement guard was accepted"),
        )


def test_execute_never_recreates_missing_bound_guard(tmp_path: Path) -> None:
    manifest = _campaign(tmp_path, 1)
    guard_path = tmp_path / manifest["writer_guard"]["path"]
    guard_path.unlink()

    with pytest.raises(RecoveryError, match="^CAMPAIGN_GUARD_CHANGED$"):
        execute_campaign(
            manifest,
            attempt_root=tmp_path / "attempt-001",
            invoke_batch=lambda *_args: pytest.fail("missing guard was recreated"),
        )

    assert not guard_path.exists()
    assert not (tmp_path / "attempt-001").exists()


def test_execute_validates_all_children_before_first_invocation(tmp_path: Path) -> None:
    manifest = _campaign(tmp_path, 21)
    (tmp_path / manifest["children"][1]["path"]).write_text("{}", encoding="utf-8")
    invoked: list[object] = []

    with pytest.raises(RecoveryError, match="^CAMPAIGN_CHILD_INVALID$"):
        execute_campaign(
            manifest,
            attempt_root=tmp_path / "attempt-001",
            invoke_batch=lambda *_args: invoked.append(True),
        )

    assert invoked == []
    assert not (tmp_path / "attempt-001").exists()


def test_execute_stops_on_child_hash_drift_between_batches(tmp_path: Path) -> None:
    manifest = _campaign(tmp_path, 21)
    invoked: list[str] = []

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        invoked.append(attempt.name)
        if attempt.name == "batch-001":
            second = tmp_path / manifest["children"][1]["path"]
            second.write_text("{}", encoding="utf-8")
        return _native_apply_result(child, digest, attempt)

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert invoked == ["batch-001"]
    assert result["status"] == "partial"
    assert result["failed_batch"] == {
        "batch_id": "batch-002",
        "error_code": "CAMPAIGN_CHILD_DRIFT",
    }
    assert result["summary"] == {
        "denominator_unit_count": 21,
        "success_unit_count": 20,
        "isolated_unit_count": 0,
        "partial_source_exception_unit_count": 0,
        "stopping_failure_unit_count": 0,
        "unattempted_unit_count": 1,
        "unknown_unit_count": 0,
    }


def test_execute_21_units_across_two_native_batches_preserves_all_readbacks(
    tmp_path: Path,
) -> None:
    manifest = _campaign(tmp_path, 21)
    observed: list[str] = []

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        prepared = json.loads(child.read_text())
        assert hashlib.sha256(child.read_bytes()).hexdigest() == digest
        completed = []
        for unit in prepared["units"]:
            assert {target["dataset"][3] for target in unit["targets"]} == {"1d", "1w"}
            observed.append(unit["contract"])
            completed.append(
                {
                    **unit,
                    "status": "passed",
                    "remaining_target_count": 0,
                    "readback": {
                        "catalog_physical_mds": "passed",
                        "mds_target_count": 2,
                    },
                }
            )
        return _native_apply_result(child, digest, attempt, completed=completed)

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert result["status"] == "passed"
    assert result["completed_batch_ids"] == ["batch-001", "batch-002"]
    assert observed == [f"AG{1000 + index}" for index in range(21)]
    assert all(
        unit["readback"]["catalog_physical_mds"] == "passed"
        for batch in result["completed_batches"]
        for unit in batch["native_result"]["result"]["completed"]
    )


def test_execute_21_units_crosses_two_real_native_batches_with_isolated_readback(
    tmp_path: Path,
) -> None:
    through = date(2025, 4, 4)
    trading_days = tuple(
        date(2025, 3, 31) + timedelta(days=index) for index in range(5)
    )
    daily_ends = tuple(
        datetime.combine(day, datetime.min.time(), tzinfo=UTC).replace(hour=7)
        for day in trading_days
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Exchange(code="DCE", name="DCE"))
    session.add(Instrument(symbol="ag", name="AG", exchange_code="DCE", is_active=True))
    for day in trading_days:
        session.add(TradingCalendar(exchange_code="DCE", trade_date=day, is_trading_day=True))
    session.add(TradingSession(
        exchange_code="DCE", instrument_symbol="ag", session_name="day",
        start_time=datetime.min.time().replace(hour=9),
        end_time=datetime.min.time().replace(hour=15),
        effective_from=trading_days[0], effective_to=trading_days[-1],
        is_active=True,
    ))
    contracts = [f"AG{1000 + index}" for index in range(21)]
    for contract in contracts:
        session.add(
            Contract(
                contract_code=contract,
                instrument_symbol="ag",
                exchange_code="DCE",
                listed_date=trading_days[0],
                expired_date=date(2025, 5, 1),
                provider="rqdata",
            )
        )
    session.commit()
    canonical_root = tmp_path / "canonical"
    canonical_root.mkdir()
    ends: dict[tuple[str, str, str, str], tuple[datetime, ...]] = {}
    for contract in contracts:
        ends[DatasetKey("contract", "ag", contract, "1d").as_tuple()] = daily_ends
        ends[DatasetKey("contract", "ag", contract, "1w").as_tuple()] = (
            daily_ends[-1],
        )
    coverage = FakeCoverage(ends)
    coverage.latest_day = through

    class Provider:
        def __init__(self) -> None:
            self.observer = None
            self.calls: list[tuple[DatasetKey, ...]] = []

        def exchange_daily_source_requests(
            self, requests: tuple[BarFetchRequest, ...]
        ) -> tuple[ExchangeDailySourceRequest, ...]:
            daily = tuple(
                request for request in requests if request.key.frequency.value == "1d"
            )
            dates = tuple(
                sorted({value.date() for item in daily for value in item.expected})
            )
            return (
                ExchangeDailySourceRequest(
                    contract=requests[0].key.series_or_contract,
                    start=dates[0],
                    end=dates[-1],
                    expected_dates=dates,
                ),
            )

        def fetch_many(
            self, requests: tuple[BarFetchRequest, ...]
        ) -> tuple[BarBatch, ...]:
            self.calls.append(tuple(request.key for request in requests))
            daily_dates = tuple(
                sorted(
                    {
                        value.date()
                        for request in requests
                        if request.key.frequency.value == "1d"
                        for value in request.expected
                    }
                )
            )
            source = ExchangeDailySourceRequest(
                contract=requests[0].key.series_or_contract,
                start=daily_dates[0],
                end=daily_dates[-1],
                expected_dates=daily_dates,
            )
            assert self.observer is not None
            self.observer.before_request(source)
            self.observer.after_response(
                source,
                tuple(
                    {
                        "date": day,
                        "open": Decimal("100"),
                        "high": Decimal("101"),
                        "low": Decimal("99"),
                        "close": Decimal("100"),
                        "volume": Decimal("1"),
                        "total_turnover": Decimal("100"),
                        "open_interest": Decimal("10"),
                        "settlement": Decimal("100"),
                        "prev_settlement": Decimal("100"),
                    }
                    for day in daily_dates
                ),
            )
            batches = []
            for request in requests:
                bars = []
                for bar_end in request.expected:
                    volume = (
                        Decimal("5")
                        if request.key.frequency.value == "1w"
                        else Decimal("1")
                    )
                    bars.append(
                        CanonicalBar(
                            bar_end,
                            bar_end.date(),
                            Decimal("100"),
                            Decimal("101"),
                            Decimal("99"),
                            Decimal("100"),
                            volume,
                            volume * Decimal("100"),
                            Decimal("10"),
                        )
                    )
                batches.append(BarBatch(tuple(bars)))
            return tuple(batches)

    provider = Provider()
    manager = HistoricalDataManager(
        catalog=MarketCatalog(session, canonical_root),
        store=CanonicalMonthlyStore(canonical_root),
        coverage=coverage,
        metadata=FakeMetadata(),
        provider=provider,
    )
    report_units = []
    for contract in contracts:
        plan = manager.contract_warmup(
            ContractWarmupRequest("ag", contract, through, frequency="1w")
        ).plan
        report_units.append(
            {
                "symbol": "ag",
                "contract": contract,
                "through": through.isoformat(),
                "requested_through": through.isoformat(),
                "frequency": "1w",
                "plan_sha256": plan.plan_sha256,
                "status": "PROPOSED",
                "expected_bar_count": plan.expected_bar_count,
                "consumers": [
                    {
                        "strategy": strategy,
                        "frequency": "1w",
                        "section": section,
                    }
                    for section in ("chart", "auxiliary", "reference")
                    for strategy in ("trend", "oscillation", "main_rise")
                ],
                "target_windows": [dict(item) for item in plan.target_windows],
            }
        )
    identity = {
        **IDENTITY,
        "canonical_root_sha256": hashlib.sha256(
            str(canonical_root.resolve()).encode()
        ).hexdigest(),
    }

    def prepare_native(
        units: tuple[dict[str, Any], ...], batch_id: str, root: Path
    ) -> Mapping[str, Any]:
        child = prepare_bounded_units(
            manager=manager,
            adapter=provider,
            requests=tuple(
                ContractWarmupRequest(
                    unit["symbol"],
                    unit["contract"],
                    date.fromisoformat(unit["through"]),
                    expected_plan_sha256=unit["expected_plan_sha256"],
                    frequency="1w",
                )
                for unit in units
            ),
            expected_data_root=canonical_root,
            code_commit=identity["code_commit"],
            execution_code_sha256=identity["execution_code_sha256"],
            config_sha256=identity["config_sha256"],
        )
        path, digest = write_prepared_manifest(root, batch_id, child)
        return {
            "status": "prepared",
            "readonly": True,
            "provider_requests": 0,
            "writes": 0,
            "prepared_file": str(path),
            "prepared_sha256": digest,
            "unit_count": len(units),
        }

    campaign = prepare_campaign(
        _report(report_units),
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=identity,
        invoke_batch=prepare_native,
    )

    def apply_native(child_path: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        child = load_prepared_manifest(child_path, digest)

        def open_unit(observer, unit):
            provider.observer = observer
            return (
                manager,
                lambda: None,
                lambda: _post_commit_readback(manager, unit),
                lambda: setattr(provider, "observer", None),
            )

        batch_result = execute_prepared_batch(
            manifest=child,
            attempt_dir=attempt,
            prepared_sha256=digest,
            current_code_commit=identity["code_commit"],
            current_execution_code_sha256=identity["execution_code_sha256"],
            current_config_sha256=identity["config_sha256"],
            current_canonical_root_sha256=identity["canonical_root_sha256"],
            open_unit=open_unit,
        )
        return {
            "return_code": 0 if batch_result["status"] == "passed" else 1,
            "batch_result": {
                "schema_version": "newow_weekly_recovery_result_v1",
                "status": batch_result["status"],
                "readonly": False,
                "attempt_dir": str(attempt),
                "result": batch_result,
            },
        }

    result = execute_campaign(
        campaign,
        attempt_root=tmp_path / "attempt-native",
        invoke_batch=apply_native,
    )

    assert result["status"] == "passed"
    assert result["completed_batch_ids"] == ["batch-001", "batch-002"]
    completed = [
        unit
        for batch in result["completed_batches"]
        for unit in batch["native_result"]["result"]["completed"]
    ]
    assert len(completed) == 21
    assert all(unit["remaining_target_count"] == 0 for unit in completed)
    assert all(
        unit["readback"]["catalog_physical_mds"] == "passed" for unit in completed
    )
    assert all(unit["readback"]["mds_target_count"] == 3 for unit in completed)
    assert len(provider.calls) == 21
    session.close()
    engine.dispose()


def test_cli_apply_calls_native_main_in_same_process_for_each_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import newow_weekly_recovery_campaign as module

    _campaign(tmp_path, 21)
    campaign_path = tmp_path / "campaign.prepare.json"
    campaign_sha256 = hashlib.sha256(campaign_path.read_bytes()).hexdigest()
    project_env = tmp_path / "project.env"
    project_env.write_text("fixture", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(module, "_current_execution_identity", lambda _path: IDENTITY)

    def native_main(argv: list[str], *, stdout: io.StringIO) -> int:
        calls.append(argv)
        batch_attempt = Path(argv[argv.index("--output-root") + 1])
        child = Path(argv[argv.index("--prepared") + 1])
        digest = argv[argv.index("--expected-prepared-sha256") + 1]
        payload = _native_apply_result(child, digest, batch_attempt)["batch_result"]
        stdout.write(json.dumps(payload))
        return 0

    monkeypatch.setattr(module.native, "main", native_main)
    output = io.StringIO()

    code = main(
        [
            "apply",
            "--project-env",
            str(project_env),
            "--campaign",
            str(campaign_path),
            "--expected-campaign-sha256",
            campaign_sha256,
            "--output-root",
            str(tmp_path),
            "--attempt-id",
            "attempt-001",
            "--apply",
        ],
        stdout=output,
    )

    payload = json.loads(output.getvalue())
    assert code == 0
    assert payload["status"] == "passed"
    assert [call[0] for call in calls] == ["apply", "apply"]
    assert all("--apply" in call for call in calls)
    assert all("--expected-prepared-sha256" in call for call in calls)


def test_cli_apply_rejects_current_code_or_config_drift_before_native_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import newow_weekly_recovery_campaign as module

    _campaign(tmp_path, 1)
    campaign_path = tmp_path / "campaign.prepare.json"
    campaign_sha256 = hashlib.sha256(campaign_path.read_bytes()).hexdigest()
    project_env = tmp_path / "project.env"
    project_env.write_text("fixture", encoding="utf-8")
    calls: list[object] = []
    monkeypatch.setattr(
        module,
        "_current_execution_identity",
        lambda _path: {**IDENTITY, "config_sha256": "0" * 64},
    )
    monkeypatch.setattr(
        module.native, "main", lambda *_args, **_kwargs: calls.append(True)
    )
    output = io.StringIO()

    code = main(
        [
            "apply",
            "--project-env",
            str(project_env),
            "--campaign",
            str(campaign_path),
            "--expected-campaign-sha256",
            campaign_sha256,
            "--output-root",
            str(tmp_path),
            "--attempt-id",
            "attempt-001",
            "--apply",
        ],
        stdout=output,
    )

    assert code == 1
    assert json.loads(output.getvalue())["error_code"] == "EXECUTION_IDENTITY_CHANGED"
    assert calls == []


def test_prepare_campaign_accepts_hash_bound_partial_source_exception_input() -> None:
    assert (
        "partial_source_exception_attempt_path"
        in inspect.signature(prepare_campaign).parameters
    )


def _weekly_partial_binding(unit: Mapping[str, Any]) -> dict[str, Any]:
    committed = {
        **unit["target_windows"][0],
        "year": 2026,
        "month": 8,
    }
    return {
        "schema_version": "newow_partial_source_exception_v1",
        "symbol": unit["symbol"],
        "contract": unit["contract"],
        "frequency": "1w",
        "through": unit["through"],
        "failed_plan_sha256": "a" * 64,
        "fresh_replan_sha256": unit["plan_sha256"],
        "failed_attempt_id": "prior-apply-001",
        "failed_attempt_path": "prior-apply-001",
        "failed_execution_commit": "b" * 40,
        "failed_execution_code_sha256": "c" * 64,
        "committed_targets": [committed],
        "remaining_targets": unit["target_windows"],
        "source_request_identity": {"start": "2026-08-01"},
        "source_response_sha256": "d" * 64,
        "journal_sha256": "e" * 64,
        "error_code": "RQDATA_ZERO_OHL_INVALID",
        "requests_started": 1,
        "responses_saved": 1,
        "retries": 0,
        "outcome_unknown": False,
        "catalog_readback": {"status": "passed", "partitions": []},
        "parquet_readback": {"status": "passed", "files": []},
        "mds_readback": {"status": "passed", "windows": []},
        "classification": PARTIAL_EXCEPTION_CLASSIFICATION,
        "evidence_sha256": "f" * 64,
        "binding_sha256": "1" * 64,
        "batch_id": "batch-001",
        "unit_dir": "batch-001/native/unit-001-ag-AG1000",
    }


def test_weekly_campaign_excludes_verified_partial_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failed = _ordinary_unit(0)
    sibling = _ordinary_unit(1)
    binding = _weekly_partial_binding(failed)
    monkeypatch.setattr(
        campaign,
        "_derive_partial_source_exceptions",
        lambda *_args, **_kwargs: [binding],
    )
    prepared_contracts: list[str] = []

    manifest = prepare_campaign(
        _report([failed, sibling]),
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda units, batch_id, root: (
            prepared_contracts.extend(item["contract"] for item in units)
            or _native_child(root, batch_id, units)
        ),
        name="weekly-partial-exception",
        partial_source_exception_attempt_path=tmp_path / "prior-apply-001",
        observe_partial_committed=lambda *_args: {},
    )

    assert prepared_contracts == [sibling["contract"]]
    assert manifest["scope"]["denominator_unit_count"] == 2
    assert manifest["scope"]["execution_unit_count"] == 1
    assert manifest["scope"]["prior_partial_source_exception_count"] == 1

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "fresh-apply-001",
        invoke_batch=lambda child, digest, attempt: _native_apply_result(
            child, digest, attempt
        ),
        observe_partial_committed=lambda *_args: {},
    )

    assert result["summary"] == {
        "denominator_unit_count": 2,
        "success_unit_count": 1,
        "isolated_unit_count": 0,
        "partial_source_exception_unit_count": 1,
        "stopping_failure_unit_count": 0,
        "unattempted_unit_count": 0,
        "unknown_unit_count": 0,
    }
    assert (
        result["partial_source_exception_units"][0]["contract"] == (failed["contract"])
    )


def test_weekly_campaign_stops_before_attempt_on_partial_exception_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failed = _ordinary_unit(0)
    binding = _weekly_partial_binding(failed)
    live_drift = False

    def derive(*_args, **kwargs):
        if live_drift and kwargs.get("observe_committed") is not None:
            raise RecoveryError(PARTIAL_EXCEPTION_INVALID)
        return [binding]

    monkeypatch.setattr(campaign, "_derive_partial_source_exceptions", derive)
    manifest = prepare_campaign(
        _report([failed]),
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda *_args: pytest.fail(
            "partial exception must not prepare an executable child"
        ),
        name="weekly-partial-drift",
        partial_source_exception_attempt_path=tmp_path / "prior-apply-001",
        observe_partial_committed=lambda *_args: {},
    )
    live_drift = True
    attempt = tmp_path / "fresh-apply-001"

    with pytest.raises(RecoveryError, match=f"^{PARTIAL_EXCEPTION_INVALID}$"):
        execute_campaign(
            manifest,
            attempt_root=attempt,
            invoke_batch=lambda *_args: pytest.fail("drift reached native apply"),
            observe_partial_committed=lambda *_args: {},
        )
    assert not attempt.exists()


def test_campaign_revalidates_each_partial_exception_from_its_own_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _weekly_partial_binding(_ordinary_unit(0))
    second = deepcopy(_weekly_partial_binding(_ordinary_unit(1)))
    second["failed_attempt_id"] = "prior-apply-002"
    second["failed_attempt_path"] = "prior-apply-002"
    attempts: list[str] = []

    def derive(*_args, **kwargs):
        attempt = Path(kwargs["attempt_path"]).name
        attempts.append(attempt)
        return [first if attempt == "prior-apply-001" else second]

    monkeypatch.setattr(campaign, "_derive_partial_source_exceptions", derive)

    campaign._revalidate_partial_source_exceptions(
        {"prior_partial_source_exceptions": [first, second]},
        evidence_root=tmp_path,
        current_identity=IDENTITY,
        observe_committed=lambda *_args: {},
    )

    assert attempts == ["prior-apply-001", "prior-apply-002"]
