from datetime import UTC, date, datetime
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256

import pytest
from sqlalchemy import event, select

from guiyi_quant.reference_trading import BoundaryReason, ReferenceBoundary, reduce_reference

from app.db.readonly import readonly_transaction
from app.reference_trading.contracts import SnapshotIdentity
from app.reference_trading.query import HistoricalReferenceQuery, QueryConflict
from app.reference_trading.presentation import envelope, presentation_point
from app.reference_trading.models import ReferenceActionRow, ReferenceBatch, ReferenceTradeRow
from tests.reference_trading.test_repository import _digest, _open_batch, _seed_repository
from tests.reference_trading.test_repository_snapshots import _close_batch


def test_sql_page_preserves_old_snapshot_and_cutoff_without_future_exit() -> None:
    repository, factory, stream, revision, manifest, seed = _seed_repository()
    opened = repository.commit_batch(seed, _open_batch(stream, revision, manifest, seed))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    repository.publish_revision(stream.stream_id, revision, token.row_version, _digest(manifest))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    closed = repository.commit_batch(token, _close_batch(repository, stream, revision, manifest, token))
    early = datetime(2026, 9, 19, 23, tzinfo=UTC)
    with factory() as session, readonly_transaction(session):
        old = repository.query_historical_trades(
            session, SnapshotIdentity(stream.stream_id, revision, opened.seq),
            since=date(2026, 9, 19), through=date(2026, 9, 20), cutoff=early, limit=1,
        )
        cutoff = repository.query_historical_trades(
            session, SnapshotIdentity(stream.stream_id, revision, closed.seq),
            since=date(2026, 9, 19), through=date(2026, 9, 20), cutoff=early, limit=1,
        )
        now = repository.query_historical_trades(
            session, SnapshotIdentity(stream.stream_id, revision, closed.seq),
            since=date(2026, 9, 19), through=date(2026, 9, 20), cutoff=None, limit=1,
        )
    assert old.items[0].status.value == cutoff.items[0].status.value == "OPEN"
    assert cutoff.items[0].mark_reference_price == Decimal("3501.123456789")
    assert cutoff.items[0].exit_bar_end is None
    assert now.items[0].status.value == "CLOSED"
    with factory() as session, readonly_transaction(session):
        initial = repository.query_historical_trades(
            session, SnapshotIdentity(stream.stream_id, revision, closed.seq),
            since=date(2026, 9, 20), through=date(2026, 9, 20),
            cutoff=None, limit=1,
        )
    assert len(initial.items) == 1
    assert initial.items[0].entry_trading_day < date(2026, 9, 20)


def test_historical_page_preserves_closed_trade_as_initial_before_window() -> None:
    repository, factory, stream, revision, manifest, seed = _seed_repository()
    repository.commit_batch(seed, _open_batch(stream, revision, manifest, seed))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    repository.publish_revision(stream.stream_id, revision, token.row_version, _digest(manifest))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    closed = repository.commit_batch(token, _close_batch(repository, stream, revision, manifest, token))
    with factory() as session, readonly_transaction(session):
        page = repository.query_historical_trades(
            session, SnapshotIdentity(stream.stream_id, revision, closed.seq),
            since=date(2026, 9, 21), through=date(2026, 9, 22),
            cutoff=None, limit=50,
        )
    assert len(page.items) == 1
    assert page.items[0].status.value == "CLOSED"


def test_historical_summary_preserves_interruption_as_initial_before_window(monkeypatch) -> None:
    repository, factory, stream, revision, manifest, seed = _seed_repository()
    repository.commit_batch(seed, _open_batch(stream, revision, manifest, seed, evidence={
        "presentation_v1": envelope([presentation_point(
            kind="trade_identity", trading_day=date(2026, 9, 19),
            formula_versions=("v1",),
            value={"source_action_id": "build-1", "public_trade_id": "public-one"},
        )]),
    }))
    token, opened = repository.load_checkpoint(stream.stream_id, revision)
    boundary = ReferenceBoundary(
        stream, BoundaryReason.ROLLOVER, "RB2610", "owner-1", "calc-1",
        datetime(2026, 9, 20, 7, tzinfo=UTC), date(2026, 9, 20),
    )
    transition = reduce_reference(opened.reference_state, boundaries=(boundary,))
    close_batch = _close_batch(repository, stream, revision, manifest, token)
    interrupted = replace(
        close_batch,
        source_actions=(), transitions=(transition,),
        checkpoint=replace(close_batch.checkpoint, reference_state=transition.state),
        source_evidence={"presentation_v1": envelope([])},
    )
    repository.commit_batch(token, interrupted)
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    repository.publish_revision(stream.stream_id, revision, token.row_version, _digest(manifest))
    monkeypatch.setattr(HistoricalReferenceQuery, "_registered", staticmethod(lambda _row: True))
    query = HistoricalReferenceQuery(factory)
    params = {"since": date(2026, 9, 21), "through": date(2026, 9, 22)}
    assert len(query.trades(stream.stream_id, **params)["items"]) == 1
    assert query.summary(stream.stream_id, **params)["initial_count"] == 1


def test_hint_known_later_than_cutoff_is_not_visible(monkeypatch) -> None:
    repository, factory, stream, revision, manifest, seed = _seed_repository()
    evidence = {"presentation_v1": envelope([
        presentation_point(
            kind="hint", trading_day=date(2026, 9, 19),
            formula_versions=("v1",),
            value={"bar_end": datetime(2026, 9, 19, 8, tzinfo=UTC),
                   "known_at": datetime(2026, 9, 20, 8, tzinfo=UTC)},
        ),
    ])}
    repository.commit_batch(seed, _open_batch(stream, revision, manifest, seed, evidence=evidence))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    repository.publish_revision(stream.stream_id, revision, token.row_version, _digest(manifest))
    monkeypatch.setattr(HistoricalReferenceQuery, "_registered", staticmethod(lambda _row: True))
    page = HistoricalReferenceQuery(factory).signals(
        stream.stream_id, since=date(2026, 9, 19), through=date(2026, 9, 20),
        cutoff=datetime(2026, 9, 19, 23, tzinfo=UTC), point_kind="hint",
    )
    assert page["items"] == []


def test_published_legacy_batch_without_presentation_is_unreadable(monkeypatch) -> None:
    repository, factory, stream, revision, manifest, seed = _seed_repository()
    repository.commit_batch(seed, _open_batch(stream, revision, manifest, seed))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    repository.publish_revision(stream.stream_id, revision, token.row_version, _digest(manifest))
    monkeypatch.setattr(HistoricalReferenceQuery, "_registered", staticmethod(lambda _row: True))
    with pytest.raises(QueryConflict, match="PRESENTATION_NOT_MATERIALIZED"):
        HistoricalReferenceQuery(factory).signals(
            stream.stream_id, since=date(2026, 9, 19), through=date(2026, 9, 19),
        )
    with pytest.raises(QueryConflict, match="PRESENTATION_NOT_MATERIALIZED"):
        HistoricalReferenceQuery(factory).trades(
            stream.stream_id, since=date(2026, 9, 19), through=date(2026, 9, 19),
        )
    with pytest.raises(QueryConflict, match="PRESENTATION_NOT_MATERIALIZED"):
        HistoricalReferenceQuery(factory).summary(
            stream.stream_id, since=date(2026, 9, 19), through=date(2026, 9, 19),
        )


def test_boundary_selection_uses_exchange_trading_day_not_utc_date() -> None:
    repository, factory, stream, revision, manifest, seed = _seed_repository()
    evidence = {"presentation_v1": envelope([
        presentation_point(
            kind="boundary", trading_day=date(2026, 9, 21),
            formula_versions=("v1",),
            value={"bar_end": datetime(2026, 9, 18, 23, tzinfo=UTC),
                   "physical_contract": "RB2610", "owner_segment_id": "owner-1",
                   "calculation_segment_id": "calc-1"},
        ),
    ])}
    committed = repository.commit_batch(
        seed, _open_batch(stream, revision, manifest, seed, evidence=evidence),
    )
    with factory() as session, readonly_transaction(session):
        keys = HistoricalReferenceQuery._boundary_keys(
            session, SnapshotIdentity(stream.stream_id, revision, committed.seq),
            date(2026, 9, 21), date(2026, 9, 21), None,
        )
    assert keys == {("RB2610", "owner-1", "calc-1")}


def test_summary_uses_full_window_and_same_snapshot(monkeypatch) -> None:
    repository, factory, stream, revision, manifest, seed = _seed_repository()
    evidence = {"bar": "fixture-1", "presentation_v1": envelope([
        presentation_point(
            kind="trade_identity",
            value={"source_action_id": "build-1", "public_trade_id": "public-one"},
            trading_day=date(2026, 9, 19), formula_versions=("v1",),
        ),
    ])}
    repository.commit_batch(seed, _open_batch(stream, revision, manifest, seed, evidence=evidence))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    repository.publish_revision(stream.stream_id, revision, token.row_version, _digest(manifest))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    closing = _close_batch(repository, stream, revision, manifest, token)
    repository.commit_batch(token, replace(
        closing, source_evidence={"presentation_v1": envelope([])},
    ))
    monkeypatch.setattr(HistoricalReferenceQuery, "_registered", staticmethod(lambda _row: True))
    query = HistoricalReferenceQuery(factory)
    params = {"since": date(2026, 9, 19), "through": date(2026, 9, 20)}
    page = query.trades(stream.stream_id, limit=1, **params)
    summary = query.summary(stream.stream_id, snapshot_token=page["snapshot"], **params)
    assert summary["closed_count"] == 1
    assert summary["sum_return_percentage_points"] == str(page["items"][0]["reference_return"])
    assert summary["snapshot"] == page["snapshot"]
    later = {"since": date(2026, 9, 21), "through": date(2026, 9, 22)}
    assert len(query.trades(stream.stream_id, **later)["items"]) == 1
    later_summary = query.summary(stream.stream_id, **later)
    assert later_summary["closed_count"] == 0
    assert later_summary["initial_count"] == 1


def test_large_history_page_uses_sql_limit_without_mark_n_plus_one() -> None:
    repository, factory, stream, revision, manifest, seed = _seed_repository()
    with factory.begin() as session:
        batch = session.scalar(select(ReferenceBatch).where(
            ReferenceBatch.stream_id == stream.stream_id,
            ReferenceBatch.revision_id == revision,
            ReferenceBatch.kind == "seed_seal",
        ))
        assert batch is not None
        for index in range(300):
            entry_pk = sha256(f"entry-{index}".encode()).hexdigest()
            exit_pk = sha256(f"exit-{index}".encode()).hexdigest()
            entry_day = date(2026, 1, 1)
            entry_time = datetime(2026, 1, 1, 7, tzinfo=UTC)
            exit_time = datetime(2026, 1, 2, 7, tzinfo=UTC)
            for action_pk, kind, source, instant, day, link in (
                (entry_pk, "OPEN_LONG", f"entry-{index}", entry_time, entry_day, None),
                (exit_pk, "CLOSE", f"exit-{index}", exit_time, date(2026, 1, 2), f"entry-{index}"),
            ):
                session.add(ReferenceActionRow(
                    action_pk=action_pk, stream_id=stream.stream_id,
                    origin_revision_id=revision, batch_revision_id=revision,
                    source_action_id=source, recording_mode="historical_replay",
                    kind=kind, sequence=0, physical_contract="RB2610",
                    owner_segment_id="owner-1", calculation_segment_id="calc-1",
                    bar_end=instant, trading_day=day, observed_at=None,
                    reference_price=Decimal("100"), reference_price_type="fixture",
                    entry_source_action_id=link, batch_id=batch.batch_id, batch_seq=1,
                ))
            session.add(ReferenceTradeRow(
                stream_id=stream.stream_id, revision_id=revision,
                trade_id=f"reference-trade:{index:064x}", valid_from_seq=1,
                valid_to_seq=None, entry_action_pk=entry_pk, exit_action_pk=exit_pk,
                side="LONG", status="CLOSED", physical_contract="RB2610",
                owner_segment_id="owner-1", calculation_segment_id="calc-1",
                entry_bar_end=entry_time, entry_trading_day=entry_day,
                entry_reference_price=Decimal("100"), exit_bar_end=exit_time,
                exit_trading_day=date(2026, 1, 2), exit_reference_price=Decimal("101"),
                reference_return=Decimal("1"), holding_bars=1,
                effective_bar_end=exit_time, observed_at=None,
            ))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    repository.publish_revision(stream.stream_id, revision, token.row_version, _digest(manifest))
    statements: list[str] = []
    engine = factory.kw["bind"]

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with factory() as session, readonly_transaction(session):
            page = repository.query_historical_trades(
                session, SnapshotIdentity(stream.stream_id, revision, 1),
                since=date(2026, 1, 1), through=date(2026, 1, 2),
                cutoff=None, limit=2,
            )
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(page.items) == 2 and page.next_key is not None
    trade_selects = [value for value in statements if "reference_trades" in value]
    assert len(trade_selects) == 1
    assert "LIMIT" in trade_selects[0].upper()
    assert len(statements) <= 5
