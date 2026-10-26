from datetime import date
import pytest
from app.reference_trading.inbox_protocol import ReceivingProtocol


class Journal:
    def days(self):
        return (date(2026, 10, 27),)

    def cursor(self, *_):
        return "123-4"

    def tail(self, *_):
        return "200-1"


def test_request_does_not_move_cursor_and_actual_owner_freezes_boundary(tmp_path):
    p = ReceivingProtocol(tmp_path / "protocol.json", binding="a" * 64)
    assert not p.enabled()
    p.request(schema_ready=lambda: None)
    assert not p.enabled()
    assert p.activate(Journal(), assert_owned=lambda: None, warmup=True) is False
    assert not p.enabled()
    assert p.activate(Journal(), assert_owned=lambda: None)
    assert p.enabled()
    state = p.read()
    assert state["boundaries"] == {"2026-10-27": {"cursor": "123-4", "tail": "200-1"}}
    assert p.activate(Journal(), assert_owned=lambda: None)
    assert p.read() == state


def test_binding_drift_and_failed_ownership_cannot_activate(tmp_path):
    p = ReceivingProtocol(tmp_path / "protocol.json", binding="a" * 64)
    p.request(schema_ready=lambda: None)
    with pytest.raises(ValueError, match="REFERENCE_INBOX_BINDING_DRIFT"):
        ReceivingProtocol(p.path, binding="b" * 64).enabled()

    def lost():
        raise RuntimeError("owner lost")

    with pytest.raises(RuntimeError):
        p.activate(Journal(), assert_owned=lost)
    assert not p.enabled()
