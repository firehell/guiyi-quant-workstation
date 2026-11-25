from decimal import Decimal

from guiyi_quant.lms405 import Position
from guiyi_quant.lms405.public_conditions import PublicCase
from lms405_protection_layers_replay import ORDER, ROUTES, START, US, assessment, fact, trace


def test_protection_waits_for_separate_permission_and_rejects_future_input():
    start = START
    case = PublicCase("study", "SH2701", "fixture", start, True, ("LOCK",), ROUTES, ORDER)
    before = Position("SH2701", short=Decimal(20))
    facts = [
        fact(case, "PROTECTION_REFERENCE", start, "fixture"),
        fact(case, "OPENING_CONTEXT", start + US, "fixture"),
        fact(case, "PA_PRICE_OBSERVATION", start + 2 * US, "fixture"),
        fact(case, "OPPOSITE_VPLUS", start + 3 * US, "fixture"),
        fact(case, "LOCK_PERMISSION", start + 4 * US, "fixture"),
    ]
    cut = start + 4 * US

    assert trace(case, before, facts, cut)[-1]["after"] is None
    assert all(row["cutoff"] <= cut for row in trace(case, before, facts, cut))
    assert assessment(case, before, facts, cut + US)["after"] == {"long": "20", "short": "20"}
