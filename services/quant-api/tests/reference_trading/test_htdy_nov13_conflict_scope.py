from sqlalchemy import select

from app.reference_trading import htdy_conflict_recovery as domain
from app.reference_trading.htdy_conflict_incidents import NOV13_BINDINGS, NOV13_VERSION
from tests.reference_trading.test_htdy_conflict_recovery import NOW, conflict_setup
from tests.reference_trading.test_htdy_eleven_conflict_scope import configure_eleven, freeze


def test_nov13_si_recovery_interrupts_the_open_reference_without_rewriting_batches(monkeypatch):
    factory, recovery, _ = conflict_setup(products=["si", "rb"])
    factory, recovery, ids = configure_eleven(
        factory, recovery, monkeypatch, products=("si",), opened=("si",),
        bindings=NOV13_BINDINGS, incident=NOV13_VERSION, binding_name="NOV13_BINDINGS",
    )
    with factory() as db:
        original = {b.batch_id: domain._row(b) for b in db.scalars(select(domain.ReferenceBatch))}
    plan = freeze(recovery, ids)
    result = recovery.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    assert set(result) == set(ids)
    assert recovery.readback(plan) == result
    with factory() as db:
        assert all(domain._row(db.get(domain.ReferenceBatch, key)) == row
                   for key, row in original.items())
        interrupted, = db.scalars(select(domain.ReferenceTradeRow).where(
            domain.ReferenceTradeRow.status == "DATA_INTERRUPTED"
        )).all()
        assert interrupted.stream_id == ids[0]
    _, checkpoint = domain.ReferenceRepository(factory).load_checkpoint(ids[0])
    assert checkpoint.reference_state.open_trade is None
