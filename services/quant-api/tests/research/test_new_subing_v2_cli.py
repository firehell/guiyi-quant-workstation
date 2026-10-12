from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.market_data.new_subing_research import NewSubingInputError
from app.new_subing_research.store import publish_result
from guiyi_quant.new_subing_v2 import Profile
from scripts.research import new_subing_v2 as cli


def test_capital_identity_and_blocked_no_return(tmp_path):
    ids = []
    for cash in cli.CAPITALS:
        packet = cli.build_packet(product='al', scenario='baseline', profile=Profile(initial_cash=cash),
                                  code_revision='a'*40, status='DATA_INSUFFICIENT')
        frozen = publish_result(tmp_path, packet)
        assert frozen['summary'].get('account_return_pct') is None
        assert frozen['metadata']['initial_cash'] == str(cash)
        ids.append(frozen['metadata']['run_id'])
    assert ids[0] != ids[1]


@pytest.mark.parametrize('input_hash,facts_hash,code', [
    ('b'*64, 'c'*64, 'COMPARISON_INPUT_HASH_MISMATCH'),
    ('a'*64, 'd'*64, 'COMPARISON_FACTS_HASH_MISMATCH'),
])
def test_comparison_hash_changes_fail_closed(input_hash, facts_hash, code):
    with pytest.raises(NewSubingInputError) as exc:
        cli.verify_inputs(SimpleNamespace(input_snapshot_hash=input_hash), facts_hash, ('a'*64, 'c'*64))
    assert exc.value.code == code


def test_single_prepare_independent_capital_scenario_window_runs(monkeypatch):
    prepared = object()
    preparations = []
    calls = []
    monkeypatch.setattr(cli, 'progress', lambda **_: None)
    monkeypatch.setattr(cli, 'prepare_research', lambda bars, profile: preparations.append(bars) or prepared)
    def replay(bars, executions, **kwargs):
        assert kwargs['prepared'] is prepared
        calls.append(kwargs)
        cash = str(kwargs['profile'].initial_cash)
        return {'summary': {'status': 'COMPLETED', 'initial_cash': cash}, 'diagnostics': {}}
    monkeypatch.setattr(cli, 'run_research', replay)
    source = SimpleNamespace(product='AL', bars_by_frequency={}, input_snapshot_hash='a'*64, diagnostics={})
    packets = cli.run_source(source, (), facts_hash='b'*64, code_revision='c'*40)
    assert len(preparations) == 1
    assert len(calls) == 42
    assert len(packets) == 6
    assert {p['metadata']['initial_cash'] for p in packets} == {'100000', '1000000'}
    for packet in packets:
        cash = packet['metadata']['initial_cash']
        assert len(packet['diagnostics']['independent_windows']) == 6
        assert all(w['independent_initial_cash'] == cash for w in packet['diagnostics']['independent_windows'])
    assert sum(c['profile'].initial_cash == Decimal('100000') for c in calls) == 21
