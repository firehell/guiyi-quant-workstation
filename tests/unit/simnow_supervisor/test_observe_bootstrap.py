"""Real local journals with injected native reports; no SDK or broker calls."""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import importlib.util
import json

import pytest

from test_preparation import preparation
from guiyi_quant.simnow_execution.settings import load_settings
from guiyi_quant.simnow_execution.account_binding import existing_account

spec = importlib.util.spec_from_file_location('bootstrap_inventory_fixture',
    Path(__file__).parents[1] / 'simnow_host/test_inventory.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def clock():
    return native.T + timedelta(seconds=13)


def test_probe_is_two_pass_readonly_and_preserves_preparation(tmp_path):
    from guiyi_quant.simnow_execution.observe_bootstrap import probe_account
    config, _ = preparation(tmp_path)
    raw = config.read_bytes()
    snapshot = probe_account(config, native.report, now=clock)
    assert snapshot.account_id == 'a' * 64
    assert config.read_bytes() == raw
    assert not load_settings(config).state_root.exists()


def test_initialize_uses_actual_balance_and_atomically_publishes_four_journals(tmp_path):
    from guiyi_quant.simnow_execution.observe_bootstrap import initialize_observe
    config, _ = preparation(tmp_path)
    settings = load_settings(config)
    value = native.report()
    funds = value['rounds'][0]['queries']['funds']['rows'][0]
    value = native.changed(value, 'funds', [{**funds, 'Balance': '92345.67', 'Available': '92345.67'}])
    result = initialize_observe(config, ('JM', 'RB'), lambda: value, now=clock, assert_closed=lambda: True)
    published = json.loads(Path(result['config_path']).read_bytes())
    assert set(published) == {'schema', 'account_id', 'state_root', 'project_root', 'sdk_python',
                              'api_env', 'mode', 'enabled', 'state_project_root'}
    runtime = load_settings(Path(result['config_path']))
    state = existing_account(runtime.state_root, runtime.account_id)
    assert runtime.schema == 2 and runtime.mode == 'observe' and not runtime.enabled
    assert runtime.state_root == settings.state_root
    assert state.initial_readback.snapshot.balance == Decimal('92345.67')
    assert {p.product for p in state.products} == {'JM', 'RB'}
    assert result['execution_permitted'] is False
    assert len(list((runtime.state_root / runtime.account_id).glob('*.sqlite'))) == 4


def test_initialization_rejects_open_market_before_any_broker_read(tmp_path):
    from guiyi_quant.simnow_execution.observe_bootstrap import initialize_observe
    config, _ = preparation(tmp_path)
    def reader():
        pytest.fail('open market initialization must not connect')
    with pytest.raises(ValueError, match='CLOSED'):
        initialize_observe(config, ('RB',), reader, now=clock, assert_closed=lambda: False)
    assert not load_settings(config).state_root.exists()


@pytest.mark.parametrize('fault', ['account', 'partial', 'position', 'frozen', 'unexplained_cash', 'working_order', 'stale'])
def test_invalid_or_nonflat_facts_do_not_publish_an_account(tmp_path, fault):
    from guiyi_quant.simnow_execution.observe_bootstrap import initialize_observe
    config, _ = preparation(tmp_path)
    settings = load_settings(config)
    value = native.report()
    now = clock
    if fault == 'account':
        value['account_fingerprint'] = 'b' * 64
    elif fault == 'partial':
        value['rounds'][1]['queries']['funds']['complete'] = False
    elif fault == 'position':
        value = native.changed(value, 'positions', [dict(TradingDay='20261027', ExchangeID='SHFE',
            InstrumentID='rb2701', PosiDirection='2', HedgeFlag='1', PositionDate='1',
            Position=1, TodayPosition=1, YdPosition=0, LongFrozen=0, ShortFrozen=0)])
    elif fault == 'frozen':
        funds = value['rounds'][0]['queries']['funds']['rows'][0]
        value = native.changed(value, 'funds', [{**funds, 'FrozenMargin': '10'}])
    elif fault == 'unexplained_cash':
        funds = value['rounds'][0]['queries']['funds']['rows'][0]
        value = native.changed(value, 'funds', [{**funds, 'Available': '99900'}])
    elif fault == 'working_order':
        value = native.changed(value, 'orders', [dict(TradingDay='20261027',
            FrontID=1, SessionID=2, OrderRef='1', OrderStatus='3',
            OrderSubmitStatus='3', VolumeTraded=0)])
    else:
        def now():
            return native.T + timedelta(minutes=2)
    with pytest.raises(ValueError):
        initialize_observe(config, ('RB',), lambda: value, now=now, assert_closed=lambda: True)
    assert not (settings.state_root / settings.account_id).exists()


def test_partial_creation_failure_preserves_evidence_without_publishing(tmp_path):
    from guiyi_quant.simnow_execution.observe_bootstrap import initialize_observe
    config, _ = preparation(tmp_path)
    settings = load_settings(config)
    def fail(stage):
        if stage == 'account_created':
            raise RuntimeError('injected')
    with pytest.raises(RuntimeError):
        initialize_observe(config, ('RB',), native.report, now=clock, assert_closed=lambda: True, fault=fail)
    assert not (settings.state_root / settings.account_id).exists()
    assert list((settings.state_project_root / 'output').glob('.observe-bootstrap-*'))
    assert load_settings(config).schema == 3


def test_initialization_rechecks_closure_before_publication(tmp_path):
    from guiyi_quant.simnow_execution.observe_bootstrap import initialize_observe
    config, _ = preparation(tmp_path)
    calls = []
    def closed():
        calls.append(1)
        return len(calls) == 1
    with pytest.raises(ValueError, match='CLOSED'):
        initialize_observe(config, ('RB',), native.report, now=clock, assert_closed=closed)
    assert not (load_settings(config).state_root / ('a' * 64)).exists()


def test_probe_cannot_bypass_a_same_account_writer_in_another_root(tmp_path):
    from guiyi_quant.simnow_execution.observe_bootstrap import probe_account
    from guiyi_quant.simnow_execution.supervisor import global_account_lock
    config, _ = preparation(tmp_path)
    with global_account_lock('a' * 64):
        with pytest.raises(ValueError, match='ALREADY_RUNNING'):
            probe_account(config, lambda: pytest.fail('locked writer must prevent login'), now=clock)


def test_repeated_initialization_never_changes_existing_journals(tmp_path):
    from guiyi_quant.simnow_execution.observe_bootstrap import initialize_observe
    config, _ = preparation(tmp_path)
    result = initialize_observe(config, ('RB',), native.report, now=clock, assert_closed=lambda: True)
    folder = Path(result['config_path']).parent
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    with pytest.raises(ValueError):
        initialize_observe(config, ('RB',), lambda: pytest.fail('do not reconnect'), now=clock, assert_closed=lambda: True)
    assert before == {p.name: p.read_bytes() for p in folder.iterdir()}


def test_initialization_deadline_is_checked_before_publication(tmp_path):
    from guiyi_quant.simnow_execution.observe_bootstrap import initialize_observe
    config, _ = preparation(tmp_path)
    calls = []
    def check():
        calls.append(1)
        if len(calls) == 4:
            raise ValueError('BOOTSTRAP_DEADLINE_REACHED')
    with pytest.raises(ValueError, match='DEADLINE'):
        initialize_observe(config, ('RB',), native.report, now=clock,
            assert_closed=lambda: True, check=check)
    assert not (load_settings(config).state_root / ('a' * 64)).exists()


def test_probe_rejects_preparation_changed_during_native_read(tmp_path):
    import json
    from guiyi_quant.simnow_execution.observe_bootstrap import probe_account
    config, value = preparation(tmp_path)
    def reader():
        value['api_env'] = str(tmp_path)
        config.write_text(json.dumps(value))
        return native.report()
    with pytest.raises(ValueError, match='CONFIG_CHANGED'):
        probe_account(config, reader, now=clock)


def test_deadline_crossed_during_last_closure_proof_cannot_publish(tmp_path):
    from guiyi_quant.simnow_execution.observe_bootstrap import initialize_observe
    config, _ = preparation(tmp_path)
    calls = []
    def closed():
        calls.append(1)
        return True
    def check():
        if len(calls) >= 2:
            raise ValueError('BOOTSTRAP_DEADLINE_REACHED')
    with pytest.raises(ValueError, match='DEADLINE'):
        initialize_observe(config, ('RB',), native.report, now=clock, assert_closed=closed, check=check)
    assert not (load_settings(config).state_root / ('a' * 64)).exists()


def test_slow_stage_fsync_cannot_publish_an_expired_snapshot(tmp_path, monkeypatch):
    from guiyi_quant.simnow_execution import observe_bootstrap as bootstrap
    config, _ = preparation(tmp_path)
    instant = [clock()]
    original = bootstrap._fsync_directory
    def slow(path):
        original(path)
        instant[0] = native.T + timedelta(seconds=45)
    monkeypatch.setattr(bootstrap, '_fsync_directory', slow)
    with pytest.raises(ValueError, match='SNAPSHOT_EXPIRED'):
        bootstrap.initialize_observe(config, ('RB',), native.report,
            now=lambda: instant[0], assert_closed=lambda: True)
    assert not (load_settings(config).state_root / ('a' * 64)).exists()


def test_observe_config_excludes_inmemory_metadata_and_trade_permit(tmp_path):
    from dataclasses import replace
    from guiyi_quant.simnow_execution.observe_bootstrap import _write_config
    config, _ = preparation(tmp_path)
    settings = replace(load_settings(config), source_config_path=tmp_path / "source.private.json",
                       source_config_sha256="a" * 64,
                       deployment_connection_permit=tmp_path / "deployment-connection-permit.private.json")
    target = tmp_path / "observe-only.private.json"
    _write_config(target, settings)
    published = json.loads(target.read_bytes())
    assert published['schema'] == 2 and published['mode'] == 'observe' and not published['enabled']
    assert {'source_config_path', 'source_config_sha256', 'deployment_connection_permit'}.isdisjoint(published)
