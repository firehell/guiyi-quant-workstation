from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Bar
from lms405_protection_zone_order import after_confirmation_bounds, check_frozen_prior, zone_order


BASE = datetime.fromisoformat("2026-06-03T10:30:00+08:00")
US = timedelta(microseconds=1)


def bar(minute, low, high, close):
    end = BASE + timedelta(minutes=minute)
    return Bar("OI2609", end, Decimal(close), Decimal(high), Decimal(low),
               Decimal(close), start=end - timedelta(minutes=1))


def timeline(*minutes, close, bounds=(Decimal(10175), Decimal(10197))):
    event = dict(shape_end=minutes[-2].end, confirmed_at=minutes[-1].end,
                 available_at=minutes[-1].end + US, close=Decimal(close))
    (row,), contacts = zone_order(
        minutes, [event], bounds=bounds, shape_minutes=1,
        start=minutes[0].start, as_of=minutes[-1].end + 2 * US,
    )
    return row, contacts


def test_already_touched_and_confirmation_inside_can_disagree_at_same_minute_boundary():
    setup, shape, confirmation = (
        bar(1, 10185, 10202, 10197), bar(2, 10180, 10194, 10192), bar(3, 10172, 10194, 10177),
    )
    row, contacts = timeline(setup, shape, confirmation, close=10177)
    assert contacts[0] == setup.end == row["shape_start"]
    assert row["contact_ending_at_shape_start"]
    assert not row["before_shape_policy"]
    assert row["close_inside_policy"]


def test_same_session_touch_and_close_outside_and_absent_zone():
    touched = bar(1, 10170, 10193, 10188)
    missed = bar(2, 10166, 10173, 10171)
    shape = bar(3, 10166, 10172, 10169)
    confirmation = bar(4, 10162, 10173, 10164)
    row, _ = timeline(touched, missed, shape, confirmation, close=10164)
    assert row["before_shape_policy"] and not row["close_inside_policy"]
    assert row["confirmation_close_relation"] == "BELOW"
    row, _ = timeline(touched, bar(15, 10162, 10171, 10165),
                      bar(16, 10161, 10169, 10164), close=10164)
    assert row["prior_contact_at"] == touched.end
    assert not row["before_shape_policy"]
    missing, _ = timeline(touched, missed, shape, confirmation, close=10164, bounds=None)
    assert missing["before_shape_policy"] is missing["close_inside_policy"] is None


def test_snapshot_price_envelope_starts_at_the_next_minute_and_keeps_empty_unknown():
    signal, next_bar, later = (bar(1, 10175, 10192, 10180), bar(2, 10182, 10190, 10182),
                              bar(3, 10195, 10201, 10200))
    minutes = [signal, next_bar, later]
    result = after_confirmation_bounds(minutes, after=signal.end, cutoff=later.end,
                                       average=Decimal(10180))
    assert result == dict(count=1, low=Decimal(10182), high=Decimal(10190), compatible=False)
    empty = after_confirmation_bounds(minutes, after=signal.end, cutoff=next_bar.end,
                                      average=Decimal(10180))
    assert empty == dict(count=0, low=None, high=None, compatible=None)


def test_all_frozen_periods_and_event_fields_are_checked():
    shape, confirm = bar(1, 10175, 10192, 10180), bar(2, 10176, 10190, 10181)
    event = dict(shape_end=shape.end, confirmed_at=confirm.end, available_at=confirm.end + US,
                 close=confirm.close, boundary=shape.high, ibar=True, pinbar=None)
    raw_event = {key: str(value) if isinstance(value, (Decimal, datetime)) else value
                 for key, value in event.items()}
    hashes = {"1m": "minute", "5m": "five", "15m": "quarter"}
    frozen = dict(market={key: {"sha256": value} for key, value in hashes.items()}, band=None,
                  hypotheses={"1m_to_1m": {"events": [raw_event]}})
    actual = dict(market=hashes, variants={"1m_to_1m": {"events": [event]}})
    check_frozen_prior(frozen, actual, band=None)
    with pytest.raises(ValueError, match="FROZEN_ZONE_ORDER_INPUT_CHANGED"):
        check_frozen_prior(frozen, actual | {"market": hashes | {"15m": "changed"}}, band=None)
    with pytest.raises(ValueError, match="FROZEN_GEOMETRY_EVENT_CHANGED"):
        check_frozen_prior(frozen, actual | {"variants": {"1m_to_1m": {"events": [event | {"ibar": False}]}}},
                           band=None)
