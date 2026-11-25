from lms405_opening_portfolio_replay import apply_scenario, opening_selection, scenario_permission, state_before
from lms405_right_side_study import ONE, US, at


START = at("2026-10-23T21:00")


def opening_case():
    reached, shape_end, confirmed = (START + n * ONE for n in (1, 3, 4))
    first = dict(shape_end=shape_end.isoformat(), confirmed_at=confirmed.isoformat(),
                 available_at=(confirmed + US).isoformat())
    return {"contract": "TA2701", "start": START.isoformat(), "direction": "LONG",
            "clocks": {"prior": {"first_range_reaches_direction": reached.isoformat()}},
            "gates": {"keybar:1m_to_1m": confirmed.isoformat(), "prior:fresh_1m_to_1m_after_reach": confirmed.isoformat()},
            "geometric_candidates": {"keybar:1m_to_1m": [first]}}


def test_opening_author_permission_unknown_and_fixture_is_not_available_same_time():
    case = opening_case()
    signal = opening_selection(case, "prior", "DIRECTIONAL_PRICE_REACH", "1m_to_1m")
    known = signal["confirmed_at"] + US
    assert scenario_permission("case", "TA2701", signal, known, explicit_fixture_permission=True)["value"] is None
    assert scenario_permission("case", "TA2701", signal, known + US, explicit_fixture_permission=True)["value"] is True
    steps, audit = apply_scenario([], [], {}, case, "DIRECTIONAL_PRICE_REACH", "1m_to_1m", "prior",
                                  as_of=known + US, explicit_fixture_permission=False)
    assert steps == [] and audit["status"] == "AUTHOR_PERMISSION_AND_SIGNAL_UNKNOWN"


def test_transition_same_time_as_quote_does_not_change_before_state():
    seed = {"long": "0", "short": "0"}
    step = {"known_at": START.isoformat(), "after": {"long": "1", "short": "0"}}
    assert state_before([step], seed, START) == seed
    assert state_before([step], seed, START + US) == step["after"]
