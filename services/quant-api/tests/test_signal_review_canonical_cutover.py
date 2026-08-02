from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from types import SimpleNamespace
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
from app.models.data_center import MainContractMap
from app.models.review import ReviewNote
from app.models.signal import SignalEvent, SignalNotification, SignalScanTask, StrategySignal
from app.schemas.signal import SignalScanRequest


START = datetime(2026, 7, 10, 0, 30, tzinfo=UTC)
END = datetime(2026, 7, 10, 2, 0, tzinfo=UTC)


class FakeCanonicalMarketData:
    def __init__(
        self,
        *,
        manifest_suffix: str = "a",
        manifest_suffix_by_frequency: dict[BarFrequency, str] | None = None,
    ) -> None:
        self.queries: list[BarQuery] = []
        self.manifest_suffix = manifest_suffix
        self.manifest_suffix_by_frequency = manifest_suffix_by_frequency or {}

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
            manifest_digests=(
                self.manifest_suffix_by_frequency.get(
                    query.frequency,
                    self.manifest_suffix,
                )
                * 64,
            ),
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


@pytest.mark.parametrize(
    ("strategy_code", "strategy_version"),
    [
        ("htdy_original_realtime_first_seen", "v1.0"),
        ("su_bing_ema21", "forged-version"),
        ("caller_selected_evaluator", "v0"),
    ],
)
def test_formal_signal_request_rejects_unsupported_evaluator_identity(
    strategy_code: str,
    strategy_version: str,
) -> None:
    with pytest.raises(ValidationError, match="SIGNAL_FORMAL_STRATEGY_UNSUPPORTED"):
        SignalScanRequest.model_validate(
            {
                **_formal_request(),
                "strategy_code": strategy_code,
                "strategy_version": strategy_version,
            }
        )


@pytest.mark.parametrize(
    "override",
    [
        {"risk_per_trade_pct": "0.0100001"},
        {"max_margin_usage_pct": "0.3500001"},
    ],
)
def test_formal_signal_request_enforces_existing_risk_caps(
    override: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        SignalScanRequest.model_validate({**_formal_request(), **override})


def test_formal_risk_derivation_uses_decimal_until_payload_boundary() -> None:
    from app.signal.scanner import SignalScanner

    factory = _session_factory()
    with factory() as session:
        risk = SignalScanner(session)._risk_payload(
            SimpleNamespace(
                direction="long",
                features={"atr": "1.25", "prior_low": "98.75"},
            ),
            {"symbol": "jm", "contract": "JM2609", "close": Decimal("100.10")},
            {
                "account_equity": "100000.01",
                "risk_per_trade_pct": "0.01",
                "max_margin_usage_pct": "0.35",
            },
        )

        assert isinstance(risk["entry_price"], Decimal)
        assert isinstance(risk["margin_required"], Decimal)
        assert isinstance(risk["risk_amount"], Decimal)
        assert isinstance(risk["account_equity"], Decimal)


def test_formal_scan_passes_canonical_decimal_close_to_risk_derivation() -> None:
    from app.signal.scanner import SignalScanner, create_signal_scan_task

    class DecimalBoundaryScanner(SignalScanner):
        def _risk_payload(
            self,
            snapshot: Any,
            bar: dict[str, Any],
            payload: dict[str, Any],
        ) -> dict[str, Any]:
            assert isinstance(bar["close"], Decimal)
            return super()._risk_payload(snapshot, bar, payload)

    factory = _session_factory()
    with factory() as session:
        _seed_rank1_mapping(session, known_at=START)
        task = create_signal_scan_task(session, _formal_request())
        scanner = DecimalBoundaryScanner(
            session,
            canonical_market_data=FakeCanonicalMarketData(),
        )

        scanner._scan_one(task, scanner._targets(task.request_payload)[0])


def test_formal_scan_uses_canonical_service_and_deep_copies_identity() -> None:
    from app.signal.scanner import SignalScanner, create_signal_scan_task

    factory = _session_factory()
    canonical = FakeCanonicalMarketData()
    with factory() as session:
        _seed_rank1_mapping(session, known_at=START)
        task = create_signal_scan_task(session, _formal_request())
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
        assert signal.strategy_version == "v0"
        assert event.strategy_version == "v0"
        assert signal.actual_contract == "JM2609"
        assert signal.continuous_contract == "JM.MAIN"
        assert signal.features["observation_only"] is True
        assert signal.features["not_trading_instruction"] is True
        assert signal.features["auto_order"] is False
        identity = signal.features["input_identity"]
        assert identity["schema_version"] == "canonical_consumer_input_v1"
        assert identity["request"]["dataset_kind"] == "actual_dominant"
        assert event.payload["input_identity"] == identity
        assert event.payload["input_identity"] is not identity
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0


@pytest.mark.parametrize(
    ("known_at", "error_code"),
    [
        (None, "SIGNAL_MAIN_CONTRACT_KNOWN_AT_MISSING"),
        (END + timedelta(minutes=1), "SIGNAL_MAIN_CONTRACT_KNOWN_AT_AFTER_DECISION"),
    ],
)
def test_formal_scan_validates_mapping_knowledge_before_evaluator(
    known_at: datetime | None,
    error_code: str,
) -> None:
    from app.signal.scanner import SignalScanner, create_signal_scan_task

    factory = _session_factory()
    with factory() as session:
        _seed_rank1_mapping(session, known_at=known_at)
        task = create_signal_scan_task(session, _formal_request())
        scanner = SignalScanner(session, canonical_market_data=FakeCanonicalMarketData())
        target = scanner._targets(task.request_payload)[0]

        with pytest.raises(ValueError, match=error_code):
            scanner._scan_one(task, target)

        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 0
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0


def test_formal_strategy_code_cannot_select_legacy_research_reader() -> None:
    from app.signal.jm_v1b import JM_V1B_STRATEGY_CODE
    from app.signal.scanner import create_signal_scan_task

    factory = _session_factory()
    with factory() as session:
        with pytest.raises(ValidationError, match="SIGNAL_FORMAL_STRATEGY_UNSUPPORTED"):
            create_signal_scan_task(
                session,
                {**_formal_request(), "strategy_code": JM_V1B_STRATEGY_CODE},
            )


@pytest.mark.parametrize("mode", ["replay", "repair", "recompute"])
def test_non_scan_modes_evaluate_without_signal_side_effects(mode: str) -> None:
    from app.signal.scanner import SignalScanner

    factory = _session_factory()
    canonical = FakeCanonicalMarketData()
    with factory() as session:
        _seed_rank1_mapping(session, known_at=START)

        result = SignalScanner(session, canonical_market_data=canonical).preview(
            {**_formal_request(), "mode": mode}
        )

        assert result["evaluations"]
        assert result["evaluations"][0]["input_identity"]["schema_version"] == "canonical_consumer_input_v1"
        assert session.scalar(select(func.count()).select_from(SignalScanTask)) == 0
        assert session.scalar(select(func.count()).select_from(StrategySignal)) == 0
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0


@pytest.mark.parametrize("mode", ["replay", "repair", "recompute"])
def test_non_scan_api_path_is_synchronous_and_writes_no_task_or_result(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.signals import _start_scan
    from app.signal.scanner import SignalScanner

    factory = _session_factory()
    canonical = FakeCanonicalMarketData()
    with factory() as session:
        _seed_rank1_mapping(session, known_at=START)
        request = SignalScanRequest.model_validate(
            {**_formal_request(), "mode": mode, "run_inline": False}
        )
        monkeypatch.setattr(
            SignalScanner,
            "_canonical_service",
            lambda _self: canonical,
        )

        response = _start_scan(request, session, research_only=False)

        assert response["mode"] == mode
        assert response["evaluations"]
        assert "task_no" not in response
        assert session.scalar(select(func.count()).select_from(SignalScanTask)) == 0
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


@pytest.mark.parametrize(
    "forgery",
    [
        "minimal_identity",
        "symbol_mismatch",
        "strategy_mismatch",
        "strategy_input_mismatch",
        "legacy_profile",
        "missing_safety",
        "task_auto_order",
    ],
)
def test_event_writer_rejects_forged_canonical_signal_identity(forgery: str) -> None:
    from app.signal.events import SIGNAL_CREATED, record_signal_scan_event

    factory = _session_factory()
    canonical = FakeCanonicalMarketData()
    with factory() as session:
        identity = _canonical_identity(
            canonical,
            BarFrequency.M5,
            strategy_input_version=_expected_strategy_input_version(
                _formal_request()
            ),
        )
        formal_payload = SignalScanRequest.model_validate(
            _formal_request()
        ).model_dump(mode="json")
        task = SignalScanTask(
            task_no=f"SIG-FORGED-{forgery}",
            status="running",
            watchlist_code="black",
            periods=["5m"],
            request_payload={
                **formal_payload,
                "research_only": False,
                "data_role": "primary",
            },
            result_payload={},
            profile_id=None,
            market_data_file_id=None,
        )
        signal = _canonical_signal(identity, task_no=task.task_no)
        if forgery == "minimal_identity":
            signal.features["input_identity"] = {
                "request": {"dataset_kind": "actual_dominant"}
            }
        elif forgery == "symbol_mismatch":
            signal.symbol = "rb"
            signal.product = "rb"
        elif forgery == "strategy_mismatch":
            signal.strategy_name = "htdy_original_realtime_first_seen"
            signal.strategy_version = "v1.0"
        elif forgery == "strategy_input_mismatch":
            wrong_identity = _canonical_identity(
                canonical,
                BarFrequency.M5,
                strategy_input_version=f"su_bing_ema21:v0:{'f' * 64}",
            )
            signal.features["input_identity"] = deepcopy(wrong_identity)
            signal.features["formal_lineage"]["input_identity"] = deepcopy(
                wrong_identity
            )
            signal.quality_status["canonical_consumer_input_digest"] = wrong_identity[
                "digest"
            ]
        elif forgery == "legacy_profile":
            signal.profile_id = "legacy-profile"
        elif forgery == "missing_safety":
            del signal.features["auto_order"]
        elif forgery == "task_auto_order":
            task.request_payload["auto_order"] = True
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


def test_review_exact_bars_rejects_strategy_version_drift() -> None:
    from app.services.review_lineage import ReviewLineageError, load_review_bars

    factory = _session_factory()
    canonical = FakeCanonicalMarketData()
    with factory() as session:
        note = _canonical_review_note(session, canonical)
        note.strategy_version = "forged-version"
        note.extra["formal_lineage"]["strategy_version"] = "forged-version"

        with pytest.raises(
            ReviewLineageError,
            match="REVIEW_EXACT_BARS_IDENTITY_CHANGED",
        ):
            load_review_bars(session, note, market_data=canonical)


def test_review_freezes_and_exactly_verifies_every_auxiliary_input() -> None:
    from app.services.review_lineage import (
        ReviewLineageError,
        load_review_bars,
        resolve_review_source_lineage,
    )

    factory = _session_factory()
    canonical = FakeCanonicalMarketData()
    with factory() as session:
        primary = _canonical_identity(canonical, BarFrequency.M5)
        auxiliary = _canonical_identity(canonical, BarFrequency.M15)
        signal = _canonical_signal(primary, task_no="SIG-REVIEW-AUXILIARY")
        signal.features["formal_lineage"]["auxiliary_input_identities"] = {
            "15m": deepcopy(auxiliary)
        }
        session.add(signal)
        session.flush()

        lineage = resolve_review_source_lineage(
            session,
            source_type="strategy_signal",
            source_id=signal.id,
        )
        assert lineage["auxiliary_input_identities"]["15m"] == auxiliary

        note = ReviewNote(
            source_type="strategy_signal",
            source_id=signal.id,
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

        canonical.queries.clear()
        response = load_review_bars(session, note, market_data=canonical)
        assert [query.frequency for query in canonical.queries] == [
            BarFrequency.M5,
            BarFrequency.M15,
        ]
        assert response["auxiliary_bars"]["15m"][-1]["period"] == "15m"

        auxiliary_drift = FakeCanonicalMarketData(
            manifest_suffix_by_frequency={BarFrequency.M15: "f"}
        )
        with pytest.raises(
            ReviewLineageError,
            match="REVIEW_EXACT_BARS_IDENTITY_CHANGED",
        ):
            load_review_bars(session, note, market_data=auxiliary_drift)


def test_review_openapi_explicitly_declares_canonical_lineage_fields() -> None:
    from app.schemas.review import ReviewExactBarsResponse, ReviewLineageResponse

    lineage_properties = ReviewLineageResponse.model_json_schema()["properties"]
    assert {
        "strategy_version",
        "input_digest",
        "dataset_keys",
        "manifest_digests",
        "window",
        "source_window",
        "input_identity",
        "auxiliary_input_identities",
    } <= set(lineage_properties)
    exact_properties = ReviewExactBarsResponse.model_json_schema()["properties"]
    assert "auxiliary_bars" in exact_properties


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


@pytest.mark.parametrize("source_type", ["strategy_signal", "signal_event"])
@pytest.mark.parametrize(
    "malformed_field",
    [
        "symbol",
        "actual_contract",
        "period",
        "bar_start_before_request",
        "bar_end_after_request",
        "signal_time_mismatch",
    ],
)
def test_review_rejects_source_row_unbound_from_canonical_identity(
    source_type: str,
    malformed_field: str,
) -> None:
    from app.services.review_lineage import (
        ReviewLineageError,
        resolve_review_source_lineage,
    )

    factory = _session_factory()
    with factory() as session:
        source = _canonical_review_source(session, source_type=source_type)
        if malformed_field == "symbol":
            source.symbol = "rb"
        elif malformed_field == "actual_contract":
            source.actual_contract = "RB2610"
        elif malformed_field == "period":
            source.period = "15m"
        elif malformed_field == "bar_start_before_request":
            source.bar_start = START - timedelta(minutes=1)
        elif malformed_field == "bar_end_after_request":
            source.bar_end = END + timedelta(minutes=1)
            source.signal_time = source.bar_end
        elif malformed_field == "signal_time_mismatch":
            source.signal_time = END - timedelta(minutes=1)
        session.flush()

        with pytest.raises(
            ReviewLineageError,
            match="REVIEW_SOURCE_IDENTITY_MISMATCH",
        ):
            resolve_review_source_lineage(
                session,
                source_type=source_type,
                source_id=source.id,
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
        "auxiliary_input_identities": {},
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


def _canonical_identity(
    canonical: FakeCanonicalMarketData,
    frequency: BarFrequency,
    *,
    strategy_input_version: str = "su_bing_ema21:v0:test-input",
) -> dict[str, Any]:
    from app.data_core.consumer_identity import build_canonical_consumer_input

    query = BarQuery(
        dataset_kind=DatasetKind.ACTUAL_DOMINANT,
        symbol="jm",
        contract_or_series="JM2609",
        frequency=frequency,
        start=START,
        end=END,
    )
    return build_canonical_consumer_input(
        query,
        canonical.get_bars(query),
        strategy_input_version=strategy_input_version,
    ).to_snapshot()


def _expected_strategy_input_version(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload.get("strategy_params") or {},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"su_bing_ema21:v0:{hashlib.sha256(encoded).hexdigest()}"


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


def _seed_rank1_mapping(
    session: Session,
    *,
    known_at: datetime | None,
) -> None:
    raw_payload: dict[str, Any] = {}
    if known_at is not None:
        raw_payload["known_at"] = known_at.isoformat()
    session.add(
        MainContractMap(
            instrument_symbol="jm",
            trade_date=START.date(),
            rank=1,
            contract_code="JM2609",
            rule="volume_open_interest",
            provider="rqdata",
            data_version="canonical-mapping-v1",
            raw_payload=raw_payload,
        )
    )
    session.flush()


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


def _canonical_signal(
    identity: dict[str, Any],
    *,
    task_no: str,
) -> StrategySignal:
    signal = _legacy_signal()
    signal.task_no = task_no
    signal.profile_id = None
    signal.market_data_file_id = None
    signal.product = "jm"
    signal.continuous_contract = "JM.MAIN"
    signal.actual_contract = "JM2609"
    signal.period = "5m"
    signal.bar_start = END - timedelta(minutes=5)
    signal.bar_end = END
    signal.signal_time = END
    signal.provider = "rqdata"
    signal.source = "historical_canonical"
    signal.data_role = "primary"
    signal.research_contract = False
    signal.features = {
        "input_identity": deepcopy(identity),
        "observation_only": True,
        "not_trading_instruction": True,
        "auto_order": False,
        "formal_lineage": {
            "schema_version": "signal_canonical_inputs_v1",
            "input_identity": deepcopy(identity),
            "auxiliary_input_identities": {},
            "strategy_version": "v0",
        },
    }
    signal.quality_status = {
        "status": "passed",
        "canonical_consumer_input_digest": identity["digest"],
    }
    return signal


def _canonical_review_source(
    session: Session,
    *,
    source_type: str,
) -> StrategySignal | SignalEvent:
    from app.signal.events import SIGNAL_CREATED, record_signal_scan_event

    canonical = FakeCanonicalMarketData()
    request_payload = _formal_request()
    identity = _canonical_identity(
        canonical,
        BarFrequency.M5,
        strategy_input_version=_expected_strategy_input_version(request_payload),
    )
    formal_payload = SignalScanRequest.model_validate(request_payload).model_dump(
        mode="json"
    )
    task = SignalScanTask(
        task_no=f"SIG-REVIEW-SOURCE-{source_type}",
        status="running",
        watchlist_code="black",
        periods=["5m"],
        request_payload={
            **formal_payload,
            "research_only": False,
            "data_role": "primary",
        },
        result_payload={},
        profile_id=None,
        market_data_file_id=None,
    )
    signal = _canonical_signal(identity, task_no=task.task_no)
    session.add_all([task, signal])
    session.flush()
    if source_type == "strategy_signal":
        return signal
    event = record_signal_scan_event(session, signal, SIGNAL_CREATED, task)
    assert event is not None
    return event


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
