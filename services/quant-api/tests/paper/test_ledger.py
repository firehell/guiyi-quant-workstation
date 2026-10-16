"""Independent Paper storage: never use production DATABASE_URL."""
from datetime import UTC, datetime
import os

import pytest

from app.paper.ledger import PaperLedger, PaperLedgerError


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://postgres@127.0.0.1:5432/guiyi",
    "postgresql+psycopg://postgres@remote.example:15462/guiyi_paper_test",
    "sqlite:///:memory:",
    "postgresql+psycopg://postgres@127.0.0.1:15462/production",
    "postgresql+psycopg://postgres@127.0.0.1/guiyi_paper_test",
    "invalid-url",
])
def test_production_or_ambiguous_database_rejected_before_connection(url):
    with pytest.raises(PaperLedgerError, match="PAPER_DATABASE_SCOPE_INVALID"):
        PaperLedger(url)


@pytest.fixture
def ledger():
    url = os.environ.get("GUIYI_ISOLATED_PAPER_DATABASE_URL")
    if not url:
        pytest.skip("dedicated isolated PostgreSQL URL required")
    if not url.endswith("/guiyi_paper_isolated_test"):
        pytest.fail("test database identity rejected")
    result = PaperLedger(url)
    result.initialize_schema()
    yield result
    result.close()


def _initialize(identity="initialize"):
    from guiyi_quant.paper import Initialize, PaperProfile
    return Initialize(identity, datetime(2026, 10, 9, 0, tzinfo=UTC),
                      PaperProfile("jm-pilot-v1", "newow_dual_fusion_causal_target_v1"))


def test_atomic_command_idempotency_and_replay(ledger):
    from uuid import uuid4
    account = "test_" + uuid4().hex
    command = _initialize()
    first = ledger.execute(account, command, expected_sequence=0)
    duplicate = ledger.execute(account, command, expected_sequence=0)
    assert first.event_count > 0
    assert duplicate.duplicate
    assert duplicate.last_sequence == first.last_sequence
    state, sequence = ledger.load(account)
    assert str(state.cash) == "50000"
    assert sequence == first.last_sequence
    assert ledger.verify(account)["verified"] is True


def test_same_command_id_different_payload_cannot_mutate(ledger):
    from dataclasses import replace
    from uuid import uuid4
    account = "test_" + uuid4().hex
    command = _initialize()
    first = ledger.execute(account, command)
    with pytest.raises(PaperLedgerError, match="PAPER_COMMAND_CONFLICT"):
        ledger.execute(account, replace(command, at=datetime(2026, 10, 10, tzinfo=UTC)))
    assert ledger.load(account)[1] == first.last_sequence


def test_concurrent_same_command_is_one_commit(ledger):
    from concurrent.futures import ThreadPoolExecutor
    from uuid import uuid4
    account = "test_" + uuid4().hex
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: ledger.execute(account, _initialize()), range(2)))
    assert sorted(r.duplicate for r in results) == [False, True]
    assert results[0].last_sequence == results[1].last_sequence


def test_sql_updates_and_deletes_cannot_rewrite_events(ledger):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from uuid import uuid4
    account = "test_" + uuid4().hex
    ledger.execute(account, _initialize())
    for statement in (
        "UPDATE paper_events SET event_hash = 'tampered' WHERE account_id=:account",
        "DELETE FROM paper_events WHERE account_id=:account",
        "DELETE FROM paper_commands WHERE account_id=:account",
    ):
        with pytest.raises(DBAPIError):
            with ledger.engine.begin() as connection:
                connection.execute(text(statement), {"account": account})
    assert ledger.verify(account)["verified"] is True


def test_batch_failure_rolls_back_previous_commands(ledger):
    from dataclasses import replace
    from uuid import uuid4
    account = "test_" + uuid4().hex
    command = _initialize()
    with pytest.raises(PaperLedgerError, match="PAPER_COMMAND_CONFLICT"):
        ledger.execute_many(account, (command, replace(command, at=datetime(2026, 10, 10, tzinfo=UTC))))
    assert ledger.lookup(account, command) is None


def test_readback_distinguishes_unknown_commit_from_absence(ledger):
    from uuid import uuid4
    account = "test_" + uuid4().hex
    command = _initialize()
    assert ledger.lookup(account, command) is None
    committed = ledger.execute(account, command)
    readback = ledger.lookup(account, command)
    assert readback.last_sequence == committed.last_sequence
    assert readback.duplicate


def test_stale_sequence_cannot_append_new_command(ledger):
    from guiyi_quant.paper import BeginTradingDay
    from uuid import uuid4
    account = "test_" + uuid4().hex
    committed = ledger.execute(account, _initialize())
    command = BeginTradingDay("day", datetime(2026, 10, 9, 1, tzinfo=UTC),
                              "2026-10-09", 0, None, "ledger-reconciled")
    with pytest.raises(PaperLedgerError, match="PAPER_SEQUENCE_CONFLICT"):
        ledger.execute(account, command, expected_sequence=0)
    assert ledger.lookup(account, command) is None
    assert ledger.load(account)[1] == committed.last_sequence


def test_injected_receipt_without_events_is_rejected(ledger):
    from sqlalchemy import text
    from uuid import uuid4
    account = "test_" + uuid4().hex
    ledger.execute(account, _initialize())
    with ledger.engine.begin() as connection:
        connection.execute(text("""INSERT INTO paper_commands
            (account_id,command_id,command_hash,first_sequence,last_sequence,event_count)
            VALUES (:account,'ghost',:hash,2,2,1)"""),
            {"account": account, "hash": "0" * 64})
    with pytest.raises(PaperLedgerError, match="PAPER_LEDGER_CORRUPT"):
        ledger.load(account)


def test_connection_loss_does_not_retry_or_claim_commit(ledger, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from uuid import uuid4
    account = "test_" + uuid4().hex
    calls = []
    def failed_begin():
        calls.append(1)
        raise OperationalError("private SQL", {}, Exception("private endpoint"),
                               connection_invalidated=True)
    monkeypatch.setattr(ledger.engine, "begin", failed_begin)
    with pytest.raises(PaperLedgerError, match="^PAPER_COMMIT_OUTCOME_UNKNOWN$"):
        ledger.execute(account, _initialize())
    assert calls == [1]


def test_lost_ack_after_real_commit_recovers_by_readback(ledger, monkeypatch):
    from contextlib import contextmanager
    from sqlalchemy.exc import OperationalError
    from uuid import uuid4
    account = "test_" + uuid4().hex
    command = _initialize()
    original_begin = ledger.engine.begin
    calls = []
    @contextmanager
    def commit_then_lose_ack():
        calls.append(1)
        with original_begin() as connection:
            yield connection
        raise OperationalError("private SQL", {}, Exception("lost acknowledgement"),
                               connection_invalidated=True)
    monkeypatch.setattr(ledger.engine, "begin", commit_then_lose_ack)
    with pytest.raises(PaperLedgerError, match="^PAPER_COMMIT_OUTCOME_UNKNOWN$"):
        ledger.execute(account, command)
    assert calls == [1]
    result = ledger.lookup(account, command)
    assert result is not None and result.duplicate and result.event_count == 1
    assert ledger.verify(account)["sequence"] == result.last_sequence
