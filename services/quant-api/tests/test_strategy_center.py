from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from types import SimpleNamespace
import asyncio

from fastapi.testclient import TestClient
import pytest

from app.api import strategy_center as api
from app.main import app
from app.services.strategy_center import htdy, newow, subing
from app.services.strategy_center.catalog import CATALOG
from app.services.strategy_center.reads import DomainReads, projection


PREFIX = "/api/v1/strategies"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "_reads", DomainReads(timeout=0.25))
    with TestClient(app) as test_client:
        yield test_client


def test_active_directory_uses_existing_public_entrypoints(client):
    result = client.get(PREFIX).json()
    assert result["version"] == "0.1.0"
    assert [row["strategy_id"] for row in result["items"]] == [
        "newow_trend", "newow_oscillation", "newow_main_rise", "newow_dual_fusion",
        "htdy_60m", "subing_portfolio_16",
    ]
    assert result["items"][3]["kind"] == "COMPOSITE"
    assert result["items"][3]["dependencies"] == ["newow_trend", "newow_oscillation"]
    assert client.get(f"{PREFIX}/not-active").status_code == 404
    assert client.post(f"{PREFIX}/newow_trend").status_code == 405

    original = client.get(f"{PREFIX}/htdy_60m").json()
    assert original["capability"] == {"60m": None}
    assert set(original["allowed_uses"]) == {
        "retrospective_repainting_observation", "domain_authorized_tqkq_simulation",
    }
    assert len({ref["value"] for ref in original["references"]}) == 5
    paper = client.get(f"{PREFIX}/subing_portfolio_16").json()
    assert len(paper["policy"]["products"]) == 16
    assert paper["policy"]["initial_cash"] == "1000000"
    assert paper["policy"]["max_lots"] == 1
    assert client.get(f"{PREFIX}/htdy_60m/evidence?product=jm&frequency=60m").status_code == 422
    assert client.get(f"{PREFIX}/newow_trend/bindings?product=jm").status_code == 422
    assert client.get(f"{PREFIX}/newow_trend/bindings?product=rs&frequency=60m").json()["status"] == "UNSUPPORTED"


def test_formal_runtime_keeps_receipt_and_heartbeat_identities(monkeypatch):
    from app import runtime_bindings, runtime_deployment, runtime_handover

    now = datetime.now(UTC)
    monkeypatch.setattr(runtime_bindings, "resolve_service_binding",
                        lambda _: SimpleNamespace(enabled=True, generation=96, tag="v1.16.152", commit="a" * 40))
    state = dict(generation=96, phase="active", at=now.isoformat(), ready=True,
                 proof={"reference_receipts": "waiting_archive", "canonical_compute": "pending"})
    monkeypatch.setattr(runtime_handover, "read_service_state", lambda _: state)
    monkeypatch.setattr(runtime_deployment, "owner_process_matches", lambda *_: True)
    adapter = newow.Newow(lambda: None, receipt_only=True, formal=True)
    read = adapter.runtime()
    assert read["status"] == "WAITING"
    assert read["domain_status"] == "waiting_archive"
    assert read["worker_status"] == "ready"
    assert read["heartbeat_at"] == now.isoformat()
    assert read["generation"] == 96
    assert read["diagnostics"]["canonical_compute"] == "pending"
    state["proof"] = {"reference_receipts": "current"}
    state["ready"] = False
    assert adapter.runtime()["status"] == "BLOCKED"
    state["ready"] = True
    monkeypatch.setattr(newow, "formal_archive_root", lambda: None)
    monkeypatch.setattr(newow, "current_retained_receipt", lambda *_, **__: None)
    assert adapter.runtime()["status"] == "UNVERIFIED"
    state["at"] = (now - timedelta(seconds=61)).isoformat()
    state["proof"] = {"reference_receipts": "current"}
    read = adapter.runtime()
    assert read["status"] == "STALE"
    assert read["domain_status"] == "current"
    assert read["source_as_of"] == state["at"]


def test_formal_evidence_fallback_keeps_history_and_current_result_distinct(monkeypatch):
    cutoff = datetime(2026, 11, 27, 7, tzinfo=UTC)
    result = dict(stream_id="original", revision_id="revision", seq=25, through="2026-11-27",
                  cutoff=cutoff, computed_at=cutoff)
    monkeypatch.setattr(newow, "latest_formal_reference", lambda *args, **kw: None)
    monkeypatch.setattr(newow, "latest_reference", lambda *args, **kw: result)
    hint = {"hint_id": "hint-original", "quantity_effect": "none"}
    monkeypatch.setattr(newow, "present_saved_chart", lambda *args, **kw: {
        "main_status": "saved", "frames": [{"actions": [{"signal_id": "signal-original"}], "hints": [hint]}],
    })
    adapter = newow.Newow(lambda: None, receipt_only=True, formal=True)
    adapter.reader = SimpleNamespace(
        trades=lambda *args, **kw: dict(items=[{"reference_trade_id": "reference-original"}],
                                        revision_id="revision", seq=25, snapshot="frozen", next_cursor=None),
    )
    read = adapter.evidence(CATALOG["newow_dual_fusion"], "jm", "60m")
    assert read["status"] == "HISTORICAL_RESULT"
    assert read["current_publication"] == "NOT_PUBLISHED"
    assert read["result"] == result
    assert read["hints"] == [hint]
    assert read["reference_trades"] == [{"reference_trade_id": "reference-original"}]
    assert read["dependencies"] == ("newow_trend", "newow_oscillation")
    monkeypatch.setattr(newow, "latest_formal_reference", lambda *args, **kw: {**result, "receipt": "hash"})
    read = adapter.evidence(CATALOG["newow_dual_fusion"], "jm", "60m")
    assert read["status"] == "PUBLISHED"
    assert read["result"]["receipt"] == "hash"

    def old_scope(*args, **kwargs):
        raise ValueError("MARKET_ARCHIVE_RECEIPT_SCOPE_INVALID")

    monkeypatch.setattr(newow, "latest_formal_reference", old_scope)
    read = adapter.evidence(CATALOG["newow_dual_fusion"], "jm", "60m")
    assert read["status"] == "HISTORICAL_RESULT"
    assert read["current_publication"] == "UNAVAILABLE"
    assert read["current_diagnostic"] == "MARKET_REFERENCE_CURRENT_UNAVAILABLE"
    assert read["result"] == result


def test_runtime_fanout_times_out_one_owner_and_prioritizes_the_directory(client, monkeypatch):
    stalled = Event()
    entered = Event()
    other_reads = Barrier(2)

    def stall(self):
        entered.set()
        assert stalled.wait(timeout=4)
        return projection(newow.RUNTIME, "AVAILABLE")

    def read_other():
        other_reads.wait(timeout=1)
        return projection("verified source", "AVAILABLE")

    monkeypatch.setattr(newow.Newow, "runtime", stall)
    monkeypatch.setattr(htdy, "runtime", read_other)
    monkeypatch.setattr(subing, "runtime", read_other)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(client.get, f"{PREFIX}/runtime")
        try:
            assert entered.wait(timeout=2)
            assert len(client.get(PREFIX).json()["items"]) == 6
            assert "60m" in client.get(f"{PREFIX}/newow_trend").json()["capability"]
            value = first.result(timeout=2).json()["domains"]
            assert value["newow"]["diagnostic"] == "SOURCE_TIMEOUT"
            assert [value[domain]["status"] for domain in ("htdy", "subing")] == ["AVAILABLE", "AVAILABLE"]
            assert client.get(f"{PREFIX}/newow_trend/runtime").json()["diagnostic"] == "SOURCE_BUSY"
        finally:
            stalled.set()


def test_cancelled_client_does_not_admit_duplicate_source_work():
    stalled = Event()
    entered = Event()

    def stall():
        entered.set()
        assert stalled.wait(timeout=3)
        return projection("source", "AVAILABLE")

    async def exercise():
        reader = DomainReads()
        pending = asyncio.create_task(reader.run("newow", "source", stall))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert (await reader.run("newow", "source", stall))["diagnostic"] == "SOURCE_BUSY"
        finally:
            stalled.set()

    asyncio.run(exercise())


def test_paper_stale_heartbeat_preserves_one_run_and_journal(monkeypatch):
    ts = datetime.now(UTC) - timedelta(minutes=1)
    monkeypatch.setattr(subing, "read_status", lambda **_: dict(
        status="STALE_OR_STOPPED", worker_status="RUNNING", worker_at=ts, run_id="shared-run",
        sequence=250, observed_at=ts.isoformat(), auto_order=False,
    ))
    value = subing.runtime()
    assert value["status"] == "STALE"
    assert value["domain_status"] == "STALE_OR_STOPPED"
    assert value["heartbeat_status"] == "RUNNING"
    assert value["source_as_of"] == ts
    assert value["run_id"] == "shared-run"
    assert value["sequence"] == 250
    assert value["authorization"]["auto_order"] is False


def test_newow_evidence_uses_committed_presentation_and_owner_identity(tmp_path, monkeypatch):
    from app.reference_trading.presentation import envelope, presentation_point
    from tests.reference_trading import test_repository as fixtures

    identity = newow.canonical_newow_history_identity("rb", "trend", "1d")
    monkeypatch.setattr(fixtures, "_stream", lambda: identity)
    day = fixtures.AT.date()
    repository, factory, stream, revision, manifest, seed = fixtures._seed_repository(
        sqlite_path=tmp_path / "center.sqlite",
        dependency_manifest={"query_since": day.isoformat(), "query_through": day.isoformat()},
    )

    def point(point_kind, **value):
        return presentation_point(
            kind=point_kind, trading_day=day, formula_versions=stream.formula_versions,
            value={"bar_end": fixtures.AT, **value},
        )

    frame = point("indicator", version="newow_bar_state_v1", physical_contract="RB2610",
                  source_bar_sha256="b" * 64, main_values={}, action_ids=["build-1"], hint_ids=["hint-1"])
    action = point("action", signal_id="build-1", kind="BUILD", physical_contract="RB2610")
    hint = point("hint", hint_id="hint-1", physical_contract="RB2610",
                 known_at=fixtures.AT, quantity_effect="none")
    wrong_owner = {**hint, "value": {**hint["value"], "physical_contract": "RB2611"}}
    trade_identity = presentation_point(
        kind="trade_identity", trading_day=day, formula_versions=stream.formula_versions,
        value={"source_action_id": "build-1", "public_trade_id": "public-one"},
    )
    saved = repository.commit_batch(seed, fixtures._open_batch(stream, revision, manifest, seed, evidence={
        "presentation_v1": envelope([frame, action, wrong_owner, hint, trade_identity]),
    }))
    checkpoint, _ = repository.load_checkpoint(stream.stream_id, revision)
    repository.publish_revision(stream.stream_id, revision, checkpoint.row_version, fixtures._digest(manifest))

    adapter = newow.Newow(factory)
    result = adapter.evidence(CATALOG["newow_trend"], "rb", "1d")
    assert result["status"] == "HISTORICAL_RESULT"
    assert result["result"]["seq"] == saved.seq
    assert result["action_trading_day"] == day
    assert result["trade_cutoff"] == fixtures.AT
    assert result["actions"] == [action["value"]]
    assert result["hints"] == [hint["value"]]
    assert result["reference_trades"][0]["public_reference_trade_id"] == "public-one"



def test_tqkq_separates_monitor_identity_from_native_readback_and_source(monkeypatch):
    at = datetime.now(UTC).isoformat()
    packet = dict(runtime_tag="v1.16.139", runtime_commit="a" * 40, overview=dict(
        snapshot="observed", readback_status="unverified", block_code=None, generated_at=at, status="available",
        observer={"published_at": at, "status": "running", "opening_enabled": True, "executable_product_count": 0},
        trading_scope={"status": "FLATTEN_PENDING", "native_readback_verified": False}, readback_at=at,
        source_times={},
    ))
    monkeypatch.setattr(htdy, "snapshot", lambda: packet)
    value = htdy.runtime()
    assert value["status"] == "UNVERIFIED"
    assert value["deployment"] == "v1.16.139"
    assert value["heartbeat_at"] == at and value["watermark"] is None
    assert value["authorization"]["opening_enabled"] is True
    assert value["authorization"]["executable_products"] == 0

    packet["overview"]["readback_status"] = "verified"
    packet["overview"]["trading_scope"]["native_readback_verified"] = True
    assert htdy.runtime()["status"] == "UNVERIFIED"



def test_invalid_historical_window_preserves_current_publication_status(monkeypatch):
    monkeypatch.setattr(newow, "latest_formal_reference", lambda *args, **kwargs: None)

    def legacy_window(*args, **kwargs):
        raise ValueError("MARKET_REFERENCE_RESULT_INVALID")

    monkeypatch.setattr(newow, "latest_reference", legacy_window)
    adapter = newow.Newow(lambda: None, receipt_only=True, formal=True)
    result = adapter.evidence(CATALOG["newow_main_rise"], "rb", "1d")
    assert result["status"] == "UNAVAILABLE"
    assert result["diagnostic"] == "MARKET_REFERENCE_RESULT_INVALID"
    assert result["current_publication"] == "NOT_PUBLISHED"
