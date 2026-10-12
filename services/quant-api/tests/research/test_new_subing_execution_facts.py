"""Provider response boundary fixtures; these are not downloaded market evidence."""
from types import SimpleNamespace
import importlib.util
import pandas as pd
import pytest


def test_execution_fact_collector_exists():
    assert importlib.util.find_spec('scripts.research.new_subing_execution_facts') is not None


def _frame():
    return pd.DataFrame({'order_book_id':['AL2502'],'trading_date':['2025-01-02'],'long_margin_ratio':[0.1]})


def test_wrong_provider_contract_and_duplicate_day_fail_closed():
    from scripts.research.new_subing_execution_facts import normalize_rows
    frame=_frame()
    frame.loc[0,'order_book_id']='AL2503'
    with pytest.raises(ValueError):
        normalize_rows(frame,'AL2502',['2025-01-02'],['long_margin_ratio'])
    frame=_frame()
    with pytest.raises(ValueError):
        normalize_rows(pd.concat([frame,frame]),'AL2502',['2025-01-02'],['long_margin_ratio'])


def test_missing_provider_day_is_not_forward_filled():
    from scripts.research.new_subing_execution_facts import normalize_rows
    with pytest.raises(ValueError):
        normalize_rows(_frame(),'AL2502',['2025-01-02','2025-01-03'],['long_margin_ratio'])


def test_numeric_strings_and_callable_tick_are_not_instrument_repr():
    from scripts.research.new_subing_execution_facts import normalize_rows,instrument_payload
    rows=normalize_rows(_frame(),'AL2502',['2025-01-02'],['long_margin_ratio'])
    assert rows==[{'date':'2025-01-02','long_margin_ratio':'0.1'}]
    inst=SimpleNamespace(order_book_id='AL2502',tick_size=lambda:5,contract_multiplier=5)
    assert instrument_payload(inst,'AL2502')['tick_size']=='5'


def test_nonfinite_provider_number_rejected():
    from scripts.research.new_subing_execution_facts import normalize_rows
    frame=_frame()
    frame.loc[0,'long_margin_ratio']=float('nan')
    with pytest.raises(ValueError):
        normalize_rows(frame,'AL2502',['2025-01-02'],['long_margin_ratio'])


def test_exchange_settlement_and_limit_sources_require_same_exact_days():
    from scripts.research.new_subing_execution_facts import merge_daily_rows,EXCHANGE_FIELDS,LIMIT_FIELDS
    assert EXCHANGE_FIELDS==('settlement','prev_settlement')
    assert LIMIT_FIELDS==('limit_up','limit_down')
    daily=[{'date':'2025-01-02','settlement':'100','prev_settlement':'99'}]
    limits=[{'date':'2025-01-02','limit_up':'110','limit_down':'90'}]
    assert merge_daily_rows(daily,limits)==[{'date':'2025-01-02','settlement':'100','prev_settlement':'99','limit_up':'110','limit_down':'90'}]
    with pytest.raises(ValueError):
        merge_daily_rows(daily,[{**limits[0],'date':'2025-01-03'}])
