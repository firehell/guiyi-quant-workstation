"""New candidate only; synthetic scenario decisions are never human evidence."""

from datetime import datetime, UTC, timedelta
from decimal import Decimal as D
from dataclasses import replace
import json
import pytest
from guiyi_quant.lms405 import Bar
from guiyi_quant.lms405.protection_band import ProtectionBandUpdate
from guiyi_quant.lms_near405 import (
    EXTERNAL_PROTECTION_VERSION, SCOPED_PROTECTION_VERSION, ProtectionConfirmation, ScopedProtectionConfirmation,
    MANAGEMENT_VERSION, VERSION, context, evaluate, fingerprint, replay,
)

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


def test_carry_in_uses_published_state_and_unchanged_invalidation_rules():
    from guiyi_quant.lms_near405 import CarryInSeed

    b = entry_bars() + [bar(8, 106, 112, 103, 111)]
    known = b[7].end + timedelta(minutes=1)
    flat = CarryInSeed("JM2509", known, None, False, "sample")
    short = CarryInSeed("JM2509", known, "SHORT", False, "sample")
    results = [replay(b, as_of=until(b), timely_fixture=True, carry_in=seed) for seed in (flat, short)]

    cold, held = results
    assert cold["rule_hash"] == held["rule_hash"]
    assert cold["version"] == held["version"] == "lms-near405-carry-in-v1"
    assert cold["evaluations"][0]["index"] == held["evaluations"][0]["index"] == 8
    assert cold["transitions"] == []
    assert [(t["action"], t["reason"]) for t in held["transitions"]] == [("CLEAR", "RISK_INVALID")]
    assert held["checkpoint"]["initial_state"]["plan"]["source"] == "sample"
    assert held["checkpoint"]["initial_state"]["plan"]["created_at"] == known.isoformat()
    assert held["checkpoint"]["initial_state"]["plan"]["upper"] == "110"


def test_carry_proxy_exit_sensitivity_scans_later_risk_and_binds_checkpoint():
    from guiyi_quant.lms_near405 import CARRY_EXIT_SENSITIVITY_VERSION, CarryInSeed

    b = entry_bars() + [bar(8, 106, 112, 103, 111), bar(9, 101, 105, 98, 99)]
    seed = CarryInSeed("JM2509", b[7].end + US * 2, "LONG", False, "TEST_FIXTURE:opening")
    control = replay(b, as_of=until(b), carry_in=seed, timely_fixture=True)
    assert [row["reason"] for row in control["transitions"]] == ["RANGE_TARGET"]

    options = dict(carry_in=seed, timely_fixture=True, omitted_proxy_exit="RANGE_TARGET")
    at_target = replay(b, as_of=b[8].end + 2 * US, **options)
    contrast = replay(b, as_of=until(b), **options)
    assert contrast["version"] == CARRY_EXIT_SENSITIVITY_VERSION
    assert contrast["rule_hash"] != control["rule_hash"]
    assert at_target["current_state"]["long"] == "1"
    assert [row["reason"] for row in contrast["transitions"]] == ["RISK_INVALID"]
    assert contrast == replay(b, as_of=until(b), checkpoint=at_target["checkpoint"], **options)
    with pytest.raises(ValueError, match="CHECKPOINT_IDENTITY_MISMATCH"):
        replay(b, as_of=until(b), carry_in=seed, timely_fixture=True, checkpoint=at_target["checkpoint"])


def test_carry_proxy_exit_sensitivity_rejects_human_and_risk_overrides():
    from guiyi_quant.lms_near405 import CarryInSeed

    b = entry_bars()
    seed = CarryInSeed("JM2509", b[7].end + US * 2, "LONG", False, "TEST_FIXTURE:opening")
    with pytest.raises(ValueError, match="PROXY_EXIT_SENSITIVITY_REQUIRES_BASELINE_CARRY_FIXTURE"):
        replay(b, as_of=until(b), carry_in=seed, omitted_proxy_exit="RANGE_TARGET")
    with pytest.raises(ValueError, match="UNKNOWN_OMITTABLE_PROXY_EXIT"):
        replay(b, as_of=until(b), carry_in=seed, timely_fixture=True, omitted_proxy_exit="RISK_INVALID")


def test_carry_proxy_exit_sensitivity_keeps_exits_for_same_plan_reentry():
    from guiyi_quant.lms_near405 import CarryInSeed

    b = retry_bars()[:12] + [bar(12, 105, 112, 103, 111)]
    seed = CarryInSeed("JM2509", b[7].end + US * 2, "LONG", False, "TEST_FIXTURE:opening")
    result = replay(b, as_of=until(b), carry_in=seed, timely_fixture=True, omitted_proxy_exit="RANGE_TARGET")
    rows = result["transitions"]
    assert [(row["action"], row["reason"]) for row in rows] == [
        ("CLEAR", "RISK_INVALID"), ("REENTER_LONG", "FRESH_SIGNAL_RETRY"), ("CLEAR", "RANGE_TARGET"),
    ]
    assert rows[1]["after"]["cycle_id"] != rows[0]["before"]["cycle_id"]
    assert rows[1]["after"]["plan"]["plan_id"] == rows[0]["before"]["plan"]["plan_id"]


def test_carry_in_rejects_unavailable_and_mismatched_checkpoints():
    from guiyi_quant.lms_near405 import CarryInSeed

    b = entry_bars() + [bar(8, 106, 112, 103, 111)]
    known = b[7].end + timedelta(minutes=1)
    seed = CarryInSeed("JM2509", known, "SHORT", True, "sample")
    with pytest.raises(ValueError, match="CARRY_IN_NOT_YET_KNOWN"):
        replay(b, as_of=known - US, carry_in=seed)
    at_seed = replay(b, as_of=known, carry_in=seed)
    assert not at_seed["evaluations"] and not at_seed["transitions"]
    assert at_seed["current_state"]["long"] == at_seed["current_state"]["short"] == "1"
    result = replay(b, as_of=until(b), carry_in=seed)
    assert result == replay(b, as_of=until(b), carry_in=seed, checkpoint=at_seed["checkpoint"])
    with pytest.raises(ValueError, match="CHECKPOINT_IDENTITY_MISMATCH"):
        replay(b, as_of=until(b), carry_in=replace(seed, source="other"), checkpoint=at_seed["checkpoint"])


def test_carry_in_does_not_apply_risk_from_a_bar_available_at_exact_seed_time():
    from guiyi_quant.lms_near405 import CarryInSeed

    b = entry_bars() + [bar(8, 106, 112, 103, 111), bar(9, 108, 109, 106, 108)]
    seed = CarryInSeed("JM2509", b[8].end + US, "SHORT", False, "sample")

    result = replay(b, as_of=until(b), carry_in=seed, timely_fixture=True)

    assert [e["index"] for e in result["evaluations"]] == [9]
    assert result["checkpoint"]["initial_state"]["plan"]["upper"] == "110"
    assert result["current_state"]["short"] == "1"
    assert result["transitions"] == []


def test_carry_in_step_rejects_a_different_contract_or_a_bar_before_seed():
    from guiyi_quant.lms_near405 import CarryInSeed

    b = entry_bars() + [bar(8, 106, 112, 103, 111)]
    known = b[7].end + timedelta(minutes=1)
    seed = CarryInSeed("JM2509", known, "SHORT", False, "sample")
    state = replay(b, as_of=known, carry_in=seed)["current_state"]

    with pytest.raises(ValueError, match="CARRY_IN_CONTRACT_MISMATCH"):
        evaluate(state, [replace(item, contract="JM2510") for item in b], 8)
    with pytest.raises(ValueError, match="CARRY_IN_NOT_YET_KNOWN"):
        evaluate(state, b, 7)
    with pytest.raises(ValueError, match="CONTRACT_BOUNDARY"):
        evaluate(state, [replace(b[0], contract="JM2510"), *b[1:]], 8)
    with pytest.raises(ValueError, match="BAR_ORDER_OR_OVERLAP"):
        evaluate(state, [*b[:7], bar(20, 104, 108, 102, 106), b[8]], 8)


def test_decisions_at_or_before_carry_in_do_not_use_seed_identity():
    from guiyi_quant.lms_near405 import CarryInSeed

    b = entry_bars() + [bar(8, 106, 112, 103, 111)]
    known = b[7].end + timedelta(minutes=1)
    seed = CarryInSeed("JM2509", known, "SHORT", False, "sample")
    cycle = replay(b, as_of=known, carry_in=seed)["current_state"]["cycle_id"]
    supplied = [
        dict(decision_id=str(offset), proposal_id="unseen", state_fingerprint="unseen",
             decision="ACCEPT", record_kind="HUMAN_RESEARCH_DECISION", cycle_id=cycle,
             known_at=(known + offset * US).isoformat(), decided_at=(known + offset * US).isoformat())
        for offset in (-1, 0)
    ]

    result = replay(b, supplied, as_of=until(b), carry_in=seed)
    alternative = replay(b, supplied, as_of=until(b), carry_in=replace(seed, source="another"))

    assert result["decisions"] == alternative["decisions"]
    assert {row["reason"] for row in result["decisions"]} == {"DECISION_NOT_AFTER_CARRY_IN_SEED"}
    assert result["transitions"] == []


def test_protection_candidate_does_not_turn_proxy_invalidation_into_carry_exit():
    from guiyi_quant.lms_near405 import CarryInExitEvidence, CarryInSeed

    b = entry_bars() + [bar(8, 106, 112, 103, 111), bar(9, 111, 112, 105, 107)]
    known = b[7].end + timedelta(minutes=1)
    seed = CarryInSeed("JM2509", known, "SHORT", True, "sample")
    kwargs = dict(carry_in=seed, timely_fixture=True)
    gated = replay(b, as_of=until(b), carry_exit_evidence=(), **kwargs)
    assert gated["checkpoint"]["initial_state"] == gated["current_state"]
    assert gated["evaluations"][0]["carry_exit_status"] == "UNKNOWN"
    assert gated["evaluations"][0]["carry_exit_proxy_reason"] == "RISK_INVALID"

    proof = CarryInExitEvidence("JM2509", fingerprint(gated["current_state"]),
                                b[8].end + US, b[8].end + US, "fixture-only", "TEST_FIXTURE")
    authorized = replay(b, as_of=until(b), carry_exit_evidence=(proof,), **kwargs)
    assert [(x["action"], x["reason"]) for x in authorized["transitions"]] == [
        ("CLEAR", "EXPLICIT_CARRY_IN_EXIT"),
    ]
    assert authorized["proposals"][0]["index"] == 9
    assert authorized["current_state"]["short"] == authorized["current_state"]["long"] == "0"
    cutoff = b[8].end + US
    assert replay(b, as_of=cutoff, carry_exit_evidence=(), **kwargs) == replay(
        b, as_of=cutoff, carry_exit_evidence=(proof,), **kwargs,
    )
    prefix = replay(b, as_of=cutoff, carry_exit_evidence=(), **kwargs)["checkpoint"]
    assert authorized == replay(
        b, as_of=until(b), carry_exit_evidence=(proof,), checkpoint=json.loads(json.dumps(prefix)), **kwargs,
    )
    wrong = replace(proof, state_fingerprint="other-position")
    assert not replay(b, as_of=until(b), carry_exit_evidence=(wrong,), **kwargs)["transitions"]
    assert authorized == replay(b, as_of=until(b), carry_exit_evidence=(proof, proof), **kwargs)
    with pytest.raises(ValueError, match="HUMAN_CARRY_IN_EXIT_EVIDENCE_REQUIRED"):
        replay(b, as_of=until(b), carry_in=seed, carry_exit_evidence=(proof,))
    with pytest.raises(ValueError, match="CARRY_IN_EXIT_CONTRACT_MISMATCH"):
        replay(b, as_of=until(b), carry_exit_evidence=(replace(proof, contract="JM2510"),), **kwargs)
    with pytest.raises(ValueError, match="EXPLICIT_EXIT_REQUIRES_CARRY_IN"):
        replay(b, as_of=until(b), carry_exit_evidence=())


def test_carry_exit_new_conflict_expires_pending_human_proposal():
    from guiyi_quant.lms_near405 import CarryInExitEvidence, CarryInSeed

    b = entry_bars() + [bar(8, 106, 112, 103, 111)]
    seed = CarryInSeed("JM2509", b[7].end + timedelta(minutes=1), "SHORT", True, "archive")
    t = b[8].end + US
    state = replay(b, as_of=seed.known_at, carry_in=seed, carry_exit_evidence=())["current_state"]
    evidence = CarryInExitEvidence(
        seed.contract, fingerprint(state), t - 2 * US, t - US, "archive-exit", "HUMAN_RESEARCH_EVIDENCE",
    )
    kwargs = dict(carry_in=seed, carry_exit_evidence=(evidence,))
    single = replay(b, as_of=t, **kwargs)
    assert single["current_state"] == state
    assert single["proposals"][0]["signal_bar_end"] is None
    accept_at = (t + 2 * US).isoformat()
    accept = decision(single["proposals"][0], known_at=accept_at, decided_at=accept_at,
                      record_kind="HUMAN_RESEARCH_DECISION")
    accepted = replay(b, [accept], as_of=until(b), **kwargs)
    assert accepted["transitions"][0]["after"]["long"] == accepted["transitions"][0]["after"]["short"] == "0"
    late_conflict = replace(evidence, source="another", known_at=t + US)
    pending = replay(b, [accept], as_of=until(b), carry_in=seed, carry_exit_evidence=(evidence, late_conflict))
    assert pending["decisions"][0]["reason"] == "PROPOSAL_NOT_PENDING"
    assert pending["proposals"][0]["expiry_reason"] == "CARRY_IN_EXIT_EVIDENCE_CHANGED"
    assert pending["current_state"] == state
    early_conflict = replace(evidence, source="another")
    conflicting = replay(b, as_of=until(b), carry_in=seed, carry_exit_evidence=(evidence, early_conflict))
    assert conflicting["evaluations"][0]["carry_exit_status"] == "CONFLICT"
    assert not conflicting["proposals"]


def test_carry_exit_conflict_expiry_is_stable_without_a_human_record():
    from guiyi_quant.lms_near405 import CarryInExitEvidence, CarryInSeed

    b = entry_bars() + [bar(8, 106, 112, 103, 111), bar(9, 111, 112, 105, 107)]
    seed = CarryInSeed("JM2509", b[7].end + timedelta(minutes=1), "SHORT", True, "archive")
    t = b[8].end + US
    state = replay(b, as_of=seed.known_at, carry_in=seed, carry_exit_evidence=())["current_state"]
    first = CarryInExitEvidence(
        seed.contract, fingerprint(state), t - 2 * US, t - US, "archive-exit", "HUMAN_RESEARCH_EVIDENCE",
    )
    conflict = replace(first, source="another", known_at=t + 3 * US)
    kwargs = dict(carry_in=seed, carry_exit_evidence=(first, conflict))
    expected = conflict.known_at + US
    before = replay(b, as_of=conflict.known_at, **kwargs)
    short = replay(b, as_of=expected, **kwargs)
    long = replay(b, as_of=until(b), **kwargs)
    assert before["proposals"][0]["status"] == "PENDING"
    assert short["proposals"][0]["expired_at"] == expected.isoformat()
    assert short["proposals"][0]["expiry_reason"] == "CARRY_IN_EXIT_EVIDENCE_CHANGED"
    assert short["proposals"] == long["proposals"]
    assert long == replay(b, as_of=until(b), checkpoint=short["checkpoint"], **kwargs)


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


def managed_lock_restore_bars():
    return lock_restore_bars()[:11] + [
        bar(11, 107, 110, 103, 108),
        bar(12, 109, 113, 107, 111),
        bar(13, 111, 112, 108, 111.5),
        bar(14, 112, 115, 109, 114),
    ]


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_managed_recovery_preserves_original_cycle_and_hard_exit_clears_both_when_locked(side):
    rows = managed_lock_restore_bars()
    early_risk = rows[:11] + [bar(11, 103, 104, 99, 100)]
    if side == "SHORT":
        def reflect(items):
            return [replace(b, open=210 - b.open, high=210 - b.low, low=210 - b.high, close=210 - b.close)
                    for b in items]
        rows, early_risk = reflect(rows), reflect(early_risk)

    result = replay(rows, as_of=until(rows), timely_fixture=True, managed_lifecycle=True)
    assert result["version"] == MANAGEMENT_VERSION
    assert [row["action"] for row in result["transitions"]] == ["ENTER_" + side, "LOCK", "UNLOCK_" + side]
    _, lock, recover = result["transitions"]
    assert lock["after"]["cycle_id"] == recover["after"]["cycle_id"]
    assert recover["after"][side.lower()] == "1"
    closed = replay(early_risk, as_of=until(early_risk), timely_fixture=True, managed_lifecycle=True)
    last = closed["transitions"][-1]
    assert last["action"] == "CLEAR" and last["reason"] == "RISK_INVALID"
    assert last["before"]["long"] == last["before"]["short"] == "1"
    assert last["after"]["long"] == last["after"]["short"] == "0"


def test_managed_range_target_requires_later_opposing_confirmation_and_full_post_exit_context():
    rows = entry_bars() + [bar(8, 106, 109, 101, 107), bar(9, 107, 110, 101, 106),
                          bar(10, 107, 108, 103, 105), bar(11, 105, 107, 101, 102)]
    rows += [bar(i, 104, 110, 100, 106) for i in range(12, 19)]
    rows += [bar(19, 103, 105, 101, 104), bar(20, 104, 108, 102, 106)]
    earlier = replay(rows, as_of=until(rows[:11]), timely_fixture=True, managed_lifecycle=True)
    assert [row["action"] for row in earlier["transitions"]] == ["ENTER_LONG"]
    result = replay(rows, as_of=until(rows), timely_fixture=True, managed_lifecycle=True)
    assert [row["action"] for row in result["transitions"]] == ["ENTER_LONG", "CLEAR", "ENTER_LONG"]
    first, clear, reentry = result["transitions"]
    assert clear["reason"] == "OPPOSING_KEYBAR_AFTER_RANGE_TARGET"
    assert first["after"]["plan"]["plan_id"] != reentry["after"]["plan"]["plan_id"]
    assert rows[13].start > datetime.fromisoformat(clear["known_at"])
    assert result == replay(rows, as_of=until(rows), timely_fixture=True, managed_lifecycle=True,
                            checkpoint=json.loads(json.dumps(earlier["checkpoint"])))


def test_managed_recovery_requires_fresh_cross_and_human_decisions():
    rows = managed_lock_restore_bars()
    for i in (11, 12):
        rows[i] = bar(i, 111, 113, 107, 111)
    result = replay(rows, as_of=until(rows), timely_fixture=True, managed_lifecycle=True)
    assert [row["action"] for row in result["transitions"]] == ["ENTER_LONG", "LOCK"]
    assert result["evaluations"][-1]["status"] == "RECOVERY_RETURN_UNCONFIRMED"
    pending = replay(rows, as_of=until(rows[:8]), managed_lifecycle=True)["proposals"][0]
    manual = replay(rows, [decision(pending)], as_of=until(rows), managed_lifecycle=True)
    assert not manual["transitions"]
    assert manual["decisions"][0]["reason"] == "HUMAN_DECISION_REQUIRED"


@pytest.mark.parametrize("order", ["BEFORE_CONFIRMATION", "BEFORE_SHAPE"])
def test_managed_order_blocks_same_window_recovery_then_accepts_later_shape(order):
    rows = managed_lock_restore_bars()
    options = dict(managed_lifecycle=True, managed_recovery_order=order, timely_fixture=True)
    baseline = replay(rows, as_of=until(rows), managed_lifecycle=True, timely_fixture=True)
    prefix = replay(rows, as_of=until(rows), **options)
    assert [step["action"] for step in baseline["transitions"]][-1] == "UNLOCK_LONG"
    assert [step["action"] for step in prefix["transitions"]] == ["ENTER_LONG", "LOCK"]
    assert prefix["evaluations"][-1]["status"] == "RECOVERY_NOT_KNOWN_BEFORE_SIGNAL_WINDOW"
    assert prefix["rule_hash"] != baseline["rule_hash"]

    later = rows + [bar(15, 113, 114, 111, 112), bar(16, 112, 117, 111, 116)]
    full = replay(later, as_of=until(later), **options)
    assert [step["action"] for step in full["transitions"]] == ["ENTER_LONG", "LOCK", "UNLOCK_LONG"]
    assert full["transitions"][-1]["after"]["cycle_id"] == prefix["current_state"]["cycle_id"]
    assert full == replay(later, as_of=until(later), checkpoint=json.loads(json.dumps(prefix["checkpoint"])), **options)
    with pytest.raises(ValueError):
        replay(later, as_of=until(later), checkpoint=baseline["checkpoint"], **options)


def test_managed_order_distinguishes_shape_start_from_confirmation_start():
    rows = managed_lock_restore_bars()[:-1] + [bar(14, 111, 111.8, 110.5, 111.3), bar(15, 111.4, 114, 110.6, 113)]
    options = dict(as_of=until(rows), managed_lifecycle=True, timely_fixture=True)
    confirmation = replay(rows, managed_recovery_order="BEFORE_CONFIRMATION", **options)
    shape = replay(rows, managed_recovery_order="BEFORE_SHAPE", **options)
    assert confirmation["transitions"][-1]["action"] == "UNLOCK_LONG"
    assert shape["transitions"][-1]["action"] == "LOCK"
    assert shape["evaluations"][-1]["status"] == "RECOVERY_NOT_KNOWN_BEFORE_SIGNAL_WINDOW"
    assert shape["current_state"]["management_rule_version"] == shape["version"]

    for order in (None, "BEFORE_CONFIRMATION"):
        with pytest.raises(ValueError, match="MANAGED_STATE_RULE_MISMATCH"):
            evaluate(shape["current_state"], rows, len(rows) - 1, managed_lifecycle=True, managed_recovery_order=order)


def test_managed_state_cannot_be_evaluated_by_the_old_rule_or_reverse():
    rows = managed_lock_restore_bars()
    states = [replay(rows, as_of=until(rows[:8]), timely_fixture=True, managed_lifecycle=managed)["current_state"]
              for managed in (False, True)]
    for old, managed in zip(states, (True, False), strict=True):
        with pytest.raises(ValueError, match="MANAGED_STATE_RULE_MISMATCH"):
            evaluate(old, rows, 8, managed_lifecycle=managed)


def protection_for(bars, *, mirror=False):
    prefix = replay(bars, as_of=until(bars[:8]), timely_fixture=True, protection_confirmations=())
    return ProtectionConfirmation(
        bars[0].contract, fingerprint(prefix["current_state"]), bars[10].end, bars[10].end,
        bars[10].end, "fixture-short" if mirror else "fixture-long", "TEST_FIXTURE",
    )


@pytest.mark.parametrize("mirror", [False, True])
def test_external_protection_owns_lock_and_keeps_original_restore_and_risk_priority(mirror):
    bars = lock_restore_bars()
    if mirror:
        bars = [replace(x, open=210 - x.open, high=210 - x.low,
                        low=210 - x.high, close=210 - x.close) for x in bars]
    proof = protection_for(bars, mirror=mirror)
    side = "SHORT" if mirror else "LONG"
    empty = replay(bars, as_of=until(bars), timely_fixture=True, protection_confirmations=())
    assert empty["version"] == EXTERNAL_PROTECTION_VERSION
    assert "LOCK" not in [row["action"] for row in empty["transitions"]]
    accepted = replay(bars, as_of=until(bars), timely_fixture=True, protection_confirmations=(proof, proof))
    assert [row["action"] for row in accepted["transitions"]] == [
        "ENTER_" + side, "LOCK", "UNLOCK_" + side, "CLEAR",
    ]
    lock = accepted["transitions"][1]
    assert lock["reason"] == "EXTERNAL_PROTECTION_CONFIRMED"
    assert lock["before"]["cycle_id"] == lock["after"]["cycle_id"]
    lock_proposal = next(p for p in accepted["proposals"] if p["action"] == "LOCK")
    assert lock_proposal["signal_bar_end"] is None and lock_proposal["protection_confirmation"]


def test_external_protection_on_bar_without_keybar_can_clear_both_and_reenter():
    bars = lock_restore_bars()[:11] + [
        bar(11, 104, 108, 99, 100),
        bar(12, 104, 109, 100, 105),
        bar(13, 102, 104, 101, 103),
        bar(14, 103, 108, 102, 105),
    ]
    # Request protection on Bar 9, where the ordinary geometry issues no lock.
    end = bars[9].end
    proof = replace(protection_for(bars), due_at=end, signal_at=end, known_at=end)
    result = replay(bars, as_of=until(bars), timely_fixture=True, protection_confirmations=(proof,))
    assert [x["action"] for x in result["transitions"]] == ["ENTER_LONG", "LOCK", "CLEAR", "REENTER_LONG"]
    lock, clear = result["transitions"][1:3]
    assert lock["known_at"] == (end + US + US).isoformat()
    assert clear["before"]["long"] == clear["before"]["short"] == "1"
    assert clear["after"]["long"] == clear["after"]["short"] == "0"
    assert result["current_state"]["attempt"] == 2


def test_external_protection_known_at_fingerprint_conflict_and_checkpoint():
    bars = lock_restore_bars()
    proof = protection_for(bars)
    cut = bars[10].end + US
    late = replace(proof, known_at=cut)
    early = replay(bars, as_of=cut, timely_fixture=True, protection_confirmations=(late,))
    assert not any(p["action"] == "LOCK" for p in early["proposals"])
    advanced = replay(bars, as_of=until(bars), timely_fixture=True,
                      protection_confirmations=(late,), checkpoint=json.loads(json.dumps(early["checkpoint"])))
    assert advanced == replay(bars, as_of=until(bars), timely_fixture=True, protection_confirmations=(late,))
    wrong_state = replace(proof, state_fingerprint="different")
    conflicting = replace(proof, source="different")
    for invalid in ((wrong_state,), (proof, conflicting)):
        result = replay(bars, as_of=until(bars), timely_fixture=True, protection_confirmations=invalid)
        assert not any(p["action"] == "LOCK" for p in result["proposals"])
    with pytest.raises(ValueError, match="CHECKPOINT_IDENTITY_MISMATCH"):
        replay(bars, as_of=until(bars), timely_fixture=True,
               protection_confirmations=(proof, late), checkpoint=early["checkpoint"])
    with pytest.raises(ValueError, match="HUMAN_PROTECTION_EVIDENCE_REQUIRED"):
        replay(bars, as_of=until(bars), protection_confirmations=(proof,))
    with pytest.raises(ValueError, match="PROTECTION_CONFIRMATION_CONTRACT_MISMATCH"):
        replay(bars, as_of=until(bars), timely_fixture=True,
               protection_confirmations=(replace(proof, contract="I2701"),))


def protection_band(bars, revision, time, role="PROTECTION"):
    bounds = {} if role == "REVIEW_PENDING" else dict(lower=D(101), upper=D(104))
    return ProtectionBandUpdate(bars[0].contract, revision, role, time, time, "test", "LONG", **bounds)


def scoped_proof(bars, band, signal_start, record_kind="TEST_FIXTURE", state=None):
    if state is None:
        state = replay(bars, as_of=until(bars[:8]), timely_fixture=True, protection_bands=(),
                       protection_confirmations=())["current_state"]
    end = bars[10].end
    return ScopedProtectionConfirmation(
        bars[0].contract, fingerprint(state), end, end, end, "scoped-test", record_kind,
        band.scope, signal_start, "SHORT",
    )


def test_scoped_protection_rejects_target_old_scope_old_shape_and_wrong_side():
    bars = lock_restore_bars()
    active_at = bars[9].end
    old = protection_band(bars, "old", bars[8].end)
    new = protection_band(bars, "new", active_at)
    target = protection_band(bars, "target", active_at + US, "TARGET")
    pending = protection_band(bars, "review", active_at + US, "REVIEW_PENDING")
    conflict = protection_band(bars, "other", active_at)
    proof = scoped_proof(bars, new, active_at + 2 * US)
    other_side = replace(new, side="SHORT")
    for bands, supplied, expected in (
        ((target,), (replace(proof, band_scope=target.scope),), "PROTECTION_RANGE_UNAVAILABLE"),
        ((old, new), (replace(proof, band_scope=old.scope),), "PROTECTION_UNCONFIRMED"),
        ((old, new), (replace(proof, signal_start=active_at),), "PROTECTION_UNCONFIRMED"),
        ((old, new), (replace(proof, due_at=active_at),), "PROTECTION_UNCONFIRMED"),
        ((old, new), (replace(proof, signal_side="LONG"),), "PROTECTION_UNCONFIRMED"),
        ((old, new), (replace(protection_for(bars), state_fingerprint=proof.state_fingerprint),),
         "PROTECTION_UNCONFIRMED"),
        ((old, new, pending), (proof,), "PROTECTION_RANGE_REVIEW_PENDING"),
        ((old, new, conflict), (proof,), "PROTECTION_RANGE_CONFLICT"),
        ((other_side,), (replace(proof, band_scope=other_side.scope),), "PROTECTION_RANGE_UNAVAILABLE"),
    ):
        result = replay(bars, as_of=until(bars), timely_fixture=True, protection_bands=bands,
                        protection_confirmations=supplied)
        assert result["evaluations"][10]["status"] == expected
        assert not any(p["action"] == "LOCK" for p in result["proposals"])
    result = replay(bars, as_of=until(bars), timely_fixture=True,
                    protection_bands=(old, new, target, new, replace(pending, side="SHORT")),
                    protection_confirmations=(proof,))
    assert result["version"] == SCOPED_PROTECTION_VERSION
    assert [p["action"] for p in result["proposals"]] == ["ENTER_LONG", "LOCK", "UNLOCK_LONG", "CLEAR"]
    assert result["proposals"][1]["protection_band_scope"] == new.scope


def test_scoped_band_schedule_and_checkpoint_know_only_the_available_prefix():
    bars = lock_restore_bars()
    old = protection_band(bars, "old", bars[8].end)
    activation = bars[9].end + US
    new = replace(protection_band(bars, "new", bars[9].end), effective_after=activation)
    cut = new.known_at
    args = dict(timely_fixture=True, protection_confirmations=())
    prefix = replay(bars, as_of=cut, protection_bands=(old,), **args)
    assert replay(bars, as_of=cut, protection_bands=(old, new), **args) == prefix
    scheduled = replay(bars, as_of=activation, protection_bands=(old, new), **args)
    assert scheduled["evaluations"][9]["protection_band_scope"] == old.scope
    proof = scoped_proof(bars, new, activation + US)
    full = dict(timely_fixture=True, protection_bands=(old, new), protection_confirmations=(proof,))
    continued = replay(bars, as_of=until(bars), checkpoint=json.loads(json.dumps(scheduled["checkpoint"])), **full)
    assert continued == replay(bars, as_of=until(bars), **full)
    assert any(row["action"] == "LOCK" for row in continued["transitions"])
    with pytest.raises(ValueError, match="CHECKPOINT_IDENTITY_MISMATCH"):
        replay(bars, as_of=until(bars), checkpoint=scheduled["checkpoint"],
               **(full | dict(protection_bands=(old,))))
    with pytest.raises(ValueError, match="SCOPED_CONFIRMATION_REQUIRES_PROTECTION_BANDS"):
        replay(bars, as_of=until(bars), timely_fixture=True, protection_confirmations=(proof,))


def test_carry_in_combines_one_selected_band_with_independent_exit_evidence():
    from guiyi_quant.lms_near405 import CarryInExitEvidence, CarryInSeed

    bars = managed_lock_restore_bars() + [bar(15, 114, 116, 111, 113)]
    seed = CarryInSeed("JM2509", bars[7].end + timedelta(minutes=1), "LONG", False, "archive")
    early = protection_band(bars, "early", bars[9].end)
    late = replace(early, revision="late", lower=D(97), upper=D(100))
    pending = protection_band(bars, "pending", early.known_at, "REVIEW_PENDING")
    args = dict(carry_in=seed, timely_fixture=True, carry_exit_evidence=())
    initial = replay(bars, as_of=seed.known_at, protection_bands=(), protection_confirmations=(), **args)
    assert initial["version"] == "lms-near405-carry-scoped-protection-v1"
    proof = scoped_proof(bars, early, early.known_at + 2 * US, state=initial["current_state"])
    args.update(protection_confirmations=(proof,))
    cutoff = bars[14].end + 3 * US

    results = {}
    for name, bands in (("early", (early,)), ("late", (late,)), ("pending", (pending,)),
                        ("conflict", (early, late))):
        prefix = replay(bars, as_of=cutoff, protection_bands=bands, **args)
        state = prefix["current_state"]
        assert state["plan"] == initial["current_state"]["plan"]
        assert state["cycle_id"] == initial["current_state"]["cycle_id"]
        proposed_exit = CarryInExitEvidence(
            seed.contract, fingerprint(state), cutoff, cutoff, "fixed-exit-fixture", "TEST_FIXTURE",
        )
        with_exit = args | dict(carry_exit_evidence=(proposed_exit,))
        advanced = replay(bars, as_of=until(bars), protection_bands=bands, **with_exit)
        assert advanced == replay(bars, as_of=until(bars), protection_bands=bands,
                                  checkpoint=json.loads(json.dumps(prefix["checkpoint"])), **with_exit)
        assert advanced["transitions"][-1]["reason"] == "EXPLICIT_CARRY_IN_EXIT"
        assert advanced["terminal_status"] == "FLAT"
        results[name] = [step["action"] for step in advanced["transitions"]]
    assert results == {"early": ["LOCK", "UNLOCK_LONG", "CLEAR"], "late": ["CLEAR"],
                       "pending": ["CLEAR"], "conflict": ["CLEAR"]}

    locked = replay(bars, as_of=until(bars[:11]), protection_bands=(early,), **args)["current_state"]
    conflict_at = bars[11].start + 3 * US
    explicit = CarryInExitEvidence(
        seed.contract, fingerprint(locked), conflict_at, conflict_at, "exit-while-locked", "TEST_FIXTURE",
    )
    cleared = replay(bars, as_of=until(bars[:12]), protection_bands=(early,),
                     **(args | dict(carry_exit_evidence=(explicit,))))
    assert [step["action"] for step in cleared["transitions"]] == ["LOCK", "CLEAR"]
    assert cleared["transitions"][-1]["before"]["long"] == cleared["transitions"][-1]["before"]["short"] == "1"
    assert cleared["terminal_status"] == "FLAT"


def test_carry_scoped_recovery_cannot_use_a_shape_opened_before_lock_acceptance():
    from guiyi_quant.lms_near405 import CarryInSeed

    rows = lock_restore_bars()[:11]
    rows += [bar(11, 102, 104, 101, 103), bar(12, 103, 106, 102, 105)]
    seed = CarryInSeed("JM2509", rows[7].end + timedelta(minutes=1), "LONG", False, "archive")
    band = protection_band(rows, "early", rows[9].end)
    args = dict(carry_in=seed, timely_fixture=True, carry_exit_evidence=(), protection_bands=(band,))
    initial = replay(rows, as_of=seed.known_at, protection_confirmations=(), **args)
    proof = scoped_proof(rows, band, band.known_at + 2 * US, state=initial["current_state"])
    result = replay(rows, as_of=until(rows), protection_confirmations=(proof,), **args)
    assert result["evaluations"][-1]["signal_direction"] == "LONG"
    assert result["evaluations"][-1]["status"] == "STALE_SIGNAL"
    assert [step["action"] for step in result["transitions"]] == ["LOCK"]
    assert result["terminal_status"] == "OPEN_LOCKED"


def test_carry_scoped_exit_preempts_a_pending_lock_once_exit_is_known():
    from guiyi_quant.lms_near405 import CarryInExitEvidence, CarryInSeed

    bars = managed_lock_restore_bars()
    seed = CarryInSeed("JM2509", bars[7].end + timedelta(minutes=1), "LONG", False, "archive")
    band = protection_band(bars, "early", bars[9].end)
    args = dict(carry_in=seed, protection_bands=(band,), carry_exit_evidence=())
    initial = replay(bars, as_of=seed.known_at, protection_confirmations=(), **args)
    proof = scoped_proof(bars, band, band.known_at + 2 * US, "HUMAN_RESEARCH_EVIDENCE", initial["current_state"])
    args.update(protection_confirmations=(proof,))
    proposal = replay(bars, as_of=until(bars[:11]), **args)["proposals"][0]
    assert proposal["action"] == "LOCK"
    generated = datetime.fromisoformat(proposal["generated_at"])
    known = generated + 2 * US
    evidence = CarryInExitEvidence(
        seed.contract, proposal["state_fingerprint"], known, known, "explicit-exit", "HUMAN_RESEARCH_EVIDENCE",
    )
    with_exit = args | dict(carry_exit_evidence=(evidence,))
    at_known = replay(bars, as_of=known, **with_exit)
    assert at_known == replay(bars, as_of=known, **args)
    assert at_known["proposals"][0]["status"] == "PENDING"

    accepted_at = (known + 2 * US).isoformat()
    accept = decision(proposal, decided_at=accepted_at, known_at=accepted_at, record_kind="HUMAN_RESEARCH_DECISION")
    result = replay(bars, [accept], as_of=until(bars[:12]), **with_exit)
    assert result == replay(bars, [accept], as_of=until(bars[:12]), checkpoint=at_known["checkpoint"], **with_exit)
    lock, clear = result["proposals"]
    assert lock["status"] == "EXPIRED"
    assert lock["expired_at"] == (known + US).isoformat()
    assert lock["expiry_reason"] == "EXPLICIT_CARRY_IN_EXIT_TAKES_PRIORITY"
    assert clear["action"] == "CLEAR"
    assert not result["transitions"]


def test_carry_scoped_revised_band_expires_pending_lock_at_a_stable_time():
    from guiyi_quant.lms_near405 import CarryInSeed

    bars = managed_lock_restore_bars()
    seed = CarryInSeed("JM2509", bars[7].end + timedelta(minutes=1), "LONG", False, "archive")
    band = protection_band(bars, "early", bars[9].end)
    initial = replay(bars, as_of=seed.known_at, carry_in=seed, carry_exit_evidence=(),
                     protection_bands=(), protection_confirmations=())
    proof = scoped_proof(bars, band, band.known_at + 2 * US, "HUMAN_RESEARCH_EVIDENCE", initial["current_state"])
    effective = bars[10].end + 3 * US
    next_band = protection_band(bars, "revised", effective)
    args = dict(carry_in=seed, carry_exit_evidence=(), protection_bands=(band, next_band),
                protection_confirmations=(proof,))
    before = replay(bars, as_of=effective, **args)
    assert before["proposals"][0]["status"] == "PENDING"
    at_expiry = replay(bars, as_of=effective + US, **args)
    extended = replay(bars, as_of=until(bars[:12]), checkpoint=before["checkpoint"], **args)
    assert at_expiry["proposals"] == extended["proposals"]
    (proposal,) = extended["proposals"]
    assert proposal["expired_at"] == (effective + US).isoformat()
    assert proposal["expiry_reason"] == "PROTECTION_RANGE_SUPERSEDED"
    assert not extended["transitions"]


def test_carry_scoped_exit_and_band_update_have_same_priority_for_fixture_and_human():
    from guiyi_quant.lms_near405 import CarryInExitEvidence, CarryInSeed

    bars = managed_lock_restore_bars()
    seed = CarryInSeed("JM2509", bars[7].end + timedelta(minutes=1), "LONG", False, "archive")
    band = protection_band(bars, "early", bars[9].end)
    generated = bars[10].end + US
    newer = protection_band(bars, "revised", generated)
    initial = replay(bars, as_of=seed.known_at, carry_in=seed, carry_exit_evidence=(),
                     protection_bands=(), protection_confirmations=())["current_state"]
    proof = scoped_proof(bars, band, band.known_at + 2 * US, "HUMAN_RESEARCH_EVIDENCE", initial)
    exit_evidence = CarryInExitEvidence(
        seed.contract, fingerprint(initial), generated, generated, "same-time-exit", "HUMAN_RESEARCH_EVIDENCE",
    )
    args = dict(carry_in=seed, protection_bands=(band, newer), protection_confirmations=(proof,),
                carry_exit_evidence=(exit_evidence,))
    fixture = replay(bars, as_of=generated + US, timely_fixture=True, **args)
    proposal = replay(bars, as_of=generated, **args)["proposals"][0]
    human = replay(bars, [decision(proposal, record_kind="HUMAN_RESEARCH_DECISION")], as_of=generated + US, **args)
    for result in (fixture, human):
        assert not result["transitions"]
        assert result["proposals"][0]["expiry_reason"] == "EXPLICIT_CARRY_IN_EXIT_TAKES_PRIORITY"


def test_carry_recovery_boundary_distinguishes_one_close_from_a_fresh_run():
    from guiyi_quant import lms_near405 as candidate

    bars = managed_lock_restore_bars()
    start = bars[7].end + timedelta(minutes=1)
    seed = candidate.CarryInSeed("JM2509", start, "LONG", True, "study")
    args = dict(carry_in=seed, carry_exit_evidence=(), protection_bands=(),
                protection_confirmations=(), timely_fixture=True)
    initial = candidate.replay(bars, as_of=start, **args)["current_state"]
    boundary_type = getattr(candidate, "CarryRecoveryBoundary", None)
    assert boundary_type is not None, "time-scoped recovery boundary contract is missing"
    boundary = boundary_type("JM2509", "LONG", D(112), bars[8].end, "CLOSE_BEYOND", "research")

    def run(rule):
        return candidate.replay(bars, as_of=until(bars), carry_recovery=rule, **args)

    simple = run(boundary)
    assert simple["version"] == "lms-near405-carry-recovery-boundary-v1"
    assert [row["action"] for row in simple["transitions"]] == ["UNLOCK_LONG"]
    assert simple["current_state"]["plan"] == initial["plan"]
    assert simple["current_state"]["cycle_id"] == initial["cycle_id"]
    strict = replace(boundary, confirmation="FRESH_TWO_CLOSES")
    assert not run(strict)["transitions"]
    assert run(strict)["evaluations"][-1]["status"] == "RECOVERY_RETURN_UNCONFIRMED"
    lower = replace(strict, edge=D(110))
    assert [row["action"] for row in run(lower)["transitions"]] == ["UNLOCK_LONG"]
    future = replace(lower, known_at=bars[-1].end + US)
    assert not run(future)["transitions"]
    assert run(future)["evaluations"][-1]["status"] == "RECOVERY_BOUNDARY_UNKNOWN"
    foreign = replace(future, contract="JM2601")
    assert candidate.replay(bars, as_of=future.known_at, carry_recovery=foreign, **args) == candidate.replay(
        bars, as_of=future.known_at, carry_recovery=future, **args,
    )
    with pytest.raises(ValueError, match="CARRY_RECOVERY_CONTRACT_MISMATCH"):
        candidate.replay(bars, as_of=future.known_at + US, carry_recovery=foreign, **args)
    cut = bars[9].end + 2 * US
    checkpoint = candidate.replay(bars, as_of=cut, carry_recovery=lower, **args)["checkpoint"]
    assert run(lower) == candidate.replay(
        bars, as_of=until(bars), carry_recovery=lower, checkpoint=json.loads(json.dumps(checkpoint)), **args,
    )


def test_ambiguous_revisions_with_decimal_scale_are_order_independent():
    bars = lock_restore_bars()
    band = protection_band(bars, "review", bars[9].end)
    alternate = replace(band, lower=D("101.00"))
    proof = scoped_proof(bars, band, bars[9].end + US)
    args = dict(as_of=until(bars), timely_fixture=True, protection_confirmations=(proof,))
    result = replay(bars, protection_bands=(band, alternate), **args)
    assert result == replay(bars, protection_bands=(alternate, band), **args)
    assert result["evaluations"][10]["status"] == "PROTECTION_RANGE_CONFLICT"
    assert not any(row["action"] == "LOCK" for row in result["transitions"])


def test_human_cannot_confirm_lock_after_the_protection_band_has_changed():
    bars = lock_restore_bars()[:11]
    old = protection_band(bars, "old", bars[8].end)
    args = dict(protection_bands=(old,), protection_confirmations=())
    initial = replay(bars, as_of=until(bars[:8]), **args)["proposals"][0]
    accepted = decision(initial, record_kind="HUMAN_RESEARCH_DECISION")
    state = replay(bars, (accepted,), as_of=until(bars[:8]), **args)["current_state"]
    proof = scoped_proof(bars, old, bars[9].end, "HUMAN_RESEARCH_EVIDENCE", state)
    args["protection_confirmations"] = (proof,)
    generated = bars[10].end + US
    p = replay(bars, (accepted,), as_of=generated, **args)["proposals"][-1]
    assert p["action"] == "LOCK"
    new = protection_band(bars, "replacement", generated, "REVIEW_PENDING")
    lock_ack = decision(p, decision_id="human-lock", record_kind="HUMAN_RESEARCH_DECISION")
    result = replay(bars, (accepted, lock_ack), as_of=until(bars),
                    **(args | dict(protection_bands=(old, new))))
    assert result["proposals"][-1]["expiry_reason"] == "PROTECTION_RANGE_REVIEW_PENDING"
    assert result["decisions"][-1]["reason"] == "PROTECTION_RANGE_REVIEW_PENDING"
    assert [t["action"] for t in result["transitions"]] == ["ENTER_LONG"]


def test_external_human_evidence_proposes_only_and_risk_exit_has_priority():
    bars = lock_restore_bars()[:11]
    end = until(bars)
    entry = replay(bars, as_of=until(bars[:8]), protection_confirmations=())["proposals"][0]
    decisions = [decision(entry, record_kind="HUMAN_RESEARCH_DECISION")]
    entered = replay(bars, decisions, as_of=until(bars[:8]), protection_confirmations=())
    proof = replace(protection_for(bars), state_fingerprint=fingerprint(entered["current_state"]),
                    record_kind="HUMAN_RESEARCH_EVIDENCE")
    observed = replay(bars, decisions, as_of=end, protection_confirmations=(proof,))
    lock = observed["proposals"][-1]
    assert lock["action"] == "LOCK" and lock["status"] == "PENDING"
    assert [row["action"] for row in observed["transitions"]] == ["ENTER_LONG"]
    synthetic = decision(lock, decision_id="lock", record_kind="TEST_FIXTURE")
    denied = replay(bars, decisions + [synthetic], as_of=end, protection_confirmations=(proof,))
    assert denied["decisions"][-1]["reason"] == "HUMAN_DECISION_REQUIRED"
    approved = replay(bars, decisions + [synthetic | {"record_kind": "HUMAN_RESEARCH_DECISION"}],
                      as_of=end, protection_confirmations=(proof,))
    assert [row["action"] for row in approved["transitions"]] == ["ENTER_LONG", "LOCK"]
    risk_bars = bars[:10] + [bar(10, 104, 106, 99, 100)]
    priority = replay(risk_bars, decisions, as_of=end, protection_confirmations=(proof,))
    assert priority["proposals"][-1]["action"] == "CLEAR"
    assert priority["proposals"][-1]["reason"] == "RISK_INVALID"


def test_future_protection_validation_respects_as_of_and_single_step_uses_same_checks():
    bars = lock_restore_bars()
    proof = protection_for(bars)
    wrong_contract = replace(proof, contract="I2701")
    early = until(bars[:8])
    assert replay(bars, as_of=early, protection_confirmations=(wrong_contract,)) == replay(
        bars, as_of=early, protection_confirmations=(),
    )
    state = replay(bars, as_of=early, timely_fixture=True, protection_confirmations=())["current_state"]
    with pytest.raises(ValueError, match="PROTECTION_CONFIRMATION_CONTRACT_MISMATCH"):
        evaluate(state, bars, 10, timely_fixture=True, protection_confirmations=(wrong_contract,))
    with pytest.raises(ValueError, match="HUMAN_PROTECTION_EVIDENCE_REQUIRED"):
        evaluate(state, bars, 10, protection_confirmations=(proof,))
    with pytest.raises(ValueError, match="BOOLEAN_MODE_REQUIRED"):
        evaluate(state, bars, 10, timely_fixture="False", protection_confirmations=(proof,))
    foreign_bars = [replace(item, contract="I2701") for item in bars]
    with pytest.raises(ValueError, match="PROTECTION_STATE_CONTRACT_MISMATCH"):
        evaluate(state, foreign_bars, 10, timely_fixture=True, protection_confirmations=(wrong_contract,))


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


def held_clock_bars():
    return lock_restore_bars()[:11] + [
        bar(i, 103, 109, 101, 104) for i in range(11, 29)
    ] + [bar(29, 104, 105, 102, 104), bar(30, 104, 109, 101, 106)] + [
        bar(i, 103, 109, 101, 104) for i in range(31, 42)
    ]


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
@pytest.mark.parametrize("clock, exit_index", [
    (None, 19), ("DEFER_WHILE_LOCKED", 31), ("PAUSE_WHILE_LOCKED", 39),
])
def test_held_clock_counts_completed_bars_before_and_after_restore(side, clock, exit_index):
    b = held_clock_bars()
    if side == "SHORT":
        b = [replace(x, open=210 - x.open, high=210 - x.low,
                     low=210 - x.high, close=210 - x.close) for x in b]
    result = replay(b, as_of=until(b), timely_fixture=True, clock=clock)
    cycle = result["transitions"][0]["after"]["cycle_id"]
    rows = [t for t in result["transitions"]
            if cycle in (t["before"]["cycle_id"], t["after"]["cycle_id"])]
    assert [t["action"] for t in rows] == ["ENTER_" + side, "LOCK"] + (
        ["UNLOCK_" + side] if clock else []
    ) + ["CLEAR"]
    assert rows[-1]["reason"] == "PLAN_EXPIRED"
    assert rows[-1]["known_at"] == (b[exit_index].end + 2 * US).isoformat()
    if clock:
        assert rows[2]["known_at"] == (b[30].end + 2 * US).isoformat()
        assert rows[2]["after"]["lock_intervals"] == [[10, 30]]
        prefix = replay(b, as_of=b[24].end + US, timely_fixture=True, clock=clock)
        checkpoint = json.loads(json.dumps(prefix["checkpoint"]))
        assert checkpoint["current_state"]["lock_intervals"] == [[10, None]]
        assert replay(b, as_of=until(b), timely_fixture=True, clock=clock,
                      checkpoint=checkpoint) == result
        assert rows[-1]["after"]["lock_intervals"] == []


@pytest.mark.parametrize("clock", ["DEFER_WHILE_LOCKED", "PAUSE_WHILE_LOCKED"])
def test_hard_risk_and_target_still_clear_locked_legs(clock):
    b = held_clock_bars()[:31]
    for closing_bar, reason in (
        (bar(30, 104, 108, 99, 100), "RISK_INVALID"),
        (bar(30, 104, 110, 100, 110), "RANGE_TARGET"),
    ):
        series = b[:30] + [closing_bar]
        result = replay(series, as_of=until(series), timely_fixture=True, clock=clock)
        assert result["transitions"][-2]["action"] == "LOCK"
        assert result["transitions"][-1]["action"] == "CLEAR"
        assert result["transitions"][-1]["reason"] == reason


@pytest.mark.parametrize("clock", ["DEFER_WHILE_LOCKED", "PAUSE_WHILE_LOCKED"])
def test_rejected_lock_does_not_suspend_clock(clock):
    b = held_clock_bars()[:20]
    proposal = replay(b, as_of=until(b[:8]), clock=clock)["proposals"][0]
    entry = decision(proposal, record_kind="HUMAN_RESEARCH_DECISION")
    result = replay(b, [entry], as_of=until(b[:11]), clock=clock)
    proposal = result["proposals"][-1]
    assert proposal["action"] == "LOCK"
    rejected = decision(proposal, decision_id="reject-lock", decision="REJECT",
                        record_kind="HUMAN_RESEARCH_DECISION")
    result = replay(b, [entry, rejected], as_of=until(b), clock=clock)
    assert result["current_state"]["lock_intervals"] == []
    assert [t["action"] for t in result["transitions"]] == ["ENTER_LONG"]
    assert result["proposals"][-1]["reason"] == "PLAN_EXPIRED"


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
