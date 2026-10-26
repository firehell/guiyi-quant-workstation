from datetime import UTC, date, datetime
from types import SimpleNamespace
import json
import pytest
from app.market_data.market_read_service import (
    MarketReadService,
    MarketReadWindow,
    MarketReadWindowError,
)
from app.market_data.observation_stream import ObservationEnvelope
from app.market_data.live_market import _bar_from_payload


def setup():
    end = datetime(2026, 10, 26, 13, 5, tzinfo=UTC)
    raw = dict(
        bar_end=end.isoformat(),
        trading_day="2026-10-27",
        contract="EG2701",
        open="5000",
        high="5001",
        low="4990",
        close="4999",
        volume="10",
        turnover=None,
        open_interest=None,
    )
    bar = _bar_from_payload(json.dumps(raw))
    event = ObservationEnvelope(
        "eg:5m", date(2026, 10, 27), end, "live:bar:eg:5m", raw, True, "123-0", end, end
    )
    window = MarketReadWindow(
        symbol="eg",
        series_kind="actual_dominant",
        frequency="5m",
        trading_day=bar.trading_day,
        contract="EG2701",
        cutoff=end,
        bars=(bar,),
        bar_contracts=("EG2701",),
    )
    service = object.__new__(MarketReadService)
    service._market_data = SimpleNamespace(
        dominant_segment_for_day=lambda *_: SimpleNamespace(contract="EG2701"),
        validate_contract_replay_coverage=lambda **kw: None,
    )
    service._current_contract_history = lambda **kw: ()
    return service, window, event


def test_retained_original_replay_survives_absent_redis_without_relabelling_original():
    service, window, event = setup()
    result = service.retained_contract_replay_window(window, observations=(event,))
    assert result.bars == window.bars
    assert event.confirmed_at == window.cutoff


def test_retained_replay_rejects_conflicting_original_and_current_owner():
    service, window, event = setup()
    service._market_data.dominant_segment_for_day = lambda *_: SimpleNamespace(
        contract="EG2611"
    )
    with pytest.raises(MarketReadWindowError):
        service.retained_contract_replay_window(window, observations=(event,))
