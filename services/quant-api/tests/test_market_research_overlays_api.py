from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import json
import os
import re

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.market_data.domain import BarFrequency, SeriesKind
from app.market_data.operational_universe import ActiveUniverseError
from app.market_data.subing_calibration import SubingCalibrationError
from app.market_data.subing_lifecycle import ConfirmationSource
from app.market_data.subing_lifecycle_policy import SubingLifecyclePolicyError
from app.market_data.subing_strategy.contracts import SubingStrategyDirection
from app.market_data.subing_strategy.current_service import (
    SubingStrategyCurrentSourceIdentityError,
)
from app.market_data.subing_strategy.direction_context import (
    SubingStrategyContextIdentityError,
)
from app.market_data.subing_strategy.policy import SubingStrategyPolicyError
from app.market_data.subing_strategy.service import (
    SubingStrategyActiveProductError,
    SubingStrategySegmentIdentityError,
    SubingStrategySourceUnavailableError,
)
from app.market_data.subing_strategy.performance import (
    SubingStrategyPerformanceProjection,
    SubingStrategyPerformanceStats,
    SubingStrategyPerformanceSummary,
)
from app.market_data.subing_strategy.performance_snapshot import (
    SubingStrategyPerformancePrefixCounts,
    SubingStrategyPerformanceSegmentFact,
    subing_strategy_performance_snapshot_from_projection,
)
from app.market_data.subing_strategy.performance_snapshot_store import (
    SubingStrategyPerformanceFileSnapshotStore,
)


_EMPTY_STATS = {
    "completed": 0,
    "positive": 0,
    "negative": 0,
    "flat": 0,
    "positive_rate_percent": None,
    "mean_reference_change_percent": None,
    "median_reference_change_percent": None,
    "best_reference_change_percent": None,
    "worst_reference_change_percent": None,
    "mean_holding_15m_bars": None,
}
_PERFORMANCE_WIRE = {
    "strategy_id": "subing_strategy_v1",
    "formula_version": "subing_strategy_15m_v1",
    "symbol": "jm",
    "series_kind": "actual_dominant",
    "frequency": "15m",
    "coverage": {
        "since": "2020-01-02",
        "through": "2026-08-26",
        "resolved_cutoff": "2026-08-26T07:00:00Z",
        "segment_count": 12,
        "bar_count_15m": 12345,
        "context_unavailable_count": 3,
    },
    "cache_state": "hit",
    "summary": {
        "overall": _EMPTY_STATS,
        "long": _EMPTY_STATS,
        "short": _EMPTY_STATS,
        "open_episodes": 0,
    },
    "exit_reason_counts": [{"reason_code": "EMA21", "count": 2}],
    "episodes": [],
}


def _empty_stats() -> SubingStrategyPerformanceStats:
    return SubingStrategyPerformanceStats(0, 0, 0, 0, None, None, None, None, None, None)


def _performance_snapshot():
    empty = _empty_stats()
    return subing_strategy_performance_snapshot_from_projection(
        SubingStrategyPerformanceProjection(
            strategy_id="subing_strategy_v1",
            formula_version="subing_strategy_15m_v1",
            symbol="jm",
            series_kind=SeriesKind.ACTUAL_DOMINANT,
            frequency=BarFrequency.M15,
            coverage_since=date(2020, 1, 2),
            coverage_through=date(2026, 8, 26),
            resolved_cutoff=datetime(2026, 8, 26, 7, 0, tzinfo=UTC),
            segment_count=12,
            bar_count_15m=12345,
            context_unavailable_count=3,
            cache_state="hit",
            summary=SubingStrategyPerformanceSummary(
                empty, empty, empty, 0, (("EMA21", 2),)
            ),
            episodes=(),
        ),
        immutable_prefix_segment_count=1,
        immutable_prefix_counts=SubingStrategyPerformancePrefixCounts(0, 0, 0, 0),
        segment_facts=(
            SubingStrategyPerformanceSegmentFact(
                contract="jm2609",
                effective_start=date(2020, 1, 2),
                effective_end=date(2026, 8, 26),
                loaded_through=date(2026, 8, 26),
                bar_count_1m=1,
                bar_count_5m=1,
                bar_count_15m=12345,
                context_unavailable_count=3,
                source_identity="a" * 64,
            ),
        ),
        source_manifest_sha256="b" * 64,
        generated_at=datetime(2026, 8, 27, 8, 0, tzinfo=UTC),
        engine_identity_sha256="e" * 64,
    )


def _file_tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class _Lineage:
    def __init__(self, through: date) -> None:
        self.through = through
        self.resolve_calls: list[object] = []

    def expected_complete_through(self, symbol: str) -> date:
        assert symbol == "jm"
        return self.through

    def resolve(self, symbol: str, *, through: date | None = None):
        self.resolve_calls.append((symbol, through))
        raise AssertionError("HTTP must not resolve full lineage")


def _install_performance_snapshot_query(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    through: date = date(2026, 8, 26),
    products: tuple[str, ...] = ("jm",),
):
    root = (tmp_path / "performance").resolve()
    root.mkdir()
    store = SubingStrategyPerformanceFileSnapshotStore(
        root,
        root_validator=lambda: root,
    )
    lineage = _Lineage(through)
    historical_calls: list[object] = []
    adoption_calls: list[object] = []
    canonical_calls: list[object] = []

    def fail_historical(*args, **kwargs):
        historical_calls.append((args, kwargs))
        raise AssertionError("Historical construction")

    def fail_old_service(_session):
        raise AssertionError("old performance service")

    def fail_adoption(*args, **kwargs):
        adoption_calls.append((args, kwargs))
        raise AssertionError("adoption")

    def fail_canonical(*args, **kwargs):
        canonical_calls.append((args, kwargs))
        raise AssertionError("Canonical Bar read")

    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_strategy_performance_service",
        fail_old_service,
        raising=False,
    )
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_strategy_historical_service",
        fail_historical,
        raising=False,
    )
    monkeypatch.setattr(
        "app.market_data.composition.build_subing_strategy_historical_service",
        fail_historical,
        raising=False,
    )
    monkeypatch.setattr(
        "app.market_data.subing_strategy.performance_adoption.SubingStrategyPerformanceAdopter.adopt",
        fail_adoption,
        raising=False,
    )
    monkeypatch.setattr(
        "app.market_data.storage.CanonicalMonthlyStore.read_month",
        fail_canonical,
        raising=False,
    )
    monkeypatch.setattr(
        "app.market_data.market_data_service.MarketDataService.query",
        fail_canonical,
        raising=False,
    )

    def build(_session):
        from app.market_data.subing_strategy.performance_snapshot import (
            SubingStrategyPerformanceSnapshotQuery,
        )

        return SubingStrategyPerformanceSnapshotQuery(
            store=store,
            lineage=lineage,
            products=products,
        )

    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_strategy_performance_snapshot_query",
        build,
        raising=False,
    )
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    return store, lineage, root, historical_calls, adoption_calls, canonical_calls


def _clear_db_override() -> None:
    app.dependency_overrides.pop(get_db, None)


def _assert_public_409(response, root: Path) -> None:
    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "SUBING_STRATEGY_CACHE_UNAVAILABLE"}
    }
    body = response.text
    assert str(root) not in body
    assert "traceback" not in body.lower()
    assert "file \"" not in body.lower()
    assert ".py" not in body
    assert "select " not in body.lower()
    assert "insert " not in body.lower()
    assert re.search(r"[0-9a-f]{64}", body) is None


def test_subing_strategy_performance_returns_current_snapshot_wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, lineage, root, historical_calls, adoption_calls, canonical_calls = (
        _install_performance_snapshot_query(monkeypatch, tmp_path)
    )
    snapshot = _performance_snapshot()
    store.publish_current(snapshot)
    before = _file_tree(root)
    try:
        response = TestClient(app).get(
            "/api/v1/market/research/subing-strategy/performance",
            params={"symbol": "JM"},
        )
    finally:
        _clear_db_override()

    assert response.status_code == 200
    expected = {
        **_PERFORMANCE_WIRE,
        "cache_identity_sha256": snapshot.identity_sha256,
        "cache_generated_at": snapshot.generated_at.astimezone(UTC).isoformat().replace(
            "+00:00", "Z"
        ),
    }
    assert response.json() == expected
    assert re.fullmatch(r"[0-9a-f]{64}", snapshot.identity_sha256)
    assert historical_calls == []
    assert adoption_calls == []
    assert canonical_calls == []
    assert lineage.resolve_calls == []
    assert _file_tree(root) == before


@pytest.mark.parametrize(
    "kind",
    ("missing", "stale", "future", "corrupt", "hash_mismatched", "symlinked"),
)
def test_subing_strategy_performance_rejects_invalid_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    through = date(2026, 8, 26)
    if kind == "stale":
        through = date(2026, 8, 27)
    elif kind == "future":
        through = date(2026, 8, 25)
    store, _lineage, root, historical_calls, adoption_calls, canonical_calls = (
        _install_performance_snapshot_query(monkeypatch, tmp_path, through=through)
    )
    if kind != "missing":
        snapshot = _performance_snapshot()
        store.publish_current(snapshot)
        manifest = root / "current" / "jm.json"
        if kind == "corrupt":
            manifest.write_bytes(b"{")
            os.chmod(manifest, 0o600)
        elif kind == "hash_mismatched":
            body = json.loads(manifest.read_text())
            body.pop("manifest_sha256")
            body["payload_sha256"] = "0" * 64
            envelope = dict(body)
            envelope["manifest_sha256"] = sha256(_canonical_bytes(body)).hexdigest()
            manifest.write_bytes(_canonical_bytes(envelope))
            os.chmod(manifest, 0o600)
        elif kind == "symlinked":
            elsewhere = root / "elsewhere.json"
            elsewhere.write_bytes(manifest.read_bytes())
            os.chmod(elsewhere, 0o600)
            manifest.unlink()
            manifest.symlink_to(elsewhere)
    before = _file_tree(root)
    try:
        response = TestClient(app).get(
            "/api/v1/market/research/subing-strategy/performance",
            params={"symbol": "jm"},
        )
    finally:
        _clear_db_override()

    _assert_public_409(response, root)
    assert historical_calls == []
    assert adoption_calls == []
    assert canonical_calls == []
    assert _file_tree(root) == before


@pytest.mark.parametrize("symbol", ("rb", "1"))
def test_subing_strategy_performance_rejects_invalid_or_inactive_products(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    symbol: str,
) -> None:
    store, _lineage, root, historical_calls, adoption_calls, canonical_calls = (
        _install_performance_snapshot_query(monkeypatch, tmp_path)
    )
    store.publish_current(_performance_snapshot())
    before = _file_tree(root)
    try:
        response = TestClient(app).get(
            "/api/v1/market/research/subing-strategy/performance",
            params={"symbol": symbol},
        )
    finally:
        _clear_db_override()

    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "SUBING_STRATEGY_ACTIVE_PRODUCT_INVALID"}
    }
    assert str(root) not in response.text
    assert "traceback" not in response.text.lower()
    assert historical_calls == []
    assert adoption_calls == []
    assert canonical_calls == []
    assert _file_tree(root) == before


class _StrategyService:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.publish_cache_calls: list[bool] = []

    def history(self, request: object, *, publish_cache: bool = False):
        self.publish_cache_calls.append(publish_cache)
        if self.failure is not None:
            raise self.failure
        action = SimpleNamespace(
            action_id="subing-action:open",
            episode_id="subing-episode:one",
            strategy_id="subing_strategy_v1",
            formula_version="subing_strategy_15m_v1",
            kind=SimpleNamespace(value="open_long"),
            symbol="jm",
            contract="JM2609",
            trading_day=date(2026, 8, 3),
            segment_start_trading_day=date(2026, 8, 3),
            opportunity_id="subing-opportunity:one",
            decision_at=datetime(2026, 8, 3, 2, 15, tzinfo=UTC),
            effective_open_at=datetime(2026, 8, 3, 2, 15, tzinfo=UTC),
            effective_bar_end=datetime(2026, 8, 3, 2, 30, tzinfo=UTC),
            reference_price=Decimal("100.5"),
            fill_basis=SimpleNamespace(value="next_bar_open"),
            confirmation_source=ConfirmationSource.FORMAL_V1,
            reason_codes=(),
            direction_context_source_day=date(2026, 7, 31),
            direction_context_target_day=date(2026, 8, 3),
            bound_reference_pivot=None,
        )
        return SimpleNamespace(
            request=request,
            policy=SimpleNamespace(
                strategy_id="subing_strategy_v1",
                formula_version="subing_strategy_15m_v1",
                research_only=True,
                series_kind=SeriesKind.ACTUAL_DOMINANT,
                decision_frequency=BarFrequency.M15,
                lifecycle_policy_id="subing_lifecycle_v2_research_v1",
                allowed_confirmation_sources=(ConfirmationSource.FORMAL_V1,),
            ),
            resolved_cutoff=datetime(2026, 8, 3, 2, 30, tzinfo=UTC),
            segment_summaries=(
                SimpleNamespace(
                    contract="JM2609",
                    start_trading_day=date(2026, 8, 3),
                    end_trading_day=date(2026, 8, 20),
                    loaded_through=date(2026, 8, 3),
                    bar_count_1m=15,
                    bar_count_5m=3,
                    bar_count_15m=1,
                    initial_position=SimpleNamespace(value="flat"),
                    final_position=SimpleNamespace(value="long"),
                    terminal_bar_end=None,
                    pending_action=False,
                ),
            ),
            actions=(action,),
            episodes=(
                SimpleNamespace(
                    episode_id="subing-episode:one",
                    direction=SimpleNamespace(value="long"),
                    entry_action=action,
                    exit_action=None,
                    state=SimpleNamespace(value="open"),
                    holding_bar_count=1,
                    reference_change_percent=None,
                    current_reference_change_percent=Decimal("1.25"),
                    latest_reference_price=Decimal("101.75625"),
                    exit_reason_codes=(),
                    structure_exit_available=False,
                ),
            ),
            context_unavailable=(
                SimpleNamespace(
                    symbol="jm",
                    target_trading_day=date(2026, 8, 4),
                    source_trading_day=date(2026, 8, 3),
                    direction=SubingStrategyDirection.UNAVAILABLE,
                    reason_codes=("D1_UNAVAILABLE",),
                    daily_bar_end=None,
                    hourly_bar_end=None,
                    physical_contract="JM2609",
                ),
            ),
            cache_state="miss",
        )


class _CurrentStrategyService:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure

    def current(self, request: object, _now: datetime):
        if self.failure is not None:
            raise self.failure
        return SimpleNamespace(
            policy=SimpleNamespace(
                strategy_id="subing_strategy_v1",
                formula_version="subing_strategy_15m_v1",
            ),
            request=request,
            contract="JM2605",
            segment_start_trading_day=date(2026, 8, 1),
            source_mode="canonical_live",
            cutoff=datetime(2026, 8, 4, 2, 30, tzinfo=UTC),
            position_state=SimpleNamespace(value="flat"),
            pending_action=SimpleNamespace(
                kind=SimpleNamespace(value="open_long"),
                decision_at=datetime(2026, 8, 4, 2, 15, tzinfo=UTC),
                opportunity_id="subing-opportunity:one",
                reason_codes=(),
            ),
            current_episode=None,
            latest_completed_episode=None,
            direction_context=SimpleNamespace(
                symbol="jm",
                target_trading_day=date(2026, 8, 4),
                source_trading_day=date(2026, 8, 3),
                direction=SubingStrategyDirection.LONG_ONLY,
                reason_codes=("D1_H1_LONG_ALIGNED",),
                daily_bar_end=datetime(2026, 8, 3, 7, 0, tzinfo=UTC),
                hourly_bar_end=datetime(2026, 8, 3, 7, 0, tzinfo=UTC),
                physical_contract="JM2605",
            ),
        )


def test_subing_strategy_current_returns_public_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_strategy_current_service",
        lambda _session: _CurrentStrategyService(),
        raising=False,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing-strategy/current",
        params={
            "series_kind": "actual_dominant",
            "symbol": "JM",
            "frequency": "15m",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "strategy_id": "subing_strategy_v1",
        "formula_version": "subing_strategy_15m_v1",
        "series_kind": "actual_dominant",
        "symbol": "jm",
        "frequency": "15m",
        "contract": "JM2605",
        "segment_start_trading_day": "2026-08-01",
        "source_mode": "canonical_live",
        "cutoff": "2026-08-04T02:30:00Z",
        "position_state": "flat",
        "pending_action": {
            "kind": "open_long",
            "decision_at": "2026-08-04T02:15:00Z",
            "opportunity_id": "subing-opportunity:one",
            "reason_codes": [],
        },
        "current_episode": None,
        "latest_completed_episode": None,
        "direction_context": {
            "symbol": "jm",
            "target_trading_day": "2026-08-04",
            "source_trading_day": "2026-08-03",
            "direction": "long_only",
            "reason_codes": ["D1_H1_LONG_ALIGNED"],
            "daily_bar_end": "2026-08-03T07:00:00Z",
            "hourly_bar_end": "2026-08-03T07:00:00Z",
            "physical_contract": "JM2605",
        },
    }


def test_subing_strategy_current_rejects_unsupported_frequency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_strategy_current_service",
        lambda _session: pytest.fail("invalid request must not execute service"),
        raising=False,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing-strategy/current",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "5m",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "INVALID_SUBING_STRATEGY_CURRENT_REQUEST"}
    }


def test_subing_strategy_current_maps_source_identity_failure_to_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_strategy_current_service",
        lambda _session: _CurrentStrategyService(
            SubingStrategyCurrentSourceIdentityError()
        ),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing-strategy/current",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "15m",
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "SUBING_STRATEGY_CURRENT_SOURCE_IDENTITY_INVALID"}
    }


def test_subing_strategy_current_maps_composition_source_failure_to_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.market_data.operational_universe import OperationalUniverseError

    def fail_build(_session):
        raise OperationalUniverseError()

    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_strategy_current_service",
        fail_build,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing-strategy/current",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "15m",
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "OPERATIONAL_UNIVERSE_INVALID"}
    }


def test_subing_strategy_history_returns_actions_complete_episodes_and_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _StrategyService()
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_strategy_historical_service",
        lambda _session: service,
        raising=False,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing-strategy/history",
        params={
            "series_kind": "actual_dominant",
            "symbol": "JM",
            "frequency": "15m",
            "since": "2026-08-03",
            "through": "2026-08-20",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request"]["symbol"] == "jm"
    assert payload["policy"]["strategy_id"] == "subing_strategy_v1"
    assert payload["resolved_cutoff"] == "2026-08-03T02:30:00Z"
    assert payload["actions"][0]["kind"] == "open_long"
    assert payload["actions"][0]["effective_open_at"] == "2026-08-03T02:15:00Z"
    assert payload["actions"][0]["reference_price"] == "100.5"
    assert payload["segment_summaries"][0]["bar_count_1m"] == 15
    assert payload["episodes"][0]["entry_action"]["action_id"] == ("subing-action:open")
    assert payload["episodes"][0]["state"] == "open"
    assert service.publish_cache_calls == [False]
    assert payload["context_unavailable"][0]["direction"] == "unavailable"
    assert payload["cache_state"] == "miss"


def test_old_subing_historical_signal_route_is_retired() -> None:
    path = "/api/v1/market/research/" + "subing/history"

    assert path not in app.openapi()["paths"]
    assert TestClient(app).get(path).status_code == 404


@pytest.mark.parametrize(
    "params",
    (
        {"series_kind": "continuous", "frequency": "15m"},
        {"series_kind": "actual_dominant", "frequency": "5m"},
        {"series_kind": "actual_dominant", "frequency": "15m", "symbol": "1"},
        {
            "series_kind": "actual_dominant",
            "frequency": "15m",
            "since": "2026-08-21",
            "through": "2026-08-20",
        },
    ),
)
def test_subing_strategy_history_rejects_invalid_request(
    monkeypatch: pytest.MonkeyPatch,
    params: dict[str, str],
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_strategy_historical_service",
        lambda _session: pytest.fail("invalid request must not execute service"),
        raising=False,
    )
    request_params = {
        "series_kind": "actual_dominant",
        "symbol": "jm",
        "frequency": "15m",
        "since": "2026-08-03",
        "through": "2026-08-20",
        **params,
    }

    response = TestClient(app).get(
        "/api/v1/market/research/subing-strategy/history",
        params=request_params,
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "INVALID_SUBING_STRATEGY_REQUEST"}}


@pytest.mark.parametrize(
    "failure",
    (
        SubingStrategyPolicyError(),
        SubingCalibrationError(),
        SubingLifecyclePolicyError(),
        ActiveUniverseError(),
        SubingStrategyActiveProductError(),
        SubingStrategySourceUnavailableError(),
        SubingStrategySegmentIdentityError(),
        SubingStrategyContextIdentityError(),
    ),
)
def test_subing_strategy_history_maps_typed_failures_before_value_error(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_strategy_historical_service",
        lambda _session: _StrategyService(failure),
        raising=False,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing-strategy/history",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "15m",
            "since": "2026-08-03",
            "through": "2026-08-20",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": failure.code}}
