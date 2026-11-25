from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from guiyi_quant.lms405 import Position
from guiyi_quant.lms405.public_conditions import PublicCase
from lms405_protection_layers_replay import ORDER, ROUTES, fact
from lms405_protection_next_night_replay import admitted_fixture, signal_route
from lms405_right_side_study import US


def test_advance_uses_only_information_known_at_signal():
    band = Decimal(1490), Decimal(1501)
    event = {"close": "1467", "pre_touch_arm": True, "survives_both_diagnostics": False}

    assert signal_route(event, band) == "ADVANCE"
    assert signal_route(event | {"survives_both_diagnostics": True}, band) == "ADVANCE"
    assert signal_route(event | {"pre_touch_arm": False}, band) is None
    assert signal_route({"close": "1501"}, band) == "IN_BAND"
    assert signal_route({"close": "1502"}, band) is None


def test_deferred_projection_starts_only_after_touch_and_distinct_permission():
    def time(clock):
        return datetime.fromisoformat(f"2026-10-27T{clock}:00+08:00")

    published = time("17:39")
    case = PublicCase("case", "SH2701", "archived-plan", published, True, ("LOCK",), ROUTES, ORDER)
    before = Position("SH2701", short=Decimal(20))
    facts = (fact(case, "OPENING_CONTEXT", time("21:01"), "completed-bar"),
             fact(case, "PROTECTION_REFERENCE", published, case.source))
    band = Decimal(1490), Decimal(1501)
    touch = SimpleNamespace(start=time("21:28"), end=time("21:29"))
    event = dict(close="1467", pre_touch_arm=True, confirmed_at=time("21:21").isoformat(),
                 available_at=(time("21:21") + US).isoformat(), touch_known_at=(touch.end + US).isoformat(),
                 survives_both_diagnostics=True)

    replay, after = admitted_fixture(case, before, facts, [event], band, published, touch)
    deferred = replay["deferred_until_touch"]
    assert replay["first_projection_at"] == time("21:21") + 3 * US
    assert after.long == after.short == 20
    assert deferred["first_projection_at"] == touch.end + 3 * US
    assert all(row["after"] is None for row in deferred["trace"] if row["cutoff"] <= touch.end + 2 * US)

    for change, cross in (({"survives_both_diagnostics": False}, touch), ({}, None)):
        ended, _ = admitted_fixture(case, before, facts, [event | change], band, published, cross)
        assert ended["deferred_until_touch"] is None
        assert ended["first_projection_at"] == replay["first_projection_at"]
