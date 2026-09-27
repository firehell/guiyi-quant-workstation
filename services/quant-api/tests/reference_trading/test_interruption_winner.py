"""Interruption winner contracts in isolated SQLite, not real-data evidence."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
import pytest
from sqlalchemy import event, select
from sqlalchemy.sql import visitors
from sqlalchemy.sql.elements import Over
from app.db.readonly import readonly_transaction
from app.reference_trading.contracts import SnapshotIdentity
from app.reference_trading.models import ReferenceTradeRow, ReferenceMarkRow
from app.reference_trading.query import HistoricalReferenceQuery, QueryConflict
from tests.reference_trading.test_trade_winner_query import _versions


def _interrupted():
    repository, factory, stream, revision, opened, closed = _versions()
    with factory.begin() as session:
        last = session.scalar(select(ReferenceTradeRow).where(ReferenceTradeRow.valid_from_seq == closed.seq))
        last.status = 'DATA_INTERRUPTED'
        for field in ('exit_action_pk','exit_bar_end','exit_trading_day','exit_reference_price','reference_return'):
            setattr(last,field,None)
        trade_id = last.trade_id
    item = SimpleNamespace(reference_trade_id=trade_id, status=SimpleNamespace(value='DATA_INTERRUPTED'))
    return factory, stream, revision, opened, closed, item


def _details(factory, stream, revision, seq, items, cutoff=None):
    with factory() as session, readonly_transaction(session):
        return HistoricalReferenceQuery._interruption_details(session, SnapshotIdentity(stream.stream_id, revision, seq), items, cutoff)


def test_interruption_trade_lookup_avoids_unbounded_window():
    factory, stream, revision, _opened, closed, item = _interrupted()
    statements=[];engine=factory.kw['bind']
    def capture(_c,_cur,_sql,_params,context,_many):
        statement=getattr(context.compiled,'statement',None)
        if any(i.get('entity') is ReferenceTradeRow for i in getattr(statement,'column_descriptions',())):statements.append(statement)
    event.listen(engine,'before_cursor_execute',capture)
    try:
        assert item.reference_trade_id in _details(factory,stream,revision,closed.seq,[item])
    finally:event.remove(engine,'before_cursor_execute',capture)
    assert len(statements)==1
    assert not any(isinstance(node,Over) for node in visitors.iterate(statements[0]))


def test_interruption_old_snapshot_and_future_effective_version_do_not_resurrect_status():
    factory, stream, revision, opened, closed, item = _interrupted()
    with pytest.raises(QueryConflict,match='TRADE_VERSION_CONFLICT'):
        _details(factory,stream,revision,opened.seq,[item])
    with pytest.raises(QueryConflict,match='TRADE_VERSION_CONFLICT'):
        _details(factory,stream,revision,closed.seq,[item],datetime(2026,9,19,23,tzinfo=UTC))
    expected=datetime(2026,9,20,7,tzinfo=UTC)
    assert datetime.fromisoformat(_details(factory,stream,revision,closed.seq,[item])[item.reference_trade_id]['interrupted_at']).replace(tzinfo=UTC)==expected
    with factory.begin() as session:
        last=session.scalar(select(ReferenceTradeRow).where(ReferenceTradeRow.valid_from_seq==closed.seq))
        values={c.name:getattr(last,c.name) for c in ReferenceTradeRow.__table__.columns}
        last.valid_to_seq=closed.seq+1
        values.update(valid_from_seq=closed.seq+1,valid_to_seq=None,status='OPEN',effective_bar_end=expected+timedelta(days=1),observed_at=expected+timedelta(days=20))
        session.add(ReferenceTradeRow(**values))
    assert item.reference_trade_id in _details(factory,stream,revision,closed.seq,[item])
    assert item.reference_trade_id in _details(factory,stream,revision,closed.seq+1,[item],expected)
    # This function's own contract filters effective time, not observed_at.
    with pytest.raises(QueryConflict,match='TRADE_VERSION_CONFLICT'):
        _details(factory,stream,revision,closed.seq+1,[item],expected+timedelta(days=2))


def test_interruption_many_ids_keep_each_identity_and_latest_version():
    factory,stream,revision,_opened,closed,item=_interrupted()
    items=[item]
    with factory.begin() as session:
        rows=session.scalars(select(ReferenceTradeRow)).all()
        for index in range(1004):
            trade_id=f'reference-trade:{index:064x}'
            items.append(SimpleNamespace(reference_trade_id=trade_id,status=SimpleNamespace(value='DATA_INTERRUPTED')))
            for row in rows:
                values={c.name:getattr(row,c.name) for c in ReferenceTradeRow.__table__.columns}
                values['trade_id']=trade_id
                session.add(ReferenceTradeRow(**values))
    result=_details(factory,stream,revision,closed.seq,items)
    assert set(result)=={item.reference_trade_id for item in items}
    assert len(result)==1005
    assert len({entry['interrupted_at'] for entry in result.values()})==1


def test_interruption_missing_identity_conflicts_and_closed_items_are_not_requested():
    factory,stream,revision,_opened,closed,item=_interrupted()
    assert _details(factory,stream,revision,closed.seq,[SimpleNamespace(reference_trade_id='ignored',status=SimpleNamespace(value='CLOSED'))])=={}
    missing=SimpleNamespace(reference_trade_id='missing',status=item.status)
    with pytest.raises(QueryConflict,match='TRADE_VERSION_CONFLICT'):
        _details(factory,stream,revision,closed.seq,[missing])


def test_interruption_latest_mark_respects_bar_order_seq_cutoff_and_decimal():
    factory,stream,revision,opened,closed,item=_interrupted()
    with factory.begin() as session:
        original=session.scalar(select(ReferenceMarkRow))
        assert original is not None
        base={c.name:getattr(original,c.name) for c in ReferenceMarkRow.__table__.columns}
        instant=datetime(2026,9,20,7,tzinfo=UTC)
        for seq,bar,price in ((closed.seq,instant,Decimal('3502.123456789')), (closed.seq+1,instant,Decimal('3503.123456789')), (closed.seq+1,instant+timedelta(days=1),Decimal('3504.123456789'))):
            values={**base,'batch_seq':seq,'bar_end':bar,'reference_price':price,'observed_at':instant+timedelta(days=30)}
            session.add(ReferenceMarkRow(**values))
    def price(seq,cutoff=None):return Decimal(_details(factory,stream,revision,seq,[item],cutoff)[item.reference_trade_id]['prior_mark_reference_price'])
    assert price(closed.seq)==Decimal('3502.123456789')
    assert price(closed.seq+1,instant)==Decimal('3503.123456789')
    assert price(closed.seq+1)==Decimal('3504.123456789')
    statements=[];engine=factory.kw['bind']
    def capture(_c,_cur,_sql,_params,context,_many):
        statement=getattr(context.compiled,'statement',None)
        if any(getattr(i.get('entity'),'__tablename__',None)=='reference_marks' for i in getattr(statement,'column_descriptions',())):statements.append(statement)
    event.listen(engine,'before_cursor_execute',capture)
    try:_details(factory,stream,revision,closed.seq,[item])
    finally:event.remove(engine,'before_cursor_execute',capture)
    assert len(statements)==1
    # A single projected ranking preserves bar-first semantics without joining
    # the full mark table back into a nested loop.
    assert not statements[0]._setup_joins
