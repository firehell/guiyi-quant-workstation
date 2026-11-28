from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.backtest_center import router
from app.backtest_center.contracts import BacktestError
from app.backtest_center.store import RunStore
from app.backtest_center.worker import Settings, Worker


CONFIG = {
    "product": "fu",
    "contract": "FU2603",
    "warmup_start": "2025-10-09",
    "start": "2026-01-06",
    "end": "2026-01-08",
    "initial_capital": "100000",
}
SNAPSHOT = {
    "data_revision": "a" * 64, "input_sha256": "b" * 64,
    "engine": {"name": "rqalpha-plus", "version": "test-double"}, "qualification": "TRIAL",
}
VALUATION = "2026-01-06T15:00:00+08:00"
TRADE = {
    "trade_id": "fill_a", "contract": "FU2603", "entry_at": "2026-01-06T09:06:00+08:00",
    "marked_at": "2026-01-06T15:30:00+08:00", "entry_price": "2701", "direction": "LONG", "status": "OPEN",
}
RESULT = {
    "summary": {"metrics": {}}, "report": {"source": "test-double"},
    "trades": [TRADE], "equity": [{"at": VALUATION, "trading_day": "2026-01-06", "equity": "100001"}],
    "bars": [
        {"at": "2026-01-06T09:05:00+08:00", "open": "2700", "high": "2703", "low": "2698", "close": "2700"},
        {"at": "2026-01-06T09:10:00+08:00", "open": "2700", "high": "2703", "low": "2698", "close": "2702"},
        {"at": VALUATION, "open": "2700", "high": "2703", "low": "2698", "close": "2702"},
    ],
    "markers": [{"at": "2026-01-06T09:05:00+08:00", "kind": "BUILD"}],
}


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "runs.db")


@pytest.fixture
def client(store):
    app = FastAPI()
    app.include_router(router)
    app.state.backtest_store = store
    with TestClient(app) as test_client:
        yield test_client


def test_concurrent_duplicate_and_rerun(store):
    with ThreadPoolExecutor(8) as pool:
        runs = list(pool.map(lambda _: store.submit("same-request", CONFIG), range(16)))
    original = runs[0]["run_id"]
    assert {row["run_id"] for row in runs} == {original}
    with pytest.raises(BacktestError, match="BACKTEST_REQUEST_KEY_CONFLICT"):
        store.submit("same-request", {**CONFIG, "slippage_ticks": 1})
    assert store.claim()["run_id"] == original
    assert store.claim() is None
    assert store.admit(original, SNAPSHOT)
    assert store.publish(original, RESULT)
    after = store.rerun(original, "repeat-run")
    assert after["run_id"] != original and after["source_run_id"] == original
    assert store.rerun(original, "repeat-run")["run_id"] == after["run_id"]


def test_cancel_publish_and_restart_readback(store):
    first = store.submit("first", CONFIG)["run_id"]
    second = store.submit("after", CONFIG)["run_id"]
    store.claim()
    store.admit(first, SNAPSHOT)
    first_terminal = store.cancel(first)
    assert first_terminal["status"] == "CANCELING"
    assert not store.publish(first, RESULT)
    assert store.result(first) is None
    assert store.claim()["run_id"] == second
    store.admit(second, SNAPSHOT)
    assert store.publish(second, RESULT)

    reopened = RunStore(store.path)
    reopened.recover()
    assert reopened.get(first)["status"] == "CANCELED"
    assert reopened.get(second)["status"] == "SUCCEEDED"
    assert reopened.result(second)["trades"] == [TRADE]
    assert reopened.cancel(second)["status"] == "SUCCEEDED"
    assert reopened.claim() is None


def test_publication_is_all_or_nothing_and_no_redispatch_after_unknown(store, monkeypatch):
    run_id = store.submit("publish", CONFIG)["run_id"]
    store.claim()
    store.admit(run_id, SNAPSHOT)
    with pytest.raises(sqlite3.IntegrityError):
        store.publish(run_id, {**RESULT, "trades": [TRADE, TRADE]})
    assert store.get(run_id)["status"] == "RUNNING"
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM bt_rows").fetchone()[0] == 0
    real_publish = store.publish

    def commit_then_disconnect(identifier, result):
        assert real_publish(identifier, result)
        raise sqlite3.OperationalError("test unknown outcome")

    monkeypatch.setattr(store, "publish", commit_then_disconnect)
    Worker(Settings(store.path, None, None), store)._publish(run_id, RESULT)
    store.recover()
    assert store.get(run_id)["status"] == "SUCCEEDED"
    assert store.claim() is None


def test_workspace_api_keeps_template_snapshot_and_result_identity(client, store):
    assert len(client.get("/api/v1/backtests/eligibility").json()["items"]) == 6
    assert client.put("/api/v1/backtests/templates/fu", json={"name": "原", "config": CONFIG},
                      headers={"Origin": "http://127.0.0.1:5175"}).status_code == 200
    original = client.post("/api/v1/backtests/runs", json={"config": CONFIG, "request_key": "first"}).json()
    a = original["run_id"]
    assert client.put("/api/v1/backtests/templates/fu", json={
        "name": "新", "config": {**CONFIG, "initial_capital": "200000"}
    }).status_code == 200
    assert client.get(f"/api/v1/backtests/runs/{a}").json()["config"]["initial_capital"] == "100000"
    assert client.post("/api/v1/backtests/runs", json={
        "config": {**CONFIG, "rqdatac_uri": "disabled"}, "request_key": "invalid"
    }).status_code == 422
    assert client.post(f"/api/v1/backtests/runs/{a}/cancel", headers={
        "origin": "https://unrelated.example",
    }).status_code == 403
    store.claim()
    store.admit(a, SNAPSHOT)
    store.publish(a, RESULT)
    b = store.submit("second", CONFIG)["run_id"]
    store.claim()
    store.admit(b, SNAPSHOT)
    store.publish(b, {**RESULT, "trades": []})
    assert client.get("/api/v1/backtests/runs?product=FU&status=SUCCEEDED").json()["latest_success"]["run_id"] == b
    assert client.get(f"/api/v1/backtests/runs/{a}/trades?offset=0&limit=1").json()["items"] == [TRADE]
    assert client.get(f"/api/v1/backtests/runs/{a}/trades?offset=1&limit=1").json()["items"] == []
    replay = client.get(f"/api/v1/backtests/runs/{a}/replay/fill_a").json()
    assert replay["available"] and replay["revision"] == "a" * 64
    assert [marker["kind"] for marker in replay["markers"]] == ["BUILD", "ENTRY"]
    assert replay["markers"][1]["event_at"] == TRADE["entry_at"]
    assert replay["bars"][-1]["in_position"] is True
    assert client.get(f"/api/v1/backtests/runs/{b}/replay/fill_a").status_code == 404


def test_queue_limit_and_superseded_publication(store, monkeypatch):
    monkeypatch.setattr("app.backtest_center.store.QUEUE_LIMIT", 2)
    old = store.submit("old", CONFIG)["run_id"]
    new = store.submit("new", CONFIG)["run_id"]
    with pytest.raises(BacktestError, match="BACKTEST_QUEUE_FULL"):
        store.submit("over-budget", CONFIG)
    store.claim()
    store.claim()
    for run_id in (old, new):
        store.admit(run_id, SNAPSHOT)
    assert store.publish(new, RESULT)
    assert store.publish(old, RESULT)
    assert store.list(offset=0, limit=10)["latest_success"]["run_id"] == new


def test_worker_reports_missing_engine_without_market_or_alternative(store):
    run = store.submit("missing", CONFIG)
    worker = Worker(Settings(store.path, None, None), store)
    assert store.claim()["run_id"] == run["run_id"]
    with pytest.raises(BacktestError, match="PLUS_PYTHON_UNAVAILABLE"):
        worker._execute(run, -1)


def test_isolated_process_admission_is_committed_before_publication(store, monkeypatch, tmp_path):
    entry = tmp_path / "entry.py"
    entry.write_text(f"""
import hashlib, json, pathlib, sys, time
out = pathlib.Path(sys.argv[1])
req = json.loads((out / "request.json").read_text())
identity = req["identity"]
snapshot = {{**{SNAPSHOT!r}, **identity}}
(out / "admission.tmp").write_text(json.dumps(snapshot))
(out / "admission.tmp").rename(out / "admission.json")
while not (out / "admission.ok").exists():
    time.sleep(.01)
serialized = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
(out / "result.json").write_text(json.dumps({{
    "run_id": req["run_id"], "snapshot_sha256": hashlib.sha256(serialized.encode()).hexdigest(),
    "result": {RESULT!r},
}}))
""")
    monkeypatch.setattr("app.backtest_center.worker._ENTRY", entry)
    monkeypatch.setattr(Settings, "code_identity", lambda _: {"code_revision": "c" * 40, "code_sha256": "d" * 64})
    worker = Worker(Settings(store.path, Path(sys.executable), tmp_path), store)
    store.submit("process", CONFIG)
    run = store.claim()
    with (tmp_path / "worker-test.lock").open("wb") as fd:
        worker._execute(run, fd.fileno())
    saved = store.get(run["run_id"])
    assert saved["status"] == "SUCCEEDED"
    assert saved["snapshot"]["input_sha256"] == SNAPSHOT["input_sha256"]


def test_delay_parameter_is_named_and_bounded(client, store):
    from app.backtest_center.contracts import RunConfig, admission_code

    wrong_delay = client.post("/api/v1/backtests/runs", json={
        "request_key": "fractional", "config": {**CONFIG, "parameters": {"execution_delay_minutes": 1.1}},
    })
    assert wrong_delay.status_code == 422
    run = client.post("/api/v1/backtests/runs", json={
        "request_key": "delay", "config": {**CONFIG, "parameters": {"execution_delay_minutes": 2}},
    }).json()
    assert store.get(run["run_id"])["config"]["parameters"] == {"execution_delay_minutes": "2"}
    assert admission_code(RunConfig.model_validate(run["config"])) is None
    unsupported = RunConfig.model_validate({**CONFIG, "parameters": {"unreviewed_formula_parameter": 1}})
    assert admission_code(unsupported) == "STRATEGY_PARAMETERS_UNSUPPORTED"


def test_performance_filter_orders_exact_positive_returns_with_closed_trades(store):
    for index, (net, count) in enumerate((
        ("0.100000000000000000001", 1), ("0.100000000000000000002", 2),
        ("0.9", 0), ("-0.3", 3), ("0", 1),
    )):
        run_id = store.submit(f"sort-{index}", CONFIG)["run_id"]
        store.claim()
        store.admit(run_id, SNAPSHOT)
        store.publish(run_id, {**RESULT, "summary": {"metrics": {
            "net_return": {"value": net}, "trade_count": {"value": count},
        }}})
    page = store.list(offset=0, limit=10, sort="net_return")
    assert page["total"] == 2 and page["counts"]["SUCCEEDED"] == 5
    assert [row["summary"]["metrics"]["trade_count"]["value"] for row in page["items"]] == [2, 1]


def test_changed_submitted_bundle_is_fenced_before_starting_a_process(tmp_path, monkeypatch):
    settings = Settings(tmp_path / "ledger.db", Path(sys.executable), tmp_path)
    monkeypatch.setattr(Settings, "code_identity", lambda _: {"code_revision": "c" * 40, "code_sha256": "d" * 64})
    store = RunStore(settings.path, settings.submission)
    store.submit("before-updated-bundle", CONFIG)
    (tmp_path / "trading_dates.npy").touch()
    with pytest.raises(BacktestError, match="BACKTEST_SUBMITTED_DATA_CHANGED"):
        Worker(settings, store)._execute(store.claim(), -1)


def test_running_cancel_waits_for_the_isolated_process_to_exit(store, monkeypatch, tmp_path):
    from time import monotonic, sleep

    entry = tmp_path / "blocked_engine.py"
    entry.write_text("""
import pathlib, sys, time
out = pathlib.Path(sys.argv[1])
(out / "engine-started").touch()
while True:
    time.sleep(.05)
""")
    monkeypatch.setattr("app.backtest_center.worker._ENTRY", entry)
    monkeypatch.setattr(Settings, "code_identity", lambda _: {"code_revision": "c" * 40, "code_sha256": "d" * 64})
    worker = Worker(Settings(store.path, Path(sys.executable), tmp_path), store)
    identifier = store.submit("cancel-real-subprocess", CONFIG)["run_id"]
    worker.start()
    try:
        end = monotonic() + 5
        while not list(tmp_path.glob("plus-*/engine-started")) and monotonic() < end:
            sleep(.02)
        assert list(tmp_path.glob("plus-*/engine-started"))
        assert store.cancel(identifier)["status"] == "CANCELING"
        while store.get(identifier)["status"] == "CANCELING" and monotonic() < end:
            sleep(.02)
        assert store.get(identifier)["status"] == "CANCELED"
        assert not list(tmp_path.glob("plus-*/engine-started"))
        assert store.result(identifier) is None
    finally:
        worker.close()


def test_archive_events_follow_atomic_commit_and_recovery(client, store):
    original = store.submit("without-result", CONFIG)["run_id"]
    store.claim()
    store.admit(original, SNAPSHOT)
    store.phase(original, "PUBLISHING")
    store.phase(original, "PUBLISHING")
    with pytest.raises(sqlite3.IntegrityError):
        store.publish(original, {**RESULT, "trades": [TRADE, TRADE]})
    assert client.get(f"/api/v1/backtests/runs/{original}/report").status_code == 409

    reopened = RunStore(store.path)
    reopened.recover()
    events = client.get(f"/api/v1/backtests/runs/{original}/events").json()["items"]
    assert [row["phase"] for row in events] == [
        "QUEUED", "CHECKING_INPUT", "EXECUTING_PLUS", "PUBLISHING", "RECOVERY",
    ]
    assert events[-1]["status"] == "FAILED"
    assert events[-1]["diagnostic"] == "BACKTEST_INTERRUPTED_BEFORE_PUBLICATION"
    assert client.get("/api/v1/backtests/runs/absent/events").status_code == 404

    later = store.rerun(original, "second-attempt")["run_id"]
    store.claim()
    store.admit(later, SNAPSHOT)
    assert store.publish(later, RESULT)
    assert store.cancel(later)["status"] == "SUCCEEDED"
    events = client.get(f"/api/v1/backtests/runs/{later}/events").json()
    assert events["run_id"] == later
    assert [row["status"] for row in events["items"]] == ["QUEUED", "RUNNING", "RUNNING", "SUCCEEDED"]


def test_rollover_interruption_survives_restart_without_publishing_a_result(client, store):
    run_id = store.submit("expired-position", CONFIG)["run_id"]
    store.claim()
    assert store.admit(run_id, {**SNAPSHOT, "physical_contract": "FU2603"})
    evidence = {
        "status": "ROLLOVER_INTERRUPTED", "contract": "FU2603", "trading_day": "2026-01-06",
        "marked_at": VALUATION, "mark_price": "2700", "quantity": 1, "direction": "LONG",
        "entry_at": TRADE["entry_at"], "entry_price": TRADE["entry_price"], "unrealized_pnl": "-10",
    }

    with store.connection(write=True) as db:
        db.execute("""CREATE TRIGGER interrupt_insert_failure
            BEFORE INSERT ON bt_run_interruptions
            BEGIN SELECT raise(ABORT, 'test interruption rollback'); END
        """)
    with pytest.raises(sqlite3.IntegrityError, match="test interruption rollback"):
        store.finish_stopped(run_id, "ROLLOVER_INTERRUPTED", interruption=evidence)
    assert store.get(run_id)["status"] == "RUNNING"
    assert store.events(run_id)["items"][-1]["phase"] == "EXECUTING_PLUS"
    with store.connection(write=True) as db:
        db.execute("DROP TRIGGER interrupt_insert_failure")
    store.finish_stopped(run_id, "ROLLOVER_INTERRUPTED", interruption=evidence)

    reopened = RunStore(store.path)
    reopened.recover()
    assert reopened.get(run_id)["interruption"] == evidence
    detail = client.get(f"/api/v1/backtests/runs/{run_id}").json()
    assert (detail["status"], detail["diagnostic"], detail["interruption"]) == ("FAILED", evidence["status"], evidence)
    assert detail["summary"] is None
    assert detail["can_extend"] is False
    assert reopened.result(run_id) is None
    assert reopened.extension_source(run_id) is None
    assert client.get(f"/api/v1/backtests/runs/{run_id}/report").json() == {
        "detail": {"code": "BACKTEST_RESULT_UNAVAILABLE"},
    }
    assert reopened.events(run_id)["items"][-1]["diagnostic"] == evidence["status"]


@pytest.mark.parametrize(("snapshot_contract", "canceled", "diagnostic"), [
    ("FU2604", False, "ROLLOVER_INTERRUPTED"),
    (None, False, "ROLLOVER_INTERRUPTED"),
    ("FU2603", False, "PLUS_RUN_FAILED"),
    ("FU2603", True, "ROLLOVER_INTERRUPTED"),
])
def test_rollover_evidence_requires_a_matching_admitted_failed_run(store, snapshot_contract, canceled, diagnostic):
    run_id = store.submit("unbound-rollover", CONFIG)["run_id"]
    store.claim()
    if snapshot_contract:
        store.admit(run_id, {**SNAPSHOT, "physical_contract": snapshot_contract})
    if canceled:
        store.cancel(run_id)

    store.finish_stopped(run_id, diagnostic, interruption={"status": "ROLLOVER_INTERRUPTED", "contract": "FU2603"})

    run = store.get(run_id)
    assert run["status"] == ("CANCELED" if canceled else "FAILED")
    assert run["interruption"] is None
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM bt_run_interruptions").fetchone()[0] == 0


def test_partial_native_legs_and_rollover_stay_on_original_contract(client, store):
    trade = {
        **TRADE, "trade_id": "roll", "status": "ROLLOVER_INTERRUPTED", "quantity": 3,
        "mark_price": "2702", "exit_at": None, "unrealized_pnl": "2",
        "native_entry_ids": ["entry1", "entry2"], "native_exit_ids": ["exit1"],
    }
    legs = [
        ("entry1", "OPEN", 1, "2026-01-06T09:06:00+08:00"),
        ("entry2", "OPEN", 2, "2026-01-06T09:07:00+08:00"),
        ("exit1", "CLOSE_TODAY", 1, "2026-01-06T09:08:00+08:00"),
    ]
    fills = [
        {"native_trade_id": fill_id, "contract": "FU2603", "position_effect": effect, "quantity": quantity,
         "modeled_fill_at": at, "signal_id": f"signal-{fill_id}", "price": "2700"}
        for fill_id, effect, quantity, at in legs
    ]
    foreign = {**fills[2], "contract": "FU2605"}
    matching_bars = [dict(bar, contract="FU2603", input_sha256=SNAPSHOT["input_sha256"]) for bar in RESULT["bars"]]
    other_bar = {**matching_bars[-1], "contract": "FU2605", "close": "4444"}
    markers = [
        {"at": RESULT["bars"][0]["at"], "kind": "BUILD", "contract": "FU2603"},
        {"at": RESULT["bars"][0]["at"], "kind": "BUILD", "contract": "FU2605"},
    ]
    run_id = store.submit("legs", CONFIG)["run_id"]
    store.claim()
    store.admit(run_id, SNAPSHOT)
    store.publish(run_id, {**RESULT, "bars": [other_bar, *matching_bars], "markers": markers, "trades": [trade], "report": {
        "native_fills": [foreign, *fills], "attempts": [{"signal_id": f"signal-{item[0]}"} for item in legs],
    }})
    replay = client.get(f"/api/v1/backtests/runs/{run_id}/replay/roll").json()
    assert replay["available"] and replay["contract"] == "FU2603"
    assert replay["input_sha256"] == SNAPSHOT["input_sha256"]
    assert replay["native_fills"] == fills and len(replay["attempts"]) == 3
    assert all(bar["contract"] == "FU2603" for bar in replay["bars"])
    assert [item["kind"] for item in replay["markers"]] == ["BUILD", "ENTRY", "ENTRY", "EXIT", "VALUATION"]
    assert [item["quantity"] for item in replay["markers"] if item.get("native_trade_id")] == [1, 2, 1]
    assert replay["markers"][-1]["event_at"] == trade["marked_at"]
    assert replay["bars"][-1]["in_position"]


@pytest.mark.parametrize("failure", ["no-bars", "other-contract", "other-input", "bad-result-hash"])
def test_replay_refuses_unbound_chart_and_preserves_the_archived_trade(client, store, failure):
    changes = {
        "no-bars": [],
        "other-contract": [dict(bar, contract="FU2605") for bar in RESULT["bars"]],
        "other-input": [dict(bar, input_sha256="foreign") for bar in RESULT["bars"]],
        "bad-result-hash": RESULT["bars"],
    }
    run_id = store.submit(failure, CONFIG)["run_id"]
    store.claim()
    store.admit(run_id, SNAPSHOT)
    store.publish(run_id, {**RESULT, "bars": changes[failure]})
    if failure == "bad-result-hash":
        with store.connection(write=True) as db:
            db.execute("UPDATE bt_rows SET payload='{}' WHERE run_id=? AND kind='bars' AND seq=0", (run_id,))
    replay = client.get(f"/api/v1/backtests/runs/{run_id}/replay/fill_a").json()
    assert replay["trade"] == TRADE and not replay["available"] and not replay["bars"] and not replay["markers"]
    assert replay["reason"] == ("RUN_CHART_EVIDENCE_MISMATCH" if failure in ("other-input", "bad-result-hash")
                                else "RUN_CHART_WINDOW_UNAVAILABLE")


def test_single_physical_run_rejects_a_self_consistent_foreign_trade_and_chart(client, store):
    run_id = store.submit("foreign-trade", CONFIG)["run_id"]
    store.claim()
    store.admit(run_id, {**SNAPSHOT, "physical_contract": "FU2603"})
    trade = {**TRADE, "contract": "FU2605"}
    store.publish(run_id, {**RESULT, "trades": [trade], "bars": [dict(bar, contract="FU2605") for bar in RESULT["bars"]]})
    replay = client.get(f"/api/v1/backtests/runs/{run_id}/replay/fill_a").json()
    assert replay["trade"] == trade and not replay["available"]
    assert replay["reason"] == "RUN_CHART_EVIDENCE_MISMATCH"


def test_extend_route_freezes_source_scope_and_keeps_checkpoint_private(client, store):
    source = store.submit("extend-base", {**CONFIG, "end": "2026-01-06"})
    source_id = source["run_id"]
    path = f"/api/v1/backtests/runs/{source_id}"
    request = {"end": "2026-01-08", "request_key": "extend-once"}
    checkpoint = {"through": "2026-01-06", "native_state": "private-opaque-state"}

    assert client.post(f"{path}/extend", json=request).json()["detail"]["code"] == "BACKTEST_EXTENSION_SOURCE_UNAVAILABLE"
    assert store.claim()["run_id"] == source_id
    assert store.admit(source_id, SNAPSHOT)
    assert store.publish(source_id, RESULT, checkpoint=checkpoint)
    assert store.extension_source(source_id) == {
        "run": store.get(source_id), "checkpoint": checkpoint, "result": RESULT,
    }
    published = client.get(path).json()
    assert published["can_extend"] and "private-opaque-state" not in client.get(path).text
    assert "private-opaque-state" not in client.get(f"{path}/report").text

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: client.post(f"{path}/extend", json=request), range(2)))
    first, repeat = (response.json() for response in responses)
    assert all(response.status_code == 202 for response in responses)
    assert first == repeat and first["run_id"] != source_id
    assert first["source_run_id"] == source_id
    assert first["incremental"] == {"source_run_id": source_id, "through": "2026-01-06"}
    assert first["config"] == {**published["config"], "end": "2026-01-08"}
    assert not first["can_extend"] and published == client.get(path).json()
    conflict = client.post(f"{path}/extend", json={**request, "end": "2026-01-09"})
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "BACKTEST_REQUEST_KEY_CONFLICT"
    assert client.post(f"{path}/extend", json={**request, "end": "2026-01-06"}).status_code == 422
    assert client.post(f"{path}/extend", json={**request, "initial_capital": "1000"}).status_code == 422
    for invalid_end in (1767830400, "1767830400", "2026-01-08T00:00:00"):
        assert client.post(f"{path}/extend", json={**request, "end": invalid_end}).status_code == 422
    assert client.post(f"{path}/extend", json=request, headers={"origin": "https://unrelated.example"}).status_code == 403
    assert store.claim()["incremental"] == first["incremental"]
    assert store.claim() is None


def test_extension_publication_keeps_original_prefix_and_supports_chaining(store):
    from datetime import date

    base = store.submit("base-chain", {**CONFIG, "end": "2026-01-06"})["run_id"]
    store.claim()
    store.admit(base, SNAPSHOT)
    store.publish(base, RESULT, checkpoint={"through": "2026-01-06"})
    child = store.extend(base, date(2026, 1, 7), "first-extension")["run_id"]
    store.claim()
    store.admit(child, SNAPSHOT)
    equity = [*RESULT["equity"], {"at": "2026-01-07T15:30:00+08:00", "trading_day": "2026-01-07", "equity": "100002"}]
    metadata = {"source_run_id": base, "through": "2026-01-06", "appended_trading_days": ["2026-01-07"],
                "executed_minutes": 345}
    extended = {**RESULT, "equity": equity, "report": {"incremental": metadata}}
    with pytest.raises(BacktestError, match="BACKTEST_EXTENSION_RESULT_INVALID"):
        store.publish(child, {**extended, "equity": [{**equity[0], "equity": "100003"}, equity[1]]})
    with pytest.raises(BacktestError, match="BACKTEST_EXTENSION_CHECKPOINT_INVALID"):
        store.publish(child, extended, checkpoint={"through": "2026-01-06"})
    assert store.result(child) is None and store.get(child)["status"] == "RUNNING"
    assert not store.get(child)["can_extend"]
    assert store.publish(child, extended, checkpoint={"through": "2026-01-07"})
    assert store.result(base)["equity"] == RESULT["equity"]
    assert store.extension_source(child)["result"] == extended
    assert store.get(child)["incremental"] == metadata
    with pytest.raises(BacktestError, match="BACKTEST_INCREMENTAL_RERUN_UNAVAILABLE"):
        store.rerun(child, "exact-child-rerun")
    next_run = store.extend(child, date(2026, 1, 8), "second-extension")
    assert next_run["incremental"] == {"source_run_id": child, "through": "2026-01-07"}


def test_checkpoint_is_atomic_and_detects_result_or_checkpoint_drift(store):
    run_id = store.submit("checkpoint-integrity", CONFIG)["run_id"]
    store.claim()
    store.admit(run_id, SNAPSHOT)
    checkpoint = {"through": "2026-01-06", "state": "original"}
    with pytest.raises(sqlite3.IntegrityError):
        store.publish(run_id, {**RESULT, "trades": [TRADE, TRADE]}, checkpoint=checkpoint)
    reopened = RunStore(store.path)
    assert reopened.get(run_id)["status"] == "RUNNING"
    assert reopened.extension_source(run_id) is None
    with reopened.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM bt_run_checkpoints").fetchone()[0] == 0
    assert reopened.publish(run_id, RESULT, checkpoint=checkpoint)
    assert reopened.extension_source(run_id)["checkpoint"] == checkpoint
    with reopened.connection(write=True) as db:
        db.execute("UPDATE bt_rows SET payload=? WHERE run_id=? AND kind='bars' AND seq=0",
                   ('{"at":"mutated"}', run_id))
    assert reopened.extension_source(run_id) is None
    with reopened.connection(write=True) as db:
        db.execute("UPDATE bt_run_checkpoints SET checkpoint=? WHERE run_id=?",
                   ('{"through":"2026-01-06","state":"foreign"}', run_id))
    assert reopened.extension_source(run_id) is None
    assert not reopened.get(run_id)["can_extend"]


def test_non_historical_and_legacy_runs_cannot_supply_extension_sources(store):
    from datetime import date

    training = store.submit("training", {**CONFIG, "sample_type": "train"})["run_id"]
    store.claim()
    store.admit(training, SNAPSHOT)
    with pytest.raises(BacktestError, match="BACKTEST_EXTENSION_CHECKPOINT_INVALID"):
        store.publish(training, RESULT, checkpoint={"through": "2026-01-06"})
    assert store.publish(training, RESULT)
    historical = store.submit("legacy", CONFIG)["run_id"]
    store.claim()
    store.admit(historical, SNAPSHOT)
    assert store.publish(historical, RESULT)
    for run_id in (training, historical):
        assert not store.get(run_id)["can_extend"] and store.extension_source(run_id) is None
        with pytest.raises(BacktestError, match="BACKTEST_EXTENSION_SOURCE_UNAVAILABLE"):
            store.extend(run_id, date(2026, 1, 9), "requires-checkpoint")
