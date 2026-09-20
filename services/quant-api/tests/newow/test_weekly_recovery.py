from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import subprocess
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
    _contract_warmup_target_payload,
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
    _validate_response_identity,
    _write_json_exclusive,
    create_attempt_directory,
    execute_prepared_batch,
    load_prepared_manifest,
    load_private_execution_settings,
    load_private_readonly_settings,
    main,
    parser,
    prepare_bounded_units,
    read_attempt_outcome,
    run_bounded_units,
    source_isolation_policy,
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
                "order_book_id": "EC2607",
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


def _priced_row(trading_day: date, *, contract: str = "EC2607") -> dict:
    return {
        "order_book_id": contract,
        "date": trading_day,
        "open": Decimal("100.10"),
        "high": Decimal("101.20"),
        "low": Decimal("99.30"),
        "close": Decimal("100.40"),
        "volume": Decimal("10"),
        "total_turnover": Decimal("1004.00"),
        "open_interest": Decimal("20"),
        "settlement": Decimal("100.50"),
        "prev_settlement": Decimal("100.00"),
    }


def _zero_ohl_row(trading_day: date, *, contract: str = "EC2607") -> dict:
    return {
        "order_book_id": contract,
        "date": trading_day,
        "open": Decimal("0"),
        "high": Decimal("0"),
        "low": Decimal("0"),
        "close": Decimal("100.40"),
        "volume": Decimal("2"),
        "total_turnover": Decimal("200.80"),
        "open_interest": Decimal("20"),
        "settlement": Decimal("100.40"),
        "prev_settlement": Decimal("100.00"),
    }


def test_response_identity_allows_in_window_zero_ohl_hole() -> None:
    expected = (date(2026, 3, 30), date(2026, 3, 31), date(2026, 4, 2), date(2026, 4, 3))
    request = ExchangeDailySourceRequest(
        contract="EC2607",
        start=date(2026, 3, 30),
        end=date(2026, 4, 3),
        expected_dates=expected,
    )
    response = (
        _priced_row(date(2026, 3, 30)),
        _priced_row(date(2026, 3, 31)),
        _zero_ohl_row(date(2026, 4, 1)),
        _priced_row(date(2026, 4, 2)),
        _priced_row(date(2026, 4, 3)),
    )
    _validate_response_identity(request, response)


def test_response_identity_allows_in_window_priced_extras_from_proven_week() -> None:
    """Fully proven weeks omit both zero-OHL and already-stored priced days."""
    expected = (date(2026, 3, 30), date(2026, 3, 31), date(2026, 4, 2), date(2026, 4, 3))
    request = ExchangeDailySourceRequest(
        contract="EC2607",
        start=date(2026, 3, 30),
        end=date(2026, 4, 3),
        expected_dates=expected,
    )
    response = (
        _priced_row(date(2026, 3, 30)),
        _priced_row(date(2026, 3, 31)),
        _priced_row(date(2026, 4, 1)),
        _priced_row(date(2026, 4, 2)),
        _priced_row(date(2026, 4, 3)),
    )
    _validate_response_identity(request, response)


def test_response_identity_rejects_missing_expected_outside_window_and_duplicate() -> None:
    request = _source_request()
    missing = tuple(_priced_row(day) for day in request.expected_dates[:-1])
    with pytest.raises(RecoveryError, match="^SOURCE_RESPONSE_IDENTITY_INVALID$"):
        _validate_response_identity(request, missing)

    outside = tuple(_rows())
    outside[-1]["date"] = date(2026, 4, 6)
    with pytest.raises(RecoveryError, match="^SOURCE_RESPONSE_IDENTITY_INVALID$"):
        _validate_response_identity(request, tuple(outside))

    duplicate = tuple(_rows())
    duplicate[-1]["date"] = request.expected_dates[0]
    with pytest.raises(RecoveryError, match="^SOURCE_RESPONSE_IDENTITY_INVALID$"):
        _validate_response_identity(request, tuple(duplicate))


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


@pytest.mark.parametrize("receipt_failure", [False, True])
def test_execute_prepared_batch_rechecks_hash_reads_back_and_stops(
    tmp_path, monkeypatch, receipt_failure,
) -> None:
    import scripts.newow_weekly_recovery as recovery_module

    write_json = recovery_module._write_json_exclusive

    def guarded_write(path, payload):
        if receipt_failure and path.name == "warmup-result.json":
            raise OSError("injected receipt write failure")
        return write_json(path, payload)

    monkeypatch.setattr(recovery_module, "_write_json_exclusive", guarded_write)
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
    arguments = dict(
        manifest=manifest,
        attempt_dir=attempt,
        prepared_sha256="9" * 64,
        current_code_commit="b" * 40,
        current_execution_code_sha256="d" * 64,
        current_config_sha256="c" * 64,
        current_canonical_root_sha256="e" * 64,
        open_unit=open_unit,
    )
    if receipt_failure:
        with pytest.raises(OSError, match="injected receipt"):
            execute_prepared_batch(**arguments)
        assert events == ["locked:EC2607", "invalidate:EC2607"]
        assert not (attempt / "unit-002-si-SI2401").exists()
        return
    result = execute_prepared_batch(**arguments)

    assert result["status"] == "partial"
    assert [unit["contract"] for unit in result["completed"]] == ["EC2607"]
    assert result["failed"]["contract"] == "SI2401"
    assert result["unattempted"] == []
    assert result["retries"] == 0
    assert json.loads((attempt / "unit-001-ec-EC2607" / "warmup-result.json").read_text())["provider_requests"] == 2
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


def _native_isolation_unit(
    contract: str,
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    unit = _isolation_unit(contract)
    symbol = contract[:2].lower()
    expected = tuple(
        datetime(2026, 3, 30, 1, 5, tzinfo=UTC) + timedelta(days=offset)
        for offset in range(5)
    )
    native_targets = (
        dict(
            _contract_warmup_target_payload(
                _Target(
                    DatasetKey("contract", symbol, contract, "1w"),
                    2026,
                    4,
                    expected,
                    expected,
                    (),
                )
            )
        ),
    )
    unit["targets"] = list(native_targets)
    return unit, native_targets


def test_source_quality_policy_isolates_one_unit_and_runs_its_next_sibling(
    tmp_path,
) -> None:
    native_unit, native_targets = _native_isolation_unit("EC2607")
    manifest = json.loads(
        json.dumps(
            {
                "schema_version": "newow_weekly_recovery_prepare_v1",
                "code_commit": "b" * 40,
                "execution_code_sha256": "d" * 64,
                "config_sha256": "c" * 64,
                "canonical_root_sha256": "e" * 64,
                "continuation_policy": _source_isolation_policy(),
                "units": [native_unit, _isolation_unit("SI2401")],
            }
        )
    )
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
                        native_targets if self.unit["contract"] == "EC2607" else ()
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
    escaped_journal_before: list[bytes] = []
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
            escaped_journal_before.append((escaped / "journal.jsonl").read_bytes())
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
        assert (escaped / "journal.jsonl").read_bytes() == escaped_journal_before[0]
        assert not (escaped / "unit-result.json").exists()
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
        "readback_plan_sha",
        "readback_dataset",
        "readback_window",
        "readback_count",
        "readback_bool_count",
    ],
)
def test_source_quality_policy_refuses_unproven_isolation(
    tmp_path,
    mutation,
) -> None:
    native_unit, native_targets = _native_isolation_unit("EC2607")
    manifest = json.loads(
        json.dumps(
            {
                "schema_version": "newow_weekly_recovery_prepare_v1",
                "code_commit": "b" * 40,
                "execution_code_sha256": "d" * 64,
                "config_sha256": "c" * 64,
                "canonical_root_sha256": "e" * 64,
                "continuation_policy": _source_isolation_policy(),
                "units": [native_unit],
            }
        )
    )
    unit = manifest["units"][0]

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
            target_windows = [dict(item) for item in native_targets]
            if mutation == "readback_dataset":
                target_windows[0]["dataset"] = (
                    "contract",
                    "ec",
                    "EC2608",
                    "1w",
                )
            elif mutation == "readback_window":
                target_windows[0]["missing_end"] = "2026-04-02T01:05:00+00:00"
            elif mutation == "readback_count":
                target_windows[0]["missing_bar_count"] = 4
            elif mutation == "readback_bool_count":
                target_windows[0]["missing_bar_count"] = True
            return SimpleNamespace(
                plan=SimpleNamespace(
                    plan_sha256=(
                        "f" * 64
                        if mutation == "readback_plan_sha"
                        else unit["plan_sha256"]
                    ),
                    target_windows=tuple(target_windows),
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
    expected_reason = (
        "SOURCE_ISOLATION_READBACK_FAILED"
        if mutation.startswith("readback_")
        else "SOURCE_ISOLATION_EVIDENCE_FAILED"
    )
    assert result["failed"]["isolation_failure_reason"] == expected_reason
    persisted = json.loads(
        (attempt / "unit-001-ec-EC2607" / "unit-result.json").read_text()
    )
    assert persisted["isolation_failure_reason"] == expected_reason
    batch_result = json.loads((attempt / "batch-result.json").read_text())
    assert batch_result["failed"]["isolation_failure_reason"] == expected_reason


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
        "frequency": "1w",
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


def test_daily_inspect_reports_daily_schema(tmp_path) -> None:
    attempt = tmp_path / "daily-attempt"
    attempt.mkdir()
    _write_json_exclusive(
        attempt / "invocation-receipt.json",
        {"schema_version": "newow_daily_recovery_invocation_v1"},
    )
    (attempt / "journal.jsonl").write_text("", encoding="utf-8")
    output = io.StringIO()

    code = main(["inspect", "--attempt", str(attempt)], stdout=output)

    assert code == 0
    assert json.loads(output.getvalue())["schema_version"] == (
        "newow_daily_recovery_result_v1"
    )
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


def test_readonly_settings_do_not_require_provider_credentials(tmp_path) -> None:
    config = tmp_path / "project.env"
    config.write_text(
        "DATABASE_URL=postgresql+psycopg://user@127.0.0.1:5432/db\n"
        "GUIYI_CANONICAL_DATA_ROOT=/private/canonical\n",
        encoding="utf-8",
    )
    config.chmod(0o600)

    settings, identity = load_private_readonly_settings(config)

    assert set(settings) == {"DATABASE_URL", "GUIYI_CANONICAL_DATA_ROOT"}
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


@pytest.mark.parametrize("value", [None, "1m", "daily", 1, ["1d"]])
def test_recovery_frequency_rejects_other_scopes(value) -> None:
    from scripts import newow_weekly_recovery as module

    with pytest.raises(RecoveryError, match="^RECOVERY_SCOPE_INVALID$"):
        module._recovery_frequency(value)


def test_recovery_frequency_accepts_hourly_profile() -> None:
    from scripts import newow_weekly_recovery as module

    assert module._recovery_frequency("60m") == "60m"
    assert module._allowed_target_frequencies("60m") == frozenset({"1m", "60m"})
    assert module._prepare_schema("60m") == "newow_hourly_recovery_prepare_v1"


def test_daily_prepare_freezes_only_native_daily_targets(tmp_path: Path) -> None:
    manager, _adapter, plan = _prepare_fixture(tmp_path)
    daily_target = _Target(
        DatasetKey("contract", "ec", "EC2607", "1d"),
        2026,
        3,
        tuple(
            datetime(2026, 3, 30, 1, 5, tzinfo=UTC) + timedelta(days=offset)
            for offset in range(5)
        ),
        tuple(
            datetime(2026, 3, 30, 1, 5, tzinfo=UTC) + timedelta(days=offset)
            for offset in range(5)
        ),
        (),
    )
    daily_plan_value = replace(
        plan,
        target_windows=(_contract_warmup_target_payload(daily_target),),
        direct_target_count=1,
        expected_bar_count=5,
        provider_request_count=1,
        frequency="1d",
        dependency_frequencies=(),
        frequencies=("1d",),
    )

    def daily_plan(request):
        assert str(getattr(request.frequency, "value", request.frequency)) == "1d"
        return daily_plan_value, (daily_target,)

    manager._contract_warmup_plan = daily_plan
    adapter = SimpleNamespace(
        client_initialized=False,
        exchange_daily_source_requests=lambda requests: (_source_request(),),
    )
    manifest = prepare_bounded_units(
        manager=manager,
        adapter=adapter,
        requests=(
            ContractWarmupRequest("ec", "EC2607", date(2026, 6, 30), frequency="1d"),
        ),
        expected_data_root=manager.catalog.canonical_root,
        code_commit="b" * 40,
        execution_code_sha256="d" * 64,
        config_sha256="c" * 64,
        recovery_frequency="1d",
    )

    assert manifest["schema_version"] == "newow_daily_recovery_prepare_v1"
    assert manifest["units"][0]["frequency"] == "1d"
    assert {target["dataset"][3] for target in manifest["units"][0]["targets"]} == {
        "1d"
    }
    assert adapter.client_initialized is False


def test_execute_prepared_batch_applies_and_replans_daily_at_daily_frequency(
    tmp_path: Path,
) -> None:
    source = _source_request()
    unit = {
        "symbol": "ec",
        "contract": "EC2607",
        "through": "2026-06-30",
        "frequency": "1d",
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
        "schema_version": "newow_daily_recovery_prepare_v1",
        "code_commit": "b" * 40,
        "execution_code_sha256": "d" * 64,
        "config_sha256": "c" * 64,
        "canonical_root_sha256": "e" * 64,
        "units": [unit],
    }
    seen: list[tuple[str, str]] = []

    class Manager:
        def contract_warmup(self, request, *, before_apply=None):
            frequency = str(getattr(request.frequency, "value", request.frequency))
            seen.append(("apply" if request.apply else "replan", frequency))
            if request.apply:
                assert before_apply is not None
                before_apply()
                return SimpleNamespace(
                    status="passed",
                    applied=1,
                    blocked=0,
                    failed=0,
                    provider_requests=1,
                    failures=(),
                )
            return SimpleNamespace(
                plan=SimpleNamespace(plan_sha256="f" * 64, target_windows=())
            )

    def open_unit(_journal, _unit):
        return (
            Manager(),
            lambda: None,
            lambda: {"catalog_partitions": [], "mds_target_count": 0},
            lambda: None,
        )

    attempt = create_attempt_directory(tmp_path, "daily-batch-001")
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

    assert seen == [("apply", "1d"), ("replan", "1d")]
    assert result["status"] == "passed"
    assert result["completed"][0]["remaining_target_count"] == 0


def test_daily_execution_digest_binds_verifier_and_consumer_inputs(
    tmp_path: Path,
) -> None:
    from scripts import newow_weekly_recovery as module

    assert (
        "services/quant-api/app/market_data/market_data_service.py"
        in module._D1_EXECUTION_CODE_PATHS
    )
    root = tmp_path / "checkout"
    root.mkdir()
    for relative in module._D1_EXECUTION_CODE_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=root,
        check=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    first = _current_execution_code_sha256(recovery_frequency="1d", project_root=root)
    _require_clean_execution_checkout(commit, project_root=root)
    verifier = root / "scripts/newow_daily_recovery_verification.py"
    verifier.write_text("changed", encoding="utf-8")
    second = _current_execution_code_sha256(recovery_frequency="1d", project_root=root)

    assert first != second
    with pytest.raises(RecoveryError, match="^EXECUTION_CHECKOUT_DIRTY$"):
        _require_clean_execution_checkout(commit, project_root=root)


@pytest.mark.parametrize("case", ["bars", "mixed", "quality_only", "missing", "overlap", "wrong_day", "wrong_expected"])
def test_daily_readback_proves_exact_quality_coverage(tmp_path, monkeypatch, case):
    from app.market_data import market_data_service as service_module

    root = tmp_path / "canonical"
    root.mkdir()
    path = root / "part.parquet"
    path.write_bytes(b"pinned-partition")
    ends = tuple(datetime(2026, 3, day, 7, tzinfo=UTC) for day in (30, 31))
    points = tuple(SimpleNamespace(bar_end=end, trading_day=end.date()) for end in ends)
    bars, facts = points, ()
    if case == "mixed":
        bars, facts = points[:1], points[1:]
    elif case == "quality_only":
        bars, facts = (), points
    elif case == "missing":
        bars = points[:1]
    elif case == "overlap":
        facts = points[1:]
    elif case == "wrong_day":
        bars = (points[0], SimpleNamespace(bar_end=ends[1], trading_day=ends[0].date()))
    partition = SimpleNamespace(year=2026, month=3, file_path=path, row_count=len(bars))
    catalog = SimpleNamespace(canonical_root=root, all_partitions=lambda key: (partition,))

    class Store:
        def read_catalog_partition_quality(self, value):
            assert value is partition
            return bars, facts

        def read_catalog_partition(self, value):
            pytest.fail("explicit D1 recovery must use the quality reader")

    class Service:
        def __init__(self, *args):
            pass

        def read_physical_daily_quality(self, request, *, require_window_coverage):
            assert request.start == ends[0] - timedelta(microseconds=1)
            assert request.end == ends[1]
            assert require_window_coverage is False
            return bars, facts

        def expected_contract_replay_endpoints(self, **kwargs):
            assert kwargs["after"] == ends[0] - timedelta(microseconds=1)
            assert kwargs["cutoff"] == ends[1]
            assert kwargs["trading_day"] == ends[1].date()
            expected = tuple((p.bar_end, p.trading_day) for p in points)
            return expected[:1] if case == "wrong_expected" else expected

    monkeypatch.setattr(service_module, "MarketDataService", Service)
    unit = {"symbol": "pg", "contract": "PG2607", "frequency": "1d", "targets": [{
        "dataset": ["contract", "pg", "PG2607", "1d"], "year": 2026, "month": 3,
        "expected_start": ends[0].isoformat(), "expected_end": ends[1].isoformat(),
        "expected_bar_count": 2,
    }]}
    manager = SimpleNamespace(catalog=catalog, store=Store())
    if case in {"missing", "overlap", "wrong_day", "wrong_expected"}:
        with pytest.raises(RecoveryError, match="POST_COMMIT_MDS_INVALID"):
            _post_commit_readback(manager, unit)
    else:
        result = _post_commit_readback(manager, unit)["catalog_partitions"][0]
        assert result["mds_bar_count"] == len(bars)
        assert result["mds_price_unavailable_count"] == len(facts)
        assert result["mds_endpoint_count"] == 2


@pytest.mark.parametrize("written", [0, 5])
def test_receipt_short_write_fails_closed(tmp_path, monkeypatch, written):
    import scripts.newow_weekly_recovery as recovery_module

    real_write = recovery_module.os.write

    def short_write(fd, content):
        return real_write(fd, content[:written])

    monkeypatch.setattr(recovery_module.os, "write", short_write)
    path = tmp_path / "receipt.json"
    with pytest.raises(OSError, match="RECEIPT_SHORT_WRITE"):
        _write_json_exclusive(path, {"provider_requests": 10})
    assert path.stat().st_size == written


@pytest.mark.parametrize("phase", ["request", "response"])
def test_source_capture_short_write_stops_before_consuming_response(tmp_path, monkeypatch, phase):
    import scripts.newow_weekly_recovery as recovery_module

    attempt = create_attempt_directory(tmp_path, "capture")
    request = _source_request()
    observer = AttemptJournal(attempt, (request,))
    if phase == "response":
        observer.before_request(request)
    real_write = recovery_module.os.write
    monkeypatch.setattr(recovery_module.os, "write", lambda fd, content: real_write(fd, content[:5]))
    with pytest.raises(RecoveryError):
        if phase == "request":
            observer.before_request(request)
        else:
            observer.after_response(request, tuple(_rows()))
    assert not (attempt / "source-response-0001.json").exists()


def _hourly_prepare_fixture(tmp_path):
    minute = DatasetKey("contract", "pt", "PT2610", "1m")
    hourly = DatasetKey("contract", "pt", "PT2610", "60m")
    ends = (datetime(2026, 9, 14, 7, 0, tzinfo=UTC),)
    targets = (
        _Target(minute, 2026, 9, ends, ends, ()),
        _Target(hourly, 2026, 9, ends, ends, ()),
    )
    windows = tuple(_contract_warmup_target_payload(item) for item in targets)
    plan = ContractWarmupPlan(
        symbol="pt",
        contract="PT2610",
        provider="rqdata",
        listed_date=date(2026, 2, 1),
        expired_date=date(2026, 10, 1),
        requested_through=date(2026, 9, 15),
        effective_through=date(2026, 9, 15),
        target_windows=windows,
        direct_target_count=1,
        derived_target_count=1,
        expected_bar_count=2,
        provider_request_count=0,
        plan_sha256="a" * 64,
        frequency="60m",
        dependency_frequencies=("1m",),
        frequencies=("1m", "60m"),
    )

    class Manager:
        catalog = SimpleNamespace(canonical_root=tmp_path / "canonical")
        provider_calls = 0
        writes = 0

        def _contract_warmup_plan(self, request):
            assert str(getattr(request.frequency, "value", request.frequency)) == "60m"
            return plan, targets

    class Adapter:
        client_initialized = False

        def exchange_daily_source_requests(self, requests):
            raise AssertionError("60m prepare must not use exchange daily")

    Manager.catalog.canonical_root.mkdir()
    return Manager(), Adapter(), plan


def test_prepare_hourly_uses_native_60m_plan_without_exchange_daily(tmp_path) -> None:
    manager, adapter, plan = _hourly_prepare_fixture(tmp_path)

    manifest = prepare_bounded_units(
        manager=manager,
        adapter=adapter,
        requests=(
            ContractWarmupRequest("pt", "PT2610", date(2026, 9, 15), frequency="60m"),
        ),
        expected_data_root=manager.catalog.canonical_root,
        code_commit="b" * 40,
        execution_code_sha256="d" * 64,
        config_sha256="c" * 64,
        recovery_frequency="60m",
    )

    assert manifest["schema_version"] == "newow_hourly_recovery_prepare_v1"
    assert manifest["units"][0]["frequency"] == "60m"
    assert manifest["units"][0]["source_requests"] == []
    assert manifest["units"][0]["provider_request_count"] == 0
    assert {item["dataset"][3] for item in manifest["units"][0]["targets"]} == {
        "1m",
        "60m",
    }
    assert [item["expected_bar_ends"] for item in manifest["units"][0]["targets"]] == [
        [end.isoformat()]
        for end in (datetime(2026, 9, 14, 7, 0, tzinfo=UTC),) * 2
    ]
    assert plan.plan_sha256 == manifest["units"][0]["plan_sha256"]
    assert adapter.client_initialized is False


def test_prepare_hourly_rejects_source_isolation_policy(tmp_path) -> None:
    manager, adapter, _plan = _hourly_prepare_fixture(tmp_path)

    with pytest.raises(RecoveryError, match="^RECOVERY_SCOPE_INVALID$"):
        prepare_bounded_units(
            manager=manager,
            adapter=adapter,
            requests=(
                ContractWarmupRequest(
                    "pt", "PT2610", date(2026, 9, 15), frequency="60m"
                ),
            ),
            expected_data_root=manager.catalog.canonical_root,
            code_commit="b" * 40,
            execution_code_sha256="d" * 64,
            config_sha256="c" * 64,
            continuation_policy=source_isolation_policy(),
            recovery_frequency="60m",
        )


def test_prepare_hourly_rejects_daily_or_weekly_targets(tmp_path) -> None:
    manager, adapter, plan = _hourly_prepare_fixture(tmp_path)
    daily = _Target(
        DatasetKey("contract", "pt", "PT2610", "1d"),
        2026,
        9,
        (datetime(2026, 9, 14, 7, 0, tzinfo=UTC),),
        (datetime(2026, 9, 14, 7, 0, tzinfo=UTC),),
        (),
    )

    def mixed_plan(request):
        assert str(getattr(request.frequency, "value", request.frequency)) == "60m"
        return plan, (daily,)

    manager._contract_warmup_plan = mixed_plan
    with pytest.raises(RecoveryError, match="^RECOVERY_SCOPE_INVALID$"):
        prepare_bounded_units(
            manager=manager,
            adapter=adapter,
            requests=(
                ContractWarmupRequest(
                    "pt", "PT2610", date(2026, 9, 15), frequency="60m"
                ),
            ),
            expected_data_root=manager.catalog.canonical_root,
            code_commit="b" * 40,
            execution_code_sha256="d" * 64,
            config_sha256="c" * 64,
            recovery_frequency="60m",
        )


def test_execute_hourly_fail_closes_without_isolation(tmp_path) -> None:
    unit = {
        "symbol": "pt",
        "contract": "PT2610",
        "through": "2026-09-15",
        "frequency": "60m",
        "plan_sha256": "a" * 64,
        "source_requests": [],
        "targets": [
            {
                "dataset": ["contract", "pt", "PT2610", "60m"],
                "year": 2026,
                "month": 9,
                "expected_start": "2026-09-14T07:00:00+00:00",
                "expected_end": "2026-09-14T07:00:00+00:00",
                "expected_bar_count": 1,
            }
        ],
    }
    manifest = {
        "schema_version": "newow_hourly_recovery_prepare_v1",
        "code_commit": "b" * 40,
        "execution_code_sha256": "d" * 64,
        "config_sha256": "c" * 64,
        "canonical_root_sha256": "e" * 64,
        "units": [unit, {**unit, "contract": "PT2608", "plan_sha256": "f" * 64}],
    }

    class Manager:
        def contract_warmup(self, request, *, before_apply=None):
            if request.apply:
                if before_apply is not None:
                    before_apply()
                return SimpleNamespace(
                    status="failed",
                    applied=0,
                    blocked=0,
                    failed=1,
                    provider_requests=0,
                    failures=({"reason_code": "ATOMIC_PUBLISH_FAILED"},),
                )
            return SimpleNamespace(plan=SimpleNamespace(target_windows=()))

    def open_unit(_observer, _unit):
        return (Manager(), lambda: None, lambda: {}, lambda: None)

    attempt = create_attempt_directory(tmp_path, "hourly-001")
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
    assert result["failed"]["contract"] == "PT2610"
    assert result["unattempted"][0]["contract"] == "PT2608"
    assert "isolated" not in result
    assert result["retries"] == 0


def test_execute_prepared_batch_applies_and_replans_hourly_at_hourly_frequency(
    tmp_path: Path,
) -> None:
    unit = {
        "symbol": "ag",
        "contract": "AG2412",
        "through": "2026-09-15",
        "frequency": "60m",
        "plan_sha256": "a" * 64,
        "source_requests": [],
        "targets": [
            {
                "dataset": ["contract", "ag", "AG2412", "1m"],
                "year": 2026,
                "month": 9,
                "expected_start": "2026-09-14T13:00:00+00:00",
                "expected_end": "2026-09-14T13:00:00+00:00",
                "expected_bar_count": 1,
            },
            {
                "dataset": ["contract", "ag", "AG2412", "60m"],
                "year": 2026,
                "month": 9,
                "expected_start": "2026-09-14T13:00:00+00:00",
                "expected_end": "2026-09-14T13:00:00+00:00",
                "expected_bar_count": 1,
            },
        ],
    }
    manifest = {
        "schema_version": "newow_hourly_recovery_prepare_v1",
        "code_commit": "b" * 40,
        "execution_code_sha256": "d" * 64,
        "config_sha256": "c" * 64,
        "canonical_root_sha256": "e" * 64,
        "units": [unit],
    }
    seen: list[tuple[str, str]] = []

    class Manager:
        def contract_warmup(self, request, *, before_apply=None):
            frequency = str(getattr(request.frequency, "value", request.frequency))
            seen.append(("apply" if request.apply else "replan", frequency))
            if request.apply:
                assert before_apply is not None
                before_apply()
                return SimpleNamespace(
                    status="passed",
                    applied=2,
                    blocked=0,
                    failed=0,
                    provider_requests=5,
                    failures=(),
                )
            return SimpleNamespace(
                plan=SimpleNamespace(plan_sha256="f" * 64, target_windows=())
            )

    def open_unit(_journal, _unit):
        assert tuple(_journal.allowed_requests) == ()
        return (
            Manager(),
            lambda: None,
            lambda: {"catalog_partitions": [], "mds_target_count": 0},
            lambda: None,
        )

    attempt = create_attempt_directory(tmp_path, "hourly-batch-001")
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

    assert seen == [("apply", "60m"), ("replan", "60m")]
    assert result["status"] == "passed"
    assert result["completed"][0]["remaining_target_count"] == 0
    assert result["completed"][0]["result"]["provider_requests"] == 5
    receipt = json.loads((attempt / "invocation-receipt.json").read_text())
    assert receipt["schema_version"] == "newow_hourly_recovery_invocation_v1"


def test_hourly_readback_uses_frozen_night_session_maintenance_expected(
    tmp_path, monkeypatch
) -> None:
    from app.market_data import market_data_service as service_module

    root = tmp_path / "canonical"
    root.mkdir()
    path = root / "part.parquet"
    path.write_bytes(b"pinned-partition")
    bar_end = datetime(2026, 9, 15, 2, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    trading_day = date(2026, 9, 14)
    bars = (SimpleNamespace(bar_end=bar_end, trading_day=trading_day),)
    partition = SimpleNamespace(year=2026, month=9, file_path=path, row_count=1)
    catalog = SimpleNamespace(canonical_root=root, all_partitions=lambda key: (partition,))
    seen: list[tuple[object, tuple[datetime, ...]]] = []

    class Store:
        def read_catalog_partition_quality(self, value):
            pytest.fail("60m recovery must not use the D1 quality reader")

        def read_catalog_partition(self, value):
            assert value is partition
            return bars

    class Service:
        def __init__(self, *args):
            pass

        def query(self, request):
            pytest.fail("60m readback must not recompute Calendar through query()")

        def query_maintenance_expected(self, request, expected):
            seen.append((request, expected))
            assert expected == (bar_end,)
            assert request.start == bar_end - timedelta(microseconds=1)
            assert request.end == bar_end
            assert request.end.astimezone(ZoneInfo("Asia/Shanghai")).date() != trading_day
            return SimpleNamespace(bars=bars)

    monkeypatch.setattr(service_module, "MarketDataService", Service)
    manager = SimpleNamespace(catalog=catalog, store=Store())
    unit = {
        "symbol": "ag",
        "contract": "AG2412",
        "frequency": "60m",
        "targets": [
            {
                "dataset": ["contract", "ag", "AG2412", "60m"],
                "year": 2026,
                "month": 9,
                "expected_start": bar_end.isoformat(),
                "expected_end": bar_end.isoformat(),
                "expected_bar_count": 1,
                "expected_bar_ends": [bar_end.isoformat()],
            }
        ],
    }
    readback = _post_commit_readback(manager, unit)
    assert readback["mds_target_count"] == 1
    assert len(seen) == 1
    assert bars[0].trading_day == trading_day
    assert bars[0].bar_end.astimezone(ZoneInfo("Asia/Shanghai")).date() != trading_day


def test_hourly_readback_rejects_missing_frozen_bar_ends(tmp_path, monkeypatch) -> None:
    from app.market_data import market_data_service as service_module

    root = tmp_path / "canonical"
    root.mkdir()
    path = root / "part.parquet"
    path.write_bytes(b"pinned-partition")
    end = datetime(2026, 9, 14, 13, tzinfo=UTC)
    bars = (SimpleNamespace(bar_end=end, trading_day=date(2026, 9, 14)),)
    partition = SimpleNamespace(year=2026, month=9, file_path=path, row_count=1)
    catalog = SimpleNamespace(canonical_root=root, all_partitions=lambda key: (partition,))

    class Store:
        def read_catalog_partition_quality(self, value):
            pytest.fail("60m recovery must not use the D1 quality reader")

        def read_catalog_partition(self, value):
            return bars

    class Service:
        def __init__(self, *args):
            pass

        def query(self, request):
            pytest.fail("60m readback must not recompute Calendar through query()")

        def query_maintenance_expected(self, request, expected):
            pytest.fail("missing expected_bar_ends must fail closed before MDS")

    monkeypatch.setattr(service_module, "MarketDataService", Service)
    manager = SimpleNamespace(catalog=catalog, store=Store())
    unit = {
        "symbol": "ag",
        "contract": "AG2412",
        "frequency": "60m",
        "targets": [
            {
                "dataset": ["contract", "ag", "AG2412", "60m"],
                "year": 2026,
                "month": 9,
                "expected_start": end.isoformat(),
                "expected_end": end.isoformat(),
                "expected_bar_count": 1,
            }
        ],
    }
    with pytest.raises(RecoveryError, match="^POST_COMMIT_READBACK_INVALID$"):
        _post_commit_readback(manager, unit)


def test_hourly_execution_digest_includes_mds(tmp_path: Path) -> None:
    from scripts import newow_weekly_recovery as module

    assert (
        "services/quant-api/app/market_data/market_data_service.py"
        in module._HOURLY_EXECUTION_CODE_PATHS
    )
    root = tmp_path / "checkout"
    root.mkdir()
    for relative in module._HOURLY_EXECUTION_CODE_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=root,
        check=True,
    )
    first = _current_execution_code_sha256(recovery_frequency="60m", project_root=root)
    weekly = _current_execution_code_sha256(recovery_frequency="1w", project_root=root)
    mds = root / "services/quant-api/app/market_data/market_data_service.py"
    mds.write_text("changed", encoding="utf-8")
    second = _current_execution_code_sha256(recovery_frequency="60m", project_root=root)
    weekly_after = _current_execution_code_sha256(
        recovery_frequency="1w", project_root=root
    )

    assert first != second
    assert first != weekly
    assert weekly == weekly_after


def test_parser_accepts_hourly_frequency() -> None:
    args = parser().parse_args(
        [
            "prepare",
            "--project-env",
            "env",
            "--units",
            "units.json",
            "--output-root",
            "out",
            "--name",
            "hourly",
            "--frequency",
            "60m",
        ]
    )
    assert args.frequency == "60m"
