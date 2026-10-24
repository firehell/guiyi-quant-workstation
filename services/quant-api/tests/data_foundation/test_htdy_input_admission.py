"""Admission fixtures are not market evidence or a first-seen observation."""
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.market_data.aggregation import SessionWindow, aggregate_from_1m, expected_intraday_ends
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.htdy_input_admission import audit_product, safe_error, summarize


DAY = date(2026, 10, 26)
AT = datetime(2026, 10, 24, 15, tzinfo=UTC)


def bar(end, day):
    return CanonicalBar(end, day, Decimal(100), Decimal(101), Decimal(99), Decimal(100),
                        Decimal(1), Decimal(100), Decimal(10))


class Market:
    def __init__(self):
        self._market_data = self
        self._phase_resolver = SimpleNamespace(resolve=lambda *_: SimpleNamespace(
            phase=SimpleNamespace(value="CLOSED"), trading_day=None,
            next_session_start=datetime(2026, 10, 26, 1, tzinfo=UTC)))
        self.sessions = {}
        self.minutes = {}
        self.hours = []
        for day in [date(2026, 10, d) for d in range(18, 24)] + [DAY]:
            start = (datetime(2026, 10, 23, 13, tzinfo=UTC) if day == DAY else
                     datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=1))
            window = SessionWindow(start, start + (timedelta(hours=2) if day == DAY else
                                                  timedelta(hours=5, minutes=30)))
            self.sessions[day] = (window,)
            source = tuple(bar(end, day) for end in expected_intraday_ends((window,), BarFrequency.M1))
            self.minutes[day] = source
            self.hours.extend(aggregate_from_1m(source, target_frequency=BarFrequency.H1, sessions=(window,)))
        self.hours = tuple(self.hours)
        self.live_m1 = self.minutes[DAY]
        self.live_h1 = tuple(item for item in self.hours if item.trading_day == DAY)
        self.live_error = None
        self.recovery_fenced = False
        self.validation_calls = 0
        self.source_reads = []

    def newow_completed_observation_endpoint(self, *_):
        return self.sessions[DAY][-1].end, DAY, "AG2612"

    def session_windows(self, *, symbol, trading_day):
        return self.sessions[trading_day]

    def dominant_segment_for_day(self, *_):
        return SimpleNamespace(contract="AG2612")

    def query_alert_history_prefix(self, query):
        source = (self.hours if query.frequency is BarFrequency.H1 else
                  tuple(item for rows in self.minutes.values() for item in rows))
        return SimpleNamespace(
            bars=tuple(item for item in source if item.bar_end < query.before)[-query.limit:],
            resolved_contract_segments=(SimpleNamespace(contract="AG2612",
                start_trading_day=date(2026, 10, 18), end_trading_day=DAY),),
        )

    def validate_actual_dominant_alert_window(self, **_):
        self.validation_calls += 1

    def expected_contract_replay_endpoints(self, *, frequency, trading_day, cutoff, **_):
        ends = expected_intraday_ends(self.sessions[trading_day], frequency)
        return tuple((end, trading_day) for end in ends if end <= cutoff)

    def query_maintenance_expected(self, query, expected):
        self.source_reads.append(query)
        source = tuple(item for rows in self.minutes.values() for item in rows
                       if query.start < item.bar_end <= query.end)
        if tuple(item.bar_end for item in source) != expected:
            raise ValueError("DATASET_OR_PARTITION_MISSING")
        return SimpleNamespace(bars=source)

    def _verified_live_bars(self, *, frequency, **_):
        return self.live_m1 if frequency is BarFrequency.M1 else self.live_h1

    def bars_until(self, *_args, **_kwargs):
        if self.live_error:
            raise ValueError(self.live_error)
        merged = {item.bar_end: item for item in self.hours}
        for item in self.live_h1:
            if item.bar_end in merged and merged[item.bar_end] != item:
                raise ValueError("MARKET_READ_LIVE_UNAVAILABLE")
            merged[item.bar_end] = item
        bars = tuple(merged[end] for end in sorted(merged))[-32:]
        end = self.sessions[DAY][-1].end
        if not bars or bars[-1].bar_end != end:
            raise ValueError("MARKET_READ_CUTOFF_BAR_MISSING")
        return SimpleNamespace(notification_eligible=not self.recovery_fenced,
                               bars=bars, bar_contracts=("AG2612",) * len(bars),
                               cutoff=end, trading_day=DAY, contract="AG2612")


@pytest.fixture
def inputs():
    return Market(), SimpleNamespace(latest_complete_day=lambda _: date(2026, 10, 23))


def test_incomplete_trading_day_night_prefix_is_historical_only(inputs, monkeypatch):
    market, coverage = inputs
    from app.alerts.evaluators import HtdyOriginalEvaluator
    monkeypatch.setattr(HtdyOriginalEvaluator, "evaluate_first_seen", lambda *_: pytest.fail("first seen called"))
    monkeypatch.setattr(HtdyOriginalEvaluator, "evaluate_candidates", lambda *_: pytest.fail("candidate called"))
    row = audit_product(market, coverage, "ag", AT)
    assert row["history"]["status"] == "WINDOW32_VERIFIED"
    assert row["history"]["source_1m_count"] == 5 * 330 + 120
    assert row["expected_trading_day"] == DAY
    assert row["latest_complete_trading_day"] < DAY
    assert market.validation_calls == 2
    assert all(query.end <= row["expected_endpoint"] for query in market.source_reads)
    assert row["live"]["status"] == "CONTINUITY_VERIFIED"
    assert row["future_signal"]["eligible_now"] is False
    assert row["future_signal"]["first_seen_proven"] is False
    assert row["future_signal"]["status"] == "WAIT_NEW_COMPLETED_OBSERVATION"
    assert row["production_writes"] == row["provider_requests"] == 0


def test_historical_repair_does_not_erase_live_gap(inputs):
    market, coverage = inputs
    before = market.live_m1
    market.live_m1 = before[:-31]
    row = audit_product(market, coverage, "ag", AT)
    assert row["history"]["status"] == "WINDOW32_VERIFIED"
    assert row["live"]["source_1m"]["missing_count"] == 31
    assert row["live"]["status"] == "BLOCKED"
    assert row["status"] == "HISTORICAL_READY_LIVE_BLOCKED"
    assert row["future_signal"]["prior_live_blocked"] is True
    assert market.live_m1 == before[:-31]


def test_original_canonical_revision_conflict_remains_blocked(inputs):
    market, coverage = inputs
    market.live_error = "MARKET_READ_LIVE_UNAVAILABLE"
    row = audit_product(market, coverage, "ag", AT)
    assert row["history"]["status"] == "WINDOW32_VERIFIED"
    assert row["live"]["source_1m"]["missing_count"] == 0
    assert row["live"]["errors"][0]["code"] == "MARKET_READ_LIVE_UNAVAILABLE"
    assert row["live"]["status"] == "BLOCKED"


def test_missing_latest_historical_endpoint_is_not_hidden_by_prior_day(inputs):
    market, coverage = inputs
    market.hours = tuple(item for item in market.hours if item.trading_day != DAY)
    market.minutes.pop(DAY)
    market.live_m1 = market.live_m1[:-31]
    market.live_h1 = market.live_h1[:-1]
    row = audit_product(market, coverage, "ag", AT)
    assert row["history"]["status"] == "WINDOW32_VERIFIED"
    assert row["history"]["covers_latest_endpoint"] is False
    assert row["calculation_input"]["status"] == "BLOCKED"
    assert row["future_signal"]["status"] == "BLOCKED"


def test_source_minute_gap_blocks_even_when_h1_present(inputs):
    market, coverage = inputs
    market.minutes[DAY] = market.minutes[DAY][:-1]
    market.live_m1 = market.live_m1[:-1]
    row = audit_product(market, coverage, "ag", AT)
    assert row["history"]["errors"][0]["code"] == "DATASET_OR_PARTITION_MISSING"
    assert row["calculation_input"]["status"] == "BLOCKED"
    assert row["status"] == "BLOCKED"


def test_h1_numeric_mismatch_blocks_history(inputs):
    market, coverage = inputs
    market.hours = (*market.hours[:-1], replace(market.hours[-1], close=Decimal("100.5")))
    row = audit_product(market, coverage, "ag", AT)
    assert row["history"]["errors"][0]["code"] == "H1_SOURCE_1M_AGGREGATION_MISMATCH"


def test_source_wrong_trading_day_blocks_history(inputs):
    market, coverage = inputs
    market.minutes[DAY] = tuple(replace(item, trading_day=date(2026, 10, 23)) for item in market.minutes[DAY])
    row = audit_product(market, coverage, "ag", AT)
    assert row["history"]["errors"][0]["code"] == "HTDY_SOURCE_ENDPOINT_INVALID"


def test_recovery_fence_is_disclosed_and_audit_never_grants_first_seen(inputs):
    market, coverage = inputs
    market.recovery_fenced = True
    row = audit_product(market, coverage, "ag", AT)
    assert row["live"]["recovery_fenced"] is True
    assert row["future_signal"]["eligible_now"] is False


@pytest.mark.parametrize("at", [AT.replace(tzinfo=None), datetime.now(UTC) + timedelta(days=1)])
def test_invalid_snapshot_time_rejected(inputs, at):
    with pytest.raises(ValueError, match="HTDY_ADMISSION_TIME_INVALID"):
        audit_product(*inputs, "ag", at)


def test_unknown_session_blocks_all_inputs(inputs):
    market, coverage = inputs
    market._phase_resolver.resolve = lambda *_: SimpleNamespace(
        phase=SimpleNamespace(value="UNKNOWN"), trading_day=None, next_session_start=None)
    row = audit_product(market, coverage, "ag", AT)
    assert row["status"] == "BLOCKED"
    assert market.source_reads == []


def test_no_current_endpoint_checks_prior_baseline_without_live_signal(inputs):
    market, coverage = inputs
    market.newow_completed_observation_endpoint = lambda *_: (None, DAY, "AG2612")
    row = audit_product(market, coverage, "ag", AT)
    assert row["expected_trading_day"] == date(2026, 10, 23)
    assert row["history"]["status"] == "WINDOW32_VERIFIED"
    assert row["live"]["status"] == "NOT_DUE"
    assert row["future_signal"]["eligible_now"] is False


def test_summary_keeps_three_separate_axes_and_redacts_errors(inputs):
    row = audit_product(*inputs, "ag", AT)
    report = summarize([row], AT)
    assert report["history_counts"] == {"WINDOW32_VERIFIED": 1}
    assert report["live_counts"] == {"CONTINUITY_VERIFIED": 1}
    assert report["calculation_counts"] == {"WINDOW32_VERIFIED": 1}
    assert report["first_seen_proven"] is False
    assert safe_error(ValueError("postgres://private-password"))[0]["code"] == "DETAIL_REDACTED"


def test_complete_originals_supply_current_window_after_prior_canonical_baseline(inputs):
    market, coverage = inputs
    market.hours = tuple(item for item in market.hours if item.trading_day != DAY)
    market.minutes.pop(DAY)
    row = audit_product(market, coverage, "ag", AT)
    assert row["history"]["last"] < row["expected_endpoint"]
    assert row["history"]["status"] == "WINDOW32_VERIFIED"
    assert row["calculation_input"]["last"] == row["expected_endpoint"]
    assert row["calculation_input"]["status"] == "WINDOW32_VERIFIED"
    assert row["live"]["status"] == "CONTINUITY_VERIFIED"
    assert row["status"] == "INPUTS_VERIFIED_WAIT_NEW_OBSERVATION"
    assert row["future_signal"]["eligible_now"] is False


def test_minute_revision_conflict_blocks_calculation_even_if_h1_still_matches(inputs):
    market, coverage = inputs
    market.live_m1 = (replace(market.live_m1[0], volume=Decimal(2)), *market.live_m1[1:])
    row = audit_product(market, coverage, "ag", AT)
    assert row["history"]["status"] == "WINDOW32_VERIFIED"
    assert row["calculation_input"]["errors"][0]["code"] == "HTDY_SOURCE_ORIGINAL_CANONICAL_CONFLICT"
    assert row["calculation_input"]["status"] == "BLOCKED"
    assert row["status"] == "BLOCKED"


@pytest.mark.parametrize("scenario,expected", [
    ("canonical_baseline_original_complete", "INPUTS_VERIFIED_WAIT_NEW_OBSERVATION"),
    ("canonical_complete_original_gap", "HISTORICAL_READY_LIVE_BLOCKED"),
    ("canonical_and_original_gap", "BLOCKED"),
    ("original_canonical_revision", "BLOCKED"),
])
def test_native_market_read_union_and_conflicts(inputs, scenario, expected):
    from app.market_data.live_market import LiveBarObservation
    from app.market_data.market_read_service import MarketReadService

    market, coverage = inputs
    if scenario in {"canonical_baseline_original_complete", "canonical_and_original_gap"}:
        market.hours = tuple(item for item in market.hours if item.trading_day != DAY)
        market.minutes.pop(DAY)
    if scenario in {"canonical_complete_original_gap", "canonical_and_original_gap"}:
        market.live_m1 = market.live_m1[:-31]
        market.live_h1 = market.live_h1[:-1]
    if scenario == "original_canonical_revision":
        market.live_h1 = (replace(market.live_h1[0], close=Decimal("100.5")), *market.live_h1[1:])
    market._phase_resolver.completed_observation_trading_day = lambda *_: DAY
    store = SimpleNamespace(
        subscriptions=lambda _: {"ag": "AG2612"}, recovery_state=lambda *_: None,
        bar_observations=lambda _day, _symbol, frequency, *_args, **_kwargs: tuple(
            LiveBarObservation(item, "AG2612") for item in (
                market.live_m1 if frequency == "1m" else market.live_h1)),
    )
    native = MarketReadService(
        market_data=market, phase_resolver=market._phase_resolver,
        operational_products=("ag",), live_store=store,
    )
    row = audit_product(native, coverage, "ag", AT)
    assert row["status"] == expected
    assert row["history"]["status"] == "WINDOW32_VERIFIED"
    assert row["future_signal"]["eligible_now"] is False
    assert row["future_signal"]["first_seen_proven"] is False


def test_no_current_endpoint_requires_complete_baseline_tail(inputs):
    market, coverage = inputs
    market.newow_completed_observation_endpoint = lambda *_: (None, None, None)
    baseline = tuple(b for b in market.hours if b.trading_day != DAY)
    market.hours = baseline[:-1]
    row = audit_product(market, coverage, "ag", AT)
    assert row["history"]["status"] == "WINDOW32_VERIFIED"
    assert row["history"]["covers_latest_endpoint"] is False
    assert row["live"]["status"] == "NOT_DUE"
    assert row["calculation_input"]["status"] == "BLOCKED"
    assert row["future_signal"]["status"] == "BLOCKED"
