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
