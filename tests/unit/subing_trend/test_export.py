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
