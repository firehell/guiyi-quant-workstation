"""New candidate only; synthetic scenario decisions are never human evidence."""

from datetime import datetime, UTC, timedelta
from decimal import Decimal as D
from dataclasses import replace
import pytest
from guiyi_quant.lms405 import Bar
from guiyi_quant.lms_near405 import replay, context, VERSION

T = datetime(2025, 1, 1, tzinfo=UTC)
US = timedelta(microseconds=1)


def bar(i, o, h, low, c):
    t = T + timedelta(minutes=5 * i)
    return Bar(
        "JM2509", t + timedelta(minutes=5), *map(D, map(str, (o, h, low, c))), start=t
    )


def entry_bars():
    # RANGE [100,110], inside S in lower half then close confirms upward.
    return [bar(i, 104, 110, 100, 106) for i in range(6)] + [
        bar(6, 103, 105, 101, 104),
        bar(7, 104, 108, 102, 106),
    ]


def until(b):
    return b[-1].end + timedelta(microseconds=3)


def decision(p, **changes):
    t = datetime.fromisoformat(p["generated_at"]) + US
    return (
        dict(
            decision_id="fixture-1",
            proposal_id=p["proposal_id"],
            state_fingerprint=p["state_fingerprint"],
            decision="ACCEPT",
            decided_at=t.isoformat(),
            known_at=t.isoformat(),
            record_kind="TEST_FIXTURE",
        )
        | changes
    )


def test_warmup_then_entry_proposal_without_application():
    b = entry_bars()
    r = replay(b, as_of=until(b))
    assert VERSION == "lms-near405-v1"
    assert r["current_state"]["long"] == "0" and not r["transitions"]
    assert r["proposals"][-1]["action"] == "ENTER_LONG"
    assert r["evaluations"][-1]["environment"] == "RANGE"
    assert all(e["status"] == "WARMUP" for e in r["evaluations"][:-1])


def test_entry_exit_and_mirror_fixture():
    b = entry_bars() + [bar(8, 106, 109, 99, 100)]
    r = replay(b, as_of=until(b), timely_fixture=True)
    assert [t["action"] for t in r["transitions"]] == ["ENTER_LONG", "CLEAR"]
    assert r["proposals"][-1]["reason"] == "RISK_INVALID"
    assert r["current_state"]["long"] == r["current_state"]["short"] == "0"
    mirror = [
        replace(
            x,
            open=210 - x.open,
            high=210 - x.low,
            low=210 - x.high,
            close=210 - x.close,
        )
        for x in b
    ]
    r = replay(mirror, as_of=until(mirror), timely_fixture=True)
    assert [t["action"] for t in r["transitions"]] == ["ENTER_SHORT", "CLEAR"]


def test_confirmation_reject_expiry_and_duplicate():
    b = entry_bars()
    p = replay(b, as_of=until(b))["proposals"][0]
    d = decision(p)
    r = replay(b, [d, d], as_of=until(b))
    assert len(r["transitions"]) == 1
    r = replay(b, [d | {"decision": "REJECT"}], as_of=until(b))
    assert not r["transitions"]
    nxt = b + [bar(8, 106, 109, 102, 107)]
    late = decision(p, known_at=(nxt[-1].end + US).isoformat())
    r = replay(nxt, [late], as_of=until(nxt))
    assert not r["transitions"]


def test_context_strict_prior_and_equal_environment():
    b = entry_bars()
    c = context(b, 7)
    assert c["lower"] == "100" and c["upper"] == "110" and c["environment"] == "RANGE"
    assert context(b, 6) is None


def test_checkpoint_and_prefix_no_future():
    b = entry_bars() + [bar(8, 106, 109, 99, 100)]
    first = replay(b[:8], as_of=until(b[:8]), timely_fixture=True)
    end = replay(b, as_of=until(b), timely_fixture=True)
    assert (
        replay(b, as_of=until(b), checkpoint=first["checkpoint"], timely_fixture=True)
        == end
    )
    assert first == replay(b, as_of=until(b[:8]), timely_fixture=True)
    with pytest.raises(ValueError):
        replay(
            b, as_of=until(b), checkpoint=first["checkpoint"] | {"current_state": {}}
        )


def lock_restore_bars():
    return entry_bars() + [
        bar(8, 106, 109, 101, 107),
        bar(9, 106, 108, 102, 104),
        bar(10, 104, 106, 100, 101),
        bar(11, 102, 103, 99, 103),
        bar(12, 103, 105, 102, 104),
        bar(13, 104, 111, 103, 110),
    ]


def retry_bars():
    return entry_bars() + [
        bar(8, 106, 109, 100, 100),
        bar(9, 104, 109, 100, 105),
        bar(10, 102, 104, 101, 103),
        bar(11, 103, 108, 102, 105),
        bar(12, 105, 108, 100, 100),
        bar(13, 104, 109, 100, 105),
        bar(14, 102, 104, 101, 103),
        bar(15, 103, 108, 102, 105),
    ]


@pytest.mark.parametrize("mirror", [False, True])
def test_full_enter_lock_restore_exit(mirror):
    b = lock_restore_bars()
    if mirror:
        b = [
            replace(
                x,
                open=210 - x.open,
                high=210 - x.low,
                low=210 - x.high,
                close=210 - x.close,
            )
            for x in b
        ]
    r = replay(b, as_of=until(b), timely_fixture=True)
    side = "SHORT" if mirror else "LONG"
    assert [x["action"] for x in r["transitions"]] == [
        "ENTER_" + side,
        "LOCK",
        "UNLOCK_" + side,
        "CLEAR",
    ]
    assert r["transitions"][-1]["reason"] == "REGIME_INVALID"
    assert r["terminal_status"] == "FLAT"


@pytest.mark.parametrize("mirror", [False, True])
def test_risk_exit_one_reentry_then_second_failure_exhausts_plan(mirror):
    b = retry_bars()
    if mirror:
        b = [
            replace(
                x,
                open=210 - x.open,
                high=210 - x.low,
                low=210 - x.high,
                close=210 - x.close,
            )
            for x in b
        ]
    r = replay(b, as_of=until(b), timely_fixture=True)
    side = "SHORT" if mirror else "LONG"
    assert [x["action"] for x in r["transitions"]] == [
        "ENTER_" + side,
        "CLEAR",
        "REENTER_" + side,
        "CLEAR",
    ]
    entries = [x for x in r["transitions"] if "ENTER_" in x["action"]]
    assert entries[0]["after"]["cycle_id"] != entries[1]["after"]["cycle_id"]
    assert (
        entries[0]["after"]["plan"]["plan_id"] == entries[1]["after"]["plan"]["plan_id"]
    )
    assert r["current_state"]["attempt"] == 2


def test_locked_risk_cleanup_and_risk_has_priority_over_restore():
    b = lock_restore_bars()[:11] + [bar(11, 103, 105, 99, 100)]
    r = replay(b, as_of=until(b), timely_fixture=True)
    assert [x["action"] for x in r["transitions"]] == ["ENTER_LONG", "LOCK", "CLEAR"]
    clear = r["transitions"][-1]
    assert clear["before"]["long"] == clear["before"]["short"] == "1"
    assert clear["after"]["long"] == clear["after"]["short"] == "0"
    assert clear["reason"] == "RISK_INVALID"


def test_plan_expiry_even_while_locked_and_no_terminal_force_clear():
    b = lock_restore_bars()[:11] + [bar(i, 104, 109, 101, 105) for i in range(11, 20)]
    early = replay(b, as_of=b[18].end + US, timely_fixture=True)
    assert early["terminal_status"] == "OPEN_LOCKED"
    r = replay(b, as_of=until(b), timely_fixture=True)
    assert (
        r["transitions"][-1]["action"] == "CLEAR"
        and r["transitions"][-1]["reason"] == "PLAN_EXPIRED"
    )


def test_risk_exit_proposal_persists_without_acceptance_when_price_recovers():
    b = retry_bars()
    base = replay(b[:8], as_of=until(b[:8]))
    d = decision(base["proposals"][0])
    r = replay(b, [d], as_of=until(b))
    assert len(r["transitions"]) == 1
    assert all(p["reason"] == "RISK_INVALID" for p in r["proposals"][1:])
    assert r["terminal_status"] == "OPEN_DIRECTIONAL"


@pytest.mark.parametrize(
    "change",
    [
        {"state_fingerprint": "forged"},
        {"cycle_id": "wrong"},
        {"plan_id": "wrong"},
        {"rule_hash": "wrong"},
        {"contract": "SH2701"},
        {"record_kind": "AUTO"},
        {"decision": "AUTO"},
        {"version": "wrong"},
        {"known_at": "bad"},
        {"decision_id": []},
    ],
)
def test_invalid_records_fail_closed(change):
    b = entry_bars()
    p = replay(b, as_of=until(b))["proposals"][0]
    r = replay(b, [decision(p, **change)], as_of=until(b))
    assert not r["transitions"] and r["current_state"]["long"] == "0"


def test_equal_time_conflict_id_tamper_and_late_checkpoint():
    b = entry_bars()
    p = replay(b, as_of=until(b))["proposals"][0]
    d = decision(p)
    r = replay(b, [d, d | {"decision_id": "d2", "decision": "REJECT"}], as_of=until(b))
    assert not r["transitions"]
    late = d | {
        "known_at": (datetime.fromisoformat(d["known_at"]) + US).isoformat(),
        "decision": "REJECT",
    }
    r = replay(b, [d, late], as_of=until(b))
    assert (
        len(r["transitions"]) == 1
        and r["decisions"][-1]["reason"] == "DECISION_ID_CONTENT_CONFLICT"
    )
    cp = replay(b, as_of=until(b))["checkpoint"]
    with pytest.raises(ValueError, match="LATE_DECISION"):
        replay(b, [d], as_of=until(b), checkpoint=cp)


def test_all_prefixes_fixture_batch_and_restart_match():
    b = lock_restore_bars()
    cp = None
    for j in range(1, len(b) + 1):
        end = until(b[:j])
        a = replay(b, as_of=end, timely_fixture=True)
        r = replay(b, as_of=end, timely_fixture=True, checkpoint=cp)
        assert a == r == replay(b[:j], as_of=end, timely_fixture=True)
        cp = r["checkpoint"]


def test_input_boundaries_and_no_clock_expiry_across_session_gap():
    b = entry_bars()
    with pytest.raises(ValueError):
        replay(b + [replace(b[-1], contract="SH2701")], as_of=until(b))
    with pytest.raises(ValueError):
        replay([b[0], b[0]], as_of=until(b))
    with pytest.raises(ValueError):
        replay([replace(b[0], completed=False)], as_of=until(b))
    p = replay(b, as_of=until(b))["proposals"][0]
    far = b[-1].end + timedelta(days=1)
    r = replay(
        b,
        [decision(p, decided_at=far.isoformat(), known_at=far.isoformat())],
        as_of=far,
    )
    assert (
        len(r["transitions"]) == 1
    )  # no next completed supplied Bar, no invented clock expiry


def test_range_target_exit_equal_boundary():
    b = entry_bars() + [bar(8, 106, 111, 103, 110)]
    r = replay(b, as_of=until(b), timely_fixture=True)
    assert r["transitions"][-1]["reason"] == "RANGE_TARGET"


@pytest.mark.parametrize("mirror", [False, True])
def test_trend_entry_and_equality_does_not_break(mirror):
    b = [bar(i, 105 + i, 110 + i, 100 + i, 106 + i) for i in range(6)] + [
        bar(6, 110, 114, 108, 111),
        bar(7, 112, 117, 110, 116),
    ]
    if mirror:
        b = [
            replace(
                x,
                open=230 - x.open,
                high=230 - x.low,
                low=230 - x.high,
                close=230 - x.close,
            )
            for x in b
        ]
    r = replay(b, as_of=until(b), timely_fixture=True)
    assert r["transitions"][0]["action"] == ("ENTER_SHORT" if mirror else "ENTER_LONG")
    assert r["evaluations"][-1]["environment"] == ("DOWN" if mirror else "UP")
    equal = b[:-1] + [replace(b[-1], close=b[-2].high if not mirror else b[-2].low)]
    assert not replay(equal, as_of=until(equal), timely_fixture=True)["transitions"]


def test_new_plan_can_change_direction_only_after_post_exit_context():
    b = entry_bars() + [bar(8, 106, 111, 103, 110)]
    # Fresh six-Bar range all after CLEAR, then upper-half short keybar.
    b += [bar(i, 105, 110, 100, 104) for i in range(9, 15)]
    b += [bar(15, 107, 109, 105, 106), bar(16, 106, 108, 102, 104)]
    r = replay(b, as_of=until(b), timely_fixture=True)
    assert [x["action"] for x in r["transitions"]] == [
        "ENTER_LONG",
        "CLEAR",
        "ENTER_SHORT",
    ]
    first, last = r["transitions"][0]["after"], r["transitions"][-1]["after"]
    assert (
        first["plan"]["plan_id"] != last["plan"]["plan_id"]
        and last["original_side"] == "SHORT"
    )


def test_completed_gap_unknown_is_not_silently_filled():
    # The kernel cannot infer Session from wall clocks. Explicit non-5m rejected.
    b = entry_bars()
    b[-1] = replace(b[-1], start=b[-1].start - timedelta(minutes=5))
    with pytest.raises(ValueError, match="COMPLETED_5M"):
        replay(b, as_of=until(b))


def test_human_checkpoint_prefix_and_duplicate_proposal():
    b = lock_restore_bars()
    p = replay(b[:8], as_of=until(b[:8]))["proposals"][0]
    d = decision(p)
    cp = None
    for i in range(1, len(b) + 1):
        t = until(b[:i])
        r = replay(b, [d], as_of=t, checkpoint=cp)
        assert r == replay(b[:i], [d], as_of=t)
        cp = r["checkpoint"]
    again = d | {
        "decision_id": "another",
        "known_at": (b[7].end + timedelta(seconds=1)).isoformat(),
    }
    r = replay(b, [d, again], as_of=until(b))
    assert (
        len(r["transitions"]) == 1
        and r["decisions"][1]["reason"] == "PROPOSAL_NOT_PENDING"
    )


def test_half_region_comparison_is_exact_for_mixed_decimal_scales():
    from guiyi_quant.lms_near405 import _entry_allowed

    signal = bar(6, "5e19", "1e20", "5e19", "6e19")
    confirm = bar(7, "2e20", "3e20", "2e20", "3e20")
    region = dict(lower="1e-20", upper="2e20", environment="UP")
    assert not _entry_allowed(region, "LONG", signal, confirm)


def test_report_rules_cannot_mutate_next_replay():
    b = entry_bars()
    r = replay(b, as_of=until(b))
    r["rules"]["max_attempts"] = 99
    r["rules"]["priority"].reverse()
    fresh = replay(b, as_of=until(b))
    assert fresh["rules"]["max_attempts"] == 2
    assert fresh["rules"]["priority"][0] == "RISK_INVALID"


def test_first_invalidation_reason_cannot_be_rewritten_by_later_prices():
    b = entry_bars() + [bar(8, 106, 111, 103, 110), bar(9, 108, 111, 99, 100)]
    p = replay(b[:8], as_of=until(b[:8]))["proposals"][0]
    r = replay(b, [decision(p)], as_of=until(b))
    assert [p["reason"] for p in r["proposals"][1:]] == ["RANGE_TARGET", "RANGE_TARGET"]


def test_human_unordered_file_has_batch_incremental_parity():
    b = lock_restore_bars()
    trace = replay(b, as_of=until(b), timely_fixture=True)["checkpoint"][
        "decision_records"
    ]
    trace = list(reversed(trace))
    cp = None
    for i in range(1, len(b) + 1):
        t = until(b[:i])
        r = replay(b, trace, as_of=t, checkpoint=cp)
        assert r == replay(b[:i], trace, as_of=t)
        cp = r["checkpoint"]


def test_same_time_conflict_reversed_file_restart_full_report_matches():
    b = entry_bars() + [bar(8, 106, 109, 101, 107)]
    p = replay(b[:8], as_of=until(b[:8]))["proposals"][0]
    d = decision(p, decision_id="a")
    other = d | {"decision_id": "z", "decision": "REJECT"}
    records = [other, d, {"bad": "z"}, {"bad": "a"}]
    first = replay(b[:8], records, as_of=until(b[:8]))
    assert replay(b, records, as_of=until(b), checkpoint=first["checkpoint"]) == replay(
        b, records, as_of=until(b)
    )
