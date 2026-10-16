"""Constructed adapter boundary tests, not market or original-case evidence."""
from datetime import UTC, date, datetime
from decimal import Decimal
import importlib.util

import pytest


def test_new_subing_input_adapter_exists():
    assert importlib.util.find_spec('app.market_data.new_subing_research') is not None


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-1', 1.5, True, None])
def test_execution_fact_decimal_rejects_invalid(value):
    from app.market_data.new_subing_research import NewSubingInputError, fact_decimal
    with pytest.raises(NewSubingInputError, match='EXECUTION_FACTS_MISSING'):
        fact_decimal(value, positive=True)


def test_execution_facts_missing_does_not_invent_costs():
    from app.market_data.new_subing_research import NewSubingInputError, load_execution_facts
    with pytest.raises(NewSubingInputError, match='EXECUTION_FACTS_MISSING'):
        load_execution_facts(None, product='al', bars=())


def test_source_identity_rejects_wrong_physical_contract():
    from app.market_data.new_subing_research import NewSubingInputError, validate_series
    from app.market_data.domain import BarFrequency, MarketSeriesResult
    result = MarketSeriesResult(
        {'symbol':'al','series_kind':'contract','contract':'AL2501','frequency':'5m'},
        (), None, (),
    )
    with pytest.raises(NewSubingInputError, match='DATA_CONFLICT'):
        validate_series(result, product='al', contract='AL2502', frequency=BarFrequency.M5,
                        expected=())


def test_source_missing_expected_endpoint_is_not_shortened():
    from app.market_data.new_subing_research import NewSubingInputError, validate_series
    from app.market_data.domain import BarFrequency, CanonicalBar, MarketSeriesResult
    t=datetime(2025,1,2,1,5,tzinfo=UTC)
    b=CanonicalBar(t,date(2025,1,2),Decimal('10'),Decimal('11'),Decimal('9'),Decimal('10'),Decimal('1'),None,None)
    result=MarketSeriesResult(
        {'symbol':'al','series_kind':'contract','contract':'AL2502','frequency':'5m'},
        (b,), (t,t), (),
    )
    with pytest.raises(NewSubingInputError, match='DATA_INSUFFICIENT'):
        validate_series(result, product='al',contract='AL2502',frequency=BarFrequency.M5,
                        expected=((t,date(2025,1,2)),(datetime(2025,1,2,1,10,tzinfo=UTC),date(2025,1,2))))


def test_gap_diagnostic_redacts_internal_details():
    from app.market_data.new_subing_research import safe_diagnostic
    from app.market_data.market_data_service import MarketDataError
    e=MarketDataError('DATASET_OR_PARTITION_MISSING', context={'symbol':'al','contract':'AL2502',
        'frequency':'5m','password':'secret','sql':'query','file_uri':'private'})
    result=safe_diagnostic(e,product='al',stage='physical_prefix')
    assert result['symbol']=='al'
    assert result['contract']=='AL2502'
    assert 'password' not in result and 'sql' not in result and 'file_uri' not in result


def test_fixed_research_universe_and_window():
    from app.market_data.new_subing_research import PRODUCTS, SINCE, THROUGH
    assert PRODUCTS == ('al','rb','ta')
    assert (SINCE,THROUGH)==(date(2024,10,14),date(2026,10,9))


def _minute():
    from guiyi_quant.new_subing import StrategyBar
    t=datetime(2025,1,2,1,1,tzinfo=UTC)
    return StrategyBar('al','AL2502','1m',t,date(2025,1,2),
        Decimal('100'),Decimal('101'),Decimal('99'),Decimal('100'),Decimal('1'),Decimal('20'),
        'a'*64,t,True,datetime(2025,1,2,1,tzinfo=UTC),datetime(2025,1,2,7,tzinfo=UTC))


def _facts():
    return {'schema_version':1,'source':'rqdata','plan_hash':'a'*64,
        'captured_at':'2026-10-12T00:00:00+00:00','contracts':{'AL2502':{
            'instrument':{'order_book_id':'AL2502','tick_size':'1','contract_multiplier':'5'},
            'parameters':[{'date':'2025-01-02','commission_type':'by_volume','open_commission':'2',
                'close_commission':'3','close_commission_today':'4','long_margin_ratio':'0.1','short_margin_ratio':'0.12'}],
            'daily':[{'date':'2025-01-02','prev_settlement':'100','limit_up':'110','limit_down':'90'}]}}}


def test_provider_facts_keep_direction_margin_and_offset_fee_identity():
    from app.market_data.new_subing_research import load_execution_facts
    executions,h=load_execution_facts(_facts(),product='al',bars=(_minute(),))
    f=executions[0].facts
    assert f.long_margin_ratio==Decimal('0.1') and f.short_margin_ratio==Decimal('0.12')
    assert f.fees.amount('open',Decimal('100'),Decimal('5'))==Decimal('2')
    assert f.fees.amount('close',Decimal('100'),Decimal('5'))==Decimal('3')
    assert f.fees.amount('close_today',Decimal('100'),Decimal('5'))==Decimal('4')
    assert len(h)==64 and f.physical_contract=='AL2502'


def test_missing_or_duplicate_execution_day_never_uses_adjacent_day():
    from app.market_data.new_subing_research import load_execution_facts,NewSubingInputError
    raw=_facts()
    raw['contracts']['AL2502']['parameters']*=2
    with pytest.raises(NewSubingInputError,match='EXECUTION_FACTS_MISSING'):
        load_execution_facts(raw,product='al',bars=(_minute(),))


@pytest.mark.parametrize('field,value', [('plan_hash','bad'),('long_margin_ratio','1.1'),('short_margin_ratio','NaN')])
def test_provider_execution_plan_and_margin_bounds(field,value):
    from app.market_data.new_subing_research import load_execution_facts,NewSubingInputError
    raw=_facts()
    if field=='plan_hash':
        raw[field]=value
    else:
        raw['contracts']['AL2502']['parameters'][0][field]=value
    with pytest.raises(NewSubingInputError,match='EXECUTION_FACTS_MISSING'):
        load_execution_facts(raw,product='al',bars=(_minute(),))
