from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.api.observations import get_htdy_evaluator
from app.models.signal import HtdyObservationAlert, SignalEvent, StrategySignal
from app.services.htdy_realtime_alert import (
    HtdyRealtimeObservationEvaluator,
    HtdyObservationCandidate,
    HtdyObservationAlertService,
    candidate_from_output,
    candidate_direction,
)
from guiyi_quant.indicators.htdy_original import (
    HtdyOriginalResult,
    compute_htdy_original,
    synthetic_bars,
)
from guiyi_quant.indicators.policy import require_formal_policy


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_original_policy_allows_only_dedicated_repainting_observation_alert() -> None:
    policy = require_formal_policy(
        "huotian_dayou_original_v0",
        consumer="live_repainting_observation_alert",
    )

    assert policy.confirmed_only is True
    assert "Signal" in policy.blocked_consumers
    assert "notification" in policy.blocked_consumers


def test_production_original_kernel_keeps_future_looking_metadata() -> None:
    bars = synthetic_bars(96)

    result = compute_htdy_original(
        bars["datetime"],
        bars["open"],
        bars["high"],
        bars["low"],
        bars["close"],
        bars["volume"],
    )

    assert result.metadata["indicator_version"] == "original-v0"
    assert result.metadata["future_looking"] is True
    assert result.metadata["repainting_risk"] == "known"
    assert result.metadata["alert_capable"] is True
    assert result.metadata["formal_signal_capable"] is False


def test_candidate_direction_collapses_simultaneous_buy_and_sell() -> None:
    assert candidate_direction(buy=True, sell=False) == "long"
    assert candidate_direction(buy=False, sell=True) == "short"
    assert candidate_direction(buy=True, sell=True) == "conflict"
    assert candidate_direction(buy=False, sell=False) is None


def test_same_bar_and_later_revision_create_only_one_observation_alert() -> None:
    factory = _session_factory()
    with factory() as session:
        service = HtdyObservationAlertService(session)
        first = service.persist(_candidate(revision=1))
        second = service.persist(_candidate(revision=2, direction="short"))

        assert first.status == "created"
        assert second.status == "unchanged"
        assert first.alert_id == second.alert_id
        alert = session.get(HtdyObservationAlert, first.alert_id)
        assert alert is not None
        assert alert.direction == "long"
        assert alert.live_bar_revision == 1
        assert alert.repainting_risk == "known"
        assert alert.future_looking is True
        assert alert.payload["not_trading_instruction"] is True
        assert alert.payload["repaint_followup"] == "none"
        assert session.scalar(select(func.count()).select_from(HtdyObservationAlert)) == 1
        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 0
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0


def test_writer_blocks_unconfirmed_warning_main_and_wrong_period() -> None:
    factory = _session_factory()
    candidates = (
        _candidate(bar_status="forming"),
        _candidate(quality_status="warning"),
        _candidate(actual_contract="JM.MAIN"),
        _candidate(period="5m"),
    )
    with factory() as session:
        service = HtdyObservationAlertService(session)
        results = [service.persist(candidate) for candidate in candidates]

        assert [item.status for item in results] == ["blocked"] * 4
        assert session.scalar(select(func.count()).select_from(HtdyObservationAlert)) == 0


def test_candidate_from_latest_original_output_uses_observed_close() -> None:
    output = _output(buy=True, sell=False)

    candidate = candidate_from_output(
        output,
        continuous_contract="JM.MAIN",
        actual_contract="JM2609",
        dominant_mapping_date=date(2026, 7, 27),
        live_trigger={
            "id": 101,
            "revision": 2,
            "bar_status": "confirmed",
            "quality_status": "passed",
            "confirmed_at": datetime(2026, 7, 27, 1, 15, 1, tzinfo=UTC),
        },
        profile_id="live_observation_v1",
        market_data_file_id=42,
    )

    assert candidate is not None
    assert candidate.direction == "long"
    assert candidate.trigger_price == 103.0
    assert candidate.live_bar_revision == 2
    assert candidate.lineage["future_looking"] is True


def test_observation_alert_list_and_detail_api_are_readonly() -> None:
    factory = _session_factory()
    with factory() as session:
        result = HtdyObservationAlertService(session).persist(_candidate())
        session.commit()
        alert_id = result.alert_id

    def override_get_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        listing = client.get("/api/observations/htdy/alerts")
        detail = client.get(f"/api/observations/htdy/alerts/{alert_id}")

        assert listing.status_code == 200
        assert listing.json()["total"] == 1
        assert listing.json()["items"][0]["future_looking"] is True
        assert detail.status_code == 200
        assert detail.json()["id"] == alert_id
        assert detail.json()["payload"]["not_trading_instruction"] is True
    finally:
        app.dependency_overrides.clear()


def test_preview_evaluator_uses_actual_contract_confirmed_15m_context() -> None:
    context = type(
        "Context",
        (),
        {
            "merged_bars": [
                {
                    "datetime": datetime(2026, 7, 27, 0, 45, tzinfo=UTC),
                    "open": 100.5,
                    "high": 102.0,
                    "low": 100.0,
                    "close": 101.0,
                    "volume": 1000.0,
                }
            ],
            "live_trigger": {
                "id": 101,
                "revision": 1,
                "bar_status": "confirmed",
                "quality_status": "passed",
                "confirmed_at": datetime(2026, 7, 27, 1, 15, 1, tzinfo=UTC),
            },
            "historical_context_file_id": 42,
        },
    )()
    target_resolver = type(
        "Target",
        (),
        {
            "resolve_ready_actual_contract": lambda self, **kwargs: {
                "continuous_contract": "JM.MAIN",
                "actual_contract": "JM2609",
                "dominant_mapping_date": "2026-07-27",
            }
        },
    )()
    context_resolver = type(
        "Resolver",
        (),
        {"resolve": lambda self, **kwargs: context},
    )()

    evaluator = HtdyRealtimeObservationEvaluator(
        session=None,
        target_resolver=target_resolver,
        context_resolver=context_resolver,
        kernel=lambda *args, **kwargs: _output(buy=True, sell=False),
    )
    preview = evaluator.preview()

    assert preview["status"] == "candidate"
    assert preview["writes"] is False
    assert preview["candidate"]["actual_contract"] == "JM2609"
    assert preview["candidate"]["direction"] == "long"
    assert preview["metadata"]["repainting_risk"] == "known"


def test_preview_api_is_readonly_and_fixed_to_jm_15m() -> None:
    class FakeEvaluator:
        def preview(self, **kwargs):
            assert kwargs["contract"] == "JM2609"
            assert kwargs["profile_id"] == "live_observation_v1"
            return {
                "status": "no_observation",
                "writes": False,
                "candidate": None,
                "metadata": {
                    "indicator_code": "huotian_dayou_original_v0",
                    "indicator_version": "original-v0",
                    "alert_policy": "htdy_original_repainting_realtime_v1",
                    "future_looking": True,
                    "repainting_risk": "known",
                    "repaint_followup": "none",
                    "not_trading_instruction": True,
                },
            }

    app.dependency_overrides[get_htdy_evaluator] = lambda: FakeEvaluator()
    try:
        client = TestClient(app)
        response = client.post(
            "/api/observations/htdy/preview",
            json={
                "symbol": "jm",
                "contract": "JM2609",
                "period": "15m",
                "profile_id": "live_observation_v1",
            },
        )
        wrong_period = client.post(
            "/api/observations/htdy/preview",
            json={"symbol": "jm", "contract": "JM2609", "period": "5m"},
        )

        assert response.status_code == 200
        assert response.json()["writes"] is False
        assert wrong_period.status_code == 422
    finally:
        app.dependency_overrides.clear()


def _candidate(
    *,
    revision: int = 1,
    direction: str = "long",
    bar_status: str = "confirmed",
    quality_status: str = "passed",
    actual_contract: str = "JM2609",
    period: str = "15m",
) -> HtdyObservationCandidate:
    bar_end = datetime(2026, 7, 27, 1, 15, tzinfo=UTC)
    return HtdyObservationCandidate(
        symbol="jm",
        continuous_contract="JM.MAIN",
        actual_contract=actual_contract,
        dominant_mapping_date=date(2026, 7, 27),
        period=period,
        bar_end=bar_end,
        trigger_price=1234.5,
        direction=direction,
        bar_status=bar_status,
        quality_status=quality_status,
        provider="rqdata",
        data_role="primary",
        profile_id="live_observation_v1",
        market_data_file_id=42,
        live_bar_id=101,
        live_bar_revision=revision,
        confirmed_at=datetime(2026, 7, 27, 1, 15, 1, tzinfo=UTC),
        lineage={
            "schema_version": "htdy_observation_lineage_v1",
            "actual_contract": actual_contract,
            "period": period,
            "bar_end": bar_end.isoformat(),
            "live_bar_id": 101,
            "live_bar_revision": revision,
        },
    )


def _output(*, buy: bool, sell: bool) -> HtdyOriginalResult:
    values = np.asarray([101.0, 102.0, 103.0])
    false_flags = np.asarray([False, False, False])
    return HtdyOriginalResult(
        datetimes=np.asarray(
            [
                datetime(2026, 7, 27, 0, 45, tzinfo=UTC),
                datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
                datetime(2026, 7, 27, 1, 15, tzinfo=UTC),
            ],
            dtype=object,
        ),
        open=values - 0.5,
        high=values + 1,
        low=values - 1,
        close=values,
        volume=np.asarray([1000.0, 1100.0, 1200.0]),
        fields={
            "zk1": values + 2,
            "zd1": values - 2,
            "zd2": values - 1,
            "yellow_candle": false_flags,
            "white_candle": false_flags,
            "buy_observation": np.asarray([False, False, buy]),
            "sell_observation": np.asarray([False, False, sell]),
        },
        metadata={
            "indicator_code": "huo_tian_da_you",
            "indicator_version": "original-v0",
            "future_looking": True,
            "repainting_risk": "known",
        },
    )
