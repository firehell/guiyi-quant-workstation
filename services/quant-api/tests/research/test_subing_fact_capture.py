"""Provider response boundary fixtures; these are not downloaded market evidence."""
from types import SimpleNamespace
import importlib.util
import pandas as pd
import pytest


def test_execution_fact_collector_exists():
    assert importlib.util.find_spec('scripts.research.subing_fact_capture') is not None


def _frame():
    return pd.DataFrame({'order_book_id':['AL2502'],'trading_date':['2025-01-02'],'long_margin_ratio':[0.1]})


def test_wrong_provider_contract_and_duplicate_day_fail_closed():
    from scripts.research.subing_fact_capture import normalize_rows
    frame=_frame()
    frame.loc[0,'order_book_id']='AL2503'
    with pytest.raises(ValueError):
        normalize_rows(frame,'AL2502',['2025-01-02'],['long_margin_ratio'])
    frame=_frame()
    with pytest.raises(ValueError):
        normalize_rows(pd.concat([frame,frame]),'AL2502',['2025-01-02'],['long_margin_ratio'])


def test_missing_provider_day_is_not_forward_filled():
    from scripts.research.subing_fact_capture import normalize_rows
    with pytest.raises(ValueError):
        normalize_rows(_frame(),'AL2502',['2025-01-02','2025-01-03'],['long_margin_ratio'])


def test_numeric_strings_and_callable_tick_are_not_instrument_repr():
    from scripts.research.subing_fact_capture import normalize_rows,instrument_payload
    rows=normalize_rows(_frame(),'AL2502',['2025-01-02'],['long_margin_ratio'])
    assert rows==[{'date':'2025-01-02','long_margin_ratio':'0.1'}]
    inst=SimpleNamespace(order_book_id='AL2502',tick_size=lambda:5,contract_multiplier=5)
    assert instrument_payload(inst,'AL2502')['tick_size']=='5'


def test_nonfinite_provider_number_rejected():
    from scripts.research.subing_fact_capture import normalize_rows
    frame=_frame()
    frame.loc[0,'long_margin_ratio']=float('nan')
    with pytest.raises(ValueError):
        normalize_rows(frame,'AL2502',['2025-01-02'],['long_margin_ratio'])
