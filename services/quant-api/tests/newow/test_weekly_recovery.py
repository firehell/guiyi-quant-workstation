from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.domain import DatasetKey
from app.market_data.errors import InfrastructureError
from app.market_data.historical_data_manager import BarFetchRequest
from app.market_data.historical_data_manager import (
    ContractWarmupPlan,
    ContractWarmupRequest,
    _Target,
)
from app.market_data.rqdata_adapter import (
    ExchangeDailySourceRequest,
    RQDataMarketAdapter,
)
from app.models import Contract, Exchange, Instrument, TradingCalendar
from scripts.newow_weekly_recovery import (
    AttemptJournal,
    RecoveryError,
    _current_execution_code_sha256,
    _post_commit_readback,
    _require_clean_execution_checkout,
    _require_execution_identity,
    create_attempt_directory,
    execute_prepared_batch,
    load_prepared_manifest,
    load_private_execution_settings,
    main,
    parser,
    prepare_bounded_units,
    read_attempt_outcome,
    run_bounded_units,
    write_prepared_manifest,
)


class ExchangeDailyClient:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, date, date]] = []

    def exchange_daily(self, contract: str, start: date, end: date):
        self.calls.append((contract, start, end))
        return pd.DataFrame(self.rows)


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Exchange(code="DCE", name="DCE"))
    session.add(Instrument(symbol="ec", name="EC", exchange_code="DCE", is_active=True))
    session.add(
        Contract(
            contract_code="EC2607",
            instrument_symbol="ec",
            exchange_code="DCE",
            listed_date=date(2026, 2, 1),
            expired_date=date(2026, 8, 1),
            provider="rqdata",
        )
    )
    for offset in range(5):
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=date(2026, 3, 30) + timedelta(days=offset),
                is_trading_day=True,
                provider="rqdata",
            )
        )
    session.commit()
    return session


def _source_request() -> ExchangeDailySourceRequest:
    dates = tuple(date(2026, 3, 30) + timedelta(days=offset) for offset in range(5))
    return ExchangeDailySourceRequest(
        contract="EC2607",
        start=dates[0],
        end=dates[-1],
        expected_dates=dates,
    )


def _rows(*, invalid: bool = False) -> list[dict]:
    result = []
    for offset, trading_day in enumerate(_source_request().expected_dates):
        result.append(
            {
                "date": trading_day,
                "open": Decimal("0") if invalid and offset == 0 else Decimal("100.10"),
                "high": Decimal("101.20"),
                "low": Decimal("99.30"),
                "close": Decimal("100.40"),
                "volume": Decimal("10"),
                "total_turnover": Decimal("1004.00"),
                "open_interest": Decimal("20"),
                "settlement": Decimal("100.50"),
                "prev_settlement": Decimal("100.00"),
                "unexpected_secret": "must-not-persist",
            }
        )
    return result


def test_attempt_persists_started_and_raw_response_before_native_validation(
    tmp_path,
) -> None:
    session = _session()
    client = ExchangeDailyClient(_rows(invalid=True))
    attempt = create_attempt_directory(tmp_path, "ec2607-001")
    journal = AttemptJournal(attempt, (_source_request(),))
    adapter = RQDataMarketAdapter(
        session=session,
        client=client,
        source_observer=journal,
    )
    weekly_end = datetime(2026, 4, 3, 1, 5, tzinfo=UTC)

    with pytest.raises(InfrastructureError, match="^RQDATA_ZERO_OHL_INVALID$"):
        adapter.fetch_many(
            (
                BarFetchRequest(
                    DatasetKey("contract", "ec", "EC2607", "1w"),
                    (weekly_end,),
                ),
            )
        )

    records = [
        json.loads(line)
        for line in (attempt / "journal.jsonl").read_text().splitlines()
    ]
    assert [record["state"] for record in records] == ["started", "response_saved"]
    receipt = records[1]
    payload_path = attempt / receipt["payload_file"]
    assert payload_path.exists()
    assert len(receipt["payload_sha256"]) == 64
    payload = json.loads(payload_path.read_text())
    assert payload["rows"][0]["open"] == "0"
    assert payload["rows"][0]["date"] == "2026-03-30"
    assert "unexpected_secret" not in payload["rows"][0]
    assert read_attempt_outcome(attempt) == {
        "state": "response_saved",
        "outcome_unknown": False,
        "retry_allowed": False,
        "requests_started": 1,
        "responses_saved": 1,
    }
    session.close()


def test_started_persistence_failure_prevents_provider_call(
    tmp_path, monkeypatch
) -> None:
    session = _session()
    client = ExchangeDailyClient(_rows())
    attempt = create_attempt_directory(tmp_path, "ec2607-001")
    daily_request = ExchangeDailySourceRequest(
        contract="EC2607",
        start=date(2026, 3, 30),
        end=date(2026, 3, 30),
        expected_dates=(date(2026, 3, 30),),
    )
    journal = AttemptJournal(attempt, (daily_request,))
    monkeypatch.setattr(
        journal, "_append", lambda _record: (_ for _ in ()).throw(OSError())
    )
    adapter = RQDataMarketAdapter(
        session=session,
        client=client,
        source_observer=journal,
    )
    daily_end = datetime(2026, 3, 30, 1, 5, tzinfo=UTC)

    with pytest.raises(RecoveryError, match="^SOURCE_JOURNAL_UNAVAILABLE$"):
        adapter.fetch_many(
            (
                BarFetchRequest(
                    DatasetKey("contract", "ec", "EC2607", "1d"),
                    (daily_end,),
                ),
            )
        )

    assert client.calls == []
    session.close()


def test_response_save_failure_is_unknown_and_cannot_retry(
    tmp_path, monkeypatch
) -> None:
    attempt = create_attempt_directory(tmp_path, "ec2607-001")
    journal = AttemptJournal(attempt, (_source_request(),))
    journal.before_request(_source_request())
    monkeypatch.setattr(
        journal,
        "_write_payload",
        lambda *_args: (_ for _ in ()).throw(OSError()),
    )

    with pytest.raises(RecoveryError, match="^SOURCE_RESPONSE_PERSIST_FAILED$"):
        journal.after_response(_source_request(), tuple(_rows()))

    assert read_attempt_outcome(attempt) == {
        "state": "outcome_unknown",
        "outcome_unknown": True,
        "retry_allowed": False,
        "requests_started": 1,
        "responses_saved": 0,
    }


def test_provider_timeout_leaves_started_as_unknown(tmp_path) -> None:
    session = _session()

    class TimeoutClient(ExchangeDailyClient):
        def exchange_daily(self, contract: str, start: date, end: date):
            self.calls.append((contract, start, end))
            raise TimeoutError

    client = TimeoutClient([])
    attempt = create_attempt_directory(tmp_path, "ec2607-001")
    journal = AttemptJournal(attempt, (_source_request(),))
    adapter = RQDataMarketAdapter(
        session=session,
        client=client,
        source_observer=journal,
    )
    daily_ends = tuple(
        datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        for day in _source_request().expected_dates
    )

    with pytest.raises(TimeoutError):
        adapter.fetch_many(
            (
                BarFetchRequest(
                    DatasetKey("contract", "ec", "EC2607", "1d"),
                    daily_ends,
                ),
            )
        )

    assert read_attempt_outcome(attempt)["outcome_unknown"] is True
    assert read_attempt_outcome(attempt)["retry_allowed"] is False
    session.close()


def test_attempt_rejects_path_escape_symlink_and_duplicate(tmp_path) -> None:
    attempt = create_attempt_directory(tmp_path, "ec2607-001")
    assert attempt == tmp_path / "ec2607-001"
    with pytest.raises(RecoveryError, match="^ATTEMPT_EXISTS$"):
        create_attempt_directory(tmp_path, "ec2607-001")
    with pytest.raises(RecoveryError, match="^ATTEMPT_PATH_INVALID$"):
        create_attempt_directory(tmp_path, "../escape")
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(RecoveryError, match="^OUTPUT_ROOT_UNSAFE$"):
        create_attempt_directory(link, "ec2607-002")


def test_response_identity_failure_is_saved_then_stops(tmp_path) -> None:
    attempt = create_attempt_directory(tmp_path, "ec2607-001")
    journal = AttemptJournal(attempt, (_source_request(),))
    journal.before_request(_source_request())
    rows = _rows()
    rows[-1]["date"] = date(2026, 4, 6)

    with pytest.raises(RecoveryError, match="^SOURCE_RESPONSE_IDENTITY_INVALID$"):
        journal.after_response(_source_request(), tuple(rows))

    records = [
        json.loads(line)
        for line in (attempt / "journal.jsonl").read_text().splitlines()
    ]
    assert [record["state"] for record in records] == [
        "started",
        "response_saved",
        "failed",
    ]
    assert records[-1]["error_code"] == "SOURCE_RESPONSE_IDENTITY_INVALID"
    assert read_attempt_outcome(attempt)["retry_allowed"] is False


def test_journal_marks_known_downstream_failure_after_response_saved(tmp_path) -> None:
    attempt = create_attempt_directory(tmp_path, "ec2607-001")
    journal = AttemptJournal(attempt, (_source_request(),))
    journal.before_request(_source_request())
    journal.after_response(_source_request(), tuple(_rows()))

    journal.mark_failed("RQDATA_ZERO_OHL_INVALID")

    assert read_attempt_outcome(attempt) == {
        "state": "failed",
        "outcome_unknown": False,
        "retry_allowed": False,
        "requests_started": 1,
        "responses_saved": 1,
    }


def test_bounded_units_stops_after_first_failure_without_retry() -> None:
    calls: list[str] = []

    def execute(unit: str) -> dict[str, str]:
        calls.append(unit)
        return {"status": "passed" if unit == "first" else "failed"}

    result = run_bounded_units(("first", "second", "third"), execute)

    assert calls == ["first", "second"]
    assert result == {
        "status": "partial",
        "completed": ("first",),
        "failed": "second",
        "unattempted": ("third",),
        "retries": 0,
    }


def test_bounded_units_rejects_more_than_twenty_before_execution() -> None:
    calls: list[str] = []

    with pytest.raises(RecoveryError, match="^BATCH_SCOPE_INVALID$"):
        run_bounded_units(tuple(str(index) for index in range(21)), calls.append)

    assert calls == []


def _prepare_fixture(tmp_path):
    daily = DatasetKey("contract", "ec", "EC2607", "1d")
    weekly = DatasetKey("contract", "ec", "EC2607", "1w")
    daily_ends = tuple(
        datetime(2026, 3, 30, 1, 5, tzinfo=UTC) + timedelta(days=offset)
        for offset in range(5)
    )
    targets = (
        _Target(daily, 2026, 3, daily_ends, daily_ends, ()),
        _Target(weekly, 2026, 4, (daily_ends[-1],), (daily_ends[-1],), ()),
    )
    plan = ContractWarmupPlan(
        symbol="ec",
        contract="EC2607",
        provider="rqdata",
        listed_date=date(2026, 2, 1),
        expired_date=date(2026, 8, 1),
        requested_through=date(2026, 6, 30),
        effective_through=date(2026, 6, 30),
        target_windows=(),
        direct_target_count=2,
        derived_target_count=0,
        expected_bar_count=6,
        provider_request_count=2,
        plan_sha256="a" * 64,
        frequency="1w",
        dependency_frequencies=("1d",),
        frequencies=("1d", "1w"),
    )

    class Manager:
        catalog = SimpleNamespace(canonical_root=tmp_path / "canonical")
        provider_calls = 0
        writes = 0

        def _contract_warmup_plan(self, request):
            assert request == ContractWarmupRequest(
                "ec", "EC2607", date(2026, 6, 30), frequency="1w"
            )
            return plan, targets

    class Adapter:
        client_initialized = False
        calls = []

        @property
        def client(self):
            self.client_initialized = True
            raise AssertionError("prepare must not initialize provider")

        def exchange_daily_source_requests(self, requests):
            self.calls.append(requests)
            assert tuple(request.key.frequency.value for request in requests) == (
                "1d",
                "1w",
            )
            return (_source_request(),)

    Manager.catalog.canonical_root.mkdir()
    return Manager(), Adapter(), plan


def test_prepare_uses_native_targets_without_initializing_provider(tmp_path) -> None:
    manager, adapter, plan = _prepare_fixture(tmp_path)

    manifest = prepare_bounded_units(
        manager=manager,
        adapter=adapter,
        requests=(
            ContractWarmupRequest("ec", "EC2607", date(2026, 6, 30), frequency="1w"),
        ),
        expected_data_root=manager.catalog.canonical_root,
        code_commit="b" * 40,
        execution_code_sha256="d" * 64,
        config_sha256="c" * 64,
    )

    assert manifest["schema_version"] == "newow_weekly_recovery_prepare_v1"
    assert manifest["code_commit"] == "b" * 40
    assert manifest["execution_code_sha256"] == "d" * 64
    assert manifest["config_sha256"] == "c" * 64
    assert "canonical_root" not in manifest
    assert len(manifest["canonical_root_sha256"]) == 64
    assert manifest["units"][0]["plan_sha256"] == plan.plan_sha256
    assert manifest["units"][0]["source_requests"][0] == {
        "method": "futures.get_exchange_daily",
        "contract": "EC2607",
        "start": "2026-03-30",
        "end": "2026-04-03",
        "expected_dates": [
            "2026-03-30",
            "2026-03-31",
            "2026-04-01",
            "2026-04-02",
            "2026-04-03",
        ],
    }
    assert adapter.client_initialized is False
    assert manager.provider_calls == manager.writes == 0


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("root", "CANONICAL_ROOT_MISMATCH"),
        ("hash", "CONTRACT_WARMUP_PLAN_CHANGED"),
        ("frequency", "RECOVERY_SCOPE_INVALID"),
    ],
)
def test_prepare_rejects_root_hash_and_nonweekly_scope_before_provider(
    tmp_path,
    change,
    code,
) -> None:
    manager, adapter, _plan = _prepare_fixture(tmp_path)
    request = ContractWarmupRequest(
        "ec",
        "EC2607",
        date(2026, 6, 30),
        expected_plan_sha256="d" * 64 if change == "hash" else None,
        frequency="60m" if change == "frequency" else "1w",
    )

    with pytest.raises(RecoveryError, match=f"^{code}$"):
        prepare_bounded_units(
            manager=manager,
            adapter=adapter,
            requests=(request,),
            expected_data_root=(
                tmp_path / "other"
                if change == "root"
                else manager.catalog.canonical_root
            ),
            code_commit="b" * 40,
            execution_code_sha256="e" * 64,
            config_sha256="c" * 64,
        )

    assert adapter.client_initialized is False
    assert adapter.calls == []
    assert manager.provider_calls == manager.writes == 0


def test_execute_prepared_batch_rechecks_hash_reads_back_and_stops(tmp_path) -> None:
    source = _source_request()
    units = [
        {
            "symbol": "ec",
            "contract": "EC2607",
            "through": "2026-06-30",
            "frequency": "1w",
            "plan_sha256": "a" * 64,
            "source_requests": [
                {
                    "method": "futures.get_exchange_daily",
                    "contract": source.contract,
                    "start": source.start.isoformat(),
                    "end": source.end.isoformat(),
                    "expected_dates": [
                        day.isoformat() for day in source.expected_dates
                    ],
                }
            ],
        },
        {
            "symbol": "si",
            "contract": "SI2401",
            "through": "2023-12-01",
            "frequency": "1w",
            "plan_sha256": "d" * 64,
            "source_requests": [],
        },
    ]
    manifest = {
        "schema_version": "newow_weekly_recovery_prepare_v1",
        "code_commit": "b" * 40,
        "execution_code_sha256": "d" * 64,
        "config_sha256": "c" * 64,
        "canonical_root_sha256": "e" * 64,
        "units": units,
    }
    events: list[str] = []

    class Manager:
        def __init__(self, observer, unit):
            self.observer = observer
            self.unit = unit

        def contract_warmup(self, request, *, before_apply=None):
            if request.apply:
                assert request.expected_plan_sha256 == self.unit["plan_sha256"]
                events.append(f"locked:{self.unit['contract']}")
                assert before_apply is not None
                before_apply()
                if self.unit["contract"] == "EC2607":
                    self.observer.before_request(source)
                    self.observer.after_response(source, tuple(_rows()))
                    return SimpleNamespace(
                        status="passed",
                        applied=2,
                        blocked=0,
                        failed=0,
                        provider_requests=2,
                        failures=(),
                    )
                return SimpleNamespace(
                    status="failed",
                    applied=0,
                    blocked=0,
                    failed=1,
                    provider_requests=1,
                    failures=(),
                )
            events.append(f"replan:{self.unit['contract']}")
            return SimpleNamespace(
                plan=SimpleNamespace(
                    plan_sha256="f" * 64,
                    target_windows=()
                    if self.unit["contract"] == "EC2607"
                    else ({"missing": 1},),
                )
            )

    def open_unit(observer, unit):
        manager = Manager(observer, unit)
        return (
            manager,
            lambda: events.append(f"invalidate:{unit['contract']}"),
            lambda: (
                events.append(f"readback:{unit['contract']}")
                or {
                    "catalog_partitions": [],
                    "mds_target_count": 0,
                }
            ),
            lambda: None,
        )

    attempt = create_attempt_directory(tmp_path, "batch-001")
    result = execute_prepared_batch(
        manifest=manifest,
        attempt_dir=attempt,
        prepared_sha256="9" * 64,
        current_code_commit="b" * 40,
        current_execution_code_sha256="d" * 64,
        current_config_sha256="c" * 64,
        current_canonical_root_sha256="e" * 64,
        open_unit=open_unit,
    )

    assert result["status"] == "partial"
    assert [unit["contract"] for unit in result["completed"]] == ["EC2607"]
    assert result["failed"]["contract"] == "SI2401"
    assert result["unattempted"] == []
    assert result["retries"] == 0
    assert events == [
        "locked:EC2607",
        "invalidate:EC2607",
        "replan:EC2607",
        "readback:EC2607",
        "locked:SI2401",
        "invalidate:SI2401",
    ]
    assert (attempt / "unit-001-ec-EC2607" / "source-response-0001.json").exists()
    assert read_attempt_outcome(attempt / "unit-002-si-SI2401")["state"] == "failed"
    assert json.loads((attempt / "invocation-receipt.json").read_text()) == {
        "canonical_root_sha256": "e" * 64,
        "code_commit": "b" * 40,
        "config_sha256": "c" * 64,
        "execution_code_sha256": "d" * 64,
        "prepared_sha256": "9" * 64,
        "schema_version": "newow_weekly_recovery_invocation_v1",
        "unit_count": 2,
    }


def test_execute_prepared_batch_rejects_execution_code_drift_before_opening_unit(
    tmp_path,
) -> None:
    manifest = {
        "schema_version": "newow_weekly_recovery_prepare_v1",
        "code_commit": "b" * 40,
        "execution_code_sha256": "d" * 64,
        "config_sha256": "c" * 64,
        "canonical_root_sha256": "e" * 64,
        "units": [
            {
                "symbol": "ec",
                "contract": "EC2607",
                "through": "2026-06-30",
                "frequency": "1w",
                "plan_sha256": "a" * 64,
                "source_requests": [],
            }
        ],
    }
    opened: list[bool] = []

    with pytest.raises(RecoveryError, match="^EXECUTION_IDENTITY_CHANGED$"):
        execute_prepared_batch(
            manifest=manifest,
            attempt_dir=tmp_path,
            prepared_sha256="9" * 64,
            current_code_commit="b" * 40,
            current_execution_code_sha256="f" * 64,
            current_config_sha256="c" * 64,
            current_canonical_root_sha256="e" * 64,
            open_unit=lambda *_args: opened.append(True),
        )

    assert opened == []


def test_require_execution_identity_closes_reopened_environment_on_drift() -> None:
    closed: list[bool] = []
    environment = SimpleNamespace(
        identity={
            "config_sha256": "f" * 64,
            "canonical_root_sha256": "e" * 64,
        },
        close=lambda: closed.append(True),
    )

    with pytest.raises(RecoveryError, match="^EXECUTION_IDENTITY_CHANGED$"):
        _require_execution_identity(
            environment,
            {
                "config_sha256": "c" * 64,
                "canonical_root_sha256": "e" * 64,
            },
        )

    assert closed == [True]


def test_execute_prepared_batch_marks_known_failure_in_journal(tmp_path) -> None:
    source = _source_request()
    unit = {
        "symbol": "ec",
        "contract": "EC2607",
        "through": "2026-06-30",
        "frequency": "1w",
        "plan_sha256": "a" * 64,
        "source_requests": [
            {
                "method": "futures.get_exchange_daily",
                "contract": source.contract,
                "start": source.start.isoformat(),
                "end": source.end.isoformat(),
                "expected_dates": [day.isoformat() for day in source.expected_dates],
            }
        ],
    }
    manifest = {
        "schema_version": "newow_weekly_recovery_prepare_v1",
        "code_commit": "b" * 40,
        "execution_code_sha256": "d" * 64,
        "config_sha256": "c" * 64,
        "canonical_root_sha256": "e" * 64,
        "units": [unit],
    }

    class Manager:
        def contract_warmup(self, _request, *, before_apply=None):
            assert before_apply is not None
            before_apply()
            observer.before_request(source)
            observer.after_response(source, tuple(_rows()))
            raise InfrastructureError("RQDATA_ZERO_OHL_INVALID")

    def open_unit(value, _unit):
        nonlocal observer
        observer = value
        return Manager(), lambda: None, lambda: {}, lambda: None

    observer = None
    attempt = create_attempt_directory(tmp_path, "batch-001")

    result = execute_prepared_batch(
        manifest=manifest,
        attempt_dir=attempt,
        prepared_sha256="9" * 64,
        current_code_commit="b" * 40,
        current_execution_code_sha256="d" * 64,
        current_config_sha256="c" * 64,
        current_canonical_root_sha256="e" * 64,
        open_unit=open_unit,
    )

    assert result["status"] == "failed"
    unit_attempt = attempt / "unit-001-ec-EC2607"
    assert read_attempt_outcome(unit_attempt)["state"] == "failed"


def _source_isolation_policy() -> dict[str, object]:
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


def _isolation_unit(contract: str) -> dict[str, object]:
    source = _source_request()
    source = ExchangeDailySourceRequest(
        contract=contract,
        start=source.start,
        end=source.end,
        expected_dates=source.expected_dates,
    )
    return {
        "symbol": contract[:2].lower(),
        "contract": contract,
        "through": "2026-06-30",
        "frequency": "1w",
        "plan_sha256": hashlib.sha256(contract.encode()).hexdigest(),
        "target_count": 1,
        "expected_bar_count": 5,
        "targets": [
            {
                "dataset": ["contract", contract[:2].lower(), contract, "1w"],
                "year": 2026,
                "month": 4,
                "expected_start": "2026-04-03T01:05:00+00:00",
                "expected_end": "2026-04-03T01:05:00+00:00",
                "expected_bar_count": 5,
            }
        ],
        "source_requests": [
            {
                "method": "futures.get_exchange_daily",
                "contract": contract,
                "start": source.start.isoformat(),
                "end": source.end.isoformat(),
                "expected_dates": [day.isoformat() for day in source.expected_dates],
            }
        ],
    }


def test_source_quality_policy_isolates_one_unit_and_runs_its_next_sibling(
    tmp_path,
) -> None:
    units = [_isolation_unit("EC2607"), _isolation_unit("SI2401")]
    manifest = {
        "schema_version": "newow_weekly_recovery_prepare_v1",
        "code_commit": "b" * 40,
        "execution_code_sha256": "d" * 64,
        "config_sha256": "c" * 64,
        "canonical_root_sha256": "e" * 64,
        "continuation_policy": _source_isolation_policy(),
        "units": units,
    }
    events: list[str] = []

    class Manager:
        def __init__(self, observer, unit):
            self.observer = observer
            self.unit = unit

        def contract_warmup(self, request, *, before_apply=None):
            if request.apply:
                events.append(f"apply:{self.unit['contract']}")
                assert before_apply is not None
                before_apply()
                source = ExchangeDailySourceRequest(
                    contract=self.unit["contract"],
                    start=date(2026, 3, 30),
                    end=date(2026, 4, 3),
                    expected_dates=tuple(
                        date(2026, 3, 30) + timedelta(days=offset)
                        for offset in range(5)
                    ),
                )
                self.observer.before_request(source)
                rows = _rows(invalid=self.unit["contract"] == "EC2607")
                if self.unit["contract"] == "EC2607":
                    rows = [
                        {
                            **row,
                            "date": datetime.combine(row["date"], datetime.min.time()),
                        }
                        for row in rows
                    ]
                self.observer.after_response(source, tuple(rows))
                if self.unit["contract"] == "EC2607":
                    return SimpleNamespace(
                        status="failed",
                        applied=0,
                        blocked=0,
                        failed=1,
                        provider_requests=1,
                        failures=(
                            {
                                "dataset": ["contract", "ec", "EC2607", "1w"],
                                "year": 2026,
                                "month": 4,
                                "reason_code": "RQDATA_ZERO_OHL_INVALID",
                            },
                        ),
                    )
                return SimpleNamespace(
                    status="passed",
                    applied=1,
                    blocked=0,
                    failed=0,
                    provider_requests=1,
                    failures=(),
                )
            events.append(f"readback:{self.unit['contract']}")
            return SimpleNamespace(
                plan=SimpleNamespace(
                    plan_sha256=self.unit["plan_sha256"],
                    target_windows=(
                        tuple(self.unit["targets"])
                        if self.unit["contract"] == "EC2607"
                        else ()
                    ),
                )
            )

    def open_unit(observer, unit):
        manager = Manager(observer, unit)
        return (
            manager,
            lambda: events.append(f"invalidate:{unit['contract']}"),
            lambda: {
                "catalog_physical_mds": "passed",
                "mds_target_count": unit["target_count"],
                "catalog_partitions": [],
            },
            lambda: events.append(f"cleanup:{unit['contract']}"),
        )

    attempt = create_attempt_directory(tmp_path, "batch-001")
    result = execute_prepared_batch(
        manifest=manifest,
        attempt_dir=attempt,
        prepared_sha256="9" * 64,
        current_code_commit="b" * 40,
        current_execution_code_sha256="d" * 64,
        current_config_sha256="c" * 64,
        current_canonical_root_sha256="e" * 64,
        open_unit=open_unit,
    )

    assert result["status"] == "partial"
    assert [item["contract"] for item in result["isolated"]] == ["EC2607"]
    assert [item["contract"] for item in result["completed"]] == ["SI2401"]
    assert result["failed"] is None
    assert result["unattempted"] == []
    assert events == [
        "apply:EC2607",
        "invalidate:EC2607",
        "readback:EC2607",
        "cleanup:EC2607",
        "apply:SI2401",
        "invalidate:SI2401",
        "readback:SI2401",
        "cleanup:SI2401",
    ]
    isolated = result["isolated"][0]
    assert isolated["classification"] == "RQDATA_ZERO_OHL_INVALID"
    assert isolated["result"]["applied"] == 0
    assert isolated["readback"]["remaining_target_count"] == 1
    assert isolated["source_evidence"]["requests_started"] == 1
    assert isolated["source_evidence"]["responses_saved"] == 1


def test_source_isolation_rejects_symlinked_unit_directory_before_next_unit(
    tmp_path,
) -> None:
    units = [_isolation_unit("EC2607"), _isolation_unit("SI2401")]
    manifest = {
        "schema_version": "newow_weekly_recovery_prepare_v1",
        "code_commit": "b" * 40,
        "execution_code_sha256": "d" * 64,
        "config_sha256": "c" * 64,
        "canonical_root_sha256": "e" * 64,
        "continuation_policy": _source_isolation_policy(),
        "units": units,
    }
    calls: list[str] = []
    escaped = tmp_path.parent / f"{tmp_path.name}-escaped-unit"

    class Manager:
        def __init__(self, observer, unit):
            self.observer = observer
            self.unit = unit

        def contract_warmup(self, request, *, before_apply=None):
            if not request.apply:
                return SimpleNamespace(
                    plan=SimpleNamespace(
                        plan_sha256=self.unit["plan_sha256"],
                        target_windows=tuple(self.unit["targets"]),
                    )
                )
            calls.append(self.unit["contract"])
            assert before_apply is not None
            before_apply()
            source = _source_request()
            self.observer.before_request(source)
            self.observer.after_response(source, tuple(_rows(invalid=True)))
            self.observer.attempt_dir.rename(escaped)
            self.observer.attempt_dir.symlink_to(escaped, target_is_directory=True)
            return SimpleNamespace(
                status="failed",
                applied=0,
                blocked=0,
                failed=1,
                provider_requests=1,
                failures=(
                    {
                        "dataset": ["contract", "ec", "EC2607", "1w"],
                        "year": 2026,
                        "month": 4,
                        "reason_code": "RQDATA_ZERO_OHL_INVALID",
                    },
                ),
            )

    def open_unit(observer, unit):
        return Manager(observer, unit), lambda: None, lambda: {}, lambda: None

    attempt = create_attempt_directory(tmp_path, "batch-001")
    unit_dir = attempt / "unit-001-ec-EC2607"
    try:
        with pytest.raises(RecoveryError, match="^SOURCE_EVIDENCE_PATH_INVALID$"):
            execute_prepared_batch(
                manifest=manifest,
                attempt_dir=attempt,
                prepared_sha256="9" * 64,
                current_code_commit="b" * 40,
                current_execution_code_sha256="d" * 64,
                current_config_sha256="c" * 64,
                current_canonical_root_sha256="e" * 64,
                open_unit=open_unit,
            )
        assert calls == ["EC2607"]
        assert not (attempt / "unit-002-si-SI2401").exists()
    finally:
        unit_dir.unlink()
        escaped.rename(unit_dir)


def test_source_quality_failure_still_stops_without_explicit_policy(tmp_path) -> None:
    unit = _isolation_unit("EC2607")
    manifest = {
        "schema_version": "newow_weekly_recovery_prepare_v1",
        "code_commit": "b" * 40,
        "execution_code_sha256": "d" * 64,
        "config_sha256": "c" * 64,
        "canonical_root_sha256": "e" * 64,
        "units": [unit],
    }

    class Manager:
        def contract_warmup(self, request, *, before_apply=None):
            assert request.apply is True
            assert before_apply is not None
            before_apply()
            return SimpleNamespace(
                status="failed",
                applied=0,
                blocked=0,
                failed=1,
                provider_requests=0,
                failures=(
                    {
                        "dataset": ["contract", "ec", "EC2607", "1w"],
                        "year": 2026,
                        "month": 4,
                        "reason_code": "RQDATA_ZERO_OHL_INVALID",
                    },
                ),
            )

    attempt = create_attempt_directory(tmp_path, "batch-001")
    result = execute_prepared_batch(
        manifest=manifest,
        attempt_dir=attempt,
        prepared_sha256="9" * 64,
        current_code_commit="b" * 40,
        current_execution_code_sha256="d" * 64,
        current_config_sha256="c" * 64,
        current_canonical_root_sha256="e" * 64,
        open_unit=lambda *_args: (
            Manager(),
            lambda: None,
            lambda: pytest.fail("strict failure cannot read back as isolated"),
            lambda: None,
        ),
    )

    assert result["status"] == "failed"
    assert "isolated" not in result


@pytest.mark.parametrize(
    "mutation",
    [
        "applied_nonzero",
        "applied_bool",
        "unknown_response",
        "wrong_error_code",
        "readback_drift",
    ],
)
def test_source_quality_policy_refuses_unproven_isolation(
    tmp_path,
    mutation,
) -> None:
    unit = _isolation_unit("EC2607")
    manifest = {
        "schema_version": "newow_weekly_recovery_prepare_v1",
        "code_commit": "b" * 40,
        "execution_code_sha256": "d" * 64,
        "config_sha256": "c" * 64,
        "canonical_root_sha256": "e" * 64,
        "continuation_policy": _source_isolation_policy(),
        "units": [unit],
    }

    class Manager:
        def contract_warmup(self, request, *, before_apply=None):
            if request.apply:
                assert before_apply is not None
                before_apply()
                if mutation != "unknown_response":
                    source = ExchangeDailySourceRequest(
                        contract="EC2607",
                        start=date(2026, 3, 30),
                        end=date(2026, 4, 3),
                        expected_dates=tuple(
                            date(2026, 3, 30) + timedelta(days=offset)
                            for offset in range(5)
                        ),
                    )
                    observer.before_request(source)
                    observer.after_response(source, tuple(_rows(invalid=True)))
                else:
                    observer.before_request(_source_request())
                return SimpleNamespace(
                    status="failed",
                    applied=(
                        1
                        if mutation == "applied_nonzero"
                        else False
                        if mutation == "applied_bool"
                        else 0
                    ),
                    blocked=0,
                    failed=1,
                    provider_requests=1,
                    failures=(
                        {
                            "dataset": ["contract", "ec", "EC2607", "1w"],
                            "year": 2026,
                            "month": 4,
                            "reason_code": (
                                "PROVIDER_QUOTA_EXHAUSTED"
                                if mutation == "wrong_error_code"
                                else "RQDATA_ZERO_OHL_INVALID"
                            ),
                        },
                    ),
                )
            return SimpleNamespace(
                plan=SimpleNamespace(
                    plan_sha256=(
                        "f" * 64
                        if mutation == "readback_drift"
                        else unit["plan_sha256"]
                    ),
                    target_windows=tuple(unit["targets"]),
                )
            )

    def open_unit(value, _unit):
        nonlocal observer
        observer = value
        return Manager(), lambda: None, lambda: {}, lambda: None

    observer = None
    attempt = create_attempt_directory(tmp_path, "batch-001")
    result = execute_prepared_batch(
        manifest=manifest,
        attempt_dir=attempt,
        prepared_sha256="9" * 64,
        current_code_commit="b" * 40,
        current_execution_code_sha256="d" * 64,
        current_config_sha256="c" * 64,
        current_canonical_root_sha256="e" * 64,
        open_unit=open_unit,
    )

    assert result["status"] == (
        "partial" if mutation == "applied_nonzero" else "failed"
    )
    assert result["failed"]["contract"] == "EC2607"
    assert result["unattempted"] == []
    assert "isolated" not in result


def test_execute_prepared_batch_preserves_first_unit_partial_status(tmp_path) -> None:
    unit = {
        "symbol": "ec",
        "contract": "EC2607",
        "through": "2026-06-30",
        "frequency": "1w",
        "plan_sha256": "a" * 64,
        "source_requests": [],
    }
    manifest = {
        "schema_version": "newow_weekly_recovery_prepare_v1",
        "code_commit": "b" * 40,
        "execution_code_sha256": "d" * 64,
        "config_sha256": "c" * 64,
        "canonical_root_sha256": "e" * 64,
        "units": [unit],
    }

    class Manager:
        def contract_warmup(self, _request, *, before_apply=None):
            assert before_apply is not None
            before_apply()
            return SimpleNamespace(
                status="partial",
                applied=1,
                blocked=0,
                failed=1,
                provider_requests=1,
                failures=({"reason_code": "PROVIDER_QUOTA_EXHAUSTED"},),
            )

    attempt = create_attempt_directory(tmp_path, "batch-001")
    result = execute_prepared_batch(
        manifest=manifest,
        attempt_dir=attempt,
        prepared_sha256="9" * 64,
        current_code_commit="b" * 40,
        current_execution_code_sha256="d" * 64,
        current_config_sha256="c" * 64,
        current_canonical_root_sha256="e" * 64,
        open_unit=lambda *_args: (Manager(), lambda: None, lambda: {}, lambda: None),
    )

    assert result["status"] == "partial"
    assert result["failed"]["result"]["applied"] == 1


def test_execution_code_identity_reads_real_repository_dependencies() -> None:
    first = _current_execution_code_sha256()
    second = _current_execution_code_sha256()

    assert len(first) == 64
    assert first == second


def test_clean_execution_checkout_requires_exact_clean_commit(monkeypatch) -> None:
    from scripts import newow_weekly_recovery as module

    monkeypatch.setattr(module, "_current_code_commit", lambda: "b" * 40)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=" M domain.py\n"),
    )
    with pytest.raises(RecoveryError, match="^EXECUTION_CHECKOUT_DIRTY$"):
        _require_clean_execution_checkout("b" * 40)

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=""),
    )
    with pytest.raises(RecoveryError, match="^EXECUTION_IDENTITY_CHANGED$"):
        _require_clean_execution_checkout("a" * 40)

    _require_clean_execution_checkout("b" * 40)


def test_clean_checkout_allows_bound_recovery_artifacts_in_ignored_output(
    tmp_path,
) -> None:
    import subprocess

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".gitignore").write_text(
        "/outputs/newow-weekly-recovery-attempts/\n",
        encoding="utf-8",
    )
    (checkout / "tracked.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
    subprocess.run(["git", "add", ".gitignore", "tracked.py"], cwd=checkout, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=checkout,
        check=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    attempt = checkout / "outputs" / "newow-weekly-recovery-attempts" / "batch-001"
    attempt.mkdir(parents=True)
    (attempt / "invocation-receipt.json").write_text("{}\n", encoding="utf-8")

    _require_clean_execution_checkout(commit, project_root=checkout)

    (checkout / "unbound.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(RecoveryError, match="^EXECUTION_CHECKOUT_DIRTY$"):
        _require_clean_execution_checkout(commit, project_root=checkout)


def test_post_commit_readback_records_catalog_file_hash_and_mds(
    tmp_path,
    monkeypatch,
) -> None:
    from app.market_data import market_data_service as service_module

    root = tmp_path / "canonical"
    path = root / "kind=contract" / "part.parquet"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"immutable-canonical-partition")
    first = datetime(2026, 3, 30, 1, 5, tzinfo=UTC)
    last = datetime(2026, 3, 31, 1, 5, tzinfo=UTC)
    bars = (SimpleNamespace(bar_end=first), SimpleNamespace(bar_end=last))
    partition = SimpleNamespace(
        year=2026,
        month=3,
        file_path=path,
        row_count=2,
    )

    class Catalog:
        canonical_root = root

        def all_partitions(self, _key):
            return (partition,)

    class Store:
        def read_catalog_partition(self, value):
            assert value is partition
            return bars

    class Service:
        def __init__(self, catalog, store):
            assert isinstance(catalog, Catalog)
            assert isinstance(store, Store)

        def query(self, request):
            assert request.start == first - timedelta(microseconds=1)
            assert request.end == last
            return SimpleNamespace(bars=bars)

    monkeypatch.setattr(service_module, "MarketDataService", Service)
    unit = {
        "symbol": "ec",
        "contract": "EC2607",
        "targets": [
            {
                "dataset": ["contract", "ec", "EC2607", "1d"],
                "year": 2026,
                "month": 3,
                "expected_start": first.isoformat(),
                "expected_end": last.isoformat(),
                "expected_bar_count": 2,
            }
        ],
    }

    result = _post_commit_readback(
        SimpleNamespace(catalog=Catalog(), store=Store()),
        unit,
    )

    assert result["catalog_physical_mds"] == "passed"
    assert result["mds_target_count"] == 1
    assert (
        result["catalog_partitions"][0]["file_sha256"]
        == hashlib.sha256(path.read_bytes()).hexdigest()
    )


def test_prepared_manifest_is_exclusive_hash_locked_and_no_overwrite(tmp_path) -> None:
    manifest = {
        "schema_version": "newow_weekly_recovery_prepare_v1",
        "code_commit": "b" * 40,
        "execution_code_sha256": "d" * 64,
        "config_sha256": "c" * 64,
        "canonical_root_sha256": "e" * 64,
        "unit_count": 1,
        "units": [{"symbol": "ec"}],
    }

    path, digest = write_prepared_manifest(tmp_path, "ec2607", manifest)

    assert path == tmp_path / "ec2607.prepare.json"
    assert load_prepared_manifest(path, digest) == manifest
    with pytest.raises(RecoveryError, match="^PREPARED_MANIFEST_EXISTS$"):
        write_prepared_manifest(tmp_path, "ec2607", manifest)
    with pytest.raises(RecoveryError, match="^PREPARED_MANIFEST_HASH_MISMATCH$"):
        load_prepared_manifest(path, "f" * 64)


def test_prepared_manifest_reader_rejects_symlink(tmp_path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}")
    link = tmp_path / "prepared.json"
    link.symlink_to(target)

    with pytest.raises(RecoveryError, match="^PREPARED_MANIFEST_INVALID$"):
        load_prepared_manifest(link, "0" * 64)


def test_cli_exposes_separate_prepare_apply_and_inspect_modes() -> None:
    help_text = parser().format_help()

    assert "{prepare,apply,inspect}" in help_text
    assert (
        "--apply"
        not in parser()
        .parse_args(
            [
                "prepare",
                "--project-env",
                "/private/config",
                "--units",
                "/private/units.json",
                "--output-root",
                "/private/output",
                "--name",
                "batch",
            ]
        )
        .__dict__
    )
    assert (
        parser()
        .parse_args(
            [
                "apply",
                "--project-env",
                "/private/config",
                "--prepared",
                "/private/prepared.json",
                "--expected-prepared-sha256",
                "a" * 64,
                "--output-root",
                "/private/output",
                "--attempt-id",
                "batch-001",
                "--apply",
            ]
        )
        .apply
        is True
    )


def test_private_settings_identity_never_contains_credentials(tmp_path) -> None:
    config = tmp_path / "project.env"
    config.write_text(
        "DATABASE_URL=postgresql+psycopg://user:secret@127.0.0.1:5432/db\n"
        "GUIYI_CANONICAL_DATA_ROOT=/private/canonical\n"
        "RQDATA_LICENSE_KEY=provider-secret\n",
        encoding="utf-8",
    )
    config.chmod(0o600)

    settings, identity = load_private_execution_settings(config)

    assert settings["RQDATA_LICENSE_KEY"] == "provider-secret"
    serialized = json.dumps(identity)
    assert "secret" not in serialized
    assert identity.keys() == {"config_sha256", "canonical_root_sha256"}


def test_private_settings_uses_runtime_dependency_subset(tmp_path) -> None:
    config = tmp_path / "project.env"
    config.write_text(
        "POSTGRES_USER=user\n"
        "POSTGRES_PASSWORD=secret\n"
        "POSTGRES_DB=db\n"
        "DATABASE_URL=postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB}\n"
        "GUIYI_CANONICAL_DATA_ROOT=/private/canonical\n"
        "RQDATA_LICENSE_KEY=provider-secret\n"
        'CORS_ORIGINS=["http://127.0.0.1:5173"]\n',
        encoding="utf-8",
    )
    config.chmod(0o600)

    settings, _identity = load_private_execution_settings(config)

    assert settings["DATABASE_URL"].endswith("/db")
    assert "CORS_ORIGINS" not in settings


def test_private_settings_rejects_group_writable_or_symlink(tmp_path) -> None:
    config = tmp_path / "project.env"
    config.write_text(
        "DATABASE_URL=postgresql+psycopg://user@127.0.0.1:5432/db\n"
        "GUIYI_CANONICAL_DATA_ROOT=/private/canonical\n"
        "RQDATA_LICENSE_KEY=provider-secret\n",
        encoding="utf-8",
    )
    config.chmod(0o620)
    with pytest.raises(RecoveryError, match="^PROJECT_ENV_UNSAFE$"):
        load_private_execution_settings(config)
    config.chmod(0o600)
    link = tmp_path / "linked.env"
    link.symlink_to(config)
    with pytest.raises(RecoveryError, match="^PROJECT_ENV_UNSAFE$"):
        load_private_execution_settings(link)


def test_prepare_cli_writes_hash_locked_manifest_without_provider(
    tmp_path,
    monkeypatch,
) -> None:
    from scripts import newow_weekly_recovery as module

    manager, adapter, _plan = _prepare_fixture(tmp_path)
    released: list[bool] = []
    cleaned: list[bool] = []

    class Lease:
        def release(self):
            released.append(True)

    manager.catalog.acquire_maintenance_lock = lambda: Lease()
    units = tmp_path / "units.json"
    units.write_text(
        json.dumps(
            [
                {
                    "symbol": "ec",
                    "contract": "EC2607",
                    "through": "2026-06-30",
                    "frequency": "1w",
                }
            ]
        )
    )
    config = tmp_path / "project.env"
    config.write_text("fixture")
    monkeypatch.setattr(
        module,
        "_open_execution_environment",
        lambda _path, _observer=None: SimpleNamespace(
            manager=manager,
            adapter=adapter,
            identity={
                "config_sha256": "c" * 64,
                "canonical_root_sha256": "e" * 64,
            },
            settings={},
            close=lambda: cleaned.append(True),
        ),
    )
    monkeypatch.setattr(module, "_current_code_commit", lambda: "b" * 40)
    monkeypatch.setattr(
        module, "_require_clean_execution_checkout", lambda _commit: None
    )
    output = io.StringIO()

    code = main(
        [
            "prepare",
            "--project-env",
            str(config),
            "--units",
            str(units),
            "--output-root",
            str(tmp_path),
            "--name",
            "ec2607",
        ],
        stdout=output,
    )

    payload = json.loads(output.getvalue())
    assert code == 0
    assert payload["status"] == "prepared"
    assert payload["maintenance_lock_available"] is True
    assert len(payload["prepared_sha256"]) == 64
    assert Path(payload["prepared_file"]).exists()
    assert adapter.client_initialized is False
    assert released == [True]
    assert cleaned == [True]
