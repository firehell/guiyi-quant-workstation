"""Continuous Host boundaries using isolated stores and the simulated CTP API."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
import pytest

from test_host import f, filled_report, host_setup, report_at
from guiyi_quant import htdy_account_execution as a, htdy_execution as h
from guiyi_quant.simnow_execution.evidence import Evidence
from guiyi_quant.simnow_execution.host import Host
from guiyi_quant.simnow_execution.inventory import read_snapshot


def portfolio_setup(tmp_path):
    ad, _, facts, binding, _, at, api = f.setup(tmp_path)
    baseline = ad.store.current().initial_readback
    ad.store.close()
    initial = a.start(ad.session.account_id, ("RB", "JM"), f.T, baseline)
    for name in ("RB", "JM"):
        initial = a.apply(
            initial, "owner-" + name, h.Owner(name, name + "2701", f.T, name)
        ).state
    ad.store = a.LocalStore(tmp_path / "portfolio.db", initial)
    evidence = Evidence(tmp_path / "portfolio-evidence.db", ad.session.account_id)
    host = Host(
        ad.store,
        ad.journal,
        evidence,
        ad,
        ("RB", "JM"),
        continuous=True,
        run_id="continuous",
        deadline=at - timedelta(seconds=1),
    )
    return host, ad, facts, binding, at, api


def test_managed_tick_has_no_open_proposal_reservation_or_claim(tmp_path):
    host, ad, facts, binding, at, api = portfolio_setup(tmp_path)
    for name in ("RB", "JM"):
        ad.store.execute(
            "signal-" + name,
            h.Signal(
                "signal-" + name,
                name,
                name + "2701",
                f.T + timedelta(minutes=60),
                f.T + timedelta(minutes=60, seconds=2),
                None,
                ("buy",),
                "a" * 64,
            ),
        )
    jm = a.ExecutionInput(
        replace(facts.instrument, product="JM", contract="JM2701"),
        replace(facts.session, contract="JM2701"),
        replace(facts.quote, contract="JM2701"),
    )
    assert host.tick((facts, jm), (binding,), at) == ()
    state = ad.store.current()
    assert state.orders == () and state.reservations == () and api.calls == []
    assert type(state.audit[-1].command) is a.ManagedTickV1
    assert ad.store.replay() == state


def test_continuous_recovery_does_not_repeat_for_blocked_product(tmp_path):
    host, ad, facts, binding, at, api = portfolio_setup(tmp_path)
    ad.store.execute("disconnect", a.Disconnect(f.T + timedelta(seconds=1)))
    host.needs_recovery = True
    first = report_at(f.T + timedelta(minutes=30), ad.session.account_id)
    proof = h.RecoveryInput("RB", "RB2701", 0, f.T, "rb-recovery")
    _, recovered = host.reconcile(
        first, (binding,), f.T + timedelta(minutes=31), (proof,)
    )
    assert recovered.blocked_products == ("JM",)
    assert not host.needs_recovery
    ad.store.execute(
        "healthy-rb",
        h.Signal(
            "healthy-rb",
            "RB",
            "RB2701",
            f.T + timedelta(minutes=60),
            f.T + timedelta(minutes=60, seconds=2),
            f.T,
            ("buy",),
            "a" * 64,
        ),
    )
    before = next(p for p in ad.store.current().products if p.product == "RB")
    _, state = host.reconcile(
        report_at(at, ad.session.account_id), (binding,), at + timedelta(seconds=20)
    )
    assert next(p for p in state.products if p.product == "RB") == before
    assert state.blocked_products == ("JM",) and not host.needs_recovery
    assert type(state.audit[-1].command) is a.Readback
    assert api.calls == []


def test_continuous_close_ignores_old_run_budget_and_claims_once(tmp_path):
    old, ad, effect, facts, binding, at, api = host_setup(tmp_path)
    _, state = old.reconcile(
        filled_report(ad, effect, at), (binding,), at + timedelta(seconds=20)
    )
    signal_at = at + timedelta(seconds=21)
    ad.store.execute(
        "reverse",
        h.Signal(
            "reverse",
            "RB",
            "RB2701",
            signal_at - timedelta(seconds=1),
            signal_at,
            f.T + timedelta(minutes=60),
            ("sell",),
            "b" * 64,
        ),
    )
    host = Host(
        ad.store,
        ad.journal,
        old.evidence,
        ad,
        ("RB",),
        continuous=True,
        run_id="manage",
        deadline=at,
        max_submits=1,
    )
    host.submits = 1
    host.inventory = old.inventory
    now = signal_at + timedelta(seconds=1)
    fresh = replace(
        facts,
        quote=replace(facts.quote, at=now, valid_until=now + timedelta(seconds=5)),
    )
    assert host.tick((fresh,), (binding,), now) == ("REQUEST_ACCEPTED_AWAIT_NATIVE",)
    close = ad.store.current().orders[-1]
    assert close.offset == "CLOSE"
    assert len(api.calls) == 2 and api.calls[-1][1].CombOffsetFlag == "3"
    ad.session = replace(ad.session, front_id=2, session_id=3)
    assert host.submit_effects(
        (a.Effect("SUBMIT", close),), (binding,), (fresh,), now
    ) == ("ALREADY_CLAIMED_NO_SEND",)
    assert len(api.calls) == 2


def test_continuous_rejects_open_and_entire_foreign_scope_batch_before_send(tmp_path):
    ad, effect, facts, binding, _, at, api = f.setup(tmp_path)
    evidence = Evidence(tmp_path / "evidence.db", ad.session.account_id)
    host = Host(
        ad.store,
        ad.journal,
        evidence,
        ad,
        "RB",
        continuous=True,
        run_id="manage",
        deadline=at,
    )
    with pytest.raises(ValueError, match="CONTINUOUS_OPEN_NOT_AUTHORIZED"):
        host.submit_effects((effect,), (binding,), (facts,), at)
    foreign = a.Effect("CANCEL", replace(effect.order, product="JM", contract="JM2701"))
    with pytest.raises(ValueError, match="CONTROLLED_PRODUCT_SCOPE_VIOLATION"):
        host.submit_effects((a.Effect("CANCEL", effect.order), foreign), (), (), at)
    assert api.calls == [] and not ad.journal.claimed(effect.order.order_id)


def test_continuous_cancels_known_open_after_deadline_and_never_reclaims(tmp_path):
    old, ad, effect, facts, binding, at, api = host_setup(tmp_path)
    ad.order_callback(f.row(ad, effect, at, "3"), at + timedelta(seconds=1))
    assert ad.drain() == ()
    host = Host(
        ad.store,
        ad.journal,
        old.evidence,
        ad,
        "RB",
        continuous=True,
        run_id="manage",
        deadline=at,
        max_submits=1,
    )
    host.submits = 1
    now = at + timedelta(seconds=181)
    assert host.tick((facts,), (binding,), now) == ("REQUEST_ACCEPTED_AWAIT_NATIVE",)
    order = ad.store.current().orders[0]
    assert order.cancel_sent and ad.journal.claimed(order.order_id, "CANCEL")
    assert len(api.calls) == 2 and api.calls[-1][0] == "cancel"
    ad.session = replace(ad.session, front_id=2, session_id=3)
    assert host.submit_effects(
        (a.Effect("CANCEL", order),), (binding,), (facts,), now
    ) == ("ALREADY_CLAIMED_NO_SEND",)
    assert len(api.calls) == 2


def test_continuous_fee_scan_is_incremental_but_new_host_replays_history(
    tmp_path, monkeypatch
):
    import guiyi_quant.simnow_execution.host as module

    host, ad, facts, binding, at, api = portfolio_setup(tmp_path)
    calls = []
    real = module.actual_fee

    def scan(left, right, state, journal):
        calls.append((left.source_id, right.source_id))
        return real(left, right, state, journal)

    monkeypatch.setattr(module, "actual_fee", scan)
    reports = [
        report_at(f.T + timedelta(minutes=n), ad.session.account_id) for n in (1, 2, 3)
    ]
    for n, report in enumerate(reports, 1):
        host.reconcile(report, (binding,), f.T + timedelta(minutes=n, seconds=20))
    assert len(calls) == 2
    host.reconcile(reports[-1], (binding,), f.T + timedelta(minutes=3, seconds=20))
    assert len(calls) == 2
    restarted = Host(
        ad.store,
        ad.journal,
        host.evidence,
        ad,
        ("RB", "JM"),
        continuous=True,
        run_id="new-process",
        deadline=at,
    )
    restarted.reconcile(reports[-1], (binding,), f.T + timedelta(minutes=3, seconds=20))
    assert len(calls) == 4 and calls[:2] == calls[2:]


def test_continuous_restart_after_snapshot_before_fee_recovers(tmp_path):
    old, ad, effect, facts, binding, at, api = host_setup(tmp_path)
    report = filled_report(ad, effect, at)
    old.evidence.append(read_snapshot(report))
    ad.store.close()
    ad.store = a.LocalStore(tmp_path / "account.db")
    host = Host(
        ad.store,
        ad.journal,
        old.evidence,
        ad,
        ("RB",),
        continuous=True,
        run_id="restarted",
        deadline=at,
    )
    proof = h.RecoveryInput("RB", "RB2701", 1, f.T + timedelta(minutes=60), "proof")
    _, state = host.reconcile(report, (binding,), at + timedelta(seconds=20), (proof,))
    assert state.phase == "READY" and state.fills[0].fee == D("3.12")
    assert ad.store.replay() == state and len(api.calls) == 1
