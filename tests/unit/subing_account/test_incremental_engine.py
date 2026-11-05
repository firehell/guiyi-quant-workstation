from dataclasses import replace
from datetime import timedelta
from guiyi_quant.subing_account import AccountEngine,replay
from tests.unit.subing_account.test_account import inputs

def test_incremental_and_batch_exact_parity():
    xs,obs=inputs([100,101,102,99,98,98])
    old=replay(xs,obs,'incremental')
    a=AccountEngine('JM2609','jm',xs[0].facts.multiplier,'incremental')
    for x in xs:a.step(x,obs[x.bar.bar_end])
    assert a.snapshot()==old

def test_delayed_knowledge_cannot_fill_before_later_completed_bar():
    xs,obs=inputs([100,101,102,102,102,102],frames={0:dict(near_zero_golden=True)})
    a=AccountEngine('JM2609','jm',xs[0].facts.multiplier,'observed',live=True)
    for i,x in enumerate(xs):
        at=x.bar.bar_end+timedelta(seconds=90 if i==0 else 60)
        x=replace(x,bar=replace(x.bar,confirmed_at=at))
        a.step(x,obs[x.bar.bar_end],observed_at=at)
    assert a.fills
    assert a.fills[0]['fill_bar_end']>a.fills[0]['decision_at']
    assert a.fills[0]['fill_at']>a.fills[0]['decision_at']
