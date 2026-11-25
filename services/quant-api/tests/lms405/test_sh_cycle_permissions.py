from dataclasses import replace
from decimal import Decimal

import pytest
from guiyi_quant.lms405 import Position
from guiyi_quant.lms405.handoff import Handoff
from lms405_right_side_study import US, at
from lms405_sh_cycle_permissions import project, protection_input, recovery_input


def inputs(*, recovery_fixture, protection_fixture, deferred=False):
    seed = at("2026-10-27T11:35")
    request = Handoff("RESUME_ORIGINAL", Position("SH2701", Decimal(20), Decimal(20)), "SHORT",
                      "old-plan", "original-cycle", None, seed, seed)
    old = dict(source_url="fixture:old-plan", published_at="2026-10-26T17:45:00+08:00")
    night = dict(source_url="fixture:new-plan", published_at="2026-10-27T17:38:00+08:00")
    day_signal, night_signal, touch = (at(f"2026-10-27T{clock}") for clock in ("14:34", "21:21", "21:29"))
    recovery_row = dict(confirmed_at=day_signal.isoformat(), available_at=(day_signal + US).isoformat())
    protection_row = dict(confirmed_at=night_signal.isoformat(), available_at=(night_signal + US).isoformat(),
                          touch_known_at=(touch + US).isoformat(), pre_touch_arm=True, survives_both_diagnostics=True)
    recovery = recovery_input(request, old, recovery_row, at("2026-10-27T15:00"), fixture=recovery_fixture)
    lock = protection_input(night, protection_row, at("2026-10-27T21:00"), at("2026-10-27T22:12"),
                            fixture=protection_fixture, defer=deferred)
    return request, dict(recovery=recovery, lock=lock)


@pytest.mark.parametrize(("recovery_fixture", "protection_fixture", "old", "new"), [
    (False, False, 20, 0),
    (True, False, 0, 0),
    (False, True, 20, 0),
    (True, True, 0, 20),
])
def test_protection_replacement_requires_both_permissions(recovery_fixture, protection_fixture, old, new):
    request, scope = inputs(recovery_fixture=recovery_fixture, protection_fixture=protection_fixture)
    row = project(request, **scope, as_of=at("2026-10-27T22:12"))
    assert (row["retained_old_long"], row["new_protection_long"]) == (old, new)
    assert row["original_short"] == Decimal(20)


def test_day_and_night_permissions_are_strictly_before_the_snapshot():
    request, scope = inputs(recovery_fixture=True, protection_fixture=True, deferred=True)
    day_permission = at("2026-10-27T14:34") + 2 * US
    night_permission = at("2026-10-27T21:29") + 2 * US
    assert project(request, **scope, as_of=day_permission)["retained_old_long"] == 20
    assert project(request, **scope, as_of=day_permission + US)["retained_old_long"] == 0
    assert project(request, **scope, as_of=night_permission)["new_protection_long"] == 0
    assert project(request, **scope, as_of=night_permission + US)["new_protection_long"] == 20

    # A delayed recovery decision cannot import an afternoon action into the night session.
    policy = scope["recovery"]["policy"]
    policy["approval"] = replace(policy["approval"], decided_at=night_permission, known_at=night_permission)
    late = project(request, **scope, as_of=night_permission + US)
    assert late["retained_old_long"] == 20 and late["new_protection_long"] == 0
