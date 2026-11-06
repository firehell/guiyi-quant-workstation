"""No broker I/O: routing and failure cleanup against actual proxy resolution."""
import os
import sys
from types import SimpleNamespace
from urllib.request import getproxies_environment, proxy_bypass

import pytest
from guiyi_quant.tq_simulation import transport
from guiyi_quant.tq_simulation.gateway import Gateway


def clean_proxy(monkeypatch):
    for key in tuple(os.environ):
        if key.lower().endswith("_proxy"):
            monkeypatch.delenv(key)


def test_only_vendor_hosts_bypass_materialized_proxy_and_close_restores(monkeypatch):
    clean_proxy(monkeypatch)
    monkeypatch.setenv("no_proxy", "localhost")
    original = dict(os.environ)
    proxies = {"https": "http://127.0.0.1:7897", "http": "http://127.0.0.1:7897",
               "socks": "socks5://127.0.0.1:7897", "no": "localhost"}
    monkeypatch.setattr(transport, "getproxies", lambda: proxies)
    scope = transport.SdkTransport()
    try:
        assert getproxies_environment()["socks"] == proxies["socks"]
        assert all(proxy_bypass(host) for host in transport.DIRECT_HOSTS)
        assert not proxy_bypass("unrelated.example")
        assert proxy_bypass("localhost")
        assert transport.sdk_environment(original, {})["no_proxy"]
    finally:
        scope.close()
    assert dict(os.environ) == original


@pytest.mark.parametrize("md,td", [
    ("wss://free-api.shinnytech.com/a", "wss://otg-sim.shinnytech.com/b"),
])
def test_known_transport_endpoints_are_verified_without_network(md, td):
    transport.SdkTransport.verify(None, SimpleNamespace(_md_url=md), SimpleNamespace(_td_url=td))


@pytest.mark.parametrize("url", [
    "ws://free-api.shinnytech.com/", "wss://free-api.shinnytech.com:444/",
    "wss://other.shinnytech.com/", "wss://user:secret@free-api.shinnytech.com/",
])
def test_unknown_endpoint_cannot_enable_gateway(url):
    with pytest.raises(ValueError, match="TQ_TRANSPORT_ENDPOINT_UNPROVEN"):
        transport.SdkTransport.verify(None, SimpleNamespace(_md_url=url),
                                     SimpleNamespace(_td_url="wss://otg-sim.shinnytech.com/"))


def test_helper_receives_original_environment(monkeypatch, tmp_path):
    from guiyi_quant.tq_simulation import market
    clean_proxy(monkeypatch)
    before = dict(os.environ)
    monkeypatch.setenv("no_proxy", ",".join(transport.DIRECT_HOSTS))
    captured = {}
    def popen(*args, **kwargs):
        captured.update(kwargs)
        return object()
    monkeypatch.setattr(market.subprocess, "Popen", popen)
    monkeypatch.setattr(market.Market, "request", lambda *_: {"products": ["JM"]})
    market.Market(tmp_path, tmp_path / "services/quant-api/.venv/bin/python", before)
    assert captured["env"] == {**before, "GUIYI_PROJECT_ROOT": str(tmp_path)}
    assert "no_proxy" not in captured["env"]


def test_notifications_are_sanitized_and_disconnect_still_blocks():
    g = Gateway.__new__(Gateway)
    g.api = SimpleNamespace(_data={"notify": {"id": {
        "code": 2019112911, "conn_id": "md", "content": "SECRET", "url": "SECRET"
    }}})
    g.notifications, g.connections, g.reconnection_required = set(), {}, False
    with pytest.raises(ValueError, match="TQ_DISCONNECTED"):
        g.refresh_notifications()
    assert g.reconnection_required
    events = g.connection_events()
    assert len(events) == 1 and set(events[0]) == {"code", "connection", "at"}
    assert events[0]["connection"] == "md" and "SECRET" not in str(events)
    assert not g.connection_events()


@pytest.mark.parametrize("failure", ["login", "endpoint", "account"])
def test_gateway_failure_closes_sdk_and_restores_proxy_scope(monkeypatch, failure):
    from guiyi_quant.tq_simulation import gateway
    clean_proxy(monkeypatch)
    original = dict(os.environ)
    closed = []
    account = SimpleNamespace(_td_url="wss://otg-sim.shinnytech.com/")
    class Api:
        def __init__(self, **_):
            if failure == "login":
                raise ValueError("LOGIN_FAILED")
            self._md_url = "wss://unknown.example/" if failure == "endpoint" else "wss://free-api.shinnytech.com/"
            self._account = SimpleNamespace(_get_account_key=lambda _: "key")
        def get_account(self, **_):
            raise ValueError("ACCOUNT_FAILED")
        def close(self):
            closed.append(True)
    sdk = SimpleNamespace(TqApi=Api, TqAuth=lambda *_: object(), TqKq=lambda: account)
    monkeypatch.setitem(sys.modules, "tqsdk", sdk)
    monkeypatch.setattr(gateway, "version", lambda _: "3.10.4")
    monkeypatch.setattr(transport, "getproxies", lambda: {"https": "http://127.0.0.1:7897"})
    with pytest.raises(ValueError):
        Gateway(SimpleNamespace(username="unused", password="unused", account_id="id"))
    assert dict(os.environ) == original
    assert len(closed) == (0 if failure == "login" else 1)
