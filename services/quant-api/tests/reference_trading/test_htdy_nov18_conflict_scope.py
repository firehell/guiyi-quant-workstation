"""Owner-approved JD interruption preserves the entry and every original batch."""

import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.reference_trading import htdy_conflict_recovery as domain
from app.reference_trading.htdy_activation import htdy_identity
from app.reference_trading.htdy_conflict_incidents import NOV18_BINDINGS, NOV18_VERSION
from app.reference_trading.repository import RepositoryConflict
from tests.reference_trading.test_htdy_conflict_recovery import NOW, conflict_setup
from tests.reference_trading.test_htdy_eleven_conflict_scope import configure_eleven, freeze


def configure(factory, recovery, monkeypatch):
    return configure_eleven(
        factory, recovery, monkeypatch, products=("jd",), opened=("jd",),
        bindings=NOV18_BINDINGS, incident=NOV18_VERSION, binding_name="NOV18_BINDINGS",
    )


def assert_atomic_interruption(factory, recovery, ids):
    with factory() as db:
        originals = {b.batch_id: domain._row(b) for b in db.scalars(select(domain.ReferenceBatch))}
        rb = domain._row(db.get(domain.ReferenceStream, htdy_identity("rb").stream_id))
        original_trade, = db.scalars(select(domain.ReferenceTradeRow).where(
            domain.ReferenceTradeRow.stream_id == ids[0],
        )).all()
        original_entry = original_trade.entry_reference_price
    plan = freeze(recovery, ids)
    result = recovery.apply(plan, expected_plan_hash=plan["plan_hash"], now=NOW)
    assert set(result) == set(ids) and recovery.readback(plan) == result
    with factory() as db:
        assert all(domain._row(db.get(domain.ReferenceBatch, key)) == row
                   for key, row in originals.items())
        assert domain._row(db.get(domain.ReferenceStream, htdy_identity("rb").stream_id)) == rb
        interrupted, = db.scalars(select(domain.ReferenceTradeRow).where(
            domain.ReferenceTradeRow.status == "DATA_INTERRUPTED",
        )).all()
        assert interrupted.stream_id == ids[0]
        assert interrupted.entry_reference_price == original_entry
        assert interrupted.exit_reference_price is None and interrupted.reference_return is None
        assert db.get(domain.ReferenceStream, ids[0]).activation_generation == 8
    _, checkpoint = domain.ReferenceRepository(factory).load_checkpoint(ids[0])
    assert checkpoint.reference_state.open_trade is None
    with pytest.raises(RepositoryConflict):
        freeze(recovery, ids)


def test_jd_append_only_interruption_and_future_flat(monkeypatch):
    factory, recovery, _ = conflict_setup(products=["jd", "rb"])
    factory, recovery, ids = configure(factory, recovery, monkeypatch)
    assert_atomic_interruption(factory, recovery, ids)


@pytest.mark.parametrize("index", range(5))
def test_jd_rejects_each_stale_preimage_component(monkeypatch, index):
    factory, recovery, _ = conflict_setup(products=["jd", "rb"])
    factory, recovery, ids = configure(factory, recovery, monkeypatch)
    expected = list(domain.NOV18_BINDINGS[ids[0]])
    expected[index] = 99 if index == 2 else "foreign"
    monkeypatch.setattr(domain, "NOV18_BINDINGS", {ids[0]: tuple(expected)})
    with pytest.raises(RepositoryConflict, match="INCIDENT_PREIMAGE_DRIFT"):
        freeze(recovery, ids)
    with factory() as db:
        assert not any(domain.KEY in b.source_evidence for b in db.scalars(select(domain.ReferenceBatch)))


def test_cli_inventory_hash_and_scope_are_exact(tmp_path):
    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location("nov18_conflict_cli", root / "scripts/reference_htdy_conflict_recovery.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    sid, (revision, capture, generation, checkpoint, trade) = next(iter(NOV18_BINDINGS.items()))
    row = dict(stream_id=sid, revision_id=revision, capture_id=capture,
               activation_generation=generation, checkpoint_batch_id=checkpoint,
               reference_trade_id=trade, code="OBSERVATION_GAP", endpoint_shift_equal=True,
               reference_open=True)
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps({"pending": [row]}, sort_keys=True, separators=(",", ":")))
    path.chmod(0o600)
    assert cli.frozen_scope(path, incident=NOV18_VERSION) == (sid,)
    with pytest.raises(ValueError, match="FROZEN_SCOPE_REQUIRED"):
        cli.checked_scope([sid, htdy_identity("rb").stream_id], incident=NOV18_VERSION)
    row["reference_trade_id"] = "foreign"
    path.write_text(json.dumps({"pending": [row]}, sort_keys=True, separators=(",", ":")))
    with pytest.raises(ValueError, match="INVENTORY_DRIFT"):
        cli.frozen_scope(path, incident=NOV18_VERSION)
