from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from lms405_sh_oct_case import summarize_scopes


def stamp(s):
    return datetime.fromisoformat(s + '+08:00')


def bar(s, day, low):
    return SimpleNamespace(bar_end=stamp(s), trading_day=day,
                           high=Decimal(low) + 10, low=Decimal(low))


def window(start, end, night):
    return SimpleNamespace(is_night=night, name='catalog-session',
                           window=SimpleNamespace(start=stamp(start), end=stamp(end)))


def test_authoritative_night_day_and_publication_minute_are_separate():
    day = date(2026, 10, 27)
    sessions = {day: (window('2026-10-26T21:00', '2026-10-26T23:00', True),
                      window('2026-10-27T09:00', '2026-10-27T10:30', False))}
    bars = [bar('2026-10-26T21:01', day, '1475'),
            bar('2026-10-27T10:17', day, '1490'),
            bar('2026-10-27T10:18', day, '1480'),
            bar('2026-10-27T10:19', day, '1470')]
    r = summarize_scopes(bars, sessions, stamp('2026-10-27T10:18'))
    assert r['2026-10-27']['full_trading_day']['low'] == '1470'
    assert r['2026-10-27']['night']['low'] == '1475'
    assert r['2026-10-27']['day']['low'] == '1470'
    pre = r['2026-10-27']['completed_before_publication_minute']
    assert pre['bar_count'] == 2 and pre['low'] == '1475'
    assert pre['last_bar_end'] == stamp('2026-10-27T10:17').isoformat()
    assert pre['low_bar_ends'] == [stamp('2026-10-26T21:01').isoformat()]


def test_unassigned_or_wrong_trading_day_bar_fails_closed():
    day = date(2026, 10, 27)
    sessions = {day: (window('2026-10-27T09:00', '2026-10-27T10:30', False),)}
    for b in [bar('2026-10-27T09:00', day, '10'),
              bar('2026-10-27T09:01', day - timedelta(days=1), '10')]:
        with pytest.raises(ValueError, match='BAR_SESSION_IDENTITY_UNPROVEN'):
            summarize_scopes([b], sessions, stamp('2026-10-27T10:18'))
