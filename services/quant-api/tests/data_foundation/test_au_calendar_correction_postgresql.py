"""Explicit isolated PostgreSQL only; no application configuration is read."""
import hashlib
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.market_data.au_calendar_correction import CorrectionError, apply_correction
from app.models import TradingCalendar
from test_au_calendar_correction import RESPONSE, invoke, seed


pytestmark = pytest.mark.isolated_postgresql


@pytest.fixture
def db():
    target = os.environ.get("GUIYI_ISOLATED_CALENDAR_DATABASE_URL", "")
    if not target:
        pytest.skip("GUIYI_ISOLATED_CALENDAR_DATABASE_URL required")
    url = make_url(target)
    assert url.get_backend_name() == "postgresql" and url.host in {"localhost", "127.0.0.1"}
    assert url.database == "guiyi_calendar_isolated_test" and url.port and url.port != 5432
    schema = "calendar_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as conn:
        assert conn.scalar(text("SELECT current_database()")) == "guiyi_calendar_isolated_test"
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = create_engine(url, connect_args={"options": "-csearch_path=" + schema})
    try:
        seed(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


@pytest.fixture
def evidence(tmp_path):
    path = tmp_path / "response.json"
    path.write_text(json.dumps({"source_response": RESPONSE}))
    return path


def test_real_readonly_then_single_commit_is_visible(db, evidence):
    observed = []
    def check(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT trading_calendars"):
            observed.append(connection.exec_driver_sql("SHOW transaction_read_only").scalar())
    event.listen(db, "before_cursor_execute", check)
    code, plan = invoke(db, evidence)
    event.remove(db, "before_cursor_execute", check)
    assert code == 0 and observed == ["on"]
    assert invoke(db, evidence, "--apply", "--expected-plan-sha256", plan["plan_sha256"])[0] == 0
    with Session(db) as reader:
        assert reader.get(TradingCalendar, 46796).has_night_session is True


@pytest.mark.parametrize("phase", ["before_flush", "after_commit"])
def test_real_commit_failure_semantics(db, evidence, phase):
    _, plan = invoke(db, evidence)
    with Session(db) as writer:
        def fail(*_):
            raise RuntimeError("isolated failure")
        event.listen(writer, phase, fail)
        with pytest.raises(CorrectionError) as caught:
            apply_correction(writer, plan, expected_plan_sha256=plan["plan_sha256"])
    assert caught.value.code.endswith("COMMIT_OUTCOME_UNKNOWN" if phase == "after_commit" else "APPLY_FAILED")
    with Session(db) as reader:
        assert reader.get(TradingCalendar, 46796).has_night_session is (phase == "after_commit")


def test_real_locks_block_other_metadata_writers_and_hide_pending_update(db, evidence):
    from sqlalchemy.exc import OperationalError
    _, plan = invoke(db, evidence)
    observed = []
    with Session(db) as writer:
        def pending(*_):
            with Session(db) as reader:
                observed.append(reader.get(TradingCalendar, 46796).has_night_session)
            with db.connect() as other:
                other.exec_driver_sql("SET LOCAL lock_timeout = '100ms'")
                with pytest.raises(OperationalError):
                    other.execute(text("UPDATE trading_calendars SET remark = 'unexpected' WHERE id = :id"),
                                  {"id": 46796})
                other.rollback()
        event.listen(writer, "after_flush", pending)
        apply_correction(writer, plan, expected_plan_sha256=plan["plan_sha256"])
    assert observed == [False]


def test_real_stale_hash_and_changed_source_cannot_write(db, evidence):
    _, plan = invoke(db, evidence)
    with Session(db) as other:
        other.get(TradingCalendar, 46796).remark = "changed"
        other.commit()
    with Session(db) as writer, pytest.raises(CorrectionError):
        apply_correction(writer, plan, expected_plan_sha256=plan["plan_sha256"])
    with Session(db) as reader:
        assert reader.get(TradingCalendar, 46796).has_night_session is False
    assert hashlib.sha256(evidence.read_bytes()).hexdigest() == plan["evidence"]["file_sha256"]


def test_same_schema_identical_rows_on_replaced_table_invalidate_plan(db, evidence):
    _, plan = invoke(db, evidence)
    with db.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE replacement_calendar (LIKE trading_calendars INCLUDING ALL)")
        connection.exec_driver_sql("INSERT INTO replacement_calendar SELECT * FROM trading_calendars")
        connection.exec_driver_sql("ALTER TABLE trading_calendars RENAME TO former_calendar")
        connection.exec_driver_sql("ALTER TABLE replacement_calendar RENAME TO trading_calendars")
    with Session(db) as writer, pytest.raises(CorrectionError, match="PLAN_DRIFT"):
        apply_correction(writer, plan, expected_plan_sha256=plan["plan_sha256"])
    with Session(db) as reader:
        assert reader.get(TradingCalendar, 46796).has_night_session is False


def test_schema_translation_cannot_bypass_lock_target(db, evidence):
    from app.market_data.au_calendar_correction import plan_correction, read_evidence
    source = read_evidence(str(evidence), hashlib.sha256(evidence.read_bytes()).hexdigest())
    with db.connect() as connection:
        schema = connection.scalar(text("SELECT current_schema()"))
    translated = db.execution_options(schema_translate_map={None: schema})
    with Session(translated) as reader, pytest.raises(CorrectionError, match="SCHEMA_TRANSLATION_UNSUPPORTED"):
        plan_correction(reader, source)
