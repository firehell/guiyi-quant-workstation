from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from app.alerts.evaluators import AlertEvaluation, HtdyOriginalEvaluator
from app.market_data.subing_reference import SubingReferenceError
from app.reference_trading.signal_window import (
    SignalWindowQuery, historical_window_navigation, query_signal_window,
)
from guiyi_quant.subing_reference import ReferenceBar, ReferenceSegment
from test_htdy_history import segment


class Service:
    active_products = {"jm"}
    check_cancelled = staticmethod(lambda: None)
    now = staticmethod(lambda: datetime(2026,9,3,tzinfo=UTC))
    historical_storage_start = staticmethod(lambda symbol: date(2023,1,1))
    historical_metadata_evidence = staticmethod(lambda **kwargs: {"revision":"one"})
    def __init__(self, count=80):
        self.original = segment(count)
        self.market_data = self
    historical_input_bound = staticmethod(lambda **kwargs: (118140, 483901440))
    def query_page(self, request):
        from types import SimpleNamespace
        bars=tuple(bar for bar in self.original.bars if bar.bar_end < request.before)
        return SimpleNamespace(bars=bars[-request.limit:])
    def completed_trading_days(self, **kwargs):
        return (date(2026,9,1),)
    def session_windows(self, **kwargs):
        from types import SimpleNamespace
        return (SimpleNamespace(end=self.original.bars[-1].bar_end),)
    def load_historical_inputs(self, **kwargs):
        value = self.original
        return ((ReferenceSegment(value.contract, value.owner_id,
            tuple(ReferenceBar(bar.bar_end,bar.trading_day,bar.close) for bar in value.bars),
            value.owner_since,value.owner_through),),
            [{"contract":value.contract,"bars":[bar.as_record() for bar in value.bars]}],
            {},value.bars[-1].bar_end)


def query(service, **kwargs):
    bars = service.original.bars
    return SignalWindowQuery("jm","htdy","15m",date(2026,9,1),date(2026,9,1),
                             bars[31].bar_end,bars[-1].bar_end,**kwargs)


def test_exact_signal_pages_keep_prefix_and_source(monkeypatch):
    monkeypatch.setenv("REFERENCE_TRADING_READER_MODE","legacy")
    monkeypatch.setattr(HtdyOriginalEvaluator,"evaluate",lambda self,window: AlertEvaluation(("buy",)))
    service=Service()
    request=query(service,limit=2)
    first=query_signal_window(service,request)
    assert first["coverage"]["bar_count"]==49
    assert len(first["items"])==2
    assert first["identity"]["formula_versions"]
    assert first["history_start"]==date(2023,1,1)
    second=query_signal_window(service,replace(request,cursor=first["next_cursor"]))
    assert first["items"]!=second["items"]
    with pytest.raises(SubingReferenceError,match="CURSOR_CONFLICT"):
        query_signal_window(service,replace(request,from_time=request.from_time+timedelta(minutes=15),
                                            cursor=first["next_cursor"]))


def test_subing_legacy_reuses_real_kernel(monkeypatch):
    monkeypatch.setenv("REFERENCE_TRADING_READER_MODE","legacy")
    service=Service()
    result=query_signal_window(service,replace(query(service),strategy="subing"))
    assert result["identity"]["formula_versions"]==["subing_ths_15m_v3"]
    assert result["coverage"]["bar_count"]==49
    assert result["recording_mode"]=="historical_replay"
    assert "summary" not in result


def test_persisted_mode_never_falls_back_to_replay(monkeypatch):
    monkeypatch.setenv("REFERENCE_TRADING_READER_MODE","persisted")
    service=Service()
    with pytest.raises(SubingReferenceError,match="NOT_BUILT"):
        query_signal_window(service,query(service))


def test_display_bar_limit_is_independent_of_prefix(monkeypatch):
    monkeypatch.setenv("REFERENCE_TRADING_READER_MODE","legacy")
    service=Service(2200)
    service.now=lambda: datetime(2026,11,1,tzinfo=UTC)
    request=replace(query(service),from_time=service.original.bars[0].bar_end)
    with pytest.raises(SubingReferenceError,match="TOO_LARGE"):
        query_signal_window(service,request)


def test_navigation_uses_completed_calendar_not_wall_dates():
    service=Service()
    days=tuple(date(2026,6,1)+timedelta(days=3*index) for index in range(30))
    service.completed_trading_days=lambda **kwargs: days
    result=historical_window_navigation(service,symbol="jm",since=days[-1],through=days[-1],
                                        frequency="15m",as_of=service.now())
    assert result["previous_window"]==dict(since=days[9].isoformat(),through=days[28].isoformat())
    assert result["history_start"]=="2023-01-01"


def test_prefix_budget_rejects_before_loading(monkeypatch):
    monkeypatch.setenv("REFERENCE_TRADING_READER_MODE","legacy")
    service=Service()
    service.historical_input_bound=lambda **kwargs:(200001,819204096)
    service.load_historical_inputs=lambda **kwargs: pytest.fail("must reject before prefix allocation")
    with pytest.raises(SubingReferenceError,match="PREFIX_BUDGET"):
        query_signal_window(service,query(service))


def test_display_budget_rejects_before_loading(monkeypatch):
    monkeypatch.setenv("REFERENCE_TRADING_READER_MODE","legacy")
    service=Service(2200)
    service.now=lambda: datetime(2026,11,1,tzinfo=UTC)
    service.load_historical_inputs=lambda **kwargs: pytest.fail("must reject before prefix allocation")
    with pytest.raises(SubingReferenceError,match="TOO_LARGE"):
        query_signal_window(service,replace(query(service),from_time=service.original.bars[0].bar_end))


@pytest.mark.parametrize("change",("empty","from_gap","to_gap","wrong_day"))
def test_complete_requires_exact_existing_endpoints(monkeypatch,change):
    monkeypatch.setenv("REFERENCE_TRADING_READER_MODE","legacy")
    service=Service()
    request=query(service)
    if change=="empty":
        request=replace(request,from_time=request.to_time+timedelta(minutes=1),
                        to_time=request.to_time+timedelta(minutes=2))
    elif change=="from_gap":
        request=replace(request,from_time=request.from_time+timedelta(seconds=1))
    elif change=="to_gap":
        request=replace(request,to_time=request.to_time-timedelta(seconds=1))
    else:
        service.original=replace(service.original,bars=tuple(replace(bar,trading_day=date(2026,8,31))
                                                           for bar in service.original.bars))
    service.load_historical_inputs=lambda **kwargs: pytest.fail("must reject mismatched endpoints")
    with pytest.raises(SubingReferenceError,match="ENDPOINT_UNAVAILABLE"):
        query_signal_window(service,request)


def test_partial_canonical_has_nonempty_verified_lower_endpoint(monkeypatch):
    monkeypatch.setenv("REFERENCE_TRADING_READER_MODE","legacy")
    service=Service()
    request=replace(query(service),strategy="subing",to_time=service.original.bars[-1].bar_end+timedelta(minutes=15))
    result=query_signal_window(service,request)
    assert result["coverage"]["status"]=="PARTIAL_CANONICAL"
    assert result["coverage"]["first_bar_end"]==request.from_time
    assert result["coverage"]["bar_count"]>0
