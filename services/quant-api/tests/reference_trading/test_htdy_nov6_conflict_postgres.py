"""Nov6 exact event uses the deployed PostgreSQL immutable-input contract."""

import pytest
from sqlalchemy import select
from tests.reference_trading.test_htdy_conflict_postgres import pg_setup as _pg_setup
from tests.reference_trading.test_htdy_eleven_conflict_scope import (
    configure_eleven,
    freeze,
)
from tests.reference_trading.test_htdy_nov6_conflict_scope import PRODUCTS
from app.reference_trading import htdy_conflict_recovery as domain
from app.reference_trading.models import ReferenceBatch, ReferenceTradeRow
from app.reference_trading.htdy_conflict_incidents import NOV06_VERSION, NOV06_BINDINGS

from tests.reference_trading.test_htdy_conflict_recovery import NOW

pytestmark = pytest.mark.isolated_postgresql


@pytest.fixture
def pg_setup(request):
    yield from _pg_setup.__wrapped__(request)


@pytest.mark.parametrize("pg_setup", [[*PRODUCTS, "rb"]], indirect=True)
def test_nov6_real_transaction_retains_originals_and_no_fake_exit(
    pg_setup, monkeypatch
):
    factory, recovery, _ = pg_setup
    factory, recovery, ids = configure_eleven(
        factory,
        recovery,
        monkeypatch,
        products=PRODUCTS,
        opened=("pd", "ps"),
        bindings=NOV06_BINDINGS,
        incident=NOV06_VERSION,
        binding_name="NOV06_BINDINGS",
    )
    with factory() as db:
        originals = {
            b.batch_id: domain._row(b) for b in db.scalars(select(ReferenceBatch))
        }
    p = freeze(recovery, ids)
    result = recovery.apply(p, expected_plan_hash=p["plan_hash"], now=NOW)
    assert len(result) == 11 and recovery.readback(p) == result
    with factory() as db:
        assert all(
            domain._row(db.get(ReferenceBatch, k)) == v for k, v in originals.items()
        )
        interrupted = db.scalars(
            select(ReferenceTradeRow).where(
                ReferenceTradeRow.status == "DATA_INTERRUPTED"
            )
        ).all()
        assert len(interrupted) == 2
        assert all(
            t.exit_reference_price is None and t.reference_return is None
            for t in interrupted
        )
        assert domain.retired_delivery_ids(db, stream_ids=ids) == ()
