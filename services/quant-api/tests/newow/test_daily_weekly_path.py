from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from guiyi_quant.newow.daily_weekly_path import build_daily_weekly_path
from guiyi_quant.newow.cross_period_prices import PriceSource

END = datetime(2026, 9, 24, 7, tzinfo=UTC)


def price(value, frequency="1d", category="canonical_channel"):
    return PriceSource(
        Decimal(value),
        frequency,
        END,
        "JM2701",
        "owner",
        frequency + "-calc",
        "source",
        category,
    )


def frame(frequency, value, signal_id, kind="BUILD", related=None):
    source = price(value, frequency, "canonical_strategy_build")
    bar = SimpleNamespace(
        bar_end=END,
        physical_contract="JM2701",
        segment_id="owner",
        source_identity="source",
        observation_eligible=True,
    )
    action = SimpleNamespace(
        kind=SimpleNamespace(value=kind),
        signal_id=signal_id,
        reference_price=Decimal(value),
        bar_end=END,
        physical_contract="JM2701",
        segment_id="owner",
        calculation_segment_id=frequency + "-calc",
        related_build_id=related,
    )
    return SimpleNamespace(
        bar=SimpleNamespace(
            bar=bar, calculation_segment_id=source.calculation_segment_id
        ),
        actions=(action,),
    )


def build(**overrides):
    args = dict(
        as_of=END,
        current=price("110", category="canonical_completed_close"),
        periods={
            "1d": ("hold", [frame("1d", "101", "daily-entry")], price("125")),
            "1w": ("hold", [frame("1w", "90", "weekly-entry")], price("160", "1w")),
        },
    )
    args.update(overrides)
    return build_daily_weekly_path(**args)


def test_daily_weekly_cost_and_target_are_independent_with_exact_marker_provenance():
    result = build()
    week, day = result["periods"]
    assert day["cost"]["raw"] == "101"
    assert week["cost"]["raw"] == "90"
    assert day["cost"]["entry_marker_id"] == "daily-entry"
    assert day["target"]["raw"] == "125"
    assert week["target"]["raw"] == "160"
    assert result["page_parity"] is True and result["executable"] is False


def test_flat_or_missing_period_does_not_fabricate_entry_or_reuse_other_period():
    result = build(
        periods={
            "1d": ("wait", [frame("1d", "101", "entry")], price("125")),
            "1w": (None, [], None),
        }
    )
    week, day = result["periods"]
    assert day["state"] == "wait" and day["cost"] is None
    assert day["reason"] == "FLAT_NO_OPEN_ENTRY"
    assert week["status"] == "unavailable" and week["current"] is None


def test_clear_uses_related_identity_and_missing_build_is_explicit():
    frames = [frame("1d", "101", "entry"), frame("1d", "120", "exit", "CLEAR", "entry")]
    result = build(periods={"1d": ("hold", frames, price("125"))})
    assert result["periods"][1]["cost"] is None
    assert result["periods"][1]["reason"] == "OPEN_ENTRY_UNAVAILABLE"


@pytest.mark.parametrize(
    "field,value",
    [
        ("physical_contract", "JM2610"),
        ("segment_id", "old"),
        ("calculation_segment_id", "old-calc"),
        ("bar_end", END + timedelta(days=1)),
    ],
)
def test_invalid_target_fails_closed(field, value):
    bad = replace(price("125"), **{field: value})
    result = build(periods={"1d": ("hold", [frame("1d", "101", "entry")], bad)})
    assert result["periods"][1]["target"] is None
    assert result["periods"][1]["status"] == "partial"


def test_entry_from_other_calculation_or_owner_does_not_become_cost():
    foreign = frame("1d", "101", "entry")
    foreign.actions[0].segment_id = "foreign"
    result = build(periods={"1d": ("hold", [foreign], price("125"))})
    assert result["periods"][1]["cost"] is None


def test_current_before_entry_or_wrong_source_family_cannot_draw_completed_path():
    earlier = replace(
        price("110", category="canonical_completed_close"),
        bar_end=END - timedelta(days=1),
    )
    result = build(current=earlier)
    assert result["periods"][1]["cost"] is None
    wrong_target = replace(price("125"), source_category="page_batch")
    result = build(
        periods={"1d": ("hold", [frame("1d", "101", "entry")], wrong_target)}
    )
    assert result["periods"][1]["target"] is None
