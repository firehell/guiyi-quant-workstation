from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load(relative_path: str) -> dict[str, object]:
    return tomllib.loads(ROOT.joinpath(relative_path).read_text(encoding="utf-8"))


def test_frps_control_and_proxy_listeners_are_fail_closed() -> None:
    config = _load("deploy/frp/frps.toml.example")

    assert config["proxyBindAddr"] == "127.0.0.1"
    assert config["auth"] == {
        "method": "token",
        "tokenSource": {"type": "file", "file": {"path": "/etc/frp/server_token"}},
    }


def test_frpc_requires_the_same_environment_injected_token() -> None:
    config = _load("deploy/frp/frpc.toml.example")

    assert config["auth"] == {
        "method": "token",
        "tokenSource": {
            "type": "file",
            "file": {"path": "/usr/local/etc/frp/client_token"},
        },
    }
