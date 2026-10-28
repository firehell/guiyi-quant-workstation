"""The bootstrap runner has an explicit action and a read-only native API."""
from pathlib import Path
from types import SimpleNamespace
from datetime import UTC, datetime, timedelta
import importlib.util

import pytest


def runner():
    path = Path(__file__).parents[3] / 'scripts/broker/simnow_observe_bootstrap.py'
    spec = importlib.util.spec_from_file_location('observe_bootstrap_runner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runner_requires_explicit_action_and_aware_deadline():
    module = runner()
    args = ['--config', '/private/config.json', '--output', '/private/result.json',
            '--deadline', '2026-10-29T07:00:00+08:00']
    with pytest.raises(SystemExit):
        module.options(args)
    value = module.options([*args, '--read-only'])
    assert value.read_only and not value.initialize_observe
    with pytest.raises(SystemExit):
        module.options([*args, '--read-only', '--initialize-observe'])


@pytest.mark.parametrize('name', ['ReqOrderInsert', 'ReqOrderAction', 'ReqSettlementInfoConfirm', 'ReqQrySettlementInfoConfirm'])
def test_native_api_cannot_send_or_confirm_settlement(name):
    module = runner()
    calls = []
    api = module.ReadOnlyTraderAPI(SimpleNamespace(**{name: lambda *_: calls.append(name)}))
    with pytest.raises(ValueError, match='READ_ONLY'):
        getattr(api, name)
    assert calls == []


def test_native_api_allows_inventory_and_release():
    module = runner()
    calls = []
    api = module.ReadOnlyTraderAPI(SimpleNamespace(ReqQryTradingAccount=lambda *_: calls.append('funds'),
        Release=lambda: calls.append('closed')))
    api.ReqQryTradingAccount(None, 1)
    api.Release()
    assert calls == ['funds', 'closed']


def test_deadline_prevents_starting_a_late_read_or_initialization():
    module = runner()
    now = datetime(2026, 10, 29, tzinfo=UTC)
    with pytest.raises(ValueError, match='DEADLINE'):
        module.check_deadline(now, now=now)
    with pytest.raises(ValueError, match='DEADLINE'):
        module.check_deadline(now.replace(tzinfo=None), now=now)
    module.check_deadline(now + timedelta(seconds=1), now=now)


def test_readonly_summary_does_not_claim_a_ledger_has_been_reconciled():
    module = runner()
    from test_observe_bootstrap import native
    from guiyi_quant.simnow_execution.inventory import read_snapshot
    value = module.probe_summary(read_snapshot(native.report()))
    assert value['account_read_complete'] and value['balance_verified'] and value['flat_verified']
    assert value['account_reconciled'] is False
    assert value['new_account_state'] == 'UNINITIALIZED'
    assert value['old_account_state'] == 'UNKNOWN' and not value['execution_permitted']


def test_native_diagnostic_failure_cannot_bypass_connection_release(monkeypatch):
    from contextlib import nullcontext
    from guiyi_quant.simnow_execution.credentials import CredentialStore
    from test_observe_bootstrap import native
    module = runner()
    monkeypatch.setattr(module, 'quiet_native', lambda: nullcontext())
    monkeypatch.setattr(CredentialStore, 'load', lambda *_: SimpleNamespace(
        account_id='a' * 64, user='fixture', password='fixture'))
    calls = []
    api = SimpleNamespace(RegisterSpi=lambda *_: calls.append('detach'),
                          Release=lambda: calls.append('released'))
    def diagnostics():
        raise RuntimeError('diagnostic failure')
    gateway = SimpleNamespace(user='fixture', password='fixture', api=None,
        snapshot=native.report, inventory_diagnostics=diagnostics)
    sdk = SimpleNamespace(Gateway=lambda *_args, **_kwargs: gateway,
        tdapi=SimpleNamespace(CThostFtdcTraderApi=SimpleNamespace(CreateFtdcTraderApi=lambda _: api)))
    def connect(g, facade, flow):
        g.api = facade.CThostFtdcTraderApi.CreateFtdcTraderApi(flow)
    reader = module.NativeReader(SimpleNamespace(account_id='a' * 64), sdk, connect, lambda: None)
    assert reader()['status'] == 'READ_ONLY_COMPLETE'
    assert calls == ['detach', 'released']
    assert gateway.user == gateway.password == ''
