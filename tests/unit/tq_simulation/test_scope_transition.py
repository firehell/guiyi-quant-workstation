"""Offline old-account transition, preserving owned orders and native reconciliation."""
from dataclasses import replace
from datetime import timedelta
from guiyi_quant.htdy_execution import OrderReport
from guiyi_quant.htdy_account_execution import model as m, codec
from guiyi_quant.htdy_account_execution.reducer import start
from guiyi_quant.htdy_account_execution.scope import scope_status, trading_scope
from guiyi_quant.htdy_account_execution.store import LocalStore
from guiyi_quant.trading_universe import TRADING_PRODUCTS, TRADING_SCOPE_VERSION
from test_execution import A, T, rb, fact

ALLOWED = tuple(p.upper() for p in TRADING_PRODUCTS)
# Original account universe from v1.16.139:data/universe/operational_products.txt.
BASELINE = tuple((
    'A AG AL AO AP AU B BU BZ C CF CJ CU EB EC EG FG FU HC I J JD JM L LC LH M MA NI OI '
    'P PB PD PF PG PK PL PP PR PS PT PX RB RM RS RU SA SC SF SH SI SM SN SR SS TA UR V Y ZN'
).split())


def input_for(product, at, *, can_trade=True):
    base = fact(at)
    contract = product + ('2612' if product == 'NI' else '2701')
    return m.TqKqExecutionInput(replace(base.instrument, product=product, contract=contract),
        replace(base.session, contract=contract, can_trade=can_trade),
        replace(base.quote, contract=contract))


def native_readback(state, at):
    return replace(rb(at, positions=state.positions, used='1000' if state.positions else '0',
        trades=tuple(f.trade_id for f in state.fills)),
        snapshot=replace(rb(at).snapshot, positions=state.positions,
            orders=tuple(OrderReport(o.order_id, o.status) for o in state.orders)))


def fill_order(store, order, at):
    f = m.TqKqFill('tq-trade:' + order.order_id, order.order_id, A, order.contract,
        at, at, order.price, None, 1, order.order_id, 'native:' + order.order_id, 'f' * 64)
    store.execute('fill:' + order.order_id, f)
    state = store.current()
    store.execute('rb:' + at.isoformat(), native_readback(state, at))


def old_account(tmp_path):
    assert len(BASELINE) == 60
    store = LocalStore(tmp_path / 'account.sqlite', start(A, BASELINE, T, rb()),
        execution_identity='TQKQ:' + A + ':htdy_tqkq_v1')
    at = T
    for product in ('AP', 'OI', 'PG', 'NI', 'SS'):
        at += timedelta(seconds=10)
        f = input_for(product, at)
        store.execute('owner:' + product, m.Owner(product, f.instrument.contract, at, 'owner:' + product))
        s = m.Signal('signal:' + product, product, f.instrument.contract, at - timedelta(microseconds=1), at, None, ('buy',), 'b' * 64)
        store.execute('signal:' + product, m.TqKqObservedSignalV1(s, at))
        at += timedelta(seconds=1)
        tx = store.execute('open:' + product, m.TqKqTick(at, (input_for(product, at),), True))
        assert len(tx.effects) == 1
        at += timedelta(seconds=1)
        fill_order(store, tx.effects[0].order, at)
    return store, at


def transition(store, at):
    cmd = m.TqKqTradingScopeV1(at, ALLOWED, TRADING_SCOPE_VERSION)
    return store.execute('scope', cmd)


def test_old_sixty_scope_retires_four_positions_preserves_oi_and_journal(tmp_path):
    store, at = old_account(tmp_path)
    before = store.current()
    payload = codec.checkpoint(before)
    assert codec.checkpoint(codec.load(payload)) == payload
    at += timedelta(seconds=1)
    tx = transition(store, at)
    state = tx.state
    assert not tx.effects
    assert state.positions == before.positions
    assert state.orders == before.orders and state.fills == before.fills
    assert state.audit[:-1] == before.audit
    assert state.receipts[:-1] == before.receipts
    assert len(state.products) == 60
    assert next(p for p in state.products if p.product == 'OI') == next(p for p in before.products if p.product == 'OI')
    assert {p.product for p in state.products if p.must_close} == {'AP', 'PG', 'NI', 'SS'}
    assert scope_status(state)['status'] == 'FLATTEN_PENDING'
    assert transition(store, at).duplicate
    assert store.replay() == state
    store.close()
    reopened = LocalStore(tmp_path / 'account.sqlite', execution_identity='TQKQ:' + A + ':htdy_tqkq_v1')
    assert trading_scope(reopened.current()) == tx.state.audit[-1].command
    assert scope_status(reopened.current())['status'] == 'FLATTEN_PENDING'
    assert reopened.replay() == state
    reopened.close()


def test_closed_session_partial_closes_restart_and_native_flat_gate(tmp_path):
    store, at = old_account(tmp_path)
    at += timedelta(seconds=1)
    transition(store, at)
    at += timedelta(seconds=1)
    assert not store.execute('closed', m.TqKqTick(at,
        tuple(input_for(p, at, can_trade=False) for p in ('AP', 'PG', 'NI', 'SS')), True)).effects
    for product in ('AP', 'PG', 'NI', 'SS'):
        at += timedelta(seconds=1)
        tx = store.execute('close:' + product, m.TqKqTick(at, (input_for(product, at),), True))
        assert len(tx.effects) == 1
        order = tx.effects[0].order
        assert order.product == product and order.offset == 'CLOSE' and order.side == 'SELL'
        # A pending/unknown result blocks every later submission; no blind retry.
        assert not store.execute('pending:' + product, m.TqKqTick(at,
            tuple(input_for(p, at) for p in ('AP', 'PG', 'NI', 'SS')), True)).effects
        assert scope_status(store.current())['status'] == 'FLATTEN_PENDING'
        at += timedelta(seconds=1)
        fill_order(store, order, at)
    state = store.current()
    assert state.positions == (m.Position('OI', 'OI2701', 1),)
    assert scope_status(state, at)['status'] == 'ACTIVE'
    assert scope_status(state, state.readback.valid_until)['status'] == 'FLATTEN_PENDING'
    assert not scope_status(state, state.readback.valid_until)['native_readback_verified']
    assert store.replay() == state
    store.close()


def test_recovery_and_new_signals_never_reactivate_retired_openings(tmp_path):
    store, at = old_account(tmp_path)
    at += timedelta(seconds=1)
    transition(store, at)
    at += timedelta(seconds=1)
    state = store.current()
    proofs = tuple(m.RecoveryInput(p.product, p.owner, 1, at - timedelta(microseconds=1), 'recover:' + p.product)
        for p in state.products if p.owner)
    store.execute('recover', m.Recover(native_readback(state, at), proofs))
    at += timedelta(seconds=1)
    s = m.Signal('late-outside', 'AP', 'AP2701', at - timedelta(microseconds=1), at, None, ('buy',), 'b' * 64)
    tx = store.execute('late', m.TqKqObservedSignalV1(s, at))
    assert tx.state.audit[-1].reason == 'TQ_PRODUCT_RETIRED'
    p = next(p for p in tx.state.products if p.product == 'AP')
    assert p.desired == 0 and p.must_close and p.opening_consumed
    assert not any(e.order.offset == 'OPEN' for e in store.execute('tick', m.TqKqTick(at,
        (input_for('AP', at),), True)).effects)
    assert store.replay() == store.current()
    store.close()


def test_retired_working_open_cancel_unknown_and_late_fill_stay_owned(tmp_path):
    store, at = old_account(tmp_path)
    at += timedelta(seconds=1)
    f = input_for('AU', at)
    store.execute('au-owner', m.Owner('AU', f.instrument.contract, at, 'au-owner'))
    s = m.Signal('au-signal', 'AU', f.instrument.contract, at - timedelta(microseconds=1), at, None, ('buy',), 'b' * 64)
    store.execute('au-signal', m.TqKqObservedSignalV1(s, at))
    at += timedelta(seconds=1)
    tx = store.execute('au-open', m.TqKqTick(at, (input_for('AU', at),), True))
    order = tx.effects[0].order
    at += timedelta(seconds=1)
    store.execute('accepted', m.OrderUpdate(A, order.order_id, at, 'native-working', 'WORKING', at))
    store.execute('working-rb', native_readback(store.current(), at))
    at += timedelta(seconds=1)
    transition(store, at)
    retired_order = next(o for o in store.current().orders if o.order_id == order.order_id)
    assert retired_order.cancel_required
    at += timedelta(seconds=1)
    cancelled = store.execute('cancel', m.TqKqTick(at, (input_for('AU', at),), True))
    assert [e.kind for e in cancelled.effects] == ['CANCEL']
    at += timedelta(seconds=1)
    store.execute('unknown', m.OrderUpdate(A, order.order_id, at, 'native-unknown', 'UNKNOWN'))
    assert not store.execute('unknown-tick', m.TqKqTick(at, (input_for('AP', at), input_for('AU', at)), True)).effects
    reservation = next(r for r in store.current().reservations if r.order_id == order.order_id)
    assert not reservation.released
    at += timedelta(seconds=1)
    fill_order(store, order, at)
    assert next(p for p in store.current().products if p.product == 'AU').must_close
    assert store.current().phase == 'RECOVERY_REQUIRED'
    at += timedelta(seconds=1)
    store.execute('unknown-recovered', m.Recover(native_readback(store.current(), at), ()))
    at += timedelta(seconds=1)
    close = store.execute('au-close', m.TqKqTick(at, (input_for('AU', at),), True))
    assert len(close.effects) == 1 and close.effects[0].order.offset == 'CLOSE'
    assert close.effects[0].order.contract == order.contract
    assert scope_status(store.current())['status'] == 'FLATTEN_PENDING'
    assert store.replay() == store.current()
    store.close()


def test_scope_command_during_restart_does_not_grant_native_recovery(tmp_path):
    store, at = old_account(tmp_path)
    old_state = store.current()
    store.close()
    store = LocalStore(tmp_path / 'account.sqlite', execution_identity='TQKQ:' + A + ':htdy_tqkq_v1')
    at += timedelta(seconds=1)
    tx = transition(store, at)
    assert tx.state.phase == 'RECOVERY_REQUIRED' and not tx.state.readback_valid
    assert not tx.effects
    assert tx.state.orders == old_state.orders and tx.state.positions == old_state.positions
    assert store.replay() == tx.state
    store.close()


def test_worker_inspect_reopens_old_sixty_account_with_outside_native_positions(monkeypatch, tmp_path, capsys):
    """Full inspect/recover accepts partial 16 authority and retains old mappings."""
    from datetime import datetime, UTC
    from test_worker import host
    from test_execution import snapshot, Transport
    from guiyi_quant import trading_universe
    from guiyi_quant.tq_simulation import worker
    from guiyi_quant.tq_simulation.journal import Journal
    from guiyi_quant.tq_simulation.runtime import read_private

    base, _ = host(monkeypatch, tmp_path, mode='observe')
    monkeypatch.setattr(trading_universe, 'TRADING_PRODUCTS', tuple(p.lower() for p in ALLOWED))
    folder = base / 'accounts' / A
    folder.mkdir(parents=True, mode=0o700)
    folder.parent.chmod(0o700)
    store, at = old_account(folder)
    original = store.current()
    store.close()
    journal = Journal(folder / 'dispatch.sqlite', A)
    native_orders, native_trades, native_positions = [], [], []

    def symbol_for(product, contract):
        exchange = 'SHFE' if product in {'NI', 'SS', 'RB'} else 'CZCE' if product in {'AP', 'OI'} else 'DCE'
        return exchange + '.' + contract.lower()

    for order in original.orders:
        symbol = symbol_for(order.product, order.contract)
        exchange, instrument = symbol.split('.')
        journal.event('symbol', dict(symbol=symbol, product=order.product, contract=order.contract), at)
        native_id = journal.claim('SUBMIT', order.order_id,
            dict(symbol=symbol, side=order.side, offset='OPEN', volume=1, price=str(order.price), profile='htdy_tqkq_v1'), at)
        native_orders.append(dict(order_id=native_id, exchange_id=exchange, instrument_id=instrument,
            state='FILLED', volume_orign=1, volume_left=0, direction=order.side, offset='OPEN',
            price_type='LIMIT', limit_price=str(order.price)))
        fill = next(f for f in original.fills if f.order_id == order.order_id)
        native_trades.append(dict(order_id=native_id, trade_id=order.order_id,
            exchange_id=exchange, instrument_id=instrument, direction=order.side, offset='OPEN',
            volume=1, price=str(fill.price), trade_date_time=int(fill.filled_at.timestamp()) * 1_000_000_000))
        native_positions.append(dict(symbol=symbol, pos_long_today=0, pos_long_his=1,
            pos_short_today=0, pos_short_his=0))
    journal.close()

    class Gateway(Transport):
        reconnection_required = False
        def __init__(self, *_):
            super().__init__()
        def update(self, *_):
            pass
        def snapshot(self, now):
            s = snapshot(now, orders=native_orders, trades=native_trades, positions=native_positions)
            s['account']['margin'] = '1000'
            return s
        def close(self):
            assert self.calls == []

    class Market:
        products = ALLOWED
        def __init__(self, *_):
            pass
        def close(self):
            pass
        def poll(self, state, contracts, *, inspect):
            assert inspect
            now = datetime.now(UTC)
            requested = dict((p, p+'2701') for p in ALLOWED)
            requested.update(contracts)
            return dict(issues={}, signals=[], facts=[dict(product=p, contract=contract,
                trading_day='2026-11-19', source_id='authority:'+p,
                session=codec.encode(replace(input_for(p, now).session, can_trade=False))) for p, contract in requested.items()],
                recovery=[codec.encode(m.RecoveryInput('OI', 'OI2701', 1, at, 'oi-proof'))])

    monkeypatch.setattr(worker, 'Gateway', Gateway)
    monkeypatch.setattr(worker, 'Market', Market)
    monkeypatch.setattr(worker, 'bind_symbol', lambda g,c,f: c.bind_symbol(symbol_for(f['product'], f['contract']), f['product'], f['contract']))
    assert worker.run(base / 'config.json', inspect=True) == 0
    report = __import__('json').loads(capsys.readouterr().out)
    assert report['ready_for_start'] is True and report['position_count'] == 5
    assert report['products'] == 16
    assert read_private(base/'preflight.json')['ready_for_start'] is True
    # A persisted hold must never turn an inspect invocation into a scope write.
    from guiyi_quant.tq_simulation.runtime import write_private
    write_private(base/'hold.json', {'code': 'TQ_POSITION_MISMATCH'})
    assert worker.run(base/'config.json', inspect=True) == 0
    held_report = __import__('json').loads(capsys.readouterr().out)
    assert held_report['ready_for_start'] is False
    assert type(LocalStore.inspect(folder/'account.sqlite')) is m.State
    (base/'hold.json').unlink()
    inspected = LocalStore.inspect(folder / 'account.sqlite')
    assert type(inspected) is m.State  # inspect never applies the scope mutation.
    assert inspected.positions == original.positions
    assert inspected.orders == original.orders and inspected.fills == original.fills
    assert inspected.phase == 'READY'
    assert {'AP', 'PG', 'NI', 'SS'} <= set(inspected.blocked_products)
    assert inspected.audit[:len(original.audit)] == original.audit
    from guiyi_quant.tq_simulation.controller import Controller
    resumed = Controller(folder, A, ALLOWED, None)
    resumed.apply_trading_scope(datetime.now(UTC))
    migrated = resumed.store.current()
    assert type(migrated) is m.TqKqScopedStateV1
    assert {p.product for p in migrated.products if p.must_close} == {'AP', 'PG', 'NI', 'SS'}
    assert migrated.positions == original.positions
    assert all(symbol in resumed.symbols for symbol in (p['symbol'] for p in native_positions))
    assert migrated.audit[:len(inspected.audit)] == inspected.audit
    assert resumed.store.replay() == migrated
    resumed.close()
    # A later release/restart must also pass preflight while original outside
    # positions are waiting for their Session. Their extra close mappings do not
    # widen the sixteen-product opening coverage or disqualify that coverage.
    assert worker.run(base / 'config.json', inspect=True) == 0
    again = __import__('json').loads(capsys.readouterr().out)
    assert again['ready_for_start'] is True
    assert again['mapped_contracts'] == again['products'] == 16
    assert again['position_count'] == 5 and not again['issues']
    reopened = LocalStore.inspect(folder / 'account.sqlite')
    assert reopened.scope_command == migrated.scope_command
    assert reopened.positions == original.positions
    assert reopened.audit[:len(migrated.audit)] == migrated.audit


def test_next_trading_day_close_needs_session_quote_not_a_new_h1_signal(tmp_path):
    """Yesterday's native orders/trades may disappear after account day rollover."""
    store, at = old_account(tmp_path)
    at += timedelta(hours=3)
    transition(store, at)
    at += timedelta(seconds=1)
    assert not store.execute('closed-day', m.TqKqTick(at,
        (input_for('AP', at, can_trade=False),), True)).effects
    before_signals = store.current().signals
    store.close()
    store = LocalStore(tmp_path / 'account.sqlite', execution_identity='TQKQ:' + A + ':htdy_tqkq_v1')
    at += timedelta(days=1)
    state = store.current()
    # New native trading-day collections omit all yesterday's reconciled IDs.
    fresh = rb(at, positions=state.positions, used='1000', orders=(), trades=())
    store.execute('new-day-readback', m.Recover(fresh, ()))
    assert 'AP' in store.current().blocked_products  # no new strategy/H1 proof
    at += timedelta(seconds=1)
    close = store.execute('new-day-owner-close', m.TqKqTick(at,
        (input_for('AP', at),), True))
    assert len(close.effects) == 1
    order = close.effects[0].order
    assert (order.product, order.contract, order.offset, order.side) == ('AP', 'AP2701', 'CLOSE', 'SELL')
    assert store.current().signals == before_signals
    assert store.current().positions == state.positions
    assert store.replay() == store.current()
    store.close()


def test_new_unreconciled_native_snapshot_revokes_scope_and_position_verification(tmp_path):
    import pytest
    from guiyi_quant.tq_simulation.controller import Controller
    from guiyi_quant.tq_simulation.monitor import projection
    from test_execution import snapshot
    store = LocalStore(tmp_path/'account.sqlite', start(A, BASELINE, T, rb()),
                       execution_identity='TQKQ:'+A+':htdy_tqkq_v1')
    transition(store, T+timedelta(seconds=1))
    store.close()
    c = Controller(tmp_path, A, ALLOWED, None)
    now = T+timedelta(seconds=2)
    original = snapshot(now)
    readback = c.synchronize(original, now)
    c.recover(readback, ())
    good = projection(c, original, now, mode='trade', opening=True)['overview']
    assert good['trading_scope']['status'] == 'ACTIVE'
    c.bind_symbol('CZCE.AP701', 'AP', 'AP2701')
    changed = snapshot(now+timedelta(seconds=1), positions=[dict(symbol='CZCE.AP701',
        pos_long_today=1,pos_long_his=0,pos_short_today=0,pos_short_his=0)])
    with pytest.raises(ValueError, match='TQ_POSITION_MISMATCH'):
        c.synchronize(changed, now+timedelta(seconds=1))
    for code in (None, 'TQ_POSITION_MISMATCH'):
        view = projection(c, changed, now+timedelta(seconds=1), mode='trade',
                          opening=True, code=code)['overview']
        assert view['trading_scope']['status'] == 'FLATTEN_PENDING'
        assert not view['trading_scope']['native_readback_verified']
        assert view['readback_status'] == 'unverified'
        assert not view['position_projection_complete']
        assert view['positions'][0]['status'] == 'UNVERIFIED'
        assert view['observer']['executable_product_count'] == 0
    c.close()
