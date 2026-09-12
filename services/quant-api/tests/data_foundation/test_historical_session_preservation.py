"""Historical replacement must not erase bounded next-trading-day preparation."""
from dataclasses import replace
from datetime import date, time, timedelta

import pytest
from sqlalchemy import delete, select

from app.market_data.historical_data_manager import RefreshRequest, UpdateRequest
from app.market_data.metadata import MetadataSnapshot, MetadataSynchronizer
from app.models import MainContractMap, TradingCalendar, TradingSession
from tests.data_foundation.test_daily_maintenance import daily_manager  # noqa: F401
from tests.data_foundation.test_historical_data_manager import session  # noqa: F401


class _MetadataAdapter:
    def __init__(self, db):
        day, next_day = date(2025, 3, 7), date(2025, 3, 10)
        session_values = tuple({
            field: getattr(row, field) for field in (
                'exchange_code', 'instrument_symbol', 'session_name', 'start_time',
                'end_time', 'crosses_midnight', 'effective_from', 'effective_to',
                'is_active', 'provider',
            )
        } for row in db.scalars(select(TradingSession).where(
            TradingSession.instrument_symbol == 'jm', TradingSession.effective_from <= day,
        )))
        maps = tuple((row.symbol, row.trade_date, row.contract_code)
                     for row in db.scalars(select(MainContractMap).where(
                         MainContractMap.symbol == 'jm', MainContractMap.trade_date <= day,
                     )))
        calendars = tuple({**{field: getattr(row, field) for field in (
            'exchange_code', 'trade_date', 'is_trading_day', 'provider',
        )}, 'has_night_session': False if (
            not row.is_trading_day or row.trade_date >= date(2025, 1, 1)
        ) else None, 'night_session_products': ('jm',)}
        for row in db.scalars(select(TradingCalendar).where(
            TradingCalendar.exchange_code == 'DCE', TradingCalendar.trade_date <= day,
        )))
        self.historical = MetadataSnapshot((), (), (), calendars, session_values, maps,
                                            {'jm': date(2025, 1, 1)})
        self.current = MetadataSnapshot((), (), (), tuple({
            'exchange_code': 'DCE', 'trade_date': day + timedelta(days=n),
            'is_trading_day': n in (0, 3), 'has_night_session': False,
            'provider': 'rqdata', 'night_session_products': ('jm',),
        } for n in range(4)), tuple({
            'exchange_code': 'DCE', 'instrument_symbol': 'jm', 'session_name': 'day',
            'start_time': time(9), 'end_time': time(9, 5), 'crosses_midnight': False,
            'effective_from': d, 'effective_to': d, 'is_active': True, 'provider': 'rqdata',
        } for d in (day, next_day)), (('jm', day, 'JM2509'),), {'jm': day})
        self.historical_calls = 0

    def fetch_metadata(self, products, through, starts):
        assert products == ('jm',) and through == date(2025, 3, 7)
        self.historical_calls += 1
        return self.historical

    def fetch_current_day_metadata(self, products, trading_day):
        assert products == ('jm',) and trading_day == date(2025, 3, 7)
        return self.current


def _session_facts(db):
    return tuple(tuple(getattr(row, column.name) for column in TradingSession.__table__.columns)
                 for row in db.scalars(select(TradingSession).order_by(TradingSession.id)))


@pytest.mark.parametrize('operation', ['full', 'refresh', 'daily'])
def test_maintenance_preserves_prepared_next_day_sessions(daily_manager, operation):  # noqa: F811
    manager = daily_manager
    db = manager.catalog.session
    adapter = _MetadataAdapter(db)
    manager.metadata = MetadataSynchronizer(adapter, manager.catalog)
    if operation != 'daily':
        # Real historical incompleteness triggers the production metadata fallback.
        db.execute(delete(TradingSession).where(
            TradingSession.effective_from == date(2025, 1, 1)))
        db.commit()
        assert not manager.coverage.metadata_complete(('jm',), date(2025, 3, 7))
    if operation == 'refresh':
        manager.metadata.synchronize_current_day(('jm',), date(2025, 3, 7))
        result = manager.refresh(RefreshRequest('jm', date(2025, 3, 7),
                                               date(2025, 3, 7), apply=True))
    else:
        result = manager.update(UpdateRequest(('jm',), None, date(2025, 3, 7),
            apply=True, sync_current_day_metadata=True, mode=operation))
    assert result.status == 'passed'
    db.expire_all()
    future = tuple(db.scalars(select(TradingSession).where(
        TradingSession.instrument_symbol == 'jm',
        TradingSession.effective_from == date(2025, 3, 10))))
    assert len(future) == 1
    assert (future[0].effective_to, future[0].start_time, future[0].end_time) == (
        date(2025, 3, 10), time(9), time(9, 5))
    assert adapter.historical_calls == (0 if operation == 'daily' else 1)


@pytest.mark.parametrize(('start', 'end'), [
    (date(2025, 3, 6), date(2025, 3, 10)),
    (date(2025, 3, 6), None),
    (date(2025, 3, 10), None),
    (date(2025, 3, 10), date(2025, 3, 11)),
])
def test_historical_sync_rejects_unbounded_future_templates_without_mutation(
    daily_manager, start, end,  # noqa: F811
):
    manager = daily_manager
    db = manager.catalog.session
    adapter = _MetadataAdapter(db)
    db.add(TradingSession(exchange_code='DCE', instrument_symbol='jm', session_name='legacy',
        start_time=time(9), end_time=time(15), effective_from=start, effective_to=end,
        is_active=True, provider='rqdata'))
    db.commit()
    before = _session_facts(db)
    sync = MetadataSynchronizer(adapter, manager.catalog)
    with pytest.raises(ValueError, match='HISTORICAL_SESSION_REPLACEMENT_UNPROVEN'):
        sync.synchronize(('jm',), date(2025, 3, 7), {'jm': date(2025, 1, 1)})
    assert _session_facts(db) == before


def test_historical_snapshot_cannot_overwrite_future_fact(daily_manager):  # noqa: F811
    manager = daily_manager
    db = manager.catalog.session
    adapter = _MetadataAdapter(db)
    sync = MetadataSynchronizer(adapter, manager.catalog)
    sync.synchronize_current_day(('jm',), date(2025, 3, 7))
    before = _session_facts(db)
    adapter.historical = replace(adapter.historical, sessions=(
        *adapter.historical.sessions,
        {**adapter.current.sessions[-1], 'end_time': time(15)},
    ))
    with pytest.raises(ValueError, match='HISTORICAL_SESSION_REPLACEMENT_UNPROVEN'):
        sync.synchronize(('jm',), date(2025, 3, 7), {'jm': date(2025, 1, 1)})
    assert _session_facts(db) == before
