"""Private fixture roots only; monitoring may never create execution state."""

from datetime import datetime, UTC, timedelta
from pathlib import Path
import pytest
from guiyi_quant.simnow_execution.monitor import MonitorReader, MonitorPublisher

T = datetime(2026, 10, 27, 1, tzinfo=UTC)


def test_absent_root_is_unconnected_and_is_not_created(tmp_path):
    root = tmp_path / "not-created"
    result = MonitorReader(root).overview(T)
    assert result["status"] == "not_connected" and result["metrics"]["equity"] is None
    assert result["positions"] == [] and not result["position_projection_complete"]
    assert not root.exists()


def test_monitor_publication_does_not_switch_accounts(tmp_path):
    first = MonitorPublisher(tmp_path, "a" * 64, "run-one")
    assert first.publish("STARTING", T)
    other = MonitorPublisher(tmp_path, "b" * 64, "run-two")
    assert not other.publish("STARTING", T)
    import json

    assert json.loads((tmp_path / "monitor.json").read_text())["account_id"] == "a" * 64


def test_corrupt_index_is_unavailable_not_zero_balance(tmp_path):
    (tmp_path / "monitor.json").write_text("{")
    result = MonitorReader(tmp_path).overview(T)
    assert result["status"] == "unavailable" and result["metrics"]["equity"] is None


def fixture_root(tmp_path):
    import sys
    import importlib.util

    helper = Path(__file__).parents[1] / "simnow_host"
    sys.path.insert(0, str(helper))
    spec = importlib.util.spec_from_file_location(
        "monitor_host_fixture", helper / "test_host.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    account = module.f.ACCOUNT
    folder = tmp_path / account
    folder.mkdir(mode=0o700)
    host, adapter, e, facts, b, when, api = module.host_setup(folder)
    snapshot, state = host.reconcile(
        module.filled_report(adapter, e, when), (b,), when + timedelta(seconds=20)
    )
    host.evidence.close()
    adapter.journal.close()
    adapter.store.close()
    for old, new in (
        ("account.db", "account.sqlite"),
        ("dispatch.db", "dispatch.sqlite"),
        ("evidence.db", "native-evidence.sqlite"),
    ):
        (folder / old).rename(folder / new)
    observed = when + timedelta(seconds=20)
    from guiyi_quant.htdy_account_execution.codec import digest

    assert MonitorPublisher(tmp_path, account, "fixture-run", "RB").publish(
        "ACTIVE",
        observed,
        connection="LOGGED_IN",
        native_source_id=snapshot.source_id,
        ledger_hash=digest(state),
    )
    return MonitorReader(tmp_path), observed, folder


def test_readonly_projection_reuses_native_money_and_chain(tmp_path):
    import hashlib

    reader, now, folder = fixture_root(tmp_path)
    before = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()
    }
    result = reader.overview(now)
    assert result["status"] == "available"
    assert (
        result["metrics"]["equity"] == "99996.88"
        and result["metrics"]["net_profit"] == "-3.12"
    )
    assert (
        result["metrics"]["daily_fee"] == "3.12"
        and result["position_projection_complete"]
    )
    assert result["positions"][0]["quantity"] == 1
    page = reader.records(now)
    assert {r["kind"] for r in page["items"]} == {"signal", "risk", "order", "fill"}
    row = next(r for r in page["items"] if r["kind"] == "fill")
    detail = reader.detail(now, row["id"])
    assert {r["kind"] for r in detail["chain"]} == {"signal", "risk", "order", "fill"}
    after = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()
    }
    assert before == after
    import json

    encoded = json.dumps(result) + json.dumps(detail)
    assert "123456" not in encoded and str(folder) not in encoded


def test_observer_stale_and_stopped_are_not_connected(tmp_path):
    reader, now, folder = fixture_root(tmp_path)
    stale = reader.overview(now + timedelta(seconds=31))
    assert (
        stale["observer"]["status"] == "stale"
        and stale["observer"]["connection"] == "UNKNOWN"
    )
    import json

    account = json.loads((tmp_path / "monitor.json").read_text())["account_id"]
    binding = json.loads((tmp_path / "monitor.json").read_text())
    MonitorPublisher(tmp_path, account, "fixture-run").publish(
        "STOPPED",
        now + timedelta(seconds=32),
        connection="RELEASED",
        native_source_id=binding["native_source_id"],
        ledger_hash=binding["ledger_hash"],
    )
    stopped = reader.overview(now + timedelta(seconds=33))
    assert (
        stopped["observer"]["status"] == "stopped"
        and stopped["metrics"]["equity"] == "99996.88"
    )


@pytest.mark.parametrize("problem", ["account", "ledger", "native", "symlink"])
def test_source_damage_never_falls_back_to_flat(tmp_path, problem):
    reader, now, folder = fixture_root(tmp_path)
    import sqlite3

    if problem == "account":
        import json

        index = json.loads((tmp_path / "monitor.json").read_text())
        index["account_id"] = "b" * 64
        (tmp_path / "monitor.json").write_text(json.dumps(index))
    elif problem == "ledger":
        db = sqlite3.connect(folder / "account.sqlite")
        db.execute("UPDATE projection SET payload='{}'")
        db.commit()
        db.close()
    elif problem == "native":
        (folder / "native-evidence.sqlite").unlink()
    else:
        source = folder / "dispatch.sqlite"
        source.rename(folder / "other.sqlite")
        source.symlink_to(folder / "other.sqlite")
    result = reader.overview(now)
    assert result["status"] == "unavailable" and result["metrics"]["equity"] is None
    assert not result["position_projection_complete"]


def test_monitor_failure_does_not_change_host_or_native_actions(tmp_path):
    root = tmp_path / "bad"
    root.write_text("not a directory")
    assert MonitorPublisher(root, "a" * 64, "run").publish("ERROR", T) is False
    assert root.read_text() == "not a directory"


def test_pending_trade_keeps_native_position_and_withholds_budget(tmp_path):
    import sqlite3
    import json

    reader, now, folder = fixture_root(tmp_path)
    db = sqlite3.connect(folder / "dispatch.sqlite")
    db.execute(
        "INSERT INTO events(event_id,payload,received_at) VALUES(?,?,?)",
        ("unreconciled-trade", json.dumps({"kind": "trade"}), now.isoformat()),
    )
    db.commit()
    db.close()
    value = reader.overview(now)
    assert value["status"] == "partial" and not value["position_projection_complete"]
    assert value["positions"][0]["quantity"] == 1
    assert value["metrics"]["margin_limit"] is None
    assert any(i["code"] == "FEE_PENDING" for i in value["issues"])


def test_read_during_uncommitted_native_write_remains_consistent(tmp_path):
    import sqlite3

    reader, now, folder = fixture_root(tmp_path)
    db = sqlite3.connect(folder / "native-evidence.sqlite")
    db.execute("BEGIN IMMEDIATE")
    db.execute("INSERT INTO snapshots(source,payload) VALUES('uncommitted','{}')")
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    assert reader.overview(now)["status"] == "available"
    assert before == {p.name: p.read_bytes() for p in folder.iterdir()}
    db.rollback()
    db.close()


def test_crossday_net_return_unknown_but_native_equity_preserved(tmp_path):
    from guiyi_quant.simnow_execution.monitor_projection import overview
    from dataclasses import replace

    reader, now, _ = fixture_root(tmp_path)
    data = reader.load(now)
    baseline = replace(data["snapshots"][0], trading_day="20261026")
    data["baseline"] = baseline
    result = overview(data, now)
    assert result["metrics"]["net_profit"] is None
    assert result["metrics"]["return_ratio"] is None
    assert result["metrics"]["equity"] == "99996.88"
    assert result["curve"][-1]["net_profit"] is None


def test_decimal_strings_never_use_exponent_notation():
    from guiyi_quant.simnow_execution.monitor_projection import _decimal, _text
    from decimal import Decimal

    assert _decimal(Decimal("1E-7")) == "0.0000001"
    assert _text(Decimal("0E-8")) == "0.00000000"
    assert _text(Decimal("-1E-8")) == "-0.00000001"


def test_cursor_bound_to_query_and_snapshot(tmp_path, monkeypatch):
    from guiyi_quant.simnow_execution import monitor_projection as p
    from guiyi_quant.simnow_execution.monitor import MonitorError

    reader, now, _ = fixture_root(tmp_path)
    data = reader.load(now)
    sample = p.all_records(data)[0]
    monkeypatch.setattr(
        p, "all_records", lambda _: [{**sample, "id": str(i)} for i in range(61)]
    )
    first = p.records_page(data, "all", "", "", None, None, None)
    assert len(first["items"]) == 50
    second = p.records_page(data, "all", "", "", None, None, first["next_cursor"])
    assert len(second["items"]) == 11 and second["next_cursor"] is None
    with pytest.raises(MonitorError, match="SNAPSHOT_CHANGED"):
        p.records_page(data, "signal", "", "", None, None, first["next_cursor"])
    with pytest.raises(MonitorError, match="SNAPSHOT_CHANGED"):
        p.records_page(
            {**data, "snapshot": "changed"},
            "all",
            "",
            "",
            None,
            None,
            first["next_cursor"],
        )


def test_wal_mode_rejected_before_sqlite_can_create_sidecars(tmp_path):
    import sqlite3

    reader, now, folder = fixture_root(tmp_path)
    db = sqlite3.connect(folder / "dispatch.sqlite")
    db.execute("PRAGMA journal_mode=WAL")
    db.close()
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    assert reader.overview(now)["status"] == "unavailable"
    assert before == {p.name: p.read_bytes() for p in folder.iterdir()}


def test_abnormal_native_quantity_remains_visible_as_pending(tmp_path):
    from guiyi_quant.simnow_execution.monitor_projection import overview
    from dataclasses import replace
    import json

    reader, now, _ = fixture_root(tmp_path)
    data = reader.load(now)
    native = data["snapshots"][-1]
    payload = native.data
    payload["positions"][0]["Position"] = 3
    data["snapshots"][-1] = replace(native, payload_json=json.dumps(payload))
    result = overview(data, now)
    assert result["status"] == "partial"
    assert not result["position_projection_complete"]
    assert result["metrics"]["margin_limit"] is None
    assert result["positions"][0]["quantity"] == 3
    assert result["positions"][0]["status"] == "pending"
    assert any(i["code"] == "NATIVE_POSITION_PENDING" for i in result["issues"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("native_source_id", "ctp-inventory:20261027:" + "0" * 64),
        ("ledger_hash", "0" * 64),
        ("native_source_id", None),
    ],
)
def test_index_cannot_claim_an_unbound_source(tmp_path, field, value):
    import json

    reader, now, _ = fixture_root(tmp_path)
    index = tmp_path / "monitor.json"
    payload = json.loads(index.read_text())
    payload[field] = value
    index.write_text(json.dumps(payload))
    result = reader.overview(now)
    assert result["status"] == "unavailable"
    assert result["metrics"]["equity"] is None
