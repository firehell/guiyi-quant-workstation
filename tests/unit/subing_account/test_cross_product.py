from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
import pytest
from test_account import inputs
from guiyi_quant.subing_account import replay
from guiyi_quant.subing_decision import DecisionModel, _digest


def transferred(product,tick,multiplier):
    xs,obs=inputs([100,102,104,106,108,110],frames={0:dict(near_zero_golden=True),3:dict(below_ema=True)})
    contract=product.upper()+'2609'
    xs=[replace(x,bar=replace(x.bar,product=product,physical_contract=contract,high=x.bar.close+D(2),low=x.bar.close-D(2)),facts=replace(x.facts,physical_contract=contract,tick_size=D(tick),multiplier=D(multiplier))) for x in xs]
    obs={k:dict(v,contract=contract) for k,v in obs.items()}
    return xs,obs


@pytest.mark.parametrize('product,tick,multiplier',[('ma','1','10'),('ta','2','5')])
@pytest.mark.parametrize('slip',[1,2,3])
def test_transfer_actual_contract_units_and_restore(product,tick,multiplier,slip):
    xs,obs=transferred(product,tick,multiplier)
    r=replay(xs,obs,'transfer',execution_model='theoretical_open',slippage_ticks=slip)
    assert r['contract']==product.upper()+'2609'
    assert r['version']==f'subing_{product}30_account_theoretical_open_v2_slip{slip}_transfer_v1'
    assert r['decision_state']['version']==f'subing_{product}30_decision_v6_transfer_v1'
    assert D(r['fills'][0]['price'])==D(104)+D(tick)*slip
    assert D(r['fills'][-1]['price'])==D(110)-D(tick)*slip
    expected=(D(r['fills'][-1]['price'])-D(r['fills'][0]['price']))*D(multiplier)-D(6)
    assert D(r['net_pnl'])==expected
    opening=next(a for t in r['trace'] for a in t['actions'] if a['kind']=='OPEN')
    assert D(opening['initial_stop'])==D(67)
    m=DecisionModel.restore(r['decision_checkpoint'])
    assert m.state()==r['decision_state'] and m.checkpoint()==r['decision_checkpoint']
    wrong=deepcopy(r['decision_checkpoint']);wrong['version']='subing_jm30_decision_v6';wrong['sha256']=_digest({k:v for k,v in wrong.items() if k!='sha256'})
    with pytest.raises(ValueError):DecisionModel.restore(wrong)


def test_mismatched_product_and_contract_rejected():
    xs,obs=transferred('ma','1','10')
    xs[1]=replace(xs[1],bar=replace(xs[1].bar,product='ta'))
    with pytest.raises(ValueError,match='PHYSICAL_IDENTITY'):replay(xs,obs,'r')


@pytest.mark.parametrize('kw',[dict(research_profile='window4'),dict(risk_research_profile='round1500')])
def test_no_cross_product_tuning(kw):
    xs,obs=transferred('ta','2','5')
    with pytest.raises(ValueError,match='CROSS_PRODUCT_PARAMETER'):replay(xs,obs,'r',execution_model='theoretical_open',**kw)
