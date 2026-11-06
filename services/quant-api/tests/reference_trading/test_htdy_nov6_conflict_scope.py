"""Owner-approved Nov 6 exact eleven repair: preserve originals and future FLAT only."""

from copy import deepcopy
import pytest
from sqlalchemy import select
from app.reference_trading import htdy_conflict_recovery as domain
from app.reference_trading.htdy_conflict_incidents import NOV06_VERSION, NOV06_BINDINGS
from app.reference_trading.htdy_activation import htdy_identity
from app.reference_trading.models import (
    ReferenceBatch,
    ReferenceStream,
    ReferenceTradeRow,
)
from app.reference_trading.repository import RepositoryConflict
from tests.reference_trading.test_htdy_conflict_recovery import NOW, conflict_setup
from tests.reference_trading.test_htdy_eleven_conflict_scope import (
    configure_eleven,
    freeze,
)

PRODUCTS = ("ap", "cj", "jd", "lc", "lh", "pd", "pk", "ps", "sf", "sm", "ur")


def setup(monkeypatch, engine=None):
    factory, recovery, _ = conflict_setup(engine, products=[*PRODUCTS, "rb"])
    return configure_eleven(
        factory,
        recovery,
        monkeypatch,
        products=PRODUCTS,
        opened=("pd", "ps"),
        bindings=NOV06_BINDINGS,
        incident=NOV06_VERSION,
        binding_name="NOV06_BINDINGS",
    )


def test_nov6_append_only_two_open_interrupted_and_future_flat(monkeypatch):
    factory, recovery, ids = setup(monkeypatch)
    with factory() as db:
        originals = {
            b.batch_id: domain._row(b) for b in db.scalars(select(ReferenceBatch))
        }
        rb = domain._row(db.get(ReferenceStream, htdy_identity("rb").stream_id))
    p = freeze(recovery, ids)
    result = recovery.apply(p, expected_plan_hash=p["plan_hash"], now=NOW)
    assert set(result) == set(ids) and recovery.readback(p) == result
    with factory() as db:
        assert all(
            domain._row(db.get(ReferenceBatch, k)) == v for k, v in originals.items()
        )
        assert domain._row(db.get(ReferenceStream, htdy_identity("rb").stream_id)) == rb
        interrupted = db.scalars(
            select(ReferenceTradeRow).where(
                ReferenceTradeRow.status == "DATA_INTERRUPTED"
            )
        ).all()
        assert len(interrupted) == 2
        assert {t.stream_id for t in interrupted} == {
            htdy_identity("pd").stream_id,
            htdy_identity("ps").stream_id,
        }
        from app.reference_trading.repository import ReferenceRepository

        repository = ReferenceRepository(factory)
        for sid in ids:
            _, cp = repository.load_checkpoint(sid)
            assert cp.reference_state.open_trade is None
            assert (
                db.get(ReferenceStream, sid).activation_generation
                == domain.NOV06_BINDINGS[sid][2] + 1
            )
    with pytest.raises(RepositoryConflict):
        freeze(recovery, ids)


@pytest.mark.parametrize(
    "change",
    [
        "scope",
        "duplicate",
        "revision",
        "capture",
        "generation",
        "checkpoint",
        "open_id",
    ],
)
def test_two_scope_or_original_drift_has_no_boundary(monkeypatch, change):
    factory, recovery, ids = setup(monkeypatch)
    if change == "scope":
        ids[-1] = htdy_identity("rb").stream_id
    elif change == "duplicate":
        ids[-1] = ids[0]
    else:
        sid = htdy_identity("pd").stream_id
        row = list(domain.NOV06_BINDINGS[sid])
        index = {
            "revision": 0,
            "capture": 1,
            "generation": 2,
            "checkpoint": 3,
            "open_id": 4,
        }[change]
        row[index] = 99 if index == 2 else "foreign"
        monkeypatch.setattr(
            domain, "NOV06_BINDINGS", {**domain.NOV06_BINDINGS, sid: tuple(row)}
        )
    with pytest.raises(RepositoryConflict):
        freeze(recovery, ids)
    with factory() as db:
        assert not any(
            domain.KEY in b.source_evidence for b in db.scalars(select(ReferenceBatch))
        )


def test_two_fence_loss_rolls_back_all_and_foreign_readback_rejected(monkeypatch):
    factory, recovery, ids = setup(monkeypatch)
    p = freeze(recovery, ids)
    bad = deepcopy(p)
    bad["items"][0]["binding"]["stream_id"] = "outside"
    bad["plan_hash"] = domain._hash({k: v for k, v in bad.items() if k != "plan_hash"})
    with pytest.raises(RepositoryConflict, match="SCOPE_INVALID"):
        recovery.readback(bad)
    calls = []

    def lost():
        calls.append(True)
        if len(calls) == 2:
            raise RepositoryConflict("FENCE_LOST")

    recovery.assert_fenced = lost
    with pytest.raises(RepositoryConflict):
        recovery.apply(p, expected_plan_hash=p["plan_hash"], now=NOW)
    assert recovery.readback(p) is None
    with factory() as db:
        assert all(
            db.get(ReferenceStream, sid).activation_generation
            == domain.NOV06_BINDINGS[sid][2]
            for sid in ids
        )


@pytest.mark.parametrize("cause", ["prior_retirement", "new_source", "open_set"])
def test_two_proof_source_or_unexpected_open_refuses_before_successor(
    monkeypatch, cause
):
    factory, recovery, ids = setup(monkeypatch)
    if cause == "prior_retirement":
        import app.reference_trading.inbox_recovery as inbox

        def invalid(*args, **kwargs):
            raise RepositoryConflict("PRIOR_RETIREMENT_INVALID")

        monkeypatch.setattr(inbox, "verified_resolution_ids", invalid)
        with pytest.raises(RepositoryConflict, match="PRIOR_RETIREMENT_INVALID"):
            freeze(recovery, ids)
    elif cause == "open_set":
        from tests.reference_trading.test_htdy_conflict_recovery import add_open_trade

        add_open_trade(factory, "ur", action_pk="unexpected-ur")
        with pytest.raises(RepositoryConflict):
            freeze(recovery, ids)
    else:
        p = freeze(recovery, ids)
        original = recovery.verify_source
        recovery.verify_source = lambda *args: {
            **original(*args),
            "changed_epoch": True,
        }
        with pytest.raises(RepositoryConflict):
            recovery.apply(p, expected_plan_hash=p["plan_hash"], now=NOW)
        assert recovery.readback(p) is None
    with factory() as db:
        assert not any(
            domain.KEY in b.source_evidence for b in db.scalars(select(ReferenceBatch))
        )
