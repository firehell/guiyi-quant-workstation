"""Constructed audit cases; these are not evidence of historical readiness."""
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from decimal import Decimal

import pytest

from scripts.research import subing_jm_daily_preflight as audit


def snapshot():
    return {'schema_version': 1, 'source': 'rqdata', 'plan_hash': 'a' * 64,
        'captured_at': '2026-01-01T00:00:00+00:00', 'contracts': {'JM2605': {
            'instrument': {'order_book_id': 'JM2605', 'tick_size': '0.5', 'contract_multiplier': '60'},
            'parameters': [{'date': '2025-12-01', 'long_margin_ratio': '0.2', 'short_margin_ratio': '0.3',
                'commission_type': 'by_money', 'open_commission': '0.0001',
                'close_commission': '0.0002', 'close_commission_today': '0.0003'}],
            'daily': [{'date': '2025-12-01', 'prev_settlement': '1000', 'limit_up': '1100',
                       'limit_down': '900'}]}}}


def test_endpoint_diagnostic_keeps_missing_extra_duplicates_and_order():
    t = datetime(2025, 12, 1, 1, tzinfo=UTC)
    day = t.date()
    other = t.replace(hour=2)
    result = audit.compare_endpoints([(t, day)], [SimpleNamespace(bar_end=other, trading_day=day)] * 2)
    assert result['missing'] == [[t.isoformat(), day.isoformat()]]
    assert result['unexpected'] == [[other.isoformat(), day.isoformat()]]
    assert result['duplicate_count'] == 1
    assert result['ordered'] is False


def test_fact_validation_preserves_both_margin_sides_and_three_fee_kinds():
    result = audit.execution_day(snapshot(), 'JM2605', date(2025, 12, 1))
    assert result['long_margin_ratio'] == '0.2'
    assert result['short_margin_ratio'] == '0.3'
    assert result['fees']['open_rate'] == '0.0001'
    assert result['fees']['close_rate'] == '0.0002'
    assert result['fees']['close_today_rate'] == '0.0003'
    assert 'source_id' not in result and 'source_id' not in result['fees']


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'negative_fee', 'bad_margin', 'bad_limit'])
def test_bad_facts_never_become_available(mutation):
    raw = snapshot()
    body = raw['contracts']['JM2605']
    if mutation == 'missing':
        body['parameters'] = []
    elif mutation == 'duplicate':
        body['parameters'] *= 2
    elif mutation == 'negative_fee':
        body['parameters'][0]['open_commission'] = '-1'
    elif mutation == 'bad_margin':
        body['parameters'][0]['short_margin_ratio'] = '2'
    else:
        body['daily'][0]['limit_down'] = '1200'
    with pytest.raises(ValueError):
        audit.execution_day(raw, 'JM2605', date(2025, 12, 1))


def test_windows_do_not_bridge_failure_or_owner_change():
    rows = [{'day': f'2025-12-0{i}', 'contract': c, 'status': s} for i, c, s in [
        (1, 'JM2601', 'INPUTS_VERIFIED'), (2, 'JM2601', 'INPUTS_VERIFIED'),
        (3, 'JM2601', 'DATA_INSUFFICIENT'), (4, 'JM2601', 'INPUTS_VERIFIED'),
        (5, 'JM2605', 'INPUTS_VERIFIED')]]
    result = audit.windows_from_days(rows)
    assert [w['days'] for w in result] == [2, 1, 1, 1]
    assert result[0]['through'] == '2025-12-02'


def test_daily_first_macd_ready_bar_is_not_cross_evaluable_and_prefix_is_stable():
    start = datetime(2025, 1, 1, tzinfo=UTC)
    bars = [SimpleNamespace(bar_end=start + timedelta(days=i),
        trading_day=(start + timedelta(days=i)).date(), close=100 + i) for i in range(40)]
    ready = audit.daily_readiness(bars)
    assert not ready[bars[33].trading_day]
    assert ready[bars[34].trading_day]
    assert audit.daily_readiness(bars[:35]) == {b.trading_day: ready[b.trading_day] for b in bars[:35]}


def test_session_failure_stays_in_total_day_ledger_and_breaks_available_window():
    rows = [{'day': d, 'contract': 'JM2605', 'status': 'INPUTS_VERIFIED'}
            for d in ('2025-12-01', '2025-12-03')]
    errors = [{'day': '2025-12-02', 'contract': 'JM2605', 'status': 'DATA_INSUFFICIENT',
               'error': {'code': 'TRADING_SESSION_MISSING'}}]
    merged = audit.include_session_failures(rows, errors)
    assert len(merged) == 3
    assert merged[1]['signal_inputs_verified'] is False
    assert [w['days'] for w in audit.windows_from_days(merged)] == [1, 1, 1]


@pytest.mark.parametrize('mutation', ['source_changed', 'missing_endpoint', 'duplicate'])
def test_physical_audit_fails_closed_on_changed_or_incomplete_input(mutation):
    from app.market_data.domain import BarFrequency, CanonicalBar
    t = datetime(2025, 12, 1, 7, tzinfo=UTC)
    bar = CanonicalBar(t, t.date(), *(Decimal('100') for _ in range(4)),
                       Decimal('10'), None, None)

    class Market:
        calls = 0

        def contract_source_evidence(self, **kwargs):
            self.calls += 1
            return {'hash': str(self.calls) if mutation == 'source_changed' else 'stable'}

        def expected_contract_replay_endpoints(self, **kwargs):
            return ((t, t.date()),)

        def query_contract_trading_days(self, request):
            bars = () if mutation == 'missing_endpoint' else (bar, bar) if mutation == 'duplicate' else (bar,)
            return SimpleNamespace(request_identity={'symbol': 'jm', 'series_kind': 'contract',
                'contract': 'JM2605', 'frequency': '1d'}, bars=bars, coverage=(t, t))

    report, bars = audit.audit_series(Market(), 'JM2605', BarFrequency.D1, t.date(), t.date(), t)
    assert bars == ()
    assert report['status'] != 'PASS'
    if mutation == 'source_changed':
        assert report['status'] == 'INPUT_CHANGED_DURING_AUDIT'
    elif mutation == 'missing_endpoint':
        assert len(report['missing']) == 1
    else:
        assert report['duplicate_count'] == 1
