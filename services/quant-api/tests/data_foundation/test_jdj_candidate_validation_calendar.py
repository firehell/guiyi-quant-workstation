from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

import app.research.jdj.jdj_candidate_validation_calendar as calendar_module
from app.db.base import Base
from app.research.jdj.jdj_candidate_validation_policy import (
    JdjCandidateValidationProtocolError,
)
from app.research.jdj.jdj_candidate_validation_calendar import (
    JdjProspectiveCalendarError,
    assert_jdj_prospective_calendar,
)
from app.models import Exchange, Instrument, TradingCalendar


_EXPECTED = (
    (date(2026, 8, 21), True),
    (date(2026, 8, 22), False),
    (date(2026, 8, 23), False),
    (date(2026, 8, 24), True),
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        value.add(
            Exchange(
                code="DCE",
                name="Dalian Commodity Exchange",
                country="CN",
                timezone="Asia/Shanghai",
                is_active=True,
            )
        )
        value.add(
            Instrument(
                symbol="jm",
                name="JM",
                exchange_code="DCE",
                is_active=True,
            )
        )
        value.add_all(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=trade_date,
                is_trading_day=is_trading_day,
            )
            for trade_date, is_trading_day in _EXPECTED
        )
        value.commit()
        yield value


def test_exact_jm_calendar_is_read_only_and_accepted(session: Session) -> None:
    before = tuple(
        session.execute(
            select(
                TradingCalendar.trade_date,
                TradingCalendar.is_trading_day,
            ).order_by(TradingCalendar.trade_date)
        ).all()
    )

    assert assert_jdj_prospective_calendar(session) is None

    after = tuple(
        session.execute(
            select(
                TradingCalendar.trade_date,
                TradingCalendar.is_trading_day,
            ).order_by(TradingCalendar.trade_date)
        ).all()
    )
    assert after == before == _EXPECTED
    assert not session.new
    assert not session.dirty
    assert not session.deleted


def test_frozen_provider_evidence_allows_future_catalog_day_to_be_pending(
    session: Session,
) -> None:
    session.execute(
        delete(TradingCalendar).where(
            TradingCalendar.trade_date == date(2026, 8, 24)
        )
    )
    session.commit()

    before = tuple(
        session.execute(
            select(
                TradingCalendar.trade_date,
                TradingCalendar.is_trading_day,
            ).order_by(TradingCalendar.trade_date)
        ).all()
    )

    assert assert_jdj_prospective_calendar(session) is None

    after = tuple(
        session.execute(
            select(
                TradingCalendar.trade_date,
                TradingCalendar.is_trading_day,
            ).order_by(TradingCalendar.trade_date)
        ).all()
    )
    assert after == before == _EXPECTED[:3]
    assert not session.new
    assert not session.dirty
    assert not session.deleted


def test_invalid_protocol_evidence_maps_to_stable_calendar_error(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid_protocol() -> None:
        raise JdjCandidateValidationProtocolError()

    monkeypatch.setattr(
        calendar_module,
        "load_jdj_candidate_validation_protocol",
        invalid_protocol,
    )

    with pytest.raises(
        JdjProspectiveCalendarError,
        match="^JDJ_PROSPECTIVE_CALENDAR_INVALID$",
    ) as captured:
        assert_jdj_prospective_calendar(session)
    assert captured.value.__cause__ is None


@pytest.mark.parametrize("missing_day", [item[0] for item in _EXPECTED[:3]])
def test_missing_required_calendar_day_fails_closed(
    session: Session,
    missing_day: date,
) -> None:
    session.execute(
        delete(TradingCalendar).where(
            TradingCalendar.trade_date == missing_day
        )
    )
    session.commit()

    with pytest.raises(
        JdjProspectiveCalendarError,
        match="^JDJ_PROSPECTIVE_CALENDAR_INVALID$",
    ):
        assert_jdj_prospective_calendar(session)


@pytest.mark.parametrize("trade_date", [item[0] for item in _EXPECTED])
def test_conflicting_calendar_eligibility_fails_closed(
    session: Session,
    trade_date: date,
) -> None:
    row = session.scalar(
        select(TradingCalendar).where(
            TradingCalendar.trade_date == trade_date
        )
    )
    assert row is not None
    row.is_trading_day = not row.is_trading_day
    session.commit()

    with pytest.raises(
        JdjProspectiveCalendarError,
        match="^JDJ_PROSPECTIVE_CALENDAR_INVALID$",
    ):
        assert_jdj_prospective_calendar(session)


def test_missing_or_duplicate_active_jm_identity_fails_closed(
    session: Session,
) -> None:
    instrument = session.scalar(
        select(Instrument).where(Instrument.symbol == "jm")
    )
    assert instrument is not None
    instrument.is_active = False
    session.commit()

    with pytest.raises(JdjProspectiveCalendarError):
        assert_jdj_prospective_calendar(session)

    duplicate_session = _FakeSession(
        instruments=(
            Instrument(
                symbol="jm",
                name="JM",
                exchange_code="DCE",
                is_active=True,
            ),
            Instrument(
                symbol="jm",
                name="JM duplicate",
                exchange_code="DCE",
                is_active=True,
            ),
        ),
        calendars=(),
    )
    with pytest.raises(JdjProspectiveCalendarError):
        assert_jdj_prospective_calendar(duplicate_session)  # type: ignore[arg-type]


def test_duplicate_or_conflicting_calendar_fact_fails_closed() -> None:
    instrument = Instrument(
        symbol="jm",
        name="JM",
        exchange_code="DCE",
        is_active=True,
    )
    calendars = tuple(
        TradingCalendar(
            exchange_code="DCE",
            trade_date=trade_date,
            is_trading_day=is_trading_day,
        )
        for trade_date, is_trading_day in _EXPECTED
    )
    conflicting = TradingCalendar(
        exchange_code="DCE",
        trade_date=date(2026, 8, 24),
        is_trading_day=False,
    )

    with pytest.raises(JdjProspectiveCalendarError):
        assert_jdj_prospective_calendar(  # type: ignore[arg-type]
            _FakeSession(
                instruments=(instrument,),
                calendars=(*calendars, conflicting),
            )
        )


class _Scalars:
    def __init__(self, values: tuple[object, ...]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return list(self._values)


class _FakeSession:
    def __init__(
        self,
        *,
        instruments: tuple[Instrument, ...],
        calendars: tuple[TradingCalendar, ...],
    ) -> None:
        self._results = [instruments, calendars]

    def scalars(self, _statement: object) -> _Scalars:
        return _Scalars(self._results.pop(0))
