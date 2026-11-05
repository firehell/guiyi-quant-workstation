import pytest
from scripts.research.regime_boundary_review import validate, VERSION


def test_boundary_sequence_and_first_cut_is_censored():
    public=dict(dataset_id='id',samples=[dict(id='ag')])
    base=dict(dataset_id='id',label_version=VERSION)
    assert validate(public,dict(base,answers={'ag':[dict(cut=40,choice='range')]}))['reviewed']==0
    assert validate(public,dict(base,answers={'ag':[dict(cut=40,choice='not_yet')]}))['remaining']==1
    assert validate(public,dict(base,answers={'ag':[dict(cut=i,choice='not_yet') for i in range(40,65)]}))['reviewed']==1
    for events in ([dict(cut=41,choice='range')],[dict(cut=40,choice='unknown')]):
        with pytest.raises(ValueError):
            validate(public,dict(base,answers={'ag':events}))
    with pytest.raises(ValueError):
        validate(public,dict(base,answers={'other':[]}))
    with pytest.raises(ValueError):
        validate(public,dict(base,dataset_id='other',answers={}))


def test_multiple_range_trend_transitions_are_preserved():
    public=dict(dataset_id='id',samples=[dict(id='ag')])
    events=[dict(cut=i,choice='range' if i<45 or i>=60 else 'not_yet') for i in range(40,65)]
    result=validate(public,dict(dataset_id='id',label_version=VERSION,answers={'ag':events}))
    assert result['reviewed']==1 and result['remaining']==0
