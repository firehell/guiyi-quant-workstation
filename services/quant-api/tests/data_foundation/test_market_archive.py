from datetime import UTC, date, datetime, timedelta
from app.market_data.after_market import _atomic_write_status, _evidence_hash
from app.market_data.market_archive import (
    archive_receipt, read_archive_receipt, retain_archive_receipt, retained_cleanup_receipt,
)


DAY = date(2026, 11, 26)
FINISHED = datetime(2026, 11, 26, 10, 11, tzinfo=UTC)


def _status(*, finished=FINISHED, digest="a" * 64):
    started = finished - timedelta(minutes=6)
    return {
        "schema_version": 3,
        "current_run": None,
        "last_successful_trading_day": DAY.isoformat(),
        "last_run": {
            "status": "passed",
            "trading_day": DAY.isoformat(),
            "attempts": 1,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "products": ["jm"],
            "historical_publications": [],
            "live_evidence": {
                "trading_day": DAY.isoformat(), "attempt": 1, "run_started_at": started.isoformat(),
                "scope_sha256": _evidence_hash(["jm"]), "snapshot_sha256": "b" * 64,
                "formal_rank1_sha256": "b" * 64, "rank1_matches_snapshot": True,
                "reconciled_at": started.isoformat(), "code_commit": None,
                "cleanup_verified": True, "cleanup_checked_at": finished.isoformat(),
                "remaining_bar_keys": 0, "subscription_present": False,
                "canonical_live_exclusion": "no_publication", "canonical_readback": {"jm": digest},
            },
        },
    }


def test_archive_receipt_requires_native_readback_and_rejects_future_qualification():
    valid = _status()
    assert archive_receipt(valid, now=FINISHED).trading_day == DAY
    assert archive_receipt(valid, now=FINISHED - timedelta(seconds=1)) is None
    del valid["last_run"]["live_evidence"]["canonical_readback"]
    assert archive_receipt(valid, now=FINISHED) is None


def test_identical_archive_replay_deduplicates_but_same_day_revision_is_admitted(tmp_path):
    path = tmp_path / "after-market-status.json"
    for index, digest in enumerate(("a", "a", "c")):
        instant = FINISHED + timedelta(minutes=index)
        _atomic_write_status(path, _status(finished=instant, digest=digest * 64))
        retain_archive_receipt(path, now=instant)
    receipts = tuple(path.parent.glob("market-archive-receipts/*"))
    assert len(receipts) == 2
    assert {read_archive_receipt(p, now=instant).finished_at for p in receipts} == {FINISHED, instant}


def test_retained_cleanup_is_exact_and_independent_of_failed_mutable_status(tmp_path):
    status_path = tmp_path / "after-market-status.json"
    status = _status()
    _atomic_write_status(status_path, status)
    retain_archive_receipt(status_path, now=FINISHED)
    status["last_run"].update(status="failed", error_code="RQDATA_NOT_READY")
    del status["last_run"]["live_evidence"]
    _atomic_write_status(status_path, status)
    assert archive_receipt(status, now=FINISHED) is None

    scope = {"sandbox": tmp_path, "day": DAY, "now": FINISHED, "products": ("jm",)}
    assert retained_cleanup_receipt(**scope)["remaining_bar_keys"] == 0
    assert retained_cleanup_receipt(**scope, formal_rank1_sha256="b" * 64)["subscription_present"] is False
    assert retained_cleanup_receipt(**scope, formal_rank1_sha256="c" * 64) is None
    assert retained_cleanup_receipt(**{**scope, "products": ("rb",)}) is None
    assert retained_cleanup_receipt(**{**scope, "day": DAY + timedelta(days=1)}) is None


def test_reference_intake_resumes_unfinished_routes_and_acknowledges_once(tmp_path):
    from app.market_data.newow.market_reference_after_close import consume_receipt

    receipt = archive_receipt(_status(), now=FINISHED)
    state = {"tick": 0}
    ids = ("reference-stream:" + "1" * 64, "reference-stream:" + "2" * 64)
    def refresh(receipt, completed, cancelled):
        assert not cancelled()
        state["tick"] += 1
        completed.add(ids[0])
        if state["tick"] >= 2:
            completed.add(ids[1])
        return ids

    assert consume_receipt(tmp_path, receipt, refresh=refresh)["status"] == "completed"
    assert consume_receipt(tmp_path, receipt, refresh=refresh)["status"] == "already_consumed"
    assert state["tick"] == 2


def test_reference_intake_never_acknowledges_empty_or_changed_scope(tmp_path):
    from app.market_data.newow.market_reference_after_close import consume_receipt

    receipt = archive_receipt(_status(), now=FINISHED)
    assert consume_receipt(tmp_path, receipt, refresh=lambda *_: ())["status"] == "no_routes"
    assert not list(tmp_path.rglob("*.json"))


def test_web_selection_reads_only_the_latest_committed_historical_reference(monkeypatch):
    from app.market_data.newow.market_reference_after_close import latest_reference
    from app.market_data.newow.product_release import (
        FORMAL_HISTORICAL_REFERENCE_PRICE_POLICY, candidate_input_quality_policy,
    )
    from guiyi_quant.newow.product_adapters import build_product_identity
    from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
    from guiyi_quant.newow.product_identity import build_newow_stream_identity
    from tests.reference_trading import test_repository as fixtures

    identity = build_newow_stream_identity(build_product_identity(
        "rb", ProductStrategy.TREND, ProductFrequency.DAILY,
        input_quality_policy=candidate_input_quality_policy("rb", "1d", candidate_weekly=False),
        reference_price_policy=FORMAL_HISTORICAL_REFERENCE_PRICE_POLICY,
    ))
    monkeypatch.setattr(fixtures, "_stream", lambda: identity)
    repository, factory, stream, revision, manifest, seed = fixtures._seed_repository(
        dependency_manifest={"query_since": "2026-09-18", "query_through": "2026-09-19"},
    )
    assert latest_reference("rb", "trend", "1d", session_factory=factory) is None
    opened = repository.commit_batch(seed, fixtures._open_batch(stream, revision, manifest, seed))
    assert latest_reference("rb", "trend", "1d", session_factory=factory) is None
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    repository.publish_revision(stream.stream_id, revision, token.row_version, fixtures._digest(manifest))

    result = latest_reference("rb", "trend", "1d", session_factory=factory)
    assert result["stream_id"] == stream.stream_id
    assert result["revision_id"] == revision
    assert result["seq"] == opened.seq
    assert result["cutoff"] == fixtures.AT
    assert result["through"] == "2026-09-19"


def test_reference_routes_use_the_requests_bound_sandbox_factory(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import reference_trading
    from tests.reference_trading import test_repository as fixtures

    _, factory, *_ = fixtures._seed_repository(sqlite_path=tmp_path / "candidate.sqlite")
    def unavailable():
        raise AssertionError("restricted app cannot open ambient database")
    monkeypatch.setattr(reference_trading, "SessionLocal", unavailable)
    app = FastAPI()
    app.state.market_foundation_reference_sessions = factory
    app.include_router(reference_trading.router)
    with TestClient(app) as client:
        response = client.get("/api/v1/reference-trading/newow/after-close", params={
            "product": "rb", "strategy": "trend", "frequency": "1d",
        })
        assert response.status_code == 200 and response.json() == {"result": None}
        for product in ("PD", " pt "):
            rejected = client.get("/api/v1/reference-trading/newow/after-close", params={
                "product": product, "strategy": "trend", "frequency": "1d",
            })
            assert rejected.status_code == 410 and rejected.json()["detail"]["code"] == "PRODUCT_RETIRED"
        missing = "reference-stream:" + "f" * 64
        response = client.get(f"/api/v1/reference-trading/streams/{missing}/trades", params={
            "since": "2026-09-18", "through": "2026-09-19",
        })
        assert response.status_code == 404 and response.json()["detail"]["code"] == "STREAM_NOT_FOUND"
        assert client.get("/api/v1/reference-trading/health").status_code == 404


def test_candidate_chart_presentation_reads_saved_actions_and_requires_matching_frame(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.reference_trading import router
    from app.reference_trading.presentation import envelope, presentation_point
    from tests.reference_trading import test_repository as fixtures

    from app.market_data.newow.product_release import (
        FORMAL_HISTORICAL_REFERENCE_PRICE_POLICY, candidate_input_quality_policy,
    )
    from guiyi_quant.newow.product_adapters import build_product_identity
    from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
    from guiyi_quant.newow.product_identity import build_newow_stream_identity

    identity = build_newow_stream_identity(build_product_identity(
        "rb", ProductStrategy.TREND, ProductFrequency.DAILY,
        input_quality_policy=candidate_input_quality_policy("rb", "1d", candidate_weekly=False),
        reference_price_policy=FORMAL_HISTORICAL_REFERENCE_PRICE_POLICY,
    ))
    monkeypatch.setattr(fixtures, "_stream", lambda: identity)
    day = fixtures.AT.date()
    repository, factory, stream, revision, manifest, seed = fixtures._seed_repository(
        sqlite_path=tmp_path / "presentation.sqlite",
        dependency_manifest={"query_since": day.isoformat(), "query_through": day.isoformat()},
    )
    frame = presentation_point(
        kind="indicator", trading_day=day, formula_versions=stream.formula_versions,
        value={"version": "newow_bar_state_v1", "bar_end": fixtures.AT,
               "physical_contract": "RB2610", "source_bar_sha256": "b" * 64,
               "main_values": {"a": "3550.1"}, "action_ids": ["build-1"], "hint_ids": []},
    )
    action = presentation_point(
        kind="action", trading_day=day, formula_versions=stream.formula_versions,
        value={"signal_id": "build-1", "kind": "BUILD", "physical_contract": "RB2610", "bar_end": fixtures.AT},
    )
    wrong_owner = {**action, "value": {**action["value"], "physical_contract": "RB2611"}}
    trade_identity = presentation_point(
        kind="trade_identity", trading_day=day, formula_versions=stream.formula_versions,
        value={"source_action_id": "build-1", "public_trade_id": "public-one"},
    )
    repository.commit_batch(seed, fixtures._open_batch(stream, revision, manifest, seed, evidence={
        "presentation_v1": envelope([frame, wrong_owner, action, trade_identity]),
    }))
    token, _ = repository.load_checkpoint(stream.stream_id, revision)
    repository.publish_revision(stream.stream_id, revision, token.row_version, fixtures._digest(manifest))

    app = FastAPI()
    app.state.market_foundation_reference_sessions = factory
    app.include_router(router)
    window = {"since": day.isoformat(), "through": day.isoformat(), "cutoff": fixtures.AT.isoformat()}
    with TestClient(app) as client:
        page = client.get(f"/api/v1/reference-trading/streams/{stream.stream_id}/trades", params=window)
        assert page.status_code == 200, page.json()
        response = client.get("/api/v1/reference-trading/newow/after-close/presentation", params={
            **window, "stream_id": stream.stream_id, "snapshot": page.json()["snapshot"],
            "bar_from": fixtures.AT.isoformat(), "bar_through": fixtures.AT.isoformat(),
        })
        assert response.status_code == 200
        assert response.json()["frames"][0]["actions"] == [action["value"]]
        assert response.json()["frames"][0]["main_values"] == {"a": "3550.1"}
        assert response.json()["explanation_status"] == "not_materialized"


def test_bar_fingerprint_same_exact_historical_encoding_but_daily_fact_differs():
    from dataclasses import replace
    from decimal import Decimal
    import hashlib
    import json

    from app.market_data.domain import CanonicalBar, canonical_bar_source_sha256

    bar = CanonicalBar(FINISHED, DAY, Decimal("10.00"), Decimal("10.01"), Decimal("10.00"),
                       Decimal("10.01"), Decimal("3"), None, Decimal("4"))
    historical = (FINISHED.isoformat(), DAY.isoformat(), "10.00", "10.01", "10.00", "10.01", "3", "None", "4")
    assert canonical_bar_source_sha256(bar) == hashlib.sha256(json.dumps(historical, separators=(",", ":")).encode()).hexdigest()
    assert canonical_bar_source_sha256(replace(bar, turnover=Decimal(0))) != canonical_bar_source_sha256(bar)


def test_archive_rejects_redis_client_different_from_declared_isolation(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import pytest
    from redis import Redis
    from sqlalchemy.engine import make_url

    from app.market_data.live_market import RedisLiveStore
    from app.market_data.market_archive import build_isolated_archive

    sandbox = tmp_path.resolve()
    canonical = sandbox / "canonical"
    canonical.mkdir()
    monkeypatch.setenv("GUIYI_MARKET_FOUNDATION_SANDBOX", str(sandbox))
    result_db = make_url("postgresql+psycopg://127.0.0.1:5402/guiyi_market_foundation")
    manager = SimpleNamespace(catalog=SimpleNamespace(
        canonical_root=canonical, session=SimpleNamespace(get_bind=lambda: SimpleNamespace(url=result_db)),
    ))
    redis = Redis(host="127.0.0.1", port=6379, db=0)
    try:
        with pytest.raises(ValueError, match="MARKET_FOUNDATION_REDIS_BINDING_CONFLICT"):
            build_isolated_archive(
                manager, redis_url="redis://127.0.0.1:6388/0", live_store=RedisLiveStore(redis),
                rqdata_factory=None, sleep=None,
            )
    finally:
        redis.close()



def test_stable_formal_receipt_survives_release_rotation(tmp_path):
    from app.market_data.market_archive import current_retained_receipt

    old_status = tmp_path / "release-a" / "after-market-status.json"
    stable = tmp_path / "stable" / "market-foundation"
    stable.parent.mkdir(mode=0o700)
    assert current_retained_receipt(stable, now=FINISHED) is None
    _atomic_write_status(old_status, _status())
    path = retain_archive_receipt(old_status, now=FINISHED, archive_root=stable)
    first = current_retained_receipt(stable, now=FINISHED)
    assert path.parent.parent == stable and path.stem == first.identity

    new_status = tmp_path / "release-b" / "after-market-status.json"
    later = FINISHED + timedelta(minutes=10)
    _atomic_write_status(new_status, _status(finished=later))
    assert retain_archive_receipt(new_status, now=later, archive_root=stable) == path
    assert current_retained_receipt(stable, now=later) == first
    _atomic_write_status(new_status, _status(finished=later, digest="c" * 64))
    next_receipt = retain_archive_receipt(new_status, now=later, archive_root=stable)
    assert current_retained_receipt(stable, now=later).identity == next_receipt.stem
    assert read_archive_receipt(path, now=later) == first
