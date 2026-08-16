from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import importlib

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.alerts.models import AlertEvent, AlertRule
from app.db.base import Base
from app.execution_review.models import TradeEpisode, TradeExecution
from app.execution_review.service import (
    ExecutedCommand,
    ExecutionCommand,
    ExecutionReviewService,
)
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.market_data_service import (
    DominantContractSegmentSummary,
    MarketDataError,
)


BAR_END = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)
OPENED_AT = BAR_END + timedelta(minutes=3)
ROLL_DAY = date(2026, 8, 14)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


class _MarketData:
    def __init__(self) -> None:
        self.old_segment = DominantContractSegmentSummary(
            "jm", "JM2609", ROLL_DAY, ROLL_DAY
        )
        self.current_segment = DominantContractSegmentSummary(
            "jm", "JM2701", date(2026, 8, 17), date(2026, 8, 18)
        )
        self.reference_bars = (
            _bar(BAR_END + timedelta(minutes=20), "1260"),
            _bar(BAR_END + timedelta(minutes=30), "1258"),
        )
        self.error: MarketDataError | None = None
        self.reference_calls: list[tuple[str, str, BarFrequency, date]] = []

    def dominant_segment_for_day(
        self, _symbol: str, _trading_day: date
    ) -> DominantContractSegmentSummary:
        if self.error is not None:
            raise self.error
        return self.old_segment

    def latest_dominant_segment(
        self, _symbol: str
    ) -> DominantContractSegmentSummary:
        if self.error is not None:
            raise self.error
        return self.current_segment

    def contract_bars_for_trading_day(
        self,
        *,
        symbol: str,
        contract: str,
        frequency: BarFrequency,
        trading_day: date,
    ) -> tuple[CanonicalBar, ...]:
        self.reference_calls.append((symbol, contract, frequency, trading_day))
        if self.error is not None:
            raise self.error
        return self.reference_bars


def test_same_current_rank1_is_noop_without_reference_read(session: Session) -> None:
    opened = _open_episode(session)
    market_data = _MarketData()
    market_data.current_segment = market_data.old_segment

    result = _reconciler(session, market_data).reconcile_symbol("jm")

    assert result.status == "NOOP"
    assert market_data.reference_calls == []
    episode = session.get(TradeEpisode, opened.id)
    assert episode is not None
    assert episode.closed_at is None


def test_same_contract_code_in_a_later_rank1_segment_still_closes_old_episode(
    session: Session,
) -> None:
    opened = _open_episode(session)
    market_data = _MarketData()
    market_data.current_segment = DominantContractSegmentSummary(
        "jm",
        market_data.old_segment.contract,
        date(2026, 8, 20),
        date(2026, 8, 21),
    )

    result = _reconciler(session, market_data).reconcile_symbol("jm")

    assert result.status == "DOMINANT_ROLL"
    episode = session.get(TradeEpisode, opened.id)
    assert episode is not None
    assert episode.close_reason == "DOMINANT_ROLL"
    assert market_data.reference_calls == [
        ("jm", "JM2609", BarFrequency.M1, ROLL_DAY)
    ]


def test_changed_rank1_closes_with_last_old_contract_confirmed_m1_without_fake_close(
    session: Session,
) -> None:
    opened = _open_episode(session)
    market_data = _MarketData()

    result = _reconciler(session, market_data).reconcile_symbol("jm")

    assert result.status == "DOMINANT_ROLL"
    episode = session.get(TradeEpisode, opened.id)
    assert episode is not None
    assert episode.close_reason == "DOMINANT_ROLL"
    assert _utc(episode.closed_at) == BAR_END + timedelta(minutes=30)
    assert episode.roll_reference_exit_price == Decimal("1258")
    assert _utc(episode.roll_reference_bar_end) == BAR_END + timedelta(minutes=30)
    assert market_data.reference_calls == [
        ("jm", "JM2609", BarFrequency.M1, ROLL_DAY)
    ]
    assert session.scalar(select(func.count()).select_from(TradeExecution)) == 1


def test_missing_formal_identity_keeps_episode_open_and_requires_reconciliation(
    session: Session,
) -> None:
    opened = _open_episode(session)
    market_data = _MarketData()
    market_data.error = MarketDataError("DOMINANT_CONTEXT_MISSING")

    result = _reconciler(session, market_data).reconcile_symbol("jm")

    assert result.status == "ROLL_RECONCILIATION_REQUIRED"
    episode = session.get(TradeEpisode, opened.id)
    assert episode is not None
    assert episode.closed_at is None
    assert episode.roll_reference_bar_end is None


def test_historical_contract_conflict_keeps_episode_open(session: Session) -> None:
    opened = _open_episode(session)
    market_data = _MarketData()
    market_data.old_segment = DominantContractSegmentSummary(
        "jm", "JM2509", ROLL_DAY, ROLL_DAY
    )

    result = _reconciler(session, market_data).reconcile_symbol("jm")

    assert result.status == "ROLL_RECONCILIATION_REQUIRED"
    episode = session.get(TradeEpisode, opened.id)
    assert episode is not None
    assert episode.closed_at is None
    assert market_data.reference_calls == []


def test_missing_reference_bar_keeps_episode_open(session: Session) -> None:
    opened = _open_episode(session)
    market_data = _MarketData()
    market_data.reference_bars = ()

    result = _reconciler(session, market_data).reconcile_symbol("jm")

    assert result.status == "ROLL_RECONCILIATION_REQUIRED"
    episode = session.get(TradeEpisode, opened.id)
    assert episode is not None
    assert episode.closed_at is None


def test_reference_before_opened_at_keeps_episode_open(session: Session) -> None:
    opened = _open_episode(session)
    market_data = _MarketData()
    market_data.reference_bars = (_bar(OPENED_AT - timedelta(seconds=1), "1260"),)

    result = _reconciler(session, market_data).reconcile_symbol("jm")

    assert result.status == "ROLL_RECONCILIATION_REQUIRED"
    episode = session.get(TradeEpisode, opened.id)
    assert episode is not None
    assert episode.closed_at is None
    assert episode.close_reason is None


def test_reference_before_later_real_add_keeps_episode_open(session: Session) -> None:
    opened = _open_episode(session)
    later_add = BAR_END + timedelta(minutes=40)
    ExecutionReviewService(
        session, multipliers={"jm": Decimal("60")}, clock=lambda: later_add
    ).append_execution(
        opened.id,
        ExecutionCommand(
            execution_type="ADD",
            executed_at=later_add,
            price=Decimal("1255"),
            quantity=1,
        ),
    )
    market_data = _MarketData()
    market_data.reference_bars = (_bar(BAR_END + timedelta(minutes=30), "1258"),)

    result = _reconciler(session, market_data).reconcile_symbol("jm")

    assert result.status == "ROLL_RECONCILIATION_REQUIRED"
    episode = session.get(TradeEpisode, opened.id)
    assert episode is not None
    assert episode.closed_at is None
    assert episode.close_reason is None
    assert session.scalar(select(func.count()).select_from(TradeExecution)) == 2


def test_reference_equal_to_latest_real_execution_can_close(session: Session) -> None:
    opened = _open_episode(session)
    later_add = BAR_END + timedelta(minutes=40)
    ExecutionReviewService(
        session, multipliers={"jm": Decimal("60")}, clock=lambda: later_add
    ).append_execution(
        opened.id,
        ExecutionCommand(
            execution_type="ADD",
            executed_at=later_add,
            price=Decimal("1255"),
            quantity=1,
        ),
    )
    market_data = _MarketData()
    market_data.reference_bars = (_bar(later_add, "1255"),)

    result = _reconciler(session, market_data).reconcile_symbol("jm")

    assert result.status == "DOMINANT_ROLL"
    episode = session.get(TradeEpisode, opened.id)
    assert episode is not None
    assert _utc(episode.closed_at) == later_add


def _reconciler(session: Session, market_data: _MarketData):
    module = importlib.import_module("app.execution_review.reconciler")
    return module.ExecutionReviewRollReconciler(session, market_data=market_data)


def _open_episode(session: Session) -> TradeEpisode:
    rule = AlertRule(
        rule_code="subing_entry_signal_v1",
        enabled=True,
        scope_products=["jm"],
        created_at=BAR_END,
        updated_at=BAR_END,
    )
    event = AlertEvent(
        rule=rule,
        symbol="jm",
        contract="JM2609",
        trading_day=ROLL_DAY,
        frequency="15m",
        bar_end=BAR_END,
        result_codes=["buy"],
        lower_tf_confirmation=False,
        detected_at=BAR_END + timedelta(seconds=1),
    )
    session.add(event)
    session.commit()
    result = ExecutionReviewService(
        session,
        multipliers={"jm": Decimal("60")},
        clock=lambda: OPENED_AT,
    ).record_executed(
        event.id,
        ExecutedCommand(
            executed_at=OPENED_AT,
            price=Decimal("1268"),
            quantity=1,
            execution_reason_tags=("KEY_LEVEL_BREAKOUT",),
        ),
    )
    return result.episode


def _bar(bar_end: datetime, close: str) -> CanonicalBar:
    value = Decimal(close)
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=ROLL_DAY,
        open=value,
        high=value + 1,
        low=value - 1,
        close=value,
        volume=Decimal(1),
        turnover=Decimal(10),
        open_interest=Decimal(20),
    )


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
