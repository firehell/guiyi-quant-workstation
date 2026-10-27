"""Manual scope and budgets are independent of strategy/observer capabilities."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as N
import json

import pytest

from guiyi_quant.simnow_execution.host import Host
from guiyi_quant.simnow_execution.manual_host import admission, claim_login

T = datetime(2026, 10, 27, 6, tzinfo=UTC)
ID = "manual:97039e1c-850a-44af-9ab1-60af6c561ac4"


def authority(seconds, **updates):
    value = N(
        product="RB",
        owner="RB2701",
        contract="RB2701",
        contiguous_session_end=T + timedelta(seconds=seconds),
        session=N(can_trade=True, at=T, valid_until=T + timedelta(seconds=15)),
    )
    value.__dict__.update(updates)
    return value


def test_admission_requires_contiguous_window_not_final_close():
    admission(authority(900), T)
    for value in (
        authority(899),
        authority(600),
        authority(900, contiguous_session_end=None),
        authority(900, contract="RB2612"),
        authority(900, product="AL"),
    ):
        with pytest.raises(ValueError, match="CONTIGUOUS"):
            admission(value, T)
    value = authority(3600)
    value.session.can_trade = False
    with pytest.raises(ValueError, match="CONTIGUOUS"):
        admission(value, T)


def test_login_claim_is_once_and_keeps_observer_budget(tmp_path):
    observer = tmp_path / "signals.sqlite"
    observer.write_bytes(b"old attempt3 and block")
    claim_login(tmp_path, ID, T, "a" * 64)
    with pytest.raises(FileExistsError):
        claim_login(tmp_path, ID, T, "a" * 64)
    assert observer.read_bytes() == b"old attempt3 and block"
    saved = json.loads(next(tmp_path.glob("manual-*.json")).read_text())
    assert saved["connections"] == saved["max_connections"] == 1
    assert saved["hold_seconds"] == 600 and saved["side"] == 1


def fake_host(monkeypatch, orders=(), claimed=()):
    state = N(
        account_id="a" * 64, phase="READY", products=(N(product="RB"),), orders=orders
    )
    store = N(current=lambda: state)
    journal = N(claimed=lambda order_id, kind="SUBMIT": (order_id, kind) in claimed)
    sent, aborted = [], []
    adapter = N(
        session=N(account_id=state.account_id, trading_day="20261027"),
        dispatch=lambda *args: sent.append(args[0].order.order_id) or "SENT",
        abort_unsent=lambda *args: aborted.append(args[0]),
    )
    monkeypatch.setattr(
        "guiyi_quant.simnow_execution.host.action_hash", lambda *args: "b" * 64
    )
    host = Host(
        store,
        journal,
        N(snapshots=lambda: ()),
        adapter,
        "RB",
        run_id=ID,
        deadline=T,
        max_submits=1,
        manual_test_id=ID,
    )
    return host, sent, aborted


def effect(offset, signal_id=ID, order_id="one"):
    return N(
        kind="SUBMIT",
        order=N(
            product="RB",
            contract="RB2701",
            offset=offset,
            signal_id=signal_id,
            order_id=order_id,
        ),
    )


def dispatch(host, item):
    return host.submit_effects(
        (item,), (N(canonical="RB2701"),), (N(instrument=N(contract="RB2701")),), T
    )


def test_manual_closing_is_not_limited_by_opening_deadline_or_budget(monkeypatch):
    host, sent, aborted = fake_host(monkeypatch)
    host.submits = 1
    assert dispatch(host, effect("CLOSE")) == ("SENT",)
    assert sent == ["one"] and aborted == [] and host.submits == 1
    assert dispatch(host, effect("OPEN")) == ("RUN_BUDGET_EXHAUSTED_NO_SEND",)
    assert aborted == ["one"]


def test_manual_defense_rejects_strategy_effect_and_repeated_open_claim(monkeypatch):
    prior = effect("OPEN", order_id="prior").order
    host, sent, _ = fake_host(monkeypatch, (prior,), (("prior", "SUBMIT"),))
    for item, code in (
        (effect("CLOSE", "strategy"), "SCOPE"),
        (effect("OPEN"), "ALREADY_CLAIMED"),
    ):
        with pytest.raises(ValueError, match=code):
            dispatch(host, item)
    assert sent == []


def test_claimed_close_is_never_resent(monkeypatch):
    host, sent, _ = fake_host(monkeypatch, claimed=(("one", "SUBMIT"),))
    assert dispatch(host, effect("CLOSE")) == ("ALREADY_CLAIMED_NO_SEND",)
    assert sent == []
