from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import pytest
from scripts.research.subing_trend import load, render


@dataclass
class Bar:
    bar_end: datetime
    trading_day: date
    open: Decimal = Decimal('100')
    high: Decimal = Decimal('102')
    low: Decimal = Decimal('98')
    close: Decimal = Decimal('101')
    volume: Decimal = Decimal('100')


class Market:
    changed = False
    missing = False
    def __init__(self):
        self.calls = 0
        self.day = date(2026,7,20)
        self.end = datetime(2026,7,20,7,tzinfo=timezone.utc)
        self.owner = SimpleNamespace(symbol='jm', contract='JM2609',start_trading_day=self.day,end_trading_day=self.day)
    def actual_dominant_segments(self, *args, **kwargs):
        return (self.owner,)
    def session_windows(self, **kwargs):
        return (SimpleNamespace(start=self.end-timedelta(hours=6),end=self.end),)
    def contract_source_evidence(self, **kwargs):
        self.calls += 1
        return {'revision': self.calls if self.changed else 1}
    def expected_contract_replay_endpoints(self, **kwargs):
        return tuple((self.end-timedelta(days=29-i),self.day-timedelta(days=29-i)) for i in range(30))
    def query_contract_trading_days(self, request):
        expected = self.expected_contract_replay_endpoints()
        bars = tuple(Bar(t,d) for t,d in expected)
        if self.missing: bars = bars[:-1]
        return SimpleNamespace(request_identity={'symbol':'jm','series_kind':'contract','contract':'JM2609','frequency':request.frequency.value},bars=bars,coverage=(bars[0].bar_end,bars[-1].bar_end))


def test_export_validated_physical_prefix():
    m = Market()
    data = load(m,m.day,m.day)
    assert len(data['sources']) == 2
    assert all(s['count'] == 30 for s in data['sources'])
    assert len([r for r in data['rows'] if r['owned']]) == 2
    assert all(r['reason'] is None for r in data['rows'] if r['owned'])


@pytest.mark.parametrize('issue', ['missing','changed'])
def test_export_fails_closed(issue):
    m = Market()
    setattr(m,issue,True)
    with pytest.raises(ValueError):
        load(m,m.day,m.day)


def test_render_escapes_script_breakout():
    page = render({'value':'</script><script>alert(1)</script>'})
    assert '</script><script>alert(1)' not in page
    assert '__DATA__' not in page


def test_error_categories_are_not_data_gaps():
    from scripts.research.subing_trend import diagnostic, TrendExportError
    from sqlalchemy.exc import OperationalError
    for code in ('TREND_SOURCE_CHANGED','TREND_MAPPING_CHANGED','TREND_REQUEST_INVALID'):
        assert diagnostic(TrendExportError(code))['code'] == code
    assert diagnostic(OperationalError('private sql',{},Exception('private secret'))) == {
        'symbol':'jm','stage':'trend_factor','code':'LOCAL_DATABASE_UNAVAILABLE'}
    assert 'private' not in str(diagnostic(RuntimeError('private secret')))


def test_repeated_owner_is_not_concatenated():
    m = Market()
    m.actual_dominant_segments = lambda *args: (m.owner,m.owner)
    with pytest.raises(ValueError):
        load(m,m.day,m.day)


def test_macd_uses_full_prefix_and_is_opt_in():
    m = Market()
    m.expected_contract_replay_endpoints = lambda **kw: tuple((m.end-timedelta(days=49-i),m.day-timedelta(days=49-i)) for i in range(50))
    plain = load(m,m.day,m.day)
    data = load(m,m.day,m.day,include_macd=True)
    assert plain['macd_version'] is None
    assert all('macd' not in r for r in plain['rows'])
    assert data['input_hash']==plain['input_hash']
    minutes = [r for r in data['rows'] if r['frequency']=='30m']
    assert len(minutes)==1  # Only one displayed bar, but MACD warmed on all 50.
    assert minutes[0]['macd']['reason'] is None
    assert minutes[0]['macd']['cross']=='NONE'
    assert all('macd' not in r for r in data['rows'] if r['frequency']=='1d')
    assert 'packages/quant-core/guiyi_quant/indicators/subing_macd.py' in data['code_hashes']
    assert 'scripts/research/subing_macd.html' in data['code_hashes']
    assert 'scripts/research/subing_trend.py' in data['code_hashes']
    assert 'packages/quant-core/guiyi_quant/indicators/subing_trend.py' in data['code_hashes']
    assert len(data['code_hashes']) == 5
    assert 'id="macdPanel"' in render(data)
    assert 'id="macdPanel"' not in render(plain)
    assert '__MACD_PANEL__' not in render(data)


def test_volume_predecessor_is_from_physical_prefix():
    m=Market()
    plain=load(m,m.day,m.day)
    data=load(m,m.day,m.day,include_volume=True)
    assert data['input_hash']==plain['input_hash']
    assert all('volume_factor' not in r for r in plain['rows'])
    owned=[r for r in data['rows'] if r['owned']]
    assert len(owned)==2
    for r in owned:
        v=r['volume_factor']
        assert v['current']==Decimal('100') and v['previous']==Decimal('100')
        assert v['previous_end']==m.end-timedelta(days=1)
        assert v['ratio']==1 and v['reason'] is None
        assert v['effective'] is False
    assert 'id="volumePanel"' in render(data)
    assert 'id="volumePanel"' not in render(plain)
    assert '__VOLUME_PANEL__' not in render(data)
    assert 'packages/quant-core/guiyi_quant/indicators/subing_volume.py' in data['code_hashes']


def test_all_factors_share_one_input_and_separate_versions():
    m=Market()
    data=load(m,m.day,m.day,include_macd=True,include_volume=True)
    assert len(data['code_hashes'])==7
    assert data['volume_version']=='subing_volume_d1_gt1_m30_tiers_v2'
    assert data['macd_version']=='subing_macd12_26_9_segment_cross_v3'
    page=render(data)
    assert '2.1 + 2.2 + 2.3' in page
    assert '__MACD_PANEL__' not in page and '__VOLUME_PANEL__' not in page


def test_price_uses_shared_ema_and_is_optional():
    m=Market()
    plain=load(m,m.day,m.day)
    data=load(m,m.day,m.day,include_price=True)
    assert data['input_hash']==plain['input_hash']
    assert all('price_factor' not in r for r in plain['rows'])
    assert all('price_factor' not in r for r in data['rows'] if r['frequency']=='1d')
    r=next(r for r in data['rows'] if r['frequency']=='30m')
    assert r['price_factor']['ema21']==Decimal(str(r['ema21']))
    assert r['price_factor']['relation']=='ON'
    assert r['price_factor']['near_above_ema'] is False
    assert r['price_factor']['below_ema'] is False
    assert 'id="pricePanel"' in render(data)
    assert 'id="pricePanel"' not in render(plain)
    assert '__PRICE_PANEL__' not in render(data)
    assert len(data['code_hashes'])==5


def test_joint_uses_strict_before_daily_and_physical_predecessor():
    m=Market()
    data=load(m,m.day,m.day,include_joint=True)
    r=next(r for r in data['rows'] if r['frequency']=='30m')
    j=r['joint']
    assert datetime.fromisoformat(j['daily_time'])==m.end-timedelta(days=1)
    assert j['exits']['previous_end']==m.end-timedelta(days=1)
    assert j['exits']['previous_low']==Decimal('98')
    assert j['exits']['below_previous_low'] is False
    assert j['entry']['checks']['daily_allows_long'] is True
    assert data['price_version'] and data['volume_version'] and data['macd_version']
    assert 'id="jointPanel"' in render(data)
    plain=load(m,m.day,m.day)
    assert 'id="jointPanel"' not in render(plain) and '__JOINT_PANEL__' not in render(plain)
    assert all('joint' not in r for r in plain['rows'])
    assert 'joint' not in next(r for r in data['rows'] if r['frequency']=='1d')
    assert data['input_hash']==plain['input_hash']


def test_joint_excludes_same_timestamp_daily_even_when_it_changes():
    from dataclasses import replace
    m=Market()
    original=m.query_contract_trading_days
    before=load(m,m.day,m.day,include_joint=True)
    def changed(request):
        result=original(request)
        if request.frequency.value=='1d':
            result.bars=(*result.bars[:-1],replace(result.bars[-1],high=Decimal('500'),close=Decimal('500')))
        return result
    m.query_contract_trading_days=changed
    after=load(m,m.day,m.day,include_joint=True)
    a=next(r['joint'] for r in before['rows'] if r['frequency']=='30m')
    b=next(r['joint'] for r in after['rows'] if r['frequency']=='30m')
    assert a==b
