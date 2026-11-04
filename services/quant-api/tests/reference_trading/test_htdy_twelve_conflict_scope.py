"""Owner-selected Nov 4 maintenance preserves originals and interrupts SI only."""

from copy import deepcopy
import pytest
from sqlalchemy import select
from app.reference_trading import htdy_conflict_recovery as domain
from app.reference_trading.htdy_conflict_incidents import NOV04_VERSION, NOV04_BINDINGS
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

PRODUCTS = ("sm", "pk", "ap", "cj", "jd", "lc", "lh", "pd", "ps", "pt", "sf", "si")


def setup(monkeypatch, engine=None):
    factory, recovery, _ = conflict_setup(engine, products=[*PRODUCTS, "rb"])
    return configure_eleven(
        factory,
        recovery,
        monkeypatch,
        products=PRODUCTS,
        opened=("si",),
        bindings=NOV04_BINDINGS,
        incident=NOV04_VERSION,
        binding_name="NOV04_BINDINGS",
    )


def test_twelve_append_only_single_si_interruption_and_future_flat(monkeypatch):
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
        assert (
            len(interrupted) == 1
            and interrupted[0].stream_id == htdy_identity("si").stream_id
        )
        assert (
            interrupted[0].exit_reference_price is None
            and interrupted[0].reference_return is None
        )
        from app.reference_trading.repository import ReferenceRepository

        repository = ReferenceRepository(factory)
        for sid in ids:
            _, cp = repository.load_checkpoint(sid)
            assert cp.reference_state.open_trade is None
            assert (
                db.get(ReferenceStream, sid).activation_generation
                == domain.NOV04_BINDINGS[sid][2] + 1
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
def test_twelve_scope_or_original_drift_has_no_boundary(monkeypatch, change):
    factory, recovery, ids = setup(monkeypatch)
    if change == "scope":
        ids[-1] = htdy_identity("rb").stream_id
    elif change == "duplicate":
        ids[-1] = ids[0]
    else:
        sid = htdy_identity("si").stream_id
        row = list(domain.NOV04_BINDINGS[sid])
        index = {
            "revision": 0,
            "capture": 1,
            "generation": 2,
            "checkpoint": 3,
            "open_id": 4,
        }[change]
        row[index] = 99 if index == 2 else "foreign"
        monkeypatch.setattr(
            domain, "NOV04_BINDINGS", {**domain.NOV04_BINDINGS, sid: tuple(row)}
        )
    with pytest.raises(RepositoryConflict):
        freeze(recovery, ids)
    with factory() as db:
        assert not any(
            domain.KEY in b.source_evidence for b in db.scalars(select(ReferenceBatch))
        )


def test_twelve_fence_loss_rolls_back_all_and_foreign_readback_rejected(monkeypatch):
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
            == domain.NOV04_BINDINGS[sid][2]
            for sid in ids
        )
