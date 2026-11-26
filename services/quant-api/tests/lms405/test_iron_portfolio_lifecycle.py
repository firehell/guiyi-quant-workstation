from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Bar
from lms405_iron_portfolio_lifecycle import CONTRACT, START, branch, table_counts
from lms405_right_side_study import ONE, US, at


def test_footer_matches_table_scope_and_rejects_unaccounted_lots():
    table = {"contracts": {CONTRACT: {"legs": {"short": {"quantity": 16}}}}}
    footer = {"row_count": 2, "total_lots": 26, "other_legs": {"J2701": {"long": 10}}}
    assert table_counts(table, footer) == {(CONTRACT, "short"): 16, ("J2701", "long"): 10}
    with pytest.raises(ValueError, match="IRON_LIFECYCLE_TABLE_FOOTER_MISMATCH"):
        table_counts(table, footer | {"total_lots": 42})


def test_quote_before_and_inside_minute_are_separate_and_same_average_needs_later_price():
    minutes = [Bar(CONTRACT, START + (offset + 1) * ONE, *(Decimal(price),) * 4, start=START + offset * ONE)
               for offset, price in enumerate((664, 664, 662, 662))]
    quotes = [START + 3 * ONE, START + 4 * ONE]
    observed = {"short": {"quantity": 16}}
    args = dict(known_at=START + 2 * ONE + US, seed_at=at("2026-10-27T15:17"), minutes=minutes,
                quotes=quotes, partial=quotes[-1:], tick=Decimal(1), totals=(664 * 16,))
    actual = branch("test", observed, test_permission=True, **args)
    assert actual["compatible_visible_short_before_quote"] == 2
    assert actual["compatible_if_same_complete_table_scope_and_quote_sync_before_quote"] == 1
    assert actual["quotes"][0]["START_EXCLUSIVE"]["long"] == 16
    assert actual["quotes"][0]["END_EXCLUSIVE"]["long"] == 0
    assert not any(actual["same_average_rebuild_price_sensitivity"].values())
    unknown = branch("public", observed, test_permission=False, **args)
    assert unknown["ending"]["protected_long"] == 16
    assert unknown["same_average_rebuild_price_sensitivity"] is None
