from dataclasses import replace
from datetime import timedelta

import pytest

from guiyi_quant.newow.decision_adapter import (
    ExecutionContext,
    V2Strategy,
    seed_decision_state,
    step_completed,
)
from guiyi_quant.newow.product_contracts import ActionKind, MainState

from .test_v2_completed_market import D, bar, clock, historical, window


def context(item, *, strategies=tuple(V2Strategy), position=0, **changes):
    return replace(ExecutionContext(
        scope_id="offline-test", config_revision="cfg1", strategies=strategies,
        execution_strategy=V2Strategy.OSCILLATION if V2Strategy.OSCILLATION in strategies else strategies[0],
        account_as_of=item.payload.available_at, account_ref="account-1",
        fill_prefix_ref="empty", position=D(position), position_contract=item.physical_contract,
    ), **changes)


def test_same_completed_bar_does_not_advance_again():
    item = historical(bar(clock(9, 5)), window("5m"))
    initial = seed_decision_state()
    state, decisions = step_completed(initial, item, context(item))
    assert tuple(decision.strategy for decision in decisions) == tuple(V2Strategy)
    assert all(not decision.execution_candidate for decision in decisions)
    assert step_completed(state, item, context(item)) == (state, ())
    changed = historical(bar(clock(9, 5), "101"), window("5m"))
    with pytest.raises(ValueError, match="V2_DECISION_INPUT_CONFLICT"):
        step_completed(state, changed, context(changed))


def test_warmup_and_revision_cannot_leak_into_execution():
    item = historical(bar(clock(9, 5)), window("5m"), warmup=True)
    state, decisions = step_completed(seed_decision_state(), item, context(item))
    assert all(d.reason == "WARMUP_ONLY" and not d.execution_candidate for d in decisions)
    later = historical(bar(clock(9, 10)), window("5m"))
    with pytest.raises(ValueError, match="V2_DECISION_CONFIGURATION_CONFLICT"):
        step_completed(state, later, context(later, config_revision="cfg2"))
    with pytest.raises(ValueError, match="V2_DECISION_ACCOUNT_PREFIX_IN_FUTURE"):
        step_completed(state, later, context(
            later, account_as_of=later.payload.available_at + timedelta(seconds=1),
        ))


def test_trueup_is_shared_and_clear_respects_confirmed_position():
    market = window("5m")
    state = seed_decision_state()
    seen = []
    for index in range(10):
        item = historical(bar(clock(9, 5) + timedelta(minutes=5 * index)), market)
        state, decisions = step_completed(state, item, context(item))
        seen.append(decisions)
    trend, oscillation, fusion = seen[-1]
    assert "newow_oscillation_trueup_kernel111_v1" in oscillation.formula_versions
    assert oscillation.main_action is fusion.main_action is ActionKind.BUILD
    assert oscillation.state is MainState.BUILD
    assert oscillation.execution_candidate and not fusion.execution_candidate
    assert trend.input_ref == oscillation.input_ref == fusion.input_ref
    item = historical(bar(clock(9, 55)), market)
    _, flat = step_completed(state, item, context(item))
    _, long = step_completed(state, item, context(item, position=1))
    assert flat[1].main_action is long[1].main_action is ActionKind.CLEAR
    assert not flat[1].execution_candidate
    assert long[1].execution_candidate
    _, mismatched = step_completed(state, item, context(item, position=1, position_contract="FU2605"))
    assert not mismatched[1].execution_candidate
    assert mismatched[1].reason == "ACCOUNT_CONTRACT_MISMATCH"


def test_active_source_cannot_change_generation_inside_a_checkpoint():
    item = historical(bar(clock(9, 5)), window("5m"))
    state, _ = step_completed(seed_decision_state(), item, context(item))
    revised = historical(bar(clock(9, 10)), window("5m"), revision="canon-2")
    with pytest.raises(ValueError, match="V2_DECISION_SOURCE_CONFLICT"):
        step_completed(state, revised, context(revised))


def test_new_physical_contract_rewarms_without_carrying_fusion_position():
    market = window("5m")
    state = seed_decision_state()
    for index in range(10):
        item = historical(bar(clock(9, 5) + timedelta(minutes=5 * index)), market)
        state, decisions = step_completed(state, item, context(item))
    assert decisions[-1].main_action is ActionKind.BUILD
    rolled = historical(bar(clock(9, 55)), window("5m", owner="FU2605"), warmup=True)
    _, decisions = step_completed(state, rolled, context(rolled, unsettled_contracts=("FU2603",)))
    assert not any(action.execution_candidate for action in decisions)
    assert decisions[-1].state is MainState.FLAT
    assert decisions[-1].physical_contract == "FU2605"
    assert decisions[-1].reason == "WARMUP_ONLY"


def test_research_only_cannot_emit_an_execution_candidate():
    market = window("5m")
    state = seed_decision_state()
    for index in range(10):
        item = historical(bar(clock(9, 5) + timedelta(minutes=5 * index)), market)
        state, decisions = step_completed(state, item, context(item, execution_strategy=None))
    assert decisions[1].main_action is decisions[-1].main_action is ActionKind.BUILD
    assert not any(decision.execution_candidate for decision in decisions)


@pytest.mark.parametrize("frequency", ("5m", "15m", "30m", "60m", "1d", "1w"))
def test_chunked_restarted_and_independent_consumers_have_identical_prefixes(frequency):
    from copy import deepcopy

    from app.market_data.aggregation import SessionWindow

    markets = []
    for index in range(12):
        start = clock(9) + timedelta(days=7 * index)
        end = start + timedelta(hours=1)
        day = end.date()
        week = (day, end + timedelta(microseconds=1)) if frequency == "1w" else None
        markets.append(window(frequency, sessions=(SessionWindow(start, end),), day=day, completed_week=week))
    items = tuple(historical(bar(market.endpoints[-1], day=market.trading_day), market) for market in markets)

    def replay(inputs, state=None):
        if state is None:
            state = seed_decision_state()
        results = []
        for item in inputs:
            state, decisions = step_completed(state, item, context(item, execution_strategy=V2Strategy.DUAL_FUSION))
            results.append(decisions)
        return state, tuple(results)

    full_state, full = replay(items)
    midpoint, prefix = replay(items[:6])
    restored, suffix = replay(items[6:], deepcopy(midpoint))
    rebuilt, _ = replay(items[:6])
    assert restored == full_state
    assert prefix + suffix == full
    assert replay(items[6:], rebuilt) == (restored, suffix)
    assert tuple(decision.strategy for decision in full[-1]) == tuple(V2Strategy)
    assert full[9][-1].main_action is ActionKind.BUILD


def test_real_historical_and_live_transports_share_signal_semantics():
    from app.market_data.newow.v2_completed import from_observation

    from .test_v2_completed_market import observation

    market = window("5m")
    hs = ls = seed_decision_state()
    for end in market.endpoints[:12]:
        raw = bar(end)
        archived = historical(raw, market)
        observed = from_observation(observation(raw, market), market, generation="g1",
                                    as_of=end + timedelta(seconds=2))
        hs, h = step_completed(hs, archived, context(archived))
        ls, live = step_completed(ls, observed, context(observed))
        assert [(d.state, d.main_action, d.reason, d.execution_candidate) for d in h] == [
            (d.state, d.main_action, d.reason, d.execution_candidate) for d in live
        ]
        assert all(decision.input_ref == archived.fingerprint for decision in h)
        assert all(decision.input_ref == observed.fingerprint for decision in live)
        assert archived.fingerprint != observed.fingerprint


def test_fusion_reuses_formula_steps_without_recomputing_the_prefix(monkeypatch):
    from guiyi_quant.newow import decision_adapter

    actual = decision_adapter.replay_step
    calls = []

    def count(identity, state, item, **options):
        calls.append((identity.strategy.value, item.bar.bar_end))
        return actual(identity, state, item, **options)

    monkeypatch.setattr(decision_adapter, "replay_step", count)
    state = seed_decision_state()
    market = window("5m")
    for end in market.endpoints[:12]:
        item = historical(bar(end), market)
        state, _ = step_completed(state, item, context(item))
        state, output = step_completed(state, item, context(item))
        assert output == ()
    assert calls == [(strategy, end) for end in market.endpoints[:12]
                     for strategy in ("trend", "oscillation")]


def test_frozen_fu2603_actions():
    import gzip
    import io
    import os
    import pickle
    from datetime import date, datetime, timezone
    from decimal import Decimal
    from hashlib import sha256
    from pathlib import Path

    from app.market_data.domain import CanonicalBar
    from app.market_data.live_market import LiveBarObservation
    from app.market_data.newow.v2_completed import HistoricalAvailability, completed_bucket, from_historical_bar

    root = os.environ.get("GUIYI_P2_FROZEN_FU")
    if root is None:
        pytest.skip("set GUIYI_P2_FROZEN_FU to verify the existing P0/P1-A sample")
    source = Path(root)
    expected = {
        "fu-15m-manifest.json": "589d6dcbfb59d31c48b8fba8c949723cc005df30c73c3c38d40cce0c744e337e",
        "fu-15m-000-FU2603.pickle.gz": "ce658bf3d9b672097cf03af660fec27e591c89a675e66a92d9416c02db2fd36f",
        "facts-attempt-001/FU2603.json": "b28f860978fe2d131001f925233d02ffe10c9f5f50111d9a6bf90671e1bd4335",
    }
    archive_bytes = {}
    for name, digest in expected.items():
        archive_bytes[name] = (source / name).read_bytes()
        assert sha256(archive_bytes[name]).hexdigest() == digest
    raw = gzip.decompress(archive_bytes["fu-15m-000-FU2603.pickle.gz"])
    payload_ref = sha256(raw).hexdigest()
    assert payload_ref == "114d2ee9a7da5adcf5113570d80ba4d59bad11302c4f5161fda765c10379d908"
    types = {
        ("datetime", cls.__name__): cls for cls in (date, datetime, timedelta, timezone)
    } | {("decimal", "Decimal"): Decimal}

    class FrozenUnpickler(pickle.Unpickler):
        def find_class(self, module, name):
            return types[module, name]

    archive = FrozenUnpickler(io.BytesIO(raw)).load()
    assert (archive["product"], archive["contract"], archive["gaps"]) == ("fu", "FU2603", [])
    market = window("5m")
    prefix = {
        row["time"]: LiveBarObservation(CanonicalBar(
            row["time"], row["day"], row["open"], row["high"], row["low"], row["close"],
            row["volume"], None, None,
        ), "FU2603")
        for row in archive["minutes"]
        if row["day"] == market.trading_day and clock(9) < row["time"] <= clock(9, 35) and row["eligible"]
    }
    assert len(prefix) == 35
    state = seed_decision_state()
    actions = []
    for end in market.endpoints[:7]:
        minutes = tuple(prefix[end - timedelta(minutes=offset)] for offset in range(4, -1, -1))
        finished = completed_bucket(minutes, market, through=end)
        available = end + timedelta(seconds=2)
        item = from_historical_bar(
            finished, market, revision=payload_ref, source_ref=payload_ref,
            availability=HistoricalAvailability(available, "p1-intraday-two-seconds"),
            as_of=available, verified_lifecycle=True,
        )
        state, (decision,) = step_completed(state, item, context(
            item, strategies=(V2Strategy.TREND,), position=int(end == clock(9, 35)),
        ))
        if decision.main_action:
            actions.append((end, decision.main_action, decision.reason, decision.execution_candidate))
    assert actions == [
        (clock(9, 20), ActionKind.CLEAR, "INITIAL_CLEAR_NO_ENTRY", False),
        (clock(9, 30), ActionKind.BUILD, "BUILD", True),
        (clock(9, 35), ActionKind.CLEAR, "CLEAR", True),
    ]


@pytest.mark.parametrize(("market_size", "deployment_size"), ((60, 16), (70, 20)))
def test_capacity_fixture_reaches_every_strategy_period(market_size, deployment_size):
    from string import ascii_lowercase

    from app.market_data.newow.v2_scope import Deployment, Scope, validate_scope

    products = tuple(a + b for a in ascii_lowercase for b in ascii_lowercase)[:market_size]
    frequencies = ("5m", "15m", "30m", "60m", "1d", "1w")
    deployments = tuple(
        Deployment(product, tuple(V2Strategy)[index % 3], frequencies[index % 6])
        for index, product in enumerate(products[:deployment_size])
    )
    scope = validate_scope(
        Scope("fixture-capacity", products, deployments), supported=products, retired=(),
        isolated=market_size == 70,
    )
    ownership = {item.product: item for item in scope.deployments}
    decision_keys = set()
    for product in scope.market_products:
        contract = product.upper() + "2603"
        owner = ownership.get(product)
        for frequency in frequencies:
            week = (clock(15).date(), clock(15) + timedelta(microseconds=1)) if frequency == "1w" else None
            market = replace(window(frequency, completed_week=week), product=product,
                             contract=contract, owner_segment_id=contract)
            item = historical(bar(market.endpoints[-1]), market)
            selected = owner.strategy if owner is not None and owner.frequency == frequency else None
            _, decisions = step_completed(seed_decision_state(), item, context(
                item, config_revision=scope.revision, execution_strategy=selected,
            ))
            decision_keys.update(decision.decision_id for decision in decisions)
    assert len(decision_keys) == market_size * len(frequencies) * len(V2Strategy)


def test_core_does_not_use_a_prefix_known_later_than_the_new_bar():
    market = window("5m")
    first = historical(bar(clock(9, 5)), market, delay=timedelta(minutes=7))
    state, _ = step_completed(seed_decision_state(), first, context(first))
    second = historical(bar(clock(9, 10)), market)
    with pytest.raises(ValueError, match="V2_DECISION_AVAILABILITY_OUT_OF_ORDER"):
        step_completed(state, second, context(second))


def test_forward_handoff_and_admission_leave_one_decision_per_endpoint():
    from app.market_data.newow.v2_completed import Admission, CompletedStream, consume_completed, from_observation

    from .test_v2_completed_market import observation

    market = window("5m")
    prior = historical(bar(clock(9, 5)), market, warmup=True)
    _, seeded, outcome, decisions = consume_completed(
        CompletedStream(), seed_decision_state(), prior, context(prior), expected=prior.bar_end,
    )
    assert outcome is Admission.ACCEPTED and all(d.reason == "WARMUP_ONLY" for d in decisions)
    raw = bar(clock(9, 10))
    item = from_observation(observation(raw, market), market, generation="g1", as_of=clock(9, 10, 2))
    next_market, next_decisions, outcome, decisions = consume_completed(
        CompletedStream(), seeded, item, context(item),
        expected=market.next_after(prior.bar_end), fresh=True,
    )
    assert outcome is Admission.ACCEPTED
    assert next_market.through == next_decisions.computed_through == item.bar_end
    assert all(d.previous_state_ref == seeded.strategy_state.reference for d in decisions)
    assert consume_completed(
        next_market, next_decisions, item, context(item),
        expected=market.next_after(item.bar_end), fresh=True,
    ) == (next_market, next_decisions, Admission.DUPLICATE, ())


def test_historical_owner_prewarm_can_overlap_the_previous_owner():
    from app.market_data.newow.v2_completed import iter_historical_segments

    old_end = historical(bar(clock(9, 55)), window("5m"))
    new_market = window("5m", owner="FU2605")
    new_prefix = historical(bar(clock(9, 5)), new_market, warmup=True)
    new_observation = historical(bar(clock(10)), new_market)
    observed = []
    for owner, inputs in iter_historical_segments((old_end, new_prefix, new_observation)):
        state = seed_decision_state()
        for item in inputs:
            state, decisions = step_completed(state, item, context(item))
            observed.extend((owner[0], decision.bar_end, decision.reason) for decision in decisions)
    assert [item[1] for item in observed[::3]] == [clock(9, 55), clock(9, 5), clock(10)]
    assert observed[3] == ("FU2605", clock(9, 5), "WARMUP_ONLY")


def test_restart_without_the_active_market_checkpoint_cannot_bypass_a_gap():
    from app.market_data.newow.v2_completed import Admission, CompletedStream, consume_completed, from_observation

    from .test_v2_completed_market import observation

    market = window("5m")
    first_raw = bar(clock(9, 5))
    first = from_observation(observation(first_raw, market), market, generation="g1", as_of=clock(9, 5, 2))
    active_market, strategy, result, _ = consume_completed(
        CompletedStream(), seed_decision_state(), first, context(first),
        expected=first.bar_end, fresh=True,
    )
    assert result is Admission.ACCEPTED
    later_raw = bar(clock(9, 15))
    later = from_observation(observation(later_raw, market), market, generation="g1", as_of=clock(9, 15, 2))
    blocked, _, reason, _ = consume_completed(
        active_market, strategy, later, context(later), expected=clock(9, 10), fresh=True,
    )
    assert blocked.blocked and reason is Admission.GAP
    with pytest.raises(ValueError, match="V2_MARKET_DECISION_CHECKPOINT_CONFLICT"):
        consume_completed(CompletedStream(), strategy, later, context(later), expected=later.bar_end, fresh=True)
