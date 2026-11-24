from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from lms405_counter_m_study import first_breach, subsequent_confirmation


@pytest.mark.parametrize("side, previous, following", [("LONG", "99", "101"), ("SHORT", "101", "99")])
def test_strict_breach_ignores_equality_and_tests_both_sides(side, previous, following):
    earliest, equal, final = (datetime.fromisoformat(f"2026-10-23T09:0{i}+08:00") for i in range(1, 4))
    bars = [SimpleNamespace(end=at, close=Decimal(close))
            for at, close in [(earliest, previous), (equal, "100"), (final, following)]]
    assert first_breach(bars, field="close", level=Decimal(100), side=side) == final
    assert first_breach(bars[:-1], field="close", level=Decimal(100), side=side) is None


def test_ordering_excludes_same_instant_and_distinguishes_reentry_inside_boundary():
    times = [datetime.fromisoformat(f"2026-10-23T09:{minute:02}+08:00")
             for minute in (5, 10, 11, 15, 16)]
    earlier, breach, allow_prior, fresh, confirm_fresh = times
    shapes = [dict(shape_at=shape.isoformat(), fast_at=confirm.isoformat(), level="98")
              for shape, confirm in [(earlier, breach), (breach, allow_prior), (fresh, confirm_fresh)]]
    kwargs = dict(quotes={breach: (Decimal(101), earlier), allow_prior: (Decimal(101), earlier),
                          confirm_fresh: (Decimal(99), fresh)},
                  level=Decimal(100), side="LONG")
    assert subsequent_confirmation(shapes[:1], breach, "fast_at", shape_close_after_breach=False, **kwargs) is None
    assert subsequent_confirmation(shapes[:2], breach, "fast_at", shape_close_after_breach=True, **kwargs) is None
    older = subsequent_confirmation(shapes, breach, "fast_at", shape_close_after_breach=False, **kwargs)
    newer = subsequent_confirmation(shapes, breach, "fast_at", shape_close_after_breach=True, **kwargs)
    assert (older["confirmation_at"], older["close_beyond_price_endpoint"]) == (allow_prior.isoformat(timespec="minutes"), True)
    assert (newer["confirmation_at"], newer["close_beyond_price_endpoint"]) == (confirm_fresh.isoformat(timespec="minutes"), False)
    assert older["uninterrupted_minute_coverage"] and not newer["uninterrupted_minute_coverage"]
