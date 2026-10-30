from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from contextlib import contextmanager
from app.simnow_portfolio_market import PortfolioMarket


def test_audit_boundary_uses_earliest_actual_completed_endpoint(monkeypatch):
    now=datetime(2026,10,30,5,40,tzinfo=UTC)
    @contextmanager
    def sessions():yield SimpleNamespace(execute=lambda *_:None)
    class Resolver:
        def __init__(self,db):pass
        def resolve(self,product,at):return SimpleNamespace(phase=__import__('app.market_data.market_phase',fromlist=['MarketPhase']).MarketPhase.TRADING,trading_day=now.date(),current_session=SimpleNamespace(start=now-timedelta(minutes=10),end=now+timedelta(minutes=80)))
    monkeypatch.setattr('app.simnow_portfolio_market.MarketPhaseResolver',Resolver)
    monkeypatch.setattr('app.market_data.composition.build_market_data_service',lambda db:SimpleNamespace(session_windows=lambda **kw:(SimpleNamespace(),)))
    monkeypatch.setattr('app.market_data.aggregation.expected_intraday_ends',lambda *_:(now-timedelta(minutes=10),now+timedelta(minutes=50)))
    market = object.__new__(PortfolioMarket)
    market.products = ('FG', 'AG')
    market._session_factory = sessions
    assert market.next_audit_boundary(now)==now+timedelta(minutes=50)
