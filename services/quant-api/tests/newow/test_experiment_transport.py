from copy import deepcopy
import pytest
from app.market_data.newow.experiment_transport import experiment_response
from app.market_data.newow.snapshot_cache import SnapshotCache
from app.market_data.newow.product_reader import NewowProductReadError


def result():
    return dict(
        product="rb",
        frequency="1d",
        kind="osc-test",
        as_of="2026-10-19T07:00:00+00:00",
        formula_version="formula",
        profile_id="profile",
        input_policy_version="policy",
        input_snapshot_hash="a" * 64,
        window={"since": "2026-01-01", "through": "2026-10-19"},
        bars=[dict(bar_end="2026-10-19T07:00:00+00:00", trading_day="2026-10-19")],
        segments=[
            dict(
                segment_id="owner",
                physical_contract="RB2701",
                status="CURRENT",
                ordinary={"trades": list(range(125))},
                theoretical={"trades": list(range(9))},
            )
        ],
    )


def test_bounded_panel_and_history_do_not_change_projection():
    data = result()
    original = deepcopy(data)
    cache = SnapshotCache()
    panel = experiment_response(data, cache)
    assert panel["segments"][0]["ordinary"]["trades"] == [122, 123, 124]
    assert panel["segments"][0]["ordinary"]["total_count"] == 125
    assert data == original
    token = panel["meta"]["snapshot_token"]
    before = None
    rows = []
    while True:
        page = experiment_response(
            data,
            cache,
            snapshot_token=token,
            part="history",
            segment_id="owner",
            before=before,
        )
        rows += page["items"]
        before = page["next_before"]
        if not before:
            break
    assert rows == list(reversed(range(125)))


def test_cursor_and_snapshot_fail_closed_on_mode_input_or_owner_changes():
    data = result()
    cache = SnapshotCache()
    token = experiment_response(data, cache)["meta"]["snapshot_token"]
    cursor = experiment_response(
        data, cache, snapshot_token=token, part="history", segment_id="owner"
    )["next_before"]
    for change in [dict(mode="theoretical"), dict(segment_id="foreign")]:
        with pytest.raises(NewowProductReadError):
            experiment_response(
                data,
                cache,
                snapshot_token=token,
                part="history",
                segment_id=change.get("segment_id", "owner"),
                mode=change.get("mode", "ordinary"),
                before=cursor,
            )
    data["segments"][0]["status"] = "DATA_CONFLICT"
    with pytest.raises(NewowProductReadError, match="SNAPSHOT_GENERATION_CONFLICT"):
        experiment_response(data, cache, snapshot_token=token)


def test_expired_tokens_and_invalid_parameters_are_not_recovered_silently():
    clock = [0]
    cache = SnapshotCache(ttl_seconds=1, now=lambda: clock[0])
    data = result()
    token = experiment_response(data, cache)["meta"]["snapshot_token"]
    clock[0] = 2
    with pytest.raises(NewowProductReadError, match="SNAPSHOT_GENERATION_CONFLICT"):
        experiment_response(data, cache, snapshot_token=token)
    for args in [
        dict(part="history"),
        dict(limit=201),
        dict(part="panel", before="bad"),
    ]:
        with pytest.raises(NewowProductReadError):
            experiment_response(data, cache, **args)


def test_http_v2_contract_etag_and_cross_mode_cursor(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import market_newow
    from app.db.session import get_db
    from app.market_data.newow.experiments import NewowExperimentService
    from types import SimpleNamespace
    from contextlib import contextmanager

    priorities = []

    @contextmanager
    def admission(cancelled, *, priority):
        priorities.append(priority)
        yield

    monkeypatch.setattr(
        market_newow, "_PRODUCT_GATE", SimpleNamespace(acquire=admission)
    )
    data = result()
    monkeypatch.setattr(market_newow, "_PRODUCT_CACHE", SnapshotCache())
    monkeypatch.setattr(market_newow, "_enforce_product_frequency", lambda *a: None)
    monkeypatch.setattr(market_newow, "_input_quality_policy", lambda *a: None)
    monkeypatch.setattr(market_newow, "build_market_data_service", lambda *a: None)
    monkeypatch.setattr(market_newow, "build_database_coverage_source", lambda *a: None)
    monkeypatch.setattr(market_newow, "load_active_products", lambda: ())
    monkeypatch.setattr(
        market_newow,
        "NewowComposition",
        lambda *a: SimpleNamespace(reader=lambda **k: None),
    )
    monkeypatch.setattr(NewowExperimentService, "query", lambda *a: data)
    app = FastAPI()
    app.include_router(market_newow.router)
    app.dependency_overrides[get_db] = lambda: None
    params = dict(product="rb", frequency="1d", kind="osc-test", as_of=data["as_of"])
    with TestClient(app) as client:
        response = client.get("/api/v1/market/newow/experiments", params=params)
        assert response.status_code == 200, response.text
        panel = response.json()
        assert panel["schema_version"] == "newow_experiment_detail_v2"
        assert (
            client.get(
                "/api/v1/market/newow/experiments",
                params=params,
                headers={"If-None-Match": response.headers["etag"]},
            ).status_code
            == 304
        )
        token = panel["meta"]["snapshot_token"]
        query = {
            **params,
            "snapshot_token": token,
            "reference_part": "history",
            "segment_id": "owner",
        }
        page = client.get("/api/v1/market/newow/experiments", params=query)
        assert page.status_code == 200, page.text
        assert len(page.json()["items"]) == 50
        assert priorities[-1] == 3, "history must not queue at main-chart priority"
        conflict = client.get(
            "/api/v1/market/newow/experiments",
            params={
                **query,
                "reference_mode": "theoretical",
                "history_before": page.json()["next_before"],
            },
        )
        assert conflict.status_code == 409
        assert (
            client.get(
                "/api/v1/market/newow/experiments",
                params={**query, "history_limit": 201},
            ).status_code
            == 422
        )


def test_actual_experiment_models_are_unchanged_by_transport():
    from newow.test_experiments import Reader, make_bar, NOW
    from app.market_data.newow.experiments import (
        NewowExperimentService,
        ExperimentQuery,
    )

    for kind in ("osc-test", "osc-test2", "osc-test3", "osc-test4"):
        raw = NewowExperimentService(
            Reader(tuple(make_bar(i) for i in range(40))), now=lambda: NOW
        ).query(ExperimentQuery("rb", "1d", kind))
        panel = experiment_response(raw, SnapshotCache())
        assert panel["meta"]["data_revision_identity"] == raw["data_revision_identity"]
        for original, segment in zip(raw["segments"], panel["segments"], strict=True):
            for mode in ("ordinary", "theoretical"):
                assert {
                    k: v
                    for k, v in segment[mode].items()
                    if k not in {"trades", "total_count"}
                } == {k: v for k, v in original[mode].items() if k != "trades"}
                assert segment[mode]["total_count"] == len(original[mode]["trades"])
                assert segment[mode]["trades"] == original[mode]["trades"][-3:]
