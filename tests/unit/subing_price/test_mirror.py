from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from guiyi_quant.indicators.subing_price import PullbackState, observe
from guiyi_quant.indicators.subing_macd import cross_point


def test_rebound_qualification_requires_down_context_and_breaks_later():
    base=datetime(2026,7,13,tzinfo=timezone.utc)
    long,short=PullbackState('JM2609'),PullbackState('JM2609',side='SHORT')
    for i,(high,low,close,direction) in enumerate([('110','105','108','UP'),('104','100','103','NEUTRAL'),('106','102','105','UP'),('99','97','98','DOWN')]):
        args=dict(contract='JM2609',bar_end=base+timedelta(minutes=30*i),high=D(high),low=D(low),close=D(close),ema21=D('100'),atr14=D('10'),trend_direction=direction)
        long,a=observe(long,**args)
        args.update(high=D('500')-D(low),low=D('500')-D(high),close=D('500')-D(close),ema21=D('400'),trend_direction={'UP':'DOWN','DOWN':'UP'}.get(direction,direction))
        short,b=observe(short,**args,side='SHORT')
        for key in ('touch','hold','qualified_hold','breakout','invalidated','background_reset'):
            assert a[key]==b[key]
        if a['armed_high'] is not None:assert a['armed_high']+b['armed_high']==D('500')
    with pytest.raises(ValueError,match='IDENTITY'):
        observe(long,**args,side='SHORT')


@pytest.mark.parametrize('height',[-18,-17,-4,0,4,17,18])
def test_short_macd_cross_geometry_mirrors_long_inclusive_axis_strict_extreme(height):
    a=cross_point((height-1,height),(height+1),height)
    b=cross_point((-height+1,-height),(-height-1),-height)
    assert a.near_zero_golden==b.near_zero_death
    c=cross_point((height+1,height),(height-1),height)
    d=cross_point((-height-1,-height),(-height+1),-height)
    assert c.high_death==d.low_golden
    assert d.low_golden==(height>17)
