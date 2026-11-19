"""Offline operator checks using temporary plans, handover files and a fake writer."""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from importlib import import_module
import json
import os
from pathlib import Path
import signal
import sys
from types import SimpleNamespace

import pytest

from app import runtime_bindings, runtime_handover
from app.market_data.catalog import _PostgresMaintenanceLease
from app.reference_trading import interval_retirement
from app.reference_trading.recovery_campaign import AttemptProgress, write_once


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / "scripts"))
    return import_module("reference_interval_retirement")


def test_plan_fifo_is_rejected_before_read(cli, tmp_path):
    path = tmp_path / "fifo"
    os.mkfifo(path, 0o600)

    def timed_out(*_):
        pytest.fail("open waited for a FIFO writer")

    previous = signal.signal(signal.SIGALRM, timed_out)
    try:
        signal.alarm(2)
        with pytest.raises(RuntimeError, match="PLAN_UNSAFE"):
            cli.read_plan(path)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def test_plan_link_and_oversize_rejected(cli, tmp_path):
    path = tmp_path / "plan"
    write_once(path, {})
    link = tmp_path / "alias"
    os.link(path, link)
    with pytest.raises(RuntimeError, match="PLAN_UNSAFE"):
        cli.read_plan(path)
    link.unlink()
    with path.open("ab") as file:
        file.truncate(32 * 1024 * 1024 + 1)
    with pytest.raises(RuntimeError, match="PLAN_UNSAFE"):
        cli.read_plan(path)


def test_lease_loss_never_reacquires_lock():
    queries = []
    def other_backend_has_lock(query, params):
        queries.append(str(query))
        return False

    connection = SimpleNamespace(closed=False, invalidated=False, scalar=other_backend_has_lock)
    lease = _PostgresMaintenanceLease(connection, close_on_release=False)
    with pytest.raises(RuntimeError, match="MAINTENANCE_LEASE_LOST"):
        lease.assert_held()
    assert len(queries) == 1 and "pid=pg_backend_pid()" in queries[0]
    assert "pg_try_advisory_lock" not in queries[0]
    connection.invalidated = True
    with pytest.raises(RuntimeError, match="MAINTENANCE_LEASE_LOST"):
        lease.assert_held()
    assert len(queries) == 1


@pytest.fixture
def invocation(cli, tmp_path, monkeypatch):
    @dataclass(frozen=True)
    class ActiveBinding:
        root: str
        commit: str
        enabled: bool
        generation: int

    binding = ActiveBinding(str(cli.ROOT), "b" * 40, True, 4)
    monkeypatch.setattr(cli, "business_claim_path", lambda: tmp_path / "business-claim")
    handlers = {}
    monkeypatch.setattr(signal, "signal", handlers.__setitem__)
    monkeypatch.setattr(runtime_bindings, "resolve_service_binding", lambda _: binding)
    monkeypatch.setattr(runtime_handover, "runtime_directory", lambda: tmp_path)
    runtime_handover._write(tmp_path / "reference-worker.owner.json", {
        "schema_version": 1, "service": "reference-worker", "generation": 4, "phase": "active",
    })
    monkeypatch.setattr(cli, "load_dependencies", lambda _: "a" * 64)
    monkeypatch.setattr(cli, "verify_code", lambda *_: None)
    inventory = tmp_path / "inventory"
    write_once(inventory, {})
    monkeypatch.setattr(interval_retirement, "INVENTORY_SHA256", sha256(inventory.read_bytes()).hexdigest())
    monkeypatch.setattr(sys, "argv", [
        "retire", "--exact-root", str(cli.ROOT), "--exact-commit", binding.commit,
        "--inventory", str(inventory), "--phase", "execute", "--attempt", str(tmp_path / "attempt"),
        "--plan", str(tmp_path / "plan"),
    ])
    return handlers


def test_prewrite_termination_releases_drain_even_if_progress_disk_fails(cli, tmp_path, monkeypatch, invocation):
    def terminate_while_waiting(*args):
        invocation[signal.SIGTERM](signal.SIGTERM, None)

    record = AttemptProgress.record
    def disk_failure(self, stage, **fields):
        if stage == "stopped":
            raise OSError("simulated progress disk failure")
        return record(self, stage, **fields)

    monkeypatch.setattr(cli, "wait_phase", terminate_while_waiting)
    monkeypatch.setattr(AttemptProgress, "record", disk_failure)
    with pytest.raises(OSError, match="simulated progress disk failure"):
        cli.main()
    assert json.loads((tmp_path / "reference-worker.handover.json").read_text())["phase"] == "cancelled"
    assert not (tmp_path / "business-claim").exists()


def test_unknown_apply_keeps_drain_and_cannot_reuse_attempt(cli, tmp_path, monkeypatch, invocation):
    monkeypatch.setattr(cli, "wait_phase", lambda *_: None)
    calls = []

    class UnknownWriter:
        def __init__(self, *_, **kwargs):
            self.inventory = kwargs["inventory"]

        def plan(self, *_, **kwargs):
            return {"plan_hash": "c" * 64}

        def apply(self, *_, **kwargs):
            calls.append(kwargs["expected_plan_hash"])
            raise RuntimeError("FORMULA_TRANSITION_COMMIT_OUTCOME_UNKNOWN")

    @contextmanager
    def no_db(*args):
        yield None, None, None

    monkeypatch.setattr(cli, "resources", no_db)
    monkeypatch.setattr(interval_retirement, "NewowIntervalRetirement", UnknownWriter)
    with pytest.raises(RuntimeError, match="COMMIT_OUTCOME_UNKNOWN"):
        cli.main()
    assert json.loads((tmp_path / "reference-worker.handover.json").read_text())["phase"] == "drain"
    with pytest.raises(RuntimeError, match="NEW_ATTEMPT_REQUIRED"):
        cli.main()
    sys.argv[-1] = str(tmp_path / "second-plan")
    sys.argv[sys.argv.index("--attempt") + 1] = str(tmp_path / "second-attempt")
    with pytest.raises(RuntimeError, match="CLAIM_CONSUMED_READBACK_ONLY"):
        cli.main()
    assert calls == ["c" * 64]
