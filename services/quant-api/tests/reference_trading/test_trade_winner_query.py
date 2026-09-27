"""Eligible-version and bounded SQL winner regressions; isolated SQLite only."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from sqlalchemy import select
from app.reference_trading.models import ReferenceActionRow, ReferenceBatch, ReferenceTradeRow, ReferenceStream
from sqlalchemy import event
from sqlalchemy.sql import visitors
from sqlalchemy.sql.elements import Over
from sqlalchemy.sql.selectable import ScalarSelect
from app.db.readonly import readonly_transaction
from app.reference_trading.contracts import SnapshotIdentity
from tests.reference_trading.test_repository import _digest, _open_batch, _seed_repository
from tests.reference_trading.test_repository_snapshots import _close_batch


def test_complete_trade_winner_select_does_not_execute_a_window_aggregate():
    repository, factory, stream, revision, manifest, seed = _seed_repository()
    repository.commit_batch(seed, _open_batch(stream, revision, manifest, seed))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    repository.publish_revision(stream.stream_id, revision, token.row_version, _digest(manifest))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    closed = repository.commit_batch(token, _close_batch(repository, stream, revision, manifest, token))
    engine = factory.kw["bind"]
    winner_statements = []

    def record(_connection, _cursor, _statement, _parameters, context, _many):
        statement = getattr(context.compiled, "statement", None)
        if statement is None:
            return
        descriptions = getattr(statement, "column_descriptions", ())
        if any(getattr(item.get("entity"), "__tablename__", None) == "reference_trades" for item in descriptions):
            winner_statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with factory() as session, readonly_transaction(session):
            page = repository.query_historical_trades(
                session, SnapshotIdentity(stream.stream_id, revision, closed.seq),
                since=date(2026, 9, 19), through=date(2026, 9, 20),
                cutoff=datetime(2026, 9, 20, 23, tzinfo=UTC), limit=1000,
                entry_since_only=True, complete_budget=1000,
            )
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(page.items) == 1 and page.items[0].status.value == "CLOSED"
    assert len(winner_statements) == 1
    # EXPLAIN places WindowAgg under a nested loop, risking repeated work;
    # no ANALYZE proved actual loop counts. Avoid this operator in the trade path,
    # independently of how the equivalent eligible winner is implemented.
    nodes = tuple(visitors.iterate(winner_statements[0]))
    assert not any(isinstance(node, Over) for node in nodes)
    # The per-trade lookup must be bounded, rather than repeatedly aggregating
    # all eligible trades under the observed nested-loop plan.
    assert any(isinstance(node, ScalarSelect) and node.element._limit_clause is not None
               and node.element._limit_clause.value == 1 for node in nodes)


def _versions():
    repository, factory, stream, revision, manifest, seed = _seed_repository()
    opened = repository.commit_batch(seed, _open_batch(stream, revision, manifest, seed))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    repository.publish_revision(stream.stream_id, revision, token.row_version, _digest(manifest))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    closed = repository.commit_batch(token, _close_batch(repository, stream, revision, manifest, token))
    return repository, factory, stream, revision, opened, closed


def _page(repository, factory, stream, revision, seq, **overrides):
    arguments = dict(since=date(2026, 9, 19), through=date(2026, 9, 21), cutoff=None, limit=20)
    arguments.update(overrides)
    with factory() as session, readonly_transaction(session):
        return repository.query_historical_trades(session, SnapshotIdentity(stream.stream_id, revision, seq), **arguments)


def test_complete_winner_preserves_snapshot_cutoff_and_exact_prices():
    repository, factory, stream, revision, opened, closed = _versions()
    old = _page(repository, factory, stream, revision, opened.seq, complete_budget=20)
    early = _page(repository, factory, stream, revision, closed.seq,
                  cutoff=datetime(2026, 9, 19, 23, tzinfo=UTC), complete_budget=20)
    latest = _page(repository, factory, stream, revision, closed.seq, complete_budget=20)
    assert old.items[0].status.value == early.items[0].status.value == "OPEN"
    assert early.items[0].exit_bar_end is None
    assert early.items[0].mark_reference_price == Decimal("3501.123456789")
    assert latest.items[0].status.value == "CLOSED"
    assert latest.items[0].exit_reference_price == Decimal("3510.987654321")


def test_outer_window_does_not_resurrect_old_open_version():
    repository, factory, stream, revision, _opened, closed = _versions()
    with factory.begin() as session:
        stored = session.get(ReferenceStream, stream.stream_id)
        stored.recording_mode = "forward_observation"
        stored.observation_policy_version = "forward-flat-v1"
    page = _page(repository, factory, stream, revision, closed.seq,
                 since=date(2026, 9, 21), forward=True)
    assert page.items == ()


def test_forward_eligibility_requires_action_and_batch_observation_before_cutoff():
    repository, factory, stream, revision, opened, _closed = _versions()
    cutoff = datetime(2026, 9, 19, 23, tzinfo=UTC)
    with factory.begin() as session:
        stored = session.get(ReferenceStream, stream.stream_id)
        stored.recording_mode = "forward_observation"
        stored.observation_policy_version = "forward-flat-v1"
        action = session.scalar(select(ReferenceActionRow).where(ReferenceActionRow.source_action_id == "build-1"))
        batch = session.scalar(select(ReferenceBatch).where(ReferenceBatch.stream_id == stream.stream_id, ReferenceBatch.revision_id == revision, ReferenceBatch.seq == opened.seq))
        action.observed_at = cutoff - timedelta(seconds=1)
        batch.observed_at = cutoff + timedelta(seconds=1)
    assert _page(repository, factory, stream, revision, opened.seq, cutoff=cutoff, forward=True).items == ()
    with factory.begin() as session:
        batch = session.scalar(select(ReferenceBatch).where(ReferenceBatch.stream_id == stream.stream_id, ReferenceBatch.revision_id == revision, ReferenceBatch.seq == opened.seq))
        batch.observed_at = cutoff - timedelta(seconds=1)
    assert len(_page(repository, factory, stream, revision, opened.seq, cutoff=cutoff, forward=True).items) == 1
    with factory.begin() as session:
        action = session.scalar(select(ReferenceActionRow).where(ReferenceActionRow.source_action_id == "build-1"))
        action.observed_at = cutoff + timedelta(seconds=1)
    assert _page(repository, factory, stream, revision, opened.seq, cutoff=cutoff, forward=True).items == ()


def test_versioned_winners_keep_same_bar_keyset_cursor_and_limit():
    repository, factory, stream, revision, _opened, closed = _versions()
    with factory.begin() as session:
        originals = session.scalars(select(ReferenceTradeRow)).all()
        for original in originals:
            values = {column.name: getattr(original, column.name) for column in ReferenceTradeRow.__table__.columns}
            values["trade_id"] = "reference-trade:" + "f" * 64
            session.add(ReferenceTradeRow(**values))
    first = _page(repository, factory, stream, revision, closed.seq, limit=1)
    second = _page(repository, factory, stream, revision, closed.seq, limit=1, after_key=first.next_key)
    assert len(first.items) == len(second.items) == 1
    assert first.next_key is not None and second.next_key is None
    assert first.items[0].reference_trade_id != second.items[0].reference_trade_id
    assert first.items[0].status.value == second.items[0].status.value == "CLOSED"
