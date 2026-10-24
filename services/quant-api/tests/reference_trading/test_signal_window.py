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


@pytest.fixture(autouse=True)
def clear_derived_replay_cache():
    from app.reference_trading.htdy_history import _REPLAY_CACHE
    _REPLAY_CACHE.clear()


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
    def observed(self, window):
        index=int((window.cutoff-service.original.bars[0].bar_end).total_seconds()/900)
        return AlertEvaluation(("buy",) if index in (31,40) else ("sell",) if index==34 else ())
    monkeypatch.setattr(HtdyOriginalEvaluator,"evaluate",observed)
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


def test_subing_formal_signals_require_saved_history_even_with_legacy_environment(monkeypatch):
    monkeypatch.setenv("REFERENCE_TRADING_READER_MODE", "legacy")
    service = Service()
    with pytest.raises(SubingReferenceError, match="NOT_BUILT"):
        query_signal_window(service, replace(query(service), strategy="subing"))


def test_htdy_uses_its_canonical_model_independent_of_obsolete_reader_switch(monkeypatch):
    monkeypatch.setenv("REFERENCE_TRADING_READER_MODE", "persisted")
    service = Service()
    result = query_signal_window(service, query(service))
    assert result["recording_mode"] == "historical_replay"
    assert result["identity"]["reference_model_version"]


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
    request=replace(query(service),strategy="htdy",to_time=service.original.bars[-1].bar_end+timedelta(minutes=15))
    result=query_signal_window(service,request)
    assert result["coverage"]["status"]=="PARTIAL_CANONICAL"
    assert result["coverage"]["first_bar_end"]==request.from_time
    assert result["coverage"]["bar_count"]>0


def test_v2_htdy_actions_are_paired_reverse_facts_not_duplicate_observations(monkeypatch):
    service=Service()
    def evaluate(self,window):
        offset=int((window.cutoff-service.original.bars[0].bar_end).total_seconds()/900)
        return AlertEvaluation(("buy",) if offset in (31,32) else ("sell",) if offset==34 else ())
    monkeypatch.setattr(HtdyOriginalEvaluator,"evaluate",evaluate)
    result=query_signal_window(service,query(service))
    assert result["schema_version"]=="historical_signal_window_v2"
    actions=result["items"]
    assert [(item["role"],item["side"]) for item in actions]==[("BUILD","LONG"),("CLEAR","LONG"),("BUILD","SHORT")]
    assert actions[0]["reference_trade_id"]==actions[1]["reference_trade_id"]
    assert actions[1]["bar_end"]==actions[2]["bar_end"]
    assert actions[0]["return_pct"] is None
    assert actions[1]["return_pct"] is not None
    assert actions[2]["return_pct"] is None
    assert actions[1]["signal_id"]==actions[2]["signal_id"]
    assert len({item["action_id"] for item in actions})==3
    reread=query_signal_window(service,query(service))
    assert reread["items"]==actions


def test_v2_subing_uses_exact_verified_saved_trade_snapshot():
    service=Service()
    bars=service.original.bars
    common=dict(physical_contract="JM2701",owner_segment_id="owner",calculation_segment_id="calc",holding_bars=3)
    trades=[dict(common,reference_trade_id="internal-long",public_reference_trade_id="public-long",
        side="LONG",status="CLOSED",entry_action_id="build-long",entry_bar_end=bars[31].bar_end,
        entry_trading_day=bars[31].trading_day,entry_reference_price="131.00",exit_action_id="clear-long",
        exit_bar_end=bars[34].bar_end,exit_trading_day=bars[34].trading_day,exit_reference_price="134.00",
        reference_return="2.2900763358778625954198473"),
        dict(common,reference_trade_id="internal-short",public_reference_trade_id="public-short",side="SHORT",
        status="OPEN",entry_action_id="build-short",entry_bar_end=bars[34].bar_end,
        entry_trading_day=bars[34].trading_day,entry_reference_price="134.00",reference_return=None)]
    signals=[dict(signal_id=f"signal-{index}",bar_end=bars[index].bar_end,
        physical_contract="JM2701",segment_id="owner",calculation_segment_id="calc",direction=direction,
        entry_trade_id="public-long" if index==31 else "public-short",
        closed_trade_id=None if index==31 else "public-long") for index,direction in ((31,"buy"),(34,"sell"))]
    class Saved:
        def streams(self,**kwargs):
            return [dict(stream_id="saved-subing",formula_versions=["subing_ths_15m_v3"],reference_model_version="subing_reference_reverse_close_v1")]
        def signals(self,*args,**kwargs):
            return dict(items=[dict(value=signal) for signal in signals],snapshot="snapshot",revision_id="revision",seq=7,next_cursor=None)
        def trades(self,*args,**kwargs):
            assert kwargs["snapshot_token"]=="snapshot"
            return dict(items=trades,snapshot="snapshot",revision_id="revision",seq=7,next_cursor=None)
    verification=[]
    result=query_signal_window(service,replace(query(service),strategy="subing"),persisted_query=Saved(),
        verify_persisted_source=lambda **kwargs:verification.append(kwargs))
    assert len(verification)==2
    assert [(item["role"],item["reference_trade_id"]) for item in result["items"]]==[
        ("BUILD","public-long"),("CLEAR","public-long"),("BUILD","public-short")]
    assert str(result["items"][1]["return_pct"])=="2.2900763358778625954198473"


def test_interrupted_trade_never_manufactures_clear():
    from app.reference_trading.signal_window import _reference_actions
    bar=Service().original.bars[31]
    trade=dict(reference_trade_id="interrupted",side="LONG",status="ROLLOVER_INTERRUPTED",
        entry_action_id="open",entry_bar_end=bar.bar_end,entry_trading_day=bar.trading_day,
        entry_reference_price="131",physical_contract="JM2701",owner_segment_id="owner",calculation_segment_id="calc")
    signals=[dict(signal_id="signal",bar_end=bar.bar_end,physical_contract="JM2701",segment_id="owner",calculation_segment_id="calc")]
    result=_reference_actions([trade],signals,stream_id="stream",from_time=bar.bar_end,to_time=bar.bar_end)
    assert len(result)==1
    assert result[0]["role"]=="BUILD" and result[0]["return_pct"] is None


@pytest.mark.parametrize("mismatch",("owner","action","entry_trade","closed_trade"))
def test_action_rejects_wrong_explicit_signal_association(mismatch):
    from app.reference_trading.signal_window import _reference_actions
    bar=Service().original.bars[31]
    trade=dict(reference_trade_id="trade",side="LONG",status="CLOSED",
        entry_action_id="build",entry_bar_end=bar.bar_end,entry_trading_day=bar.trading_day,
        entry_reference_price="131",exit_action_id="clear",exit_bar_end=bar.bar_end,
        exit_trading_day=bar.trading_day,exit_reference_price="131",reference_return="0",
        physical_contract="JM2701",owner_segment_id="owner",calculation_segment_id="calc")
    signal=dict(signal_id="signal",bar_end=bar.bar_end,physical_contract="JM2701",
        segment_id="owner",calculation_segment_id="calc",action_ids=["build","clear"],
        entry_trade_id="trade",closed_trade_id="trade")
    if mismatch=="owner":
        signal["segment_id"]="other-owner"
    elif mismatch=="action":
        signal["action_ids"]=["unrelated-action"]
    elif mismatch=="entry_trade":
        signal["entry_trade_id"]="unrelated-trade"
    else:
        signal["closed_trade_id"]="unrelated-trade"
    with pytest.raises(SubingReferenceError,match="SIGNAL_WINDOW_(ACTION_SIGNAL_MISSING|SOURCE_CONFLICT)"):
        _reference_actions([trade],[signal],stream_id="stream",from_time=bar.bar_end,to_time=bar.bar_end)
