from dataclasses import replace
from datetime import datetime, timedelta, UTC
from decimal import Decimal
import json

import pytest

from guiyi_quant.lms405 import Bar
from lms405_counter_m_lot_roles import exit_projection
from lms405_portfolio_replay import (
    BOOK,
    CONTRACTS,
    batch_fixture_transitions,
    input_sources,
    observation_events,
    replay_portfolio,
    visible_legs,
)
from lms405_portfolio_task_exits import condition_comparison


T = datetime(2026, 10, 23, 2, tzinfo=UTC)


def test_unlisted_side_and_unknown_quantity_stay_distinct():
    legs = visible_legs({"OI2701": {"long": 40, "short": 40}, "TA2701": {"long": None},
                         "SH2701": {"short": 20}})
    assert legs["OI2701"]["displayed_signed_net"] == "0"
    assert legs["OI2701"]["visible_gross_lower_bound"] == "80"
    assert legs["TA2701"]["long_shown"] and legs["TA2701"]["long"] is None
    assert legs["TA2701"]["visible_gross_lower_bound"] is None
    assert not legs["SH2701"]["long_shown"] and legs["SH2701"]["displayed_signed_net"] is None
    assert legs["SH2701"]["visible_gross_lower_bound"] == "20"
    assert not legs["FG2701"]["short_shown"]


def test_book_joins_exact_sources_and_cutoff_does_not_import_earlier_quote_anchor():
    book = json.loads(BOOK.read_bytes())
    sources = input_sources()
    at_publication_plus_minute = datetime.fromisoformat("2026-10-27T11:35:00+08:00")
    visible = observation_events(book, sources, as_of=at_publication_plus_minute)
    assert not any(row["payload"]["source"] == "WRoAkcEppg" for row in visible)
    visible = observation_events(book, sources, as_of=at_publication_plus_minute + timedelta(microseconds=1))
    observed = next(row["payload"] for row in visible if row["payload"]["source"] == "WRoAkcEppg")
    assert observed["quote_anchor"] == "2026-10-27T11:30:00+08:00"
    assert observed["system"] is None and not observed["author_action_verified"]
    same_night = {row["payload"]["source"]: row["payload"] for row in visible
                  if row["payload"]["source"] in {"WRo2KQ43iX", "WRo2LIbP3s"}}
    assert same_night["WRo2KQ43iX"]["positions"]["TA2701"]["long"] == 34
    assert same_night["WRo2LIbP3s"]["positions"]["TA2701"]["long"] is None


def test_same_time_transitions_are_applied_as_one_batch():
    def row(contract, old, new, when):
        return dict(
            record_kind="TEST_FIXTURE", known_at=when.isoformat(), action="TEST",
            reason="fixture", proposal_id=contract,
            before=dict(zip(("contract", "long", "short"), (contract, *old), strict=True)),
            after=dict(zip(("contract", "long", "short"), (contract, *new), strict=True)),
        )

    oil_open = row("OI2701", (0, 0), (0, 1), T)
    rubber_open = row("RU2701", (0, 0), (1, 0), T)
    oil_lock = row("OI2701", (0, 1), (1, 1), T + timedelta(minutes=5))
    batches, state = batch_fixture_transitions([oil_lock, rubber_open, oil_open])
    assert len(batches) == 2
    assert batches[0]["payload"]["portfolio_units"]["directional_products"] == 2
    assert batches[1]["payload"]["portfolio_units"] == {
        "locked_products": 1, "directional_products": 1, "total_legs_units": "3",
    }
    assert state["RU2701"] == (Decimal(1), Decimal(0))
    with pytest.raises(ValueError, match="INCONSISTENT_FIXTURE_STATE"):
        batch_fixture_transitions([oil_open, oil_open])


def test_frozen_candidate_is_independent_of_observations_and_future_bars():
    def bar(index, values):
        start = T + timedelta(minutes=5 * index)
        return Bar("OI2701", start + timedelta(minutes=5), *map(Decimal, values), start=start)

    values = [(104, 110, 100, 106)] * 6 + [(103, 105, 101, 104), (104, 108, 102, 106), (106, 109, 99, 100)]
    bars = [bar(i, v) for i, v in enumerate(values)]
    inputs = {contract: [replace(b, contract=contract) for b in bars] for contract in CONTRACTS}
    prefix_end = bars[-2].end + timedelta(microseconds=3)
    until = bars[-1].end + timedelta(microseconds=3)
    empty = {"snapshots": [], "notices": []}
    book = {"snapshots": [{"source": "p", "table": "1", "system": "4.0.5", "legs": {"OI2701": {"short": 40}}}],
            "notices": []}
    sources = {"p": {"published_at": T.isoformat(), "source_url": "https://example.invalid/p"}}
    full = replay_portfolio(inputs, book, sources, as_of=until, timely_fixture=True)
    no_evidence = replay_portfolio(inputs, empty, {}, as_of=until, timely_fixture=True)
    prefix = replay_portfolio(inputs, book, sources, as_of=prefix_end, timely_fixture=True)
    assert full["contract_summaries"] == no_evidence["contract_summaries"]
    assert len(no_evidence["timeline"]) < len(full["timeline"])
    assert prefix["timeline"] == [row for row in full["timeline"] if datetime.fromisoformat(row["time"]) <= prefix_end]
    assert full["fixture_terminal_units"]["total_legs_units"] == "0"
    human = replay_portfolio(inputs, book, sources, as_of=until)
    assert not any(row["layer"] == "FIXTURE_STATE_BATCH" for row in human["timeline"])
    assert human["fills"] is None and human["admitted_author_action_samples"] == 0


def test_counter_m_comparison_requires_separate_exit_permission_without_clearing_protection():
    scenario = exit_projection("JM2701", 20, 20, 5)
    for cutoff in (T - timedelta(microseconds=1), T + timedelta(microseconds=2)):
        early = condition_comparison("JM2701", scenario, ("old", "later"), T, as_of=cutoff)
        assert early == dict(public_status="INDETERMINATE", public_after=None, fixture=None)
    comparison = condition_comparison("JM2701", scenario, ("old", "later"), T,
                                      as_of=T + timedelta(microseconds=4))
    assert comparison["public_status"] == "INDETERMINATE" and comparison["public_after"] is None
    assert comparison["fixture"]["permit"]["after"] == dict(long=15, short=20, net=-5, gross=35)
    assert comparison["fixture"]["deny"] == dict(status="NOT_PERMITTED", after=None)
    assert comparison["fixture"]["missing"] == dict(status="INDETERMINATE", after=None)
    assert comparison["whole_long_leg_comparator"] == dict(long=0, short=20, net=-20, gross=20)
    assert comparison["changes_remaining_exposure"]
