from scripts.research.subing_trade_report import project
import pytest


def test_report_preserves_single_variant_and_open_position():
    # An open position must not acquire an invented exit or realized PnL.
    outcome = dict(opening=dict(contract='JM2505', side='LONG', decision_at='decision',
                                fill_at='fill', price='100', reasons=['ENTRY_MET']),
                   exit=None, handoff=None)
    summary = dict(net_pnl='0', drawdown='0', opportunities={}, execution_rejections={}, risk_records=[])
    report = dict(kind='THREE_PRODUCT_RETROSPECTIVE_HISTORICAL_RESEARCH', input_id='input',
                  requested=[], fee_multiplier=1, slippage_ticks=1, exit_profile='hour', portfolio_runs={'A': summary, 'B': summary},
                  matched_entries=[], unmatched_entries={'A': [outcome], 'B': []}, code_hashes={})
    meta, row = project(report)
    assert meta['matched'] == 0
    assert (row['rule'], row['match'], row['decision_at'], row['fill_at']) == ('A', '单侧入场', 'decision', 'fill')
    assert row['net'] is None and row['exit_at'] is None


def test_incomplete_research_reports_the_source_reason():
    with pytest.raises(ValueError, match='ACTUAL_KNOWLEDGE_FACTS_REQUIRED'):
        list(project(dict(kind='HISTORICAL_RESEARCH_COVERAGE',
                          execution_status='ACTUAL_KNOWLEDGE_FACTS_REQUIRED_FOR_16')))
