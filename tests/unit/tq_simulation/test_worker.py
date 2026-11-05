"""Host-loop fixtures assert account effects, never imply a broker integration result."""

from datetime import datetime, UTC, timedelta
from types import SimpleNamespace
import logging
from guiyi_quant.tq_simulation import worker
from guiyi_quant.tq_simulation.runtime import write_private, read_private
from guiyi_quant.tq_simulation.controller import Controller
from guiyi_quant.htdy_account_execution import codec, model as m
from test_execution import A, snapshot, Transport


def host(monkeypatch, tmp_path, *, mode="trade", restart=False):
    base = tmp_path / "host"
    base.mkdir(mode=0o700)
    write_private(base / "control.json", {"mode": mode})
    config = dict(account_id=A, root=str(tmp_path), commit="b" * 40, tag="v1.16.82")
    write_private(base / "config.json", config)

    def publish(path, value):
        if path.name == "hold.json":
            raise AssertionError("unexpected persistent hold: " + value["code"])
        return write_private(path, value)

    monkeypatch.setattr(worker, "write_private", publish)
    monkeypatch.setattr(worker, "directory", lambda: base)
    monkeypatch.setattr(worker, "verify_config", lambda _: tmp_path)
    monkeypatch.setattr(worker, "verify_launcher", lambda _: None)
    monkeypatch.setattr(
        worker,
        "CredentialStore",
        lambda: SimpleNamespace(load=lambda: SimpleNamespace(account_id=A)),
    )
    monkeypatch.setattr(worker.signal, "signal", lambda *_: None)
    monkeypatch.setattr(logging, "disable", lambda *_: None)
    prior_at = datetime.now(UTC) - timedelta(days=1)
    calls = []

    class Gateway(Transport):
        reconnection_required = False

        def __init__(self, *_):
            super().__init__()
            self.n = 0

        def update(self, *_):
            self.n += 1
            if self.n >= 2:
                write_private(base / "control.json", {"mode": "stop"})

        def snapshot(self, now):
            if self.n > 5:
                raise AssertionError("host failed to stop")
            return snapshot(now)

        def close(self):
            calls.extend(self.calls)

    class Market:
        products = ("RB",)

        def __init__(self, *_):
            pass

        def close(self):
            pass

        def poll(self, state, contracts, *, inspect):
            now = datetime.now(UTC)
            sig = m.Signal(
                "recovery-boundary",
                "RB",
                "RB2701",
                now - timedelta(seconds=1),
                now,
                None,
                ("buy",),
                "c" * 64,
            )
            return dict(
                issues={},
                facts=[
                    dict(
                        product="RB",
                        contract="RB2701",
                        trading_day="2026-11-05",
                        session=codec.encode(
                            m.Session(
                                "RB2701",
                                now - timedelta(seconds=1),
                                now + timedelta(seconds=5),
                                "session",
                                now + timedelta(hours=2),
                                True,
                                True,
                            )
                        ),
                        source_id="authority",
                    )
                ],
                signals=[codec.encode(sig)] if restart else [],
                recovery=[
                    codec.encode(
                        m.RecoveryInput("RB", "RB2701", 0, prior_at, "recovery-proof")
                    )
                ],
            )

    monkeypatch.setattr(worker, "Gateway", Gateway)
    monkeypatch.setattr(worker, "Market", Market)
    monkeypatch.setattr(
        worker,
        "bind_symbol",
        lambda g, c, f: c.bind_symbol("SHFE.rb2701", "RB", f["contract"]),
    )
    if restart:
        accounts = base / "accounts"
        accounts.mkdir(mode=0o700)
        folder = accounts / A
        folder.mkdir(mode=0o700)
        c = Controller(folder, A, ("RB",), Transport())
        c.bootstrap(snapshot(prior_at), prior_at)
        c.owner("RB", "RB2701", prior_at, "old-owner")
        c.close()
    return base, calls


def test_inspect_cannot_take_over_account_even_with_saved_trade_control(
    monkeypatch, tmp_path, capsys
):
    base, calls = host(monkeypatch, tmp_path)
    assert worker.run(base / "config.json", inspect=True) == 0
    assert not (base / "accounts" / A / "account.sqlite").exists()
    assert read_private(base / "preflight.json")["ready_for_start"] is True
    assert calls == []


def test_recovery_discards_same_poll_signals_and_waits_for_next_natural_bar(
    monkeypatch, tmp_path
):
    base, calls = host(monkeypatch, tmp_path, restart=True)
    assert worker.run(base / "config.json") == 0
    assert not (base / "hold.json").exists()
    c = Controller(base / "accounts" / A, A, ("RB",), Transport())
    assert c.store.current().signals == ()
    assert calls == []
    c.close()


def test_current_mapping_coverage_does_not_count_historical_symbols(
    monkeypatch, tmp_path
):
    base, calls = host(monkeypatch, tmp_path)
    accounts = base / "accounts"
    accounts.mkdir(mode=0o700)
    folder = accounts / A
    folder.mkdir(mode=0o700)
    c = Controller(folder, A, ("RB",), Transport())
    c.bind_symbol("SHFE.rb2610", "RB", "RB2610")
    c.close()
    assert worker.run(base / "config.json", inspect=True) == 0
    proof = read_private(base / "preflight.json")
    assert proof["ready_for_start"] and proof["mapped_contracts"] == 1
    assert calls == []


def test_probe_and_service_environment_match_and_do_not_inherit_terminal_proxy(
    monkeypatch, tmp_path
):
    from guiyi_quant.tq_simulation.cli import service_environment, service_command

    monkeypatch.setenv("HTTPS_PROXY", "http://terminal-only.example:8080")
    monkeypatch.setenv("PYTHONPATH", "/terminal-only")
    env = service_environment(tmp_path)
    assert env["GUIYI_PROJECT_ROOT"] == str(tmp_path)
    assert env["PATH"] == "/usr/bin:/bin:/usr/sbin:/sbin"
    assert "HTTPS_PROXY" not in env and "PYTHONPATH" not in env
    assert env["USER"] == env["LOGNAME"] and env["HOME"]
    service = service_command(tmp_path)
    assert service[0] == "/bin/bash"
    assert service[1].endswith("/GuiyiQuant/run-tq-simulation.sh")
    assert service_command(tmp_path, inspect=True) == service + ["--inspect"]


def test_private_launcher_is_bound_to_exact_source_and_rejects_links(
    monkeypatch, tmp_path
):
    import pytest
    from guiyi_quant.tq_simulation import runtime as rt

    root = tmp_path / "release"
    source = root / "scripts/ops/macos/run-tq-simulation.sh"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"#!/bin/bash\nexit 0\n")
    monkeypatch.setattr(rt, "directory", lambda: tmp_path / "tqkq-simulation")
    path = rt.launcher_path()
    rt.write_private_bytes(path, source.read_bytes())
    assert rt.verify_launcher(root) == path and path.stat().st_mode & 0o777 == 0o600
    source.write_bytes(b"#!/bin/bash\nexit 1\n")
    with pytest.raises(ValueError, match="LAUNCHER_IDENTITY_UNPROVEN"):
        rt.verify_launcher(root)
    path.unlink()
    path.symlink_to(source)
    with pytest.raises(ValueError, match="LAUNCHER_IDENTITY_UNPROVEN"):
        rt.verify_launcher(root)


def test_private_binary_writer_rejects_hardlinks_and_retains_json_contract(tmp_path):
    import os
    import pytest
    from guiyi_quant.tq_simulation import runtime as rt

    path = tmp_path / "original"
    rt.write_private(path, {"mode": "observe"})
    assert rt.read_private(path) == {"mode": "observe"}
    linked = tmp_path / "linked"
    os.link(path, linked)
    with pytest.raises(ValueError, match="PRIVATE_PATH_REQUIRED"):
        rt.write_private_bytes(linked, b"overwrite")
    assert path.read_bytes() == linked.read_bytes()


def test_stop_does_not_require_keychain_to_remain_available(monkeypatch, tmp_path):
    from guiyi_quant.tq_simulation import cli

    write_private(tmp_path / "config.json", {"account_id": A})
    monkeypatch.setattr(cli, "directory", lambda: tmp_path)
    monkeypatch.setattr(cli, "verify_config", lambda _: tmp_path)

    def unavailable():
        raise AssertionError("stop must not read credentials")

    monkeypatch.setattr(cli, "CredentialStore", unavailable)
    assert cli.main(["stop"]) == 0
    assert read_private(tmp_path / "control.json") == {"mode": "stop"}


def test_channel_failure_preserves_first_hold_and_safe_stop_needs_no_market(
    monkeypatch, tmp_path
):
    from itertools import count

    base, calls = host(monkeypatch, tmp_path, restart=True)
    ticks = count(0, 2)
    monkeypatch.setattr(worker, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    monkeypatch.setattr(worker, "write_private", write_private)
    market_type = worker.Market
    prior_poll = market_type.poll
    attempts = []
    first_hold = []

    def update(self, *_):
        self.n += 1
        if self.n >= 4:
            write_private(base / "control.json", {"mode": "stop"})

    monkeypatch.setattr(worker.Gateway, "update", update)

    def poll(self, *args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            return prior_poll(self, *args, **kwargs)
        if len(attempts) == 2:
            raise ValueError("TQ_MARKET_TIMEOUT")
        first_hold.append((base / "hold.json").read_bytes())
        raise ValueError("TQ_MARKET_CHANNEL_FAILED")

    monkeypatch.setattr(market_type, "poll", poll)
    assert worker.run(base / "config.json") == 0
    assert len(attempts) == 3
    assert read_private(base / "hold.json")["code"] == "TQ_MARKET_TIMEOUT"
    assert (base / "hold.json").read_bytes() == first_hold[0]
    assert calls == []
