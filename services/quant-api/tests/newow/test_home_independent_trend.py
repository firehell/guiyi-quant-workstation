from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from guiyi_quant.newow.product_contracts import ProductBar
from tests.newow.test_oscillation_channel import golden_bars


def bars(closes):
    base = golden_bars()[0]
    return tuple(ProductBar(replace(base, trading_day=base.trading_day + timedelta(days=i),
        bar_end=base.bar_end + timedelta(days=i), open=Decimal(c), high=Decimal(c)+1,
        low=Decimal(c)-1, close=Decimal(c)), '1d') for i,c in enumerate(closes))


def calculate(values, anchor=None):
    from guiyi_quant.newow.home_independent_trend import calculate_home_trend
    return calculate_home_trend(values, anchor or values[-1])


def test_ma60_direction_equality_decimal_and_last_sixty_only():
    for last, direction in [('101','bull'),('100','bull'),('99','bear')]:
        value=calculate(bars(['100']*59+[last]))
        assert value['direction']==direction
        assert value['formula_version']=='guiyi_home_close_ma60_v1'
        assert value['page_parity'] is False and value['approximate'] is True and value['executable'] is False
        assert value['status']=='ready' and value['sample_count']==60
    assert calculate(bars(['100000']*20+['100']*60))['ma60']==Decimal(100)
    assert calculate(bars(['9007199254740993.125']*59+['9007199254740993.124999']))['direction']=='bear'


def test_warmup_owner_reset_future_prefix_and_weekly_are_not_substituted():
    values=bars(['100']*80)
    assert calculate(values[:59])['status']=='warming'
    changed=values[:60]+tuple(replace(v, calculation_segment_id='new') for v in values[60:])
    assert calculate(changed)['status']=='warming'
    assert calculate(changed)['sample_count']==20
    assert calculate(values, values[59])==calculate(values[:60])
    assert calculate(tuple(replace(v,frequency='1w') for v in values)) is None
    foreign=replace(values[-1],bar=replace(values[-1].bar,physical_contract='OTHER'))
    assert calculate(values,foreign)['status']=='unavailable'
    assert calculate(values)['input_sha256'] != calculate(tuple(replace(v,bar=replace(v.bar,source_identity='different')) for v in values))['input_sha256']
