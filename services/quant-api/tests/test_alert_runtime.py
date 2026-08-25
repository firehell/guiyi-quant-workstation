from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
import json
from typing import cast

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.alerts.composition import RedisAlertHeartbeatStore
from app.alerts.evaluators import AlertEvaluation
from app.alerts.models import AlertEvent, AlertRule
from app.alerts.notification import AlertNotificationMessage, ProviderAcceptance
from app.alerts.runtime import (
    AlertRuntime,
    AlertRuntimeStatusStore,
    _event_session_window,
    _parse_event,
    _subing_snapshot_now,
)
from app.db.base import Base
from app.market_data.aggregation import SessionWindow
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.live_market import LIVE_SESSION_END_ARRIVAL_GRACE
from app.market_data.market_read_service import MarketReadWindow
from app.market_data.product_taxonomy import ProductTaxonomyEntry
from app.market_data.session_clock import SHANGHAI
from app.market_data.subing_read_service import SubingReadRequest, SubingReadSnapshot
from app.market_data.subing_research import (
    MacdCross,
    PriceSide,
    SubingDirection,
    SubingFactorResult,
    SubingFactorSnapshot,
    SubingFactorStatus,
    SubingSignalEvaluation,
    SubingSignalResolution,
    SubingSignalStatus,
)
from app.models import Exchange, Instrument, TradingCalendar, TradingSession


DAY = date(2026, 8, 14)
PRIOR_DAY = date(2026, 8, 13)
DAY_SESSION_START = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)
DAY_SESSION_END = datetime(2026, 8, 14, 3, 30, tzinfo=UTC)
ORDINARY_END = datetime(2026, 8, 14, 1, 5, tzinfo=UTC)
BOUNDARY_END = datetime(2026, 8, 14, 1, 15, tzinfo=UTC)
CROSS_MIDNIGHT_START = datetime(2026, 8, 13, 13, 0, tzinfo=UTC)
CROSS_MIDNIGHT_END = datetime(2026, 8, 13, 18, 30, tzinfo=UTC)


def _payload(
    *,
    bar_end: datetime = ORDINARY_END,
    trading_day: date = DAY,
) -> str:
    return json.dumps(
        {
            "bar_end": bar_end.isoformat(),
            "trading_day": trading_day.isoformat(),
            "open": "100",
            "high": "101",
            "low": "99",
            "close": "100",
            "volume": "10",
            "turnover": "1000",
            "open_interest": "20",
        }
    )


def _bar(
    bar_end: datetime = ORDINARY_END,
    trading_day: date = DAY,
) -> CanonicalBar:
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=trading_day,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("10"),
        turnover=Decimal("1000"),
        open_interest=Decimal("20"),
    )


def _window(
    *,
    bar_end: datetime,
    trading_day: date = DAY,
    contract: str = "JM2609",
    cutoff: datetime | None = None,
    frequency: str = "15m",
) -> MarketReadWindow:
    event_bar = _bar(bar_end, trading_day)
    return MarketReadWindow(
        symbol="jm",
        series_kind="actual_dominant",
        frequency=frequency,
        trading_day=trading_day,
        contract=contract,
        cutoff=cutoff or bar_end,
        bars=(event_bar,) * 32,
    )


def _factor(
    *,
    frequency: BarFrequency,
    bar_end: datetime,
    trading_day: date = DAY,
    status: SubingFactorStatus = SubingFactorStatus.READY,
) -> SubingFactorResult:
    if status is not SubingFactorStatus.READY:
        return SubingFactorResult(status, None)
    return SubingFactorResult(
        status,
        SubingFactorSnapshot(
            timeframe=frequency,
            bar_end=bar_end,
            trading_day=trading_day,
            contract="JM2609",
            segment_start_trading_day=date(2026, 8, 3),
            bar_source="live",
            close=Decimal("100"),
            ema21=Decimal("99"),
            price_side=PriceSide.ABOVE,
            slope_5_raw=Decimal("0.1"),
            slope_10_raw=Decimal("0.1"),
            slope_5_bps_per_bar=Decimal("10"),
            slope_10_bps_per_bar=Decimal("10"),
            macd_dif=Decimal("0.2"),
            macd_dea=Decimal("0.1"),
            macd_histogram=Decimal("0.2"),
            macd_cross=MacdCross.GOLDEN,
            macd_cross_level=Decimal("0.15"),
            macd_zero_distance_abs=Decimal("0.15"),
            macd_zero_distance_bps=Decimal("15"),
            volume=Decimal("20"),
            previous_volume=Decimal("10"),
            volume_ratio_prev=Decimal("2"),
        ),
    )


def _signal(
    *,
    status: SubingSignalStatus = SubingSignalStatus.MATCHED,
    direction: SubingDirection = SubingDirection.LONG,
    trigger_timeframe: BarFrequency | None = BarFrequency.M5,
    bar_end: datetime = ORDINARY_END,
    lower_tf_confirmation: bool = False,
    resolution: SubingSignalResolution | None = None,
    error_code: str | None = None,
) -> SubingSignalEvaluation:
    return SubingSignalEvaluation(
        status=status,
        direction=direction,
        trigger_timeframe=trigger_timeframe,
        bar_end=bar_end,
        lower_tf_confirmation=lower_tf_confirmation,
        resolution=resolution,
        conditions=(),
        error_code=error_code,
    )


def _snapshot(
    *,
    frequency: BarFrequency,
    primary_bar_end: datetime,
    primary_trading_day: date = DAY,
    primary_status: SubingFactorStatus = SubingFactorStatus.READY,
    primary_signal: SubingSignalEvaluation | None = None,
    resolved_signal: SubingSignalEvaluation | None = None,
) -> SubingReadSnapshot:
    primary = _factor(
        frequency=frequency,
        bar_end=primary_bar_end,
        trading_day=primary_trading_day,
        status=primary_status,
    )
    active_primary_signal = (
        primary_signal
        if primary_signal is not None
        else _signal(
            status=SubingSignalStatus.NOT_MATCHED,
            direction=SubingDirection.NONE,
            trigger_timeframe=frequency,
            bar_end=primary_bar_end,
        )
    )
    return SubingReadSnapshot(
        symbol="jm",
        product_name="焦煤",
        frequency=frequency,
        actual_contract="JM2609",
        dominant_mapping_date=primary_trading_day,
        segment_start_trading_day=date(2026, 8, 3),
        source_mode="canonical_live",
        live_observation="available",
        live_reason=None,
        macd_policy_id="web_macd_legacy_v1",
        signal_macd_policy_id="subing_macd_sma_window_scale2_v1",
        calibration_state="accepted",
        calibration_id="subing_intraday_v1",
        primary=primary,
        companion=None,
        primary_signal=active_primary_signal,
        resolved_signal=resolved_signal,
    )


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as active:
        yield active


def _seed_rule(
    session: Session,
    rule_code: str,
    *,
    scope: tuple[str, ...] = ("jm",),
    frequency_scope: dict[str, list[str]] | None = None,
    enabled: bool = True,
) -> AlertRule:
    if rule_code == "htdy_original_15m":
        scope_products: list[str] = []
        scope_product_frequencies = (
            frequency_scope
            if frequency_scope is not None
            else {symbol: ["15m"] for symbol in scope}
        )
    else:
        scope_products = list(scope)
        scope_product_frequencies = {}
    rule = AlertRule(
        rule_code=rule_code,
        enabled=enabled,
        scope_products=scope_products,
        scope_product_frequencies=scope_product_frequencies,
    )
    session.add(rule)
    session.commit()
    return rule


def _seed_market_facts(
    session: Session,
    *,
    session_kind: str = "day",
    include_calendar: bool = True,
    is_trading_day: bool = True,
    has_night_session: bool = True,
) -> SessionWindow:
    session.add_all(
        [
            Exchange(code="DCE", name="大商所"),
            Instrument(
                symbol="jm",
                name="焦煤",
                exchange_code="DCE",
                is_active=True,
            ),
            TradingCalendar(
                exchange_code="DCE",
                trade_date=PRIOR_DAY,
                is_trading_day=True,
                has_night_session=True,
            ),
        ]
    )
    if include_calendar:
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=DAY,
                is_trading_day=is_trading_day,
                has_night_session=has_night_session,
            )
        )
    if session_kind == "day":
        session.add(
            TradingSession(
                exchange_code="DCE",
                instrument_symbol="jm",
                session_name="day",
                start_time=time(9),
                end_time=time(11, 30),
                effective_from=date(2020, 1, 1),
                crosses_midnight=False,
                is_active=True,
            )
        )
        result = SessionWindow(DAY_SESSION_START, DAY_SESSION_END)
    else:
        session.add(
            TradingSession(
                exchange_code="DCE",
                instrument_symbol="jm",
                session_name="night",
                start_time=time(21),
                end_time=time(2, 30),
                effective_from=date(2020, 1, 1),
                crosses_midnight=True,
                is_active=True,
            )
        )
        result = SessionWindow(CROSS_MIDNIGHT_START, CROSS_MIDNIGHT_END)
    session.commit()
    return result


class FakeRead:
    def __init__(self, result: MarketReadWindow | Exception) -> None:
        self.result = result
        self.calls: list[tuple[object, dict[str, object]]] = []

    def bars_until(self, request, **kwargs) -> MarketReadWindow:
        self.calls.append((request, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeHtdyEvaluator:
    indicator_code = "huotian_dayou_original_v0"
    frequency = "15m"

    def __init__(
        self,
        observations: tuple[str, ...] = ("buy",),
        error: Exception | None = None,
    ) -> None:
        self.observations = observations
        self.error = error
        self.calls: list[MarketReadWindow] = []

    def evaluate(self, window: MarketReadWindow) -> AlertEvaluation:
        self.calls.append(window)
        if self.error is not None:
            raise self.error
        return AlertEvaluation(self.observations)


@dataclass(frozen=True, slots=True)
class SubingCall:
    request: object
    now: datetime


class FakeSubingRead:
    def __init__(
        self,
        snapshot: SubingReadSnapshot,
        error: Exception | None = None,
    ) -> None:
        self.result = snapshot
        self.error = error
        self.calls: list[SubingCall] = []
        self.raised: list[Exception] = []

    def snapshot(self, request, now: datetime) -> SubingReadSnapshot:
        self.calls.append(SubingCall(request, now))
        if self.error is not None:
            self.raised.append(self.error)
            raise self.error
        return self.result


class FakeSender:
    def __init__(
        self,
        error: Exception | None = None,
        acceptance: ProviderAcceptance | None = ProviderAcceptance(
            "private-provider-reference"
        ),
    ) -> None:
        self.error = error
        self.acceptance = acceptance
        self.messages: list[AlertNotificationMessage] = []

    def send(self, event: AlertNotificationMessage) -> ProviderAcceptance:
        self.messages.append(event)
        if self.error is not None:
            raise self.error
        return cast(ProviderAcceptance, self.acceptance)


@dataclass(frozen=True, slots=True)
class RuntimeHarness:
    runtime: AlertRuntime
    market_read: FakeRead
    subing_read: FakeSubingRead
    htdy_evaluator: FakeHtdyEvaluator
    sender: FakeSender


def _runtime(
    session: Session,
    *,
    event_end: datetime = ORDINARY_END,
    event_day: date = DAY,
    subing_snapshot: SubingReadSnapshot | None = None,
    subing_error: Exception | None = None,
    market_read_result: MarketReadWindow | Exception | None = None,
    htdy_observations: tuple[str, ...] = ("buy",),
    htdy_error: Exception | None = None,
    sender_error: Exception | None = None,
    sender_acceptance: ProviderAcceptance | None = ProviderAcceptance(
        "private-provider-reference"
    ),
    operational_products: tuple[str, ...] = ("jm",),
    clock: datetime | None = None,
    runtime_status_store: AlertRuntimeStatusStore | None = None,
    taxonomy: dict[str, ProductTaxonomyEntry] | None = None,
) -> RuntimeHarness:
    active_snapshot = subing_snapshot or _snapshot(
        frequency=BarFrequency.M5,
        primary_bar_end=event_end,
        primary_trading_day=event_day,
        resolved_signal=_signal(
            trigger_timeframe=BarFrequency.M5,
            bar_end=event_end,
        ),
    )
    market_read = FakeRead(
        market_read_result or _window(bar_end=event_end, trading_day=event_day)
    )
    subing_read = FakeSubingRead(active_snapshot, subing_error)
    htdy_evaluator = FakeHtdyEvaluator(htdy_observations, htdy_error)
    sender = FakeSender(sender_error, sender_acceptance)
    runtime = AlertRuntime(
        session_factory=lambda: nullcontext(session),
        market_read_factory=lambda _session: market_read,
        subing_read_factory=lambda _session: subing_read,
        htdy_evaluator=htdy_evaluator,
        sender=sender,
        operational_products=operational_products,
        taxonomy=(
            {"jm": ProductTaxonomyEntry(name="焦煤", sector="coal")}
            if taxonomy is None
            else taxonomy
        ),
        clock=lambda: clock or event_end + timedelta(seconds=2),
        runtime_status_store=runtime_status_store,
    )
    return RuntimeHarness(
        runtime,
        market_read,
        subing_read,
        htdy_evaluator,
        sender,
    )


def _event_rows(session: Session) -> list[AlertEvent]:
    return list(session.scalars(select(AlertEvent).order_by(AlertEvent.id)).all())


def _rule_codes(events: list[AlertEvent]) -> list[str]:
    return [event.rule.rule_code for event in events]


@pytest.mark.parametrize("frequency", ("1m", "5m", "15m", "30m", "60m"))
def test_runtime_accepts_each_completed_intraday_channel(frequency: str) -> None:
    parsed = _parse_event(f"live:bar:jm:{frequency}", _payload())

    assert parsed is not None
    assert parsed[1].value == frequency


@pytest.mark.parametrize("frequency", ("1d", "1w"))
def test_runtime_rejects_daily_and_weekly_live_bar_channels(
    frequency: str,
) -> None:
    assert _parse_event(f"live:bar:jm:{frequency}", _payload()) is None


@pytest.mark.parametrize(
    ("channel", "payload"),
    (
        ("bad", _payload()),
        ("live:bar:jm:15m:extra", _payload()),
        ("live:bar:jm:15m", "not-json"),
        ("live:bar:jm:15m", json.dumps({"bar_end": ORDINARY_END.isoformat()})),
    ),
)
def test_malformed_channel_or_payload_is_rejected(
    channel: str,
    payload: object,
) -> None:
    assert _parse_event(channel, payload) is None


@pytest.mark.parametrize("numeric", ("not-a-number", "NaN", "Infinity"))
def test_nonfinite_numeric_payload_is_rejected(numeric: str) -> None:
    payload = json.loads(_payload())
    payload["close"] = numeric

    assert _parse_event("live:bar:jm:5m", json.dumps(payload)) is None


def test_non_operational_symbol_stops_before_rule_dispatch(session: Session) -> None:
    _seed_rule(session, "subing_entry_signal_v1")
    harness = _runtime(session, operational_products=("ag",))

    harness.runtime.process_message("live:bar:jm:5m", _payload())

    assert harness.subing_read.calls == []
    assert _event_rows(session) == []
    assert harness.sender.messages == []


def test_ordinary_5m_subing_match_creates_event_and_sends_once(
    session: Session,
) -> None:
    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    snapshot = _snapshot(
        frequency=BarFrequency.M5,
        primary_bar_end=ORDINARY_END,
        resolved_signal=_signal(
            direction=SubingDirection.LONG,
            trigger_timeframe=BarFrequency.M5,
            bar_end=ORDINARY_END,
        ),
    )
    harness = _runtime(session, subing_snapshot=snapshot)

    harness.runtime.process_message("live:bar:jm:5m", _payload())

    events = _event_rows(session)
    assert harness.subing_read.calls[0].request == SubingReadRequest(
        "jm",
        BarFrequency.M5,
    )
    assert len(events) == 1
    assert events[0].frequency == "5m"
    assert events[0].result_codes == ["buy"]
    assert events[0].lower_tf_confirmation is False
    assert events[0].notification_attempted_at is not None
    assert harness.sender.messages == [
        AlertNotificationMessage(
            rule_code="subing_entry_signal_v1",
            symbol="jm",
            product_name="焦煤",
            contract="JM2609",
            frequency="5m",
            bar_end=ORDINARY_END,
            result_codes=("buy",),
            lower_tf_confirmation=False,
        )
    ]


@pytest.mark.parametrize(
    ("bar_end", "trading_day", "status"),
    (
        (ORDINARY_END + timedelta(minutes=5), DAY, SubingFactorStatus.READY),
        (ORDINARY_END, DAY + timedelta(days=1), SubingFactorStatus.READY),
        (ORDINARY_END, DAY, SubingFactorStatus.INSUFFICIENT_DATA),
    ),
)
def test_stale_or_unready_subing_primary_is_dropped_without_event_or_send(
    session: Session,
    bar_end: datetime,
    trading_day: date,
    status: SubingFactorStatus,
) -> None:
    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    snapshot = _snapshot(
        frequency=BarFrequency.M5,
        primary_bar_end=bar_end,
        primary_trading_day=trading_day,
        primary_status=status,
        resolved_signal=_signal(bar_end=bar_end),
    )
    harness = _runtime(session, subing_snapshot=snapshot)

    harness.runtime.process_message("live:bar:jm:5m", _payload())

    assert len(harness.subing_read.calls) == 1
    assert _event_rows(session) == []
    assert harness.sender.messages == []


def test_event_session_window_resolves_exact_real_day_session(session: Session) -> None:
    expected = _seed_market_facts(session)

    resolved = _event_session_window(
        session,
        symbol="jm",
        event_bar=_bar(BOUNDARY_END),
    )

    assert resolved == expected


@pytest.mark.parametrize(
    ("include_calendar", "is_trading_day"),
    ((False, True), (True, False)),
)
def test_event_session_window_requires_current_trading_calendar_fact(
    session: Session,
    include_calendar: bool,
    is_trading_day: bool,
) -> None:
    _seed_market_facts(
        session,
        include_calendar=include_calendar,
        is_trading_day=is_trading_day,
    )

    assert (
        _event_session_window(
            session,
            symbol="jm",
            event_bar=_bar(BOUNDARY_END),
        )
        is None
    )


def test_event_session_window_rejects_night_bar_on_no_night_trading_day(
    session: Session,
) -> None:
    _seed_market_facts(
        session,
        session_kind="night",
        has_night_session=False,
    )

    assert (
        _event_session_window(
            session,
            symbol="jm",
            event_bar=_bar(CROSS_MIDNIGHT_END),
        )
        is None
    )


def test_event_session_window_rejects_ambiguous_matching_windows(
    session: Session,
) -> None:
    _seed_market_facts(session)
    session.add(
        TradingSession(
            exchange_code="DCE",
            instrument_symbol="jm",
            session_name="duplicate-day-window",
            start_time=time(9),
            end_time=time(11, 30),
            effective_from=date(2020, 1, 1),
            crosses_midnight=False,
            is_active=True,
        )
    )
    session.commit()

    assert (
        _event_session_window(
            session,
            symbol="jm",
            event_bar=_bar(BOUNDARY_END),
        )
        is None
    )


def test_same_boundary_5m_defers_to_single_15m_subing_evaluation(
    session: Session,
) -> None:
    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    snapshot = _snapshot(
        frequency=BarFrequency.M15,
        primary_bar_end=BOUNDARY_END,
        resolved_signal=_signal(
            trigger_timeframe=BarFrequency.M15,
            bar_end=BOUNDARY_END,
        ),
    )
    harness = _runtime(
        session,
        event_end=BOUNDARY_END,
        subing_snapshot=snapshot,
    )

    harness.runtime.process_message(
        "live:bar:jm:5m",
        _payload(bar_end=BOUNDARY_END),
    )

    assert harness.subing_read.calls == []
    assert _event_rows(session) == []

    harness.runtime.process_message(
        "live:bar:jm:15m",
        _payload(bar_end=BOUNDARY_END),
    )

    assert len(harness.subing_read.calls) == 1
    assert harness.subing_read.calls[0].request == SubingReadRequest(
        "jm",
        BarFrequency.M15,
    )
    assert len(_event_rows(session)) == 1
    assert len(harness.sender.messages) == 1


@pytest.mark.parametrize(
    ("session_kind", "bar_end"),
    (("day", DAY_SESSION_END), ("night", CROSS_MIDNIGHT_END)),
)
def test_session_final_bar_uses_bounded_phase_observation_handoff(
    session: Session,
    session_kind: str,
    bar_end: datetime,
) -> None:
    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session, session_kind=session_kind)
    snapshot = _snapshot(
        frequency=BarFrequency.M15,
        primary_bar_end=bar_end,
        resolved_signal=_signal(
            trigger_timeframe=BarFrequency.M15,
            bar_end=bar_end,
        ),
    )
    harness = _runtime(
        session,
        event_end=bar_end,
        subing_snapshot=snapshot,
        clock=bar_end + timedelta(seconds=2),
    )

    harness.runtime.process_message(
        "live:bar:jm:15m",
        _payload(bar_end=bar_end),
    )

    assert harness.subing_read.calls[0].now == bar_end - timedelta(microseconds=1)
    assert len(_event_rows(session)) == 1
    assert len(harness.sender.messages) == 1


def test_session_final_bar_after_shared_grace_is_dropped(session: Session) -> None:
    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    snapshot = _snapshot(
        frequency=BarFrequency.M15,
        primary_bar_end=DAY_SESSION_END,
        resolved_signal=_signal(
            trigger_timeframe=BarFrequency.M15,
            bar_end=DAY_SESSION_END,
        ),
    )
    harness = _runtime(
        session,
        event_end=DAY_SESSION_END,
        subing_snapshot=snapshot,
        clock=(
            DAY_SESSION_END + LIVE_SESSION_END_ARRIVAL_GRACE + timedelta(microseconds=1)
        ),
    )

    harness.runtime.process_message(
        "live:bar:jm:15m",
        _payload(bar_end=DAY_SESSION_END),
    )

    assert harness.subing_read.calls == []
    assert _event_rows(session) == []
    assert harness.sender.messages == []


def test_ordinary_bar_uses_processing_time_without_adjustment(session: Session) -> None:
    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    processing_now = ORDINARY_END + timedelta(seconds=2)
    harness = _runtime(session, clock=processing_now)

    harness.runtime.process_message("live:bar:jm:5m", _payload())

    assert harness.subing_read.calls[0].now == processing_now


@pytest.mark.parametrize(
    ("processing_now", "event_end", "session_end", "expected"),
    (
        (
            ORDINARY_END - timedelta(microseconds=1),
            ORDINARY_END,
            DAY_SESSION_END,
            None,
        ),
        (
            ORDINARY_END + timedelta(seconds=2),
            ORDINARY_END,
            DAY_SESSION_END,
            ORDINARY_END + timedelta(seconds=2),
        ),
        (
            DAY_SESSION_END + LIVE_SESSION_END_ARRIVAL_GRACE,
            DAY_SESSION_END,
            DAY_SESSION_END,
            DAY_SESSION_END - timedelta(microseconds=1),
        ),
        (
            DAY_SESSION_END
            + LIVE_SESSION_END_ARRIVAL_GRACE
            + timedelta(microseconds=1),
            DAY_SESSION_END,
            DAY_SESSION_END,
            None,
        ),
    ),
)
def test_subing_snapshot_now_obeys_exact_final_bar_contract(
    processing_now: datetime,
    event_end: datetime,
    session_end: datetime,
    expected: datetime | None,
) -> None:
    assert (
        _subing_snapshot_now(
            event_bar=_bar(event_end),
            event_session=SessionWindow(DAY_SESSION_START, session_end),
            processing_now=processing_now,
        )
        == expected
    )


def test_reciprocal_only_resolved_match_drives_event_and_sender(
    session: Session,
) -> None:
    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    primary_signal = _signal(
        status=SubingSignalStatus.NOT_MATCHED,
        direction=SubingDirection.NONE,
        trigger_timeframe=BarFrequency.M15,
        bar_end=BOUNDARY_END,
    )
    resolved_signal = _signal(
        direction=SubingDirection.SHORT,
        trigger_timeframe=BarFrequency.M5,
        bar_end=BOUNDARY_END,
    )
    snapshot = _snapshot(
        frequency=BarFrequency.M15,
        primary_bar_end=BOUNDARY_END,
        primary_signal=primary_signal,
        resolved_signal=resolved_signal,
    )
    harness = _runtime(
        session,
        event_end=BOUNDARY_END,
        subing_snapshot=snapshot,
    )

    harness.runtime.process_message(
        "live:bar:jm:15m",
        _payload(bar_end=BOUNDARY_END),
    )

    events = _event_rows(session)
    assert len(events) == 1
    assert events[0].frequency == "5m"
    assert events[0].result_codes == ["sell"]
    assert events[0].lower_tf_confirmation is False
    assert harness.sender.messages == [
        AlertNotificationMessage(
            rule_code="subing_entry_signal_v1",
            symbol="jm",
            product_name="焦煤",
            contract="JM2609",
            frequency="5m",
            bar_end=BOUNDARY_END,
            result_codes=("sell",),
            lower_tf_confirmation=False,
        )
    ]


def test_higher_timeframe_resolved_confirmation_drives_event_and_sender(
    session: Session,
) -> None:
    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    primary_signal = _signal(
        direction=SubingDirection.LONG,
        trigger_timeframe=BarFrequency.M15,
        bar_end=BOUNDARY_END,
        lower_tf_confirmation=False,
    )
    resolved_signal = _signal(
        direction=SubingDirection.LONG,
        trigger_timeframe=BarFrequency.M15,
        bar_end=BOUNDARY_END,
        lower_tf_confirmation=True,
        resolution=SubingSignalResolution.HIGHER_TIMEFRAME_WINS,
    )
    snapshot = _snapshot(
        frequency=BarFrequency.M15,
        primary_bar_end=BOUNDARY_END,
        primary_signal=primary_signal,
        resolved_signal=resolved_signal,
    )
    harness = _runtime(
        session,
        event_end=BOUNDARY_END,
        subing_snapshot=snapshot,
    )

    harness.runtime.process_message(
        "live:bar:jm:15m",
        _payload(bar_end=BOUNDARY_END),
    )

    events = _event_rows(session)
    assert len(events) == 1
    assert events[0].frequency == "15m"
    assert events[0].result_codes == ["buy"]
    assert events[0].lower_tf_confirmation is True
    assert harness.sender.messages == [
        AlertNotificationMessage(
            rule_code="subing_entry_signal_v1",
            symbol="jm",
            product_name="焦煤",
            contract="JM2609",
            frequency="15m",
            bar_end=BOUNDARY_END,
            result_codes=("buy",),
            lower_tf_confirmation=True,
        )
    ]


@pytest.mark.parametrize(
    "resolved_signal",
    (
        None,
        _signal(
            status=SubingSignalStatus.NOT_MATCHED,
            direction=SubingDirection.NONE,
            trigger_timeframe=None,
            bar_end=BOUNDARY_END,
            resolution=SubingSignalResolution.DIRECTION_CONFLICT,
            error_code="SUBING_SIGNAL_DIRECTION_CONFLICT",
        ),
    ),
)
def test_none_or_direction_conflict_resolved_signal_creates_no_event(
    session: Session,
    resolved_signal: SubingSignalEvaluation | None,
) -> None:
    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    snapshot = _snapshot(
        frequency=BarFrequency.M15,
        primary_bar_end=BOUNDARY_END,
        resolved_signal=resolved_signal,
    )
    harness = _runtime(
        session,
        event_end=BOUNDARY_END,
        subing_snapshot=snapshot,
    )

    harness.runtime.process_message(
        "live:bar:jm:15m",
        _payload(bar_end=BOUNDARY_END),
    )

    assert _event_rows(session) == []
    assert harness.sender.messages == []


def test_subing_failure_does_not_block_htdy(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _seed_rule(session, "htdy_original_15m")
    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    subing_error = RuntimeError("SUBING_READ_FAILED")
    harness = _runtime(
        session,
        event_end=BOUNDARY_END,
        subing_error=subing_error,
        htdy_observations=("sell",),
    )

    harness.runtime.process_message(
        "live:bar:jm:15m",
        _payload(bar_end=BOUNDARY_END),
    )

    events = _event_rows(session)
    assert len(harness.subing_read.calls) == 1
    assert harness.subing_read.calls[0].request == SubingReadRequest(
        "jm",
        BarFrequency.M15,
    )
    assert harness.subing_read.raised == [subing_error]
    assert caplog.messages.count("ALERT_RULE_PROCESSING_FAILED") == 1
    assert _rule_codes(events) == ["htdy_original_15m"]
    assert events[0].result_codes == ["sell"]
    assert harness.sender.messages == [
        AlertNotificationMessage(
            rule_code="htdy_original_15m",
            symbol="jm",
            product_name="焦煤",
            contract="JM2609",
            frequency="15m",
            bar_end=BOUNDARY_END,
            result_codes=("sell",),
            lower_tf_confirmation=False,
        )
    ]


def test_htdy_failure_does_not_block_subing(session: Session) -> None:
    _seed_rule(session, "htdy_original_15m")
    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    snapshot = _snapshot(
        frequency=BarFrequency.M15,
        primary_bar_end=BOUNDARY_END,
        resolved_signal=_signal(
            trigger_timeframe=BarFrequency.M15,
            bar_end=BOUNDARY_END,
        ),
    )
    harness = _runtime(
        session,
        event_end=BOUNDARY_END,
        subing_snapshot=snapshot,
        htdy_error=RuntimeError("x"),
    )

    harness.runtime.process_message(
        "live:bar:jm:15m",
        _payload(bar_end=BOUNDARY_END),
    )

    assert _rule_codes(_event_rows(session)) == ["subing_entry_signal_v1"]


def test_htdy_keeps_exact_event_cutoff_market_read_path(session: Session) -> None:
    _seed_rule(session, "htdy_original_15m")
    harness = _runtime(
        session,
        event_end=BOUNDARY_END,
        htdy_observations=("buy", "sell"),
    )

    harness.runtime.process_message(
        "live:bar:jm:15m",
        _payload(bar_end=BOUNDARY_END),
    )

    request, kwargs = harness.market_read.calls[0]
    assert request.series_kind.value == "actual_dominant"
    assert request.symbol == "jm"
    assert request.frequency is BarFrequency.M15
    assert kwargs == {"trading_day": DAY, "end": BOUNDARY_END, "limit": 32}
    events = _event_rows(session)
    assert events[0].result_codes == ["buy", "sell"]


def test_htdy_uses_exact_frequency_pair_scope_before_market_read(
    session: Session,
) -> None:
    _seed_rule(
        session,
        "htdy_original_15m",
        frequency_scope={"jm": ["15m"]},
    )
    harness = _runtime(session)

    harness.runtime.process_message("live:bar:jm:5m", _payload())

    assert harness.market_read.calls == []
    assert harness.htdy_evaluator.calls == []
    assert _event_rows(session) == []
    assert harness.sender.messages == []

    harness.runtime.process_message("live:bar:jm:15m", _payload())

    assert len(harness.market_read.calls) == 1
    assert len(harness.htdy_evaluator.calls) == 1
    assert [event.frequency for event in _event_rows(session)] == ["15m"]
    assert [message.frequency for message in harness.sender.messages] == ["15m"]


def test_htdy_enabled_frequency_pairs_evaluate_independently(
    session: Session,
) -> None:
    _seed_rule(
        session,
        "htdy_original_15m",
        frequency_scope={"jm": ["5m", "15m"]},
    )
    harness = _runtime(
        session,
        market_read_result=_window(
            bar_end=BOUNDARY_END,
            frequency="5m",
        ),
        event_end=BOUNDARY_END,
    )

    harness.runtime.process_message(
        "live:bar:jm:5m",
        _payload(bar_end=BOUNDARY_END),
    )
    harness.market_read.result = _window(
        bar_end=BOUNDARY_END,
        frequency="15m",
    )
    harness.runtime.process_message(
        "live:bar:jm:15m",
        _payload(bar_end=BOUNDARY_END),
    )

    assert [call[0].frequency for call in harness.market_read.calls] == [
        BarFrequency.M5,
        BarFrequency.M15,
    ]
    assert [window.frequency for window in harness.htdy_evaluator.calls] == [
        "5m",
        "15m",
    ]
    assert [event.frequency for event in _event_rows(session)] == ["5m", "15m"]
    assert [message.frequency for message in harness.sender.messages] == [
        "5m",
        "15m",
    ]


def test_htdy_mixed_scope_authority_fails_before_evaluation(
    session: Session,
) -> None:
    rule = _seed_rule(
        session,
        "htdy_original_15m",
        frequency_scope={"jm": ["15m"]},
    )
    rule.scope_products = ["jm"]
    session.commit()
    harness = _runtime(session)

    harness.runtime.process_message("live:bar:jm:15m", _payload())

    assert harness.market_read.calls == []
    assert harness.htdy_evaluator.calls == []
    assert _event_rows(session) == []
    assert harness.sender.messages == []


def test_htdy_mismatched_event_cutoff_creates_no_event(session: Session) -> None:
    _seed_rule(session, "htdy_original_15m")
    harness = _runtime(
        session,
        event_end=BOUNDARY_END,
        market_read_result=_window(
            bar_end=BOUNDARY_END,
            cutoff=BOUNDARY_END - timedelta(minutes=15),
        ),
    )

    harness.runtime.process_message(
        "live:bar:jm:15m",
        _payload(bar_end=BOUNDARY_END),
    )

    assert _event_rows(session) == []
    assert harness.sender.messages == []


def test_htdy_same_cutoff_with_different_bar_values_creates_no_event(
    session: Session,
) -> None:
    """Catches an Event being attributed to a Pub/Sub bar the reader did not return."""
    _seed_rule(session, "htdy_original_15m")
    mismatched = CanonicalBar(
        bar_end=BOUNDARY_END,
        trading_day=DAY,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("10"),
        turnover=Decimal("1000"),
        open_interest=Decimal("20"),
    )
    window = MarketReadWindow(
        symbol="jm",
        series_kind="actual_dominant",
        frequency="15m",
        trading_day=DAY,
        contract="JM2609",
        cutoff=BOUNDARY_END,
        bars=(_bar(BOUNDARY_END),) * 31 + (mismatched,),
    )
    harness = _runtime(
        session,
        event_end=BOUNDARY_END,
        market_read_result=window,
    )

    harness.runtime.process_message(
        "live:bar:jm:15m",
        _payload(bar_end=BOUNDARY_END),
    )

    assert _event_rows(session) == []
    assert harness.sender.messages == []


def test_duplicate_pubsub_creates_one_event_and_sends_once(session: Session) -> None:
    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    harness = _runtime(session)

    harness.runtime.process_message("live:bar:jm:5m", _payload())
    harness.runtime.process_message("live:bar:jm:5m", _payload())

    assert len(_event_rows(session)) == 1
    assert len(harness.sender.messages) == 1


def test_notification_failure_keeps_event_and_duplicate_never_retries(
    session: Session,
) -> None:
    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    harness = _runtime(session, sender_error=RuntimeError("send failed"))

    harness.runtime.process_message("live:bar:jm:5m", _payload())
    harness.runtime.process_message("live:bar:jm:5m", _payload())

    assert len(_event_rows(session)) == 1
    assert len(harness.sender.messages) == 1


def test_notification_failure_does_not_block_next_completed_bar(
    session: Session,
) -> None:
    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    harness = _runtime(session, sender_error=RuntimeError("send failed"))

    harness.runtime.process_message("live:bar:jm:5m", _payload())
    next_end = ORDINARY_END + timedelta(minutes=15)
    harness.subing_read.result = _snapshot(
        frequency=BarFrequency.M5,
        primary_bar_end=next_end,
        resolved_signal=_signal(
            trigger_timeframe=BarFrequency.M5,
            bar_end=next_end,
        ),
    )
    harness.runtime.clock = lambda: next_end + timedelta(seconds=2)
    harness.runtime.process_message(
        "live:bar:jm:5m",
        _payload(bar_end=next_end),
    )

    assert len(_event_rows(session)) == 2
    assert len(harness.sender.messages) == 2


def test_multiple_messages_from_one_bar_are_sent_sequentially(session: Session) -> None:
    _seed_rule(session, "htdy_original_15m")
    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    snapshot = _snapshot(
        frequency=BarFrequency.M15,
        primary_bar_end=BOUNDARY_END,
        resolved_signal=_signal(
            trigger_timeframe=BarFrequency.M15,
            bar_end=BOUNDARY_END,
        ),
    )
    harness = _runtime(
        session,
        event_end=BOUNDARY_END,
        subing_snapshot=snapshot,
    )

    harness.runtime.process_message(
        "live:bar:jm:15m",
        _payload(bar_end=BOUNDARY_END),
    )

    assert len(_event_rows(session)) == 2
    assert [message.rule_code for message in harness.sender.messages] == [
        "htdy_original_15m",
        "subing_entry_signal_v1",
    ]


@pytest.mark.parametrize("revocation", ("disable", "scope_remove"))
def test_runtime_refreshes_rule_truth_after_external_revocation(
    revocation: str,
    tmp_path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'alerts.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as runtime_session:
        _seed_rule(runtime_session, "subing_entry_signal_v1")
        cached = runtime_session.scalar(select(AlertRule))
        assert cached is not None
        with Session(engine) as writer:
            rule = writer.scalar(select(AlertRule))
            assert rule is not None
            if revocation == "disable":
                rule.enabled = False
            else:
                rule.scope_products = []
            writer.commit()

        harness = _runtime(runtime_session)
        harness.runtime.process_message("live:bar:jm:5m", _payload())

        assert harness.subing_read.calls == []
        assert _event_rows(runtime_session) == []


class FakeMessageSource:
    def __init__(self) -> None:
        self.patterns: list[str] = []

    def subscribe(self, pattern: str) -> None:
        self.patterns.append(pattern)

    def get_message(self, *, timeout_seconds: float):
        assert timeout_seconds == 1.0
        return None

    def close(self) -> None:
        return None


class FakeHeartbeatStore:
    def __init__(self) -> None:
        self.writes: list[tuple[dict[str, object], int]] = []

    def write(self, payload: dict[str, object], *, ttl_seconds: int) -> None:
        self.writes.append((payload, ttl_seconds))


class RuntimeStatusRedis:
    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self.values: dict[str, str] = {}
        if payload is not None:
            self.values["alert:runtime-status"] = json.dumps(payload)

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> bool:
        self.values[key] = value
        return True


def _runtime_status_payload(**overrides: object) -> dict[str, object]:
    return {
        "schema_version": 1,
        "last_processed_bar_at": None,
        "last_processing_success_at": None,
        "last_processing_failure_at": None,
        "processing_error_type": None,
        "last_event_at": None,
        "last_transport_attempt_at": None,
        "last_provider_accepted_at": None,
        "last_notification_failure_at": None,
        "notification_error_type": None,
        "consecutive_notification_failures": 0,
        **overrides,
    }


def test_redis_heartbeat_store_sets_value_and_ttl_atomically() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.calls = []

        def set(self, *args, **kwargs) -> bool:
            self.calls.append((args, kwargs))
            return True

        def expire(self, *_args, **_kwargs):
            raise AssertionError("heartbeat TTL must be atomic with SET")

    redis = FakeRedis()

    RedisAlertHeartbeatStore(redis).write({"available": True}, ttl_seconds=30)

    assert len(redis.calls) == 1
    assert redis.calls[0][0][0] == "alert:heartbeat"
    assert json.loads(redis.calls[0][0][1]) == {"available": True}
    assert redis.calls[0][1] == {"ex": 30}


def test_redis_runtime_status_store_persists_schema_v1_without_ttl() -> None:
    from app.alerts import composition

    class FakeRedis:
        def __init__(self) -> None:
            self.calls = []

        def set(self, *args, **kwargs) -> bool:
            self.calls.append((args, kwargs))
            return True

    redis = FakeRedis()
    payload = {
        "schema_version": 1,
        "last_processed_bar_at": "2026-08-14T00:00:00+00:00",
        "last_processing_success_at": "2026-08-14T00:00:02+00:00",
        "last_processing_failure_at": None,
        "processing_error_type": None,
        "last_event_at": "2026-08-14T00:00:02+00:00",
        "last_transport_attempt_at": "2026-08-14T00:00:02+00:00",
        "last_provider_accepted_at": "2026-08-14T00:00:02+00:00",
        "last_notification_failure_at": None,
        "notification_error_type": None,
        "consecutive_notification_failures": 0,
    }

    composition.RedisAlertRuntimeStatusStore(redis).write(payload)

    assert redis.calls == [
        (("alert:runtime-status", json.dumps(payload, ensure_ascii=False, separators=(",", ":"))), {})
    ]
    assert "provider_reference" not in redis.calls[0][0][1]


def test_redis_runtime_status_store_rejects_failed_set() -> None:
    from app.alerts.composition import RedisAlertRuntimeStatusStore

    class FailedRedis:
        def set(self, *_args, **_kwargs) -> bool:
            return False

    with pytest.raises(
        RuntimeError,
        match="^ALERT_RUNTIME_STATUS_WRITE_FAILED$",
    ):
        RedisAlertRuntimeStatusStore(FailedRedis()).write(
            {
                "schema_version": 1,
                "last_processed_bar_at": None,
                "last_processing_success_at": None,
                "last_processing_failure_at": None,
                "processing_error_type": None,
                "last_event_at": None,
                "last_transport_attempt_at": None,
                "last_provider_accepted_at": None,
                "last_notification_failure_at": None,
                "notification_error_type": None,
                "consecutive_notification_failures": 0,
            }
        )


@pytest.mark.parametrize(
    "error_field",
    ("processing_error_type", "notification_error_type"),
)
def test_redis_runtime_status_store_rejects_nonpublic_error_token(
    error_field: str,
) -> None:
    from app.alerts.composition import RedisAlertRuntimeStatusStore

    class RecordingRedis:
        def __init__(self) -> None:
            self.values: dict[str, str] = {}

        def set(self, key: str, value: str) -> bool:
            self.values[key] = value
            return True

    redis = RecordingRedis()

    with pytest.raises(ValueError, match="^ALERT_RUNTIME_STATUS_INVALID$"):
        RedisAlertRuntimeStatusStore(redis).write(
            _runtime_status_payload(
                **{error_field: "must_not_leak"}
            )
        )

    assert redis.values == {}


def test_runtime_status_write_failure_escapes_processing_boundary(
    session: Session,
) -> None:
    from app.alerts.runtime import empty_alert_runtime_status

    class FailingStatusStore:
        def read(self) -> dict[str, object]:
            return empty_alert_runtime_status()

        def write(self, _payload: dict[str, object]) -> None:
            raise RuntimeError("ALERT_RUNTIME_STATUS_WRITE_FAILED")

    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    harness = _runtime(
        session,
        runtime_status_store=FailingStatusStore(),
    )

    with pytest.raises(
        RuntimeError,
        match="^ALERT_RUNTIME_STATUS_WRITE_FAILED$",
    ):
        harness.runtime.process_message("live:bar:jm:5m", _payload())

    assert len(_event_rows(session)) == 1


@pytest.mark.parametrize(
    (
        "failure_stage",
        "taxonomy",
        "sender_error",
        "expected_sender_calls",
    ),
    (
        ("preparation_failure", {}, None, 0),
        ("transport_attempt", None, None, 0),
        (
            "transport_failure",
            None,
            RuntimeError("private transport detail"),
            1,
        ),
        ("provider_acceptance", None, None, 1),
    ),
)
def test_runtime_status_write_failure_escapes_each_notification_boundary(
    session: Session,
    failure_stage: str,
    taxonomy: dict[str, ProductTaxonomyEntry] | None,
    sender_error: Exception | None,
    expected_sender_calls: int,
) -> None:
    from app.alerts.runtime import empty_alert_runtime_status

    class BoundaryFailingStatusStore:
        def __init__(self) -> None:
            self.status = empty_alert_runtime_status()

        def read(self) -> dict[str, object]:
            return self.status

        def write(self, payload: dict[str, object]) -> None:
            if self._matches_failure_stage(payload):
                raise RuntimeError("ALERT_RUNTIME_STATUS_WRITE_FAILED")
            self.status = dict(payload)

        def _matches_failure_stage(self, payload: dict[str, object]) -> bool:
            if failure_stage == "preparation_failure":
                return (
                    payload["notification_error_type"]
                    == "notification_preparation_failed"
                    and payload["last_transport_attempt_at"] is None
                )
            if failure_stage == "transport_attempt":
                return (
                    payload["last_transport_attempt_at"] is not None
                    and payload["last_provider_accepted_at"] is None
                    and payload["last_notification_failure_at"] is None
                )
            if failure_stage == "transport_failure":
                return (
                    payload["last_transport_attempt_at"] is not None
                    and payload["notification_error_type"]
                    == "notification_transport_failed"
                )
            return payload["last_provider_accepted_at"] is not None

    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    harness = _runtime(
        session,
        taxonomy=taxonomy,
        sender_error=sender_error,
        runtime_status_store=BoundaryFailingStatusStore(),
    )

    with pytest.raises(
        RuntimeError,
        match="^ALERT_RUNTIME_STATUS_WRITE_FAILED$",
    ):
        harness.runtime.process_message("live:bar:jm:5m", _payload())

    assert len(_event_rows(session)) == 1
    assert len(harness.sender.messages) == expected_sender_calls


def test_runtime_status_records_processing_event_and_provider_acceptance(
    session: Session,
) -> None:
    from app.alerts.composition import RedisAlertRuntimeStatusStore

    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    redis = RuntimeStatusRedis()
    harness = _runtime(
        session,
        runtime_status_store=RedisAlertRuntimeStatusStore(redis),
    )

    harness.runtime.process_message("live:bar:jm:5m", _payload())

    status = json.loads(redis.values["alert:runtime-status"])
    observed_at = (ORDINARY_END + timedelta(seconds=2)).isoformat()
    assert status == {
        "schema_version": 1,
        "last_processed_bar_at": ORDINARY_END.isoformat(),
        "last_processing_success_at": observed_at,
        "last_processing_failure_at": None,
        "processing_error_type": None,
        "last_event_at": observed_at,
        "last_transport_attempt_at": observed_at,
        "last_provider_accepted_at": observed_at,
        "last_notification_failure_at": None,
        "notification_error_type": None,
        "consecutive_notification_failures": 0,
    }
    assert "private-provider-reference" not in redis.values["alert:runtime-status"]


def test_missing_taxonomy_records_preparation_failure_without_transport_attempt(
    session: Session,
) -> None:
    from app.alerts.composition import RedisAlertRuntimeStatusStore

    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    redis = RuntimeStatusRedis()
    harness = _runtime(
        session,
        taxonomy={},
        runtime_status_store=RedisAlertRuntimeStatusStore(redis),
    )

    harness.runtime.process_message("live:bar:jm:5m", _payload())

    event = _event_rows(session)[0]
    observed_at = ORDINARY_END + timedelta(seconds=2)
    assert event.notification_attempted_at == observed_at.replace(tzinfo=None)
    status = json.loads(redis.values["alert:runtime-status"])
    assert status["last_event_at"] == observed_at.isoformat()
    assert status["last_transport_attempt_at"] is None
    assert status["last_provider_accepted_at"] is None
    assert status["last_notification_failure_at"] == observed_at.isoformat()
    assert status["notification_error_type"] == "notification_preparation_failed"
    assert status["consecutive_notification_failures"] == 1


def test_transport_failure_is_persisted_after_real_attempt(
    session: Session,
) -> None:
    from app.alerts.composition import RedisAlertRuntimeStatusStore

    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    redis = RuntimeStatusRedis()
    harness = _runtime(
        session,
        sender_error=RuntimeError("private provider failure"),
        runtime_status_store=RedisAlertRuntimeStatusStore(redis),
    )

    harness.runtime.process_message("live:bar:jm:5m", _payload())

    observed_at = (ORDINARY_END + timedelta(seconds=2)).isoformat()
    status = json.loads(redis.values["alert:runtime-status"])
    assert status["last_transport_attempt_at"] == observed_at
    assert status["last_provider_accepted_at"] is None
    assert status["last_notification_failure_at"] == observed_at
    assert status["notification_error_type"] == "notification_transport_failed"
    assert status["consecutive_notification_failures"] == 1
    assert "private provider failure" not in redis.values["alert:runtime-status"]


def test_missing_provider_acceptance_is_a_notification_failure(
    session: Session,
) -> None:
    from app.alerts.composition import RedisAlertRuntimeStatusStore

    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    redis = RuntimeStatusRedis()
    harness = _runtime(
        session,
        sender_acceptance=None,
        runtime_status_store=RedisAlertRuntimeStatusStore(redis),
    )

    harness.runtime.process_message("live:bar:jm:5m", _payload())

    status = json.loads(redis.values["alert:runtime-status"])
    observed_at = (ORDINARY_END + timedelta(seconds=2)).isoformat()
    assert status["last_transport_attempt_at"] == observed_at
    assert status["last_provider_accepted_at"] is None
    assert status["last_notification_failure_at"] == observed_at
    assert status["notification_error_type"] == "notification_acceptance_invalid"


def test_next_provider_acceptance_clears_notification_failure_state(
    session: Session,
) -> None:
    from app.alerts.composition import RedisAlertRuntimeStatusStore

    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    redis = RuntimeStatusRedis(
        _runtime_status_payload(
            last_transport_attempt_at="2026-08-13T01:00:00+00:00",
            last_provider_accepted_at="2026-08-13T01:00:00+00:00",
            last_notification_failure_at="2026-08-13T01:01:00+00:00",
            notification_error_type="notification_transport_failed",
            consecutive_notification_failures=2,
        )
    )
    harness = _runtime(
        session,
        runtime_status_store=RedisAlertRuntimeStatusStore(redis),
    )

    harness.runtime.process_message("live:bar:jm:5m", _payload())

    status = json.loads(redis.values["alert:runtime-status"])
    assert status["last_provider_accepted_at"] == (
        ORDINARY_END + timedelta(seconds=2)
    ).isoformat()
    assert status["last_notification_failure_at"] is None
    assert status["notification_error_type"] is None
    assert status["consecutive_notification_failures"] == 0


def test_processing_failure_after_success_persists_latest_failure(
    session: Session,
) -> None:
    from app.alerts.composition import RedisAlertRuntimeStatusStore

    _seed_rule(session, "htdy_original_15m")
    redis = RuntimeStatusRedis(
        _runtime_status_payload(
            last_processed_bar_at="2026-08-13T01:00:00+00:00",
            last_processing_success_at="2026-08-13T01:00:02+00:00",
        )
    )
    harness = _runtime(
        session,
        event_end=BOUNDARY_END,
        htdy_error=RuntimeError("private processing detail"),
        runtime_status_store=RedisAlertRuntimeStatusStore(redis),
    )

    harness.runtime.process_message(
        "live:bar:jm:15m",
        _payload(bar_end=BOUNDARY_END),
    )

    observed_at = (BOUNDARY_END + timedelta(seconds=2)).isoformat()
    status = json.loads(redis.values["alert:runtime-status"])
    assert status["last_processed_bar_at"] == BOUNDARY_END.isoformat()
    assert status["last_processing_success_at"] == "2026-08-13T01:00:02+00:00"
    assert status["last_processing_failure_at"] == observed_at
    assert status["processing_error_type"] == "processing_failed"
    assert "private processing detail" not in redis.values["alert:runtime-status"]


def test_fatal_session_failure_never_sends_queued_notification(
    session: Session,
) -> None:
    from app.alerts.composition import RedisAlertRuntimeStatusStore

    class FailingSessionContext:
        def __enter__(self) -> Session:
            return session

        def __exit__(self, *_args: object) -> None:
            raise RuntimeError("private database exit detail")

    _seed_rule(session, "subing_entry_signal_v1")
    _seed_market_facts(session)
    redis = RuntimeStatusRedis()
    harness = _runtime(
        session,
        runtime_status_store=RedisAlertRuntimeStatusStore(redis),
    )
    harness.runtime._session_factory = FailingSessionContext

    harness.runtime.process_message("live:bar:jm:5m", _payload())

    assert len(_event_rows(session)) == 1
    assert harness.sender.messages == []
    status = json.loads(redis.values["alert:runtime-status"])
    assert status["last_processing_failure_at"] == (
        ORDINARY_END + timedelta(seconds=2)
    ).isoformat()
    assert status["processing_error_type"] == "processing_failed"
    assert status["last_transport_attempt_at"] is None
    assert "private database exit detail" not in redis.values[
        "alert:runtime-status"
    ]


def test_run_forever_uses_single_transport_and_fixed_heartbeat_contract(
    session: Session,
) -> None:
    _seed_rule(session, "htdy_original_15m")
    _seed_rule(session, "subing_entry_signal_v1", scope=())
    moments = iter(
        datetime(2026, 8, 14, 0, 0, second, tzinfo=UTC)
        for second in (0, 0, 5, 10, 10, 15, 20, 20)
    )
    checks = iter((False, False, False, False, False, False, True))
    source = FakeMessageSource()
    heartbeats = FakeHeartbeatStore()
    harness = _runtime(session)
    harness.runtime.message_source = source
    harness.runtime.heartbeat_store = heartbeats
    harness.runtime.clock = lambda: next(moments)
    harness.runtime.stop_requested = lambda: next(checks)

    harness.runtime.run_forever()

    assert source.patterns == ["live:bar:*:*"]
    assert [ttl for _payload, ttl in heartbeats.writes] == [30, 30, 30]
    assert [payload["generated_at"] for payload, _ttl in heartbeats.writes] == [
        "2026-08-14T00:00:00+00:00",
        "2026-08-14T00:00:10+00:00",
        "2026-08-14T00:00:20+00:00",
    ]
    assert [payload["enabled_rule_count"] for payload, _ttl in heartbeats.writes] == [
        2,
        2,
        2,
    ]
    assert [payload["scope_product_count"] for payload, _ttl in heartbeats.writes] == [
        1,
        1,
        1,
    ]


def test_heartbeat_counts_distinct_products_across_valid_rule_scopes(
    session: Session,
) -> None:
    _seed_rule(
        session,
        "htdy_original_15m",
        frequency_scope={"jm": ["5m", "15m"]},
    )
    _seed_rule(session, "subing_entry_signal_v1", scope=("ag",))
    heartbeats = FakeHeartbeatStore()
    harness = _runtime(session, operational_products=("jm", "ag"))
    harness.runtime.heartbeat_store = heartbeats
    now = datetime(2026, 8, 14, 0, 0, tzinfo=UTC)

    harness.runtime._write_heartbeat(now)

    assert heartbeats.writes == [
        (
            {
                "generated_at": "2026-08-14T00:00:00+00:00",
                "available": True,
                "enabled_rule_count": 2,
                "scope_product_count": 2,
            },
            30,
        )
    ]


def test_heartbeat_does_not_union_or_count_mixed_scope_authority(
    session: Session,
) -> None:
    rule = _seed_rule(
        session,
        "htdy_original_15m",
        frequency_scope={"ag": ["15m"]},
    )
    rule.scope_products = ["jm"]
    session.commit()
    heartbeats = FakeHeartbeatStore()
    harness = _runtime(session, operational_products=("jm", "ag"))
    harness.runtime.heartbeat_store = heartbeats

    harness.runtime._write_heartbeat(
        datetime(2026, 8, 14, 0, 0, tzinfo=UTC)
    )

    assert heartbeats.writes[0][0]["enabled_rule_count"] == 1
    assert heartbeats.writes[0][0]["scope_product_count"] == 0


def test_session_fixture_uses_real_shanghai_anchor() -> None:
    assert DAY_SESSION_START.astimezone(SHANGHAI).time() == time(9)
    assert CROSS_MIDNIGHT_START.astimezone(SHANGHAI).time() == time(21)
    assert CROSS_MIDNIGHT_END.astimezone(SHANGHAI).time() == time(2, 30)
