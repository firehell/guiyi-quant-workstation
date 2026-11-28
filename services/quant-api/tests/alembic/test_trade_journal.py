from concurrent.futures import ThreadPoolExecutor
from datetime import date
import importlib.util
from pathlib import Path
from threading import Barrier
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api import trade_journal
from app.db.session import get_db

BASE = "/api/v1/trade-journal"
DAY = "2026-11-30"
API_ROOT = Path(__file__).resolve().parents[2]


def _migration():
    path = API_ROOT / "alembic/versions/20261128_0057_trade_journal.py"
    spec = importlib.util.spec_from_file_location("journal_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def owner(isolated_postgres_engine):
    engine = isolated_postgres_engine
    schema = "journal_test_" + uuid4().hex
    migration = _migration()
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        conn.exec_driver_sql("CREATE TABLE existing_facts (id integer PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO existing_facts VALUES (42)")
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
    try:
        yield engine, schema
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.fixture
def client(owner):
    engine, schema = owner
    app = FastAPI()
    app.include_router(trade_journal.router)

    def session():
        # Every request owns a separate database session and transaction.
        with engine.connect() as conn:
            conn.exec_driver_sql(f'SET search_path TO "{schema}"')
            conn.commit()
            try:
                with Session(conn) as db:
                    yield db
            finally:
                conn.exec_driver_sql("RESET search_path")
                conn.commit()

    app.dependency_overrides[get_db] = session
    with TestClient(app) as connection:
        yield connection


def put(client, path, body, key=None, **headers):
    return client.put(BASE + path, json=body, headers={"Idempotency-Key": str(key or uuid4()), **headers})


def create(client, *, id=None, **fields):
    id = id or str(uuid4())
    case = {"title": "破位后等待回抽", "trading_day": DAY, "contract": "RB2701", "product": "RB", "direction": "LONG"}
    assert put(client, f"/cases/{id}/create", case | fields).status_code == 200
    return id


def case(client, id):
    response = client.get(BASE + f"/cases/{id}")
    assert response.status_code == 200, response.json()
    return response.json()


def link(client, case_id, native_id, scope="demo", source="SIMNOW", **fields):
    return put(client, f"/cases/{case_id}/links/{uuid4()}",
               {"source": source, "scope": scope, "native_id": native_id, "trading_day": DAY} | fields)


@pytest.mark.isolated_postgresql
def test_migration_is_additive_and_only_empty_journal_can_downgrade(owner):
    engine, schema = owner
    migration = _migration()
    assert migration.down_revision == "20261124_0056"
    assert "trade_journal_fill_assignment" in {
        index["name"] for index in inspect(engine).get_indexes("trade_journal_events", schema=schema)
    }
    with engine.begin() as conn:
        conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        migration.op = Operations(MigrationContext.configure(conn))
        migration.downgrade()
        assert conn.scalar(text("SELECT id FROM existing_facts")) == 42
        migration.upgrade()
        conn.execute(text("INSERT INTO trade_journal_mutations (id,fingerprint) VALUES (:id,'used')"), {"id": uuid4()})
        with pytest.raises(DBAPIError, match="TRADE_JOURNAL_NOT_EMPTY"), conn.begin_nested():
            migration.downgrade()


@pytest.mark.isolated_postgresql
def test_plan_version_snapshot_night_note_review_summary_and_retry(client):
    plan = str(uuid4())
    initial = {"expected_version": 0, "trading_day": DAY, "product": "RB", "title": "等到回抽",
               "direction": "LONG", "entry": "等待回抽到区间上沿"}
    key = uuid4()
    saved = put(client, f"/plans/{plan}", initial, key)
    assert saved.status_code == 200 and saved.json()["component_version"] == "0.1.0"
    id = create(client, plan_id=plan, plan_version=1)
    revision = initial | {"expected_version": 1, "entry": "次日版本"}
    assert put(client, f"/plans/{plan}", revision).json()["version"] == 2
    assert put(client, f"/plans/{plan}", initial, key).json() == saved.json()
    assert put(client, f"/plans/{plan}", revision, key).json()["detail"]["code"] == "JOURNAL_REQUEST_CONFLICT"
    assert put(client, f"/plans/{plan}", revision).status_code == 409
    assert case(client, id)["plan"]["content"]["entry"] == initial["entry"]

    note = {"kind": "OPEN", "trading_day": DAY, "occurred_at": "2026-11-27T21:30:00+08:00",
            "price": "3000.0200", "quantity": 2, "note": "手工补记"}
    event_id = uuid4()
    put_response = put(client, f"/cases/{id}/events/{event_id}", note)
    assert put_response.status_code == 200, put_response.json()
    row = case(client, id)["timeline"][0]
    assert row["trading_day"] == DAY and row["occurred_at"].startswith("2026-11-27T13:30")
    assert row["manual"]["price"] == "3000.0200" and row["recorded_at"] != row["occurred_at"]

    review = {"expected_version": 1, "title": "案例", "closed": True,
              "review": {"dimensions": {"entry": {"rating": "MISSED", "tags": ["提前入场"], "note": "没等回抽"}},
                         "next_action": "等回抽之后再开"}}
    assert put(client, f"/cases/{id}", review, Origin="https://outside.invalid").status_code == 403
    assert put(client, f"/cases/{id}", review, Origin="http://outside.invalid", Host="outside.invalid").status_code == 403
    assert put(client, f"/cases/{id}", review).status_code == 200
    assert put(client, f"/cases/{id}", review).status_code == 409
    filtered = client.get(BASE, params={"period": "week", "anchor": DAY, "tag": "提前入场", "product": "RB"})
    assert filtered.status_code == 200, filtered.json()
    assert [row["id"] for row in filtered.json()["cases"]] == [id]

    summary = {"expected_version": 0, "missed": "没有等到完整回抽", "case_ids": [id]}
    assert put(client, f"/summaries/week/{DAY}", summary).status_code == 200
    assert put(client, "/summaries/day/2026-12-01", summary | {"case_ids": []}).status_code == 200
    assert put(client, "/summaries/day/2026-12-01", summary | {"expected_version": 1}).status_code == 409
    assert client.get(BASE, params={"anchor": "2026-12-01"}).json()["summary"]["content"]["missed"] == summary["missed"]


@pytest.mark.isolated_postgresql
def test_concurrent_claim_correction_and_source_failure(client, monkeypatch):
    first, second = create(client), create(client)
    gate = Barrier(2)
    rows = [
        {"native_id": "shared", "contract": "RB2701", "direction": "LONG", "occurred_at": "2026-11-27T21:01:00+08:00", "action": "OPEN"},
        {"native_id": "short", "contract": "RB2701", "direction": "SHORT", "occurred_at": "2026-11-27T21:02:00+08:00", "action": "OPEN"},
        {"native_id": "other", "contract": "JM2701", "direction": "LONG", "occurred_at": "2026-11-27T21:02:00+08:00", "action": "OPEN"},
        {"native_id": "same", "contract": "RB2701", "direction": "LONG", "occurred_at": "2026-11-27T21:03:00+08:00", "action": "CLOSE"},
    ]

    def resolve(_request, key, _contract):
        if key.native_id == "shared" and gate is not None:
            gate.wait(timeout=5)
        return next(row for row in rows if row["native_id"] == key.native_id)

    def read(_request, source, day, scope, **options):
        return {"status": "UNAVAILABLE", "scope": scope, "items": [], "has_more": False}

    monkeypatch.setattr(trade_journal, "resolve", resolve)
    monkeypatch.setattr(trade_journal, "read_evidence", read)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda case_id: link(client, case_id, "shared"), [first, second]))
    gate = None
    assert sorted(row.status_code for row in results) == [200, 409]
    winner, next_case = (first, second) if results[0].status_code == 200 else (second, first)
    detail = case(client, winner)
    fill = detail["timeline"][0]
    assert fill["evidence_status"] == "UNAVAILABLE"
    assert link(client, winner, "short").json()["detail"]["code"] == "JOURNAL_FILL_SCOPE_CONFLICT"
    assert link(client, winner, "other").json()["detail"]["code"] == "JOURNAL_FILL_SCOPE_CONFLICT"
    assert link(client, winner, "same", scope="different").json()["detail"]["code"] == "JOURNAL_FILL_ACCOUNT_CONFLICT"
    assert link(client, winner, "same", source="SUBING_PAPER").status_code == 409
    assert link(client, winner, "same", source="RQALPHA_BACKTEST").status_code == 200
    assert put(client, f"/cases/{winner}/events/{fill['id']}/removal", {"reason": "误关联"}).status_code == 200
    assert case(client, winner)["timeline"][0]["removal_reason"] == "误关联"
    assert link(client, next_case, "shared").status_code == 200


def test_source_status_without_account_setup(monkeypatch):
    monkeypatch.delenv("GUIYI_SIMULATION_READER_DSN", raising=False)
    app = FastAPI()
    app.include_router(trade_journal.router)
    with TestClient(app) as client:
        result = client.get(BASE + "/evidence", params={"source": "SIMNOW", "trading_day": DAY})
    assert result.json()["status"] == "NOT_CONFIGURED"


def test_backtest_owned_read_uses_native_trading_day_and_keeps_immutable_records(tmp_path):
    from app.backtest_center.store import RunStore, read_published_runs, read_published_trades
    import json

    path = tmp_path / "test.sqlite"
    store = RunStore(path)
    with store.connection(write=True) as db:
        db.execute("""
            INSERT INTO bt_runs (run_id, request_key, request_digest, created_at, updated_at, status, phase, config, report)
            VALUES ('run-x', 'req-x', 'digest', '2026-11-30', '2026-11-30', 'SUCCEEDED', 'done',
            '{"contract":"RB2701","strategy_id":"example","start":"2026-11-30","end":"2026-12-01"}', ?)
        """, (json.dumps({"native_fills": [{"native_trade_id": "fill-x", "trading_day": DAY}]}),))
        db.execute("INSERT INTO bt_rows VALUES ('run-x','trades',1,'fill-x',?)",
                   (json.dumps({"trade_id": "fill-x", "entry_at": "2026-11-27T21:00:00+08:00"}),))
    before = path.read_bytes()
    assert read_published_trades(path, "run-x", date.fromisoformat(DAY), "fill-x")[0]["trade_id"] == "fill-x"
    assert read_published_trades(path, "run-x", date(2026, 11, 27), "fill-x") == []
    assert read_published_runs(path, date.fromisoformat(DAY), "RB2701") == [("run-x", "example")]
    assert read_published_runs(path, date.fromisoformat(DAY), "RB2702") == []
    assert path.read_bytes() == before


@pytest.mark.isolated_postgresql
def test_linking_manual_close_requires_close_evidence_and_counts_activity_day(client, monkeypatch):
    id = create(client)
    operation = uuid4()
    next_day = "2026-12-01"
    manual = {"kind": "CLOSE", "trading_day": next_day, "occurred_at": "2026-11-30T21:12:00+08:00",
              "note": "减仓后平仓"}
    assert put(client, f"/cases/{id}/events/{operation}", manual).status_code == 200

    def resolve(_request, key, _contract):
        return {"contract": "RB2701", "direction": "LONG", "occurred_at": manual["occurred_at"],
                "action": key.native_id}

    monkeypatch.setattr(trade_journal, "resolve", resolve)
    assert link(client, id, "OPEN", trading_day=next_day, replaces_manual=str(operation)).status_code == 409
    assert link(client, id, "CLOSE", trading_day=next_day, replaces_manual=str(operation)).status_code == 200
    filtered = client.get(BASE, params={"anchor": next_day})
    assert [row["id"] for row in filtered.json()["cases"]] == [id]
    assert put(client, f"/summaries/day/{next_day}", {"expected_version": 0, "case_ids": [id]}).status_code == 200


def test_corrupt_evidence_returns_source_status(monkeypatch):
    from app.trade_journal import sources

    monkeypatch.setenv("GUIYI_SIMULATION_READER_DSN", "unreachable://source")
    malformed = {"id": "bad", "contract": "RB2701", "occurred_at": "2026-11-27T21:01:00+08:00",
                 "direction": "LONG", "offset": "OPEN", "quantity": 1, "price": "bad"}
    monkeypatch.setattr(sources, "read_committed_fills", lambda *_: (["demo"], True, [malformed]))
    app = FastAPI()
    app.include_router(trade_journal.router)
    with TestClient(app) as client:
        params = {"source": "SIMNOW", "trading_day": DAY, "scope": "demo"}
        assert client.get(BASE + "/evidence", params=params).json()["status"] == "UNAVAILABLE"
        malformed.pop("price")
        assert client.get(BASE + "/evidence", params=params).json()["status"] == "UNAVAILABLE"
        malformed.update(price="3100", contract=None)
        assert client.get(BASE + "/evidence", params=params).json()["status"] == "UNAVAILABLE"


def test_retired_tq_archive_reuses_verified_close_today(monkeypatch, tmp_path):
    from datetime import datetime
    from decimal import Decimal
    import json
    import sqlite3
    from types import SimpleNamespace

    from guiyi_quant.tq_simulation.journal import digest
    from app.trade_journal import sources

    account = "a" * 64
    filled_at = datetime.fromisoformat("2026-11-27T13:10:00+00:00")
    # Compute the timestamp from the exact recorded instant.
    ts_ns = int(filled_at.timestamp()) * 1_000_000_000
    trade = {"trade_id": "native-fill", "order_id": "native-order", "exchange_id": "SHFE", "instrument_id": "rb2701",
             "trade_date_time": ts_ns, "direction": "SELL", "offset": "CLOSETODAY", "price": "3110"}
    payload = {"account_id": account, "trading_day": "20261130", "trades": [trade]}
    snapshot_id = digest(payload)
    snapshot = payload | {"snapshot_id": snapshot_id, "observed_at": "2026-11-27T13:12:00+00:00"}
    archive = tmp_path.resolve()
    for file_name in ("account.sqlite", "dispatch.sqlite"):
        path = archive / file_name
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE identity(account,profile)")
            db.execute("INSERT INTO identity VALUES (?, 'TQKQ:htdy_tqkq_v1')", (account,))
            db.execute("CREATE TABLE events(kind,payload)")
            db.execute("INSERT INTO events VALUES ('snapshot',?)", (json.dumps(snapshot),))
        path.chmod(0o600)
    state = SimpleNamespace(account_id=account, unresolved_fill_ids=(), orders=[
        SimpleNamespace(order_id="order", side="SELL", offset="CLOSE")], fills=[
        sources.TqKqFill("fill", "order", account, "RB2701", filled_at, filled_at, Decimal("3110"), None, 1,
                         "native-fill", "native-order", snapshot_id),
    ])
    monkeypatch.setattr(sources.LocalStore, "inspect_tip", lambda _path: state)
    monkeypatch.setenv("GUIYI_TRADE_JOURNAL_TQKQ_ARCHIVE", str(archive))
    before = (archive / "dispatch.sqlite").read_bytes()
    result = sources.read_evidence(None, "TQKQ_HISTORY", date.fromisoformat(DAY), account, native_id="fill")
    assert result["status"] == "AVAILABLE"
    assert (result["items"][0]["action"], result["items"][0]["direction"]) == ("CLOSETODAY", "LONG")
    assert (archive / "dispatch.sqlite").read_bytes() == before


@pytest.mark.isolated_postgresql
def test_subing_source_reads_exact_retained_paper_run(owner, monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy import create_engine
    from app.api import subing_portfolio
    from app.subing_model.store import runs
    from guiyi_quant.subing_one_lot import EXPANDED_PORTFOLIO_PRODUCTS, portfolio_policy

    engine, schema = owner
    policy = portfolio_policy(EXPANDED_PORTFOLIO_PRODUCTS)
    kind = subing_portfolio.KIND
    fill = {"fill_id": "exact-fill", "trading_day": DAY, "contract": "RB2701"}
    with engine.begin() as conn:
        conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        runs.create(conn)
        conn.execute(runs.insert().values(
            run_id="paper-run", sequence=12, identity={"kind": kind, "policy": policy}, tail_hash="a" * 64,
            state={"kind": kind, "sequence": 12, "result": {"policy": policy, "daily": {DAY: {}},
                   "accounts": {"RB2701": {"fills": [fill]}}}},
        ))

    def readonly_store(_):
        return SimpleNamespace(engine=create_engine(engine.url, connect_args={"options": f"-c search_path={schema}"}))

    monkeypatch.setattr(subing_portfolio, "ModelStore", readonly_store)
    monkeypatch.setattr(subing_portfolio, "read_private_settings_content", lambda _: b"fixture")
    monkeypatch.setattr(subing_portfolio, "read_registration", lambda _: pytest.fail("Exact Run should not read active pointer"))
    assert subing_portfolio.read_committed_fills(date.fromisoformat(DAY), "RB2701", "paper-run", "exact-fill") == (
        "paper-run", True, [fill],
    )
    assert subing_portfolio.read_committed_fills(date.fromisoformat(DAY), "JM2701", "paper-run", None) == (
        "paper-run", True, [],
    )


def _observation_png(color):
    import struct
    import zlib

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00" + color)) + chunk(b"IEND", b""))


def _observation():
    import base64

    stamp = "2026-11-30T01:31:00Z"
    pane = {
        "id": "main", "frequency": "1m", "series_kind": "actual_dominant", "physical_contract": "RB2701",
        "source": {"kind": "historical", "dataset_revision": "fixture-A", "completed_at": stamp},
        "window": {"from": stamp, "to": stamp}, "ranges": {"logical": [0, 8]},
        "indicators": [{"id": "MA", "version": "1", "cutoff": stamp, "source": {"kind": "frontend"},
                        "parameters": {"period": 5}}],
        "drawings": [{"kind": "line", "points": [[stamp, "3000"]]}],
    }
    return {
        "note": "观察回抽", "trading_day": DAY,
        "image": base64.b64encode(_observation_png(b"\x01\x02\x03\xff")).decode(),
        "snapshot": {"schema_version": 1, "captured_at": stamp, "product": "RB", "physical_contract": "RB2701",
                     "active_pane": "main", "layout": "two", "panes": [pane, pane | {"id": "higher", "frequency": "1d"}]},
    }


def test_observation_input_requires_complete_original_and_coherent_panes():
    import base64
    import json

    from app.trade_journal.observations import decode_capture
    from app.trade_journal.store import JournalError

    data = _observation()
    capture, png = decode_capture(json.dumps(data).encode())
    assert capture.snapshot.panes[1].frequency == "1d" and png == base64.b64decode(data["image"])
    for invalid in [
        data | {"image": base64.b64encode(png[:-12]).decode()},
        data | {"image": base64.b64encode(png + b"trailing").decode()},
        data | {"note": "   "}, data | {"snapshot": data["snapshot"] | {"physical_contract": "RB2702"}},
        data | {"snapshot": data["snapshot"] | {"panes": [data["snapshot"]["panes"][0]] * 2}},
        data | {"snapshot": data["snapshot"] | {"product": "CU"}},
        data | {"direction": "LONG"},
    ]:
        with pytest.raises(JournalError, match="JOURNAL_OBSERVATION_INVALID"):
            decode_capture(json.dumps(invalid).encode())


@pytest.mark.isolated_postgresql
def test_independent_chart_capture_image_atomicity_retry_and_review(client, owner):
    import base64

    from app.trade_journal.observations import BODY_LIMIT

    engine, schema = owner
    path = API_ROOT / "alembic/versions/20261128_0059_trade_journal_observations.py"
    spec = importlib.util.spec_from_file_location("chart_observation_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as conn:
        conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            migration.downgrade()
            migration.upgrade()

    data = _observation()
    observation_id, key = uuid4(), uuid4()
    route = f"/observations/{observation_id}"
    assert put(client, route, data, key, Origin="https://outside.invalid").status_code == 403
    assert put(client, route, data, key, **{"content-length": str(BODY_LIMIT + 1)}).status_code == 413
    assert put(client, route, data | {"image": "bad_image"}, key).status_code == 422
    assert client.get(BASE + route).status_code == 404
    assert client.get(BASE + route + "/image").status_code == 404

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: put(client, route, data, key), range(2)))
    assert all(response.status_code == 200 for response in responses)
    assert responses[0].json() == responses[1].json()
    assert responses[0].json()["id"] == str(observation_id)

    other_png = base64.b64encode(_observation_png(b"\x04\x05\x06\xff")).decode()
    assert put(client, route, data | {"image": other_png}, key).status_code == 409
    assert put(client, route, data | {"note": "changed"}, key).status_code == 409
    assert put(client, route, data).status_code == 409
    detail = client.get(BASE + route).json()["observation"]
    assert detail["snapshot"] == data["snapshot"] and detail["note"] == data["note"]
    assert "image" not in detail
    original = client.get(BASE + route + "/image")
    assert original.content == base64.b64decode(data["image"])
    assert original.headers["content-type"] == "image/png"
    assert original.headers["x-content-type-options"] == "nosniff"
    for period in ("day", "week"):
        rows = client.get(BASE + "/observations", params={"anchor": DAY, "period": period}).json()["items"]
        assert [(r["id"], r["physical_contract"], r["frequency"]) for r in rows] == [(str(observation_id), "RB2701", "1m")]
        assert "snapshot" not in rows[0] and "image" not in rows[0]
    assert client.get(BASE + "/observations", params={"anchor": "2026-12-01"}).json()["items"] == []
    with engine.begin() as conn:
        conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        assert conn.scalar(text("SELECT count(*) FROM trade_journal_cases")) == 0
        assert conn.scalar(text("SELECT count(*) FROM trade_journal_mutations")) == 1
        with Operations.context(MigrationContext.configure(conn)), pytest.raises(DBAPIError, match="NOT_EMPTY"), conn.begin_nested():
            migration.downgrade()


@pytest.mark.isolated_postgresql
def test_chart_observation_link_existing_plan_version_and_same_contract_case(client, owner):
    engine, schema = owner
    with engine.begin() as conn:
        conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        with Operations.context(MigrationContext.configure(conn)):
            for name in ("20261128_0059_trade_journal_observations", "20261128_0060_trade_journal_observation_links"):
                spec = importlib.util.spec_from_file_location(name, API_ROOT / f"alembic/versions/{name}.py")
                migration = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(migration)
                migration.upgrade()
            migration.downgrade()
            migration.upgrade()

    note_id = str(uuid4())
    path = f"/observations/{note_id}"
    frozen = _observation()
    assert put(client, path, frozen).status_code == 200
    original = client.get(BASE+path).json()
    case_id, wrong_case = create(client), create(client, contract="RB2705")
    plan_id, other_id = str(uuid4()), str(uuid4())
    plan = {"title": "周五收盘计划", "expected_version": 0, "trading_day": "2026-11-27", "product": "RB",
            "entry": "等待回抽", "direction": "WATCH"}
    assert put(client, f"/plans/{plan_id}", plan).status_code == 200
    assert put(client, f"/plans/{plan_id}", plan | {"expected_version":1, "entry":"追踪修订"}).status_code == 200
    assert put(client, f"/plans/{other_id}", plan | {"product": "CU"}).status_code == 200
    plans = client.get(BASE+path+"/link-candidates", params={"kind":"plan","q":"收盘"}).json()["items"]
    assert [(p["target_id"],p["version"]) for p in plans] == [(plan_id,2),(plan_id,1)]
    cases = client.get(BASE+path+"/link-candidates", params={"kind":"case"}).json()["items"]
    assert [c["target_id"] for c in cases] == [case_id]
    link_path = path+"/links"
    plan_link = {"kind":"plan","target_id":plan_id,"version":1}
    case_link = {"kind":"case","target_id":case_id}
    assert put(client,link_path,plan_link | {"target_id":other_id}).status_code == 409
    assert put(client,link_path,case_link | {"target_id":wrong_case}).status_code == 409
    assert put(client,link_path,plan_link | {"version":3}).status_code == 404
    assert put(client,link_path,case_link | {"target_id":str(uuid4())}).status_code == 404
    assert put(client,link_path,case_link | {"version":1}).status_code == 422
    assert put(client,link_path,plan_link,Origin="https://outside.invalid").status_code == 403
    key=uuid4()
    for repeated in (key,key,uuid4()):
        assert put(client,link_path,plan_link,repeated).status_code == 200
    assert put(client,link_path,case_link,key).status_code == 409
    assert put(client,link_path,case_link).status_code == 200
    targets=client.get(BASE+link_path).json()["items"]
    assert len(targets)==2 and next(t for t in targets if t["kind"]=="plan")["plan"]["entry"]=="等待回抽"
    for target in (plan_link,case_link):
        assert [n["id"] for n in client.get(BASE+"/observation-links",params=target).json()["items"]]==[note_id]
    assert not client.get(BASE+"/observation-links",params=plan_link | {"version":2}).json()["items"]
    assert client.get(BASE+path).json()==original
    with engine.begin() as conn:
        conn.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        assert conn.scalar(text("SELECT count(*) FROM trade_journal_events")) == 0
        with Operations.context(MigrationContext.configure(conn)), pytest.raises(DBAPIError, match="LINKS_NOT_EMPTY"), conn.begin_nested():
            migration.downgrade()
