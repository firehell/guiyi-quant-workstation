"""Durable account inbox behavior without a broker connection or live data."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
import guiyi_quant.simnow_execution.inbox as inbox_module

from guiyi_quant.htdy_account_execution import codec
from guiyi_quant.htdy_execution import Signal
from guiyi_quant.simnow_execution.inbox import SignalInbox


ACCOUNT = "a" * 64
BASE = datetime(2026, 10, 27, 1, tzinfo=UTC)


def signal(product="RB", minute=60, observed=2, source=None, input_hash="b" * 64):
    end = BASE + timedelta(minutes=minute)
    return Signal(
        source or f"source-{product}-{minute}",
        product,
        f"{product}2701",
        end,
        end + timedelta(seconds=observed),
        None,
        ("buy",),
        input_hash,
    )


def inbox(tmp_path, account=ACCOUNT, products=("RB", "JM")):
    return SignalInbox(tmp_path / "inbox.sqlite", account, products)


def test_first_observation_freezes_same_product_bar_redraw(tmp_path):
    box = inbox(tmp_path)
    original = signal()
    assert box.enqueue(original) == "QUEUED"
    assert box.enqueue(original) == "DUPLICATE"
    redraw = replace(original, source_id="redrawn", input_hash="c" * 64)
    assert box.enqueue(redraw) == "REDRAW_IGNORED"
    assert box.pending() == (original,)
    box.close()
    again = inbox(tmp_path)
    assert again.pending() == (original,)
    again.close()


def test_pending_order_is_observed_then_product_then_source(tmp_path):
    box = inbox(tmp_path)
    rb_z = signal("RB", minute=60, source="z", observed=62)
    rb_a = signal("RB", minute=61, source="a", observed=2)
    jm = signal("JM", minute=60, source="m", observed=62)
    earlier = signal("RB", minute=59, source="earlier", observed=1)
    for item in (rb_z, rb_a, jm, earlier):
        assert box.enqueue(item) == "QUEUED"
    # All three later observations were first seen at the same wall-clock time.
    assert box.pending() == (earlier, jm, rb_a, rb_z)
    box.close()


def test_rejects_public_symlink_wrong_account_and_scope(tmp_path):
    box = inbox(tmp_path)
    box.close()
    path = tmp_path / "inbox.sqlite"
    path.chmod(0o644)
    with pytest.raises(ValueError, match="INBOX_PRIVATE_REQUIRED"):
        inbox(tmp_path)
    path.chmod(0o600)
    with pytest.raises(ValueError, match="INBOX_IDENTITY_MISMATCH"):
        inbox(tmp_path, account="b" * 64)
    with pytest.raises(ValueError, match="INBOX_IDENTITY_MISMATCH"):
        inbox(tmp_path, products=("RB",))
    link = tmp_path / "link.sqlite"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="INBOX_PRIVATE_REQUIRED"):
        SignalInbox(link, ACCOUNT, ("RB", "JM"))


def test_rejects_existing_inbox_owned_by_another_uid(tmp_path, monkeypatch):
    box = inbox(tmp_path)
    box.close()
    monkeypatch.setattr(inbox_module.os, "getuid", lambda: -1)
    with pytest.raises(ValueError, match="INBOX_PRIVATE_REQUIRED"):
        inbox(tmp_path)


class FakeStore:
    def __init__(self):
        self.receipts = {}

    def execute(self, key, command):
        assert key not in self.receipts
        self.receipts[key] = {"command_hash": codec.digest(command)}

    def receipt(self, key):
        return self.receipts.get(key)


def test_commit_before_ack_crash_recovers_from_receipt_without_resending(
    tmp_path, monkeypatch
):
    box = inbox(tmp_path)
    item = signal()
    box.enqueue(item)
    store = FakeStore()
    monkeypatch.setattr(
        box, "mark", lambda *_: (_ for _ in ()).throw(RuntimeError("ack failed"))
    )
    with pytest.raises(RuntimeError, match="ack failed"):
        box.deliver(store)
    assert len(store.receipts) == 1
    box.close()
    again = inbox(tmp_path)
    again.recover_queue(store)
    assert again.pending() == ()
    again.deliver(store)
    assert len(store.receipts) == 1
    again.close()


def test_uncommitted_queue_is_dropped_on_restart(tmp_path):
    box = inbox(tmp_path)
    box.enqueue(signal())
    box.close()
    again = inbox(tmp_path)
    again.recover_queue(FakeStore())
    assert again.pending() == ()
    again.close()


def test_daily_three_attempts_survive_process_restart(tmp_path):
    box = inbox(tmp_path)
    assert box.attempt("20261027") == 1
    box.close()
    again = inbox(tmp_path)
    assert again.attempt("20261027") == 2
    assert again.attempt("20261027") == 3
    with pytest.raises(ValueError, match="CONNECTION_BUDGET_EXHAUSTED"):
        again.attempt("20261027")
    assert again.attempt("20261028") == 1
    again.close()
