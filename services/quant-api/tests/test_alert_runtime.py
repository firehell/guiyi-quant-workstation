from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
import json
from typing import cast

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.alerts.runtime as alert_runtime_module
from app.alerts.composition import RedisAlertHeartbeatStore, RedisAlertMessageSource
from app.alerts.evaluators import AlertEvaluation
from app.alerts.models import AlertEvent, AlertRule
from app.alerts.notification import AlertNotificationMessage, ProviderAcceptance
from app.alerts.runtime import (
    AlertRuntime,
    AlertRuntimeStatusStore,
    _CanonicalUpdatedTrigger,
    _LiveBarTrigger,
    _parse_canonical_updated_trigger,
    _parse_live_bar_trigger,
    validate_alert_runtime_status,
)
from app.alerts.subing_strategy_runtime import (
    SubingStrategyRuntimeActionFact,
    SubingStrategyRuntimeProductStatus,
    SubingStrategyRuntimeResult,
)
from app.market_data.subing_lifecycle import ConfirmationSource
from app.market_data.subing_strategy.contracts import (
    SubingStrategyAction,
    SubingStrategyActionKind,
    SubingStrategyEpisode,
    SubingStrategyFillBasis,
    subing_strategy_action_id,
    subing_strategy_episode_id,
)
from app.db.base import Base
from app.market_data.aggregation import SessionWindow
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.market_read_service import MarketReadWindow
from app.market_data.product_taxonomy import ProductTaxonomyEntry
from app.market_data.session_clock import SHANGHAI
from app.models import Exchange, Instrument, TradingCalendar, TradingSession


DAY = date(2026, 8, 14)
PRIOR_DAY = date(2026, 8, 13)
DAY_SESSION_START = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)
DAY_SESSION_END = datetime(2026, 8, 14, 3, 30, tzinfo=UTC)
ORDINARY_END = datetime(2026, 8, 14, 1, 5, tzinfo=UTC)
BOUNDARY_END = datetime(2026, 8, 14, 1, 15, tzinfo=UTC)
CANONICAL_END = datetime(2026, 8, 14, 7, 0, tzinfo=UTC)
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


def _canonical_updated_payload(trading_day: date = DAY) -> str:
    return json.dumps(
        {
            "trading_day": trading_day.isoformat(),
            "reason": "canonical_updated",
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
        bar_contracts=(contract,) * 32,
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
    def __init__(
        self,
        result: MarketReadWindow | Exception,
        *,
        canonical_results: dict[BarFrequency, MarketReadWindow | Exception]
        | None = None,
    ) -> None:
        self.result = result
        self.canonical_results = canonical_results
        self.calls: list[tuple[object, dict[str, object]]] = []
        self.canonical_calls: list[tuple[object, dict[str, object]]] = []

    def bars_until(self, request, **kwargs) -> MarketReadWindow:
        self.calls.append((request, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def latest_canonical_window(self, request, **kwargs) -> MarketReadWindow:
        self.canonical_calls.append((request, kwargs))
        if self.canonical_results is None:
            raise AssertionError("unexpected Canonical window read")
        result = self.canonical_results[request.frequency]
        if isinstance(result, Exception):
            raise result
        return result


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
    strategy_evaluator: object
    htdy_evaluator: FakeHtdyEvaluator
    sender: FakeSender


def _runtime(
    session: Session,
    *,
    event_end: datetime = ORDINARY_END,
    event_day: date = DAY,
    strategy_evaluator: object | None = None,
    market_read_result: MarketReadWindow | Exception | None = None,
    canonical_read_results: dict[BarFrequency, MarketReadWindow | Exception]
    | None = None,
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
    market_read = FakeRead(
        market_read_result or _window(bar_end=event_end, trading_day=event_day),
        canonical_results=canonical_read_results,
    )
    active_strategy = strategy_evaluator or _Task9StrategyEvaluator([])
    htdy_evaluator = FakeHtdyEvaluator(htdy_observations, htdy_error)
    sender = FakeSender(sender_error, sender_acceptance)
    runtime = AlertRuntime(
        session_factory=lambda: nullcontext(session),
        market_read_factory=lambda _session: market_read,
        strategy_evaluator=active_strategy,
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
        active_strategy,
        htdy_evaluator,
        sender,
    )


def _event_rows(session: Session) -> list[AlertEvent]:
    return list(session.scalars(select(AlertEvent).order_by(AlertEvent.id)).all())


def _rule_codes(events: list[AlertEvent]) -> list[str]:
    return [event.rule.rule_code for event in events]


@pytest.mark.parametrize("frequency", ("1m", "5m", "15m", "30m", "60m"))
def test_runtime_accepts_each_completed_intraday_channel(frequency: str) -> None:
    parsed = _parse_live_bar_trigger(f"live:bar:jm:{frequency}", _payload())

    assert parsed == _LiveBarTrigger(
        symbol="jm",
        frequency=BarFrequency(frequency),
        bar=_bar(),
    )


@pytest.mark.parametrize("frequency", ("1d", "1w"))
def test_runtime_rejects_daily_and_weekly_live_bar_channels(
    frequency: str,
) -> None:
    assert _parse_live_bar_trigger(f"live:bar:jm:{frequency}", _payload()) is None


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
    assert _parse_live_bar_trigger(channel, payload) is None


@pytest.mark.parametrize("numeric", ("not-a-number", "NaN", "Infinity"))
def test_nonfinite_numeric_payload_is_rejected(numeric: str) -> None:
    payload = json.loads(_payload())
    payload["close"] = numeric

    assert _parse_live_bar_trigger("live:bar:jm:5m", json.dumps(payload)) is None


@pytest.mark.parametrize("channel", ("market:state", b"market:state"))
def test_canonical_updated_state_parser_returns_strongly_typed_trigger(
    channel: object,
) -> None:
    assert _parse_canonical_updated_trigger(
        channel,
        json.dumps(
            {
                "trading_day": DAY.isoformat(),
                "reason": "canonical_updated",
            }
        ),
    ) == _CanonicalUpdatedTrigger(trading_day=DAY)


@pytest.mark.parametrize(
    ("channel", "payload"),
    (
        ("market:state", "not-json"),
        ("market:state", json.dumps({"trading_day": DAY.isoformat()})),
        (
            "market:state",
            json.dumps(
                {
                    "trading_day": DAY.isoformat(),
                    "reason": "live_reconciled",
                }
            ),
        ),
        (
            "market:state",
            json.dumps(
                {
                    "trading_day": "20260814",
                    "reason": "canonical_updated",
                }
            ),
        ),
        (
            "market:state",
            json.dumps(
                {
                    "trading_day": "not-a-date",
                    "reason": "canonical_updated",
                }
            ),
        ),
        (
            "market:other",
            json.dumps(
                {
                    "trading_day": DAY.isoformat(),
                    "reason": "canonical_updated",
                }
            ),
        ),
    ),
)
def test_canonical_updated_state_parser_rejects_invalid_input(
    channel: object,
    payload: object,
) -> None:
    assert _parse_canonical_updated_trigger(channel, payload) is None


def test_active_strategy_runs_before_non_operational_htdy_gate(
    session: Session,
) -> None:
    order: list[str] = []
    strategy = _Task9StrategyEvaluator(order)
    _seed_rule(session, "subing_strategy_v1")
    harness = _runtime(
        session,
        operational_products=("ag",),
        strategy_evaluator=strategy,
    )

    harness.runtime.process_message("live:bar:jm:5m", _payload())

    assert order == ["strategy:5m"]
    assert _event_rows(session) == []
    assert harness.sender.messages == []


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
        bar_contracts=("JM2609",) * 32,
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
    _seed_rule(session, "htdy_original_15m")
    harness = _runtime(session, event_end=BOUNDARY_END)

    harness.runtime.process_message("live:bar:jm:15m", _payload(bar_end=BOUNDARY_END))
    harness.runtime.process_message("live:bar:jm:15m", _payload(bar_end=BOUNDARY_END))

    assert len(_event_rows(session)) == 1
    assert len(harness.sender.messages) == 1


def test_canonical_event_commits_before_missing_taxonomy_stops_notification(
    session: Session,
) -> None:
    _seed_rule(
        session,
        "htdy_original_15m",
        frequency_scope={"jm": ["1d"]},
    )
    processing_now = CANONICAL_END + timedelta(seconds=2)
    harness = _runtime(
        session,
        event_end=CANONICAL_END,
        canonical_read_results={
            BarFrequency.D1: _window(
                bar_end=CANONICAL_END,
                frequency="1d",
            )
        },
        taxonomy={},
        clock=processing_now,
    )

    harness.runtime.process_message("market:state", _canonical_updated_payload())

    events = _event_rows(session)
    assert len(events) == 1
    assert events[0].notification_attempted_at == processing_now.replace(tzinfo=None)
    assert harness.sender.messages == []


@pytest.mark.parametrize(
    ("frequency", "enabled_frequency"),
    (
        (BarFrequency.D1, "1d"),
        (BarFrequency.W1, "1w"),
    ),
)
def test_canonical_updated_reads_only_the_exact_enabled_daily_or_weekly_pair(
    session: Session,
    frequency: BarFrequency,
    enabled_frequency: str,
) -> None:
    _seed_rule(
        session,
        "htdy_original_15m",
        frequency_scope={"jm": [enabled_frequency]},
    )
    harness = _runtime(
        session,
        event_end=CANONICAL_END,
        canonical_read_results={
            frequency: _window(
                bar_end=CANONICAL_END,
                frequency=enabled_frequency,
            )
        },
    )

    harness.runtime.process_message("market:state", _canonical_updated_payload())

    assert harness.market_read.calls == []
    assert len(harness.market_read.canonical_calls) == 1
    request, kwargs = harness.market_read.canonical_calls[0]
    assert request.series_kind.value == "actual_dominant"
    assert request.symbol == "jm"
    assert request.frequency is frequency
    assert kwargs == {"trading_day": DAY, "limit": 32}
    assert [window.frequency for window in harness.htdy_evaluator.calls] == [
        enabled_frequency
    ]
    assert [event.frequency for event in _event_rows(session)] == [enabled_frequency]
    assert [message.frequency for message in harness.sender.messages] == [
        enabled_frequency
    ]


def test_canonical_updated_evaluates_daily_and_weekly_pairs_independently(
    session: Session,
) -> None:
    _seed_rule(
        session,
        "htdy_original_15m",
        frequency_scope={"jm": ["1d", "1w"]},
    )
    harness = _runtime(
        session,
        event_end=CANONICAL_END,
        canonical_read_results={
            BarFrequency.D1: _window(
                bar_end=CANONICAL_END,
                frequency="1d",
            ),
            BarFrequency.W1: _window(
                bar_end=CANONICAL_END,
                frequency="1w",
            ),
        },
    )
    session_calls = 0

    def one_session():
        nonlocal session_calls
        session_calls += 1
        return nullcontext(session)

    harness.runtime._session_factory = one_session

    harness.runtime.process_message("market:state", _canonical_updated_payload())

    assert session_calls == 1
    assert [call[0].frequency for call in harness.market_read.canonical_calls] == [
        BarFrequency.D1,
        BarFrequency.W1,
    ]
    assert [event.frequency for event in _event_rows(session)] == ["1d", "1w"]
    assert [message.frequency for message in harness.sender.messages] == [
        "1d",
        "1w",
    ]


def test_canonical_updated_with_neither_pair_enabled_reads_nothing(
    session: Session,
) -> None:
    _seed_rule(
        session,
        "htdy_original_15m",
        frequency_scope={},
    )
    harness = _runtime(
        session,
        canonical_read_results={},
    )

    harness.runtime.process_message("market:state", _canonical_updated_payload())

    assert harness.market_read.calls == []
    assert harness.market_read.canonical_calls == []
    assert harness.htdy_evaluator.calls == []
    assert _event_rows(session) == []
    assert harness.sender.messages == []


def test_canonical_updated_mixed_scope_authority_reads_nothing(
    session: Session,
) -> None:
    rule = _seed_rule(
        session,
        "htdy_original_15m",
        frequency_scope={"jm": ["1d"]},
    )
    rule.scope_products = ["jm"]
    session.commit()
    harness = _runtime(
        session,
        canonical_read_results={},
    )

    harness.runtime.process_message("market:state", _canonical_updated_payload())

    assert harness.market_read.calls == []
    assert harness.market_read.canonical_calls == []
    assert harness.htdy_evaluator.calls == []
    assert _event_rows(session) == []
    assert harness.sender.messages == []


def test_canonical_updated_rejects_stale_weekly_window_without_backfill(
    session: Session,
) -> None:
    _seed_rule(
        session,
        "htdy_original_15m",
        frequency_scope={"jm": ["1w"]},
    )
    harness = _runtime(
        session,
        event_end=CANONICAL_END,
        canonical_read_results={
            BarFrequency.W1: _window(
                bar_end=CANONICAL_END - timedelta(days=7),
                trading_day=DAY - timedelta(days=7),
                frequency="1w",
            )
        },
    )

    harness.runtime.process_message("market:state", _canonical_updated_payload())

    assert [call[0].frequency for call in harness.market_read.canonical_calls] == [
        BarFrequency.W1
    ]
    assert harness.htdy_evaluator.calls == []
    assert _event_rows(session) == []
    assert harness.sender.messages == []


def test_duplicate_canonical_updated_state_is_event_and_notification_idempotent(
    session: Session,
) -> None:
    _seed_rule(
        session,
        "htdy_original_15m",
        frequency_scope={"jm": ["1d"]},
    )
    harness = _runtime(
        session,
        event_end=CANONICAL_END,
        canonical_read_results={
            BarFrequency.D1: _window(
                bar_end=CANONICAL_END,
                frequency="1d",
            )
        },
    )

    harness.runtime.process_message("market:state", _canonical_updated_payload())
    harness.runtime.process_message("market:state", _canonical_updated_payload())

    assert len(harness.market_read.canonical_calls) == 2
    assert len(harness.htdy_evaluator.calls) == 2
    assert len(_event_rows(session)) == 1
    assert len(harness.sender.messages) == 1


def test_duplicate_canonical_updated_never_retries_failed_notification(
    session: Session,
) -> None:
    _seed_rule(
        session,
        "htdy_original_15m",
        frequency_scope={"jm": ["1d"]},
    )
    harness = _runtime(
        session,
        event_end=CANONICAL_END,
        canonical_read_results={
            BarFrequency.D1: _window(
                bar_end=CANONICAL_END,
                frequency="1d",
            )
        },
        sender_error=RuntimeError("private provider detail"),
    )

    harness.runtime.process_message("market:state", _canonical_updated_payload())
    harness.runtime.process_message("market:state", _canonical_updated_payload())

    assert len(_event_rows(session)) == 1
    assert len(harness.sender.messages) == 1


def test_invalid_canonical_state_message_has_zero_side_effects(
    session: Session,
) -> None:
    _seed_rule(
        session,
        "htdy_original_15m",
        frequency_scope={"jm": ["1d", "1w"]},
    )
    harness = _runtime(session, canonical_read_results={})
    harness.runtime.clock = lambda: pytest.fail("invalid state must stop before clock")

    harness.runtime.process_message(
        "market:state",
        json.dumps(
            {
                "trading_day": DAY.isoformat(),
                "reason": "live_reconciled",
            }
        ),
    )

    assert harness.market_read.calls == []
    assert harness.market_read.canonical_calls == []
    assert harness.htdy_evaluator.calls == []
    assert _event_rows(session) == []
    assert harness.sender.messages == []


def test_unavailable_daily_pair_does_not_authorize_weekly_fallback(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _seed_rule(
        session,
        "htdy_original_15m",
        frequency_scope={"jm": ["1d"]},
    )
    harness = _runtime(
        session,
        event_end=CANONICAL_END,
        canonical_read_results={
            BarFrequency.D1: RuntimeError("private Canonical detail"),
        },
    )

    harness.runtime.process_message("market:state", _canonical_updated_payload())

    assert [call[0].frequency for call in harness.market_read.canonical_calls] == [
        BarFrequency.D1
    ]
    assert harness.htdy_evaluator.calls == []
    assert _event_rows(session) == []
    assert harness.sender.messages == []
    assert (
        caplog.messages.count(
            "ALERT_RULE_PROCESSING_FAILED symbol=jm frequency=1d stage=market_read"
        )
        == 1
    )
    assert "private Canonical detail" not in caplog.text


@pytest.mark.parametrize(
    ("failed_frequency", "successful_frequency", "successful_value"),
    (
        (BarFrequency.D1, BarFrequency.W1, "1w"),
        (BarFrequency.W1, BarFrequency.D1, "1d"),
    ),
)
def test_one_unavailable_canonical_pair_does_not_block_the_other_pair(
    session: Session,
    failed_frequency: BarFrequency,
    successful_frequency: BarFrequency,
    successful_value: str,
) -> None:
    _seed_rule(
        session,
        "htdy_original_15m",
        frequency_scope={"jm": ["1d", "1w"]},
    )
    harness = _runtime(
        session,
        event_end=CANONICAL_END,
        canonical_read_results={
            failed_frequency: RuntimeError("private Canonical detail"),
            successful_frequency: _window(
                bar_end=CANONICAL_END,
                frequency=successful_value,
            ),
        },
    )

    harness.runtime.process_message("market:state", _canonical_updated_payload())

    assert [call[0].frequency for call in harness.market_read.canonical_calls] == [
        BarFrequency.D1,
        BarFrequency.W1,
    ]
    assert [window.frequency for window in harness.htdy_evaluator.calls] == [
        successful_value
    ]
    assert [event.frequency for event in _event_rows(session)] == [successful_value]
    assert [message.frequency for message in harness.sender.messages] == [
        successful_value
    ]


def test_notification_failure_keeps_event_and_duplicate_never_retries(
    session: Session,
) -> None:
    _seed_rule(session, "htdy_original_15m")
    harness = _runtime(
        session,
        event_end=BOUNDARY_END,
        sender_error=RuntimeError("send failed"),
    )

    harness.runtime.process_message("live:bar:jm:15m", _payload(bar_end=BOUNDARY_END))
    harness.runtime.process_message("live:bar:jm:15m", _payload(bar_end=BOUNDARY_END))

    assert len(_event_rows(session)) == 1
    assert len(harness.sender.messages) == 1


def test_notification_failure_does_not_block_next_completed_bar(
    session: Session,
) -> None:
    _seed_rule(session, "htdy_original_15m")
    harness = _runtime(
        session,
        event_end=BOUNDARY_END,
        sender_error=RuntimeError("send failed"),
    )

    harness.runtime.process_message("live:bar:jm:15m", _payload(bar_end=BOUNDARY_END))
    next_end = BOUNDARY_END + timedelta(minutes=15)
    harness.market_read.result = _window(bar_end=next_end)
    harness.runtime.clock = lambda: next_end + timedelta(seconds=2)
    harness.runtime.process_message(
        "live:bar:jm:15m",
        _payload(bar_end=next_end),
    )

    assert len(_event_rows(session)) == 2
    assert len(harness.sender.messages) == 2


def test_multiple_messages_from_one_bar_are_sent_sequentially(session: Session) -> None:
    _seed_rule(
        session,
        "htdy_original_15m",
        frequency_scope={"jm": ["1m"]},
    )
    _seed_rule(session, "subing_strategy_v1")
    strategy = _Task9ActionEvaluator([], _task9_open_action())
    harness = _runtime(
        session,
        event_end=BOUNDARY_END,
        market_read_result=_window(bar_end=BOUNDARY_END, frequency="1m"),
        strategy_evaluator=strategy,
    )

    harness.runtime.process_message(
        "live:bar:jm:1m",
        _payload(bar_end=BOUNDARY_END),
    )

    assert len(_event_rows(session)) == 2
    assert [message.rule_code for message in harness.sender.messages] == [
        "htdy_original_15m",
        "subing_strategy_v1",
    ]


@pytest.mark.parametrize("revocation", ("disable", "scope_remove"))
def test_runtime_refreshes_rule_truth_after_external_revocation(
    revocation: str,
    tmp_path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'alerts.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as runtime_session:
        _seed_rule(runtime_session, "subing_strategy_v1")
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

        strategy = _Task9ActionEvaluator([], _task9_open_action())
        harness = _runtime(runtime_session, strategy_evaluator=strategy)
        harness.runtime.process_message(
            "live:bar:jm:1m", _payload(bar_end=BOUNDARY_END)
        )

        assert strategy.order == ["strategy:1m"]
        assert _event_rows(runtime_session) == []


class FakeMessageSource:
    def __init__(self) -> None:
        self.subscribe_calls: list[tuple[str, ...]] = []

    def subscribe(self, *patterns: str) -> None:
        self.subscribe_calls.append(patterns)

    def drain_startup_messages(self) -> tuple[tuple[object, object], ...]:
        messages: list[tuple[object, object]] = []
        while True:
            message = self.get_message(timeout_seconds=0.0)
            if message is None:
                return tuple(messages)
            messages.append(message)

    def get_message(self, *, timeout_seconds: float):
        assert timeout_seconds in {0.0, 1.0}
        return None

    def close(self) -> None:
        return None


class FakeHeartbeatStore:
    def __init__(self) -> None:
        self.writes: list[tuple[dict[str, object], int]] = []

    def write(self, payload: dict[str, object], *, ttl_seconds: int) -> None:
        self.writes.append((payload, ttl_seconds))


def test_redis_message_source_uses_one_pubsub_connection_for_both_patterns() -> None:
    class FakePubSub:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def psubscribe(self, *patterns: str) -> None:
            self.calls.append(patterns)

    class FakeRedis:
        def __init__(self) -> None:
            self.active = FakePubSub()
            self.pubsub_calls: list[dict[str, object]] = []

        def pubsub(self, **kwargs):
            self.pubsub_calls.append(kwargs)
            return self.active

    redis = FakeRedis()
    source = RedisAlertMessageSource(redis)

    source.subscribe("live:bar:*:*", "market:state")

    assert redis.pubsub_calls == [{"ignore_subscribe_messages": False}]
    assert redis.active.calls == [("live:bar:*:*", "market:state")]


def test_redis_message_source_cuts_startup_queue_at_pubsub_pong() -> None:
    startup = {
        "type": "pmessage",
        "channel": b"market:state",
        "data": b"startup",
    }
    post_ready = {
        "type": "pmessage",
        "channel": b"market:state",
        "data": b"post-ready",
    }

    class FakePubSub:
        def __init__(self) -> None:
            self.messages: list[dict[str, object]] = [
                {"type": "psubscribe", "data": 1},
                startup,
            ]
            self.pings: list[object] = []

        def psubscribe(self, *_patterns: str) -> None:
            return None

        def ping(self, payload: object) -> None:
            self.pings.append(payload)
            self.messages.extend(
                (
                    {"type": "pong", "data": payload},
                    post_ready,
                )
            )

        def get_message(self, *, timeout: float):
            assert timeout == 1.0
            return self.messages.pop(0) if self.messages else None

        def close(self) -> None:
            return None

    class FakeRedis:
        def __init__(self) -> None:
            self.active = FakePubSub()

        def pubsub(self, **_kwargs):
            return self.active

    redis = FakeRedis()
    source = RedisAlertMessageSource(redis)
    source.subscribe("live:bar:*:*", "market:state")

    assert source.drain_startup_messages() == (
        (b"market:state", b"startup"),
    )
    assert len(redis.active.pings) == 1
    assert source.get_message(timeout_seconds=1.0) == (
        b"market:state",
        b"post-ready",
    )


class RuntimeStatusPipeline:
    def __init__(self, redis) -> None:
        self.redis = redis
        self.watched_key: str | None = None
        self.snapshot: str | None = None
        self.pending: tuple[str, str] | None = None

    def watch(self, key: str) -> None:
        self.watched_key = key
        self.snapshot = self.redis.values.get(key)

    def get(self, key: str) -> str | None:
        assert key == self.watched_key
        return self.redis.values.get(key)

    def multi(self) -> None:
        return None

    def set(self, key: str, value: str):
        self.pending = (key, value)
        return self

    def execute(self) -> list[bool]:
        assert self.watched_key is not None
        assert self.redis.values.get(self.watched_key) == self.snapshot
        assert self.pending is not None
        key, value = self.pending
        self.redis.values[key] = value
        return [True]

    def reset(self) -> None:
        return None


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

    def pipeline(self) -> RuntimeStatusPipeline:
        return RuntimeStatusPipeline(self)


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


class AtomicRuntimeStatusStore:
    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self.status = validate_alert_runtime_status(
            payload or alert_runtime_module.empty_alert_runtime_status()
        )

    def read(self) -> dict[str, object]:
        return dict(self.status)

    def write(self, payload: dict[str, object]) -> None:
        self.status = dict(payload)

    def update(self, changes: dict[str, object]) -> dict[str, object]:
        self.status = validate_alert_runtime_status({**self.status, **changes})
        return dict(self.status)


@pytest.mark.parametrize("schema_version", (1, 2))
def test_runtime_status_v1_v2_is_normalized_to_v3(
    schema_version: int,
) -> None:
    payload = _runtime_status_payload()
    if schema_version == 2:
        payload = {
            **payload,
            "schema_version": 2,
            "notification_acknowledged_at": None,
        }
    normalized = validate_alert_runtime_status(payload)

    assert normalized["schema_version"] == 3
    assert normalized["notification_acknowledged_at"] is None
    assert normalized["strategy_state"] == "warming"
    assert normalized["strategy_product_count"] == 0
    assert normalized["strategy_unavailable_symbols"] == []


def test_runtime_status_rejects_strategy_counts_above_active60_bound() -> None:
    payload = {
        **alert_runtime_module.empty_alert_runtime_status(),
        "strategy_product_count": 61,
        "strategy_ready_product_count": 61,
    }

    with pytest.raises(ValueError, match="^ALERT_RUNTIME_STATUS_INVALID$"):
        validate_alert_runtime_status(payload)


def test_runtime_status_rejects_acknowledgement_without_prior_failure() -> None:
    payload = {
        **_runtime_status_payload(),
        "schema_version": 2,
        "notification_acknowledged_at": "2026-08-14T02:44:00+00:00",
    }

    with pytest.raises(ValueError, match="^ALERT_RUNTIME_STATUS_INVALID$"):
        validate_alert_runtime_status(payload)


def test_acknowledge_notification_failure_preserves_failure_facts() -> None:
    failure_at = "2026-08-14T02:44:00+00:00"
    payload = _runtime_status_payload(
        last_notification_failure_at=failure_at,
        notification_error_type="notification_transport_failed",
        consecutive_notification_failures=1,
    )

    acknowledged = alert_runtime_module.acknowledge_notification_failure(
        payload,
        expected_failure_at=failure_at,
        acknowledged_at=datetime(2026, 8, 14, 2, 45, tzinfo=UTC),
    )

    assert acknowledged["schema_version"] == 3
    assert acknowledged["last_notification_failure_at"] == failure_at
    assert acknowledged["notification_error_type"] == "notification_transport_failed"
    assert acknowledged["consecutive_notification_failures"] == 1
    assert acknowledged["notification_acknowledged_at"] == ("2026-08-14T02:45:00+00:00")


def test_acknowledge_new_failure_after_prior_acknowledgement() -> None:
    latest_failure_at = "2026-08-14T02:46:00+00:00"
    payload = {
        **_runtime_status_payload(
            last_notification_failure_at=latest_failure_at,
            notification_error_type="notification_transport_failed",
            consecutive_notification_failures=1,
        ),
        "schema_version": 2,
        "notification_acknowledged_at": "2026-08-14T02:45:00+00:00",
    }

    acknowledged = alert_runtime_module.acknowledge_notification_failure(
        payload,
        expected_failure_at=latest_failure_at,
        acknowledged_at=datetime(2026, 8, 14, 2, 47, tzinfo=UTC),
    )

    assert acknowledged["last_notification_failure_at"] == latest_failure_at
    assert acknowledged["notification_acknowledged_at"] == ("2026-08-14T02:47:00+00:00")


@pytest.mark.parametrize(
    ("payload", "expected_failure_at", "acknowledged_at", "expected_code"),
    (
        (
            _runtime_status_payload(),
            "2026-08-14T02:44:00+00:00",
            datetime(2026, 8, 14, 2, 45, tzinfo=UTC),
            "ALERT_NOTIFICATION_FAILURE_NOT_FOUND",
        ),
        (
            _runtime_status_payload(
                last_notification_failure_at="2026-08-14T02:44:00+00:00",
                notification_error_type="notification_transport_failed",
            ),
            "not-a-timestamp",
            datetime(2026, 8, 14, 2, 45, tzinfo=UTC),
            "ALERT_NOTIFICATION_FAILURE_AT_INVALID",
        ),
        (
            _runtime_status_payload(
                last_notification_failure_at="2026-08-14T02:44:00+00:00",
                notification_error_type="notification_transport_failed",
            ),
            "2026-08-14T02:43:00+00:00",
            datetime(2026, 8, 14, 2, 45, tzinfo=UTC),
            "ALERT_NOTIFICATION_FAILURE_MISMATCH",
        ),
        (
            {
                **_runtime_status_payload(
                    last_notification_failure_at="2026-08-14T02:44:00+00:00",
                    notification_error_type="notification_transport_failed",
                ),
                "schema_version": 2,
                "notification_acknowledged_at": "2026-08-14T02:45:00+00:00",
            },
            "2026-08-14T02:44:00+00:00",
            datetime(2026, 8, 14, 2, 46, tzinfo=UTC),
            "ALERT_NOTIFICATION_FAILURE_ALREADY_ACKNOWLEDGED",
        ),
        (
            _runtime_status_payload(
                last_notification_failure_at="2026-08-14T02:44:00+00:00",
                notification_error_type="notification_transport_failed",
            ),
            "2026-08-14T02:44:00+00:00",
            datetime(2026, 8, 14, 2, 43, tzinfo=UTC),
            "ALERT_NOTIFICATION_ACKNOWLEDGEMENT_TIME_INVALID",
        ),
    ),
)
def test_acknowledge_notification_failure_fails_closed(
    payload: dict[str, object],
    expected_failure_at: str,
    acknowledged_at: datetime,
    expected_code: str,
) -> None:
    with pytest.raises(RuntimeError) as raised:
        alert_runtime_module.acknowledge_notification_failure(
            payload,
            expected_failure_at=expected_failure_at,
            acknowledged_at=acknowledged_at,
        )

    assert getattr(raised.value, "code", None) == expected_code


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


def test_redis_runtime_status_store_upgrades_v1_to_v3_without_ttl() -> None:
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

    expected = {
        **payload,
        "schema_version": 3,
        "notification_acknowledged_at": None,
        "strategy_state": "warming",
        "strategy_started_at": None,
        "strategy_ready_at": None,
        "strategy_product_count": 0,
        "strategy_ready_product_count": 0,
        "strategy_unavailable_product_count": 0,
        "strategy_unavailable_symbols": [],
        "last_strategy_action_at": None,
        "last_strategy_restore_at": None,
    }
    assert redis.calls == [
        (
            (
                "alert:runtime-status",
                json.dumps(expected, ensure_ascii=False, separators=(",", ":")),
            ),
            {},
        )
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


def test_redis_runtime_status_acknowledgement_is_compare_and_set() -> None:
    from app.alerts.composition import RedisAlertRuntimeStatusStore

    failure_at = "2026-08-14T02:44:00+00:00"
    redis = RuntimeStatusRedis(
        _runtime_status_payload(
            last_notification_failure_at=failure_at,
            notification_error_type="notification_transport_failed",
            consecutive_notification_failures=1,
        )
    )
    store = RedisAlertRuntimeStatusStore(redis)

    acknowledged = store.acknowledge_notification_failure(
        expected_failure_at=failure_at,
        acknowledged_at=datetime(2026, 8, 14, 2, 45, tzinfo=UTC),
    )

    persisted = json.loads(redis.values["alert:runtime-status"])
    assert acknowledged == persisted
    assert persisted["schema_version"] == 3
    assert persisted["last_notification_failure_at"] == failure_at
    assert persisted["notification_error_type"] == "notification_transport_failed"
    assert persisted["notification_acknowledged_at"] == ("2026-08-14T02:45:00+00:00")


def test_redis_runtime_status_acknowledgement_rejects_concurrent_change() -> None:
    from redis.exceptions import WatchError

    from app.alerts.composition import RedisAlertRuntimeStatusStore

    failure_at = "2026-08-14T02:44:00+00:00"
    raw = json.dumps(
        _runtime_status_payload(
            last_notification_failure_at=failure_at,
            notification_error_type="notification_transport_failed",
        )
    )

    class ConflictingPipeline:
        def watch(self, _key: str) -> None:
            return None

        def get(self, _key: str) -> str:
            return raw

        def multi(self) -> None:
            return None

        def set(self, _key: str, _value: str):
            return self

        def execute(self) -> list[bool]:
            raise WatchError("concurrent status update")

        def reset(self) -> None:
            return None

    class ConflictingRedis:
        def pipeline(self) -> ConflictingPipeline:
            return ConflictingPipeline()

    with pytest.raises(RuntimeError) as raised:
        RedisAlertRuntimeStatusStore(
            ConflictingRedis()
        ).acknowledge_notification_failure(
            expected_failure_at=failure_at,
            acknowledged_at=datetime(2026, 8, 14, 2, 45, tzinfo=UTC),
        )

    assert getattr(raised.value, "code", None) == "ALERT_RUNTIME_STATUS_CHANGED"


def test_redis_runtime_status_atomic_update_merges_current_acknowledgement() -> None:
    from app.alerts.composition import RedisAlertRuntimeStatusStore

    failure_at = "2026-08-14T02:44:00+00:00"
    current = validate_alert_runtime_status(
        _runtime_status_payload(
            last_notification_failure_at=failure_at,
            notification_error_type="notification_transport_failed",
            consecutive_notification_failures=1,
        )
    )
    current["notification_acknowledged_at"] = "2026-08-14T02:45:00+00:00"

    redis = RuntimeStatusRedis(current)
    store = RedisAlertRuntimeStatusStore(redis)

    updated = store.update({"last_processing_success_at": "2026-08-14T02:46:00+00:00"})

    assert updated["notification_acknowledged_at"] == ("2026-08-14T02:45:00+00:00")
    assert json.loads(redis.values["alert:runtime-status"]) == updated


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
            _runtime_status_payload(**{error_field: "must_not_leak"})
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

    _seed_rule(session, "htdy_original_15m")
    harness = _runtime(
        session,
        runtime_status_store=FailingStatusStore(),
    )

    with pytest.raises(
        RuntimeError,
        match="^ALERT_RUNTIME_STATUS_WRITE_FAILED$",
    ):
        harness.runtime.process_message("live:bar:jm:15m", _payload())

    assert _event_rows(session) == []


def test_runtime_status_update_preserves_external_acknowledgement(
    session: Session,
) -> None:
    failure_at = "2026-08-14T02:44:00+00:00"

    store = AtomicRuntimeStatusStore()
    harness = _runtime(session, runtime_status_store=store)
    harness.runtime._current_runtime_status()
    store.status = validate_alert_runtime_status(
        {
            **store.status,
            "last_notification_failure_at": failure_at,
            "notification_acknowledged_at": "2026-08-14T02:45:00+00:00",
            "notification_error_type": "notification_transport_failed",
            "consecutive_notification_failures": 1,
        }
    )

    harness.runtime._update_runtime_status(
        last_processing_success_at="2026-08-14T02:46:00+00:00"
    )

    assert store.status["notification_acknowledged_at"] == ("2026-08-14T02:45:00+00:00")
    assert store.status["last_notification_failure_at"] == failure_at


def test_new_notification_failure_invalidates_same_timestamp_acknowledgement(
    session: Session,
) -> None:
    failure_at = datetime(2026, 8, 14, 2, 44, tzinfo=UTC)

    store = AtomicRuntimeStatusStore(
        {
            **_runtime_status_payload(
                last_notification_failure_at=failure_at.isoformat(),
                notification_error_type="notification_transport_failed",
                consecutive_notification_failures=1,
            ),
            "schema_version": 2,
            "notification_acknowledged_at": failure_at.isoformat(),
        }
    )
    harness = _runtime(session, runtime_status_store=store)

    harness.runtime._record_notification_failure(
        at=failure_at,
        error_type="notification_transport_failed",
    )

    assert store.status["last_notification_failure_at"] == failure_at.isoformat()
    assert store.status["notification_acknowledged_at"] is None
    assert store.status["notification_error_type"] == ("notification_transport_failed")
    assert store.status["consecutive_notification_failures"] == 2


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

    _seed_rule(session, "htdy_original_15m")
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
        harness.runtime.process_message("live:bar:jm:15m", _payload())

    assert len(_event_rows(session)) == 1
    assert len(harness.sender.messages) == expected_sender_calls


def test_runtime_status_records_processing_event_and_provider_acceptance(
    session: Session,
) -> None:
    from app.alerts.composition import RedisAlertRuntimeStatusStore

    _seed_rule(session, "htdy_original_15m")
    redis = RuntimeStatusRedis()
    harness = _runtime(
        session,
        runtime_status_store=RedisAlertRuntimeStatusStore(redis),
    )

    harness.runtime.process_message("live:bar:jm:15m", _payload())

    status = json.loads(redis.values["alert:runtime-status"])
    observed_at = (ORDINARY_END + timedelta(seconds=2)).isoformat()
    assert status == {
        "schema_version": 3,
        "last_processed_bar_at": ORDINARY_END.isoformat(),
        "last_processing_success_at": observed_at,
        "last_processing_failure_at": None,
        "processing_error_type": None,
        "last_event_at": observed_at,
        "last_transport_attempt_at": observed_at,
        "last_provider_accepted_at": observed_at,
        "last_notification_failure_at": None,
        "notification_acknowledged_at": None,
        "notification_error_type": None,
        "consecutive_notification_failures": 0,
        "strategy_state": "ready",
        "strategy_started_at": None,
        "strategy_ready_at": None,
        "strategy_product_count": 1,
        "strategy_ready_product_count": 1,
        "strategy_unavailable_product_count": 0,
        "strategy_unavailable_symbols": [],
        "last_strategy_action_at": None,
        "last_strategy_restore_at": None,
    }
    assert "private-provider-reference" not in redis.values["alert:runtime-status"]


def test_missing_taxonomy_records_preparation_failure_without_transport_attempt(
    session: Session,
) -> None:
    from app.alerts.composition import RedisAlertRuntimeStatusStore

    _seed_rule(session, "htdy_original_15m")
    redis = RuntimeStatusRedis()
    harness = _runtime(
        session,
        taxonomy={},
        runtime_status_store=RedisAlertRuntimeStatusStore(redis),
    )

    harness.runtime.process_message("live:bar:jm:15m", _payload())

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

    _seed_rule(session, "htdy_original_15m")
    redis = RuntimeStatusRedis()
    harness = _runtime(
        session,
        sender_error=RuntimeError("private provider failure"),
        runtime_status_store=RedisAlertRuntimeStatusStore(redis),
    )

    harness.runtime.process_message("live:bar:jm:15m", _payload())

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

    _seed_rule(session, "htdy_original_15m")
    redis = RuntimeStatusRedis()
    harness = _runtime(
        session,
        sender_acceptance=None,
        runtime_status_store=RedisAlertRuntimeStatusStore(redis),
    )

    harness.runtime.process_message("live:bar:jm:15m", _payload())

    status = json.loads(redis.values["alert:runtime-status"])
    observed_at = (ORDINARY_END + timedelta(seconds=2)).isoformat()
    assert status["last_transport_attempt_at"] == observed_at
    assert status["last_provider_accepted_at"] is None
    assert status["last_notification_failure_at"] == observed_at
    assert status["notification_error_type"] == "notification_acceptance_invalid"


def test_next_provider_acceptance_preserves_last_notification_failure_fact(
    session: Session,
) -> None:
    from app.alerts.composition import RedisAlertRuntimeStatusStore

    _seed_rule(session, "htdy_original_15m")
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

    harness.runtime.process_message("live:bar:jm:15m", _payload())

    status = json.loads(redis.values["alert:runtime-status"])
    assert (
        status["last_provider_accepted_at"]
        == (ORDINARY_END + timedelta(seconds=2)).isoformat()
    )
    assert status["last_notification_failure_at"] == "2026-08-13T01:01:00+00:00"
    assert status["notification_error_type"] == "notification_transport_failed"
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

    _seed_rule(session, "htdy_original_15m")
    redis = RuntimeStatusRedis()
    harness = _runtime(
        session,
        runtime_status_store=RedisAlertRuntimeStatusStore(redis),
    )
    harness.runtime._session_factory = FailingSessionContext

    harness.runtime.process_message("live:bar:jm:15m", _payload())

    assert len(_event_rows(session)) == 1
    assert harness.sender.messages == []
    status = json.loads(redis.values["alert:runtime-status"])
    assert (
        status["last_processing_failure_at"]
        == (ORDINARY_END + timedelta(seconds=2)).isoformat()
    )
    assert status["processing_error_type"] == "processing_failed"
    assert status["last_transport_attempt_at"] is None
    assert "private database exit detail" not in redis.values["alert:runtime-status"]


def test_run_forever_uses_single_transport_and_fixed_heartbeat_contract(
    session: Session,
) -> None:
    _seed_rule(session, "htdy_original_15m")
    _seed_rule(session, "subing_strategy_v1", scope=())
    moments = iter(
        datetime(2026, 8, 14, 0, 0, second, tzinfo=UTC)
        for second in (0, 0, 0, 0, 0, 5, 10, 15, 20, 20)
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

    assert source.subscribe_calls == [("live:bar:*:*", "market:state")]
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
    _seed_rule(session, "subing_strategy_v1", scope=("ag",))
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

    harness.runtime._write_heartbeat(datetime(2026, 8, 14, 0, 0, tzinfo=UTC))

    assert heartbeats.writes[0][0]["enabled_rule_count"] == 1
    assert heartbeats.writes[0][0]["scope_product_count"] == 0


def test_session_fixture_uses_real_shanghai_anchor() -> None:
    assert DAY_SESSION_START.astimezone(SHANGHAI).time() == time(9)
    assert CROSS_MIDNIGHT_START.astimezone(SHANGHAI).time() == time(21)
    assert CROSS_MIDNIGHT_END.astimezone(SHANGHAI).time() == time(2, 30)


class _Task9StrategyEvaluator:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.products = ("jm",)

    def restore_all(self, *, started_at: datetime):
        self.order.append("restore")
        return (
            SubingStrategyRuntimeResult(
                action_facts=(),
                product_status=SubingStrategyRuntimeProductStatus(
                    symbol="jm",
                    state="warming",
                    cutoff_1m=None,
                    cutoff_5m=None,
                    cutoff_15m=None,
                    reason_codes=(),
                ),
            ),
        )

    def final_catch_up(self, *, ready_at: datetime):
        self.order.append("catch_up")
        return (
            SubingStrategyRuntimeResult(
                action_facts=(),
                product_status=SubingStrategyRuntimeProductStatus(
                    symbol="jm",
                    state="ready",
                    cutoff_1m=ORDINARY_END,
                    cutoff_5m=ORDINARY_END,
                    cutoff_15m=BOUNDARY_END,
                    reason_codes=(),
                ),
            ),
        )

    def current_state(self, symbol: str):
        return type(
            "State",
            (),
            {
                "symbol": symbol,
                "contract": "JM2609",
                "segment_start_trading_day": DAY,
                "current_episode": None,
                "closed_episodes": (),
            },
        )()

    def process_completed_bar(self, bar, frequency, *, source_identity):
        self.order.append(f"strategy:{frequency.value}")
        return SubingStrategyRuntimeResult(
            action_facts=(),
            product_status=SubingStrategyRuntimeProductStatus(
                symbol=source_identity.symbol,
                state="ready",
                cutoff_1m=bar.bar_end if frequency is BarFrequency.M1 else None,
                cutoff_5m=bar.bar_end if frequency is BarFrequency.M5 else None,
                cutoff_15m=bar.bar_end if frequency is BarFrequency.M15 else None,
                reason_codes=(),
            ),
        )

    def process_canonical_updated(self, trading_day: date):
        self.order.append(f"terminal:{trading_day.isoformat()}")
        return (
            SubingStrategyRuntimeResult(
                action_facts=(),
                product_status=SubingStrategyRuntimeProductStatus(
                    symbol="jm",
                    state="ready",
                    cutoff_1m=ORDINARY_END,
                    cutoff_5m=ORDINARY_END,
                    cutoff_15m=BOUNDARY_END,
                    reason_codes=(),
                ),
            ),
        )


def _task9_open_action(
    *,
    symbol: str = "jm",
    contract: str = "JM2609",
) -> SubingStrategyAction:
    effective_bar_end = BOUNDARY_END
    identity = {
        "strategy_id": "subing_strategy_v1",
        "formula_version": "subing_strategy_15m_v1",
        "symbol": symbol,
        "contract": contract,
        "segment_start_trading_day": DAY.isoformat(),
        "opportunity_id": "subing-opportunity:task9",
        "kind": "open_long",
        "decision_at": ORDINARY_END.isoformat(),
        "effective_bar_end": effective_bar_end.isoformat(),
        "fill_basis": "next_bar_open",
    }
    return SubingStrategyAction(
        action_id=subing_strategy_action_id(identity),
        episode_id=subing_strategy_episode_id(identity),
        strategy_id="subing_strategy_v1",
        formula_version="subing_strategy_15m_v1",
        kind=SubingStrategyActionKind.OPEN_LONG,
        symbol=symbol,
        contract=contract,
        trading_day=DAY,
        segment_start_trading_day=DAY,
        opportunity_id="subing-opportunity:task9",
        decision_at=ORDINARY_END,
        effective_open_at=ORDINARY_END,
        effective_bar_end=effective_bar_end,
        reference_price=Decimal("100"),
        fill_basis=SubingStrategyFillBasis.NEXT_BAR_OPEN,
        confirmation_source=ConfirmationSource.FORMAL_V1,
        reason_codes=(),
        direction_context_source_day=DAY,
        direction_context_target_day=DAY,
        bound_reference_pivot=None,
    )


def _task9_product_status(symbol: str = "jm") -> SubingStrategyRuntimeProductStatus:
    return SubingStrategyRuntimeProductStatus(
        symbol=symbol,
        state="ready",
        cutoff_1m=ORDINARY_END,
        cutoff_5m=ORDINARY_END,
        cutoff_15m=BOUNDARY_END,
        reason_codes=(),
    )


@pytest.mark.parametrize(
    "action_facts",
    (
        [],
        (object(),),
    ),
    ids=("list", "wrong-fact-type"),
)
def test_strategy_runtime_result_rejects_non_exact_action_fact_tuple(
    action_facts: object,
) -> None:
    with pytest.raises(
        ValueError,
        match="^SUBING_STRATEGY_RUNTIME_RESULT_INVALID$",
    ):
        SubingStrategyRuntimeResult(
            action_facts=action_facts,  # type: ignore[arg-type]
            product_status=_task9_product_status(),
        )


def test_strategy_runtime_result_rejects_action_from_another_product() -> None:
    wrong_product_action = _task9_open_action(symbol="ag", contract="AG2609")

    with pytest.raises(
        ValueError,
        match="^SUBING_STRATEGY_RUNTIME_RESULT_INVALID$",
    ):
        SubingStrategyRuntimeResult(
            action_facts=(SubingStrategyRuntimeActionFact(wrong_product_action, None),),
            product_status=_task9_product_status("jm"),
        )


def _unsafe_strategy_runtime_result(
    *,
    action_facts: object,
    product_status: object,
) -> SubingStrategyRuntimeResult:
    """Bypass the constructor to exercise Runtime's evaluator trust boundary."""

    result = object.__new__(SubingStrategyRuntimeResult)
    object.__setattr__(result, "action_facts", action_facts)
    object.__setattr__(result, "product_status", product_status)
    return result


def _task9_terminal_close() -> tuple[SubingStrategyAction, SubingStrategyEpisode]:
    entry = _task9_open_action()
    identity = {
        "strategy_id": "subing_strategy_v1",
        "formula_version": "subing_strategy_15m_v1",
        "symbol": "jm",
        "contract": "JM2609",
        "segment_start_trading_day": DAY.isoformat(),
        "opportunity_id": "subing-opportunity:task9",
        "kind": "close_long",
        "decision_at": CANONICAL_END.isoformat(),
        "effective_bar_end": CANONICAL_END.isoformat(),
        "fill_basis": "segment_terminal_close",
    }
    close = SubingStrategyAction(
        action_id=subing_strategy_action_id(identity),
        episode_id=entry.episode_id,
        strategy_id="subing_strategy_v1",
        formula_version="subing_strategy_15m_v1",
        kind=SubingStrategyActionKind.CLOSE_LONG,
        symbol="jm",
        contract="JM2609",
        trading_day=DAY,
        segment_start_trading_day=DAY,
        opportunity_id="subing-opportunity:task9",
        decision_at=CANONICAL_END,
        effective_open_at=None,
        effective_bar_end=CANONICAL_END,
        reference_price=Decimal("101"),
        fill_basis=SubingStrategyFillBasis.SEGMENT_TERMINAL_CLOSE,
        confirmation_source=None,
        reason_codes=("CONTRACT_SEGMENT_END",),
        direction_context_source_day=None,
        direction_context_target_day=None,
        bound_reference_pivot=None,
    )
    episode = SubingStrategyEpisode.from_actions(
        entry_action=entry,
        exit_action=close,
        completed_15m_bars=(
            _bar(BOUNDARY_END),
            _bar(CANONICAL_END),
        ),
        latest_reference_price=None,
    )
    return close, episode


class _Task9ActionEvaluator(_Task9StrategyEvaluator):
    def __init__(
        self,
        order: list[str],
        action: SubingStrategyAction,
        *,
        episode: SubingStrategyEpisode | None = None,
    ) -> None:
        super().__init__(order)
        self.action = action
        self.episode = episode
        self.rolled_over = False

    def current_state(self, symbol: str):
        return type(
            "State",
            (),
            {
                "symbol": symbol,
                "contract": "JM2609",
                "segment_start_trading_day": DAY,
                "current_episode": None,
                "closed_episodes": (
                    ()
                    if self.rolled_over
                    else (self.episode,)
                    if self.episode is not None
                    else ()
                ),
            },
        )()

    def process_completed_bar(self, bar, frequency, *, source_identity):
        self.order.append(f"strategy:{frequency.value}")
        return SubingStrategyRuntimeResult(
            action_facts=(SubingStrategyRuntimeActionFact(self.action, self.episode),),
            product_status=SubingStrategyRuntimeProductStatus(
                symbol=source_identity.symbol,
                state="ready",
                cutoff_1m=bar.bar_end,
                cutoff_5m=None,
                cutoff_15m=None,
                reason_codes=(),
            ),
        )

    def process_canonical_updated(self, trading_day: date):
        self.order.append(f"terminal:{trading_day.isoformat()}")
        self.rolled_over = True
        return (
            SubingStrategyRuntimeResult(
                action_facts=(
                    SubingStrategyRuntimeActionFact(self.action, self.episode),
                ),
                product_status=SubingStrategyRuntimeProductStatus(
                    symbol="jm",
                    state="ready",
                    cutoff_1m=None,
                    cutoff_5m=None,
                    cutoff_15m=self.action.decision_at,
                    reason_codes=(),
                ),
            ),
        )


def test_strategy_startup_subscribes_before_restore_and_catch_up(
    session: Session,
) -> None:
    _seed_rule(session, "htdy_original_15m")
    _seed_rule(session, "subing_strategy_v1", scope=())
    order: list[str] = []

    class OrderedSource(FakeMessageSource):
        def subscribe(self, *patterns: str) -> None:
            order.append("subscribe")
            super().subscribe(*patterns)

    source = OrderedSource()
    heartbeats = FakeHeartbeatStore()
    strategy = _Task9StrategyEvaluator(order)
    status = AtomicRuntimeStatusStore()
    sender = FakeSender()
    runtime = AlertRuntime(
        session_factory=lambda: nullcontext(session),
        market_read_factory=lambda _session: FakeRead(_window(bar_end=ORDINARY_END)),
        strategy_evaluator=strategy,
        htdy_evaluator=FakeHtdyEvaluator(()),
        sender=sender,
        operational_products=("jm",),
        taxonomy={"jm": ProductTaxonomyEntry(name="焦煤", sector="coal")},
        message_source=source,
        heartbeat_store=heartbeats,
        runtime_status_store=status,
        clock=lambda: ORDINARY_END + timedelta(seconds=2),
        stop_requested=lambda: True,
    )

    runtime.run_forever()

    assert order == ["subscribe", "restore", "catch_up"]
    assert status.status["schema_version"] == 3
    assert status.status["strategy_state"] == "ready"
    assert _event_rows(session) == []
    assert sender.messages == []


def test_startup_queue_cutoff_recovers_canonical_without_backfill(
    session: Session,
) -> None:
    """Catches a subscribed-before-ready terminal being emitted after readiness."""

    _seed_rule(session, "htdy_original_15m", scope=())
    _seed_rule(session, "subing_strategy_v1")
    order: list[str] = []
    startup_close, startup_episode = _task9_terminal_close()
    post_ready_open = _task9_open_action()
    strategy = _Task9ActionEvaluator(
        order,
        startup_close,
        episode=startup_episode,
    )

    class BoundarySource(FakeMessageSource):
        def __init__(self) -> None:
            super().__init__()
            self.startup_message = (
                "market:state",
                _canonical_updated_payload(),
            )
            self.post_ready_delivered = False
            self.timeouts: list[float] = []

        def get_message(self, *, timeout_seconds: float):
            self.timeouts.append(timeout_seconds)
            if self.startup_message is not None:
                message, self.startup_message = self.startup_message, None
                return message
            if timeout_seconds == 0.0:
                return None
            assert timeout_seconds == 1.0
            if not self.post_ready_delivered:
                self.post_ready_delivered = True
                strategy.action = post_ready_open
                strategy.episode = None
                return "market:state", _canonical_updated_payload()
            return None

    stop_checks = iter((False, False, True))
    source = BoundarySource()
    sender = FakeSender()
    runtime = AlertRuntime(
        session_factory=lambda: nullcontext(session),
        market_read_factory=lambda _session: FakeRead(_window(bar_end=ORDINARY_END)),
        strategy_evaluator=strategy,
        htdy_evaluator=FakeHtdyEvaluator(()),
        sender=sender,
        operational_products=("jm",),
        taxonomy={"jm": ProductTaxonomyEntry(name="焦煤", sector="coal")},
        message_source=source,
        heartbeat_store=FakeHeartbeatStore(),
        runtime_status_store=AtomicRuntimeStatusStore(),
        clock=lambda: BOUNDARY_END + timedelta(seconds=2),
        stop_requested=lambda: next(stop_checks),
    )

    runtime.run_forever()

    events = _event_rows(session)
    assert [event.action_id for event in events] == [post_ready_open.action_id]
    assert len(sender.messages) == 1
    assert order == [
        "restore",
        "catch_up",
        f"terminal:{DAY.isoformat()}",
        f"terminal:{DAY.isoformat()}",
    ]
    assert source.timeouts[:2] == [0.0, 0.0]
    assert source.timeouts.count(1.0) == 2


def test_pending_action_can_notify_only_from_a_post_ready_live_bar(
    session: Session,
) -> None:
    _seed_rule(session, "htdy_original_15m", scope=())
    _seed_rule(session, "subing_strategy_v1")
    order: list[str] = []
    strategy = _Task9ActionEvaluator(order, _task9_open_action())

    class OneMessageSource(FakeMessageSource):
        def __init__(self) -> None:
            super().__init__()
            self.message = (
                "live:bar:jm:1m",
                _payload(bar_end=BOUNDARY_END),
            )

        def get_message(self, *, timeout_seconds: float):
            if timeout_seconds == 0.0:
                return None
            assert timeout_seconds == 1.0
            message, self.message = self.message, None
            return message

    stop_checks = iter((False, True))
    source = OneMessageSource()
    sender = FakeSender()
    runtime = AlertRuntime(
        session_factory=lambda: nullcontext(session),
        market_read_factory=lambda _session: FakeRead(_window(bar_end=ORDINARY_END)),
        strategy_evaluator=strategy,
        htdy_evaluator=FakeHtdyEvaluator(()),
        sender=sender,
        operational_products=("jm",),
        taxonomy={"jm": ProductTaxonomyEntry(name="焦煤", sector="coal")},
        message_source=source,
        heartbeat_store=FakeHeartbeatStore(),
        runtime_status_store=AtomicRuntimeStatusStore(),
        clock=lambda: BOUNDARY_END + timedelta(seconds=2),
        stop_requested=lambda: next(stop_checks),
    )

    runtime.run_forever()

    assert order == ["restore", "catch_up", "strategy:1m"]
    assert len(_event_rows(session)) == 1
    assert len(sender.messages) == 1


def test_missing_rule_registry_blocks_subscribe_restore_and_ready(
    session: Session,
) -> None:
    _seed_rule(session, "htdy_original_15m")
    order: list[str] = []
    source = FakeMessageSource()
    runtime = AlertRuntime(
        session_factory=lambda: nullcontext(session),
        market_read_factory=lambda _session: FakeRead(_window(bar_end=ORDINARY_END)),
        strategy_evaluator=_Task9StrategyEvaluator(order),
        htdy_evaluator=FakeHtdyEvaluator(()),
        sender=FakeSender(),
        operational_products=("jm",),
        taxonomy={"jm": ProductTaxonomyEntry(name="焦煤", sector="coal")},
        message_source=source,
        heartbeat_store=FakeHeartbeatStore(),
        runtime_status_store=AtomicRuntimeStatusStore(),
        clock=lambda: ORDINARY_END,
        stop_requested=lambda: True,
    )

    with pytest.raises(RuntimeError, match="^ALERT_RUNTIME_COMPOSITION_INVALID$"):
        runtime.run_forever()

    assert source.subscribe_calls == []
    assert order == []


def test_active_strategy_without_operational_live_feed_blocks_subscribe(
    session: Session,
) -> None:
    _seed_rule(session, "htdy_original_15m", scope=())
    _seed_rule(session, "subing_strategy_v1", scope=())
    order: list[str] = []
    source = FakeMessageSource()
    runtime = AlertRuntime(
        session_factory=lambda: nullcontext(session),
        market_read_factory=lambda _session: FakeRead(_window(bar_end=ORDINARY_END)),
        strategy_evaluator=_Task9StrategyEvaluator(order),
        htdy_evaluator=FakeHtdyEvaluator(()),
        sender=FakeSender(),
        operational_products=("ag",),
        taxonomy={"jm": ProductTaxonomyEntry(name="焦煤", sector="coal")},
        message_source=source,
        heartbeat_store=FakeHeartbeatStore(),
        runtime_status_store=AtomicRuntimeStatusStore(),
        clock=lambda: ORDINARY_END,
        stop_requested=lambda: True,
    )

    with pytest.raises(RuntimeError, match="^ALERT_RUNTIME_COMPOSITION_INVALID$"):
        runtime.run_forever()

    assert source.subscribe_calls == []
    assert order == []


def test_invalid_runtime_status_blocks_subscribe_restore_and_ready(
    session: Session,
) -> None:
    order: list[str] = []
    source = FakeMessageSource()

    class InvalidStatusStore:
        def read(self) -> dict[str, object]:
            return {"schema_version": 999}

        def write(self, _payload: dict[str, object]) -> None:
            raise AssertionError("invalid status must block every write")

    runtime = AlertRuntime(
        session_factory=lambda: nullcontext(session),
        market_read_factory=lambda _session: FakeRead(_window(bar_end=ORDINARY_END)),
        strategy_evaluator=_Task9StrategyEvaluator(order),
        htdy_evaluator=FakeHtdyEvaluator(()),
        sender=FakeSender(),
        operational_products=("jm",),
        taxonomy={"jm": ProductTaxonomyEntry(name="焦煤", sector="coal")},
        message_source=source,
        heartbeat_store=FakeHeartbeatStore(),
        runtime_status_store=InvalidStatusStore(),
        clock=lambda: ORDINARY_END,
        stop_requested=lambda: True,
    )

    with pytest.raises(ValueError, match="^ALERT_RUNTIME_STATUS_INVALID$"):
        runtime.run_forever()

    assert source.subscribe_calls == []
    assert order == []


def test_new_strategy_action_is_committed_before_one_shot_send(
    session: Session,
) -> None:
    _seed_rule(session, "subing_strategy_v1")
    order: list[str] = []
    strategy = _Task9ActionEvaluator(order, _task9_open_action())

    class OrderedSender(FakeSender):
        def send(self, event: AlertNotificationMessage) -> ProviderAcceptance:
            assert len(_event_rows(session)) == 1
            order.append("send")
            return super().send(event)

    sender = OrderedSender()
    runtime = AlertRuntime(
        session_factory=lambda: nullcontext(session),
        market_read_factory=lambda _session: FakeRead(_window(bar_end=ORDINARY_END)),
        strategy_evaluator=strategy,
        htdy_evaluator=FakeHtdyEvaluator(()),
        sender=sender,
        operational_products=("jm",),
        taxonomy={"jm": ProductTaxonomyEntry(name="焦煤", sector="coal")},
        clock=lambda: BOUNDARY_END + timedelta(seconds=2),
    )

    runtime.process_message("live:bar:jm:1m", _payload(bar_end=BOUNDARY_END))

    event = _event_rows(session)[0]
    assert event.action_id == strategy.action.action_id
    assert event.result_codes == ["open_long"]
    assert order == ["strategy:1m", "send"]


@pytest.mark.parametrize("enabled,scope", ((False, ("jm",)), (True, ())))
def test_strategy_rule_authority_never_controls_calculation_state(
    session: Session,
    enabled: bool,
    scope: tuple[str, ...],
) -> None:
    _seed_rule(session, "subing_strategy_v1", enabled=enabled, scope=scope)
    order: list[str] = []
    strategy = _Task9ActionEvaluator(order, _task9_open_action())
    harness = _runtime(session, strategy_evaluator=strategy)

    harness.runtime.process_message("live:bar:jm:1m", _payload(bar_end=BOUNDARY_END))

    assert order == ["strategy:1m"]
    assert _event_rows(session) == []
    assert harness.sender.messages == []


def test_strategy_duplicate_and_fact_conflict_never_send_again(
    session: Session,
) -> None:
    _seed_rule(session, "subing_strategy_v1")
    action = _task9_open_action()
    strategy = _Task9ActionEvaluator([], action)
    harness = _runtime(session, strategy_evaluator=strategy)

    harness.runtime.process_message("live:bar:jm:1m", _payload(bar_end=BOUNDARY_END))
    harness.runtime.process_message("live:bar:jm:1m", _payload(bar_end=BOUNDARY_END))
    strategy.action = replace(action, reference_price=Decimal("101"))
    harness.runtime.process_message("live:bar:jm:1m", _payload(bar_end=BOUNDARY_END))

    assert len(_event_rows(session)) == 1
    assert len(harness.sender.messages) == 1


def test_strategy_product_failure_does_not_block_htdy(session: Session) -> None:
    _seed_rule(session, "htdy_original_15m")

    class DegradedStrategy(_Task9StrategyEvaluator):
        def process_completed_bar(self, bar, _frequency, *, source_identity):
            self.order.append("strategy:degraded")
            return SubingStrategyRuntimeResult(
                action_facts=(),
                product_status=SubingStrategyRuntimeProductStatus(
                    symbol=source_identity.symbol,
                    state="unavailable",
                    cutoff_1m=bar.bar_end,
                    cutoff_5m=None,
                    cutoff_15m=None,
                    reason_codes=("CURRENT_UNAVAILABLE",),
                ),
            )

    order: list[str] = []
    strategy = DegradedStrategy(order)
    harness = _runtime(
        session,
        event_end=BOUNDARY_END,
        strategy_evaluator=strategy,
    )

    harness.runtime.process_message("live:bar:jm:15m", _payload(bar_end=BOUNDARY_END))

    assert order == ["strategy:degraded"]
    assert _rule_codes(_event_rows(session)) == ["htdy_original_15m"]
    assert len(harness.sender.messages) == 1


def test_unknown_completed_bar_evaluator_fault_escapes_without_rule_side_effects(
    session: Session,
) -> None:
    _seed_rule(session, "htdy_original_15m")

    class BrokenStrategy(_Task9StrategyEvaluator):
        def process_completed_bar(self, *_args, **_kwargs):
            raise AssertionError("programming bug")

    harness = _runtime(
        session,
        event_end=BOUNDARY_END,
        strategy_evaluator=BrokenStrategy([]),
    )

    with pytest.raises(AssertionError, match="^programming bug$"):
        harness.runtime.process_message(
            "live:bar:jm:15m", _payload(bar_end=BOUNDARY_END)
        )

    assert _event_rows(session) == []
    assert harness.sender.messages == []


def test_unknown_canonical_evaluator_fault_escapes_without_rule_side_effects(
    session: Session,
) -> None:
    _seed_rule(session, "htdy_original_15m")

    class BrokenStrategy(_Task9StrategyEvaluator):
        def process_canonical_updated(self, _trading_day: date):
            raise AssertionError("programming bug")

    harness = _runtime(
        session,
        strategy_evaluator=BrokenStrategy([]),
    )

    with pytest.raises(AssertionError, match="^programming bug$"):
        harness.runtime.process_message("market:state", _canonical_updated_payload())

    assert _event_rows(session) == []
    assert harness.sender.messages == []


def test_completed_result_from_wrong_status_product_fails_before_session(
    session: Session,
) -> None:
    class WrongStatusStrategy(_Task9StrategyEvaluator):
        def process_completed_bar(self, bar, frequency, *, source_identity):
            return SubingStrategyRuntimeResult(
                action_facts=(),
                product_status=_task9_product_status("ag"),
            )

    harness = _runtime(
        session,
        strategy_evaluator=WrongStatusStrategy([]),
    )
    session_calls = 0

    def fail_if_session_opens():
        nonlocal session_calls
        session_calls += 1
        raise AssertionError("Rule session opened")

    harness.runtime._session_factory = fail_if_session_opens

    with pytest.raises(
        ValueError,
        match="^ALERT_RUNTIME_STRATEGY_RESULT_INVALID$",
    ):
        harness.runtime.process_message("live:bar:jm:1m", _payload())

    assert session_calls == 0
    assert _event_rows(session) == []
    assert harness.sender.messages == []


def test_completed_result_with_cross_product_action_fails_before_session(
    session: Session,
) -> None:
    wrong_product_action = _task9_open_action(symbol="ag", contract="AG2609")

    class WrongActionStrategy(_Task9StrategyEvaluator):
        def process_completed_bar(self, bar, frequency, *, source_identity):
            return _unsafe_strategy_runtime_result(
                action_facts=(
                    SubingStrategyRuntimeActionFact(wrong_product_action, None),
                ),
                product_status=_task9_product_status("jm"),
            )

    harness = _runtime(
        session,
        strategy_evaluator=WrongActionStrategy([]),
    )
    session_calls = 0

    def fail_if_session_opens():
        nonlocal session_calls
        session_calls += 1
        raise AssertionError("Rule session opened")

    harness.runtime._session_factory = fail_if_session_opens

    with pytest.raises(
        ValueError,
        match="^ALERT_RUNTIME_STRATEGY_RESULT_INVALID$",
    ):
        harness.runtime.process_message("live:bar:jm:1m", _payload())

    assert session_calls == 0
    assert _event_rows(session) == []
    assert harness.sender.messages == []


@pytest.mark.parametrize(
    ("active_products", "result_symbols"),
    (
        (("jm", "ag"), ("jm",)),
        (("jm", "ag"), ("jm", "jm")),
        (("jm",), ("jm", "ag")),
    ),
    ids=("missing", "duplicate", "extra"),
)
def test_canonical_result_product_set_mismatch_fails_before_session(
    session: Session,
    active_products: tuple[str, ...],
    result_symbols: tuple[str, ...],
) -> None:
    class WrongProductSetStrategy(_Task9StrategyEvaluator):
        def __init__(self) -> None:
            super().__init__([])
            self.products = active_products

        def process_canonical_updated(self, _trading_day: date):
            return tuple(
                SubingStrategyRuntimeResult(
                    action_facts=(),
                    product_status=_task9_product_status(symbol),
                )
                for symbol in result_symbols
            )

    harness = _runtime(
        session,
        operational_products=active_products,
        strategy_evaluator=WrongProductSetStrategy(),
    )
    session_calls = 0

    def fail_if_session_opens():
        nonlocal session_calls
        session_calls += 1
        raise AssertionError("Rule session opened")

    harness.runtime._session_factory = fail_if_session_opens

    with pytest.raises(
        ValueError,
        match="^ALERT_RUNTIME_STRATEGY_RESULT_INVALID$",
    ):
        harness.runtime.process_message("market:state", _canonical_updated_payload())

    assert session_calls == 0
    assert _event_rows(session) == []
    assert harness.sender.messages == []


def test_completed_bar_refreshes_strategy_v3_degrade_and_recovery(
    session: Session,
) -> None:
    states = iter(("unavailable", "ready"))

    class ChangingStrategy(_Task9StrategyEvaluator):
        def process_completed_bar(self, bar, frequency, *, source_identity):
            state = next(states)
            return SubingStrategyRuntimeResult(
                action_facts=(),
                product_status=SubingStrategyRuntimeProductStatus(
                    symbol=source_identity.symbol,
                    state=state,
                    cutoff_1m=bar.bar_end,
                    cutoff_5m=None,
                    cutoff_15m=None,
                    reason_codes=("CURRENT_UNAVAILABLE",)
                    if state == "unavailable"
                    else (),
                ),
            )

    status = AtomicRuntimeStatusStore()
    harness = _runtime(
        session,
        strategy_evaluator=ChangingStrategy([]),
        runtime_status_store=status,
    )

    harness.runtime.process_message("live:bar:jm:1m", _payload())
    assert status.status["strategy_state"] == "degraded"
    assert status.status["strategy_product_count"] == 1
    assert status.status["strategy_ready_product_count"] == 0
    assert status.status["strategy_unavailable_symbols"] == ["jm"]

    harness.runtime.process_message("live:bar:jm:1m", _payload())
    assert status.status["strategy_state"] == "ready"
    assert status.status["strategy_ready_product_count"] == 1
    assert status.status["strategy_unavailable_product_count"] == 0
    assert status.status["strategy_unavailable_symbols"] == []


def test_canonical_result_refreshes_strategy_v3_product_aggregate(
    session: Session,
) -> None:
    class DegradedTerminalStrategy(_Task9StrategyEvaluator):
        def process_canonical_updated(self, trading_day: date):
            return (
                SubingStrategyRuntimeResult(
                    action_facts=(),
                    product_status=SubingStrategyRuntimeProductStatus(
                        symbol="jm",
                        state="unavailable",
                        cutoff_1m=None,
                        cutoff_5m=None,
                        cutoff_15m=None,
                        reason_codes=("TERMINAL_UNAVAILABLE",),
                    ),
                ),
            )

    status = AtomicRuntimeStatusStore()
    harness = _runtime(
        session,
        strategy_evaluator=DegradedTerminalStrategy([]),
        runtime_status_store=status,
    )

    harness.runtime.process_message("market:state", _canonical_updated_payload())

    assert status.status["strategy_state"] == "degraded"
    assert status.status["strategy_product_count"] == 1
    assert status.status["strategy_unavailable_product_count"] == 1
    assert status.status["strategy_unavailable_symbols"] == ["jm"]


def test_canonical_terminal_action_uses_the_same_event_path(session: Session) -> None:
    _seed_rule(session, "subing_strategy_v1")
    close, episode = _task9_terminal_close()
    order: list[str] = []
    strategy = _Task9ActionEvaluator(order, close, episode=episode)
    harness = _runtime(session, strategy_evaluator=strategy)

    harness.runtime.process_message("market:state", _canonical_updated_payload())

    event = _event_rows(session)[0]
    assert event.action_id == close.action_id
    assert event.result_codes == ["close_long"]
    assert order == [f"terminal:{DAY.isoformat()}"]
    assert len(harness.sender.messages) == 1
