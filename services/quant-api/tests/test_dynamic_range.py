from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from app.market_data.dynamic_range import chart_window


@dataclass(frozen=True)
class Bar:
    bar_end: datetime
    trading_day: object
    open: D = D('100')
    high: D = D('101')
    low: D = D('99')
    close: D = D('100')


@dataclass(frozen=True)
class Result:
    request_identity: dict
    bars: tuple
    coverage: tuple | None


class Market:
    def __init__(self):
        start=datetime(2026,1,1,tzinfo=timezone.utc)
        self.bars=tuple(Bar(start+timedelta(minutes=30*i),start.date(),close=D('99.5') if i%2 else D('100.5')) for i in range(100))
        self.expected=self.bars
        self.calls=0
        self.changed=False
    def contract_source_evidence(self, **kw):
        self.calls+=1
        return dict(contract='JM2701',frequency='30m',listed_date='2025-01-01',expired_date='2027-01-01',
            partitions=[dict(year=2026,month=1,revision=self.calls if self.changed else 1)])
    def query_page_inclusive(self, q):
        assert q.before <= self.expected[-1].bar_end, 'no artificial timestamp past coverage'
        return SimpleNamespace(bars=tuple(b for b in self.bars if b.bar_end<=q.before)[-1:])
    def expected_contract_replay_endpoints(self, **kw):
        return tuple((b.bar_end,b.trading_day) for b in self.expected if b.bar_end<=kw['cutoff'])
    def query_contract_trading_days(self, q):
        return Result(dict(symbol='jm',contract='JM2701',frequency=q.frequency.value,series_kind='contract'),self.bars,(self.bars[0].bar_end,self.bars[-1].bar_end))


def query(m,start=50,end=80):
    return chart_window(m,symbol='jm',contract='JM2701',frequency='30m',start=m.expected[start].bar_end,end=m.expected[end].bar_end)


def test_prepend_and_different_end_share_exact_points():
    m=Market()
    original=query(m)
    expanded=query(m,30,90)
    assert original['points']==expanded['points'][20:51]
    assert original['prefix_start']==m.bars[0].bar_end
    assert original['points'][0]['box']['confirmed_at'] < m.bars[50].bar_end
    # The query reads a complete day, but that day's future suffix cannot leak.
    m.bars=m.bars[:81]+tuple(replace(b,high=D('1000'),close=D('1000')) for b in m.bars[81:])
    assert query(m)['points']==original['points']


@pytest.mark.parametrize('issue',['gap','source','endpoint','identity'])
def test_no_partial_or_guessing_on_invalid_sources(issue):
    m=Market()
    if issue=='gap':
        m.bars=m.bars[:10]+m.bars[11:]
    if issue=='source':
        m.changed=True
    if issue=='endpoint':
        m.bars=m.bars[:80]
    if issue=='identity':
        old=m.query_contract_trading_days
        m.query_contract_trading_days=lambda q:replace(old(q),request_identity={})
    with pytest.raises(ValueError):
        query(m)


def test_missing_window_or_unsupported_frequency_fail_before_read():
    m=Market()
    with pytest.raises(ValueError,match='FREQUENCY_UNSUPPORTED'):
        chart_window(m,symbol='jm',contract='JM2701',frequency='1m',start=m.bars[0].bar_end,end=m.bars[-1].bar_end)
    assert m.calls==0
    with pytest.raises(ValueError,match='WINDOW_INVALID'):
        chart_window(m,symbol='jm',contract='JM2701',frequency='30m',start=m.bars[0].bar_end+timedelta(seconds=1),end=m.bars[-1].bar_end)


def test_api_readonly_wire_and_safe_errors(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import market
    from app.db.session import get_db
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    app=FastAPI()
    app.include_router(market.router)
    def db():
        with Session(engine,autoflush=False) as s:
            yield s
    app.dependency_overrides[get_db]=db
    m=Market()
    monkeypatch.setattr(market,'build_market_data_service',lambda s,**kwargs:m)
    params=dict(symbol='jm',contract='JM2701',frequency='30m',start=m.bars[50].bar_end.isoformat(),end=m.bars[80].bar_end.isoformat())
    with TestClient(app) as client:
        r=client.get('/api/v1/market/indicators/dynamic-range',params=params)
        assert r.status_code==200,r.text
        assert r.json()['points'][0]['high']=='101'
        assert r.json()['points'][0]['box']['upper']=='101'
        def fail(s,**kwargs): raise RuntimeError('private password sql address')
        monkeypatch.setattr(market,'build_market_data_service',fail)
        r=client.get('/api/v1/market/indicators/dynamic-range',params=params)
        assert r.status_code==503 and r.json()=={'detail':{'code':'DYNAMIC_RANGE_UNAVAILABLE'}}
    engine.dispose()


def test_budget_checked_after_final_source_verification():
    from app.market_data.dynamic_range import DynamicRangeError
    m=Market()
    def check():
        if m.calls>=2:
            raise DynamicRangeError('DYNAMIC_RANGE_BUDGET_EXCEEDED')
    with pytest.raises(DynamicRangeError,match='BUDGET_EXCEEDED'):
        chart_window(m,symbol='jm',contract='JM2701',frequency='30m',start=m.bars[50].bar_end,end=m.bars[80].bar_end,check=check)


def test_source_fingerprinting_checks_cancel_between_partitions():
    from app.market_data.market_data_service import MarketDataService
    calls=[]
    part=SimpleNamespace(year=2026,month=1,row_count=1,coverage_start=None,coverage_end=None,
                         source_coverage_start=None,source_coverage_end=None,source_quality_sha256='q')
    fact=SimpleNamespace(listed_date=datetime(2025,1,1).date(),expired_date=datetime(2027,1,1).date())
    catalog=SimpleNamespace(contract_fact=lambda *a:fact,partitions_before=lambda *a:[part,part])
    def fingerprint(p):
        calls.append('read')
        return 'a'*64
    def check():
        if calls:
            raise TimeoutError('budget')
    m=MarketDataService(catalog,SimpleNamespace(verified_partition_fingerprint=fingerprint),check_cancelled=check)
    with pytest.raises(TimeoutError):
        from app.market_data.domain import BarFrequency
        m.contract_source_evidence(symbol='jm',contract='JM2701',frequency=BarFrequency.M30,before=datetime(2026,1,2,tzinfo=timezone.utc))
    assert calls==['read']


def test_exact_last_published_endpoint_uses_inclusive_cursor():
    m=Market()
    result=query(m,50,99)
    assert len(result['points'])==50
    assert result['points'][-1]['time']==m.bars[-1].bar_end.isoformat()


def test_sixty_minute_prefix_is_available_and_stable():
    m=Market()
    original=m.contract_source_evidence
    m.contract_source_evidence=lambda **kw:{**original(**kw),'frequency':'60m'}
    def window(start,end):
        return chart_window(m,symbol='jm',contract='JM2701',frequency='60m',
                            start=m.expected[start].bar_end,end=m.expected[end].bar_end)
    a,b=window(50,80),window(30,90)
    assert a['frequency']=='60m' and a['version']=='subing_dynamic_range_v2'
    assert a['points']==b['points'][20:51]
