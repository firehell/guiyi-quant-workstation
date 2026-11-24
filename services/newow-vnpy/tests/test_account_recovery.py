from dataclasses import replace
from datetime import timedelta

import pytest

from gateway import NativeFill, NativeOrder, OrderStatus, Position
from host import TradingHost


@pytest.mark.parametrize('boundary', ('before_commit', 'after_claim', 'after_send'))
def test_crash_boundaries(scenario, monkeypatch, boundary):
    end = scenario.signal_end + timedelta(seconds=5)
    with scenario.host() as host:
        scenario.prepare_builds(host, ('RB',))
        if boundary == 'before_commit':
            make_intent = host._make_intent

            def abort(*args, **kwargs):
                make_intent(*args, **kwargs)
                raise SystemExit

            monkeypatch.setattr(host, '_make_intent', abort)
        elif boundary == 'after_claim':
            def abort(_request):
                raise SystemExit
            monkeypatch.setattr(scenario.gateway, 'send', abort)
        else:
            def abort(_request):
                raise SystemExit
            scenario.gateway.on_send = abort
        with pytest.raises(SystemExit):
            host.advance(end)
    with scenario.host() as resumed:
        empty = scenario.snapshot(at=end + timedelta(seconds=1))
        assert resumed.reconcile(empty) is (boundary == 'before_commit')
        resumed.advance(end + timedelta(seconds=6))
        assert len(scenario.gateway.sends) == (boundary == 'after_send')
        events = resumed.store.projection('orders')['data']
        if boundary == 'before_commit':
            assert not events
        else:
            assert [event['state'] for event in events] == ['PLANNED', 'CLAIMED', 'UNKNOWN']
            assert events[-1]['reserved'] == '100'


def test_restart_requires_exact_order_and_fill_prefix(scenario):
    end = scenario.signal_end + timedelta(seconds=5)
    with scenario.host() as host:
        scenario.prepare_builds(host, ('RB',))
        host.advance(end)
    order = NativeOrder('SHFE', 'RB2701', scenario.day, 'fixture-1', 1, 1, OrderStatus.FILLED)
    fill = NativeFill('SHFE', 'RB2701', scenario.day, order.native_id, 'trade-1', 1, scenario.D(100), end)
    position = Position('SHFE', 'RB2701', 'RB', 1, 1, 0)
    with scenario.host() as host:
        assert not host.reconcile(scenario.snapshot(at=end, positions=(position,), orders=(order,)))
        assert host.status()['reason'] == 'P5_ORDER_FILL_TOTAL_UNVERIFIED'
        assert host.reconcile(scenario.snapshot(at=end, positions=(position,), orders=(order,), fills=(fill,)))
        host.advance(end + timedelta(seconds=8))
        assert len(scenario.gateway.sends) == 1
        assert host.store.projection('orders')['data'][-1]['reserved'] == '0'


def test_unknown_receipt_does_not_match_a_similar_native_order(scenario):
    scenario.gateway.on_send = lambda _: None
    end = scenario.signal_end + timedelta(seconds=5)
    with scenario.host() as host:
        scenario.prepare_builds(host, ('RB',))
        host.advance(end)
    foreign = NativeOrder('SHFE', 'RB2701', scenario.day, 'unbound', 1, 0, OrderStatus.ACTIVE)
    with scenario.host() as host:
        assert not host.reconcile(scenario.snapshot(at=end, orders=(foreign,)))
        host.advance(end + timedelta(seconds=1))
        assert len(scenario.gateway.sends) == 1
        intents = [r for r in host.store.projection('orders')['data'] if r['kind'] == 'order_intent']
        assert intents[-1]['reserved'] == '100' and intents[-1]['state'] == 'UNKNOWN'


def test_partial_fill_clear_cancels_then_closes_only_native_position(scenario):
    build = scenario.signal_end + timedelta(seconds=5)
    with scenario.host() as host:
        scenario.prepare_builds(host, ('RB',), cash='310', maximum_lots=3)
        host.advance(build)
        partial = NativeOrder('SHFE', 'RB2701', scenario.day, 'fixture-1', 3, 1, OrderStatus.PARTIAL)
        fill = NativeFill('SHFE', 'RB2701', scenario.day, partial.native_id, 'trade-1', 1, scenario.D(100), build)
        position = Position('SHFE', 'RB2701', 'RB', 1, 1, 0)
        host.callback(partial, generation=scenario.generation, sequence=1, known_at=build)
        host.callback(fill, generation=scenario.generation, sequence=2, known_at=build)
        host.callback(fill, generation=scenario.generation, sequence=3, known_at=build)
        assert host.reconcile(scenario.snapshot(at=build, cash='210', margin='100', through=3,
                                                positions=(position,), orders=(partial,), fills=(fill,)))
        clear = scenario.signal_end + timedelta(minutes=5)
        scenario.quoted(host, 'RB', at=clear)
        assert scenario.live(host, 'RB', end=clear) == 'ACCEPTED'
        assert len(scenario.gateway.cancels) == 1
        assert len(scenario.gateway.sends) == 1
        terminal = replace(partial, status=OrderStatus.CANCELLED, filled=2)
        late = replace(fill, native_trade_id='trade-2', occurred_at=clear + timedelta(seconds=3))
        host.callback(terminal, generation=scenario.generation, sequence=4, known_at=clear + timedelta(seconds=3))
        assert not host.reconcile(scenario.snapshot(at=clear + timedelta(seconds=5), through=4,
                                                    positions=(position,), orders=(terminal,), fills=(fill,)))
        host.advance(clear + timedelta(seconds=5))
        assert len(scenario.gateway.cancels) == len(scenario.gateway.sends) == 1
        host.callback(late, generation=scenario.generation, sequence=5, known_at=clear + timedelta(seconds=5))
        host.callback(partial, generation=scenario.generation, sequence=6, known_at=clear + timedelta(seconds=5))
        tail = clear + timedelta(seconds=5)
        assert host.reconcile(scenario.snapshot(at=tail, cash='110', margin='200', through=6,
                                                positions=(replace(position, quantity=2, today=2),),
                                                orders=(terminal,), fills=(fill, late)))
        host.advance(tail)
        assert [item['offset'] for item in scenario.gateway.sends] == ['OPEN', 'CLOSETODAY']
        assert [item['quantity'] for item in scenario.gateway.sends] == [3, 2]
        assert len(host.store.projection('fills')['data']) == 2
        assert scenario.live(host, 'RB', end=clear) == 'DUPLICATE'
        assert len(scenario.gateway.sends) == 2


def test_old_month_keeps_owner_and_subscription_when_draining(scenario):
    with scenario.host() as host:
        host.activate(scenario.scope(('RB',)), expected_revision=None, supported=('RB',))
        old = Position('SHFE', 'RB2701', 'RB', 1, 0, 0)
        assert host.reconcile(scenario.snapshot(positions=(old,)))
        for contract in ('RB2701', 'RB2705'):
            host.register_policy(scenario.policy('RB', contract=contract))
            market = scenario.market('RB', contract=contract)
            scenario.warm(host, market, count=9 if contract.endswith('01') else 10)
            scenario.quoted(host, 'RB', contract=contract)
            end = scenario.signal_end if contract.endswith('01') else scenario.signal_end + timedelta(minutes=5)
            scenario.live(host, 'RB', end=end, market=market)
        host.activate(scenario.scope((), revision='r2'), expected_revision='r1', supported=('RB',))
        assert host.status()['owners']['rb']['phase'] == 'DRAINING'
        assert host.status()['owners']['rb']['contract'] == 'RB2705'
        assert host.status()['subscriptions'] == {
            'physical_count': 2, 'contracts': {'rb': ['RB2701', 'RB2705']},
        }
        with pytest.raises(ValueError, match='P5_DRAIN_UNSETTLED'):
            host.retire('RB', expected_revision='r2', new_revision='r3', now=end)
        with pytest.raises(ValueError, match='P5_OWNER_UNSETTLED'):
            host.activate(scenario.scope(('RB',), revision='r3', strategy='trend'), expected_revision='r2',
                          supported=('RB',), now=end)
        host.advance(end + timedelta(seconds=5))
        assert not scenario.gateway.sends and not scenario.gateway.cancels
        assert host.store.projection('positions')['data'][0]['contract'] == 'RB2701'


def test_callback_gap_and_identity_conflict_keep_host_blocked(scenario):
    with scenario.host() as host:
        assert host.reconcile(scenario.snapshot())
        order = NativeOrder('SHFE', 'RB2701', scenario.day, 'order-a', 1, 0, OrderStatus.ACTIVE)
        host.callback(order, generation=scenario.generation, sequence=2, known_at=scenario.start)
        assert host.status()['reason'] == 'P5_CALLBACK_GAP'
        assert not host.reconcile(scenario.snapshot())
        assert not scenario.gateway.sends


def test_restart_mismatched_profile_cannot_write(scenario):
    with scenario.host():
        pass
    changed = replace(scenario.config, market_generation='another-market')
    with pytest.raises(ValueError, match='P5_HOST_CONFIGURATION_CONFLICT'):
        with TradingHost(scenario.database, changed, scenario.gateway):
            pass


def test_projection_pages_stay_within_a_snapshot(scenario):
    with scenario.host() as host:
        assert host.store.projection('account')['data'] is None
        scenario.prepare_builds(host, ('RB',))
        page = host.store.projection('decisions', limit=2)
        first = {d['sequence'] for d in page['data']}
        host.advance(scenario.signal_end + timedelta(seconds=5))
        assert host.store.projection('decisions')['through'] > page['through']
        old = host.store.projection('decisions', after=page['next_after'], through=page['through'])
        assert all(d['sequence'] <= page['through'] and d['sequence'] not in first for d in old['data'])


def test_clear_during_reconciliation_keeps_existing_open_obligation(scenario):
    with scenario.host() as host:
        scenario.prepare_builds(host, ('RB',), cash='310', maximum_lots=3)
        build = scenario.signal_end + timedelta(seconds=5)
        host.advance(build)
        order = NativeOrder('SHFE', 'RB2701', scenario.day, 'fixture-1', 3, 1, OrderStatus.PARTIAL)
        host.callback(order, generation=scenario.generation, sequence=1, known_at=build)
        assert host.status()['status'] == 'RECONCILING'
        clear = scenario.signal_end + timedelta(minutes=5)
        scenario.quoted(host, 'RB', at=clear)
        scenario.live(host, 'RB', end=clear)
        assert len(scenario.gateway.cancels) == 1
        assert len(scenario.gateway.sends) == 1
        fill = NativeFill('SHFE', 'RB2701', scenario.day, 'fixture-1', 'trade-1', 1, scenario.D(100), build)
        terminal = replace(order, status=OrderStatus.CANCELLED)
        position = Position('SHFE', 'RB2701', 'RB', 1, 0, 0)
        tail = clear + timedelta(seconds=5)
        assert host.reconcile(scenario.snapshot(at=tail, through=1, positions=(position,), orders=(terminal,), fills=(fill,)))
        host.advance(tail)
        assert [(i['offset'], i['quantity']) for i in scenario.gateway.sends] == [('OPEN', 3), ('CLOSEYESTERDAY', 1)]


def test_unproven_flat_snapshot_does_not_erase_known_position(scenario):
    with scenario.host() as host:
        host.activate(scenario.scope(('RB',)), expected_revision=None, supported=('RB',))
        old = Position('SHFE', 'RB2701', 'RB', 1, 0, 0)
        assert host.reconcile(scenario.snapshot(positions=(old,)))
        assert not host.reconcile(scenario.snapshot(at=scenario.start + timedelta(seconds=1)))
        assert host.status()['reason'] == 'P5_POSITION_READBACK_MISMATCH'
        assert host.store.projection('positions')['data'][0]['quantity'] == 1


def test_restart_rejects_complete_readback_from_previous_process(scenario):
    with scenario.host() as host:
        previous = scenario.snapshot()
        assert host.reconcile(previous)
    with scenario.host() as host:
        assert not host.reconcile(previous)
        assert host.status()['status'] == 'RECONCILING'
        assert not host.reconcile(replace(previous, readback_id=scenario.readback_id))
        assert host.reconcile(scenario.snapshot(at=scenario.start + timedelta(seconds=1)))


def test_as_of_prefix_excludes_later_native_readback_and_local_intent(scenario, monkeypatch):
    import host as module

    with scenario.host() as host:
        host.activate(scenario.scope(('RB',)), expected_revision=None, supported=('RB',))
        assert host.reconcile(scenario.snapshot())
        host.register_policy(scenario.policy('RB'))
        scenario.warm(host, scenario.market('RB'))
        observed = scenario.signal_end + timedelta(seconds=2)
        after = observed + timedelta(seconds=1)
        assert host.reconcile(scenario.snapshot(at=after, cash='500'))
        with host.store.transaction() as (_state, journal):
            journal.record('orders', 'fixture-future', {'id': 'future', 'product': 'rb', 'contract': 'RB2701',
                                                       'state': 'CLAIMED'}, at=after)
        seen = []
        consume = module.consume_completed

        def capture(market, core, item, context, **kwargs):
            seen.append(context)
            return consume(market, core, item, context, **kwargs)

        monkeypatch.setattr(module, 'consume_completed', capture)
        assert scenario.live(host, 'RB', now=after) == 'ACCEPTED'
        assert seen[0].account_as_of == scenario.start
        assert seen[0].unsettled_contracts == ()
        assert seen[0].position == scenario.D(0)


def test_close_legs_recheck_frozen_inventory_immediately_before_send(scenario, monkeypatch):
    with scenario.host() as host:
        host.activate(scenario.scope(('RB',)), expected_revision=None, supported=('RB',))
        host.register_policy(scenario.policy('RB'))
        position = Position('SHFE', 'RB2701', 'RB', 2, 1, 0)
        assert host.reconcile(scenario.snapshot(positions=(position,)))
        scenario.warm(host, scenario.market('RB'))
        scenario.live(host, 'RB')
        clear = scenario.signal_end + timedelta(minutes=5)
        scenario.quoted(host, 'RB', at=clear)
        send = host._dispatch
        changed = False

        def freeze_before_claim(key, now):
            nonlocal changed
            if not changed:
                changed = True
                assert host.reconcile(scenario.snapshot(at=now, positions=(replace(position, frozen=1),)))
            send(key, now)

        monkeypatch.setattr(host, '_dispatch', freeze_before_claim)
        scenario.live(host, 'RB', end=clear)
        host.advance(clear + timedelta(seconds=3))
        orders = host.store.projection('orders')['data']
        assert {o['offset'] for o in orders if o['state'] == 'PLANNED'} == {'CLOSETODAY', 'CLOSEYESTERDAY'}
        assert sum(o.get('reason') == 'P5_CLOSE_QUANTITY_CHANGED' for o in orders) == 2
        assert not scenario.gateway.sends


def test_explicit_old_month_management_never_opens_or_exceeds_permit(scenario):
    from risk import ManagementPermit

    with scenario.host() as host:
        host.activate(scenario.scope(('RB',)), expected_revision=None, supported=('RB',))
        position = Position('SHFE', 'RB2701', 'RB', 2, 0, 0)
        assert host.reconcile(scenario.snapshot(positions=(position,)))
        host.register_policy(scenario.policy('RB'))
        latest = scenario.signal_end
        scenario.live(host, 'RB', end=latest, market=scenario.market('RB', contract='RB2705'))
        scenario.quoted(host, 'RB', at=latest, contract='RB2701')
        permit = ManagementPermit('fixture-old-month-reduce', 'r1', 'RB', 'SHFE', 'RB2701', scenario.day,
                                  (scenario.start, scenario.start + timedelta(hours=3)), latest,
                                  latest + timedelta(seconds=10), 1)
        now = latest + timedelta(seconds=3)
        host.manage_existing(permit, now=now)
        host.manage_existing(permit, now=now)
        assert [(i['contract'], i['offset'], i['quantity']) for i in scenario.gateway.sends] == [
            ('RB2701', 'CLOSEYESTERDAY', 1),
        ]
        assert scenario.gateway.sends[0]['decision']['management_ref'] == permit.reference


@pytest.mark.parametrize('cause', ('disconnect', 'readback'))
def test_a_build_known_during_unverified_account_cannot_be_retroactively_sent(scenario, cause):
    with scenario.host() as host:
        host.activate(scenario.scope(('RB',)), expected_revision=None, supported=('RB',))
        assert host.reconcile(scenario.snapshot())
        host.register_policy(scenario.policy('RB'))
        scenario.warm(host, scenario.market('RB'))
        scenario.quoted(host, 'RB')
        if cause == 'disconnect':
            host.block('P5_DISCONNECTED', known_at=scenario.signal_end)
        else:
            scenario.readback_id = host.begin_readback(generation=scenario.generation, trading_day=scenario.day,
                                                       started_at=scenario.signal_end)
        # Deliver the signal after the account resumes, but preserve its original availability.
        again = scenario.signal_end + timedelta(seconds=3)
        assert host.reconcile(scenario.snapshot(at=again))
        assert scenario.live(host, 'RB', now=again) == 'ACCEPTED'
        host.advance(scenario.signal_end + timedelta(seconds=5))
        decisions = host.store.projection('decisions')['data']
        assert any(d['main_action'] == 'BUILD' and d['reason'] == 'ACCOUNT_PREFIX_UNVERIFIED' for d in decisions)
        assert not scenario.gateway.sends
