"""Read visibility, failure recovery and pagination against isolated PostgreSQL."""

from datetime import date
from decimal import Decimal
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from app.main import app
from app.services.newow_backtest_results import (
    ResultStore,
    ResultStoreError,
    SeriesKey,
)


API = "/api/v1/newow/backtests"


def _key(profile_id="trend_5m_rqalpha_v1"):
    return SeriesKey("fu", "trend", "5m", profile_id)


def _manifest(day, variant):
    return {
        "as_of_trading_day": day,
        "input_digest": variant,
        "engine": "RQAlpha",
        "window": [day, day],
    }


def _trades():
    return [
        {
            "physical_contract": "FU2603",
            "side": "BUY",
            "position_effect": "OPEN",
            "quantity": 1,
            "price": Decimal("2485"),
            "fee": Decimal("1.2425"),
            "decision": {"signal_bar_end": "2026-01-05T09:30:00+08:00"},
        },
        {
            "physical_contract": "FU2603",
            "side": "SELL",
            "position_effect": "CLOSE_TODAY",
            "quantity": 1,
            "price": Decimal("2480"),
            "fee": Decimal("0"),
            "gross_pnl": Decimal("-50"),
            "net_pnl": Decimal("-51.2425"),
            "entry_seq": 1,
        },
    ]


def _equity(day):
    return [
        dict(
            trading_day=day, equity="10000", cash="10000", margin="0",
            fees="0", unrealized_pnl="0", drawdown="0",
        ),
        dict(
            trading_day=day, equity="9948.7575", cash="9948.7575", margin="0",
            fees="1.2425", unrealized_pnl="0", drawdown="51.2425",
        ),
    ]


def _publish(store, admission, day):
    store.publish(admission, {"net_pnl": "-51.24250000"}, _trades(), _equity(day))


@pytest.fixture
def p3_results(monkeypatch):
    dsn = os.environ.get("GUIYI_P3_TEST_WRITE_DSN")
    read_dsn = os.environ.get("GUIYI_P3_TEST_READ_DSN")
    if not dsn or not read_dsn:
        pytest.skip("explicit dedicated P3 PostgreSQL test DSNs required")
    assert dsn.endswith("/guiyi_newow_backtest_test")
    assert read_dsn.endswith("/guiyi_newow_backtest_test")
    store = ResultStore(dsn)
    monkeypatch.setenv("GUIYI_NEWOW_BACKTEST_READ_DSN", read_dsn)
    with store._engine.begin() as conn:
        conn.execute(text(
            "TRUNCATE newow_backtest_series, newow_backtest_runs, "
            "newow_backtest_trades, newow_backtest_equity"
        ))
    with TestClient(app) as client:
        yield store, client
    store.close()


def _latest(client, key):
    response = client.get(f"{API}/latest", params={
        "product": key.product, "strategy": key.strategy,
        "frequency": key.frequency, "research_profile_id": key.research_profile_id,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_api_never_uses_the_main_database(monkeypatch):
    monkeypatch.delenv("GUIYI_NEWOW_BACKTEST_READ_DSN", raising=False)
    with TestClient(app) as client:
        assert client.get(
            f"{API}/latest?product=fu&strategy=trend&frequency=5m&research_profile_id=trend_5m_rqalpha_v1"
        ).status_code == 503


@pytest.mark.parametrize("dsn", [
    "",
    "sqlite:///x.db",
    "postgresql+psycopg://u@127.0.0.1:5432/guiyi_newow_backtest",
    "postgresql+psycopg://u@remote.example:55432/guiyi_newow_backtest",
    "postgresql+psycopg://u@127.0.0.1:55432/guiyi_quant",
    "postgresql+psycopg://u@127.0.0.1:55432/guiyi_newow_backtest?host=remote.example",
])
def test_result_store_requires_named_isolated_database(dsn):
    with pytest.raises(ResultStoreError, match="BACKTEST_DATABASE_UNAVAILABLE"):
        ResultStore(dsn)


@pytest.mark.isolated_postgresql
def test_publication_keeps_run_bound_pagination_and_prior_success_on_failure(p3_results, monkeypatch):
    store, client = p3_results
    key = _key()
    day = "2026-01-05"
    assert _latest(client, key) == {"result": None, "last_attempt": None}
    first = store.admit(key, _manifest(day, "first"), eligible=True)
    assert _latest(client, key)["last_attempt"]["status"] == "RUNNING"
    assert client.get(f"{API}/{first.run_id}/trades").status_code == 404
    _publish(store, first, day)
    _publish(store, first, day)
    assert not store.admit(key, _manifest(day, "first"), eligible=True).should_run

    page = client.get(f"{API}/{first.run_id}/trades?limit=1").json()
    assert page["items"][0]["price"] == "2485.00000000"
    assert page["items"][0]["fee"] == "1.24250000"
    cursor = page["next_cursor"]
    assert cursor
    assert client.get(f"{API}/{first.run_id}/equity", params={"cursor": cursor}).status_code == 422
    assert client.get(f"{API}/{first.run_id}/trades?limit=201").status_code == 422

    late = store.admit(key, _manifest(day, "late"), eligible=True)
    current = store.admit(key, _manifest(day, "current"), eligible=True)
    _publish(store, current, day)
    _publish(store, late, day)
    earlier = store.admit(key, _manifest("2026-01-04", "earlier"), eligible=True)
    _publish(store, earlier, "2026-01-04")

    latest = _latest(client, key)
    assert latest["result"]["run_id"] == current.run_id
    assert latest["result"]["as_of_trading_day"] == day
    assert client.get(f"{API}/{current.run_id}/trades", params={"cursor": cursor}).status_code == 422
    page = client.get(f"{API}/{first.run_id}/trades", params={"cursor": cursor}).json()
    assert page["items"][0]["entry_seq"] == 1
    assert page["items"][0]["net_pnl"] == "-51.24250000"
    assert page["next_cursor"] is None

    def forbidden(*args, **kwargs):
        raise AssertionError("HTTP attempted a result write")

    from app.market_data.market_data_service import MarketDataService
    monkeypatch.setattr(MarketDataService, "query_contract_trading_days", forbidden)
    monkeypatch.setattr(ResultStore, "publish", forbidden)
    monkeypatch.setattr(ResultStore, "admit", forbidden)
    import subprocess
    monkeypatch.setattr(subprocess, "run", forbidden)
    assert _latest(client, key)["result"]["run_id"] == current.run_id
    equity = client.get(f"{API}/{current.run_id}/equity").json()["items"]
    assert [item["seq"] for item in equity] == [0, 1]
    assert equity[1]["equity"] == "9948.75750000"


@pytest.mark.isolated_postgresql
def test_ineligible_attempt_preserves_old_result_and_trial_cannot_promote(p3_results):
    store, client = p3_results
    date_value = date(2026, 1, 5)
    day = date_value.isoformat()
    key = _key()
    previous = store.admit(key, _manifest(day, "qualified"), eligible=True)
    _publish(store, previous, day)
    blocked = store.admit(key, _manifest(day, "data_gap"), eligible=False)
    with pytest.raises(ResultStoreError, match="BACKTEST_FORMAL_INELIGIBLE"):
        _publish(store, blocked, day)
    store.fail(blocked, "RANK1_AS_KNOWN_UNPROVEN")
    latest = _latest(client, key)
    assert latest["result"]["run_id"] == previous.run_id
    assert latest["last_attempt"]["error_code"] == "RANK1_AS_KNOWN_UNPROVEN"
    assert latest["last_attempt"]["status"] == "FAILED"
    assert client.get(f"{API}/{blocked.run_id}/equity").status_code == 404

    trial_key = _key("trend_5m_rqalpha_trial_v1")
    trial = store.admit(trial_key, _manifest(day, "data_gap"), eligible=False)
    _publish(store, trial, day)
    assert _latest(client, trial_key)["result"]["qualification"] == "TRIAL"
    assert _latest(client, key)["result"]["qualification"] == "QUALIFIED"


@pytest.mark.isolated_postgresql
def test_true_transaction_failure_is_atomic_and_explicit_retry_is_safe(p3_results):
    store, client = p3_results
    key, day = _key(), "2026-01-05"
    first = store.admit(key, _manifest(day, "first"), eligible=True)
    _publish(store, first, day)
    failed = store.admit(key, _manifest(day, "in_flight"), eligible=True)
    with store._engine.begin() as conn:
        conn.exec_driver_sql(
            "ALTER TABLE newow_backtest_equity ADD CONSTRAINT p3_test_force_rollback "
            "CHECK (seq < 0) NOT VALID"
        )
    try:
        with pytest.raises(ResultStoreError, match="BACKTEST_RESULT_WRITE_FAILED"):
            _publish(store, failed, day)
        with store._engine.connect() as conn:
            count = conn.execute(text("SELECT count(*) FROM newow_backtest_trades WHERE run_id = :run_id"),
                                 {"run_id": failed.run_id}).scalar_one()
            assert count == 0
        assert _latest(client, key)["result"]["run_id"] == first.run_id
        store.fail(failed, "BACKTEST_RESULT_WRITE_FAILED")
    finally:
        with store._engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE newow_backtest_equity DROP CONSTRAINT p3_test_force_rollback")
    retry = store.admit(key, _manifest(day, "in_flight"), eligible=True)
    assert retry.run_id == failed.run_id
    assert retry.generation > failed.generation
    _publish(store, retry, day)
    assert _latest(client, key)["result"]["run_id"] == retry.run_id


@pytest.mark.isolated_postgresql
def test_lost_commit_acknowledgement_reconciles_committed_publication(p3_results, monkeypatch):
    import psycopg

    store, client = p3_results
    key, day = _key(), "2026-01-05"
    admission = store.admit(key, _manifest(day, "lost_commit_ack"), eligible=True)
    commit = store._engine.dialect.do_commit

    def commit_without_ack(dbapi_connection):
        commit(dbapi_connection)
        raise psycopg.OperationalError("simulated lost acknowledgement")

    with monkeypatch.context() as patch:
        patch.setattr(store._engine.dialect, "do_commit", commit_without_ack)
        _publish(store, admission, day)
    assert _latest(client, key)["result"]["run_id"] == admission.run_id
    assert len(client.get(f"{API}/{admission.run_id}/trades").json()["items"]) == 2
    assert not store.admit(key, _manifest(day, "lost_commit_ack"), eligible=True).should_run


@pytest.mark.isolated_postgresql
def test_migration_coexists_with_existing_catalog_and_reference_tables(p3_results):
    store, _ = p3_results
    with store._engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20261124_0055"
        tables = set(inspect(conn).get_table_names())
        assert {
            "market_partitions", "reference_inbox_recovery_results",
            "newow_backtest_series", "newow_backtest_runs",
            "newow_backtest_trades", "newow_backtest_equity",
        } <= tables


@pytest.mark.isolated_postgresql
def test_read_connection_cannot_issue_writes(p3_results):
    from sqlalchemy.exc import DBAPIError

    store = ResultStore(os.environ["GUIYI_P3_TEST_READ_DSN"], read_only=True)
    try:
        with store._reader() as conn:
            assert conn.scalar(text("SHOW transaction_read_only")) == "on"
            with pytest.raises(DBAPIError) as exc_info:
                conn.execute(text("DELETE FROM newow_backtest_runs WHERE false"))
            assert exc_info.value.orig.sqlstate == "25006"
    finally:
        store.close()


@pytest.mark.isolated_postgresql
def test_readers_never_see_partially_inserted_run(p3_results):
    from sqlalchemy import event

    store, client = p3_results
    key, day = _key(), "2026-01-05"
    first = store.admit(key, _manifest(day, "previous"), eligible=True)
    _publish(store, first, day)
    second = store.admit(key, _manifest(day, "invisible"), eligible=True)
    observations = []

    def check_staged_trades(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.startswith("INSERT INTO newow_backtest_trades"):
            observations.append(_latest(client, key)["result"]["run_id"])
            assert client.get(f"{API}/{second.run_id}/trades").status_code == 404

    event.listen(store._engine, "after_cursor_execute", check_staged_trades)
    try:
        _publish(store, second, day)
    finally:
        event.remove(store._engine, "after_cursor_execute", check_staged_trades)
    assert observations == [first.run_id]
    assert _latest(client, key)["result"]["run_id"] == second.run_id


@pytest.mark.isolated_postgresql
def test_job_slot_rejects_same_series_contention_without_waiting(p3_results):
    store, _ = p3_results
    key, day = _key(), "2026-01-05"
    with store.job_slot(key) as connection:
        with pytest.raises(ResultStoreError, match="BACKTEST_JOB_BUSY"), store.job_slot(key):
            pytest.fail("a second connection obtained the active series lock")
        trial = _key("trend_5m_rqalpha_trial_v1")
        with store.job_slot(trial):
            pass
        run = store.admit(key, _manifest(day, "slot"), eligible=True, job_connection=connection)
        assert run.should_run
    with store.job_slot(key):
        pass


@pytest.mark.isolated_postgresql
def test_job_slot_recovers_known_orphan_and_rejects_old_writer(p3_results):
    store, client = p3_results
    key, day = _key(), "2026-01-05"
    manifest = _manifest(day, "orphan")
    with store.job_slot(key) as connection:
        orphan = store.admit(key, manifest, eligible=True, job_connection=connection)
    duplicate = store.admit(key, manifest, eligible=True)
    assert duplicate.status == "RUNNING"
    assert not duplicate.should_run
    with store.job_slot(key) as connection:
        recovered = store.admit(key, manifest, eligible=True, job_connection=connection)
        assert recovered.run_id == orphan.run_id
        assert recovered.generation > orphan.generation
        assert recovered.should_run
        with pytest.raises(ResultStoreError, match="BACKTEST_STALE_ATTEMPT"):
            _publish(store, orphan, day)
        with pytest.raises(ResultStoreError, match="BACKTEST_STALE_ATTEMPT"):
            store.fail(orphan, "OLD_PROCESS_FAILURE")
        _publish(store, recovered, day)

    with store.job_slot(key) as connection:
        duplicate = store.admit(key, manifest, eligible=True, job_connection=connection)
        assert duplicate.status == "SUCCEEDED"
        assert not duplicate.should_run
        assert duplicate.generation == recovered.generation
        assert _latest(client, key)["result"]["run_id"] == recovered.run_id


@pytest.mark.isolated_postgresql
def test_admission_cannot_allocate_a_generation_after_job_slot_loss(p3_results):
    store, client = p3_results
    key, day = _key(), "2026-01-05"
    with store.job_slot(key) as connection:
        with connection.begin():
            connection.execute(text("SELECT pg_advisory_unlock_all()"))
        with pytest.raises(ResultStoreError, match="BACKTEST_JOB_SLOT_LOST"):
            store.admit(key, _manifest(day, "lost_slot"), eligible=True, job_connection=connection)
    assert _latest(client, key) == {"result": None, "last_attempt": None}


@pytest.mark.isolated_postgresql
def test_job_slot_refuses_to_recover_running_with_existing_children(p3_results):
    store, client = p3_results
    key, day = _key(), "2026-01-05"
    manifest = _manifest(day, "partial_state")
    with store.job_slot(key) as connection:
        orphan = store.admit(key, manifest, eligible=True, job_connection=connection)
    with store._engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO newow_backtest_equity "
            "(run_id, seq, trading_day, equity, cash, margin, fees, unrealized_pnl, drawdown, detail) "
            "VALUES (:run_id, 0, :day, 10000, 10000, 0, 0, 0, 0, '{}')"
        ), {"run_id": orphan.run_id, "day": date.fromisoformat(day)})
    with store.job_slot(key) as connection:
        with pytest.raises(ResultStoreError, match="BACKTEST_COMMIT_OUTCOME_UNKNOWN"):
            store.admit(key, manifest, eligible=True, job_connection=connection)
    assert _latest(client, key)["last_attempt"]["generation"] == orphan.generation
