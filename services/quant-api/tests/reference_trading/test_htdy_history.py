from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.alerts.evaluators import AlertEvaluation, HtdyOriginalEvaluator
from app.market_data.domain import CanonicalBar
from app.reference_trading.htdy_history import HtdyReplaySegment, history_identity, replay_htdy
from guiyi_quant.reference_trading import BoundaryReason, RecordingMode

START = datetime(2026, 9, 1, tzinfo=UTC)


def segment(count=36, contract="JM2701", **kwargs):
    bars = tuple(CanonicalBar(
        bar_end=START + timedelta(minutes=15*i), trading_day=date(2026, 9, 1),
        open=Decimal(100+i), high=Decimal(101+i), low=Decimal(99+i),
        close=Decimal(100+i), volume=Decimal(10), turnover=None, open_interest=None,
    ) for i in range(count))
    return HtdyReplaySegment(contract, contract, contract, date(2026, 9, 1),
                             date(2026, 9, 1), bars, **kwargs)


def test_fixed_window_prefix_and_stable_reverse_pairing(monkeypatch):
    windows = []
    def evaluate(self, window):
        windows.append(window)
        index = int((window.cutoff-START).total_seconds()/900)
        return AlertEvaluation(("buy",) if index == 31 else ("sell",) if index == 34 else ())
    monkeypatch.setattr(HtdyOriginalEvaluator, "evaluate", evaluate)
    identity = history_identity("jm", "15m")
    full, signals, _ = replay_htdy(identity, (segment(),))
    prefix, prefix_signals, _ = replay_htdy(identity, (segment(34),))
    assert len(full) == 2
    assert full[0].status.value == "CLOSED"
    assert full[1].status.value == "OPEN"
    assert full[1].holding_bars == 1
    assert full[1].mark_bar_end == START + timedelta(minutes=15*35)
    assert full[0].entry_action_id == prefix[0].entry_action_id
    assert signals[:1] == prefix_signals
    assert all(len(window.bars) == 32 and window.bars[-1].bar_end == window.cutoff for window in windows)


def test_warmup_and_boundary_never_cross_contract(monkeypatch):
    monkeypatch.setattr(HtdyOriginalEvaluator, "evaluate", lambda self, window: AlertEvaluation(("buy",)))
    identity = history_identity("jm", "15m")
    assert replay_htdy(identity, (segment(31),))[0] == ()
    first = segment(32, interrupted_at=START+timedelta(minutes=15*32),
                    interruption_reason=BoundaryReason.DATA_INTERRUPTED)
    second = replace(segment(32, "JM2705"), bars=tuple(
        replace(bar, bar_end=bar.bar_end+timedelta(days=1), trading_day=date(2026,9,2))
        for bar in segment(32).bars), owner_since=date(2026,9,2), owner_through=date(2026,9,2))
    trades, _, _ = replay_htdy(identity, (first, second))
    assert [trade.status.value for trade in trades] == ["DATA_INTERRUPTED", "OPEN"]
    assert trades[0].reference_trade_id != trades[1].reference_trade_id


def test_forward_identity_rejected():
    stream = replace(history_identity("jm", "15m"), recording_mode=RecordingMode.FORWARD_OBSERVATION,
                     observation_policy_version="latest_only_32_v1")
    with pytest.raises(ValueError, match="IDENTITY"):
        replay_htdy(stream, ())


def test_query_uses_storage_prefix_and_cursor_identity(monkeypatch):
    from app.reference_trading.htdy_history import query_htdy_history
    from app.market_data.subing_reference import SubingReferenceQuery
    from guiyi_quant.subing_reference import ReferenceBar, ReferenceSegment

    original = segment(35)
    metadata = {"revision": "one"}
    calls = []
    evaluations = []
    from app.reference_trading.htdy_history import _REPLAY_CACHE
    _REPLAY_CACHE.clear()
    class Service:
        check_cancelled = staticmethod(lambda: None)
        historical_storage_start = staticmethod(lambda symbol: date(2026,9,1))
        historical_metadata_evidence = staticmethod(lambda **kwargs: dict(metadata))
        historical_input_bound = staticmethod(lambda **kwargs: (118140, 483901440))
        resolve_read_window = staticmethod(lambda query: (date(2026,9,1), date(2026,9,1), original.bars[-1].bar_end, original.bars[-1].bar_end))
        def load_historical_inputs(self, **kwargs):
            calls.append(kwargs)
            return ((ReferenceSegment(original.contract, original.owner_id,
                tuple(ReferenceBar(bar.bar_end, bar.trading_day, bar.close) for bar in original.bars),
                original.owner_since, original.owner_through),),
                [{"contract": original.contract, "bars": [bar.as_record() for bar in original.bars]}], {}, original.bars[-1].bar_end)
    def evaluate(self, window):
        evaluations.append(window.cutoff)
        return AlertEvaluation(
            ("buy",) if window.cutoff == original.bars[31].bar_end else
            ("sell",) if window.cutoff == original.bars[34].bar_end else ())
    monkeypatch.setattr(HtdyOriginalEvaluator, "evaluate", evaluate)
    query = SubingReferenceQuery("jm", limit=1)
    result = query_htdy_history(Service(), query)
    assert result["recording_mode"] == "historical_replay"
    assert result["summary"]["total"] == 2
    assert result["summary"]["closed"] == 1
    assert result["summary"]["wins"] == 1
    assert result["summary"]["win_rate_pct"] == Decimal(100)
    assert result["summary"]["mean_return_pct"] == result["summary"]["sum_return_percentage_points"]
    assert result["next_cursor"]
    initial_evaluations = len(evaluations)
    next_result = query_htdy_history(Service(), replace(query, before=result["next_cursor"]))
    assert len(next_result["trades"]) == 1
    assert next_result["summary"] == result["summary"]
    assert next_result["trades"] != result["trades"]
    assert len(evaluations) == initial_evaluations
    # Responses cannot mutate the cached signal dictionaries.
    next_result["signals"][0]["actions"].clear()
    reread = query_htdy_history(Service(), query)
    assert reread["signals"][0]["actions"]
    metadata["revision"] = "two"
    with pytest.raises(ValueError, match="CURSOR_CONFLICT"):
        query_htdy_history(Service(), replace(query, before=result["next_cursor"]))
    assert len(evaluations) > initial_evaluations
    prior_evaluations = len(evaluations)
    original = replace(original, bars=original.bars[:-1] + (
        replace(original.bars[-1], high=original.bars[-1].high + Decimal("1")),))
    changed = query_htdy_history(Service(), query)
    assert changed["source_token"] != result["source_token"]
    assert len(evaluations) > prior_evaluations
    assert all(call["since"] == date(2026,9,1) for call in calls)


def test_real_evaluator_last_window_parity():
    original = segment(80)
    stream = history_identity("jm", "15m")
    expected = []
    evaluator = HtdyOriginalEvaluator()
    for index in range(31, len(original.bars)):
        bar = original.bars[index]
        from app.market_data.market_read_service import MarketReadWindow
        window = MarketReadWindow("JM", "actual_dominant", "15m", bar.trading_day,
                                  original.contract, bar.bar_end,
                                  original.bars[index-31:index+1], (original.contract,)*32)
        values = evaluator.evaluate(window).observation_types
        if values:
            expected.append((bar.bar_end, values))
    _, signals, _ = replay_htdy(stream, (original,))
    assert [(item["bar_end"], item["observation_types"]) for item in signals] == expected


def test_replay_cache_bounds_and_copy(monkeypatch):
    import app.reference_trading.htdy_history as module
    module._REPLAY_CACHE.clear()
    monkeypatch.setattr(module, "replay_htdy", lambda *args, **kwargs: ((), (), None))
    for index in range(module._CACHE_KEYS + 2):
        module._cached_replay(str(index), None, (), lambda: None)
    assert len(module._REPLAY_CACHE) == module._CACHE_KEYS
    assert "0" not in module._REPLAY_CACHE


def test_htdy_bar_budget_preserves_hard_upper_bound():
    from app.reference_trading.htdy_history import query_htdy_history
    from app.market_data.subing_reference import SubingReferenceError, SubingReferenceQuery
    class Service:
        resolve_read_window = staticmethod(lambda query: (
            date(2026,9,1), date(2026,9,1), START, START))
        historical_storage_start = staticmethod(lambda symbol: date(2023,1,1))
        historical_input_bound = staticmethod(lambda **kwargs: (200001, 819204096))
    with pytest.raises(SubingReferenceError, match="HTDY_REFERENCE_BUDGET_EXCEEDED"):
        query_htdy_history(Service(), SubingReferenceQuery("jm"))


def test_http_preserves_decimal_lexemes(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import market_subing_reference as routes
    from app.reference_trading import htdy_history

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_db] = lambda: None
    monkeypatch.setattr(routes, "_build_service", lambda *_: object())
    from app.reference_trading import signal_window
    monkeypatch.setattr(signal_window, "historical_window_navigation", lambda *args, **kwargs: {})
    monkeypatch.setattr(htdy_history, "query_htdy_history", lambda *_: {
        "trades": [{"entry_reference_price": Decimal("1417.00"),
                    "reference_return": Decimal("0.1234567890123456789")}],
        "computed_through": START, "since": START.date(), "through": START.date(),
    })
    response = TestClient(app).get("/api/v1/market/jm/htdy/reference?as_of=" + START.isoformat().replace("+", "%2B"))
    assert response.status_code == 200
    assert response.json()["trades"][0] == {
        "entry_reference_price": "1417.00",
        "reference_return": "0.1234567890123456789",
    }
