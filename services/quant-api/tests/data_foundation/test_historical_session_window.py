"""Real metadata adapter coverage proves both Session replacement boundaries."""
from dataclasses import replace
from datetime import date, time, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data.metadata import MetadataSynchronizer
from app.market_data.rqdata_adapter import RQDataClient, RQDataMarketAdapter
from app.models import Contract, Exchange, Instrument, MainContractMap, TradingCalendar, TradingSession

LOWER = date(2023, 1, 3)
UPPER = date(2023, 1, 9)
FLOOR = date(2023, 1, 1)
FUTURE = date(2023, 1, 10)
WARMUP = date(2022, 5, 19)


def _days(start, end):
    return tuple(start + timedelta(days=n) for n in range((end - start).days + 1))


def _row(day, *, name='existing', end=None):
    return TradingSession(exchange_code='DCE', instrument_symbol='a', session_name=name,
        start_time=time(9), end_time=time(15), effective_from=day,
        effective_to=day if end is None else end, is_active=True, provider='rqdata')


def _state(db):
    return {model.__tablename__: tuple(tuple(getattr(row, column.name)
        for column in model.__table__.columns) for row in db.scalars(select(model).order_by(model.id)))
        for model in (Exchange, Instrument, Contract, TradingCalendar, TradingSession, MainContractMap)}


@pytest.fixture
def authority():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Exchange(code='DCE', name='original'),
            Instrument(symbol='a', name='original', exchange_code='DCE', is_active=True),
            Contract(contract_code='A2305', instrument_symbol='a', exchange_code='DCE',
                listed_date=date(2022, 5, 1), expired_date=date(2023, 5, 15), provider='rqdata'),
            _row(WARMUP), _row(FUTURE)])
        for day in _days(date(2022, 12, 1), UPPER + timedelta(days=7)):
            db.add(TradingCalendar(exchange_code='DCE', trade_date=day,
                is_trading_day=day.weekday() < 5, has_night_session=False, provider='rqdata'))
        for day in _days(LOWER, UPPER):
            if day.weekday() < 5:
                db.add_all([MainContractMap(symbol='a', trade_date=day, contract_code='A2305'), _row(day)])
        db.commit()
        yield db
    engine.dispose()


class _Api:
    periods = '09:01-10:15,10:31-11:30,13:31-15:00'

    def __init__(self):
        self.futures = self
        self.dominant_calls = []

    def all_instruments(self, *, type):
        assert type == 'Future'
        return pd.DataFrame([{'underlying_symbol': 'A', 'exchange': 'DCE',
            'order_book_id': 'A2305', 'symbol': 'A2305', 'listed_date': '2022-05-01',
            'de_listed_date': '2023-05-15'}])

    def get_trading_dates(self, *, start_date, end_date):
        return tuple(day for day in _days(start_date, end_date) if day.weekday() < 5)

    def get_dominant(self, symbol, *, start_date, end_date, rule, rank):
        assert symbol == 'A' and rule == 2 and rank == 1
        self.dominant_calls.append((symbol, start_date, end_date))
        return pd.DataFrame([{'date': day, 'dominant': 'A2305'}
            for day in _days(start_date, end_date) if day.weekday() < 5])

    def get_trading_periods(self, contracts, *, start_date, end_date, frequency):
        assert contracts == ('A2305',) and frequency == '1m'
        return pd.DataFrame([{'order_book_id': 'A2305', 'date': day,
            'trading_hours': self.periods}
            for day in _days(start_date, end_date) if day.weekday() < 5])


def _synchronizer(db, mutate=lambda snapshot: snapshot, *, periods=None):
    api = _Api()
    if periods is not None:
        api.periods = periods
    client = object.__new__(RQDataClient)
    client.api = api
    snapshots = []
    requested = []
    real_snapshot = client.metadata_snapshot

    def capture(products, through, starts):
        requested.append((products, through, dict(starts)))
        snapshot = real_snapshot(products, through, starts)
        snapshots.append(snapshot)
        return mutate(snapshot)

    client.metadata_snapshot = capture
    adapter = RQDataMarketAdapter(session=db, client=client)
    return MetadataSynchronizer(adapter, MarketCatalog(db, Path('/private/tmp'))), api, requested, snapshots


def test_real_adapter_preserves_warmup_and_future_outside_its_proven_window(authority):
    db = authority
    before = _state(db)['trading_sessions']
    sync, api, requested, snapshots = _synchronizer(db)
    sync.synchronize(('a',), UPPER, {'a': FLOOR})
    assert requested == [(('a',), UPPER, {'a': LOWER})]
    assert api.dominant_calls == [('A', LOWER, UPPER)]
    assert snapshots[0].main_contract_starts == {'a': LOWER}
    after = _state(db)['trading_sessions']
    assert before[0] in after and before[1] in after
    rows = tuple(db.scalars(select(TradingSession).where(TradingSession.effective_from == LOWER)))
    assert [(row.start_time, row.end_time) for row in rows] == [
        (time(9), time(10, 15)), (time(10, 30), time(11, 30)), (time(13, 30), time(15))]
    # Legitimate previous-month and through+7 Calendar context is not rejected.
    assert min(row['trade_date'] for row in snapshots[0].calendars) == date(2022, 12, 1)
    assert max(row['trade_date'] for row in snapshots[0].calendars) == date(2023, 1, 16)


def test_real_adapter_accepts_multiple_day_and_cross_midnight_sessions(authority):
    for calendar in authority.scalars(select(TradingCalendar).where(
        TradingCalendar.trade_date >= LOWER, TradingCalendar.trade_date <= UPPER,
        TradingCalendar.is_trading_day.is_(True),
    )):
        calendar.has_night_session = True
    authority.commit()
    sync, *_ = _synchronizer(authority,
        periods='21:01-02:30,09:01-10:15,10:31-11:30,13:31-15:00')
    sync.synchronize(('a',), UPPER, {'a': FLOOR})
    rows = tuple(authority.scalars(select(TradingSession).where(
        TradingSession.effective_from == LOWER).order_by(TradingSession.start_time)))
    assert len(rows) == 4
    assert (rows[-1].start_time, rows[-1].end_time, rows[-1].crosses_midnight) == (
        time(21), time(2, 30), True)


def _fault(snapshot, fault):
    if fault == 'missing_bound':
        return replace(snapshot, main_contract_starts={})
    if fault == 'lower_before_floor':
        return replace(snapshot, main_contract_starts={'a': date(2022, 12, 30)})
    if fault == 'lower_after_upper':
        return replace(snapshot, main_contract_starts={'a': FUTURE})
    if fault in ('missing_calendar', 'missing_weekend_calendar'):
        missing = date(2023, 1, 4) if fault == 'missing_calendar' else date(2023, 1, 7)
        return replace(snapshot, calendars=tuple(r for r in snapshot.calendars if r['trade_date'] != missing))
    if fault == 'duplicate_calendar':
        row = next(r for r in snapshot.calendars if r['trade_date'] == LOWER)
        return replace(snapshot, calendars=(*snapshot.calendars, row))
    if fault in ('calendar_not_bool', 'calendar_provider'):
        field, value = ('is_trading_day', 1) if fault == 'calendar_not_bool' else ('provider', 'other')
        return replace(snapshot, calendars=tuple({**r, field: value} if r['trade_date'] == LOWER else r for r in snapshot.calendars))
    if fault == 'missing_map':
        return replace(snapshot, main_contracts=tuple(r for r in snapshot.main_contracts if r[1] != date(2023, 1, 4)))
    if fault == 'duplicate_map':
        return replace(snapshot, main_contracts=(*snapshot.main_contracts, snapshot.main_contracts[0]))
    if fault == 'wrong_map_symbol':
        return replace(snapshot, main_contracts=(('jm', LOWER, 'JM2305'), *snapshot.main_contracts[1:]))
    if fault == 'wrong_map_contract':
        return replace(snapshot, main_contracts=(('a', LOWER, 'JM2305'), *snapshot.main_contracts[1:]))
    if fault == 'empty_sessions':
        return replace(snapshot, sessions=())
    if fault == 'missing_session_day':
        return replace(snapshot, sessions=tuple(r for r in snapshot.sessions if r['effective_from'] != date(2023, 1, 4)))
    if fault == 'session_before_lower':
        return replace(snapshot, sessions=(*snapshot.sessions,
            {**snapshot.sessions[0], 'effective_from': WARMUP, 'effective_to': WARMUP}))
    if fault == 'duplicate_session':
        return replace(snapshot, sessions=(*snapshot.sessions, snapshot.sessions[0]))
    if fault == 'overlap_session':
        return replace(snapshot, sessions=(*snapshot.sessions,
            {**snapshot.sessions[0], 'session_name': 'overlap', 'start_time': time(9, 30), 'end_time': time(10)}))
    raise AssertionError(fault)


@pytest.mark.parametrize('fault', [
    'missing_bound', 'lower_before_floor', 'lower_after_upper', 'missing_calendar',
    'missing_weekend_calendar', 'duplicate_calendar', 'calendar_not_bool', 'calendar_provider',
    'missing_map', 'duplicate_map', 'wrong_map_symbol', 'wrong_map_contract',
    'empty_sessions', 'missing_session_day', 'session_before_lower', 'duplicate_session', 'overlap_session',
])
def test_unproven_window_rolls_back_every_metadata_table(authority, fault):
    before = _state(authority)
    sync, *_ = _synchronizer(authority, lambda snapshot: _fault(snapshot, fault))
    with pytest.raises(ValueError, match='HISTORICAL_SESSION_REPLACEMENT_UNPROVEN'):
        sync.synchronize(('a',), UPPER, {'a': FLOOR})
    assert _state(authority) == before


@pytest.mark.parametrize(('start', 'end'), [
    (date(2022, 12, 30), LOWER), (date(2022, 12, 30), date(2023, 1, 4)),
])
def test_template_crossing_lower_boundary_is_not_deleted(authority, start, end):
    authority.add(_row(start, name='lower-crossing', end=end))
    authority.commit()
    before = _state(authority)
    sync, *_ = _synchronizer(authority)
    with pytest.raises(ValueError, match='HISTORICAL_SESSION_REPLACEMENT_UNPROVEN'):
        sync.synchronize(('a',), UPPER, {'a': FLOOR})
    assert _state(authority) == before


def test_finite_template_wholly_before_lower_boundary_is_preserved(authority):
    authority.add(_row(date(2022, 12, 20), name='old-range', end=date(2022, 12, 30)))
    authority.commit()
    before = _state(authority)['trading_sessions'][-1]
    sync, *_ = _synchronizer(authority)
    sync.synchronize(('a',), UPPER, {'a': FLOOR})
    assert before in _state(authority)['trading_sessions']
