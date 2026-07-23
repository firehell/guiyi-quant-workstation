from copy import deepcopy

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.signal import SignalEvent, StrategySignal
from app.schemas.signal import LiveSignalEvaluationItem, LiveSignalEvaluationResponse
from app.services.live_signal_events import LiveSignalEventService


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_same_confirmed_bar_writes_one_signal_and_one_event() -> None:
    factory = _session_factory()
    response = _response(_item())
    with factory() as session:
        first = LiveSignalEventService(session).persist(response)
        second = LiveSignalEventService(session).persist(response)

        assert first.created == 1
        assert second.unchanged == 1
        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 1
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 1
        event = session.scalar(select(SignalEvent))
        assert event is not None
        assert event.source_mode == "live_confirmed"
        assert event.actual_contract == "JM2609"
        assert event.data_role == "primary"
        assert event.quality_status["status"] == "passed"
        assert event.payload["live_observation"]["observation_only"] is True
        assert event.payload["live_observation"]["auto_order"] is False


def test_writer_does_not_commit_and_caller_can_rollback() -> None:
    factory = _session_factory()
    with factory() as session:
        result = LiveSignalEventService(session).persist(_response(_item()))
        assert result.created == 1
        session.rollback()

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 0
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0


def test_same_bar_revision_writes_one_changed_event() -> None:
    factory = _session_factory()
    original = _item()
    revised = original.model_copy(
        update={
            "trigger_price": 1235.0,
            "stop_loss_price": 1215.0,
            "source": {**original.source, "formal_lineage": _formal_lineage(trigger_price=1235.0, revision=2)},
        }
    )
    with factory() as session:
        LiveSignalEventService(session).persist(_response(original))
        result = LiveSignalEventService(session).persist(_response(revised))

        assert result.changed == 1
        events = list(session.scalars(select(SignalEvent).order_by(SignalEvent.id)))
        assert [event.event_type for event in events] == ["signal_created", "signal_changed"]
        assert events[1].trigger_price == 1235.0
        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 1


def test_revision_only_change_writes_signal_changed_event() -> None:
    factory = _session_factory()
    original = _item()
    revised = original.model_copy(
        update={"source": {**original.source, "formal_lineage": _formal_lineage(revision=2)}}
    )
    with factory() as session:
        LiveSignalEventService(session).persist(_response(original))
        result = LiveSignalEventService(session).persist(_response(revised))

        assert result.changed == 1
        events = list(session.scalars(select(SignalEvent).order_by(SignalEvent.id)))
        assert [event.event_type for event in events] == ["signal_created", "signal_changed"]
        assert events[1].payload["formal_lineage"]["bar"]["live_bar_revision"] == 2


def test_writer_blocks_warning_partial_main_and_missing_trigger() -> None:
    factory = _session_factory()
    base = _item().model_dump()
    warning = LiveSignalEvaluationItem(**{**deepcopy(base), "quality": {"status": "warning"}})
    partial = LiveSignalEvaluationItem(**{**deepcopy(base), "warnings": ["live_partial_bucket"]})
    main = LiveSignalEvaluationItem(**{**deepcopy(base), "actual_contract": "JM.MAIN", "contract": "JM.MAIN"})
    missing_trigger = LiveSignalEvaluationItem(**{**deepcopy(base), "trigger_price": None})

    with factory() as session:
        result = LiveSignalEventService(session).persist(_response(warning, partial, main, missing_trigger))
        assert result.blocked == 4
        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 0
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0


def test_writer_blocks_source_without_confirmed_bar_evidence() -> None:
    factory = _session_factory()
    item = _item().model_copy(update={"source": {**_item().source, "bar_status": "forming"}})
    with factory() as session:
        result = LiveSignalEventService(session).persist(_response(item))
        assert result.blocked == 1
        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 0


def _item() -> LiveSignalEvaluationItem:
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
        source={
            "entry_data_source": "live_db_actual_contract",
            "daily_data_source": "active_standard_parquet_continuous",
            "provider": "rqdata",
            "source_mode": "live_1m_sequential_bucket",
            "preview_only": True,
            "writes_signal_event": False,
            "sends_notification": False,
            "auto_order": False,
            "bar_status": "confirmed",
            "formal_lineage": _formal_lineage(),
        },
    )


def _formal_lineage(*, trigger_price: float = 1234.5, revision: int = 1) -> dict:
    return {
        "schema_version": "signal_review_lineage_v1",
        "resolver_name": "ProfileLineageResolver",
        "resolver_contract_version": "signal_profile_v1",
        "quality_policy": "passed_only",
        "source_mode": "live_confirmed",
        "primary": {
            "profile_id": "live_observation_v1",
            "market_data_file_id": 42,
            "instrument_symbol": "jm",
            "contract_code": "JM2609",
            "period": "15m",
            "data_version": "jm2609-15m-v1",
            "provider": "rqdata",
            "data_role": "primary",
            "quality_status": "passed",
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
            "trigger_price": trigger_price,
            "confirmation_mode": "live_confirmed",
            "bar_status": "confirmed",
            "live_bar_id": 101,
            "live_bar_revision": revision,
            "confirmed_at": "2026-07-10T01:30:01+00:00",
        },
    }


def _response(*items: LiveSignalEvaluationItem) -> LiveSignalEvaluationResponse:
    return LiveSignalEvaluationResponse(
        strategy_code="jm_v1b_daily_direction_fast_entry",
        strategy_version="v1.0.0",
        symbol="jm",
        contract="JM2609",
        continuous_contract="JM.MAIN",
        actual_contract="JM2609",
        dominant_mapping_date="2026-07-10",
        evaluated_at="2026-07-10T01:30:01+00:00",
        results=list(items),
        quality_summary={"status": "passed", "preview_only": True},
        message=None,
    )
