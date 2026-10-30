"""Supervisor audits run only after execution and fresh callback/account checks."""

from datetime import timedelta
from types import SimpleNamespace as NS
import pytest
from test_native_portfolio import T
from guiyi_quant.simnow_execution.supervisor import Supervisor


def fixture():
    events = []
    state = NS(
        phase="READY",
        readback_valid=True,
        products=(),
        orders=(),
        readback=NS(at=T, valid_until=T + timedelta(seconds=30)),
        activated_at=T,
    )

    def audit(*args, **kwargs):
        events.append(("audit", kwargs))
        return dict(status="CHECKED", product="JM")

    s = object.__new__(Supervisor)
    s.settings = NS(mode="trade")
    s.driver = NS(
        audit_next=audit,
        transport_failed=False,
        gateway=NS(failed=False),
        input_checks={},
        input_diagnostics={},
    )
    s.store = NS(current=lambda: state, _needs_recovery=False)
    s.host = NS(
        pending=(),
        needs_recovery=False,
        adapter=NS(_faulted=False, drain=lambda: events.append(("drain", {})) or ()),
    )
    s.market = NS(
        next_audit_boundary=lambda now: (
            events.append(("boundary", {})) or T + timedelta(minutes=30)
        )
    )
    s.products = ("JM",)
    s.day = "20261027"
    s.now = lambda: T
    return s, state, events


def test_idle_audit_follows_callback_drain():
    s, _, events = fixture()
    s._audit_trade_inputs()
    assert [e[0] for e in events] == ["drain", "boundary", "audit"]
    assert events[-1][1]["idle"] is True
    assert events[-1][1]["obligations_pending"] is False


@pytest.mark.parametrize(
    "reason", ["host_pending", "drain_pending", "recovery", "readback", "force"]
)
def test_busy_cycle_notifies_audit_to_discard_partial(reason):
    s, state, events = fixture()
    if reason == "host_pending":
        s.host.pending = ("pending",)
    if reason == "drain_pending":
        s.host.adapter.drain = lambda: ("pending",)
    if reason == "recovery":
        s.host.needs_recovery = True
    if reason == "readback":
        state.readback_valid = False
    s._audit_trade_inputs(force_defer=reason == "force")
    call = events[-1]
    assert call[0] == "audit" and call[1]["idle"] is False
    assert call[1]["next_boundary"] is None


@pytest.mark.parametrize(
    "transport,gateway,code",
    [(True, False, "NATIVE_TRANSPORT_FAILED"), (False, True, "NATIVE_GATEWAY_FAILED")],
)
def test_audit_native_failure_keeps_existing_host_failclosed(transport, gateway, code):
    s, _, _ = fixture()

    def audit(*args, **kwargs):
        s.driver.transport_failed = transport
        s.driver.gateway.failed = gateway
        return dict(status="FAILED")

    s.driver.audit_next = audit
    with pytest.raises(ValueError, match=code):
        s._audit_trade_inputs()


def test_unknown_boundary_is_passed_as_none_without_query_permission():
    s, _, events = fixture()
    s.market.next_audit_boundary = lambda _: None
    s._audit_trade_inputs()
    assert events[-1][1]["next_boundary"] is None


def test_execution_candidate_always_preempts_audit(monkeypatch):
    from guiyi_quant.htdy_account_execution import scheduling

    s, _, events = fixture()
    monkeypatch.setattr(
        scheduling, "execution_candidates", lambda *args, **kwargs: ("candidate",)
    )
    s._audit_trade_inputs()
    assert events[-1][1]["idle"] is False
    assert events[-1][1]["next_boundary"] is None
    assert not any(kind == "boundary" for kind, _ in events)


def test_product_failure_does_not_change_account_gate_or_issues():
    s, state, _ = fixture()
    s.issues = {"JM": "EXISTING_ACCOUNT_GATE"}
    s.driver.audit_next = lambda *args, **kwargs: dict(status="FAILED", product="JM")
    s._audit_trade_inputs()
    assert s.issues == {"JM": "EXISTING_ACCOUNT_GATE"}
    assert state.phase == "READY" and state.readback_valid
