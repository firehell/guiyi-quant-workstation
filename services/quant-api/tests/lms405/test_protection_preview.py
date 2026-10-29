import json
from pathlib import Path

import pytest

from lms_protection_proposal_replay import (
    build_report,
    preview_states,
    render_html,
    write_report,
)
from test_protection_proposals import bar

ROOT = Path(__file__).resolve().parents[4]
INPUT = (
    ROOT
    / "output/lms405-jm2509-july22-20261017/market-read-authorized/JM2509_2025-07-21_2025-07-22_5m.csv"
)


def test_four_static_states_not_a_position_chain_and_repeatable():
    r = build_report(INPUT)
    assert r == build_report(INPUT)
    assert r["input_mode"] == "FOUR_INDEPENDENT_STATIC_STATE_SCENARIOS"
    assert r["policy_version"] == "lms-protection-proposal-v1"
    assert len(r["scenarios"]) == 4
    for s in r["scenarios"]:
        assert len(s["evaluations"]) == 27
        assert all(
            e["unit_position_before"] == s["unit_position"] for e in s["evaluations"]
        )
        assert all(
            e["requires_human_confirmation"] is True and e["executable"] is False
            for e in s["evaluations"]
        )
    assert r["author_action_match_rate"] is r["fill"] is r["performance"] is None
    assert r["executable"] is False
    assert r["keybar_report"]["local_pattern_counts"] == {
        "ibar": 21,
        "pinbar_long": 5,
        "pinbar_short": 2,
    }


def test_preview_prefix_and_streamed_reads_do_not_backfill_or_advance_state():
    xs = [bar(0, h="20", low="5"), bar(1), bar(2, "11", "16", "6", "7"), bar(3)]
    full = preview_states(xs)
    for n in range(1, len(xs) + 1):
        short = preview_states(xs[:n])
        for a, b in zip(short, full):
            assert a["unit_position"] == b["unit_position"]
            assert a["evaluations"] == [
                e
                for e in b["evaluations"]
                if e["available_after"] <= xs[n - 1].end.isoformat()
            ]


def test_preview_html_keeps_human_confirmation_and_counterfactual_scope_visible():
    r = build_report(INPUT)
    html = render_html(r, "<svg/>")
    assert "四个独立前像" in html and "人工确认" in html
    assert "不自动改变" in html and "不是成交" in html
    assert "LOCK" in html and "UNLOCK_LONG" in html and "UNLOCK_SHORT" in html
    assert "proposals.csv" in html and "report.json" in html
    assert json.loads(json.dumps(r)) == r


def test_refuse_existing_output_before_rendering(tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    marker = target / "keep"
    marker.write_text("UNCHANGED")
    with pytest.raises(FileExistsError):
        write_report(INPUT, target)
    assert marker.read_text() == "UNCHANGED" and list(target.iterdir()) == [marker]


def test_tampered_input_creates_no_preview(tmp_path):
    changed = tmp_path / "bad.csv"
    changed.write_bytes(INPUT.read_bytes() + b"\n")
    out = tmp_path / "new"
    with pytest.raises(ValueError, match="FROZEN_INPUT_HASH_MISMATCH"):
        write_report(changed, out)
    assert not out.exists()


def test_html_shows_signal_dates_to_distinguish_multi_day_rows():
    html = render_html(build_report(INPUT), "<svg/>")
    assert "07-22 09:10:00" in html
