from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
from uuid import uuid4

import pytest

from app.simulation_center.execution_store import ExecutionStore, ExecutionStoreError
from app.simulation_center.store import connect
from guiyi_quant import htdy_account_execution as account
from guiyi_quant import htdy_execution as strategy
from guiyi_quant.htdy_account_execution import codec

T = datetime(2026, 10, 27, 1, tzinfo=UTC)
D = Decimal


@pytest.fixture
def connection():
    dsn = os.getenv("GUIYI_SIMULATION_ISOLATED_TEST_DSN")
    if not dsn:
        pytest.skip("isolated Simulation Center PostgreSQL required")
    with connect(dsn) as conn:
        yield conn


def initial(identity):
    readback = account.Readback(strategy.AccountSnapshot(identity, T, D(100_000), D(100_000)),
                               D(0), D(0), D(0), (), (), "offline-initial", T + timedelta(hours=3), True)
    return account.start(identity, ("RB",), T, readback)


def commands():
    observed = T + timedelta(hours=1, seconds=2)
    tick_at = observed + timedelta(seconds=1)
    valid_until = T + timedelta(hours=3)
    instrument = account.Instrument("RB", "RB2701", T, valid_until, "offline-instrument", D(1), D(10),
                                    D("0.1"), D("0.1"), D(3))
    session = account.Session("RB2701", T, valid_until, "offline-session", valid_until, True, True)
    quote = account.Quote("RB2701", tick_at, valid_until, "offline-quote", D(999), D(1000), 3, 3,
                          D(900), D(1100))
    return (
        ("owner", strategy.Owner("RB", "RB2701", T, "offline-owner")),
        ("signal", strategy.Signal("offline-signal", "RB", "RB2701", T + timedelta(hours=1), observed,
                                   None, ("buy",), "a" * 64)),
        ("tick", account.ContinuousTradeTickV1(tick_at, (account.ExecutionInput(instrument, session, quote),))),
    )


def claim_payload(store, effect):
    state = store.current()
    order = effect.order
    return {"order_id": order.order_id, "price": str(order.price), "quantity": order.quantity,
            "native_id": "2026-10-27:SHFE:1:-2:31", "contract": "RB2701", "exchange": "SHFE",
            "direction": "LONG", "offset": "OPEN", "state_hash": codec.digest(state),
            "proof": state.readback.source_id, "source": "OFFLINE_CTP_REHEARSAL", "claimed_at": state.clock.isoformat()}


def test_run_identity_is_offline_and_path_safe():
    with pytest.raises(ExecutionStoreError, match="OFFLINE_RUN_ID_INVALID"):
        ExecutionStore(None, "offline:production-account")
    store = ExecutionStore(None, "run-a")
    with pytest.raises(ExecutionStoreError, match="OFFLINE_ACCOUNT_IDENTITY_MISMATCH"):
        store.create(initial("native-account"))


@pytest.mark.isolated_postgresql
def test_commit_replay_and_claim_survive_a_new_connection(connection):
    run_id = uuid4().hex
    store = ExecutionStore(connection, run_id)
    genesis = initial(f"offline:{run_id}")
    store.create(genesis)
    steps = commands()
    (submit,) = store.transact(lambda state: steps)
    assert submit.kind == "SUBMIT"
    order_id = submit.order.order_id
    payload = claim_payload(store, submit)
    assert not store.transact(lambda state: steps)
    assert store.claim(order_id, "SUBMIT", payload)

    with connect(os.environ["GUIYI_SIMULATION_ISOLATED_TEST_DSN"]) as reopened:
        recovered = ExecutionStore(reopened, run_id)
        recovered.create(genesis)
        assert recovered.current() == recovered.replay() == store.current()
        assert recovered.claims() == {(order_id, "SUBMIT"): payload}
        assert not recovered.claim(order_id, "SUBMIT", payload)
        with pytest.raises(ExecutionStoreError, match="OFFLINE_CLAIM_IDENTITY_CONFLICT"):
            recovered.claim(order_id, "SUBMIT", {**payload, "price": "1"})
        with pytest.raises(ExecutionStoreError, match="OFFLINE_CLAIM_EFFECT_MISSING"):
            recovered.claim(order_id, "CANCEL", payload)


@pytest.mark.isolated_postgresql
def test_batch_rolls_back_and_claim_requires_own_transaction(connection):
    run_id = uuid4().hex
    store = ExecutionStore(connection, run_id)
    genesis = initial(f"offline:{run_id}")
    store.create(genesis)
    steps = commands()
    bad_owner = strategy.Owner("RB", "RB2702", T, "other-offline-owner")
    with pytest.raises(ValueError, match="COMMAND_IDENTITY_CONFLICT"):
        store.transact(lambda state: (steps[0], ("owner", bad_owner)))
    assert store.current() == store.replay() == genesis
    (submit,) = store.transact(lambda state: steps)
    payload = claim_payload(store, submit)
    with connection.transaction(), pytest.raises(ExecutionStoreError, match="OFFLINE_TRANSACTION_ALREADY_ACTIVE"):
        store.claim(submit.order.order_id, "SUBMIT", payload)
    assert store.claims() == {}


@pytest.mark.isolated_postgresql
def test_concurrent_claims_have_one_winner_and_replay_checks_projection(connection):
    run_id = uuid4().hex
    store = ExecutionStore(connection, run_id)
    genesis = initial(f"offline:{run_id}")
    store.create(genesis)
    (submit,) = store.transact(lambda state: commands())
    order_id = submit.order.order_id
    payload = claim_payload(store, submit)

    def claim():
        with connect(os.environ["GUIYI_SIMULATION_ISOLATED_TEST_DSN"]) as other:
            return ExecutionStore(other, run_id).claim(order_id, "SUBMIT", payload)

    with ThreadPoolExecutor(2) as pool:
        first, second = pool.submit(claim), pool.submit(claim)
        assert sorted((first.result(), second.result())) == [False, True]

    with connection.transaction():
        connection.execute("UPDATE guiyi_simulation.execution_runs SET projection = %s WHERE run_id = %s",
                           (codec.checkpoint(genesis), run_id))
    with pytest.raises(ExecutionStoreError, match="OFFLINE_PROJECTION_REPLAY_MISMATCH"):
        store.current()
    with pytest.raises(ExecutionStoreError, match="OFFLINE_PROJECTION_REPLAY_MISMATCH"):
        store.replay()


@pytest.mark.isolated_postgresql
def test_claim_rechecks_preparation_state_under_its_write_lock(connection):
    store = ExecutionStore(connection, uuid4().hex)
    store.create(initial(store.account_id))
    (submit,) = store.transact(lambda _: commands())
    old = claim_payload(store, submit)
    state = store.current()
    next_clock = state.clock + timedelta(seconds=1)
    store.transact(lambda _: (("no-new-effect", account.ContinuousTradeTickV1(next_clock, ())),))
    with pytest.raises(ExecutionStoreError, match="OFFLINE_CLAIM_PROOF_STALE"):
        store.claim(submit.order.order_id, "SUBMIT", old)
    assert not store.claims()
