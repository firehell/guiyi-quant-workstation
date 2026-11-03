"""Versioned signed SessionID fill facts; local fake native wire and SQLite only."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from guiyi_quant import htdy_account_execution as account, simnow_execution as native
from guiyi_quant.htdy_account_execution import codec
import test_adapter as wire
from test_strategy_correlation import strategy_adapter


@pytest.mark.parametrize("session_id", [-2, 2, -(2**31), 2**31-1], ids=["negative", "positive", "signed-min", "signed-max"])
def test_signed_session_adapter_store_codec_and_replay(tmp_path, monkeypatch, session_id):
    old, effect, facts, binding, permit, at, api = wire.setup(tmp_path)
    old.session = replace(old.session, session_id=session_id)
    permit = replace(permit, action_hash=native.action_hash(old.store.current(), effect, old.session, binding, None, facts))
    original_row = wire.row
    def row(adapter, *args, **kwargs):
        result = original_row(adapter, *args, **kwargs)
        result.SessionID = adapter.session.session_id
        return result
    monkeypatch.setattr(wire, "row", row)
    adapter = strategy_adapter(old, api)
    assert adapter.dispatch(effect, binding, None, facts, permit, at) == "REQUEST_ACCEPTED_AWAIT_NATIVE"
    adapter.order_callback(row(adapter, effect, at-timedelta(seconds=2), "0"), at+timedelta(seconds=1))
    adapter.trade_callback(wire.native_trade(clock="10:00:58"), at+timedelta(seconds=1))
    assert adapter.drain() and not old.store.current().fills
    snapshot = wire.correlated_snapshot(adapter, effect, at)
    adapter.correlate_snapshot(snapshot)
    pending = adapter.drain()
    assert pending and not old.store.current().fills
    adapter.fee(native.Fee(pending[0], Decimal(3), "ctp-commission-delta:fixture"), snapshot.at)
    assert adapter.drain() == ()
    fill = old.store.current().fills[0]
    assert type(fill) is account.StrategyCorrelatedNativeFillV2
    assert fill.native_session_id == session_id
    assert fill.correlation_policy_version == "simnow_strategy_correlated_fill_v2"
    assert fill.filled_at < fill.request_started_at
    assert codec.decode(codec.encode(fill)) == fill
    assert codec.load(codec.checkpoint(old.store.current())) == old.store.current()
    assert old.store.replay() == old.store.current()
    assert len(api.calls) == 1
    adapter.drain()
    assert len(old.store.current().fills) == len(api.calls) == 1
    old.store.close()
    restarted = account.LocalStore(tmp_path / "account.db")
    assert restarted.current().fills == (fill,)
    assert restarted.replay().fills == (fill,)
    restarted.close()
    assert account.LocalStore.inspect(tmp_path / "account.db").fills == (fill,)


def legacy_fill(adapter, effect, at):
    return account.StrategyCorrelatedNativeFillV1(
        "legacy-v1", effect.order.order_id, adapter.session.account_id, effect.order.contract,
        at-timedelta(seconds=2), at+timedelta(seconds=1), effect.order.price,
        Decimal(3), 1, at, "dispatch:1", "sys", readback_source_id="snapshot",
        native_order_ref="11", native_front_id=1, native_session_id=2,
    )


def test_v1_canonical_hash_checkpoint_and_replay_remain_exact(tmp_path):
    import hashlib
    adapter, effect, _, _, _, at, _ = wire.setup(tmp_path)
    fill = legacy_fill(adapter, effect, at)
    # These SHA values were measured on develop before the V2 implementation.
    assert codec.digest(fill) == "07946936ca40be5a2d8d95a8fb716197611b7d66266311478ce780be5795a4bd"
    assert codec.decode(codec.encode(fill)) == fill
    assert type(codec.decode(codec.encode(fill))) is account.StrategyCorrelatedNativeFillV1
    assert account.STRATEGY_CORRELATED_NATIVE_FILL_POLICY_VERSION == "simnow_strategy_correlated_fill_v1"
    adapter.store.execute("legacy-v1-fill", fill)
    state = adapter.store.current()
    assert codec.digest(state) == "bac9875e629b1a290489581f083a3af39630556682393b66249b8b8a3f2df4b9"
    assert hashlib.sha256(codec.checkpoint(state).encode()).hexdigest() == "07666fdfa087375187fe78ec26caa0ae031b2fa133f2abc6d1bf40797552a613"
    assert codec.load(codec.checkpoint(state)) == state
    assert adapter.store.replay() == state
    adapter.store.close()
    assert account.LocalStore.inspect(tmp_path / "account.db") == state
    # V1 retains its historical positive-int contract, including its old upper bound.
    assert replace(fill, native_session_id=2**31).native_session_id == 2**31
    with pytest.raises(ValueError, match="STRATEGY_CORRELATED_NATIVE_FILL_PROOF_INVALID"):
        replace(fill, native_session_id=-2)


@pytest.mark.parametrize("session_id", [0, -(2**31)-1, 2**31, True, "-2", None])
def test_v2_rejects_non_native_session_identifiers_before_store_write(tmp_path, session_id):
    adapter, effect, _, _, _, at, _ = wire.setup(tmp_path)
    original = legacy_fill(adapter, effect, at)
    fields = {**vars(original), "correlation_policy_version": account.STRATEGY_CORRELATED_NATIVE_FILL_V2_POLICY_VERSION,
              "native_session_id": session_id}
    before = adapter.store.current()
    with pytest.raises(ValueError, match="STRATEGY_CORRELATED_NATIVE_FILL_PROOF_INVALID"):
        adapter.store.execute("invalid-v2", account.StrategyCorrelatedNativeFillV2(**fields))
    assert adapter.store.current() == before
    assert adapter.store.receipt("invalid-v2") is None
    adapter.store.close()


def test_v2_policy_is_independent_and_v1_payload_cannot_silently_change_versions(tmp_path):
    adapter, effect, _, _, _, at, _ = wire.setup(tmp_path)
    old = legacy_fill(adapter, effect, at)
    new = account.StrategyCorrelatedNativeFillV2(**{
        **vars(old), "correlation_policy_version": account.STRATEGY_CORRELATED_NATIVE_FILL_V2_POLICY_VERSION})
    assert codec.encode(old)["type"] == "StrategyCorrelatedNativeFillV1"
    assert codec.encode(new)["type"] == "StrategyCorrelatedNativeFillV2"
    assert codec.digest(old) != codec.digest(new)
    with pytest.raises(ValueError, match="STRATEGY_CORRELATED_NATIVE_FILL_PROOF_INVALID"):
        replace(new, correlation_policy_version=old.correlation_policy_version)
    with pytest.raises(ValueError, match="STRATEGY_CORRELATED_NATIVE_FILL_PROOF_INVALID"):
        replace(old, correlation_policy_version=new.correlation_policy_version)
    adapter.store.execute("retained-v1", old)
    with pytest.raises(ValueError, match="FILL_IDENTITY_CONFLICT"):
        adapter.store.execute("forbidden-relabel-v2", new)
    assert adapter.store.current().fills == (old,)
    assert adapter.store.receipt("forbidden-relabel-v2") is None
    assert adapter.store.replay().fills == (old,)
    adapter.store.close()
