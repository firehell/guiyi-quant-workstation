from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.alerts.models import AlertEvent, AlertRule
from app.db.base import Base
from app.execution_review.models import TradeDecision, TradeEpisode, TradeExecution
from app.execution_review.service import (
    ExecutionReviewDomainError,
    ExecutionReviewService,
)
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.market_data_service import (
    DominantContractSegmentSummary,
    MarketDataError,
)


EVENT_DAY = date(2026, 8, 14)
EVENT_END = datetime(2026, 8, 14, 1, 10, tzinfo=UTC)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


class _MarketData:
    def __init__(self) -> None:
        self.segment = DominantContractSegmentSummary(
            symbol="jm",
            contract="JM2609",
            start_trading_day=date(2026, 8, 13),
            end_trading_day=date(2026, 8, 17),
        )
        self.bars: dict[tuple[BarFrequency, date], tuple[CanonicalBar, ...]] = {}
        self.error: MarketDataError | None = None
        self.calls: list[tuple[str, object]] = []

    def dominant_segment_for_day(
        self, symbol: str, trading_day: date
    ) -> DominantContractSegmentSummary:
        self.calls.append(("segment", (symbol, trading_day)))
        if self.error is not None:
            raise self.error
        return self.segment

    def contract_bars_for_trading_day(
        self,
        *,
        symbol: str,
        contract: str,
        frequency: BarFrequency,
        trading_day: date,
    ) -> tuple[CanonicalBar, ...]:
        self.calls.append(
            ("bars", (symbol, contract, frequency, trading_day))
        )
        if self.error is not None:
            raise self.error
        return self.bars.get((frequency, trading_day), ())


def test_signal_reconstruction_uses_event_identity_and_strict_cutoff(
    session: Session,
) -> None:
    event = _event(session, frequency="5m")
    market_data = _MarketData()
    market_data.bars[(BarFrequency.M5, EVENT_DAY)] = (
        _bar(EVENT_END - timedelta(minutes=5), EVENT_DAY, "100"),
        _bar(EVENT_END, EVENT_DAY, "101"),
        _bar(EVENT_END + timedelta(minutes=5), EVENT_DAY, "102"),
    )
    market_data.bars[(BarFrequency.M15, EVENT_DAY)] = (
        _bar(EVENT_END - timedelta(minutes=10), EVENT_DAY, "200"),
        _bar(EVENT_END + timedelta(minutes=5), EVENT_DAY, "201"),
    )

    result = _service(session, market_data).reconstruct_event(event.id, mode="signal")

    assert result.status == "READY"
    assert result.reason is None
    assert result.post_hoc_reconstruction is True
    assert result.window.start_trading_day == EVENT_DAY
    assert result.window.end_trading_day == EVENT_DAY
    assert result.window.bar_end_cutoff == EVENT_END
    assert tuple(bar.bar_end for bar in result.bars_5m) == (
        EVENT_END - timedelta(minutes=5),
        EVENT_END,
    )
    assert tuple(bar.bar_end for bar in result.bars_15m) == (
        EVENT_END - timedelta(minutes=10),
    )
    assert all(
        call[1][1] == "JM2609"
        for call in market_data.calls
        if call[0] == "bars"
    )
    assert _db_row_count(session) == 0


def test_full_reconstruction_returns_only_the_event_rank1_segment(
    session: Session,
) -> None:
    event = _event(session, frequency="15m")
    market_data = _MarketData()
    for offset in range(5):
        trading_day = date(2026, 8, 13) + timedelta(days=offset)
        bar_end = EVENT_END + timedelta(days=offset - 1)
        market_data.bars[(BarFrequency.M5, trading_day)] = (
            _bar(bar_end, trading_day, str(100 + offset)),
        )
        market_data.bars[(BarFrequency.M15, trading_day)] = (
            _bar(bar_end, trading_day, str(200 + offset)),
        )

    result = _service(session, market_data).reconstruct_event(event.id, mode="full")

    assert result.status == "READY"
    assert result.window.start_trading_day == date(2026, 8, 13)
    assert result.window.end_trading_day == date(2026, 8, 17)
    assert result.window.bar_end_cutoff is None
    assert len(result.bars_5m) == len(result.bars_15m) == 5
    assert max(bar.trading_day for bar in result.bars_5m) == date(2026, 8, 17)
    assert _db_row_count(session) == 0


def test_fifteen_minute_signal_reconstruction_excludes_future_five_minute_bar(
    session: Session,
) -> None:
    event = _event(session, frequency="15m")
    market_data = _MarketData()
    market_data.bars[(BarFrequency.M5, EVENT_DAY)] = (
        _bar(EVENT_END - timedelta(minutes=5), EVENT_DAY, "100"),
        _bar(EVENT_END + timedelta(minutes=5), EVENT_DAY, "101"),
    )
    market_data.bars[(BarFrequency.M15, EVENT_DAY)] = (
        _bar(EVENT_END, EVENT_DAY, "200"),
        _bar(EVENT_END + timedelta(minutes=15), EVENT_DAY, "201"),
    )

    result = _service(session, market_data).reconstruct_event(event.id, mode="signal")

    assert result.status == "READY"
    assert tuple(bar.bar_end for bar in result.bars_5m) == (
        EVENT_END - timedelta(minutes=5),
    )
    assert tuple(bar.bar_end for bar in result.bars_15m) == (EVENT_END,)


def test_reconstruction_fails_closed_for_historical_contract_conflict(
    session: Session,
) -> None:
    event = _event(session)
    market_data = _MarketData()
    market_data.segment = DominantContractSegmentSummary(
        symbol="jm",
        contract="JM2701",
        start_trading_day=EVENT_DAY,
        end_trading_day=EVENT_DAY,
    )

    result = _service(session, market_data).reconstruct_event(event.id, mode="signal")

    assert result.status == "UNAVAILABLE"
    assert result.reason == "MARKET_IDENTITY_CONFLICT"
    assert result.segment is None
    assert result.bars_5m == result.bars_15m == ()
    assert _db_row_count(session) == 0


@pytest.mark.parametrize(
    ("code", "reason"),
    (
        ("DOMINANT_CONTEXT_MISSING", "MARKET_HISTORY_NOT_READY"),
        ("TRADING_CALENDAR_MISSING", "MARKET_HISTORY_NOT_READY"),
        ("MAIN_CONTRACT_MAP_MISSING", "MARKET_HISTORY_NOT_READY"),
        ("INSTRUMENT_EXCHANGE_MISSING", "MARKET_HISTORY_NOT_READY"),
        ("TRADING_SESSION_MISSING", "MARKET_HISTORY_NOT_READY"),
        ("PREVIOUS_TRADING_DAY_MISSING", "MARKET_HISTORY_NOT_READY"),
        ("PRODUCT_RETIRED", "MARKET_HISTORY_NOT_READY"),
        ("MAIN_CONTRACT_MAP_CONFLICT", "MARKET_IDENTITY_CONFLICT"),
        ("BAR_IDENTITY_CONFLICT", "MARKET_IDENTITY_CONFLICT"),
        ("DATASET_OR_PARTITION_MISSING", "MARKET_PARTITION_UNAVAILABLE"),
        ("QUERY_WINDOW_EMPTY", "MARKET_PARTITION_UNAVAILABLE"),
        ("PARTITION_INTEGRITY_INVALID", "MARKET_PARTITION_UNAVAILABLE"),
    ),
)
def test_reconstruction_maps_only_expected_market_data_errors_to_unavailable(
    session: Session,
    code: str,
    reason: str,
) -> None:
    event = _event(session)
    market_data = _MarketData()
    market_data.error = MarketDataError(code)

    result = _service(session, market_data).reconstruct_event(event.id, mode="signal")

    assert result.status == "UNAVAILABLE"
    assert result.reason == reason
    assert _db_row_count(session) == 0


def test_reconstruction_unknown_market_error_is_503_and_writes_nothing(
    session: Session,
) -> None:
    event = _event(session)
    market_data = _MarketData()
    market_data.error = MarketDataError("UNKNOWN_INFRASTRUCTURE_FAILURE")

    with pytest.raises(
        ExecutionReviewDomainError,
        match="EXECUTION_REVIEW_PERSIST_FAILED",
    ) as raised:
        _service(session, market_data).reconstruct_event(event.id, mode="signal")

    assert raised.value.status_code == 503
    assert _db_row_count(session) == 0


def _service(session: Session, market_data: _MarketData) -> ExecutionReviewService:
    return ExecutionReviewService(
        session,
        multipliers={},
        clock=lambda: EVENT_END,
        market_data=market_data,
    )


def _event(session: Session, *, frequency: str = "5m") -> AlertEvent:
    rule = AlertRule(
        rule_code="subing_entry_signal_v1",
        enabled=True,
        scope_products=["jm"],
        created_at=EVENT_END,
        updated_at=EVENT_END,
    )
    session.add(rule)
    session.flush()
    event = AlertEvent(
        rule_id=rule.id,
        symbol="jm",
        contract="JM2609",
        trading_day=EVENT_DAY,
        frequency=frequency,
        bar_end=EVENT_END,
        result_codes=["buy"],
        lower_tf_confirmation=False,
        detected_at=EVENT_END + timedelta(seconds=1),
    )
    session.add(event)
    session.commit()
    return event


def _bar(bar_end: datetime, trading_day: date, close: str) -> CanonicalBar:
    value = Decimal(close)
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=trading_day,
        open=value,
        high=value + 1,
        low=value - 1,
        close=value,
        volume=Decimal(1),
        turnover=Decimal(10),
        open_interest=Decimal(20),
    )


def _db_row_count(session: Session) -> int:
    return sum(
        session.scalar(select(func.count()).select_from(model)) or 0
        for model in (TradeDecision, TradeEpisode, TradeExecution)
    )
