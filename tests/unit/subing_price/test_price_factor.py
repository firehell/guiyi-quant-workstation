from decimal import Decimal
import pytest
from guiyi_quant.indicators.subing_price import price_point


@pytest.mark.parametrize('close,relation,near',[
    ('99.999999','BELOW',False),('100','ON',False),('100.000001','ABOVE',True),
    ('109.999999','ABOVE',True),('110','ABOVE',False),('110.000001','ABOVE',False),
])
def test_price_distance_boundaries(close,relation,near):
    p=price_point(Decimal(close),Decimal('100'))
    assert p.relation==relation and p.near_above_ema is near
    assert p.above_ema is (relation=='ABOVE')
    assert p.below_ema is (relation=='BELOW')
    assert p.distance==Decimal(close)-Decimal('100')


def test_warmup_and_invalid_are_unknown():
    p=price_point(Decimal('100'),None)
    assert p.reason=='WARMUP' and p.above_ema is None
    for close,ema in [(Decimal('NaN'),Decimal('100')),(Decimal('100'),Decimal('Infinity')),(Decimal('0'),Decimal('100'))]:
        p=price_point(close,ema)
        assert p.reason=='INPUT_INVALID' and p.near_above_ema is None
