from dataclasses import replace
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms405.portfolio_tasks import Book
from guiyi_quant.lms405.protection_band import ProtectionBandUpdate
from lms405_jm_first_lock_chain import CONTRACT, NIGHT_START, PROTECTION, protection_events_15m, retention_sensitivity
from lms405_right_side_study import ONE, US


def test_fifteen_minute_candidate_is_bound_to_published_revision_and_visible_after_confirmation():
    start = NIGHT_START
    period = 15 * ONE
    fives = [
        Bar(CONTRACT, start + (i + 1) * period, *map(Decimal, ohlc), start=start + i * period)
        for i, ohlc in enumerate(((1388, 1395, 1380, 1390), (1390, 1393, 1386, 1390), (1390, 1396, 1387, 1396)))
    ]
    minutes = [Bar(CONTRACT, start + (i + 1) * ONE, *map(Decimal, (1390, 1396, 1387, 1390)), start=start + i * ONE)
               for i in range(45)]
    tape = {1: minutes, 15: fives}
    known = start - ONE
    band = ProtectionBandUpdate(CONTRACT, PROTECTION, "PROTECTION", known, known, "example", "SHORT",
                                Decimal("1382.5"), Decimal("1397.5"))
    confirm = fives[-1]
    assert protection_events_15m(tape, [band], confirm.end + 6 * US) == []
    event, = protection_events_15m(tape, [band], confirm.end + 7 * US)
    assert event["confirmation_period"] == 15
    assert event["signal"]["confirmed_at"] == confirm.end
    assert protection_events_15m(tape, [replace(band, revision="replacement")], confirm.end + 7 * US) == []
    with pytest.raises(ValueError, match="JM_FIRST_PROTECTION_CONTRACT_MISMATCH"):
        protection_events_15m({1: [replace(minutes[0], contract="JM2609")], 15: fives},
                              [band], confirm.end + 7 * US)


def test_retention_sensitivity_scopes_variant_to_the_focal_original_short():
    book = Book(CONTRACT, "original", "SHORT", NIGHT_START)
    assert not retention_sensitivity(book, None, None, None)["admitted"]
    assert retention_sensitivity(replace(book, direction="LONG"), None, None, None)["admitted"]
    assert retention_sensitivity(replace(book, contract="I2701"), None, None, None)["admitted"]
