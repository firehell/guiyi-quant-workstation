from scripts.research.regime_calibration import overlaps, select
from scripts.research.regime_learning_core import BlindPool
from tests.unit.subing_range.test_learning import sample_bars


def test_exclusion_is_cross_frequency_and_contract():
    a = dict(symbol='ag', frequency='1d', contract='AG1', bars=sample_bars())
    b = dict(symbol='ag', frequency='60m', contract='AG2', bars=sample_bars())
    assert overlaps(a,b)
    assert not overlaps(a,dict(b,symbol='cu'))
    assert not overlaps(a,dict(b,bars=sample_bars('2020-02-01')))


def test_fresh_selection_balanced_deterministic_no_overlap():
    pool=BlindPool('2021-01-01')
    for frequency in ('1d','30m','60m'):
        for label in ('TREND_UP','TREND_DOWN','RANGE','DISPUTED'):
            for i in range(30):
                pool.offer(symbol=f'p{i}',frequency=frequency,contract=f'C{i}',sector=f's{i%4}',
                           label=label,bars=sample_bars(f'2020-01-{i%28+1:02d}'))
    prior=[dict(symbol='p0',bars=sample_bars())]
    selected, deficits=select(pool,prior)
    assert len(selected)==24 and not deficits
    assert select(pool,prior)==(selected,deficits)
    assert not any(overlaps(s,p) for s in selected for p in prior)
    assert not any(overlaps(s,p) for i,s in enumerate(selected) for p in selected[:i])
    assert all(sum(s['frequency']==f for s in selected)==8 for f in ('1d','30m','60m'))


def test_insufficient_samples_are_explicit():
    selected, deficits=select(BlindPool('2021-01-01'),[])
    assert selected==[] and sum(deficits.values())==24


def test_prior_content_not_trusted_from_identity_alone():
    import copy
    import pytest
    from scripts.research.regime_calibration import validate_prior
    from scripts.research.regime_learning_core import blind_payload
    pool=BlindPool('2021-01-01')
    for frequency in ('1d','30m','60m'):
        for label in ('TREND_UP','TREND_DOWN','RANGE','DISPUTED'):
            for i in range(12):
                pool.offer(symbol=f'p{i}',frequency=frequency,contract=f'C{i}{label}',sector=f's{i%4}',
                           label=label,bars=sample_bars(f'2020-01-{i+1:02d}'))
    public=blind_payload(pool.select()[0],'source')
    validate_prior(pool,public,'source')
    for mutation in ('delete','price','identity'):
        bad=copy.deepcopy(public)
        if mutation=='delete':
            bad['samples']=[]
        elif mutation=='price':
            bad['samples'][0]['bars'][0]['close']+=1
        else:
            bad['dataset_id']='other'
        with pytest.raises(ValueError,match='PRIOR_CONTENT_CHANGED'):
            validate_prior(pool,bad,'source')


def test_public_identity_changes_with_ema_or_price():
    import copy
    from scripts.research.regime_calibration import content_hash
    sample=dict(id='a',symbol='ag',frequency='60m',contract='AG1',bars=sample_bars(),ema21=[100.]*64)
    original=content_hash([sample])
    for field in ('ema','price'):
        changed=copy.deepcopy(sample)
        if field=='ema':
            changed['ema21'][-1]+=1
        else:
            changed['bars'][-1]['close']+=1
        assert content_hash([changed])!=original
