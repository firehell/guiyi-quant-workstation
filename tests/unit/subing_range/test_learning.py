from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pickle

import pytest

from scripts.research.regime_learning_core import (
    BlindPool, blind_payload, reference_label, temporal_split,
)
from guiyi_quant.indicators import subing_trend, subing_range


def test_reference_price_labels_and_unknown():
    assert reference_label(list(range(100,140)),2)['label']=='TREND_UP'
    assert reference_label(list(range(140,100,-1)),2)['label']=='TREND_DOWN'
    assert reference_label([100.0]*40,2)['label']=='RANGE'
    assert reference_label([100.+i%2 for i in range(40)],2)['label']=='RANGE'
    assert reference_label([100.+i*.01 for i in range(40)],2)['label']=='DISPUTED'
    for values,atr in [([100.]*39,2),([100.]*40,0),([100.]*40,None),([100.]*39+[float('nan')],2)]:
        assert reference_label(values,atr)['label']=='UNKNOWN'


def test_reference_prefix_future_perturbation():
    closes=[100+i*.25+(i%3)*.1 for i in range(150)]
    labels=[reference_label(closes[:i+1],2) for i in range(len(closes))]
    for cut in (40,64,100):
        changed=closes[:cut]+[10000.]*100
        assert [reference_label(changed[:i+1],2) for i in range(cut)]==labels[:cut]


def test_split_global_order_no_random_rows():
    days=[(datetime(2020,1,1)+timedelta(days=i)).date().isoformat() for i in range(100)]
    split=temporal_split(days[::-1]+days)
    assert split['test_from']==days[80]
    assert len(split['folds'])==3
    for fold in split['folds']:
        assert fold['train_through']<fold['validation_from']<=fold['validation_through']<split['test_from']
    with pytest.raises(ValueError):
        temporal_split(days[:10])


def sample_bars(day='2020-01-01'):
    start=datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    return [dict(time=(start+timedelta(minutes=30*i)).isoformat(),day=day,open=100.,high=101.,low=99.,close=100.) for i in range(64)]


def test_blind_pool_excludes_test_and_hides_reference():
    pool=BlindPool('2021-01-01')
    for freq in ('1d','30m','60m'):
        for label in ('TREND_UP','TREND_DOWN','RANGE','DISPUTED'):
            for i in range(12):
                pool.offer(symbol=f'p{i}',frequency=freq,contract=f'C{i}{label}',sector=f's{i%4}',
                           label=label,bars=sample_bars(f'2020-01-{i+1:02d}'))
    before=pickle.dumps(pool.pools)
    pool.offer(symbol='holdout',frequency='30m',contract='H',sector='x',label='RANGE',bars=sample_bars('2021-01-01'))
    assert pickle.dumps(pool.pools)==before
    selected,deficits=pool.select()
    assert len(selected)==90 and not deficits
    public=blind_payload(selected,'abc')
    for s in public['samples']:
        assert set(s)=={'id','symbol','frequency','contract','bars'}
        assert all(set(b)=={'time','day','open','high','low','close'} for b in s['bars'])
    assert selected==pool.select()[0]


def test_insufficient_samples_remain_explicit():
    selected,deficits=BlindPool('2021-01-01').select()
    assert selected==[] and sum(deficits.values())==90


def run_frequency(frequency):
    trend=subing_trend.initial_state('JM2701',frequency)
    state=subing_range.initial_state('JM2701',frequency)
    output=[]
    for i in range(120):
        c=100+i*.1+(i%4)*.1
        at=datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(hours=i)
        trend,tp=subing_trend.step(trend,contract='JM2701',frequency=frequency,bar_end=at,high=c+1,low=c-1,close=c)
        state,rp=subing_range.step(state,contract='JM2701',frequency=frequency,bar_end=at,
            high=Decimal(str(c+1)),low=Decimal(str(c-1)),close=Decimal(str(c)),
            atr=Decimal(str(tp.atr14)) if tp.atr14 is not None else None,trend_direction=tp.direction)
        output.append((tp,rp.regime,rp.er,rp.chop))
    return output


def test_60m_uses_identical_algorithm_without_changing_existing_periods():
    assert run_frequency('60m')==run_frequency('30m')==run_frequency('1d')


def test_seen_case_and_cross_boundary_windows_never_become_holdout():
    from scripts.research.regime_learning_core import sample_partition
    split={'test_from':'2026-01-01','test_through':'2026-10-30',
           'known_development':[{'symbol':'jm','since':'2026-07-13','through':'2026-10-30'}]}
    assert sample_partition(symbol='jm',days=['2026-08-01']*64,splits=split)=='CASE_REGRESSION'
    assert sample_partition(symbol='rb',days=['2026-08-01']*64,splits=split)=='SEALED_TEST'
    assert sample_partition(symbol='rb',days=['2025-12-31']*32+['2026-01-01']*32,splits=split)=='PURGED_BOUNDARY'
    assert sample_partition(symbol='rb',days=['2025-12-31']*64,splits=split)=='DEVELOPMENT'
    assert sample_partition(symbol='rb',days=['2025-12-31']*63,splits=split)=='INELIGIBLE'


def test_owner_review_identity_partial_and_no_automatic_training():
    from scripts.research.regime_review import validate_review
    key={'dataset_id':'abc','references':[{'id':'s1','symbol':'jm','frequency':'1d','reference':'TREND_UP'},
        {'id':'s2','symbol':'rb','frequency':'30m','reference':'DISPUTED'}]}
    review={'dataset_id':'abc','label_version':'v1','answers':{'s1':{'answer':'UNCERTAIN','note':'转折不清晰'}}}
    result=validate_review(key,review,'v1')
    assert result['remaining']==1 and result['owner_uncertain']==1 and not result['training_permitted']
    assert result['status']=='WAIT_OWNER_LABEL_DECISION'
    for bad in ({**review,'dataset_id':'other'},{**review,'label_version':'other'},
                {**review,'answers':{'unknown':{'answer':'RANGE','note':''}}},
                {**review,'answers':{'s1':{'answer':'BUY','note':''}}}):
        with pytest.raises(ValueError):
            validate_review(key,bad,'v1')
