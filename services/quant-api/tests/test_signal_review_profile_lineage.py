from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.signal import SignalEvent, SignalNotification, StrategySignal
from app.models.data_center import DataProfile, LiveAggregatedBar, MainContractMap, MarketDataFile, ProfileActiveBinding
from app.models.backtest import BacktestReportModel, BacktestTask, BacktestTradeModel, Watchlist, WatchlistItem
from app.schemas.signal import LiveSignalEvaluationItem, LiveSignalEvaluationResponse, SignalScanRequest
from app.services.live_signal_events import LiveSignalEventService
from app.services.live_market_reader import LiveMarketReader
from app.services.live_signal_context import historical_context_hash
from app.services.rqdata_ingest.parquet import sha256_file
from app.signal.events import SIGNAL_CREATED, record_live_signal_event, record_signal_scan_event
from app.signal.stage9_gate import evaluate_stage9_signal_event_gate


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _formal_lineage(*, source_mode: str = "live_confirmed", revision: int = 1) -> dict:
    return {
        "schema_version": "signal_review_lineage_v1",
        "resolver_name": "ProfileLineageResolver",
        "resolver_contract_version": "signal_profile_v1",
        "quality_policy": "passed_only",
        "source_mode": source_mode,
        "primary": {
            "profile_id": "live_observation_v1",
            "market_data_file_id": 42,
            "instrument_symbol": "jm",
            "contract_code": "JM2609",
            "period": "15m",
            "data_version": "jm2609_15m_passed",
            "provider": "rqdata",
            "data_role": "primary",
            "quality_status": "passed",
            "coverage_start": "2026-07-10T01:00:00+00:00",
            "coverage_end": "2026-07-10T02:00:00+00:00",
        },
        "context_assets": [],
        "contract": {
            "continuous_contract": "JM.MAIN",
            "actual_contract": "JM2609",
            "dominant_mapping_date": "2026-07-10",
        },
        "bar": {
            "bar_start": "2026-07-10T01:15:00+00:00",
            "bar_end": "2026-07-10T01:30:00+00:00",
            "trigger_price": 1234.5,
            "confirmation_mode": "live_confirmed",
            "bar_status": "confirmed",
            "live_bar_id": 101,
            "live_bar_revision": revision,
            "confirmed_at": "2026-07-10T01:30:01+00:00",
        },
    }


def _signal(lineage: dict | None) -> StrategySignal:
    bar_end = datetime(2026, 7, 10, 1, 30, tzinfo=UTC)
    return StrategySignal(
        task_no=None,
        dedupe_key="live:jm:JM2609:15m:2026-07-10T01:30:00+00:00",
        strategy_name="jm_v1b_daily_direction_fast_entry",
        strategy_version="v1.0.0",
        watchlist_code="jm_v1b_live",
        symbol="jm",
        contract="JM2609",
        product="jm",
        continuous_contract="JM.MAIN",
        actual_contract="JM2609",
        dominant_mapping_date=date(2026, 7, 10),
        exchange="DCE",
        period="15m",
        signal_time=bar_end,
        bar_start=bar_end - timedelta(minutes=15),
        bar_end=bar_end,
        trigger_price=1234.5,
        provider="rqdata",
        source="live_db_actual_contract",
        data_role="primary",
        status="entry_signal",
        direction="long",
        signal_level=80,
        score_bucket=80,
        bucket_label="实时确认观察",
        current_price=1234.5,
        open_volume=0,
        margin_required=0.0,
        risk_amount=0.0,
        account_equity=100000.0,
        reasons=["confirmed_test_entry"],
        features={"formal_lineage": deepcopy(lineage)} if lineage else {},
        quality_status={"status": "passed"},
        research_contract=False,
        spec_source="live_confirmed_v1",
        alert_status="unread",
        profile_id="live_observation_v1" if lineage else None,
        market_data_file_id=42 if lineage else None,
    )


def test_event_freezes_signal_lineage_and_stage9_allows_complete_event() -> None:
    factory = _session_factory()
    lineage = _formal_lineage()
    with factory() as session:
        signal = _signal(lineage)
        session.add(signal)
        session.flush()
        event = record_live_signal_event(session, signal, SIGNAL_CREATED, state_key="state-1")
        assert event is not None

        assert event.profile_id == "live_observation_v1"
        assert event.market_data_file_id == 42
        assert event.payload["formal_lineage"] == lineage
        assert event.payload["formal_lineage"] is not signal.features["formal_lineage"]
        assert evaluate_stage9_signal_event_gate(event)["allowed"] is True

        signal.features["formal_lineage"]["primary"]["market_data_file_id"] = 999
        assert event.payload["formal_lineage"]["primary"]["market_data_file_id"] == 42


def test_stage9_blocks_legacy_event_without_formal_lineage() -> None:
    factory = _session_factory()
    with factory() as session:
        signal = _signal(None)
        session.add(signal)
        session.flush()
        event = record_live_signal_event(session, signal, SIGNAL_CREATED, state_key="legacy")
        assert event is not None

        gate = evaluate_stage9_signal_event_gate(event)
        assert gate["allowed"] is False
        assert "formal_lineage_missing" in gate["blocked_reasons"]


def test_live_writer_requires_formal_lineage_and_never_creates_notification() -> None:
    factory = _session_factory()
    with factory() as session:
        result = LiveSignalEventService(session).persist(_response(_item(lineage=None)))

        assert result.blocked == 1
        assert result.blocked_reasons[0]["code"] == "SIGNAL_FORMAL_LINEAGE_MISSING"
        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 0
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0


def test_live_writer_persists_resolved_lineage() -> None:
    factory = _session_factory()
    with factory() as session:
        result = LiveSignalEventService(session).persist(_response(_item(lineage=_formal_lineage())))

        assert result.created == 1
        signal = session.scalar(select(StrategySignal))
        event = session.scalar(select(SignalEvent))
        assert signal is not None and event is not None
        assert signal.profile_id == "live_observation_v1"
        assert signal.market_data_file_id == 42
        assert event.profile_id == signal.profile_id
        assert event.market_data_file_id == signal.market_data_file_id
        assert event.payload["formal_lineage"]["bar"]["live_bar_revision"] == 1
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0


def test_historical_resolver_builds_snapshot_from_profile_and_exact_bar(tmp_path: Path) -> None:
    from app.services.signal_lineage import SignalFormalLineageResolver

    factory = _session_factory()
    bar_end = datetime(2026, 7, 10, 1, 30, tzinfo=UTC)
    with factory() as session:
        market_file = _seed_profile_asset(session, tmp_path, bar_end=bar_end)
        session.commit()

        result = SignalFormalLineageResolver(session, project_root=tmp_path).resolve(
            profile_id="intraday_research_v1",
            symbol="jm",
            continuous_contract="JM.MAIN",
            actual_contract="JM2609",
            period="15m",
            dominant_mapping_date=date(2026, 7, 10),
            bar_start=bar_end - timedelta(minutes=15),
            bar_end=bar_end,
            trigger_price=1234.5,
            source_mode="jm_v1b_historical_replay",
            confirmation={"confirmation_mode": "historical_canonical"},
        )

        assert result.blocked_code is None
        assert result.profile_id == "intraday_research_v1"
        assert result.market_data_file_id == market_file.id
        assert result.snapshot is not None
        assert result.snapshot["primary"]["market_data_file_id"] == market_file.id
        assert result.snapshot["bar"]["confirmation_mode"] == "historical_canonical"


def test_historical_resolver_blocks_mapping_quality_and_trigger_mismatch(tmp_path: Path) -> None:
    from app.services.signal_lineage import SignalFormalLineageResolver

    factory = _session_factory()
    bar_end = datetime(2026, 7, 10, 1, 30, tzinfo=UTC)
    with factory() as session:
        market_file = _seed_profile_asset(session, tmp_path, bar_end=bar_end)
        session.commit()
        resolver = SignalFormalLineageResolver(session, project_root=tmp_path)
        request = {
            "profile_id": "intraday_research_v1",
            "symbol": "jm",
            "continuous_contract": "JM.MAIN",
            "actual_contract": "JM2609",
            "period": "15m",
            "dominant_mapping_date": date(2026, 7, 10),
            "bar_start": bar_end - timedelta(minutes=15),
            "bar_end": bar_end,
            "trigger_price": 1234.5,
            "source_mode": "jm_v1b_historical_replay",
            "confirmation": {"confirmation_mode": "historical_canonical"},
        }

        mapping = session.scalar(select(MainContractMap))
        assert mapping is not None
        mapping.contract_code = "JM2605"
        session.flush()
        assert resolver.resolve(**request).blocked_code == "SIGNAL_DOMINANT_MAPPING_MISMATCH"

        mapping.contract_code = "JM2609"
        market_file.quality_status = "warning"
        session.flush()
        assert resolver.resolve(**request).blocked_code == "SIGNAL_PROFILE_QUALITY_BLOCKED"

        market_file.quality_status = "passed"
        session.flush()
        assert resolver.resolve(**{**request, "trigger_price": 999.0}).blocked_code == "SIGNAL_TRIGGER_PRICE_MISMATCH"


@pytest.mark.parametrize("quality_status", ["warning", "failed", "unchecked"])
def test_historical_resolver_fail_closes_every_non_passed_quality(tmp_path: Path, quality_status: str) -> None:
    from app.services.signal_lineage import SignalFormalLineageResolver

    factory = _session_factory()
    bar_end = datetime(2026, 7, 10, 1, 30, tzinfo=UTC)
    with factory() as session:
        market_file = _seed_profile_asset(session, tmp_path, bar_end=bar_end)
        market_file.quality_status = quality_status
        session.commit()

        result = SignalFormalLineageResolver(session, project_root=tmp_path).resolve(
            profile_id="intraday_research_v1",
            symbol="jm",
            continuous_contract="JM.MAIN",
            actual_contract="JM2609",
            period="15m",
            dominant_mapping_date=date(2026, 7, 10),
            bar_start=bar_end - timedelta(minutes=15),
            bar_end=bar_end,
            trigger_price=1234.5,
            source_mode="jm_v1b_historical_replay",
            confirmation={"confirmation_mode": "historical_canonical"},
        )

        assert result.blocked_code == "SIGNAL_PROFILE_QUALITY_BLOCKED"


def test_historical_resolver_blocks_missing_wrong_profile_binding_and_range(tmp_path: Path) -> None:
    from app.services.signal_lineage import SignalFormalLineageResolver

    factory = _session_factory()
    bar_end = datetime(2026, 7, 10, 1, 30, tzinfo=UTC)
    with factory() as session:
        market_file = _seed_profile_asset(session, tmp_path, bar_end=bar_end)
        session.commit()
        resolver = SignalFormalLineageResolver(session, project_root=tmp_path)
        request = {
            "profile_id": "intraday_research_v1",
            "symbol": "jm",
            "continuous_contract": "JM.MAIN",
            "actual_contract": "JM2609",
            "period": "15m",
            "dominant_mapping_date": date(2026, 7, 10),
            "bar_start": bar_end - timedelta(minutes=15),
            "bar_end": bar_end,
            "trigger_price": 1234.5,
            "source_mode": "jm_v1b_historical_replay",
            "confirmation": {"confirmation_mode": "historical_canonical"},
        }

        assert resolver.resolve(**{**request, "profile_id": "unknown_profile"}).blocked_code == "SIGNAL_PROFILE_NOT_FOUND"

        binding = session.scalar(select(ProfileActiveBinding))
        assert binding is not None
        binding.binding_status = "retired"
        session.flush()
        assert resolver.resolve(**request).blocked_code == "SIGNAL_PROFILE_BINDING_MISSING"

        binding.binding_status = "active"
        market_file.end_time = bar_end - timedelta(minutes=1)
        session.flush()
        assert resolver.resolve(**request).blocked_code == "SIGNAL_PROFILE_RANGE_NOT_COVERED"


def test_live_resolver_verifies_confirmed_row_identity_revision_and_close(tmp_path: Path) -> None:
    from app.services.signal_lineage import SignalFormalLineageResolver

    factory = _session_factory()
    bar_end = datetime(2026, 7, 10, 1, 30, tzinfo=UTC)
    with factory() as session:
        market_file = _seed_profile_asset(session, tmp_path, bar_end=bar_end)
        live_bar = LiveAggregatedBar(
            provider="rqdata",
            instrument_symbol="jm",
            contract_code="JM2609",
            exchange_code="DCE",
            period="15m",
            source_period="1m",
            source_mode="live_1m_sequential_bucket",
            bar_datetime=bar_end,
            trading_day=bar_end.date(),
            source_start_datetime=bar_end - timedelta(minutes=14),
            source_end_datetime=bar_end,
            source_bar_count=15,
            expected_bar_count=15,
            open=1230,
            high=1236,
            low=1228,
            close=1234.5,
            volume=100,
            open_interest=1000,
            turnover=123450,
            bar_status="confirmed",
            quality_status="passed",
            confirmed_at=bar_end + timedelta(seconds=1),
            revision=3,
        )
        session.add(live_bar)
        session.commit()
        request = {
            "profile_id": "intraday_research_v1",
            "symbol": "jm",
            "continuous_contract": "JM.MAIN",
            "actual_contract": "JM2609",
            "period": "15m",
            "dominant_mapping_date": date(2026, 7, 10),
            "bar_start": bar_end - timedelta(minutes=15),
            "bar_end": bar_end,
            "trigger_price": 1234.5,
            "source_mode": "live_confirmed",
            "confirmation": {
                "confirmation_mode": "live_confirmed",
                "bar_status": "confirmed",
                "live_bar_id": live_bar.id,
                "live_bar_revision": 3,
                "confirmed_at": (bar_end + timedelta(seconds=1)).isoformat(),
            },
            "historical_context": {
                "status": "ready",
                "historical_context_file_id": market_file.id,
                "historical_context_data_version": market_file.data_version,
                "historical_context_file_checksum": market_file.checksum,
                "historical_context_hash": historical_context_hash(
                    pd.read_parquet(market_file.file_path).to_dict("records")
                ),
                "historical_context_bar_count": 1,
                "historical_context_start": bar_end.replace(tzinfo=None).isoformat(),
                "historical_context_end": bar_end.replace(tzinfo=None).isoformat(),
                "actual_contract": "JM2609",
            },
        }
        resolver = SignalFormalLineageResolver(session, project_root=tmp_path)

        assert resolver.resolve(**request).blocked_code is None
        tampered = {**request["historical_context"], "historical_context_hash": "0" * 64}
        assert (
            resolver.resolve(**{**request, "historical_context": tampered}).blocked_code
            == "SIGNAL_HISTORICAL_CONTEXT_HASH_MISMATCH"
        )
        assert resolver.resolve(**{**request, "trigger_price": 999.0}).blocked_code == "SIGNAL_TRIGGER_PRICE_MISMATCH"

        request["confirmation"] = {**request["confirmation"], "live_bar_revision": 2}
        assert resolver.resolve(**request).blocked_code == "SIGNAL_LIVE_BAR_IDENTITY_MISMATCH"

        live_bar.bar_status = "forming"
        session.flush()
        assert resolver.resolve(**{**request, "confirmation": {**request["confirmation"], "live_bar_revision": 3}}).blocked_code == "SIGNAL_BAR_NOT_CONFIRMED"


@pytest.mark.parametrize("field,value", [("provider", "rqdata"), ("data_role", "primary"), ("allow_warning_quality", True)])
def test_formal_signal_request_rejects_client_data_selection(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match="signal_formal_data_selection_forbidden"):
        SignalScanRequest.model_validate({"symbols": ["jm"], "periods": ["15m"], field: value})


def test_research_scan_never_writes_formal_event() -> None:
    factory = _session_factory()
    with factory() as session:
        task = _research_task(session)
        signal = _signal(_formal_lineage(source_mode="historical_scan"))
        signal.task_no = task.task_no
        session.add(signal)
        session.flush()

        assert record_signal_scan_event(session, signal, SIGNAL_CREATED, task) is None
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0


def test_formal_scanner_rejects_profile_and_mapping_selected_request() -> None:
    from app.signal.scanner import create_signal_scan_task

    factory = _session_factory()
    with factory() as session, pytest.raises(
        ValidationError,
        match="signal_formal_data_selection_forbidden",
    ):
        create_signal_scan_task(
            session,
            {
                "watchlist_code": "black",
                "symbols": ["jm"],
                "periods": ["15m"],
                "profile_id": "intraday_research_v1",
                "research_only": False,
            },
        )


def test_formal_scanner_old_profile_execution_contract_is_retired() -> None:
    with pytest.raises(ValidationError, match="signal_formal_data_selection_forbidden"):
        SignalScanRequest.model_validate(
            {
                "watchlist_code": "black",
                "symbols": ["jm"],
                "periods": ["5m"],
                "profile_id": "intraday_research_v1",
            }
        )


def test_live_reader_exposes_server_bar_identity_for_lineage() -> None:
    factory = _session_factory()
    bar_end = datetime(2026, 7, 10, 1, 30, tzinfo=UTC)
    with factory() as session:
        row = LiveAggregatedBar(
            provider="rqdata",
            instrument_symbol="jm",
            contract_code="JM2609",
            exchange_code="DCE",
            period="15m",
            source_period="1m",
            source_mode="live_1m_sequential_bucket",
            bar_datetime=bar_end,
            trading_day=bar_end.date(),
            source_start_datetime=bar_end - timedelta(minutes=14),
            source_end_datetime=bar_end,
            source_bar_count=15,
            expected_bar_count=15,
            open=1230,
            high=1236,
            low=1228,
            close=1234.5,
            volume=100,
            open_interest=1000,
            turnover=123450,
            bar_status="confirmed",
            quality_status="passed",
            confirmed_at=bar_end + timedelta(seconds=1),
            revision=3,
        )
        session.add(row)
        session.commit()

        response = LiveMarketReader(session).get_bars(
            symbol="jm",
            contract="JM2609",
            period="15m",
            start=None,
            end=None,
            provider="rqdata",
            source_mode="live_1m_sequential_bucket",
            limit=10,
        )

        assert response.bars[0]["live_bar_id"] == row.id
        assert response.bars[0]["revision"] == 3
        assert response.bars[0]["confirmed_at"] == "2026-07-10T01:30:01"


def test_review_marks_legacy_backtest_trade_lineage_unavailable(tmp_path: Path) -> None:
    from app.services.review_center import create_or_get_backtest_trade_review
    from app.services.review_lineage import load_review_bars

    factory = _session_factory()
    bar_end = datetime(2026, 7, 10, 1, 30, tzinfo=UTC)
    with factory() as session:
        market_file = _seed_profile_asset(session, tmp_path, bar_end=bar_end)
        trade = _seed_backtest_trade(session, market_file=market_file, bar_end=bar_end)
        session.commit()

        note = create_or_get_backtest_trade_review(session, trade.id)
        assert note.extra["lineage_status"] == "unavailable"
        assert note.extra["lineage_blocked_reason"] == "REVIEW_LINEAGE_UNAVAILABLE"
        with pytest.raises(ValueError, match="REVIEW_LINEAGE_UNAVAILABLE"):
            load_review_bars(session, note, project_root=tmp_path)


@pytest.mark.parametrize("source_type", ["strategy_signal", "signal_event"])
def test_review_supports_formal_signal_and_event_sources(source_type: str) -> None:
    from app.services.review_center import create_or_get_signal_review

    factory = _session_factory()
    with factory() as session:
        signal = _signal(_formal_lineage())
        session.add(signal)
        session.flush()
        event = record_live_signal_event(session, signal, SIGNAL_CREATED, state_key="review-source")
        assert event is not None

        source_id = signal.id if source_type == "strategy_signal" else event.id
        note = create_or_get_signal_review(session, source_type=source_type, source_id=source_id)

        assert note.source_type == source_type
        assert note.source_id == source_id
        assert note.extra["lineage_status"] == "ready"
        assert note.extra["formal_lineage"]["primary"]["market_data_file_id"] == 42
        duplicate = create_or_get_signal_review(session, source_type=source_type, source_id=source_id)
        assert duplicate.id == note.id


def test_review_api_exposes_source_lineage_and_exact_bars(tmp_path: Path) -> None:
    factory = _session_factory()
    bar_end = datetime(2026, 7, 10, 1, 30, tzinfo=UTC)
    with factory() as session:
        market_file = _seed_profile_asset(session, tmp_path, bar_end=bar_end)
        trade = _seed_backtest_trade(session, market_file=market_file, bar_end=bar_end)
        trade_id = trade.id
        session.commit()

    def override_get_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        created = client.post(f"/api/reviews/from-backtest-trade/{trade_id}")
        assert created.status_code == 200
        review_id = created.json()["id"]

        lineage = client.get(f"/api/reviews/lineage/backtest_trade/{trade_id}")
        assert lineage.status_code == 422
        assert lineage.json()["detail"]["code"] == "REVIEW_LINEAGE_UNAVAILABLE"

        bars = client.get(f"/api/reviews/{review_id}/bars")
        assert bars.status_code == 422
        assert bars.json()["detail"]["code"] == "REVIEW_LINEAGE_UNAVAILABLE"
    finally:
        app.dependency_overrides.clear()


def test_review_api_creates_signal_and_event_reviews() -> None:
    factory = _session_factory()
    with factory() as session:
        signal = _signal(_formal_lineage())
        session.add(signal)
        session.flush()
        event = record_live_signal_event(session, signal, SIGNAL_CREATED, state_key="api-review")
        assert event is not None
        signal_id, event_id = signal.id, event.id
        session.commit()

    def override_get_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        signal_response = client.post(f"/api/reviews/from-strategy-signal/{signal_id}")
        event_response = client.post(f"/api/reviews/from-signal-event/{event_id}")
        assert signal_response.status_code == 200
        assert event_response.status_code == 200
        assert signal_response.json()["source_type"] == "strategy_signal"
        assert event_response.json()["source_type"] == "signal_event"
    finally:
        app.dependency_overrides.clear()


def _seed_backtest_trade(
    session: Session,
    *,
    market_file: MarketDataFile,
    bar_end: datetime,
) -> BacktestTradeModel:
    task = BacktestTask(
        task_no="BT-review-lineage",
        profile_id="intraday_research_v1",
        market_data_file_id=market_file.id,
        binding_snapshot={},
        request_payload={},
        result_payload={},
    )
    session.add(task)
    session.flush()
    binding_snapshot = {
        "schema_version": "backtest_binding_snapshot_v1",
        "resolver_name": "ProfileLineageResolver",
        "resolver_contract_version": "backtest_profile_v1",
        "quality_policy": "passed_only",
        "primary": {
            "profile_id": "intraday_research_v1",
            "market_data_file_id": market_file.id,
            "instrument_symbol": "jm",
            "contract_code": "JM2609",
            "period": "15m",
            "data_version": market_file.data_version,
            "provider": "rqdata",
            "data_role": "primary",
            "quality_status": "passed",
            "coverage_start": market_file.start_time.isoformat(),
            "coverage_end": market_file.end_time.isoformat(),
            "checksum": market_file.checksum,
        },
        "auxiliary": {},
    }
    report = BacktestReportModel(
        task_id=task.id,
        task_no=task.task_no,
        report_no="RPT-review-lineage",
        template_name="default",
        strategy_code="jm_v1b_daily_direction_fast_entry",
        strategy_version="v1b.0",
        symbol="jm",
        contract="JM2609",
        period="15m",
        profile_id="intraday_research_v1",
        market_data_file_id=market_file.id,
        binding_snapshot=deepcopy(binding_snapshot),
        status="completed",
        summary={"quality_status": {"status": "passed"}},
    )
    session.add(report)
    session.flush()
    trade = BacktestTradeModel(
        report_id=report.id,
        trade_no="TRD-review-lineage",
        symbol="jm",
        contract="JM2609",
        direction="long",
        open_time=bar_end,
        open_price=1234.5,
        close_time=bar_end,
        close_price=1234.5,
        volume=1,
        turnover=1234.5,
        commission=0,
        slippage=0,
        gross_pnl=0,
        net_pnl=0,
        return_pct=0,
        holding_bars=1,
        entry_reason="formal entry",
        exit_reason="formal exit",
        raw_payload={"entry_interval": "15m"},
    )
    session.add(trade)
    session.flush()
    return trade


def _research_task(session: Session):
    from app.models.signal import SignalScanTask

    task = SignalScanTask(
        task_no="SIG-RESEARCH-1",
        status="completed",
        progress=100.0,
        watchlist_code="black",
        periods=["15m"],
        total_items=1,
        completed_items=1,
        request_payload={"research_only": True},
        result_payload={},
    )
    session.add(task)
    session.flush()
    return task


def _seed_profile_asset(session: Session, tmp_path: Path, *, bar_end: datetime) -> MarketDataFile:
    path = tmp_path / "canonical" / "bars" / "jm2609_15m.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "symbol": "jm",
                "contract": "JM2609",
                "exchange": "DCE",
                "datetime": bar_end.replace(tzinfo=None),
                "trading_day": bar_end.date(),
                "open": 1230.0,
                "high": 1236.0,
                "low": 1228.0,
                "close": 1234.5,
                "volume": 100,
                "open_interest": 1000,
                "turnover": 123450,
                "period": "15m",
                "provider": "rqdata",
                "data_version": "jm2609_15m_passed",
                "source_interval": "1m",
            }
        ]
    ).to_parquet(path, index=False)
    session.add(
        DataProfile(
            profile_id="intraday_research_v1",
            label="Intraday",
            description="test",
            contract_roles=["actual_contract"],
            periods=["15m"],
            quality_policy="passed_only",
            provider="rqdata",
            is_active=True,
        )
    )
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="jm",
        contract_code="JM2609",
        period="15m",
        start_time=bar_end - timedelta(minutes=15),
        end_time=bar_end,
        file_path=str(path),
        row_count=1,
        file_size_bytes=path.stat().st_size,
        checksum=sha256_file(path),
        data_version="jm2609_15m_passed",
        data_role="primary",
        quality_status="passed",
    )
    session.add(market_file)
    session.flush()
    session.add(
        ProfileActiveBinding(
            profile_id="intraday_research_v1",
            instrument_symbol="jm",
            contract_code="JM2609",
            contract_role="actual_contract",
            period="15m",
            data_version=market_file.data_version,
            market_data_file_id=market_file.id,
            binding_status="active",
            activated_at=bar_end - timedelta(days=1),
        )
    )
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=date(2026, 7, 10),
            rank=1,
            contract_code="JM2609",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="mapping-v1",
        )
    )
    session.flush()
    return market_file


def _seed_formal_scan_asset(session: Session, tmp_path: Path) -> None:
    session.add(Watchlist(code="black", name="Black", category="test"))
    session.add(
        WatchlistItem(
            watchlist_code="black",
            symbol="jm",
            name="焦煤",
            exchange_code="DCE",
            default_contract="JM.MAIN",
            is_active=True,
        )
    )
    start = datetime(2026, 7, 10, 0, 30)
    closes = [100, 99.8, 99.6, 99.4, 99.2, 99.3, 99.5, 99.8, 101.5, 101.8, 102.0, 102.2, 102.4]
    rows = []
    previous = closes[0]
    for index, close in enumerate(closes):
        timestamp = start + timedelta(minutes=(index + 1) * 5)
        rows.append(
            {
                "symbol": "jm",
                "contract": "JM2609",
                "exchange": "DCE",
                "datetime": timestamp,
                "trading_day": timestamp.date(),
                "open": previous,
                "high": max(previous, close) + 0.2,
                "low": min(previous, close) - 0.2,
                "close": close,
                "volume": 300 if index == 7 else 100,
                "open_interest": 1000 + index,
                "turnover": 1000,
                "period": "5m",
                "provider": "rqdata",
                "data_version": "formal-scan-v1",
                "source_interval": "1m",
            }
        )
        previous = close
    path = tmp_path / "canonical" / "bars" / "jm2609_5m.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    session.add(
        DataProfile(
            profile_id="intraday_research_v1",
            label="Intraday",
            description="test",
            contract_roles=["actual_contract"],
            periods=["5m", "15m"],
            quality_policy="passed_only",
            provider="rqdata",
            is_active=True,
        )
    )
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="jm",
        contract_code="JM2609",
        period="5m",
        start_time=rows[0]["datetime"],
        end_time=rows[-1]["datetime"],
        file_path=str(path),
        row_count=len(rows),
        file_size_bytes=path.stat().st_size,
        checksum="b" * 64,
        data_version="formal-scan-v1",
        data_role="primary",
        quality_status="passed",
    )
    session.add(market_file)
    session.flush()
    higher_rows = []
    for index in range(5):
        timestamp = start + timedelta(minutes=(index + 1) * 15)
        close = 100 + index
        higher_rows.append(
            {
                "symbol": "jm",
                "contract": "JM2609",
                "exchange": "DCE",
                "datetime": timestamp,
                "trading_day": timestamp.date(),
                "open": close - 0.5,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 300,
                "open_interest": 1000 + index,
                "turnover": 1000,
                "period": "15m",
                "provider": "rqdata",
                "data_version": "formal-scan-15m-v1",
                "source_interval": "1m",
            }
        )
    higher_path = tmp_path / "canonical" / "bars" / "jm2609_15m.parquet"
    pd.DataFrame(higher_rows).to_parquet(higher_path, index=False)
    higher_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="jm",
        contract_code="JM2609",
        period="15m",
        start_time=higher_rows[0]["datetime"],
        end_time=higher_rows[-1]["datetime"],
        file_path=str(higher_path),
        row_count=len(higher_rows),
        file_size_bytes=higher_path.stat().st_size,
        checksum="c" * 64,
        data_version="formal-scan-15m-v1",
        data_role="primary",
        quality_status="passed",
    )
    session.add(higher_file)
    session.flush()
    session.add(
        ProfileActiveBinding(
            profile_id="intraday_research_v1",
            instrument_symbol="jm",
            contract_code="JM2609",
            contract_role="actual_contract",
            period="5m",
            data_version="formal-scan-v1",
            market_data_file_id=market_file.id,
            binding_status="active",
            activated_at=start - timedelta(days=1),
        )
    )
    session.add(
        ProfileActiveBinding(
            profile_id="intraday_research_v1",
            instrument_symbol="jm",
            contract_code="JM2609",
            contract_role="actual_contract",
            period="15m",
            data_version=higher_file.data_version,
            market_data_file_id=higher_file.id,
            binding_status="active",
            activated_at=start - timedelta(days=1),
        )
    )
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=rows[-1]["trading_day"],
            rank=1,
            contract_code="JM2609",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="mapping-v1",
        )
    )
    session.flush()


def _item(*, lineage: dict | None) -> LiveSignalEvaluationItem:
    source = {
        "entry_data_source": "live_db_actual_contract",
        "daily_data_source": "active_standard_parquet_continuous",
        "provider": "rqdata",
        "source_mode": "live_1m_sequential_bucket",
        "preview_only": True,
        "writes_signal_event": False,
        "sends_notification": False,
        "auto_order": False,
        "bar_status": "confirmed",
    }
    if lineage is not None:
        source["formal_lineage"] = lineage
    return LiveSignalEvaluationItem(
        strategy_code="jm_v1b_daily_direction_fast_entry",
        strategy_version="v1.0.0",
        symbol="jm",
        contract="JM2609",
        continuous_contract="JM.MAIN",
        actual_contract="JM2609",
        dominant_mapping_date="2026-07-10",
        entry_interval="15m",
        evaluated_at="2026-07-10T01:30:01+00:00",
        bar_time="2026-07-10T01:30:00+00:00",
        bar_end="2026-07-10T01:30:00+00:00",
        trigger_price=1234.5,
        direction="long",
        status="entry_signal",
        daily_direction="long",
        entry_reason="confirmed_test_entry",
        stop_loss_price=1214.5,
        quality={"status": "passed", "live": {"status": "passed"}, "daily": {"status": "passed"}},
        warnings=[],
        reasons=["confirmed_test_entry"],
        source=source,
    )


def _response(item: LiveSignalEvaluationItem) -> LiveSignalEvaluationResponse:
    return LiveSignalEvaluationResponse(
        strategy_code="jm_v1b_daily_direction_fast_entry",
        strategy_version="v1.0.0",
        symbol="jm",
        contract="JM2609",
        continuous_contract="JM.MAIN",
        actual_contract="JM2609",
        dominant_mapping_date="2026-07-10",
        evaluated_at="2026-07-10T01:30:01+00:00",
        results=[item],
        quality_summary={"status": "passed", "preview_only": True},
        message=None,
    )
