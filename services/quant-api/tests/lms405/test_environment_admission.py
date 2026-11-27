from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms405.protection_band import ProtectionBandUpdate
from lms405_portfolio_environment_audit import (
    LOCAL,
    archived_chapter,
    context_before,
    known_and,
    opening_alternatives,
    range_revision_audit,
    resistance_context_before,
    short_target_progress,
)


def test_environment_cutoff_is_strict_before_for_both_full_and_prefix_input():
    start = datetime(2026, 10, 22, 12, tzinfo=UTC)
    step = timedelta(minutes=5)
    bars = [Bar("SH2701", start + i * step, *map(Decimal, (100 + i, 105 + i, 99 + i, 102 + i)),
                start=start + (i - 1) * step) for i in range(1, 10)]
    known = bars[5].end + timedelta(microseconds=1)
    assert context_before(bars, known) is None
    after = known + timedelta(microseconds=1)
    assert context_before(bars, after) == context_before(bars[:6], after)
    assert context_before(bars, after)["window_end"] == bars[5].end.isoformat()
    assert context_before(bars, after)["environment"] == "UP"


def test_two_consecutive_opening_labels_cannot_change_the_first_vote():
    items = [dict(author_class="DOWN", day_close={"environment": "DOWN"},
                  opening_clocks=[{"environment": value} for value in ("UP", "UP", "DOWN")])]
    scores = opening_alternatives(items)
    assert scores["ROLLING"]["first_agrees"] == 0
    assert scores["TWO_LOCAL_VOTES"]["first_agrees"] == 1
    assert scores["TWO_LOCAL_VOTES"]["cases_with_flip"] == 1
    assert scores["HOLD_DAY_CLOSE"]["all_agree"] == 1
    assert known_and(None, False) is False and known_and(False, None) is False
    assert known_and(True, None) is None


def test_resistance_requires_an_adjacent_completed_right_bar_and_drops_a_broken_high():
    start = datetime(2026, 10, 22, 12, tzinfo=UTC)
    step, us = timedelta(minutes=5), timedelta(microseconds=1)
    prices = ((102, 104, 101, 103), (103, 105, 102, 104), (104, 106, 103, 105),
              (105, 108, 104, 106), (106, 110, 105, 107), (107, 107, 104, 105), (105, 111, 104, 110))
    bars = [Bar("SH2701", start + (i + 1) * step, *map(Decimal, fields), start=start + i * step)
            for i, fields in enumerate(prices)]
    known = bars[5].end + us
    assert resistance_context_before(bars, known) is None
    band = resistance_context_before(bars, known + us)
    assert band == resistance_context_before(bars[:6], known + us)
    assert (band["lower"], band["upper"]) == (107, 110)
    assert band["pivot_end"] == bars[4].end and band["confirmed_at"] == known
    gap = bars[:5] + [replace(bars[5], start=bars[5].start + step, end=bars[5].end + step)]
    assert resistance_context_before(gap, gap[-1].end + 2 * us) is None
    assert resistance_context_before(bars, bars[-1].end + 2 * us) is None


def test_short_target_progress_keeps_gap_reach_separate_from_range_contact():
    start = datetime(2026, 10, 22, 12, tzinfo=UTC)
    step, us = timedelta(minutes=1), timedelta(microseconds=1)
    bars = [SimpleNamespace(bar_end=start + i * step, low=Decimal(low), high=Decimal(high), close=Decimal(close))
            for i, (low, high, close) in enumerate(((98, 99, 99), (99, 101, 100)), 1)]
    clock = bars[-1].bar_end + us
    first = short_target_progress(bars, clock, Decimal(98), Decimal(100))
    assert first["near"] == {"first_reach": bars[0].bar_end, "first_contact": None,
                             "first_close_below": bars[0].bar_end}
    assert first["far"]["first_reach"] == bars[0].bar_end and first["far"]["first_close_below"] is None
    assert short_target_progress(bars, clock + us, Decimal(98), Decimal(100))["near"][
        "first_contact"
    ] == bars[-1].bar_end


def test_revision_evidence_does_not_take_target_values_from_neighboring_contracts(tmp_path):
    archive = tmp_path / "archive.md"
    archive.write_text(
        "## 内容记录\n四章节读至结尾。LH空方9725。TA暂停。SH空方1543。RU空方19320—19420。\n",
        encoding="utf-8",
    )
    assert "1543" in archived_chapter(archive, "SH2701")
    assert "9725" not in archived_chapter(archive, "SH2701")
    assert "19320-19420" not in archived_chapter(archive, "SH2701")
    archive.write_text("## 内容记录\n|SH2701|空1543|\n|RU2701|空19320–19420|\n", encoding="utf-8")
    assert "1543" in archived_chapter(archive, "SH2701")
    assert "19320-19420" not in archived_chapter(archive, "SH2701")


def test_generated_ranges_update_and_frozen_boundary_never_recovers():
    start = datetime(2026, 10, 22, 21, tzinfo=LOCAL)
    step = timedelta(minutes=5)
    prices = [(100, 105, 99, 102)] * 6 + [(102, 106, 100, 105)] + [(103, 104, 101, 103)] * 6
    closes = [start - timedelta(hours=6) + (i - 5) * step for i in range(6)]
    closes.extend(start + i * step for i in range(1, 8))
    bars = [
        Bar("SH2701", end, *map(Decimal, values), start=end - step)
        for end, values in zip(closes, prices, strict=True)
    ]
    plan = ProtectionBandUpdate(
        "SH2701", "test-plan", "PROTECTION", start - step, start - step, "test-source", "SHORT",
        Decimal(102), Decimal(107),
    )
    report = range_revision_audit(bars, start.date(), plan, Decimal(1))
    assert report["frozen_at_open"]["upper"] == 105 and report["frozen_at_open"]["upper_error_ticks"] == -2
    assert report["frozen_at_open"]["overlap"] is True
    assert report["frozen_short_boundary_invalidated_at"] == bars[6].end + timedelta(microseconds=1)
    assert all(row["frozen_valid_for_short"] is False for row in report["checkpoints"])
    assert report["checkpoints"][0]["rolling"]["upper"] == Decimal(106)
    pending = ProtectionBandUpdate(
        "SH2701", "test-pending", "REVIEW_PENDING", start - step, start - step, "test-source", "SHORT",
    )
    unmatched = range_revision_audit(bars, start.date(), pending, Decimal(1))
    assert unmatched["frozen_at_open"]["upper"] == 105
    assert unmatched["frozen_at_open"]["upper_error_ticks"] is None
