from datetime import timedelta

import pytest

from host import TradingHost


def test_ready_host_requires_complete_native_readback(scenario):
    with TradingHost(scenario.database, scenario.config, scenario.gateway) as host:
        assert host.status()['status'] == 'RECONCILING'
        scenario.readback_id = host.begin_readback(generation=scenario.generation, trading_day=scenario.day)
        assert not host.reconcile(scenario.snapshot(sections=('account', 'positions', 'orders')))
        assert host.status()['status'] == 'RECONCILING'
        assert host.reconcile(scenario.snapshot())
        assert host.status()['status'] == 'READY'


def test_batch_winner_survives_reverse_arrival(scenario):
    outcome = []
    for products in [('RB', 'HC'), ('HC', 'RB')]:
        with scenario.host(reset=True) as host:
            scenario.prepare_builds(host, products)
            assert len(scenario.gateway.sends) == 0
            host.advance(scenario.signal_end + timedelta(seconds=4))
            assert len(scenario.gateway.sends) == 1
            outcome.append(scenario.gateway.sends[0]['product'])
    assert outcome == ['hc', 'hc']


def test_second_writer_cannot_acquire_same_account(scenario):
    with scenario.host():
        with pytest.raises(RuntimeError, match='P5_WRITER_BUSY'):
            with TradingHost(scenario.database, scenario.config, scenario.gateway):
                pass


def test_capacity_keeps_draining_product_until_fresh_readback(scenario):
    from string import ascii_lowercase

    symbols = [f'z{letter}' for letter in ascii_lowercase[:21]]
    with scenario.host() as host:
        host.activate(scenario.scope(symbols[:20]), expected_revision=None, supported=symbols)
        assert host.reconcile(scenario.snapshot())
        host.activate(scenario.scope(symbols[1:20], revision='r2'), expected_revision='r1', supported=symbols)
        assert host.status()['owners'][symbols[0]]['phase'] == 'DRAINING'
        with pytest.raises(ValueError, match='V2_SCOPE_CAPACITY_EXCEEDED'):
            host.activate(scenario.scope(symbols[1:], revision='r3'), expected_revision='r2', supported=symbols)
        assert host.status()['revision'] == 'r2'
        with pytest.raises(ValueError, match='P5_DRAIN_UNSETTLED'):
            host.retire(symbols[0], expected_revision='r2', new_revision='r3', now=scenario.start)
        now = scenario.start + timedelta(seconds=1)
        assert host.reconcile(scenario.snapshot(at=now))
        host.retire(symbols[0], expected_revision='r2', new_revision='r3', now=now)
        host.activate(scenario.scope(symbols[1:], revision='r4'), expected_revision='r3', supported=symbols)
        assert len(host.status()['owners']) == 20
        assert not scenario.gateway.sends and not scenario.gateway.cancels


def test_two_configurations_cannot_both_claim_one_revision(scenario):
    from concurrent.futures import ThreadPoolExecutor

    with scenario.host() as host, ThreadPoolExecutor(max_workers=2) as pool:
        def try_config(index):
            try:
                host.activate(scenario.scope(('RB',), revision=f'r{index}', strategy=('trend', 'oscillation')[index]),
                              expected_revision=None, supported=('RB',))
                return True
            except ValueError as error:
                assert str(error) == 'P5_SCOPE_REVISION_CONFLICT'
                return False
        assert sorted(pool.map(try_config, range(2))) == [False, True]


@pytest.mark.parametrize('missing', ('account', 'policy', 'risk', 'valuation', 'daily_loss'))
def test_missing_execution_facts_do_not_create_risk(scenario, missing):
    from dataclasses import replace
    from gateway import Position

    if missing == 'risk':
        scenario.config = replace(scenario.config, limits=None)
    with scenario.host() as host:
        host.activate(scenario.scope(('HC', 'RB')), expected_revision=None, supported=('HC', 'RB'))
        snapshot = scenario.snapshot(account=missing != 'account', loss='20' if missing == 'daily_loss' else '0',
                                     positions=(Position('SHFE', 'RB2701', 'RB', 1, 0, 0, False),)
                                     if missing == 'valuation' else ())
        ready = host.reconcile(snapshot)
        assert ready is (missing in {'policy', 'daily_loss'})
        if missing != 'policy':
            host.register_policy(scenario.policy('HC'))
        scenario.warm(host, scenario.market('HC'))
        scenario.quoted(host, 'HC')
        scenario.live(host, 'HC')
        host.advance(scenario.signal_end + timedelta(seconds=4))
        assert host.store.projection('orders')['data'] == []
        assert scenario.gateway.sends == []


def test_duplicate_build_staged_then_committed_has_exactly_one_submission(scenario):
    with scenario.host() as host:
        scenario.prepare_builds(host, ('RB',))
        assert scenario.live(host, 'RB') == 'DUPLICATE'
        end = scenario.signal_end + timedelta(seconds=4)
        host.advance(end)
        assert scenario.live(host, 'RB') == 'DUPLICATE'
        host.advance(end)
        assert len(scenario.gateway.sends) == 1
        planned = [r for r in host.store.projection('orders')['data'] if r['state'] == 'PLANNED']
        assert len(planned) == 1


def test_conflicting_duplicate_quarantines_staged_input(scenario):
    with scenario.host() as host:
        scenario.prepare_builds(host, ('RB',))
        assert scenario.live(host, 'RB', price='101') == 'CONFLICT'
        host.advance(scenario.signal_end + timedelta(seconds=4))
        assert not scenario.gateway.sends
        assert scenario.live(host, 'RB', end=scenario.signal_end + timedelta(minutes=5)) == 'BLOCKED'


def test_read_only_host_records_decisions_without_intents(scenario):
    from dataclasses import replace

    scenario.config = replace(scenario.config, fixture_send_enabled=False)
    with scenario.host() as host:
        scenario.prepare_builds(host, ('RB',))
        host.advance(scenario.signal_end + timedelta(seconds=4))
        assert not scenario.gateway.sends
        decisions = host.store.projection('decisions')['data']
        assert any(d['execution_reason'] == 'P5_OBSERVATION_ONLY' for d in decisions)


@pytest.mark.parametrize('frequency', ('5m', '15m', '30m', '60m', '1d', '1w'))
def test_input_matrix_reuses_p2_for_all_three_observers(scenario, frequency):
    from dataclasses import replace
    from app.market_data.newow.v2_completed import HistoricalAvailability, PublishedObservation, from_historical_bar
    from guiyi_quant.newow.product_identity import InputQualityPolicy

    with scenario.host() as host:
        host.activate(scenario.scope(('RB',), frequency=frequency, strategy='dual_fusion'),
                      expected_revision=None, supported=('RB',))
        assert host.reconcile(scenario.snapshot())
        market = scenario.market('RB', freq=frequency)
        if frequency in {'1d', '1w'}:
            end = market.sessions[-1].end
            observed = end + timedelta(minutes=1)
            if frequency == '1w':
                market = replace(market, completed_week=(scenario.day, end + timedelta(seconds=1)))
            product_bar = from_historical_bar(
                scenario.bar(end), market, revision='frozen', source_ref='official-bar', as_of=observed,
                availability=HistoricalAvailability(observed, 'fixture-close'),
            ).payload.bar
            bar_sha = 'a' * 64

            class Reader:
                def forward_incremental_bar(self, **options):
                    assert options['as_of'] == observed
                    return replace(product_bar, source_bar_sha256=bar_sha), InputQualityPolicy.V1

            assert host.receive_publication(
                Reader(), market, generation=scenario.config.market_generation, expected=end, now=observed,
                publication=PublishedObservation('test-post-close', bar_sha, observed), after=scenario.start,
                prior_owner_segment_id=market.owner_segment_id,
                prior_calculation_segment_id=product_bar.calculation_segment_id,
            ) == 'ACCEPTED'
        else:
            end = market.endpoints[0]
            assert scenario.live(host, 'RB', end=end, market=market) == 'ACCEPTED'
        rows = host.store.projection('decisions')['data']
        assert {row['frequency'] for row in rows} == {frequency}
        assert {row['strategy'] for row in rows} == {'trend', 'oscillation', 'dual_fusion'}
        assert not scenario.gateway.sends


def test_mutable_sources_and_uncompleted_bars_have_no_authority(scenario):
    with scenario.host() as host:
        host.activate(scenario.scope(('RB',)), expected_revision=None, supported=('RB',))
        with pytest.raises(ValueError, match='P5_MARKET_GENERATION_CONFLICT'):
            host.receive_observation(None, scenario.market('RB'), now=scenario.start,
                                     expected=scenario.signal_end, generation='wrong-source')
        with pytest.raises(ValueError, match='V2_MARKET_FREQUENCY_INVALID'):
            scenario.market('RB', freq='1m')
        assert not host.store.projection('decisions')['data']


def test_conflict_at_batch_deadline_is_known_before_dispatch(scenario):
    with scenario.host() as host:
        scenario.prepare_builds(host, ('RB',))
        deadline = scenario.signal_end + timedelta(seconds=4)
        assert scenario.live(host, 'RB', price='101', now=deadline) == 'CONFLICT'
        host.advance(deadline)
        assert not scenario.gateway.sends


def test_quarantined_canonical_prefix_cannot_handoff_to_observation(scenario):
    from app.market_data.newow.v2_completed import HistoricalAvailability, from_historical_bar

    with scenario.host() as host:
        market = scenario.market('RB')
        host.activate(scenario.scope(('RB',)), expected_revision=None, supported=('RB',))
        assert host.reconcile(scenario.snapshot())
        host.register_policy(scenario.policy('RB'))
        scenario.warm(host, market)
        end = market.endpoints[8]
        available = end + timedelta(seconds=1)
        conflict = from_historical_bar(
            scenario.bar(end, '101'), market, revision='fixture-canonical', source_ref=f'bar-{end}',
            availability=HistoricalAvailability(available, 'fixture-clock'), as_of=available, warmup=True,
        )
        assert host.receive_completed(conflict, market, expected=end, now=available) == 'CONFLICT'
        scenario.quoted(host, 'RB')
        assert scenario.live(host, 'RB') == 'BLOCKED'
        host.advance(scenario.signal_end + timedelta(seconds=4))
        assert not scenario.gateway.sends


def test_market_only_product_and_unattributed_order_keep_physical_bindings(scenario):
    from app.market_data.newow.v2_scope import Scope
    from gateway import NativeOrder, OrderStatus

    with scenario.host() as host:
        scope = scenario.scope(('RB',))
        host.activate(Scope(scope.revision, ('rb', 'hc'), scope.deployments), expected_revision=None,
                      supported=('RB', 'HC'))
        assert scenario.live(host, 'HC', end=scenario.start + timedelta(minutes=5)) == 'ACCEPTED'
        unknown = NativeOrder('SHFE', 'HC2609', scenario.day, 'unattributed', 1, 0, OrderStatus.ACTIVE)
        assert not host.reconcile(scenario.snapshot(orders=(unknown,)))
        assert host.status()['subscriptions'] == {'physical_count': 2, 'contracts': {'hc': ['HC2609', 'HC2701'], 'rb': []}}


def test_exact_contract_product_and_czce_binding(scenario):
    from gateway import Position
    from guiyi_quant.simnow_execution.model import Contract
    from risk import ContractPolicy

    with pytest.raises(ValueError, match='P5_NATIVE_POSITION_INVALID'):
        Position('CFFEX', 'IF2701', 'I', 1, 0, 0)
    with pytest.raises(ValueError, match='P5_CONTRACT_POLICY_INVALID'):
        scenario.policy('R', contract='RB2701')
    binding = Contract('SR2701', 'SR701', 'CZCE', 'fixture-instrument',
                       scenario.start, scenario.start + timedelta(hours=3))
    policy = ContractPolicy('SR', 'CZCE', 'SR2701', 'SR701', 1, scenario.D(10),
                            scenario.D(1), scenario.D('0.10'), scenario.D(0), binding)
    assert policy.product == 'sr' and policy.native_symbol == 'SR701'
