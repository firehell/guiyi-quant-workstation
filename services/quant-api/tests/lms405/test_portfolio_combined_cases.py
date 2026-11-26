import pytest

from lms405_portfolio_combined_cases import source_alignment


def observed(side, checks):
    return dict(status="CHECKED", source="snapshot", side=side,
                by_variant={"strict_replay": {at: {"status": status} for at, status in checks.items()}})


def test_shared_quote_label_cannot_combine_different_minutes_or_unlisted_legs():
    earlier, later = "2026-10-22T22:08:00+08:00", "2026-10-22T22:09:00+08:00"
    matches = source_alignment({
        "SH2701": [observed("short", {earlier: "PRICE_COMPATIBLE"}),
                   dict(status="UNLISTED_UNKNOWN", source="snapshot", side="long")],
        "I2701": [observed("short", {earlier: "TRADING_DAY_DIFFERS", later: "PRICE_COMPATIBLE"})],
    })["snapshot"]
    assert matches["checked_legs"] == matches["independently_compatible_legs"] == 2
    assert matches["most_compatible_at_one_quote_label"] == 1
    assert matches["best_quote_labels"] == {earlier: [("SH2701", "short")], later: [("I2701", "short")]}


def test_shared_quote_label_rejects_duplicate_snapshot_legs():
    row = observed("short", {"2026-10-22T22:08:00+08:00": "PRICE_COMPATIBLE"})
    with pytest.raises(ValueError, match="COMBINED_REPEAT_SOURCE_LEG"):
        source_alignment({"I2701": [row, row]})
