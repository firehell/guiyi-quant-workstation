"""Local recovery stays scoped to blocked products, preserving healthy products."""
from datetime import datetime, UTC, timedelta
from types import SimpleNamespace
import pytest
from guiyi_quant.htdy_account_execution import model as m, codec
from guiyi_quant.tq_simulation.controller import Controller
from guiyi_quant.tq_simulation.worker import recover_blocked_products
from test_execution import A, Transport, snapshot


def blocked_controller(tmp_path):
    now = datetime.now(UTC) - timedelta(minutes=2)
    c = Controller(tmp_path, A, ("RB", "JM"), Transport())
    c.bootstrap(snapshot(now), now)
    c.owner("RB", "RB2701", now, "rb-owner")
    c.owner("JM", "JM2701", now, "jm-owner")
    proof = m.RecoveryInput("RB", "RB2701", 0, now, "rb-proof")
    at = now + timedelta(seconds=1)
    c.recover(c.readback(snapshot(at), at), (proof,))
    assert c.store.current().blocked_products == ("JM",)
    return c, now, proof


@pytest.mark.parametrize("product,contract", [("RB", "RB2701"), ("JM", "JM2705")])
def test_unrelated_or_unmapped_proof_does_not_recover_or_read_account(tmp_path, product, contract):
    c, now, _ = blocked_controller(tmp_path)
    before = c.store.current()
    def forbidden(_):
        raise AssertionError("unrelated proof must not trigger account synchronization")
    proof = m.RecoveryInput(product, contract, 0, now, "unrelated-proof")
    assert recover_blocked_products(c, SimpleNamespace(snapshot=forbidden, reconnection_required=False), [codec.encode(proof)]) is False
    assert c.store.current() == before
    c.close()


def test_mixed_proofs_recover_only_named_blocked_product(tmp_path):
    c, now, healthy_proof = blocked_controller(tmp_path)
    before = c.store.current()
    proof = m.RecoveryInput("JM", "JM2701", 0, now, "jm-proof")
    assert recover_blocked_products(c, SimpleNamespace(snapshot=snapshot, reconnection_required=False),
        [codec.encode(healthy_proof), codec.encode(proof)]) is True
    after = c.store.current()
    assert not after.blocked_products
    cmd = after.audit[-1].command
    assert type(cmd) is m.ProductRecoveryV1
    assert cmd.products == ("JM",) and cmd.inputs == (proof,)
    assert after.products[0] == before.products[0]
    assert after.activated_at == before.activated_at
    assert after.orders == before.orders and after.fills == before.fills
    assert c.store.replay() == after
    c.close()


def test_expired_proof_cannot_turn_product_recovery_into_account_hold(tmp_path):
    c, now, _ = blocked_controller(tmp_path)
    observed = now + timedelta(seconds=2)
    c.signal(m.Signal("jm-completed", "JM", "JM2701", observed,
                     observed + timedelta(seconds=1), None, (), "a" * 64),
             processed_at=observed + timedelta(seconds=1))
    proof = m.RecoveryInput("JM", "JM2701", 0, now, "old-jm-proof")
    gateway = SimpleNamespace(snapshot=snapshot, reconnection_required=False)
    assert recover_blocked_products(c, gateway, [codec.encode(proof)]) is False
    after = c.store.current()
    assert after.phase == "READY" and after.blocked_products == ("JM",)
    assert after.audit[-1].command.__class__ is m.Readback
    assert c.store.replay() == after
    c.close()


def test_native_day_change_defers_scoped_recovery_to_account_recovery(tmp_path):
    c, now, _ = blocked_controller(tmp_path)
    gateway = SimpleNamespace(reconnection_required=False)

    def changed_day(at):
        gateway.reconnection_required = True
        return snapshot(at)

    gateway.snapshot = changed_day
    proof = m.RecoveryInput("JM", "JM2701", 0, now, "jm-proof")
    assert recover_blocked_products(c, gateway, [codec.encode(proof)]) is False
    after = c.store.current()
    assert after.phase == "RECOVERY_REQUIRED"
    assert type(after.audit[-1].command) is m.Disconnect
    assert c.store.replay() == after
    c.close()
