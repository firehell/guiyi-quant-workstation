from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from guiyi_quant.indicators.subing_volume import initial_state, observe


def run(values, frequency='30m', state=None, start=0):
    state = state or initial_state('JM2701',frequency)
    out = []
    for i,v in enumerate(values,start):
        state,p = observe(state,contract='JM2701',frequency=frequency,
            bar_end=datetime(2026,8,1,tzinfo=timezone.utc)+timedelta(minutes=30*i),volume=v)
        out.append(p)
    return state,out


def test_predecessor_reset_and_zero():
    _,out = run([Decimal('10'),None,Decimal('30'),Decimal('0'),Decimal('20')])
    assert out[0].reason=='PREVIOUS_UNAVAILABLE'
    assert out[1].reason=='INPUT_INVALID'
    assert out[2].reason=='PREVIOUS_UNAVAILABLE'  # Never compare to volume before the bad bar.
    assert out[3].ratio==0
    assert out[4].previous==0 and out[4].ratio is None


def test_prefix_and_incremental():
    values=list(map(Decimal,['100','200','50','300','600','600']))
    s,prefix=run(values[:3])
    _,tail=run(values[3:],state=s,start=3)
    _,full=run(values)
    assert prefix+tail==full
    assert full[1].ratio==2
    assert full[2].previous==200
    _,changed=run(values[:3]+[Decimal('99999')]*3)
    assert changed[:3]==prefix


@pytest.mark.parametrize('value',[Decimal('-1'),Decimal('NaN'),Decimal('Infinity'),1.0])
def test_invalid_volume(value):
    _,out=run([Decimal('10'),value])
    assert out[-1].reason=='INPUT_INVALID'
    assert out[-1].effective is None


def test_identity_and_time():
    s,_=run([Decimal('10')])
    kw=dict(contract='JM2701',frequency='30m',bar_end=s.last_end,volume=Decimal('20'))
    with pytest.raises(ValueError,match='TIME'):observe(s,**kw)
    kw.update(bar_end=s.last_end+timedelta(minutes=30),contract='JM2609')
    with pytest.raises(ValueError,match='IDENTITY'):observe(s,**kw)
    with pytest.raises(ValueError,match='IDENTITY'):initial_state('JM2701','15m')


@pytest.mark.parametrize('frequency,previous,current,effective',[
    ('1d','100','100',False),('1d','100','100.000001',True),('1d','100','99',False),
    ('30m','100','199.999999',False),('30m','100','200',True),('30m','100','200.000001',True),
    ('30m','100','150',False),('30m','100','300',True),
    ('1d','0','0',False),('1d','0','1',True),('30m','0','0',True),('30m','0','1',True),
])
def test_frequency_rules_without_ratio_rounding(frequency,previous,current,effective):
    _,out=run([Decimal(previous),Decimal(current)],frequency=frequency)
    assert out[0].effective is None
    assert out[1].effective is effective
    if previous=='0':assert out[1].ratio is None


def test_daily_and_minute_are_independent():
    _,daily=run(list(map(Decimal,['100','150'])),'1d')
    _,minute=run(list(map(Decimal,['100','150'])),'30m')
    assert daily[-1].effective is True
    assert minute[-1].effective is False
