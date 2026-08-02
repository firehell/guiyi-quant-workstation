from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.data_core.bar_schema import CanonicalBar
from app.data_core.contracts import (
    BarFrequency,
    BarQuery,
    BarsResult,
    DatasetKey,
    DatasetKind,
)
from app.db.base import Base
from app.models.review import ReviewNote
from app.models.signal import SignalEvent, SignalNotification, SignalScanTask, StrategySignal
from app.schemas.signal import SignalScanRequest


START = datetime(2026, 7, 10, 0, 30, tzinfo=UTC)
END = datetime(2026, 7, 10, 2, 0, tzinfo=UTC)


class FakeCanonicalMarketData:
    def __init__(self, *, manifest_suffix: str = "a") -> None:
        self.queries: list[BarQuery] = []
        self.manifest_suffix = manifest_suffix

    def get_bars(self, query: BarQuery) -> BarsResult:
        self.queries.append(query)
        if query.frequency is BarFrequency.M5:
            closes = [
                "100",
                "99.8",
                "99.6",
                "99.4",
                "99.2",
                "99.3",
                "99.5",
                "99.8",
                "101.5",
                "101.8",
                "102.0",
                "102.2",
                "102.4",
            ]
            bars = _bars(query, minutes=5, closes=closes)
        elif query.frequency is BarFrequency.M15:
            bars = _bars(
                query,
                minutes=15,
                closes=["100", "101", "102", "103", "104"],
            )
        else:
            raise AssertionError(f"unexpected canonical query: {query.frequency}")
        source = DatasetKey(
            provider="rqdata",
            dataset_kind=query.dataset_kind,
            symbol=query.symbol,
            contract_or_series=query.contract_or_series or "JM2609",
            frequency=BarFrequency.M1,
            adjustment="none",
            schema_version="canonical-bar-v1",
        )
        return BarsResult(
            bars=bars,
            source_datasets=(source,),
            manifest_digests=(self.manifest_suffix * 64,),
            requested_window=(query.start, query.end),
            data_type=query.dataset_kind,
            derived_frequency=query.frequency,
            source_data_versions=(f"canonical-{query.frequency.value}-v1",),
        )


def test_formal_signal_request_requires_explicit_actual_dominant_identity() -> None:
    request = SignalScanRequest.model_validate(_formal_request())

    assert request.dataset_kind is DatasetKind.ACTUAL_DOMINANT
    assert request.instrument_symbol == "jm"
    assert request.contract_or_series == "JM2609"
    assert request.start == START
    assert request.end == END
    assert request.mode == "scan"

    with pytest.raises(ValidationError, match="SIGNAL_FORMAL_ACTUAL_DOMINANT_REQUIRED"):
        SignalScanRequest.model_validate(
            {**_formal_request(), "dataset_kind": "continuous", "contract_or_series": "JM.MAIN"}
        )
    with pytest.raises(ValidationError):
        SignalScanRequest.model_validate({**_formal_request(), "profile_id": "legacy"})


def test_formal_scan_uses_canonical_service_and_deep_copies_identity() -> None:
    from app.signal.scanner import SignalScanner, create_signal_scan_task

    factory = _session_factory()
    canonical = FakeCanonicalMarketData()
    with factory() as session:
        task = create_signal_scan_task(
            session,
            {**_formal_request(), "strategy_version": "v-test"},
        )
        session.commit()

        result = SignalScanner(session, canonical_market_data=canonical).run(task.id)
        signal = session.scalar(select(StrategySignal))
        event = session.scalar(select(SignalEvent))

        assert result["created"] == 1
        assert [query.frequency for query in canonical.queries] == [
            BarFrequency.M5,
            BarFrequency.M15,
        ]
        assert signal is not None and event is not None
        assert signal.profile_id is None
        assert signal.market_data_file_id is None
        assert event.profile_id is None
        assert event.market_data_file_id is None
        assert signal.research_contract is False
        assert signal.strategy_version == "v-test"
        assert event.strategy_version == "v-test"
        assert signal.actual_contract == "JM2609"
        assert signal.continuous_contract == "JM.MAIN"
        identity = signal.features["input_identity"]
        assert identity["schema_version"] == "canonical_consumer_input_v1"
        assert identity["request"]["dataset_kind"] == "actual_dominant"
        assert event.payload["input_identity"] == identity
        assert event.payload["input_identity"] is not identity
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0


def test_formal_strategy_code_cannot_select_legacy_research_reader() -> None:
    from app.signal.jm_v1b import JM_V1B_STRATEGY_CODE
    from app.signal.scanner import SignalScanner, create_signal_scan_task

    factory = _session_factory()
    with factory() as session:
        task = create_signal_scan_task(
            session,
            {**_formal_request(), "strategy_code": JM_V1B_STRATEGY_CODE},
        )

        targets = SignalScanner(
            session,
            canonical_market_data=FakeCanonicalMarketData(),
        )._targets(task.request_payload)

        assert [(item.contract, item.period) for item in targets] == [("JM2609", "5m")]


@pytest.mark.parametrize("mode", ["replay", "repair", "recompute"])
def test_non_scan_modes_evaluate_without_signal_side_effects(mode: str) -> None:
    from app.signal.scanner import SignalScanner, create_signal_scan_task

    factory = _session_factory()
    canonical = FakeCanonicalMarketData()
    with factory() as session:
        task = create_signal_scan_task(session, {**_formal_request(), "mode": mode})
        session.commit()

        result = SignalScanner(session, canonical_market_data=canonical).run(task.id)

        assert result["evaluations"]
        assert result["evaluations"][0]["input_identity"]["schema_version"] == "canonical_consumer_input_v1"
        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 0
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0


@pytest.mark.parametrize("mode", ["replay", "repair", "recompute"])
def test_non_scan_modes_are_rejected_by_event_writer(mode: str) -> None:
    from app.signal.events import SIGNAL_CREATED, record_signal_scan_event

    factory = _session_factory()
    with factory() as session:
        task = SignalScanTask(
            task_no=f"SIG-{mode}",
            status="running",
            watchlist_code="black",
            periods=["5m"],
            request_payload={"mode": mode, "research_only": False},
            result_payload={},
        )
        signal = _legacy_signal()
        signal.task_no = task.task_no
        session.add_all([task, signal])
        session.flush()

        assert record_signal_scan_event(session, signal, SIGNAL_CREATED, task) is None
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0


def test_continuous_preview_cannot_persist_formal_event() -> None:
    from app.signal.events import SIGNAL_CREATED, record_signal_scan_event

    factory = _session_factory()
    with factory() as session:
        task = SignalScanTask(
            task_no="SIG-CONTINUOUS",
            status="running",
            watchlist_code="black",
            periods=["5m"],
            request_payload={
                "mode": "scan",
                "research_only": False,
                "dataset_kind": "continuous",
            },
            result_payload={},
        )
        signal = _legacy_signal()
        signal.features = {
            "input_identity": {
                "schema_version": "canonical_consumer_input_v1",
                "request": {"dataset_kind": "continuous"},
            }
        }
        session.add_all([task, signal])
        session.flush()

        assert record_signal_scan_event(session, signal, SIGNAL_CREATED, task) is None
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0


def test_review_reconstructs_canonical_query_and_detects_identity_drift() -> None:
    from app.services.review_lineage import ReviewLineageError, load_review_bars

    factory = _session_factory()
    canonical = FakeCanonicalMarketData()
    with factory() as session:
        note = _canonical_review_note(session, canonical)

        response = load_review_bars(session, note, market_data=canonical)

        assert response["lineage"]["input_digest"] == note.extra["formal_lineage"]["input_digest"]
        assert response["lineage"]["strategy_version"] == "v0"
        assert response["bars"][-1]["contract"] == "JM2609"
        assert canonical.queries[-1] == BarQuery(
            dataset_kind=DatasetKind.ACTUAL_DOMINANT,
            symbol="jm",
            contract_or_series="JM2609",
            frequency=BarFrequency.M5,
            start=START,
            end=END,
        )

        drifted = FakeCanonicalMarketData(manifest_suffix="f")
        with pytest.raises(ReviewLineageError, match="REVIEW_EXACT_BARS_IDENTITY_CHANGED"):
            load_review_bars(session, note, market_data=drifted)


def test_review_legacy_historical_row_is_stably_unavailable() -> None:
    from app.services.review_lineage import ReviewLineageError, resolve_review_source_lineage

    factory = _session_factory()
    with factory() as session:
        signal = _legacy_signal()
        session.add(signal)
        session.flush()

        with pytest.raises(ReviewLineageError, match="REVIEW_LINEAGE_UNAVAILABLE"):
            resolve_review_source_lineage(
                session,
                source_type="strategy_signal",
                source_id=signal.id,
            )


def _canonical_review_note(
    session: Session,
    canonical: FakeCanonicalMarketData,
) -> ReviewNote:
    from app.data_core.consumer_identity import build_canonical_consumer_input

    query = BarQuery(
        dataset_kind=DatasetKind.ACTUAL_DOMINANT,
        symbol="jm",
        contract_or_series="JM2609",
        frequency=BarFrequency.M5,
        start=START,
        end=END,
    )
    identity = build_canonical_consumer_input(
        query,
        canonical.get_bars(query),
        strategy_input_version="su_bing_ema21:v0:test-input",
    ).to_snapshot()
    lineage = {
        "schema_version": "review_canonical_lineage_v1",
        "source_type": "strategy_signal",
        "source_id": 1,
        "strategy_version": "v0",
        "input_digest": identity["digest"],
        "input_identity": deepcopy(identity),
    }
    note = ReviewNote(
        source_type="strategy_signal",
        source_id=1,
        symbol="jm",
        contract="JM2609",
        period="5m",
        strategy_name="su_bing_ema21",
        strategy_version="v0",
        mistake_tags=[],
        rule_tags=[],
        emotion_tags=[],
        screenshot_paths=[],
        extra={"lineage_status": "ready", "formal_lineage": lineage},
    )
    session.add(note)
    session.flush()
    return note


def _formal_request() -> dict[str, Any]:
    return {
        "dataset_kind": "actual_dominant",
        "instrument_symbol": "jm",
        "contract_or_series": "JM2609",
        "periods": ["5m"],
        "start": START.isoformat(),
        "end": END.isoformat(),
        "mode": "scan",
        "min_score_bucket": 0,
        "strategy_params": {
            "ema_period": 3,
            "macd_fast": 2,
            "macd_slow": 4,
            "macd_signal": 2,
            "atr_period": 3,
            "breakout_lookback": 3,
            "confirmation_bars": 2,
            "volume_ratio_intraday": 1.5,
            "zero_axis_atr_threshold": 10,
            "max_distance_from_ema_atr": 99,
            "confluence_threshold": 3,
            "volume_lookback": 3,
            "macd_cross_lookback": 5,
            "chop_cross_threshold": 99,
            "rapid_move_atr_threshold": 99,
        },
        "run_inline": True,
    }


def _bars(
    query: BarQuery,
    *,
    minutes: int,
    closes: list[str],
) -> tuple[CanonicalBar, ...]:
    rows: list[CanonicalBar] = []
    previous = Decimal(closes[0])
    for index, close_text in enumerate(closes):
        close = Decimal(close_text)
        bar_end = START + timedelta(minutes=(index + 1) * minutes)
        rows.append(
            CanonicalBar(
                provider="rqdata",
                dataset_kind=query.dataset_kind,
                symbol=query.symbol,
                contract_or_series=query.contract_or_series or "JM2609",
                frequency=query.frequency,
                bar_end=bar_end,
                trading_day=bar_end.date(),
                open=previous,
                high=max(previous, close) + Decimal("0.2"),
                low=min(previous, close) - Decimal("0.2"),
                close=close,
                volume=Decimal(300 if index == 7 else 100),
                turnover=Decimal("1000"),
                open_interest=Decimal(1000 + index),
                adjustment="none",
                schema_version="canonical-bar-v1",
            )
        )
        previous = close
    return tuple(rows)


def _legacy_signal() -> StrategySignal:
    return StrategySignal(
        dedupe_key="legacy-historical-signal",
        strategy_name="su_bing_ema21",
        strategy_version="v0",
        symbol="jm",
        contract="JM2609",
        period="5m",
        signal_time=END,
        status="entry_signal",
        direction="long",
        current_price=100,
        features={
            "formal_lineage": {
                "schema_version": "signal_review_lineage_v1",
                "primary": {"market_data_file_id": 42},
            }
        },
        quality_status={"status": "passed"},
    )


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
