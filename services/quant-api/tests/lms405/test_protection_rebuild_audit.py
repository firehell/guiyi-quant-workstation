from datetime import timedelta
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Bar, Position
from lms405_protection_rebuild_audit import SH, START, fixture_event, projection


def test_equal_quantities_require_a_new_protection_leg_to_explain_today_field():
    one = timedelta(minutes=1)
    qty = Decimal(20)
    old = Position(SH, qty, qty)
    released = fixture_event(SH, "UNLOCK_SHORT", qty, START - one, source="test")
    relocked = fixture_event(SH, "LOCK", qty, START + one, source="test")
    first, second = START + one, START + 2 * one
    mark = Decimal("1492.0")
    bars = [Bar(SH, end, mark, mark, mark, mark, start=end - one) for end in (first, second, second + one)]
    observed = {"long": {"quantity": 20, "today_quantity": 20}, "short": {"quantity": 20, "today_quantity": 0}}
    args = (tuple(b.end for b in bars), bars, Decimal(1), observed, mark)

    kept = projection(old, (), *args)
    assert kept["compatible_quotes"] == 0
    assert all(x["both_quantities_match"] for x in kept["quote_checks"].values())

    replaced = projection(old, (released, relocked), *args)
    assert replaced["compatible_quotes"] == 1
    assert not replaced["quote_checks"][first.isoformat()]["both_quantities_match"]
    assert not replaced["quote_checks"][second.isoformat()]["compatible"]
    assert replaced["quote_checks"][(second + one).isoformat()]["compatible"]

    with pytest.raises(ValueError, match="ACTION_STATE_CONFLICT"):
        projection(old, (relocked,), *args)
