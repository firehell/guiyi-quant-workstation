from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.alerts.evaluators import AlertEvaluationError, SubingThsEvaluator
from app.alerts.registry import SUBING_QUALITY_REWARM_POLICY_V2
from app.market_data.domain import (
    BarFrequency, CanonicalBar, MarketSeriesResult, ResolvedContractSegment,
    SeriesPageQuery,
)
from app.market_data.market_data_service import DominantContractSegmentSummary
from app.market_data.market_read_service import MarketReadService, MarketReadWindowError
from app.market_data.source_quality import NonpositiveCloseFact, PriceUnavailableFact
from app.market_data.weekly_quality import WeeklySourceInterruption


DAY = date(2026, 1, 1)
END = datetime(2026, 1, 1, 7, tzinfo=UTC)


def _bar(index: int, *, weekly: bool = False) -> CanonicalBar:
    day = DAY + timedelta(days=7 * index if weekly else index)
    end = END + timedelta(days=7 * index if weekly else index)
    return CanonicalBar(end, day, Decimal(100 + index), Decimal(101 + index),
                        Decimal(99 + index), Decimal(100 + index), Decimal(100),
                        None, None)


def _quality(index: int, *, kind: str):
    bar = _bar(index)
    cls = PriceUnavailableFact if kind == "PRICE_UNAVAILABLE" else NonpositiveCloseFact
    return cls(
        bar_end=bar.bar_end, trading_day=bar.trading_day,
        open=Decimal(0), high=Decimal(0), low=Decimal(0),
        close=Decimal(100) if cls is PriceUnavailableFact else Decimal(0),
        volume=Decimal(1), turnover=Decimal(0), open_interest=None,
        request_sha256="a" * 64, response_sha256="b" * 64,
        observed_at=bar.bar_end + timedelta(seconds=1),
    )


class _QualityReader:
    def __init__(self, bars, facts, *, frequency: BarFrequency, owner_start: date = DAY):
        self.bars = tuple(bars)
        self.facts = tuple(facts)
        self.frequency = frequency
        self.owner_start = owner_start
        self.calls = []
        self.unpublished_days = set()

    def dominant_segment_for_day(self, symbol, trading_day):
        self.owner_day = trading_day
        return DominantContractSegmentSummary(symbol, "RB2610", self.owner_start, trading_day)

    def completed_trading_days(self, **kwargs):
        self.calendar_args = kwargs
        return (self.bars[-1].trading_day, *sorted(self.unpublished_days))

    def rank1_quality_endpoint_published(self, *, symbol, frequency, trading_day):
        return trading_day not in self.unpublished_days

    def completed_calendar_week(self, *, symbol, week_monday, as_of):
        self.week_queries = getattr(self, "week_queries", []) + [week_monday]
        if week_monday <= self.bars[-1].trading_day <= week_monday + timedelta(days=6):
            return self.bars[-1].trading_day, self.bars[-1].bar_end
        return None

    def session_windows(self, *, symbol, trading_day):
        points = [bar for bar in self.bars if bar.trading_day == trading_day]
        points += [fact for _, fact in self.facts
                   if hasattr(fact, "trading_day") and fact.trading_day == trading_day]
        return (SimpleNamespace(end=points[-1].bar_end),) if points else ()

    def expected_contract_replay_endpoints(self, **kwargs):
        self.expected_args = kwargs
        points = [(bar.bar_end, bar.trading_day) for bar in self.bars]
        points += [(fact.bar_end, fact.trading_day) for _, fact in self.facts
                   if hasattr(fact, "bar_end") and hasattr(fact, "trading_day")]
        return tuple(sorted(point for point in points if point[0] <= kwargs["cutoff"]))

    def query_contract_replay_quality_union(self, **kwargs):
        self.physical_args = kwargs
        return self.bars, tuple(fact for _, fact in self.facts)

    def query_contract_weekly_replay_quality(self, **kwargs):
        self.physical_args = kwargs
        assert kwargs["classification_version"] == "weekly-d1-quality-v2"
        return self.bars, tuple(fact for _, fact in self.facts)

    def query_actual_dominant_trading_days_quality_union(self, request):
        assert request.frequency is BarFrequency.D1
        self.calls.append(request)
        return self._result(request), self.facts

    def query_actual_dominant_trading_days_quality(self, request, *, weekly_classification_version):
        assert request.frequency is BarFrequency.W1
        assert weekly_classification_version == "weekly-d1-quality-v2"
        self.calls.append(request)
        return self._result(request), self.facts

    def _result(self, request):
        selected = tuple(bar for bar in self.bars if bar.trading_day >= request.since)
        segments = () if not selected else (
            ResolvedContractSegment("RB2610", selected[0].trading_day,
                                    selected[-1].trading_day),
        )
        return MarketSeriesResult({}, selected,
                                  (selected[0].bar_end, selected[-1].bar_end) if selected else None,
                                  segments, (request.since, request.through))


def _service(reader):
    return MarketReadService(market_data=reader, phase_resolver=None,
                             operational_products=("rb",), live_store=None)


@pytest.mark.parametrize("kind", ("PRICE_UNAVAILABLE", "NONPOSITIVE_CLOSE"))
def test_daily_quality_break_rewarms_from_first_valid_bar(kind):
    gap = _quality(4, kind=kind)
    bars = tuple(_bar(i) for i in range(4)) + tuple(_bar(i) for i in range(5, 40))
    reader = _QualityReader(bars, (("RB2610", gap),), frequency=BarFrequency.D1)
    service = _service(reader)
    window = service.latest_subing_quality_window(
        SeriesPageQuery("actual_dominant", "rb", "1d"), trading_day=bars[-1].trading_day,
    )
    assert window.bars == bars[4:]
    assert window.input_policy_version == SUBING_QUALITY_REWARM_POLICY_V2
    assert all(owner == "RB2610" for owner in window.bar_contracts)
    assert reader.physical_args["since"] is None
    service.assert_window_current(window)


def test_latest_daily_quality_break_cannot_fall_back_to_earlier_bar():
    bars = tuple(_bar(i) for i in range(4))
    reader = _QualityReader(bars, (("RB2610", _quality(4, kind="PRICE_UNAVAILABLE")),),
                            frequency=BarFrequency.D1)
    with pytest.raises(MarketReadWindowError, match="MARKET_READ_CUTOFF_BAR_MISSING"):
        _service(reader).latest_subing_quality_window(
            SeriesPageQuery("actual_dominant", "rb", "1d"), trading_day=_bar(4).trading_day,
        )


def test_unknown_quality_fact_fails_closed():
    bars = tuple(_bar(i) for i in range(6))
    reader = _QualityReader(bars, (("RB2610", object()),), frequency=BarFrequency.D1)
    with pytest.raises(MarketReadWindowError, match="MARKET_READ_WINDOW_INCOMPLETE"):
        _service(reader).latest_subing_quality_window(
            SeriesPageQuery("actual_dominant", "rb", "1d"), trading_day=bars[-1].trading_day,
        )


def test_weekly_interruption_v2_resets_and_twenty_real_weeks_remain_warming():
    gap_bar = _bar(3, weekly=True)
    interruption = WeeklySourceInterruption(
        "rb", "RB2610", 2026, 4, gap_bar.bar_end,
        ((gap_bar.bar_end, gap_bar.trading_day),), (gap_bar.trading_day,),
        (("a" * 64, "b" * 64),), "c" * 64, "source", "weekly-d1-quality-v2",
        ("NONPOSITIVE_CLOSE",),
    )
    bars = tuple(_bar(i, weekly=True) for i in range(3)) + tuple(
        _bar(i, weekly=True) for i in range(4, 24)
    )
    reader = _QualityReader(bars, (("RB2610", interruption),), frequency=BarFrequency.W1)
    window = _service(reader).latest_subing_quality_window(
        SeriesPageQuery("actual_dominant", "rb", "1w"), trading_day=bars[-1].trading_day,
    )
    assert len(window.bars) == 20
    with pytest.raises(AlertEvaluationError, match="ALERT_EVALUATION_WARMING_UP"):
        SubingThsEvaluator().evaluate_candidates(_service(reader), window)


def test_stale_quality_window_is_rejected_after_source_changes():
    bars = tuple(_bar(i) for i in range(40))
    reader = _QualityReader(bars, (), frequency=BarFrequency.D1)
    service = _service(reader)
    window = service.latest_subing_quality_window(
        SeriesPageQuery("actual_dominant", "rb", "1d"), trading_day=bars[-1].trading_day,
    )
    reader.bars = reader.bars[:-1] + (replace(reader.bars[-1], close=Decimal("139.5")),)
    with pytest.raises(MarketReadWindowError, match="MARKET_READ_CONTRACT_UNAVAILABLE"):
        service.assert_window_current(window)


@pytest.mark.parametrize("frequency", ("1d", "1w"))
def test_formal_daily_weekly_evaluation_requires_quality_policy(frequency):
    bars = tuple(_bar(i, weekly=frequency == "1w") for i in range(35))
    from app.market_data.market_read_service import MarketReadWindow

    window = MarketReadWindow(
        "rb", "actual_dominant", frequency, bars[-1].trading_day,
        "RB2610", bars[-1].bar_end, bars, ("RB2610",) * len(bars),
    )
    with pytest.raises(AlertEvaluationError, match="ALERT_EVALUATION_INPUT_INVALID"):
        SubingThsEvaluator().evaluate_candidates(_service(None), window)


def test_as_of_daily_uses_authoritative_completed_day_without_generic_page():
    bars = tuple(_bar(i) for i in range(35))
    reader = _QualityReader(bars, (), frequency=BarFrequency.D1)
    service = _service(reader)
    window = service.latest_subing_quality_window_as_of(
        SeriesPageQuery("actual_dominant", "rb", "1d"),
        as_of=bars[-1].bar_end + timedelta(hours=1),
    )
    assert window.cutoff == bars[-1].bar_end
    assert reader.owner_day == bars[-1].trading_day
    assert reader.calendar_args["latest"] == bars[-1].trading_day


def test_as_of_weekly_uses_last_completed_week_owner():
    bars = tuple(_bar(i, weekly=True) for i in range(35))
    reader = _QualityReader(bars, (), frequency=BarFrequency.W1)
    service = _service(reader)
    window = service.latest_subing_quality_window_as_of(
        SeriesPageQuery("actual_dominant", "rb", "1w"),
        as_of=bars[-1].bar_end + timedelta(days=4),
    )
    assert window.trading_day == bars[-1].trading_day
    assert reader.owner_day == bars[-1].trading_day
    assert len(reader.week_queries) >= 1


def test_as_of_daily_defers_completed_but_unpublished_tail():
    bars = tuple(_bar(i) for i in range(35))
    reader = _QualityReader(bars, (), frequency=BarFrequency.D1)
    reader.unpublished_days.add(bars[-1].trading_day + timedelta(days=1))
    window = _service(reader).latest_subing_quality_window_as_of(
        SeriesPageQuery("actual_dominant", "rb", "1d"),
        as_of=bars[-1].bar_end + timedelta(days=1, hours=1),
    )
    assert window.trading_day == bars[-1].trading_day


def test_daily_rewarm_incremental_and_restart_replay_have_identical_state():
    gap = _quality(4, kind="NONPOSITIVE_CLOSE")
    bars = tuple(_bar(i) for i in range(4)) + tuple(_bar(i) for i in range(5, 40))
    reader = _QualityReader(bars, (("RB2610", gap),), frequency=BarFrequency.D1)
    service = _service(reader)
    first = service.latest_subing_quality_window(
        SeriesPageQuery("actual_dominant", "rb", "1d"), trading_day=bars[-1].trading_day,
    )
    incremental = SubingThsEvaluator()
    incremental.evaluate_candidates(service, first)

    reader.bars += (_bar(40),)
    next_window = service.latest_subing_quality_window(
        SeriesPageQuery("actual_dominant", "rb", "1d"), trading_day=reader.bars[-1].trading_day,
    )
    incremental_result = incremental.evaluate_candidates(service, next_window)
    restarted = SubingThsEvaluator()
    restart_result = restarted.evaluate_candidates(service, next_window)
    assert incremental_result == restart_result
    assert incremental._cursors[("rb", "1d")].state == restarted._cursors[("rb", "1d")].state


def test_quality_candidate_carries_persistable_input_policy():
    class ActionKernel:
        def initial_state(self):
            return 0

        def step(self, state, close, *, bar_end):
            del close, bar_end
            next_state = state + 1
            return next_state, SimpleNamespace(
                valid=True, ready=next_state >= 35,
                result_codes=("buy",) if next_state == 35 else (),
            )

    bars = tuple(_bar(i) for i in range(35))
    reader = _QualityReader(bars, (), frequency=BarFrequency.D1)
    window = _service(reader).latest_subing_quality_window(
        SeriesPageQuery("actual_dominant", "rb", "1d"), trading_day=bars[-1].trading_day,
    )
    candidates = SubingThsEvaluator(kernel=ActionKernel()).evaluate_candidates(_service(reader), window)
    assert len(candidates) == 1
    assert candidates[0].observation_types == ("buy",)
    assert candidates[0].input_policy_version == SUBING_QUALITY_REWARM_POLICY_V2


def test_no_break_preserves_full_physical_warmup_before_rank1_takeover():
    bars = tuple(_bar(i) for i in range(40))
    reader = _QualityReader(
        bars, (), frequency=BarFrequency.D1, owner_start=_bar(20).trading_day,
    )
    window = _service(reader).latest_subing_quality_window(
        SeriesPageQuery("actual_dominant", "rb", "1d"), trading_day=bars[-1].trading_day,
    )
    assert window.bars == bars
    assert reader.physical_args["contract"] == "RB2610"
