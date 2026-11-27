"""Constructed SuBing account inputs shared by the Paper tests."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

from guiyi_quant.paper import FeeSchedule
from guiyi_quant.subing_inputs import ExecutionBar, ExecutionFacts, StrategyBar

BASE=datetime(2026,7,13,1,tzinfo=timezone.utc)
FEES=FeeSchedule(D('0'),D('2'),D('0'),D('3'),D('0'),D('4'),'test-fees')


def inputs(prices, *, frames=None):
    xs=[];obs={};frames=frames or {}
    for i,price in enumerate(prices):
        end=BASE+timedelta(minutes=i)
        p=D(str(price))
        facts=ExecutionFacts('JM2609',end.date(),D('.5'),D('60'),D('100'),D('.1'),D('.1'),D('500'),D('1'),FEES,'test-facts')
        bar=StrategyBar('jm','JM2609','1m',end,end.date(),p,p+D('1'),p-D('1'),p,D('100'),None,
            f'test-bar-{i}',end,True,BASE-timedelta(minutes=1),BASE+timedelta(hours=4))
        xs.append(ExecutionBar(bar,facts))
        m=None
        if i in frames:
            m=dict(high='140',near_zero_death=False,low_golden=False,above_previous_high=False,qualified_rebound=False,rebound_low=None,rebound_invalidated=True,ema21='90',low='80',near_zero_golden=False,minute_angle='2',above_ema=True,volume_effective=True,volume_tier='TIER_2',
                below_previous_low=False,high_death=False,below_ema=False,
                qualified_pullback=False,pullback_high=None,pullback_invalidated=False)
            m.update(frames[i])
        obs[end]=dict(event_id=f'o{i}',kind='observe',at=end.isoformat(),contract='JM2609',trading_day=end.date().isoformat(),
            close=str(p),daily_direction='UP',daily_at=(BASE-timedelta(days=1)).isoformat(),day_end_window=False,m30=m)
    return xs,obs
