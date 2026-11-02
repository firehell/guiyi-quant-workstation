"""Isolated files and fake API only; no SDK import, credentials, or Broker I/O."""
from datetime import UTC, datetime, timedelta
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/quant-core"))
spec = importlib.util.spec_from_file_location("tested_session_diagnostic", ROOT / "scripts/broker/simnow_session_diagnostic.py")
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)
ACCOUNT = "a" * 64


def make_inbox(tmp_path):
    path = tmp_path / "signals.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE identity(account TEXT, scope TEXT);
        CREATE TABLE attempts(day TEXT PRIMARY KEY, count INTEGER NOT NULL);
        CREATE TABLE blocks(day TEXT PRIMARY KEY, code TEXT NOT NULL);
        CREATE TABLE signals(id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
        """)
        conn.execute("INSERT INTO identity VALUES (?,?)", (ACCOUNT, '["JM"]'))
        conn.executemany("INSERT INTO attempts VALUES (?,?)", [("20261102", 3), (diagnostic.DAY, 1)])
        conn.executemany("INSERT INTO blocks VALUES (?,?)", [("20261102", "PRIOR_BLOCK"),
                                                            (diagnostic.DAY, diagnostic.BLOCK)])
        conn.execute("INSERT INTO signals VALUES (1,'preserved')")
    path.chmod(0o600)
    return path


def test_budget_spends_exactly_one_and_preserves_all_blocks_and_signals(tmp_path):
    path = make_inbox(tmp_path)
    before = diagnostic.database(path, ACCOUNT)
    after = diagnostic.spend_budget(path, ACCOUNT, before)
    assert after["budget"] == {"attempts": [["20261102", 3], [diagnostic.DAY, 2]],
                               "blocks": before["budget"]["blocks"]}
    assert after["tables"]["signals"] == before["tables"]["signals"]
    assert after["tables"]["blocks"] == before["tables"]["blocks"]
    with pytest.raises(diagnostic.DiagnosticError):
        diagnostic.spend_budget(path, ACCOUNT, before)
    assert diagnostic.database(path, ACCOUNT)["budget"] == after["budget"]


def test_concurrent_budget_writer_blocks_without_retry_or_refund(tmp_path):
    path = make_inbox(tmp_path)
    before = diagnostic.database(path, ACCOUNT)
    with sqlite3.connect(path, isolation_level=None) as writer:
        writer.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError):
            diagnostic.spend_budget(path, ACCOUNT, before)
        writer.execute("ROLLBACK")
    assert dict(diagnostic.database(path, ACCOUNT)["budget"]["attempts"])[diagnostic.DAY] == 1


def test_changed_block_stops_before_spending(tmp_path):
    path = make_inbox(tmp_path)
    before = diagnostic.database(path, ACCOUNT)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE blocks SET code='DIFFERENT' WHERE day=?", (diagnostic.DAY,))
    with pytest.raises(diagnostic.DiagnosticError):
        diagnostic.spend_budget(path, ACCOUNT, before)
    actual = diagnostic.database(path, ACCOUNT)["budget"]
    assert dict(actual["attempts"])[diagnostic.DAY] == 1
    assert dict(actual["blocks"])[diagnostic.DAY] == "DIFFERENT"


def test_budget_trigger_cannot_modify_another_table(tmp_path):
    path = make_inbox(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TRIGGER bad AFTER UPDATE ON attempts BEGIN DELETE FROM blocks; END")
    before = diagnostic.database(path, ACCOUNT)
    with pytest.raises(sqlite3.DatabaseError):
        diagnostic.spend_budget(path, ACCOUNT, before)
    assert diagnostic.database(path, ACCOUNT) == before


def test_query_facade_denies_settlement_orders_and_third_query():
    calls, guards = [], []
    api = SimpleNamespace(**{name: (lambda *args, method=name: calls.append(method) or 0)
                             for name in diagnostic.METHODS})
    facade = diagnostic.ReadOnlyAPI(api, lambda: guards.append(True))
    facade.ReqAuthenticate(None, 1)
    facade.ReqUserLogin(None, 2)
    for unused in range(2):
        facade.ReqQryOrder(None, 112)
    for name in ("ReqOrderInsert", "ReqOrderAction", "ReqSettlementInfoConfirm", "Release", "query"):
        with pytest.raises(diagnostic.DiagnosticError):
            getattr(facade, name)
    with pytest.raises(diagnostic.DiagnosticError):
        facade.ReqQryOrder(None, 112)
    with pytest.raises(diagnostic.DiagnosticError):
        facade.ReqAuthenticate(None, 1)
    assert calls == ["ReqAuthenticate", "ReqUserLogin", "ReqQryOrder", "ReqQryOrder"]
    assert len(guards) == len(calls)


def test_guard_failure_prevents_any_native_submission():
    calls = []
    api = SimpleNamespace(**{name: (lambda *args: calls.append(True)) for name in diagnostic.METHODS})
    def stopped():
        diagnostic.invalid()
    facade = diagnostic.ReadOnlyAPI(api, stopped)
    with pytest.raises(diagnostic.DiagnosticError):
        facade.ReqAuthenticate(None, 1)
    assert calls == []


@pytest.mark.parametrize("native,passed", [
    ({"front_id": 71, "session_id": 83001, "max_order_ref": 0}, True),
    ({"front_id": -71, "session_id": 83001, "max_order_ref": 0}, False),
    ({"front_id": 71, "session_id": True, "max_order_ref": 0}, False),
    ({"front_id": 71, "session_id": 83001, "max_order_ref": -9}, False),
])
def test_native_fields_use_existing_integer_rules_without_executable_session(native, passed):
    from guiyi_quant.simnow_execution.model import FRONT
    value = diagnostic.structural_fields(native, diagnostic.DAY, FRONT)
    assert value["structural_passed"] is passed
    assert value["login_fields_structural_only"] is True
    assert value["execution_permitted"] is False and value["ledger_reconciled"] is False
    assert set(value["fields"]) == {"front_id", "session_id", "max_order_ref"}
    assert all(type(flag) is bool for flags in value["fields"].values() for flag in flags.values())
    assert "83001" not in json.dumps(value)


def test_failed_apply_keeps_claim_and_refuses_second_apply(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    at = datetime(2026, 11, 2, 14, tzinfo=UTC)
    config = tmp_path / "config"
    plan = dict(schema="simnow_session_diagnostic_v1", run=diagnostic.RUN, day=diagnostic.DAY,
                pid=diagnostic.PID, state=str(tmp_path), config=str(config), code={},
                planned_at=at.isoformat(), expires_at=(at + timedelta(seconds=60)).isoformat())
    diagnostic.new_file(tmp_path / "plan.private.json", diagnostic.encoded(plan))
    guards = []
    def stopped(*args, **kwargs):
        guards.append(True)
        diagnostic.invalid()
    guard = SimpleNamespace(state=tmp_path, config=config, check=stopped)
    monkeypatch.setattr(diagnostic, "now", lambda: at)
    monkeypatch.setattr(diagnostic, "code_binding", lambda: {})
    with pytest.raises(diagnostic.DiagnosticError):
        diagnostic.apply(guard)
    assert (tmp_path / "claim.private.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        diagnostic.apply(guard)
    assert len(guards) == 1


def test_readonly_snapshot_does_not_change_database_or_create_sidecars(tmp_path):
    path = make_inbox(tmp_path)
    original = path.read_bytes()
    diagnostic.database(path, ACCOUNT, copies=tmp_path)
    assert path.read_bytes() == original
    assert (tmp_path / "signals.sqlite.before").read_bytes() == original
    assert not any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))


def test_private_output_refuses_symlink_or_overwrite(tmp_path):
    tmp_path.chmod(0o700)
    target = tmp_path / "target"
    target.write_bytes(b"preserve")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        diagnostic.new_file(link, b"new")
    assert target.read_bytes() == b"preserve"


def test_probe_must_be_fresh_bound_and_have_no_retained_driver(tmp_path):
    at = datetime(2026, 11, 2, 14, tzinfo=UTC)
    path = tmp_path / "probe"
    value = dict(proof_at=at.isoformat(), status="READ_ONLY_INSPECTED", detached=True,
                 pid=diagnostic.PID, process_identity="a" * 64, target_calls=0, target_writes=0,
                 gateway_count=0, portfolio_count=0, retained_portfolios=[], supervisor_count=1,
                 supervisors=[dict(driver_absent=True, host_absent=True, pending=True, expected_run=True)])
    path.write_bytes(diagnostic.encoded(value))
    path.chmod(0o600)
    binding = {"process_identity": "a" * 64}
    assert diagnostic.probe_binding(path, binding, at)
    with pytest.raises(diagnostic.DiagnosticError):
        diagnostic.probe_binding(path, binding, at + timedelta(seconds=91))
    with pytest.raises(diagnostic.DiagnosticError):
        diagnostic.probe_binding(path, {"process_identity": "b" * 64}, at)
    value["gateway_count"] = 1
    path.write_bytes(diagnostic.encoded(value))
    with pytest.raises(diagnostic.DiagnosticError):
        diagnostic.probe_binding(path, binding, at)


@pytest.mark.parametrize("fault", [None, "detach", "release", "final_guard"])
def test_native_fact_precedes_release_and_success_receipt_requires_all_cleanup_checks(tmp_path, monkeypatch, fault):
    """Exercise the real budget debit and claim with an entirely fake native API."""
    from guiyi_quant.simnow_execution import inventory
    from guiyi_quant.simnow_execution.model import FRONT
    tmp_path.chmod(0o700)
    inbox = make_inbox(tmp_path)
    before = diagnostic.database(inbox, ACCOUNT)
    at = datetime(2026, 11, 2, 14, tzinfo=UTC)
    events = []

    class Raw:
        def RegisterSpi(self, value):
            if value is None:
                events.append("detach")
                if fault == "detach":
                    raise RuntimeError("never expose native error")
        def RegisterFront(self, value):
            assert value == FRONT
        def Init(self):
            gateway.api.ReqAuthenticate(None, 1)
            gateway.api.ReqUserLogin(None, 2)
        def Release(self):
            assert (tmp_path / "native-fact.private.json").exists()
            events.append("release")
            if fault == "release":
                raise RuntimeError("never expose native error")
        def __getattr__(self, method):
            assert method in diagnostic.METHODS
            return lambda *args: 0

    class Gateway:
        def __init__(self):
            self.native_session = dict(front_id=-71, session_id=83001, max_order_ref=0)
            self.front, self.day = FRONT, diagnostic.DAY
            self.user, self.password = "private-user", "private-password"
            self.failed = False
            self.result = {"private": "snapshot"}
            self.login_done = threading.Event()
            self.login_done.set()
        def snapshot(self):
            for unused in range(2):
                for method in list(diagnostic.METHODS)[2:]:
                    getattr(self.api, method)(None, 110)
            return self.result

    gateway = Gateway()
    native = SimpleNamespace(tdapi=SimpleNamespace(CThostFtdcTraderApi=SimpleNamespace(
        CreateFtdcTraderApi=lambda *args: Raw())))
    def gate(*args, **kwargs):
        if events and events[-1] == "release" and fault == "final_guard":
            diagnostic.invalid()
    guard = SimpleNamespace(state=tmp_path, config=tmp_path / "config", folder=tmp_path,
                            settings=SimpleNamespace(account_id=ACCOUNT), check=gate)
    plan = dict(schema="simnow_session_diagnostic_v1", run=diagnostic.RUN, day=diagnostic.DAY,
                pid=diagnostic.PID, state=str(tmp_path), config=str(guard.config), code={},
                before={"databases": {"signals.sqlite": before}}, planned_at=at.isoformat(),
                expires_at=(at + timedelta(seconds=60)).isoformat())
    diagnostic.new_file(tmp_path / "plan.private.json", diagnostic.encoded(plan))
    monkeypatch.setattr(diagnostic, "now", lambda: at)
    monkeypatch.setattr(diagnostic, "code_binding", lambda: {})
    monkeypatch.setattr(diagnostic, "load_gateway", lambda settings: (gateway, native))
    monkeypatch.setattr(inventory, "read_snapshot", lambda *args, **kwargs:
                        SimpleNamespace(account_id=ACCOUNT, trading_day=diagnostic.DAY))
    if fault is None:
        classification = diagnostic.apply(guard)
        # A negative native field is the diagnostic finding, not an inventory/cleanup failure.
        assert classification["structural_passed"] is False
        receipt = diagnostic.read_json(tmp_path / "release.private.json")[0]
        assert receipt["status"] == "READ_ONLY_DIAGNOSTIC_COMPLETE"
        assert receipt["native_released"] and receipt["spi_detached"] and receipt["guard_after_release_passed"]
        assert receipt["fact_sha256"] == diagnostic.read_file(tmp_path / "native-fact.private.json")[1]["sha256"]
    else:
        with pytest.raises(diagnostic.DiagnosticError):
            diagnostic.apply(guard)
        assert not (tmp_path / "release.private.json").exists()
    assert events == ["detach", "release"]
    assert diagnostic.read_json(tmp_path / "native-fact.private.json")[0]["readback_complete"] is True
    assert gateway.user == gateway.password == ""
    assert (tmp_path / "claim.private.json").exists()
    assert dict(diagnostic.database(inbox, ACCOUNT)["budget"]["attempts"])[diagnostic.DAY] == 2


def test_api_environment_is_added_before_application_imports_without_sdk_io(tmp_path, monkeypatch):
    site = tmp_path / "lib" / ("python" + str(sys.version_info.major) + "." +
                               str(sys.version_info.minor)) / "site-packages"
    site.mkdir(parents=True)
    monkeypatch.setattr(sys, "path", list(sys.path))
    before = list(sys.path)
    sdk_was_loaded = "openctp_ctp" in sys.modules
    diagnostic.api_dependencies(SimpleNamespace(api_env=tmp_path))
    assert sys.path == before + [str(site)]
    assert ("openctp_ctp" in sys.modules) is sdk_was_loaded


def test_bootstrap_failure_reports_fixed_phase_without_private_exception_text(monkeypatch, capsys):
    from guiyi_quant.simnow_execution import settings
    value = SimpleNamespace(schema=2, mode="trade", enabled=True, account_takeover_pending=True,
                            project_root=diagnostic.ROOT / ".worktrees/release-v1.16.64",
                            sdk_python=Path(sys.executable))
    monkeypatch.setattr(settings, "load_settings", lambda *args: value)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setenv("PGOPTIONS", "test_restore")
    def missing(*args):
        raise ModuleNotFoundError("private content must never cross the boundary")
    monkeypatch.setattr(diagnostic, "api_dependencies", missing)
    assert diagnostic.main(["plan"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result == dict(status="SESSION_DIAGNOSTIC_STOPPED", phase="API_DEPENDENCIES",
                          error_category="ModuleNotFoundError")
