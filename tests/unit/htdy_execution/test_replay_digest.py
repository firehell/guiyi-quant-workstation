"""Exact historical bytes and full verification survive replay-local acceleration."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal, localcontext
from hashlib import sha256
import gc
import json
import sqlite3
import weakref

import pytest
from guiyi_quant import htdy_account_execution as account
from guiyi_quant.htdy_account_execution import codec, model
from test_account_execution import T, initial, readback


def reference(value):
    return sha256(codec.json_text(codec.encode(value)).encode()).hexdigest()


def audited(payload, *, key="审计\"\n😀"):
    return replace(initial(), audit=(model.Audit(key, "理由", payload),),
                   receipts=((key, "a" * 64),))


def test_append_and_replacement_preserve_complete_canonical_state_hashes():
    state = initial()
    with codec.replay_digests() as scope:
        for index in range(40):
            command = readback(T + timedelta(seconds=index + 1))
            state = account.apply(state, f"read-{index}", command).state
            assert codec.digest(state) == reference(state)
            assert scope.cached_bytes <= scope.max_bytes
        changed = replace(state, phase="RECOVERY_REQUIRED", readback_valid=False)
        assert codec.digest(changed) == reference(changed)


@pytest.mark.parametrize("one,two", [(Decimal("1.0"), Decimal("1.00")),
    (Decimal("-0"), Decimal("0")),
    (T, T.astimezone(timezone(timedelta(hours=8))))])
def test_value_equality_never_replaces_object_identity(one, two):
    a, b = audited(one), audited(two)
    assert a == b and reference(a) != reference(b)
    extended = replace(b, audit=b.audit + (model.Audit("later", "ok", "suffix"),),
                       receipts=b.receipts + (("later", "b" * 64),))
    with codec.replay_digests():
        assert codec.digest(a) == reference(a)
        assert codec.digest(b) == reference(b)
        assert codec.digest(extended) == reference(extended)


def test_decimal_capitals_change_clears_dependent_fragments():
    state = audited(Decimal("1E+12"))
    with localcontext() as context, codec.replay_digests():
        context.capitals = 1
        before = codec.digest(state)
        assert before == reference(state)
        context.capitals = 0
        after = codec.digest(state)
        assert after == reference(state) and after != before


@dataclass(frozen=True)
class ShallowFrozen:
    values: list


@pytest.mark.parametrize("payload", [{"value": "before"}, ["before"], ShallowFrozen(["before"])])
def test_shallow_or_unknown_mutable_graph_uses_original_whole_state_path(payload):
    state = audited(payload)
    with codec.replay_digests() as scope:
        before = codec.digest(state)
        assert before == reference(state) and scope.cached_bytes == 0
        if type(payload) is dict:
            payload["value"] = "after"
        elif type(payload) is list:
            payload[0] = "after"
        else:
            payload.values[0] = "after"
        assert codec.digest(state) == reference(state) != before
        assert scope.cached_bytes == 0


class MutableTimezone(tzinfo):
    offset = timedelta(0)
    def utcoffset(self, value):
        return self.offset
    def dst(self, value):
        return timedelta(0)


def test_mutable_timezone_is_not_treated_as_deeply_immutable():
    zone = MutableTimezone()
    state = audited(datetime(2026, 11, 3, tzinfo=zone))
    with codec.replay_digests() as scope:
        before = codec.digest(state)
        zone.offset = timedelta(hours=1)
        assert codec.digest(state) == reference(state) != before
        assert scope.cached_bytes == 0


def test_public_encode_remains_fresh_and_cannot_poison_private_fragments():
    state = audited("source")
    expected = codec.encode(state)
    with codec.replay_digests():
        assert codec.digest(state) == reference(state)
        exposed = codec.encode(state)
        exposed["fields"]["audit"].clear()
        assert codec.encode(state) == expected
        assert codec.digest(state) == reference(state)


def test_over_budget_and_exception_leave_no_cached_account_data():
    state = audited("source")
    with codec.replay_digests(max_bytes=64) as small:
        assert codec.digest(state) == reference(state)
        assert small.cached_bytes == 0 and not small.values
    with pytest.raises(ValueError):
        with codec.replay_digests() as failed:
            codec.digest(state)
            codec.digest(audited(float("nan")))
    assert failed.cached_bytes == 0 and not failed.values
    assert codec._replay_digest_scope.get() is None


def test_context_isolation_and_no_accumulated_state_history():
    state = initial()
    old = []
    with codec.replay_digests() as outer:
        for index in range(30):
            old.append(weakref.ref(state))
            state = replace(state, receipts=state.receipts + ((str(index), "c" * 64),),
                            audit=state.audit + (model.Audit(str(index), "ok", str(index)),))
            codec.digest(state)
        gc.collect()
        assert all(item() is None for item in old)
        size = outer.cached_bytes
        context = copy_context()
        with ThreadPoolExecutor(1) as pool:
            other = replace(state, account_id="other-account")
            assert pool.submit(context.run, codec.digest, other).result() == reference(other)
        assert outer.cached_bytes == size
        with pytest.raises(RuntimeError):
            with codec.replay_digests() as nested:
                codec.digest(other)
                raise RuntimeError("local fixture")
        assert not nested.values and codec.digest(state) == reference(state)
    assert not outer.values and codec._replay_digest_scope.get() is None


@pytest.fixture
def journal(tmp_path):
    path = tmp_path / "account.sqlite"
    store = account.LocalStore(path, initial())
    for index in range(8):
        store.execute(f"read-{index}", readback(T + timedelta(seconds=index + 1)))
    expected = store.current()
    store.close()
    return path, expected


def test_original_writer_rows_replay_to_exact_projection_bytes(journal):
    path, expected = journal
    with sqlite3.connect(path) as db:
        payload = db.execute("SELECT payload FROM projection").fetchone()[0]
    assert codec.checkpoint(account.LocalStore.inspect(path)) == payload == codec.checkpoint(expected)
    reopened = account.LocalStore(path)
    duplicate = reopened.execute("read-0", readback(T + timedelta(seconds=1)))
    assert duplicate.duplicate and duplicate.effects == ()
    with pytest.raises(account.StoreError, match="COMMAND_IDENTITY_CONFLICT"):
        reopened.execute("read-0", readback(T + timedelta(seconds=2)))
    reopened.close()


@pytest.mark.parametrize("damage", ["sequence", "command_hash", "command", "effects",
    "before", "after", "coupled_chain", "recovery_mode", "projection", "delete"])
def test_every_original_integrity_check_still_rejects_tampering(journal, damage):
    path, expected = journal
    with sqlite3.connect(path) as db:
        db.execute("DROP TRIGGER immutable_commands_update")
        db.execute("DROP TRIGGER immutable_commands_delete")
        if damage == "sequence":
            db.execute("UPDATE commands SET sequence=100 WHERE sequence=8")
        elif damage == "command_hash":
            db.execute("UPDATE commands SET command_hash=? WHERE sequence=2", ("0" * 64,))
        elif damage == "command":
            raw = db.execute("SELECT command_payload FROM commands WHERE sequence=2").fetchone()[0]
            value = json.loads(raw)
            value["fields"]["source_id"] = "changed"
            command = codec.decode(value)
            db.execute("UPDATE commands SET command_payload=?,command_hash=? WHERE sequence=2",
                       (codec.json_text(value), reference(command)))
        elif damage == "effects":
            db.execute("UPDATE commands SET effects_payload='[ ]' WHERE sequence=2")
        elif damage in {"before", "after"}:
            field = "before_hash" if damage == "before" else "after_hash"
            db.execute("UPDATE commands SET " + field + "=? WHERE sequence=2", ("0" * 64,))
        elif damage == "coupled_chain":
            db.execute("UPDATE commands SET after_hash=? WHERE sequence=1", ("0" * 64,))
            db.execute("UPDATE commands SET before_hash=? WHERE sequence=2", ("0" * 64,))
        elif damage == "recovery_mode":
            db.execute("UPDATE commands SET recovery_mode=1 WHERE sequence=2")
        elif damage == "projection":
            altered = replace(expected, phase="RECOVERY_REQUIRED", readback_valid=False)
            db.execute("UPDATE projection SET payload=?", (codec.checkpoint(altered),))
        else:
            db.execute("DELETE FROM commands WHERE sequence=8")
    with pytest.raises(account.StoreError, match="LOCAL_STORE_INVALID"):
        account.LocalStore.inspect(path)
