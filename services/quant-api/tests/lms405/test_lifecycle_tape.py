from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from guiyi_quant.lms405 import Zone
from guiyi_quant.lms405.public_plan_handoff import Publication
from lms405_lifecycle_tape import replay
from lms405_portfolio_lifecycle import candidate, next_cursor, seed
from lms405_right_side_study import ONE, US


OPEN = datetime(2026, 10, 22, 13, tzinfo=timezone.utc)
CONTRACT = "FG2701"


def plan(label, at, *, withheld=False):
    zone = None if withheld else Zone(label, CONTRACT, Decimal(829), Decimal(836), at, label)
    return Publication(label, CONTRACT, at, at, label, zone)


def test_topup_cannot_reuse_earlier_authority_or_apply_twice_and_restart_matches():
    root = seed("case", CONTRACT, OPEN, short=20)
    active = plan("zone", OPEN)
    advance = candidate("advance", root, "PROTECT_ADD", 7, OPEN + ONE, plan=active)
    topup = candidate("topup", next_cursor(advance), "PROTECT_ADD", 13, OPEN + 2 * ONE, plan=active)
    stale = replace(topup, observation="reused", at=topup.at - US, approval=advance.approval)
    duplicate = replace(topup, observation="duplicate", at=topup.at + US)
    args = ((root,), (advance, stale, topup, duplicate), (active,))
    cut = OPEN + 3 * ONE
    full, terminal = replay(*args, cutoff=cut, allow_test_fixture=True)
    assert [row.get("status") for row in full][1:] == [
        "CONDITIONAL_ACTION", "AUTHORITY_SCOPE_MISMATCH", "CONDITIONAL_ACTION", "STALE_OR_UNAVAILABLE_POSITION",
    ]
    head, checkpoint = replay(*args, cutoff=topup.at, allow_test_fixture=True)
    assert checkpoint[root.episode].protected_long == 7
    tail, restored = replay(*args, cutoff=cut, start=topup.at, cursors=checkpoint, allow_test_fixture=True)
    assert head + tail == full and restored == terminal
    assert terminal[root.episode].position.long == terminal[root.episode].position.short == 20


def test_later_pause_blocks_in_flight_authority_and_time_limit_prevents_reuse():
    root = seed("case", CONTRACT, OPEN, short=20)
    active = plan("active", OPEN)
    touch = OPEN + ONE
    protection = candidate("protect", root, "PROTECT_ADD", 5, touch, plan=active)
    suspended = plan("paused", touch + US, withheld=True)
    expired = replace(protection, observation="expired", at=protection.expires_at)
    rows, terminal = replay((root,), (protection, expired), (active, suspended),
                            cutoff=OPEN + 3 * ONE, allow_test_fixture=True)
    assert [row.get("status") for row in rows][1:] == ["NOT_PERMITTED", "ATTEMPT_EXPIRED"]
    assert terminal[root.episode] == root


def test_withdraw_only_assigned_protection_and_preserve_original_leg():
    root = seed("case", CONTRACT, OPEN, long=20, short=20, protection=7)
    withdraw = candidate("withdraw", root, "PROTECT_WITHDRAW", 7, OPEN + ONE)
    after = next_cursor(withdraw)
    assert (after.position.long, after.position.short, after.protected_long) == (13, 20, 0)
    invalid = replace(withdraw, quantity=Decimal(8))
    with pytest.raises(ValueError, match="LIFECYCLE_WITHDRAW_UNASSIGNED_PROTECTION"):
        invalid.supported_projection()


def test_renamed_attempt_or_forged_checkpoint_cannot_apply_valid_permission():
    root = seed("case", CONTRACT, OPEN, short=20)
    active = plan("zone", OPEN)
    advance = candidate("advance", root, "PROTECT_ADD", 7, OPEN + ONE, plan=active)
    renamed = replace(advance, id="different_decision", at=advance.at + US)
    topup = candidate("topup", next_cursor(advance), "PROTECT_ADD", 13, OPEN + 2 * ONE, plan=active)
    args = ((root,), (renamed, topup), (active,))
    cut = OPEN + 3 * ONE
    rows, terminal = replay(*args, cutoff=cut, allow_test_fixture=True)
    assert [row.get("status") for row in rows][1:] == [
        "AUTHORITY_SCOPE_MISMATCH", "STALE_OR_UNAVAILABLE_POSITION",
    ]
    assert terminal[root.episode] == root
    with pytest.raises(ValueError, match="LIFECYCLE_CHECKPOINT_PREFIX_MISMATCH"):
        replay(*args, cutoff=cut, start=topup.at, cursors={root.episode: next_cursor(advance)}, allow_test_fixture=True)
