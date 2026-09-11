"""Insert-only metadata repair, using an isolated Catalog and recorded provider shapes."""

from datetime import date, timedelta, time
import copy
import io
import json

import pandas as pd
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data import bounded_metadata as repair
from app.models import Contract, Exchange, Instrument, TradingCalendar, TradingSession


DAY = date(2023, 3, 13)
TARGETS = [{"symbol": "au", "contract": "AU2304", "through": DAY.isoformat()}]
HOURS = "21:01-02:30,09:01-10:15,10:31-11:30,13:31-15:00"


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            Exchange(code="SHFE", name="SHFE"),
            Instrument(symbol="au", name="gold", exchange_code="SHFE"),
            Contract(contract_code="AU2304", instrument_symbol="au", exchange_code="SHFE",
                     listed_date=DAY, expired_date=date(2023, 4, 1), provider="rqdata"),
            Contract(contract_code="AU2306", instrument_symbol="au", exchange_code="SHFE",
                     listed_date=DAY, expired_date=date(2023, 6, 1), provider="rqdata"),
        ])
        # Context is complete except the explicitly removed dates in individual tests.
        for offset in range(-41, 8):
            day = DAY + timedelta(days=offset)
            session.add(TradingCalendar(exchange_code="SHFE", trade_date=day,
                                        is_trading_day=day == DAY, has_night_session=day == DAY))
        session.commit()
    yield engine
    engine.dispose()


def plan(db, targets=None, classification=None, evidence_sources=None):
    with Session(db) as session:
        return repair.plan_metadata(session, targets or TARGETS, classification=classification,
                                    evidence_sources=evidence_sources)


class Provider:
    def __init__(self, *, hours=HOURS, trading=(), fail=False):
        self.hours, self.trading, self.fail = hours, trading, fail
        self.calls = []

    def get_trading_dates(self, *, start_date, end_date):
        self.calls.append(("dates", start_date, end_date))
        if self.fail:
            raise RuntimeError("private provider detail")
        return list(self.trading)

    def get_trading_periods(self, contracts, *, start_date, end_date, frequency):
        self.calls.append(("periods", contracts, start_date, end_date, frequency))
        if self.fail:
            raise RuntimeError("private provider detail")
        return pd.DataFrame([{"order_book_id": contract, "date": start_date,
                              "trading_hours": self.hours}
                             for contract in contracts])


def fetch(value, provider=None):
    return repair.fetch_metadata(value, expected_plan_sha256=value["plan_sha256"],
                                 api=provider or Provider())


def apply(db, snapshot):
    with Session(db) as session:
        return repair.apply_metadata(session, snapshot,
                                     expected_plan_sha256=snapshot["plan"]["plan_sha256"],
                                     expected_snapshot_sha256=snapshot["snapshot_sha256"])


def remove_calendar(db, day=DAY):
    with Session(db) as session:
        row = session.scalar(select(TradingCalendar).where(TradingCalendar.trade_date == day))
        session.delete(row)
        session.commit()


def test_overlapping_targets_deduplicate_days_but_retain_all_physical_sources(db):
    targets = [*TARGETS, {**TARGETS[0], "contract": "AU2306"}, TARGETS[0]]
    value = plan(db, targets)
    assert len(value["targets"]) == 2
    assert value["missing_sessions"] == [{"symbol": "au", "exchange": "SHFE",
        "date": "2023-03-13", "source_contracts": ["AU2304", "AU2306"]}]
    assert value["counts"]["session_dates"] == 1
    assert value["counts"]["session_rows"] is None
    assert value["counts"]["provider_requests"] == 2
    assert value == plan(db, list(reversed(targets)))


def test_unknown_calendar_never_expands_session_fetch_until_new_explicit_plan(db):
    remove_calendar(db)
    value = plan(db)
    assert value["missing_sessions"] == []
    assert value["counts"]["natural_date_keys"] == 1
    provider = Provider(trading=[DAY])
    classified = fetch(value, provider)
    assert provider.calls == [("dates", DAY, DAY)]
    assert classified["sessions"] == []
    assert classified["calendars"] == []
    assert classified["blockers"][0]["code"] == "NIGHT_SESSION_EVIDENCE_REQUIRED"
    with pytest.raises(repair.MetadataRepairError, match="SNAPSHOT_BLOCKED"):
        apply(db, classified)
    next_plan = plan(db, classification=classified)
    assert next_plan["plan_sha256"] != value["plan_sha256"]
    assert next_plan["counts"]["provider_requests"] == 1
    assert next_plan["missing_sessions"][0]["date"] == "2023-03-13"
    ready = fetch(next_plan)
    assert ready["calendars"][0]["has_night_session"] is True
    assert apply(db, ready)["status"] == "passed"


def test_nontrading_classification_can_insert_no_night_without_periods(db):
    remove_calendar(db)
    snapshot = fetch(plan(db))
    assert snapshot["calendars"][0]["is_trading_day"] is False
    assert snapshot["calendars"][0]["has_night_session"] is False
    assert snapshot["sessions"] == []
    assert apply(db, snapshot)["calendar_rows"] == 1


def test_day_only_source_cannot_prove_exchange_has_no_night(db):
    remove_calendar(db)
    classified = fetch(plan(db), Provider(trading=[DAY]))
    snapshot = fetch(plan(db, classification=classified), Provider(hours="09:01-15:00"))
    assert snapshot["calendars"] == []
    assert snapshot["blockers"][0]["code"] == "NIGHT_SESSION_EVIDENCE_REQUIRED"


def test_success_is_insert_only_and_normalizes_start_once(db):
    before = plan(db)
    snapshot = fetch(before)
    assert len(snapshot["sessions"]) == 4
    result = apply(db, snapshot)
    assert result["session_rows"] == 4
    with Session(db) as session:
        rows = session.scalars(select(TradingSession).order_by(TradingSession.session_name)).all()
        assert [(r.start_time, r.end_time) for r in rows] == [
            (time(21), time(2, 30)), (time(9), time(10, 15)),
            (time(10, 30), time(11, 30)), (time(13, 30), time(15))]
        assert session.scalar(select(TradingCalendar).where(
            TradingCalendar.trade_date == DAY)).has_night_session is True
    with pytest.raises(repair.MetadataRepairError, match="PLAN_DRIFT"):
        apply(db, snapshot)
    assert plan(db)["counts"]["provider_requests"] == 0


@pytest.mark.parametrize("change", ["partial", "template", "calendar", "identity"])
def test_fresh_apply_rejects_concurrent_drift_before_any_insert(db, change):
    snapshot = fetch(plan(db))
    with Session(db) as session:
        if change in {"partial", "template"}:
            session.add(TradingSession(exchange_code="SHFE", instrument_symbol="au",
                session_name="partial", start_time=time(9), end_time=time(10, 15),
                effective_from=DAY, effective_to=DAY if change == "partial" else None))
        elif change == "calendar":
            session.scalar(select(TradingCalendar).where(
                TradingCalendar.trade_date == DAY)).has_night_session = False
        else:
            session.scalar(select(Contract).where(
                Contract.contract_code == "AU2304")).exchange_code = "DCE"
        session.commit()
    with pytest.raises(repair.MetadataRepairError):
        apply(db, snapshot)
    with Session(db) as session:
        assert len(session.scalars(select(TradingSession)).all()) == (1 if change in {"partial", "template"} else 0)


def test_failed_commit_rolls_back_all_inserted_rows(db):
    snapshot = fetch(plan(db))
    with Session(db) as session:
        event.listen(session, "before_commit", lambda *_: (_ for _ in ()).throw(RuntimeError("fail")))
        with pytest.raises(repair.MetadataRepairError):
            repair.apply_metadata(session, snapshot, expected_plan_sha256=snapshot["plan"]["plan_sha256"],
                                  expected_snapshot_sha256=snapshot["snapshot_sha256"])
    with Session(db) as session:
        assert session.scalars(select(TradingSession)).all() == []


def test_commit_acknowledgment_loss_is_unknown_and_never_retried(db, monkeypatch):
    snapshot = fetch(plan(db))
    attempts = []
    with Session(db) as session:
        real_commit = session.commit
        def uncertain_commit():
            attempts.append('commit')
            real_commit()
            raise RuntimeError('acknowledgment unavailable')
        monkeypatch.setattr(session, 'commit', uncertain_commit)
        with pytest.raises(repair.MetadataRepairError, match='COMMIT_OUTCOME_UNKNOWN'):
            repair.apply_metadata(session, snapshot,
                                  expected_plan_sha256=snapshot['plan']['plan_sha256'],
                                  expected_snapshot_sha256=snapshot['snapshot_sha256'])
    assert attempts == ['commit']
    with Session(db) as independent:
        assert len(independent.scalars(select(TradingSession)).all()) == len(snapshot['sessions'])


def test_precommit_flush_failure_remains_apply_failed(db):
    snapshot = fetch(plan(db))
    with Session(db) as session:
        event.listen(session, 'before_flush', lambda *_: (_ for _ in ()).throw(RuntimeError('flush failed')))
        with pytest.raises(repair.MetadataRepairError, match='APPLY_FAILED'):
            repair.apply_metadata(session, snapshot,
                                  expected_plan_sha256=snapshot['plan']['plan_sha256'],
                                  expected_snapshot_sha256=snapshot['snapshot_sha256'])
    with Session(db) as independent:
        assert independent.scalars(select(TradingSession)).all() == []


@pytest.mark.parametrize("hours", ["09:00-15:00", "09:01-10:15,10:01-11:30", "garbage"])
def test_malformed_provider_periods_fail_without_snapshot_or_apply(db, hours):
    with pytest.raises(repair.MetadataRepairError):
        fetch(plan(db), Provider(hours=hours))


def test_source_disagreement_fails_closed(db):
    class Disagreement(Provider):
        def get_trading_periods(self, contracts, **kwargs):
            self.hours = HOURS if contracts == ("AU2304",) else "09:01-15:00"
            return super().get_trading_periods(contracts, **kwargs)
    with pytest.raises(repair.MetadataRepairError, match="SOURCE_DISAGREEMENT"):
        fetch(plan(db, [*TARGETS, {**TARGETS[0], "contract": "AU2306"}]), Disagreement())


def test_provider_failure_has_one_attempt_and_sanitized_error(db):
    provider = Provider(fail=True)
    with pytest.raises(repair.MetadataRepairError, match="PROVIDER_FAILED") as error:
        fetch(plan(db), provider)
    assert "private" not in str(error.value)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("change", ["hash", "scope", "rows"])
def test_tampered_payload_cannot_apply(db, change):
    snapshot = copy.deepcopy(fetch(plan(db)))
    if change == "hash":
        snapshot["snapshot_sha256"] = "0" * 64
    elif change == "scope":
        snapshot["plan"]["targets"][0]["contract"] = "AU2306"
    else:
        snapshot["sessions"][0]["instrument_symbol"] = "ag"
    with pytest.raises(repair.MetadataRepairError):
        apply(db, snapshot)


def test_unknown_contract_authority_never_infers_identity(db):
    with pytest.raises(repair.MetadataRepairError, match="IDENTITY_UNKNOWN"):
        plan(db, [{**TARGETS[0], "contract": "AU9999"}])


def test_cli_plan_composes_no_provider_or_writer(db, tmp_path, monkeypatch):
    from app.guiyi_cli.main import main
    from app.market_data import rqdata_adapter
    def forbidden(*_args, **_kwargs):
        raise AssertionError("provider/writer composed")
    monkeypatch.setattr(rqdata_adapter, "RQDataClient", forbidden)
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(json.dumps(TARGETS))
    output = io.StringIO()
    code = main(["data", "metadata-repair", "--targets", str(targets_path)],
                session_factory=lambda: Session(db), manager_factory=forbidden,
                stdout=output, stderr=output)
    assert code == 0
    assert json.loads(output.getvalue())["counts"]["session_dates"] == 1


def test_existing_exact_night_fact_proves_calendar_without_new_period_request(db):
    apply(db, fetch(plan(db)))
    remove_calendar(db)
    value = plan(db)
    snapshot = fetch(value, Provider(trading=[DAY]))
    assert snapshot["blockers"] == []
    assert snapshot["sessions"] == []
    assert snapshot["calendars"][0]["has_night_session"] is True
    assert apply(db, snapshot)["calendar_rows"] == 1


def test_first_malformed_period_response_stops_remaining_requests(db):
    provider = Provider(hours="garbage")
    with pytest.raises(repair.MetadataRepairError):
        fetch(plan(db, [*TARGETS, {**TARGETS[0], "contract": "AU2306"}]), provider)
    assert len(provider.calls) == 1


def test_source_disagreement_stops_remaining_days(db):
    with Session(db) as session:
        for code in ("AU2304", "AU2306"):
            session.scalar(select(Contract).where(Contract.contract_code == code)).listed_date -= timedelta(days=1)
        session.scalar(select(TradingCalendar).where(
            TradingCalendar.trade_date == DAY - timedelta(days=1))).is_trading_day = True
        session.scalar(select(TradingCalendar).where(
            TradingCalendar.trade_date == DAY - timedelta(days=1))).has_night_session = True
        session.commit()
    class Disagreement(Provider):
        def get_trading_periods(self, contracts, **kwargs):
            self.hours = HOURS if contracts == ("AU2304",) else "09:01-15:00"
            return super().get_trading_periods(contracts, **kwargs)
    provider = Disagreement()
    with pytest.raises(repair.MetadataRepairError, match="SOURCE_DISAGREEMENT"):
        fetch(plan(db, [*TARGETS, {**TARGETS[0], "contract": "AU2306"}]), provider)
    assert len(provider.calls) == 2


@pytest.mark.parametrize("variant", ["extra", "duplicate", "wrong_contract", "wrong_date", "numeric_date", "conflicting_alias"])
def test_provider_row_scope_and_identity_are_validated(db, variant):
    class Invalid(Provider):
        def get_trading_periods(self, contracts, **kwargs):
            rows = super().get_trading_periods(contracts, **kwargs).to_dict("records")
            if variant in {"extra", "duplicate"}:
                rows.append({**rows[0], "order_book_id": "AU9999" if variant == "extra" else "AU2304"})
            elif variant == "wrong_contract":
                rows[0]["order_book_id"] = "AU2306"
            elif variant == "wrong_date":
                rows[0]["date"] = DAY + timedelta(days=1)
            elif variant == "numeric_date":
                rows[0]["date"] = 1
            else:
                rows[0]["trading_date"] = DAY + timedelta(days=1)
            return pd.DataFrame(rows)
    with pytest.raises(repair.MetadataRepairError):
        fetch(plan(db), Invalid())


@pytest.mark.parametrize("trading", [[DAY, DAY], [DAY + timedelta(days=1)], [1]])
def test_calendar_provider_scope_duplicates_and_type_fail(db, trading):
    remove_calendar(db)
    with pytest.raises(repair.MetadataRepairError):
        fetch(plan(db), Provider(trading=trading))


def test_calendar_groups_do_not_bridge_present_keys_or_infer_weekends(db):
    for offset in (-3, -2, 0):
        remove_calendar(db, DAY + timedelta(days=offset))
    provider = Provider()
    snapshot = fetch(plan(db), provider)
    assert provider.calls == [("dates", date(2023, 3, 10), date(2023, 3, 11)), ("dates", DAY, DAY)]
    assert len(snapshot["calendars"]) == 3


@pytest.mark.parametrize("extra", [
    [], ["--phase", "fetch", "--plan", "absent"],
    ["--phase", "fetch", "--plan", "absent", "--apply", "--expected-plan-sha256", "bad"],
    ["--phase", "apply", "--snapshot", "absent", "--apply", "--expected-plan-sha256", "0" * 64],
    ["--targets", "absent", "--apply"],
])
def test_cli_mutating_phase_requires_separate_exact_intent_before_connection(extra):
    from app.guiyi_cli.main import main
    def forbidden():
        raise AssertionError("invalid phase connected")
    output = io.StringIO()
    assert main(["data", "metadata-repair", *extra], session_factory=forbidden,
                stdout=output, stderr=output) == 2


def test_cli_fetch_rechecks_drift_before_provider_construction(db, tmp_path, monkeypatch):
    from app.guiyi_cli.main import main
    from app.market_data import rqdata_adapter
    value = plan(db)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("provider constructed on drift")
    monkeypatch.setattr(rqdata_adapter, "RQDataClient", forbidden)
    with Session(db) as session:
        session.scalar(select(Contract).where(Contract.contract_code == "AU2304")).name = "changed"
        session.commit()
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(value))
    output = io.StringIO()
    assert main(["data", "metadata-repair", "--phase", "fetch", "--plan", str(path),
                 "--apply", "--expected-plan-sha256", value["plan_sha256"]],
                session_factory=lambda: Session(db), stdout=output, stderr=output) == 1
    assert "METADATA_REPAIR_PLAN_DRIFT" in output.getvalue()


def test_cli_apply_has_no_provider_and_preserves_unrelated_rows(db, tmp_path, monkeypatch):
    from app.guiyi_cli.main import main
    from app.market_data import rqdata_adapter
    snapshot = fetch(plan(db))
    with Session(db) as session:
        session.add(TradingSession(exchange_code="SHFE", instrument_symbol="ag", session_name="unrelated",
            start_time=time(9), end_time=time(15), effective_from=DAY, effective_to=DAY))
        session.commit()
    def forbidden(*_args, **_kwargs):
        raise AssertionError("provider composed for apply")
    monkeypatch.setattr(rqdata_adapter, "RQDataClient", forbidden)
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot))
    output = io.StringIO()
    assert main(["data", "metadata-repair", "--phase", "apply", "--snapshot", str(path), "--apply",
                 "--expected-plan-sha256", snapshot["plan"]["plan_sha256"],
                 "--expected-snapshot-sha256", snapshot["snapshot_sha256"]],
                session_factory=lambda: Session(db), manager_factory=forbidden,
                stdout=output, stderr=output) == 0
    with Session(db) as session:
        assert len(session.scalars(select(TradingSession)).all()) == 5


def test_fetched_night_cannot_contradict_existing_calendar(db):
    with Session(db) as session:
        session.scalar(select(TradingCalendar).where(
            TradingCalendar.trade_date == DAY)).has_night_session = False
        session.commit()
    with pytest.raises(repair.MetadataRepairError, match="CALENDAR_CONFLICT"):
        fetch(plan(db))


def test_resealed_out_of_lifecycle_request_is_rejected_before_provider(db):
    value = plan(db)
    value["missing_sessions"][0]["date"] = "2022-01-01"
    value["requests"][0]["start_date"] = "2022-01-01"
    value["requests"][0]["end_date"] = "2022-01-01"
    # New approval hashes cannot bypass identity/lifecycle input validation.
    import hashlib
    value["plan_sha256"] = hashlib.sha256(json.dumps(
        {k: v for k, v in value.items() if k != "plan_sha256"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    provider = Provider()
    with pytest.raises(repair.MetadataRepairError, match="SCOPE_INVALID"):
        fetch(value, provider)
    assert provider.calls == []


def test_partial_existing_session_day_is_never_filled_or_claimed_complete(db):
    with Session(db) as session:
        session.add(TradingSession(exchange_code="SHFE", instrument_symbol="au", session_name="partial",
            start_time=time(9), end_time=time(10, 15), effective_from=DAY, effective_to=DAY))
        session.commit()
    value = plan(db)
    assert value["missing_sessions"] == []
    assert value["counts"]["existing_session_dates_preserved"] == 1
    assert value["counts"]["session_rows"] is None


def test_existing_template_overlap_is_an_explicit_blocker(db):
    with Session(db) as session:
        session.add(TradingSession(exchange_code="SHFE", instrument_symbol="au", session_name="template",
            start_time=time(9), end_time=time(15), effective_from=DAY, effective_to=None))
        session.commit()
    with pytest.raises(repair.MetadataRepairError, match="SESSION_OVERLAP"):
        plan(db)


def test_explicit_context_source_proves_night_without_expanding_calendar_or_session_writes(db):
    context_day = date(2023, 2, 1)
    remove_calendar(db, context_day)
    with Session(db) as session:
        session.add(Contract(contract_code="AU2302", instrument_symbol="au", exchange_code="SHFE",
            listed_date=date(2022, 2, 1), expired_date=date(2023, 2, 28), provider="rqdata"))
        session.commit()
    original = plan(db)
    classified = fetch(original, Provider(trading=[context_day]))
    assert classified["blockers"][0]["code"] == "NIGHT_SESSION_EVIDENCE_REQUIRED"
    sources = [{"symbol": "au", "contract": "AU2302", "date": context_day.isoformat()}]
    bounded = plan(db, classification=classified, evidence_sources=sources)
    assert bounded["missing_calendars"] == original["missing_calendars"]
    assert bounded["missing_sessions"] == original["missing_sessions"]
    assert bounded["counts"]["evidence_source_days"] == 1
    snapshot = fetch(bounded)
    assert snapshot["blockers"] == []
    assert [row["trade_date"] for row in snapshot["calendars"]] == ["2023-02-01"]
    assert {row["effective_from"] for row in snapshot["sessions"]} == {"2023-03-13"}
    assert apply(db, snapshot)["session_rows"] == 4


@pytest.mark.parametrize("source", [
    {"symbol": "au", "contract": "AU2304", "date": "2023-02-01"},
    {"symbol": "au", "contract": "AU2306", "date": "2023-03-12"},
    {"symbol": "au", "contract": "AU9999", "date": "2023-02-01"},
])
def test_explicit_context_source_must_match_missing_key_and_lifecycle(db, source):
    remove_calendar(db, date(2023, 2, 1))
    classified = fetch(plan(db), Provider(trading=[date(2023, 2, 1)]))
    with pytest.raises(repair.MetadataRepairError):
        plan(db, classification=classified, evidence_sources=[source])


def test_inconsistent_existing_night_row_cannot_authorize_calendar(db):
    remove_calendar(db)
    with Session(db) as session:
        session.add(TradingSession(exchange_code="SHFE", instrument_symbol="au", session_name="invalid",
            start_time=time(9), end_time=time(15), crosses_midnight=True,
            effective_from=DAY, effective_to=DAY))
        session.commit()
    with pytest.raises(repair.MetadataRepairError):
        fetch(plan(db), Provider(trading=[DAY]))


def test_apply_refreshes_cached_identity_after_lock(db):
    snapshot = fetch(plan(db))
    with Session(db, expire_on_commit=False) as session:
        cached = session.scalar(select(Contract).where(Contract.contract_code == "AU2304"))
        session.commit()
        with Session(db) as other:
            other.scalar(select(Contract).where(Contract.contract_code == "AU2304")).name = "changed"
            other.commit()
        assert cached.name is None
        with pytest.raises(repair.MetadataRepairError, match="PLAN_DRIFT"):
            repair.apply_metadata(session, snapshot, expected_plan_sha256=snapshot["plan"]["plan_sha256"],
                                  expected_snapshot_sha256=snapshot["snapshot_sha256"])


def test_invalid_empty_evidence_input_is_rejected(db):
    with pytest.raises(repair.MetadataRepairError):
        plan(db, evidence_sources={})


def test_empty_fetch_plan_does_not_initialize_provider(db, tmp_path, monkeypatch):
    from app.guiyi_cli.main import main
    from app.market_data import rqdata_adapter
    apply(db, fetch(plan(db)))
    value = plan(db)
    assert value["requests"] == []
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(value))
    def forbidden():
        raise AssertionError("zero request plan initialized provider")
    monkeypatch.setattr(rqdata_adapter, "RQDataClient", forbidden)
    output = io.StringIO()
    assert main(["data", "metadata-repair", "--phase", "fetch", "--plan", str(path),
                 "--expected-plan-sha256", value["plan_sha256"], "--apply"],
                session_factory=lambda: Session(db), stdout=output, stderr=output) == 0


def test_fetch_discloses_external_phase_and_exact_call_count(db):
    snapshot = fetch(plan(db))
    assert snapshot["readonly"] is False
    assert snapshot["database_writes"] == 0
    assert snapshot["provider_request_count"] == 1


@pytest.mark.parametrize("is_trading", [False, True])
@pytest.mark.parametrize("session_day", [DAY, DAY - timedelta(days=1)])
def test_existing_calendar_session_conflict_blocks_other_metadata_repairs(db, is_trading, session_day):
    remove_calendar(db, DAY - timedelta(days=2))
    with Session(db) as session:
        calendar = session.scalar(select(TradingCalendar).where(TradingCalendar.trade_date == session_day))
        calendar.is_trading_day = is_trading
        calendar.has_night_session = False
        session.add(TradingSession(exchange_code="SHFE", instrument_symbol="au", session_name="existing",
            start_time=time(21) if is_trading else time(9), end_time=time(23) if is_trading else time(15),
            effective_from=session_day, effective_to=session_day, provider="rqdata", is_active=True))
        session.commit()
    with pytest.raises(repair.MetadataRepairError, match="CALENDAR_CONFLICT"):
        plan(db)
    with Session(db) as session:
        assert session.scalar(select(TradingCalendar).where(
            TradingCalendar.trade_date == DAY - timedelta(days=2))) is None


@pytest.mark.parametrize("is_trading", [False, True])
def test_apply_rechecks_new_existing_session_conflict_after_lock(db, is_trading):
    remove_calendar(db, DAY - timedelta(days=2))
    with Session(db) as session:
        calendar = session.scalar(select(TradingCalendar).where(TradingCalendar.trade_date == DAY))
        calendar.is_trading_day = is_trading
        calendar.has_night_session = False
        session.commit()
    snapshot = fetch(plan(db), Provider(hours="09:01-15:00"))
    with Session(db) as session:
        session.add(TradingSession(exchange_code="SHFE", instrument_symbol="au", session_name="new-conflict",
            start_time=time(21) if is_trading else time(9), end_time=time(23) if is_trading else time(15),
            effective_from=DAY, effective_to=DAY, provider="rqdata", is_active=True))
        session.commit()
    statements = []
    event.listen(db, "before_cursor_execute", lambda _conn, _cursor, stmt, *_args: statements.append(stmt))
    with pytest.raises(repair.MetadataRepairError, match="CALENDAR_CONFLICT"):
        apply(db, snapshot)
    assert statements[0] == "BEGIN IMMEDIATE"
    assert not any(statement.startswith("INSERT") for statement in statements)
    with Session(db) as session:
        assert session.scalar(select(TradingCalendar).where(
            TradingCalendar.trade_date == DAY - timedelta(days=2))) is None


def test_unknown_calendar_can_wait_for_classification_but_not_contradict_existing_day_session(db):
    remove_calendar(db)
    with Session(db) as session:
        session.add(TradingSession(exchange_code="SHFE", instrument_symbol="au", session_name="existing-day",
            start_time=time(9), end_time=time(15), effective_from=DAY, effective_to=DAY,
            provider="rqdata", is_active=True))
        session.commit()
    value = plan(db)
    assert value["counts"]["natural_date_keys"] == 1
    assert value["missing_sessions"] == []
    with pytest.raises(repair.MetadataRepairError, match="CALENDAR_CONFLICT"):
        fetch(value, Provider(trading=[]))
    classified = fetch(value, Provider(trading=[DAY]))
    assert classified["blockers"][0]["code"] == "NIGHT_SESSION_EVIDENCE_REQUIRED"


@pytest.fixture
def future_context_db():
    """A completed target whose seven-day Calendar context reaches the future."""
    from app.market_data.coverage_source import _calendar_context_start

    through = date.today() - timedelta(days=1)
    evidence_day = date.today() + timedelta(days=4)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            Exchange(code="SHFE", name="SHFE"),
            Instrument(symbol="au", name="gold", exchange_code="SHFE"),
            Contract(contract_code="AU2701", instrument_symbol="au", exchange_code="SHFE",
                     listed_date=through, expired_date=through + timedelta(days=60), provider="rqdata"),
        ])
        start = _calendar_context_start(through)
        for offset in range((through + timedelta(days=7) - start).days + 1):
            day = start + timedelta(days=offset)
            if day != evidence_day:
                session.add(TradingCalendar(exchange_code="SHFE", trade_date=day,
                                            is_trading_day=False, has_night_session=False))
        session.commit()
    yield engine, through, evidence_day
    engine.dispose()


def test_future_context_evidence_uses_source_date_without_expanding_target_or_session_scope(future_context_db):
    db, through, evidence_day = future_context_db
    targets = [{"symbol": "au", "contract": "AU2701", "through": through.isoformat()}]
    original = plan(db, targets)
    classified = fetch(original, Provider(trading=[evidence_day]))
    source = {"symbol": "au", "contract": "AU2701", "date": evidence_day.isoformat()}
    value = plan(db, targets, classification=classified, evidence_sources=[source])
    assert value["targets"] == original["targets"]
    assert value["missing_calendars"] == original["missing_calendars"]
    assert value["missing_sessions"] == []
    assert value["requests"] == [{"method": "get_trading_periods", "symbol": "au", "contract": "AU2701",
        "exchange": "SHFE", "start_date": evidence_day.isoformat(), "end_date": evidence_day.isoformat(),
        "frequency": "1m"}]
    snapshot = fetch(value)
    assert snapshot["blockers"] == []
    assert snapshot["sessions"] == []
    assert snapshot["calendars"][0]["has_night_session"] is True
    assert apply(db, snapshot)["calendar_rows"] == 1


@pytest.mark.parametrize("offset", [0, 4])
def test_target_through_today_or_future_remains_forbidden(future_context_db, offset):
    db, _, _ = future_context_db
    with pytest.raises(repair.MetadataRepairError, match="SCOPE_INVALID"):
        plan(db, [{"symbol": "au", "contract": "AU2701",
                   "through": (date.today() + timedelta(days=offset)).isoformat()}])


@pytest.mark.parametrize("change", [
    {"symbol": "inactive_product"}, {"contract": "AU2701/escape"}, {"extra": "forbidden"},
    {"date": "not-a-date"}, {"date": (date.today() + timedelta(days=7)).isoformat()},
])
def test_future_evidence_retains_structure_identity_and_calendar_scope_guards(future_context_db, change):
    db, through, evidence_day = future_context_db
    targets = [{"symbol": "au", "contract": "AU2701", "through": through.isoformat()}]
    classified = fetch(plan(db, targets), Provider(trading=[evidence_day]))
    source = {"symbol": "au", "contract": "AU2701", "date": evidence_day.isoformat(), **change}
    with pytest.raises(repair.MetadataRepairError):
        plan(db, targets, classification=classified, evidence_sources=[source])


@pytest.mark.parametrize("case", ["unclassified", "nontrading", "expired", "before_listing", "provider"])
def test_future_evidence_requires_trading_classification_and_authoritative_lifecycle(future_context_db, case):
    db, through, evidence_day = future_context_db
    targets = [{"symbol": "au", "contract": "AU2701", "through": through.isoformat()}]
    classified = None if case == "unclassified" else fetch(
        plan(db, targets), Provider(trading=[] if case == "nontrading" else [evidence_day]))
    contract = "AU2701"
    if case in {"expired", "before_listing", "provider"}:
        contract = "AU2702"
        with Session(db) as session:
            session.add(Contract(contract_code=contract, instrument_symbol="au", exchange_code="SHFE",
                listed_date=evidence_day + timedelta(days=1) if case == "before_listing" else through,
                expired_date=evidence_day if case == "expired" else evidence_day + timedelta(days=60),
                provider="other" if case == "provider" else "rqdata"))
            session.commit()
    with pytest.raises(repair.MetadataRepairError):
        plan(db, targets, classification=classified,
             evidence_sources=[{"symbol": "au", "contract": contract, "date": evidence_day.isoformat()}])


@pytest.fixture
def exchange_universe_case(future_context_db):
    db, through, day = future_context_db
    with Session(db) as session:
        session.add(Instrument(symbol="ag", name="silver", exchange_code="SHFE"))
        session.add(Contract(contract_code="AG2701", instrument_symbol="ag", exchange_code="SHFE",
                             listed_date=through, expired_date=day + timedelta(days=60), provider="rqdata"))
        session.commit()
    targets = [{"symbol": "au", "contract": "AU2701", "through": through.isoformat()}]
    classified = fetch(plan(db, targets), Provider(trading=[day]))
    universe = {"exchange": "SHFE", "date": day.isoformat(), "products": ["ag", "au"],
                "sources": [{"symbol": symbol, "contract": symbol.upper() + "2701", "date": day.isoformat()}
                            for symbol in ("ag", "au")]}
    return db, targets, classified, universe


def inventory_for(case):
    day = date.fromisoformat(case[3]["date"])
    return {"identity": {"method": "all_instruments_by_type", "args": [],
                         "kwargs": {"instrument_type": "Future", "market": "cn"}},
            "response": [{"exchange": "SHFE", "underlying_symbol": symbol.upper(),
                          "order_book_id": symbol.upper() + "2701",
                          "listed_date": case[1][0]["through"],
                          "de_listed_date": (day + timedelta(days=60)).isoformat()}
                         for symbol in ("ag", "au")]}


def universe_plan(case, universe=None, classification=True, inventory="default"):
    db, targets, classified, original = case
    with Session(db) as session:
        return repair.plan_metadata(session, targets, classification=classified if classification else None,
                                    exchange_universes=[original if universe is None else universe],
                                    exchange_inventory_evidence=inventory_for(case) if inventory == "default" else inventory)


@pytest.mark.parametrize("night", [False, True])
def test_complete_exchange_universe_resolves_day_only_or_any_night(exchange_universe_case, night):
    case = exchange_universe_case
    value = universe_plan(case)
    assert value["targets"] == case[1]
    assert value["missing_sessions"] == []
    assert {q["contract"] for q in value["requests"]} == {"AG2701", "AU2701"}

    class MixedProvider(Provider):
        def get_trading_periods(self, contracts, **kwargs):
            self.hours = HOURS if night and contracts == ("AG2701",) else "09:01-15:00"
            return super().get_trading_periods(contracts, **kwargs)

    snapshot = fetch(value, MixedProvider())
    assert snapshot["blockers"] == []
    assert snapshot["sessions"] == []  # Cross-batch witnesses are never Session insert targets.
    assert snapshot["calendars"][0]["has_night_session"] is night
    # JSON persistence preserves the full scope and fresh-recheck contract.
    import json
    snapshot = json.loads(json.dumps(snapshot))
    with Session(case[0]) as session:
        repair.recheck_plan(session, snapshot["plan"], expected_plan_sha256=value["plan_sha256"])
    assert apply(case[0], snapshot)["calendar_rows"] == 1
    with Session(case[0]) as session:
        assert session.scalars(select(TradingSession)).all() == []


@pytest.mark.parametrize("case", ["partial", "duplicate", "mismatch", "extra", "exchange", "date", "empty", "inactive", "unclassified"])
def test_exchange_universe_rejects_partial_mismatched_or_outside_scope(exchange_universe_case, case):
    import copy
    universe = copy.deepcopy(exchange_universe_case[3])
    if case == "partial":
        universe["sources"].pop()
    elif case == "duplicate":
        universe["sources"].append(universe["sources"][0])
    elif case == "mismatch":
        universe["sources"][0]["symbol"] = "au"
    elif case == "extra":
        universe["unexpected"] = True
    elif case == "exchange":
        universe["exchange"] = "GFEX"
    elif case == "date":
        universe["date"] = "2020-01-01"
    elif case == "empty":
        universe["products"] = []
    elif case == "inactive":
        universe["products"][0] = "nonactive"
    with pytest.raises(repair.MetadataRepairError):
        universe_plan(exchange_universe_case, universe, classification=case != "unclassified")


@pytest.mark.parametrize("change", ["provider", "expired", "not_listed", "exchange", "inactive"])
def test_exchange_universe_sources_require_live_catalog_identity(exchange_universe_case, change):
    db, _, _, universe = exchange_universe_case
    with Session(db) as session:
        contract = session.scalar(select(Contract).where(Contract.contract_code == "AG2701"))
        if change == "provider":
            contract.provider = "other"
        elif change == "expired":
            contract.expired_date = date.fromisoformat(universe["date"])
        elif change == "not_listed":
            contract.listed_date = date.fromisoformat(universe["date"]) + timedelta(days=1)
        elif change == "exchange":
            contract.exchange_code = "GFEX"
        else:
            session.scalar(select(Instrument).where(Instrument.symbol == "ag")).is_active = False
        session.commit()
    with pytest.raises(repair.MetadataRepairError):
        universe_plan(exchange_universe_case)


def test_exchange_universe_tamper_and_source_drift_stop_before_insert(exchange_universe_case):
    import copy
    db = exchange_universe_case[0]
    value = universe_plan(exchange_universe_case)
    snapshot = fetch(value, Provider(hours="09:01-15:00"))
    tampered = copy.deepcopy(value)
    tampered["exchange_universes"][0]["sources"].pop()
    tampered = repair._sealed({k: v for k, v in tampered.items() if k != "plan_sha256"}, "plan_sha256")
    with pytest.raises(repair.MetadataRepairError):
        fetch(tampered)
    with Session(db) as session:
        session.scalar(select(Contract).where(Contract.contract_code == "AG2701")).expired_date += timedelta(days=1)
        session.commit()
    with pytest.raises(repair.MetadataRepairError, match="PLAN_DRIFT"):
        apply(db, snapshot)


def test_complete_universe_missing_actual_row_cannot_be_negative(exchange_universe_case):
    value = universe_plan(exchange_universe_case)
    class MissingProvider(Provider):
        def get_trading_periods(self, contracts, **kwargs):
            if contracts == ("AG2701",):
                return pd.DataFrame(columns=["order_book_id", "date", "trading_hours"])
            return super().get_trading_periods(contracts, **kwargs)
    with pytest.raises(repair.MetadataRepairError):
        fetch(value, MissingProvider(hours="09:01-15:00"))


def test_exchange_universe_simultaneous_shrink_cannot_claim_complete(exchange_universe_case):
    import copy
    universe = copy.deepcopy(exchange_universe_case[3])
    universe["products"] = ["au"]
    universe["sources"] = [source for source in universe["sources"] if source["symbol"] == "au"]
    with pytest.raises(repair.MetadataRepairError):
        universe_plan(exchange_universe_case, universe)


@pytest.mark.parametrize("change", ["missing", "method", "args", "kwargs", "omitted_row", "invalid_other_exchange", "row_identity", "duplicate", "extra_field"])
def test_exchange_inventory_requires_exact_unfiltered_identity_and_lifecycle(exchange_universe_case, change):
    inventory = inventory_for(exchange_universe_case)
    if change == "missing":
        inventory = None
    elif change == "method":
        inventory["identity"]["method"] = "all_instruments"
    elif change == "args":
        inventory["identity"]["args"] = ["AG"]
    elif change == "kwargs":
        inventory["identity"]["kwargs"]["date"] = "2026-09-14"
    elif change == "omitted_row":
        inventory["response"].pop()
    elif change == "invalid_other_exchange":
        inventory["response"].append({"exchange": "DCE", "underlying_symbol": "A", "order_book_id": "A2701",
                                      "listed_date": None, "de_listed_date": "2027-01-01"})
    elif change == "row_identity":
        inventory["response"][0]["order_book_id"] = "WRONG2701"
    elif change == "duplicate":
        inventory["response"].append(inventory["response"][0])
    else:
        inventory["identity"]["extra"] = True
    with pytest.raises(repair.MetadataRepairError):
        universe_plan(exchange_universe_case, inventory=inventory)


@pytest.mark.parametrize("field", ["listed_date", "de_listed_date"])
@pytest.mark.parametrize("value", [None, "0000-00-00", "not-a-date"])
def test_inventory_missing_or_invalid_lifecycle_retains_error_classification(exchange_universe_case, field, value):
    inventory = inventory_for(exchange_universe_case)
    inventory["response"][0][field] = value
    expected = "INVENTORY_INVALID" if value == "not-a-date" else "INVENTORY_UNIVERSE_MISMATCH"
    with pytest.raises(repair.MetadataRepairError, match=expected):
        universe_plan(exchange_universe_case, inventory=inventory)


def test_inventory_source_outside_lifecycle_retains_source_mismatch(exchange_universe_case):
    inventory = inventory_for(exchange_universe_case)
    inventory["response"].append({**inventory["response"][0], "order_book_id": "AG2702"})
    inventory["response"][0]["de_listed_date"] = exchange_universe_case[3]["date"]
    with pytest.raises(repair.MetadataRepairError, match="INVENTORY_SOURCE_MISMATCH"):
        universe_plan(exchange_universe_case, inventory=inventory)


def test_inventory_raw_response_is_hash_bound_and_recomputed(exchange_universe_case):
    import copy
    value = universe_plan(exchange_universe_case)
    assert value["exchange_inventory_evidence"] == inventory_for(exchange_universe_case)
    changed = copy.deepcopy(value)
    changed["exchange_inventory_evidence"]["response"].pop()
    with pytest.raises(repair.MetadataRepairError, match="HASH_INVALID"):
        fetch(changed)
    changed = repair._sealed({k: v for k, v in changed.items() if k != "plan_sha256"}, "plan_sha256")
    with pytest.raises(repair.MetadataRepairError, match="INVENTORY"):
        fetch(changed)


def test_inventory_source_contract_must_exist_in_full_response(exchange_universe_case):
    inventory = inventory_for(exchange_universe_case)
    inventory["response"][0]["order_book_id"] = "AG2702"
    with pytest.raises(repair.MetadataRepairError):
        universe_plan(exchange_universe_case, inventory=inventory)


def test_cli_plan_accepts_inventory_and_universe_files(exchange_universe_case, tmp_path):
    import io
    import json
    from app.guiyi_cli.main import main

    db, targets, classified, universe = exchange_universe_case
    files = {"targets": targets, "classification": classified, "exchange-universes": [universe],
             "exchange-inventory-evidence": inventory_for(exchange_universe_case)}
    args = ["data", "metadata-repair"]
    for name, value in files.items():
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps(value))
        args += ["--" + name, str(path)]
    output = io.StringIO()
    assert main(args, session_factory=lambda: Session(db), stdout=output) == 0
    value = json.loads(output.getvalue())
    assert value["exchange_inventory_evidence"] == files["exchange-inventory-evidence"]
    assert len(value["requests"]) == 2
