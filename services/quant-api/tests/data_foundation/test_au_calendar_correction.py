"""Single-key correction with isolated facts; never query a provider."""
import copy
import hashlib
import io
import json
from datetime import date, time

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.guiyi_cli.main import main
from app.models import Contract, Exchange, Instrument, TradingCalendar, TradingSession


DAY = date(2022, 3, 16)
CALENDAR = dict(id=46796, exchange_code="SHFE", trade_date=DAY,
                is_trading_day=True, has_night_session=False, provider="rqdata",
                remark="FULL-HISTORY-RESIDUAL-REPAIR-004B metadata-trading-calendar-001")
RESPONSE = [{"date": "2022-03-16", "order_book_id": "AU2304",
             "trading_hours": "21:01-02:30,09:01-10:15,10:31-11:30,13:31-15:00"}]


def seed(engine):
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            Exchange(code="SHFE", name="SHFE"),
            Instrument(symbol="au", name="gold", exchange_code="SHFE"),
            Contract(contract_code="AU2304", instrument_symbol="au", exchange_code="SHFE",
                     listed_date=DAY, expired_date=date(2023, 4, 17), provider="rqdata"),
            TradingCalendar(**CALENDAR),
            TradingCalendar(exchange_code="SHFE", trade_date=date(2022, 3, 17),
                            is_trading_day=True, has_night_session=False),
        ])
        session.commit()


@pytest.fixture
def db(tmp_path):
    engine = create_engine("sqlite+pysqlite:///" + str(tmp_path / "isolated.sqlite"))
    seed(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def evidence(tmp_path):
    path = tmp_path / "response.json"
    path.write_text(json.dumps({"source_response": RESPONSE}))
    return path


def invoke(db, evidence, *extra):
    output = io.StringIO()
    code = main(["data", "au-calendar-correction", "--evidence", str(evidence),
                 "--expected-evidence-sha256", hashlib.sha256(evidence.read_bytes()).hexdigest(),
                 *extra], session_factory=lambda: Session(db),
                manager_factory=lambda *_: pytest.fail("must not construct maintenance"),
                stdout=output, stderr=output)
    return code, json.loads(output.getvalue())


def test_dry_run_binds_one_field_without_writes(db, evidence):
    code, plan = invoke(db, evidence)
    assert code == 0, plan
    assert plan["status"] == "planned" and plan["readonly"] is True
    assert plan["target"] == {"id": 46796, "exchange_code": "SHFE", "trade_date": "2022-03-16"}
    assert plan["change"] == {"has_night_session": {"before": False, "after": True}}
    assert plan["provider_requests"] == plan["database_writes"] == 0
    assert plan["planned_calendar_updates"] == 1
    assert len(plan["plan_sha256"]) == 64
    with Session(db) as session:
        assert session.get(TradingCalendar, 46796).has_night_session is False
        assert list(session.scalars(select(TradingSession))) == []


def test_apply_changes_only_approved_field_and_independently_reads_back(db, evidence):
    _, plan = invoke(db, evidence)
    code, result = invoke(db, evidence, "--apply", "--expected-plan-sha256", plan["plan_sha256"])
    assert code == 0, result
    assert result["status"] == "passed" and result["readback_verified"] is True
    assert result["database_writes"] == 1 and result["provider_requests"] == 0
    with Session(db) as session:
        actual = session.get(TradingCalendar, 46796)
        assert {k: getattr(actual, k) for k in CALENDAR} == {**CALENDAR, "has_night_session": True}
        other = session.scalar(select(TradingCalendar).where(TradingCalendar.trade_date == date(2022, 3, 17)))
        assert other.has_night_session is False
        assert list(session.scalars(select(TradingSession))) == []
    assert invoke(db, evidence, "--apply", "--expected-plan-sha256", plan["plan_sha256"])[0] == 1


@pytest.mark.parametrize("field,value", [("id", 99), ("exchange_code", "DCE"),
    ("trade_date", date(2022, 3, 17)), ("is_trading_day", False),
    ("provider", "manual"), ("remark", "changed"), ("has_night_session", True)])
def test_wrong_calendar_or_changed_old_value_is_rejected(db, evidence, field, value):
    with Session(db) as session:
        if field == "trade_date":
            session.delete(session.scalar(select(TradingCalendar).where(TradingCalendar.trade_date == value)))
            session.flush()
        setattr(session.get(TradingCalendar, 46796), field, value)
        session.commit()
    assert invoke(db, evidence)[0] == 1


@pytest.mark.parametrize("change", ["contract", "instrument", "exchange", "session"])
def test_identity_and_session_drift_rejects_stale_plan(db, evidence, change):
    _, plan = invoke(db, evidence)
    with Session(db) as session:
        if change == "contract":
            session.scalar(select(Contract)).expired_date = date(2023, 4, 18)
        elif change == "instrument":
            session.scalar(select(Instrument)).is_active = False
        elif change == "exchange":
            session.scalar(select(Exchange)).timezone = "UTC"
        else:
            session.add(TradingSession(exchange_code="SHFE", instrument_symbol="au", session_name="new",
                start_time=time(9), end_time=time(10), effective_from=DAY, effective_to=DAY))
        session.commit()
    assert invoke(db, evidence, "--apply", "--expected-plan-sha256", plan["plan_sha256"])[0] == 1
    with Session(db) as session:
        assert session.get(TradingCalendar, 46796).has_night_session is False


@pytest.mark.parametrize("change", ["contract", "date", "hours", "extra"])
def test_evidence_cannot_expand_or_change_approved_response(db, evidence, change):
    rows = copy.deepcopy(RESPONSE)
    if change == "extra":
        rows.append(rows[0])
    else:
        rows[0][{"contract": "order_book_id", "date": "date", "hours": "trading_hours"}[change]] = {
            "contract": "AU2306", "date": "2022-03-17", "hours": "09:01-15:00"}[change]
    evidence.write_text(json.dumps({"source_response": rows}))
    assert invoke(db, evidence)[0] == 1


@pytest.mark.parametrize("args", [("--apply",), ("--expected-plan-sha256", "a" * 64),
    ("--apply", "--expected-plan-sha256", "bad"), ("--symbol", "rb")])
def test_cli_refuses_ambiguous_mutation_or_expanded_scope(db, evidence, args):
    assert invoke(db, evidence, *args)[0] == 2


def test_wrong_hash_stops_before_write(db, evidence):
    assert invoke(db, evidence, "--apply", "--expected-plan-sha256", "a" * 64)[0] == 1
    with Session(db) as session:
        assert session.get(TradingCalendar, 46796).has_night_session is False


@pytest.mark.parametrize("phase", ["before_flush", "before_commit", "after_commit"])
def test_failures_never_retry_and_commit_uncertainty_is_explicit(db, evidence, phase):
    _, plan = invoke(db, evidence)
    from app.market_data.au_calendar_correction import apply_correction, CorrectionError
    calls = []
    with Session(db) as session:
        def fail(*_):
            calls.append(1)
            raise RuntimeError("private detail")
        event.listen(session, phase, fail)
        with pytest.raises(CorrectionError) as caught:
            apply_correction(session, plan, expected_plan_sha256=plan["plan_sha256"])
    assert len(calls) == 1
    assert caught.value.code == ("AU_CALENDAR_CORRECTION_APPLY_FAILED" if phase == "before_flush"
                                 else "AU_CALENDAR_CORRECTION_COMMIT_OUTCOME_UNKNOWN")
    with Session(db) as session:
        assert session.get(TradingCalendar, 46796).has_night_session is (phase == "after_commit")


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "oversize", "duplicate", "hash"])
def test_unsafe_or_changed_evidence_is_rejected_before_db(db, evidence, kind):
    from app.market_data.au_calendar_correction import read_evidence, CorrectionError
    expected = hashlib.sha256(evidence.read_bytes()).hexdigest()
    if kind in {"symlink", "hardlink"}:
        import os
        new = evidence.with_name("linked.json")
        if kind == "symlink":
            new.symlink_to(evidence)
        else:
            os.link(evidence, new)
        evidence = new
    elif kind == "oversize":
        evidence.write_text("x" * 65537)
    elif kind == "duplicate":
        evidence.write_text('{"source_response":[],"source_response":' + json.dumps(RESPONSE) + '}')
        expected = hashlib.sha256(evidence.read_bytes()).hexdigest()
    else:
        expected = "a" * 64
    with pytest.raises(CorrectionError):
        read_evidence(str(evidence), expected)


def test_dirty_session_is_rejected_without_flushing_unrelated_changes(db, evidence):
    from app.market_data.au_calendar_correction import apply_correction, CorrectionError
    _, plan = invoke(db, evidence)
    with Session(db) as session:
        session.add(Exchange(code="UNRELATED", name="not authorized"))
        with pytest.raises(CorrectionError, match="SESSION_NOT_CLEAN"):
            apply_correction(session, plan, expected_plan_sha256=plan["plan_sha256"])
    with Session(db) as session:
        assert session.scalar(select(Exchange).where(Exchange.code == "UNRELATED")) is None


def test_readback_failure_does_not_report_success_or_retry(db, evidence):
    from types import SimpleNamespace
    from app.market_data.au_calendar_correction import run_correction, CorrectionError
    _, plan = invoke(db, evidence)
    calls = []
    def factory():
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError("readback unavailable")
        return Session(db)
    args = SimpleNamespace(evidence=str(evidence),
        expected_evidence_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
        apply=True, expected_plan_sha256=plan["plan_sha256"])
    with pytest.raises(CorrectionError, match="COMMITTED_READBACK_UNVERIFIED"):
        run_correction(args, factory)
    assert len(calls) == 3
    with Session(db) as session:
        assert session.get(TradingCalendar, 46796).has_night_session is True


def test_dry_run_is_enforced_readonly_and_rolls_back(db, evidence):
    from app.market_data.au_calendar_correction import plan_correction, read_evidence
    observed = []
    def inspect(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            observed.append(connection.exec_driver_sql("PRAGMA query_only").scalar())
    event.listen(db, "before_cursor_execute", inspect)
    with Session(db) as session:
        source = read_evidence(str(evidence), hashlib.sha256(evidence.read_bytes()).hexdigest())
        plan_correction(session, source)
        assert not session.in_transaction()
    event.remove(db, "before_cursor_execute", inspect)
    assert observed and all(value == 1 for value in observed)
    with db.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA query_only").scalar() == 0


def test_in_transaction_readback_reloads_facts_not_identity_map(db, evidence):
    from sqlalchemy import text
    from app.market_data.au_calendar_correction import apply_correction, CorrectionError
    _, plan = invoke(db, evidence)
    with Session(db) as session:
        def unexpected_change(*_):
            session.execute(text("UPDATE trading_calendars SET remark = 'trigger changed' WHERE id = 46796"))
        event.listen(session, "after_flush", unexpected_change)
        with pytest.raises(CorrectionError):
            apply_correction(session, plan, expected_plan_sha256=plan["plan_sha256"])
    with Session(db) as session:
        row = session.get(TradingCalendar, 46796)
        assert row.has_night_session is False and row.remark == CALENDAR["remark"]
