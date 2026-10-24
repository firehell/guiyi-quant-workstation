"""Small constructed packets test audit behavior; they are not research evidence."""
from copy import deepcopy
from decimal import Decimal
import json
import os
import subprocess
import sys

import pytest

from app.new_subing_research.store import publish_result
from scripts.research import subing_phase1 as audit


def packet():
    meta = {
        'product': 'RB', 'scenario': 'baseline', 'status': 'COMPLETED',
        'strategy_code': 'new_subing_v2', 'formula_version': 'new_subing_formula_v2',
        'profile_id': 'new_subing_stage_v2_100k', 'risk_profile_version': 'new_subing_risk_v2',
        'execution_profile_version': 'new_subing_next_1m_open_v2',
        'account_model_version': 'new_subing_layers_v2', 'initial_cash': '100000',
        'code_revision': 'a'*40, 'requested_since': '2025-01-01',
        'requested_through': '2025-01-31', 'input_snapshot_hash': 'b'*64,
        'execution_facts_hash': 'c'*64, 'source': 'historical_replay',
        'auto_order': False, 'case_parity': 'PENDING', 'oos_status': 'NOT_PROVEN',
    }
    fills = [
        {'action': 'OPEN', 'at': '2025-01-02T09:01:00+08:00', 'qty': 2,
         'fee': '0.1', 'physical_contract': 'RB2505', 'side': 'LONG', 'reason': 'TRIAL_SETUP'},
        {'action': 'CLOSE', 'at': '2025-01-02T09:10:00+08:00', 'qty': 1,
         'fee': '0.1', 'physical_contract': 'RB2505', 'side': 'LONG',
         'realized_pnl': '1', 'reason': 'FAST_PROFIT'},
        {'action': 'CLOSE', 'at': '2025-01-02T09:20:00+08:00', 'qty': 1,
         'fee': '0.1', 'physical_contract': 'RB2505', 'side': 'LONG',
         'realized_pnl': '-2', 'reason': 'HARD_STOP'},
    ]
    return {
        'schema_version': 1, 'metadata': meta,
        'summary': {'status': 'COMPLETED', 'initial_cash': '100000',
                    'final_equity': '99998.7', 'account_return_pct': '-0.0013',
                    'max_drawdown_pct': '0', 'closed_trades': 1, 'total_fees': '0.3',
                    'ending_qty': 0, 'annual_eligible': False},
        'fills': fills,
        'trades': [{'trade_id': 'trade-1', 'physical_contract': 'RB2505', 'side': 'LONG',
                    'entry_at': fills[0]['at'], 'exit_at': fills[-1]['at'],
                    'net_pnl': '-1.3', 'status': 'CLOSED'}],
        'decisions': [{'decision_id': 'decision-1', 'at': '2025-01-02T09:00:00+08:00',
                       'action': 'OPEN', 'reason': 'TRIAL_SETUP', 'physical_contract': 'RB2505',
                       'facts': {'setup_trigger': 'MA_CROSS',
                                 'votes': {'macd': False, 'volume': True}}}],
        'equity': [], 'diagnostics': {}, 'stages': [],
    }


def test_partial_reduction_is_not_an_extra_trade_and_all_fees_are_assigned():
    result = audit.analyze_packet(packet())
    row = result['closed_rounds'][0]
    assert Decimal(row['net_pnl']) == Decimal('-1.3')
    assert Decimal(row['fees']) == Decimal('0.3')
    assert row['partial_closes'] == 1
    assert row['exit_reason'] == 'HARD_STOP'
    assert result['by_exit_reason']['HARD_STOP']['count'] == 1
    assert result['close_fill_reasons'] == {'FAST_PROFIT': 1, 'HARD_STOP': 1}
    assert result['entry_intents']['MA_CROSS'] == 1
    assert row['entry_decision_link'] == 'NOT_RECORDED'


def test_interrupted_open_round_preserves_realized_cash_but_has_no_full_return():
    item = packet()
    item['fills'].pop()
    item['trades'] = []
    item['metadata']['status'] = item['summary']['status'] = 'ROLLOVER_INTERRUPTED'
    item['summary'].update(closed_trades=0, ending_qty=1, final_equity=None,
                           account_return_pct=None, max_drawdown_pct=None, total_fees=None)
    result = audit.analyze_packet(item)
    assert result['account_return_pct'] is None
    assert result['closed_rounds'] == []
    assert result['open_round']['remaining_qty'] == 1
    assert Decimal(result['open_round']['realized_net_to_date']) == Decimal('0.8')
    assert Decimal(result['cash_from_fills']) == Decimal('100000.8')


@pytest.mark.parametrize('mutation', ['contract', 'side', 'overclose', 'trade_pnl',
                                    'final_cash', 'fees', 'ending_qty', 'duplicate_trade',
                                    'naive_time', 'float_money', 'unsorted_fills'])
def test_unreconciled_facts_fail_closed(mutation):
    item = packet()
    if mutation == 'contract':
        item['fills'][-1]['physical_contract'] = 'RB2510'
    elif mutation == 'side':
        item['fills'][-1]['side'] = 'SHORT'
    elif mutation == 'overclose':
        item['fills'][-1]['qty'] = 2
    elif mutation == 'trade_pnl':
        item['trades'][0]['net_pnl'] = '-1.2'
    elif mutation == 'final_cash':
        item['summary']['final_equity'] = '99999'
    elif mutation == 'fees':
        item['summary']['total_fees'] = '0.2'
    elif mutation == 'ending_qty':
        item['summary']['ending_qty'] = 1
    elif mutation == 'duplicate_trade':
        item['trades'].append(deepcopy(item['trades'][0]))
    elif mutation == 'naive_time':
        item['fills'][0]['at'] = '2025-01-02T09:01:00'
    elif mutation == 'float_money':
        item['fills'][0]['fee'] = 0.1
    else:
        item['fills'][0], item['fills'][1] = item['fills'][1], item['fills'][0]
    with pytest.raises(audit.AuditError):
        audit.analyze_packet(item)


def test_decimal_tail_is_not_lost():
    item = packet()
    item['fills'][0]['fee'] = '0.1000000000000000000000000001'
    item['summary'].update(total_fees='0.3000000000000000000000000001',
                           final_equity='99998.6999999999999999999999999999')
    item['trades'][0]['net_pnl'] = '-1.3000000000000000000000000001'
    result = audit.analyze_packet(item)
    assert result['closed_rounds'][0]['net_pnl'] == '-1.3000000000000000000000000001'


def test_rounds_join_by_exact_contract_side_and_times_not_list_order():
    item = packet()
    second = deepcopy(item['trades'][0])
    second.update(trade_id='trade-2', entry_at='2025-01-03T09:01:00+08:00',
                  exit_at='2025-01-03T09:20:00+08:00')
    item['trades'].insert(0, second)
    item['fills'] += [{**f, 'at': f['at'].replace('01-02', '01-03')} for f in item['fills']]
    item['summary'].update(closed_trades=2, total_fees='0.6', final_equity='99997.4')
    rows = audit.analyze_packet(item)['closed_rounds']
    assert [r['trade_id'] for r in rows] == ['trade-1', 'trade-2']


def test_real_index_reader_detects_packet_corruption_and_does_not_write(tmp_path):
    publish_result(tmp_path, packet())
    before = (tmp_path/'index.json').read_bytes()
    assert len(audit.audit_roots([tmp_path])['runs']) == 1
    assert (tmp_path/'index.json').read_bytes() == before
    index = json.loads(before)
    (tmp_path/index['runs'][0]['file']).write_text('{}')
    with pytest.raises(ValueError):
        audit.audit_roots([tmp_path])


def test_empty_root_is_not_a_successful_audit(tmp_path):
    with pytest.raises(audit.AuditError, match='EMPTY_RESULT_ROOT'):
        audit.audit_roots([tmp_path])


def test_fifo_index_is_rejected_without_blocking(tmp_path):
    os.mkfifo(tmp_path/'index.json')
    probe = ('from pathlib import Path; from scripts.research.subing_phase1 import audit_roots; '
             'import sys; audit_roots([Path(sys.argv[1])])')
    try:
        result = subprocess.run([sys.executable, '-c', probe, str(tmp_path)],
                                capture_output=True, timeout=2, check=False)
    except subprocess.TimeoutExpired:
        pytest.fail('unsafe index blocked instead of failing closed')
    assert result.returncode != 0
    assert 'RESULT_PATH_UNSAFE' in result.stderr.decode()


def test_comparison_refuses_different_input_for_same_product_window(tmp_path):
    first, second = tmp_path/'first', tmp_path/'second'
    first.mkdir()
    second.mkdir()
    publish_result(first, packet())
    changed = packet()
    changed['metadata'].update(initial_cash='1000000', profile_id='new_subing_stage_v2_1m',
                               input_snapshot_hash='d'*64)
    changed['summary'].update(initial_cash='1000000', final_equity='999998.7')
    publish_result(second, changed)
    with pytest.raises(audit.AuditError, match='COMPARISON_INPUTS_DIFFER'):
        audit.audit_roots([first, second])


def test_casebook_labels_retrospective_selection_and_keeps_owner_judgment_unknown():
    result = audit.analyze_packet(packet())
    book = audit.render_casebook({'runs': [result]})
    assert '事后选样' in book
    assert 'UNKNOWN' in book
    assert 'RB2505' in book
    assert '2025-01-02T09:01:00+08:00' in book


def test_casebook_uses_recorded_time_exit_reason():
    item = packet()
    item['fills'][-1]['reason'] = 'FIVE_BARS_NO_PROFIT'
    book = audit.render_casebook({'runs': [audit.analyze_packet(item)]})
    assert any(line.startswith('## ') and '时间退出' in line for line in book.splitlines())


def test_output_cannot_be_written_into_a_source_root(tmp_path):
    source = tmp_path/'source'
    source.mkdir()
    publish_result(source, packet())
    assert audit.main(['--results-root', str(source), '--output-root', str(source/'audit')]) == 2
    assert not (source/'audit').exists()
