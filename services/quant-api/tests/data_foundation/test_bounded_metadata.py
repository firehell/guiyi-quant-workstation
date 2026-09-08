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
