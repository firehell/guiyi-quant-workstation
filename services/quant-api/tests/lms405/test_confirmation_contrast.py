from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Bar
from lms405_protection_timeframes import confirmation_contrast


def test_excursion_close_and_reset_appear_only_at_their_own_knowledge_times():
    start = datetime(2026, 10, 22, 12, tzinfo=UTC)
    minute, us = timedelta(minutes=1), timedelta(microseconds=1)

    def bar(offset, step, prices):
        left = start + offset * minute
        return Bar("JM2701", left + step * minute, *map(Decimal, prices), start=left)

    series = {
        5: [bar(0, 5, (100, 107, 98, 104)), bar(5, 5, (103, 105, 100, 103))],
        1: [bar(10, 1, (103, 107, 102, 105)), bar(11, 1, (105, 108, 104, 106)),
            bar(12, 1, (106, 107, 104, 105))],
    }
    excursion = start + 11 * minute + us
    close = start + 12 * minute + us
    reset = start + 13 * minute + us

    def as_of(when):
        return confirmation_contrast(series, 5, 1, start=start, as_of=when, side="LONG")

    assert as_of(excursion) == []
    (first,) = as_of(close)
    assert first["excursion_known_at"] == excursion and not first["excursion_bar_closes_beyond"]
    assert first["strict_close_known_at"] is None
    (confirmed,) = as_of(reset)
    assert confirmed["strict_close_known_at"] == close and confirmed["reset_known_at"] is None
    (returned,) = as_of(reset + us)
    assert returned["reset_known_at"] == reset
    series[1][-1] = replace(series[1][-1], contract="SH2701")
    with pytest.raises(ValueError, match="RESET_BAR_IDENTITY_MISMATCH"):
        as_of(reset + us)
