"""Explicit original-account anchors; no native connection or production files."""

from dataclasses import replace
from decimal import Decimal

import pytest
from guiyi_quant import htdy_account_execution as a
from guiyi_quant.htdy_account_execution.codec import digest
from guiyi_quant.simnow_execution.account_profile import AccountProfile
from test_adapter import setup


def non100k(tmp_path, monkeypatch):
    start = a.start

    def original_start(account, products, at, rb):
        return start(
            account,
            products,
            at,
            replace(
                rb,
                snapshot=replace(
                    rb.snapshot,
                    balance=Decimal("234567.89"),
                    available=Decimal("234567.89"),
                ),
            ),
        )

    monkeypatch.setattr(a, "start", original_start)
    return setup(tmp_path)


def test_default_profile_preserves_exact_100k_guard(tmp_path, monkeypatch):
    adapter, effect, facts, binding, permit, at, api = non100k(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="INITIAL_100K_BASELINE_REQUIRED"):
        adapter.dispatch(effect, binding, None, facts, permit, at)
    assert api.calls == [] and not adapter.journal.claimed(effect.order.order_id)


def test_original_anchor_allows_original_balance_without_reinitialization(
    tmp_path, monkeypatch
):
    adapter, effect, facts, binding, permit, at, api = non100k(tmp_path, monkeypatch)
    state = adapter.store.current()
    profile = AccountProfile.from_dict(
        dict(
            profile_id="original_anchor_v1",
            account_id=state.account_id,
            initial_readback_sha256=digest(state.initial_readback),
        )
    )
    adapter.account_profile = profile
    assert (
        adapter.dispatch(effect, binding, None, facts, permit, at)
        == "REQUEST_ACCEPTED_AWAIT_NATIVE"
    )
    assert len(api.calls) == 1
    assert adapter.store.current().initial_readback == state.initial_readback
    assert adapter.store.current().initial_readback.snapshot.balance == Decimal(
        "234567.89"
    )


@pytest.mark.parametrize("change", ["account", "baseline", "profile"])
def test_mismatched_original_anchor_never_claims_or_sends(
    tmp_path, monkeypatch, change
):
    adapter, effect, facts, binding, permit, at, api = non100k(tmp_path, monkeypatch)
    state = adapter.store.current()
    values = dict(
        profile_id="original_anchor_v1",
        account_id=state.account_id,
        initial_readback_sha256=digest(state.initial_readback),
    )
    if change == "account":
        values["account_id"] = "f" * 64
    elif change == "baseline":
        values["initial_readback_sha256"] = "f" * 64
    else:
        values["profile_id"] = "unknown"
    with pytest.raises(ValueError, match="ACCOUNT_PROFILE"):
        adapter.account_profile = AccountProfile.from_dict(values)
        adapter.dispatch(effect, binding, None, facts, permit, at)
    assert api.calls == [] and not adapter.journal.claimed(effect.order.order_id)


def test_profile_parser_exact_fields_and_immutable():
    from dataclasses import FrozenInstanceError

    value = dict(
        profile_id="original_anchor_v1",
        account_id="a" * 64,
        initial_readback_sha256="b" * 64,
    )
    with pytest.raises(ValueError, match="ACCOUNT_PROFILE"):
        AccountProfile.from_dict({**value, "balance": "100000"})
    profile = AccountProfile.from_dict(value)
    with pytest.raises(FrozenInstanceError):
        profile.account_id = "c" * 64


def test_profile_failure_has_fixed_stage_code_and_elapsed_without_claim(
    tmp_path, monkeypatch
):
    adapter, effect, facts, binding, permit, at, api = non100k(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="INITIAL_100K"):
        adapter.dispatch(effect, binding, None, facts, permit, at)
    diagnostic = adapter.last_dispatch_diagnostic
    assert diagnostic["stage"] == "ACCOUNT_PROFILE"
    assert diagnostic["code"] == "INITIAL_100K_BASELINE_REQUIRED"
    assert diagnostic["elapsed_ms"] >= 0
    assert api.calls == []


def test_unknown_exception_diagnostic_does_not_expose_exception_text(tmp_path):
    adapter, effect, facts, binding, permit, at, api = setup(tmp_path)

    def private_failure(*args):
        raise ValueError("secret-password-in-unexpected-error")

    adapter._preflight = private_failure
    with pytest.raises(ValueError):
        adapter.dispatch(effect, binding, None, facts, permit, at)
    assert adapter.last_dispatch_diagnostic["code"] == "DISPATCH_FAILED"
    assert "secret" not in str(adapter.last_dispatch_diagnostic)


@pytest.mark.parametrize("original_profile", [False, True])
def test_host_retains_failure_stage_and_abort_unsent_or_sends_exact_one(
    tmp_path, monkeypatch, original_profile
):
    from datetime import timedelta
    from guiyi_quant.simnow_execution.host import Host
    from guiyi_quant.simnow_execution.evidence import Evidence

    adapter, effect, facts, binding, permit, at, api = non100k(tmp_path, monkeypatch)
    profile = None
    if original_profile:
        state = adapter.store.current()
        profile = AccountProfile.from_dict(
            dict(
                profile_id="original_anchor_v1",
                account_id=state.account_id,
                initial_readback_sha256=digest(state.initial_readback),
            )
        )
        adapter.account_profile = profile
    book = Evidence(tmp_path / "evidence.db", adapter.session.account_id)
    host = Host(
        adapter.store,
        adapter.journal,
        book,
        adapter,
        "RB",
        run_id="profile-fixture",
        deadline=at + timedelta(minutes=1),
        account_profile=profile,
    )
    if original_profile:
        assert host.submit_effects((effect,), (binding,), (facts,), at) == (
            "REQUEST_ACCEPTED_AWAIT_NATIVE",
        )
        assert len(api.calls) == 1 and api.calls[0][1].VolumeTotalOriginal == 1
        assert host.last_dispatch_diagnostic["code"] == "REQUEST_ACCEPTED_AWAIT_NATIVE"
    else:
        with pytest.raises(ValueError, match="INITIAL_100K"):
            host.submit_effects((effect,), (binding,), (facts,), at)
        state = adapter.store.current()
        assert state.orders[0].status == "LOCAL_ABORTED"
        assert all(r.released for r in state.reservations)
        assert api.calls == [] and not adapter.journal.claimed(effect.order.order_id)
        assert host.last_dispatch_diagnostic["stage"] == "ACCOUNT_PROFILE"
        assert host.last_dispatch_diagnostic["code"] == "INITIAL_100K_BASELINE_REQUIRED"


def test_host_cannot_drop_or_change_adapter_profile(tmp_path, monkeypatch):
    from guiyi_quant.simnow_execution.host import Host
    from guiyi_quant.simnow_execution.evidence import Evidence

    adapter, _, _, _, _, at, _ = non100k(tmp_path, monkeypatch)
    state = adapter.store.current()
    adapter.account_profile = AccountProfile(
        "original_anchor_v1", state.account_id, digest(state.initial_readback)
    )
    with pytest.raises(ValueError, match="ACCOUNT_PROFILE_HOST_MISMATCH"):
        Host(
            adapter.store,
            adapter.journal,
            Evidence(tmp_path / "evidence.db", state.account_id),
            adapter,
            "RB",
            run_id="fixture",
            deadline=at,
        )


def test_diagnostic_code_helper_handles_arbitrary_exception_arguments():
    from guiyi_quant.simnow_execution.adapter import dispatch_failure_code

    assert dispatch_failure_code(ValueError({"private": "secret"})) == "DISPATCH_FAILED"
    assert (
        dispatch_failure_code(RuntimeError("INITIAL_100K_BASELINE_REQUIRED"))
        == "DISPATCH_FAILED"
    )


def test_native_portfolio_passes_explicit_profile_to_real_adapter(tmp_path):
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace as NS
    from guiyi_quant.simnow_execution.inventory import read_snapshot

    path = Path(__file__).parents[1] / "simnow_supervisor/test_native_portfolio.py"
    spec = importlib.util.spec_from_file_location("profile_native_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    native = module.portfolio(tmp_path)
    profile = AccountProfile("original_anchor_v1", module.ACCOUNT, "b" * 64)
    native.settings.account_profile = profile
    report = module.native_fixture.report()
    report["account_fingerprint"] = module.ACCOUNT
    snapshot = read_snapshot(report)
    native.gateway.query = lambda kind: [{"ConfirmDate": "20261027"}]
    native.gateway.attach = lambda *_: None
    adapter = native.adapter(
        None, NS(account_id=module.ACCOUNT, events=lambda: ()), snapshot, module.T
    )
    assert adapter.account_profile is profile


def test_expired_permit_is_diagnosed_before_profile_without_misattribution(
    tmp_path, monkeypatch
):
    from datetime import timedelta

    adapter, effect, facts, binding, permit, at, api = non100k(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="NATIVE_FACT_STALE"):
        adapter.dispatch(
            effect, binding, None, facts, permit, at + timedelta(seconds=6)
        )
    assert adapter.last_dispatch_diagnostic["stage"] == "PERMIT_FRESHNESS"
    assert adapter.last_dispatch_diagnostic["code"] == "NATIVE_FACT_STALE"
    assert api.calls == []


def test_dispatch_duration_uses_monotonic_clock(tmp_path, monkeypatch):
    import guiyi_quant.simnow_execution.adapter as module

    adapter, effect, facts, binding, permit, at, api = setup(tmp_path)
    ticks = iter((11, 11.12345))
    monkeypatch.setattr(module, "monotonic", lambda: next(ticks))
    adapter.dispatch(effect, binding, None, facts, permit, at)
    assert adapter.last_dispatch_diagnostic["elapsed_ms"] == 123.45
