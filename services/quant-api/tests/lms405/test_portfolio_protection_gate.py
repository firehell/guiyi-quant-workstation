from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms405.protection_band import ProtectionBandUpdate
from guiyi_quant.lms_near405 import CarryInSeed, ScheduledProtectionConfirmation, replay
from lms405_portfolio_protection_gate import JOINT_CONTACT, advance_due, price_admission, replay_with_price_context
from lms405_right_side_study import ONE, US, at


START = at("2026-07-10T09:00")
BAND = ProtectionBandUpdate("SA2609", "fixture", "PROTECTION", START - ONE, START - ONE,
                            "FIXTURE", "SHORT", Decimal(1079), Decimal(1087))


def minute(n, price):
    end = START + n * ONE
    price = Decimal(price)
    return Bar("SA2609", end, price, price, price, price, start=end - ONE)


def signal(n, close):
    return dict(shape_end=START + (n - 5) * ONE, available_at=START + n * ONE + US, close=Decimal(close))


def test_opening_beyond_is_a_directional_reach_without_range_contact():
    bars = [minute(n, 1089) for n in range(1, 12)]
    result = price_admission(bars, BAND, signal(11, 1089))
    assert result["status"] == "REACH_WITHOUT_RANGE_CONTACT"
    assert result["loose_due_at"] == bars[0].end + US
    assert result["ordinary_due_at"] is None


def test_contact_on_confirmation_minute_cannot_be_used_earlier():
    bars = [minute(n, 1088) for n in range(1, 11)]
    bars.append(minute(11, 1087))
    assert price_admission(bars, BAND, signal(11, 1087))["ordinary_due_at"] is None
    assert price_admission(bars, BAND, signal(12, 1087))["ordinary_due_at"] == bars[-1].end + US


def test_joint_close_uses_only_a_scoped_completed_minute():
    bars = [minute(n, 1088) for n in range(1, 11)]
    contact, future = minute(11, 1087), minute(12, 1081)
    event = signal(11, 1087)
    result = price_admission([*bars, contact], BAND, event, allow_joint_close=True)
    assert result["ordinary_due_at"] == contact.end + US == event["available_at"]
    assert result == price_admission([*bars, contact, future], BAND, event, allow_joint_close=True)
    assert price_admission([*bars, future], BAND, event, allow_joint_close=True)["ordinary_due_at"] is None
    assert price_admission([*bars, contact], BAND, event, position_since=bars[5].end + US,
                           allow_joint_close=True)["ordinary_due_at"] is None
    unfinished = SimpleNamespace(end=contact.end, completed=False, contract=contact.contract)
    for bad in (unfinished, replace(contact, contract="SH2609")):
        with pytest.raises(ValueError, match="PROTECTION_JOINT_CLOSE_BAR_IDENTITY_MISMATCH"):
            price_admission([*bars, bad], BAND, event, allow_joint_close=True)


@pytest.mark.parametrize("reopened", [False, True])
def test_scheduled_proof_is_prefix_stable_and_cannot_move_past_a_missing_driver(reopened):
    def market_bar(n, period, values):
        end = START + n * ONE
        return Bar("SA2609", end, *map(Decimal, values), start=end - period * ONE)

    fives = [market_bar(n, 5, (104, 110, 100, 106) if n <= 40 else (104, 108, 103, 106))
             for n in range(5, 66, 5)]
    confirmation = 53 if reopened else 51
    if reopened:
        fives = [b for b in fives if b.end not in (START + 45 * ONE, START + 50 * ONE)]
    minutes = [market_bar(n, 1, (106, 107, 104, 107) if n == confirmation else (104, 106, 103, 106))
               for n in range(51 if reopened else 41, 57)]
    band = replace(BAND, lower=Decimal(107), upper=Decimal(108))
    seed = CarryInSeed("SA2609", START + 40 * ONE + 2 * US, "SHORT", False, "TEST_FIXTURE")
    event = signal(confirmation, 107) | {"shape_end": START + (confirmation - 1) * ONE}
    event_known = event["available_at"]
    price = price_admission(minutes, band, event, shape_step=ONE, allow_joint_close=True)
    events = {(event_known - US, "LONG"): dict(area=band, price=price, event=event, m_reference=None,
                                              close_also_in_m=False)}
    args = dict(due_field=JOINT_CONTACT, seed=seed, period=1, scheduled=True)
    full = {1: minutes, 5: fives}
    prefixes = {}
    for cutoff in (event_known, event_known + US):
        prefix = {p: [bar for bar in rows if bar.end + US <= cutoff] for p, rows in full.items()}
        observed = {key: row for key, row in events.items() if row["event"]["available_at"] < cutoff}
        result, attempts = replay_with_price_context(prefix, (band,), observed, cutoff=cutoff, **args)
        assert (result, attempts) == replay_with_price_context(full, (band,), events, cutoff=cutoff, **args)
        assert len(attempts) == (cutoff > event_known)
        assert result["transitions"] == []
        prefixes[cutoff] = result["checkpoint"]

    driver_end = START + 55 * ONE
    cutoff = START + 65 * ONE + 2 * US
    settled, (attempt,) = replay_with_price_context(full, (band,), events, cutoff=cutoff, **args)
    proof = ScheduledProtectionConfirmation(**attempt["proof"])
    assert proof.due_at == event_known and proof.known_at == event_known + US and proof.driver_end == driver_end
    (lock,) = settled["transitions"]
    assert lock["action"] == "LOCK" and lock["known_at"] == (driver_end + 2 * US).isoformat()
    pending, _ = replay_with_price_context(full, (band,), events, cutoff=driver_end + US, **args)
    assert pending["transitions"] == []
    for checkpoint in prefixes.values():
        assert settled == replay(fives, as_of=cutoff, checkpoint=checkpoint, carry_in=seed,
                                 carry_exit_evidence=(), protection_bands=(band,), timely_fixture=True,
                                 protection_confirmations=(proof,))

    missing_fives = [bar for bar in fives if bar.end != driver_end]
    missed, attempts = replay_with_price_context(full | {5: missing_fives}, (band,), events, cutoff=cutoff, **args)
    assert attempts == [attempt]
    assert missed["transitions"] == []

    update_at = START + 54 * ONE
    superseded = replace(band, revision="new plan", known_at=update_at, effective_after=update_at)
    stale, attempts = replay_with_price_context(full, (band, superseded), events, cutoff=cutoff, **args)
    assert attempts == [attempt]
    assert stale["transitions"] == []


def test_scheduled_empty_proof_prefix_uses_only_the_first_completed_driver():
    fives = [Bar("SA2609", START + n * ONE, Decimal(107), Decimal(108), Decimal(106), Decimal(107),
                 start=START + (n - 5) * ONE) for n in (5, 10)]
    args = dict(cutoff=fives[0].end + US, due_field="ordinary_due_at", scheduled=True)
    prefix = replay_with_price_context({1: [], 5: fives[:1]}, (), {}, **args)
    assert prefix == replay_with_price_context({1: [], 5: fives}, (), {}, **args)


def test_shared_edge_preserves_protection_scope_and_session_boundary():
    old_contact = minute(1, 1087)
    new_segment = [minute(n, 1089) for n in range(20, 31)]
    assert price_admission([old_contact, *new_segment], BAND, signal(30, 1089))["first_contact_at"] is None
    new_segment[1] = minute(21, 1087)
    at_shared_edge = price_admission(new_segment, BAND, signal(30, 1087))
    assert at_shared_edge["ordinary_due_at"] == new_segment[1].end + US
    strict_m_side = price_admission(new_segment, BAND, signal(30, 1088))
    assert strict_m_side["ordinary_due_at"] is None


def test_contact_before_current_position_cannot_support_its_protection():
    bars = [minute(1, 1087), *[minute(n, 1088) for n in range(2, 12)]]
    result = price_admission(bars, BAND, signal(12, 1087), position_since=bars[0].end + US)
    assert result["first_contact_at"] is None
    assert result["ordinary_due_at"] is None


def test_advance_requires_explicit_plan_and_a_complete_confirming_bar_before_the_zone():
    authorized = replace(BAND, contract="FG2701", revision="A5356884629782554")
    bar = replace(minute(20, 1078), contract="FG2701")
    before = {"status": "NO_PRIOR_DIRECTIONAL_REACH"}
    assert advance_due(bar, authorized, before) == bar.end
    assert advance_due(bar, replace(authorized, revision="unknown"), before) is None
    assert advance_due(replace(bar, high=Decimal(1079)), authorized, before) is None
    assert advance_due(bar, authorized, {"status": "REACH_WITHOUT_RANGE_CONTACT"}) is None


def test_advance_rejects_a_foreign_confirmation_bar():
    authorized = replace(BAND, contract="FG2701", revision="A5356884629782554")
    with pytest.raises(ValueError, match="PROTECTION_ADVANCE_CONFIRMATION_BAR_MISMATCH"):
        advance_due(minute(20, 1078), authorized, {"status": "NO_PRIOR_DIRECTIONAL_REACH"})
