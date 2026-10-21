"""Constructed MDS/provider boundary fixtures; never historical market evidence."""
from datetime import UTC, date, datetime
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from app.market_data.domain import BarFrequency, CanonicalBar, MarketSeriesResult, ResolvedContractSegment

DAY = date(2025, 1, 2)
END = datetime(2025, 1, 2, 7, tzinfo=UTC)


class Market:
    def __init__(self, missing=()):
        self.missing = missing
        self.calls = []

    def actual_dominant_segments(self, symbol, since, through):
        return (ResolvedContractSegment('JM2505', DAY, DAY),)

    def session_windows(self, **kwargs):
        return (SimpleNamespace(start=END.replace(hour=1), end=END),)

    def expected_contract_replay_endpoints(self, **kwargs):
        self.calls.append(kwargs)
        return ((END, DAY),)

    def query_contract_trading_days(self, query):
        if query.frequency.value in self.missing:
            raise ValueError('do not expose provider/private detail')
        bar = CanonicalBar(END, DAY, D('100'), D('102'), D('99'), D('101'), D('1'), None, None)
        return MarketSeriesResult({'symbol':'jm', 'series_kind':'contract', 'contract':'JM2505',
                                   'frequency':query.frequency.value}, (bar,), (END,END), ())


def test_full_physical_prefix_and_shared_owner_across_all_seven_frequencies():
    from app.market_data.newow_futures_research import load_newow_futures_inputs
    market = Market()
    source = load_newow_futures_inputs(market, product='jm', since=DAY, through=DAY)
    assert set(source.bars_by_frequency) == {'1m','5m','15m','30m','60m','1d','1w'}
    bars = [values[0] for values in source.bars_by_frequency.values()]
    assert len({b.owner for b in bars}) == 1
    assert all(b.owner_segment_id and b.calculation_segment_id for b in bars)
    assert next(c for c in market.calls if c['frequency'] is BarFrequency.M1)['since'] == DAY
    assert all(c['since'] is None for c in market.calls if c['frequency'] is not BarFrequency.M1)
    assert source.diagnostics['minute_complete'] is True


def test_missing_frequency_is_typed_without_shrinking_other_frequencies():
    from app.market_data.newow_futures_research import load_newow_futures_inputs
    source = load_newow_futures_inputs(Market(('30m',)), product='jm', since=DAY, through=DAY)
    assert source.bars_by_frequency['30m'] == ()
    assert source.bars_by_frequency['5m']
    assert source.gaps_by_frequency['30m'][0]['code'] == 'DATA_INSUFFICIENT'
    assert source.diagnostics['minute_complete'] is True


def test_missing_minute_discloses_account_wide_failure_but_keeps_price_bars():
    from app.market_data.newow_futures_research import load_newow_futures_inputs
    source = load_newow_futures_inputs(Market(('1m',)), product='jm', since=DAY, through=DAY)
    assert source.minute_bars == () and source.bars_by_frequency['5m']
    assert source.diagnostics['minute_complete'] is False


def _raw():
    return {'schema_version':1, 'source':'rqdata', 'plan_hash':'a'*64,
            'captured_at':'2026-01-01T00:00:00+00:00', 'contracts':{'JM2505':{
                'instrument':{'order_book_id':'JM2505','tick_size':'0.5','contract_multiplier':'60'},
                'parameters':[], 'daily':[]}}}


def test_provider_tick_remains_usable_when_fee_dates_missing():
    from app.market_data.newow_futures_research import load_newow_futures_inputs, load_reference_ticks, load_execution_facts
    source = load_newow_futures_inputs(Market(), product='jm', since=DAY, through=DAY)
    assert load_reference_ticks(_raw(), product='jm', bars=source.minute_bars) == {('JM2505',DAY):D('0.5')}
    with pytest.raises(ValueError, match='EXECUTION_FACTS_MISSING'):
        load_execution_facts(_raw(), product='jm', bars=source.minute_bars)


def test_tick_is_never_guessed():
    from app.market_data.newow_futures_research import load_newow_futures_inputs, load_reference_ticks
    source = load_newow_futures_inputs(Market(), product='jm', since=DAY, through=DAY)
    raw = _raw()
    del raw['contracts']['JM2505']['instrument']['tick_size']
    with pytest.raises(ValueError, match='EXECUTION_FACTS_MISSING'):
        load_reference_ticks(raw, product='jm', bars=source.minute_bars)


def test_execution_facts_wrap_new_bar_without_broadening_old_subing_contracts():
    from app.market_data.newow_futures_research import load_newow_futures_inputs, load_execution_facts
    from guiyi_quant.newow_futures.contracts import Bar, ExecutionBar
    source = load_newow_futures_inputs(Market(),product='jm',since=DAY,through=DAY)
    raw = _raw()
    raw['contracts']['JM2505'].update(parameters=[{'date':DAY.isoformat(),'commission_type':'by_volume',
        'open_commission':'1','close_commission':'2','close_commission_today':'3',
        'long_margin_ratio':'0.1','short_margin_ratio':'0.12'}],
        daily=[{'date':DAY.isoformat(),'prev_settlement':'100','limit_up':'110','limit_down':'90'}])
    executions,digest = load_execution_facts(raw,product='jm',bars=source.minute_bars)
    assert type(executions[0]) is ExecutionBar and type(executions[0].bar) is Bar
    assert executions[0].facts.short_margin_ratio == D('0.12') and len(digest)==64
