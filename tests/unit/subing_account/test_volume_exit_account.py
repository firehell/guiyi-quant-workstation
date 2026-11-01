from dataclasses import replace
from decimal import Decimal as D

import pytest

from guiyi_quant.subing_account import replay
from tests.unit.subing_account.test_account import inputs
from tests.unit.subing_account.test_account_bidirectional import mirror_inputs


@pytest.mark.parametrize('short',[False,True])
def test_low_tier_target_full_close_is_next_executable_minute(short):
    # Filled long 110.5 => fixed R24.5 => target135, short mirrors.
    xs,obs=inputs([110,110,135,134,133],frames={0:dict(near_zero_golden=True,ema21='100',low='99',volume_tier='TIER_1'),2:dict(volume_tier='TIER_3')})
    if short:xs,obs=mirror_inputs(xs,obs)
    xs[3]=replace(xs[3],bar=replace(xs[3].bar,volume=D('0')))
    r=replay(xs,obs,'v')
    assert [f['action'] for f in r['fills']]==['OPEN','CLOSE']
    assert r['fills'][1]['decision_at']==xs[2].bar.bar_end.isoformat()
    assert r['fills'][1]['fill_at']==xs[4].bar.bar_end.isoformat()
    assert r['fills'][1]['reasons']==['PROFIT_1R_TIER1_CLEAR']
    assert r['execution_events'][0]['reason']=='ZERO_VOLUME'
    assert r['status']=='COMPLETED'
    assert r['closed_rounds'][0]['net_pnl']=='1314.0'


def test_higher_tier_single_base_does_not_close_at_target():
    for tier in ('TIER_2','TIER_3'):
        xs,obs=inputs([110,110,135,134],frames={0:dict(near_zero_golden=True,ema21='100',low='99',volume_tier=tier),2:dict(volume_tier='TIER_1')})
        r=replay(xs,obs,'v')
        assert len(r['fills'])==1 and r['status']=='OPEN'
        assert r['decision_state']['entry_volume_tier']==tier
