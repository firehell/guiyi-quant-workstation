"""Maintenance recovery is narrowly typed; no network or real account involved."""
from datetime import datetime, UTC
from types import SimpleNamespace
import sys
import pytest
from guiyi_quant.tq_simulation import maintenance as m

T = datetime(2026, 11, 6, 11, 0, 59, tzinfo=UTC)


def sdk_error(monkeypatch, *, host='free-api.shinnytech.com', code_type=Exception,
              first=True, ops=True, conn='md'):
    class TqConnect:
        _conn_id = conn
        _first_connect = first
        def _run(self):
            url = 'wss://' + host + '/'
            in_ops_time = ops
            assert in_ops_time is ops
            raise code_type(f'与 {url} 的连接失败，每日 19:00-19:30 为日常运维时间，请稍后再试')
    monkeypatch.setitem(sys.modules, 'tqsdk.connect', SimpleNamespace(TqConnect=TqConnect))
    monkeypatch.setattr(m, 'version', lambda _: '3.10.4')
    try:
        TqConnect()._run()
    except Exception as e:
        return e


def test_exact_sdk_branch_and_window_required(monkeypatch):
    error = sdk_error(monkeypatch)
    assert m.is_terminal_maintenance(error, T)
    assert m.resume_after(T).isoformat() == '2026-11-06T11:31:00+00:00'
    assert not m.is_terminal_maintenance(error, T.replace(hour=12))
    assert not m.is_terminal_maintenance(Exception(*error.args), T)
    monkeypatch.setattr(m, 'version', lambda _: '3.10.5')
    assert not m.is_terminal_maintenance(error, T)


@pytest.mark.parametrize('kwargs', [dict(host='unknown.example'), dict(first=False),
    dict(ops=False), dict(conn='unknown'), dict(code_type=ValueError)])
def test_unknown_branch_still_holds(monkeypatch, kwargs):
    error = sdk_error(monkeypatch, **kwargs)
    assert not m.is_terminal_maintenance(error, T)


def test_settled_claim_and_reservation_gate():
    state = SimpleNamespace(orders=[SimpleNamespace(order_id='o', reconciled=True)],
                            unresolved_fill_ids=(), reservations=[SimpleNamespace(released=True)])
    controller = SimpleNamespace(store=SimpleNamespace(current=lambda: state),
        journal=SimpleNamespace(db=SimpleNamespace(execute=lambda _: [('o',)])))
    m.require_settled(controller)
    state.orders[0].reconciled = False
    with pytest.raises(ValueError, match='OBLIGATIONS_PENDING'):
        m.require_settled(controller)
    state.orders[0].reconciled = True
    state.reservations[0].released = False
    with pytest.raises(ValueError, match='OBLIGATIONS_PENDING'):
        m.require_settled(controller)
    state.reservations = []
    state.orders = []
    with pytest.raises(ValueError, match='OBLIGATIONS_PENDING'):
        m.require_settled(controller)
