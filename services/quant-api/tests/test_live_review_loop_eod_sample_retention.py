from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.data_core.bar_schema import CanonicalBar
from app.data_core.contracts import BarFrequency, DatasetKind
from app.data_core.rqdata_adapter import ProviderBarBatch
from app.live_review_loop.contracts import StrategyInputSchema
from app.live_review_loop.decisions import SignalDecisionStore
from app.live_review_loop.eod import EodReconciliationService, record_eod_data_gap
from app.live_review_loop.gates import build_live_review_health
from app.live_review_loop.research import (
    ResearchSampleError,
    create_or_get_decision_review,
    extract_research_sample,
)
from app.live_review_loop.retention import RetentionDriftError, RetentionService
from app.live_review_loop.provider_final import RQDataProviderFinalLoader
from app.models.live_review_loop import (
    ResearchSample,
    SignalDecision,
    SignalDecisionReconciliation,
)
from app.models.data_core import DataGap, MarketDataset
from app.models.review import ReviewNote
from app.models.signal import SignalEvent, SignalNotification


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _payload(bar_end: datetime) -> dict[str, object]:
    return {
        "provider": "rqdata",
        "source_mode": "session_aggregate_15m_v2",
        "product": "jm",
        "actual_contract": "JM2609",
        "trading_day": date(2026, 8, 3),
        "period": "15m",
        "bar_end": bar_end,
        "revision": 0,
        "confirmed": True,
        "open": Decimal("100"),
        "high": Decimal("101"),
        "low": Decimal("99"),
        "close": Decimal("100"),
        "volume": Decimal("10"),
        "open_interest": Decimal("20"),
        "turnover": Decimal("1000"),
        "source_start": bar_end - timedelta(minutes=15),
        "source_end": bar_end,
        "source_bar_count": 15,
        "expected_bar_count": 15,
    }


def _live_payload(index: int) -> dict[str, object]:
    bar_end = datetime(2026, 8, 2, 13, 1, tzinfo=UTC) + timedelta(minutes=index)
    payload = _payload(bar_end)
    payload.update(
        source_mode="rqdata_live_1m_v2",
        period="1m",
        source_start=bar_end - timedelta(minutes=1),
        source_end=bar_end,
        source_bar_count=1,
        expected_bar_count=1,
    )
    return payload


def _historical_bars() -> list[dict[str, object]]:
    decision_start = datetime(2026, 8, 2, 13, 0, tzinfo=UTC)
    start = decision_start - timedelta(minutes=15 * 128)
    return [
        {
            "period": "15m",
            "bar_end": start + timedelta(minutes=15 * (index + 1)),
            "open": Decimal(100 + index),
            "high": Decimal(101 + index),
            "low": Decimal(99 + index),
            "close": Decimal(100 + index),
            "volume": Decimal("10"),
        }
        for index in range(128)
    ]


def _decision(session: Session, *, result_kind: str = "no_signal") -> SignalDecision:
    bar_end = datetime(2026, 8, 2, 13, 15, tzinfo=UTC)
    schema = StrategyInputSchema.build(
        trading_day=date(2026, 8, 3),
        actual_contract="JM2609",
        decision_bar=_payload(bar_end),
        historical_input={
            "manifest_digest": "b" * 64,
            "data_role": "primary",
            "quality_status": "passed",
            "aggregation_recipe": "trading_session_15m_v1",
            "bars": _historical_bars(),
            "dataset_key": {
                "provider": "rqdata",
                "dataset_kind": "actual_dominant",
                "symbol": "jm",
                "contract_or_series": "JM2609",
                "frequency": "1m",
                "adjustment": "none",
                "schema_version": "canonical-bar-v1",
            },
        },
        live_inputs=[_live_payload(index) for index in range(15)],
    )
    return SignalDecisionStore(session).create(
        schema,
        result_kind=result_kind,
        direction="long" if result_kind == "signal" else None,
        result_payload={"candidates": ["long"] if result_kind == "signal" else []},
        decision_at=bar_end,
    )


@pytest.mark.parametrize(
    ("change_data", "change_result", "expected"),
    [
        (False, False, "unchanged"),
        (True, False, "data_changed"),
        (False, True, "result_changed"),
        (True, True, "data_and_result_changed"),
    ],
)
def test_eod_records_four_deterministic_outcomes(
    change_data: bool, change_result: bool, expected: str
) -> None:
    with _session() as session:
        decision = _decision(session)
        snapshot = dict(decision.input_snapshot)
        if change_data:
            snapshot["provider_final_marker"] = "changed"
        result = {
            "result_kind": "signal" if change_result else decision.result_kind,
            "direction": "long" if change_result else decision.direction,
            "payload": {"candidates": ["long"]}
            if change_result
            else decision.result_payload,
        }
        row = EodReconciliationService(session).complete(
            decision,
            recipe_version="jm_ema21_confirmed_close_direction_v1",
            provider_final_snapshot=snapshot,
            provider_data_version="rqdata-test-final-v1",
            provider_request_digest="c" * 64,
            recomputed_result=result,
        )

        assert row.outcome == expected
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0


def test_eod_requires_the_original_strategy_recipe_and_identity() -> None:
    with _session() as session:
        decision = _decision(session)
        service = EodReconciliationService(session)

        with pytest.raises(ValueError, match="EOD_RECIPE_MISMATCH"):
            service.complete(
                decision,
                recipe_version="different_recipe",
                provider_final_snapshot=decision.input_snapshot,
                provider_data_version="rqdata-test-final-v1",
                provider_request_digest="c" * 64,
                recomputed_result={
                    "result_kind": decision.result_kind,
                    "direction": decision.direction,
                    "payload": decision.result_payload,
                },
            )

        changed_identity = dict(decision.input_snapshot)
        changed_identity["strategy"] = {
            **decision.input_snapshot["strategy"],
            "version": "v999",
        }
        with pytest.raises(ValueError, match="EOD_INPUT_IDENTITY_MISMATCH"):
            service.complete(
                decision,
                recipe_version="jm_ema21_confirmed_close_direction_v1",
                provider_final_snapshot=changed_identity,
                provider_data_version="rqdata-test-final-v1",
                provider_request_digest="c" * 64,
                recomputed_result={
                    "result_kind": decision.result_kind,
                    "direction": decision.direction,
                    "payload": decision.result_payload,
                },
            )


def test_eod_provider_final_loader_uses_exact_rqdata_adapter_window() -> None:
    class Adapter:
        request = None

        def fetch_bars(self, request):
            self.request = request
            bars = tuple(
                CanonicalBar(
                    provider="rqdata",
                    dataset_kind=DatasetKind.ACTUAL_DOMINANT,
                    symbol="jm",
                    contract_or_series="JM2609",
                    frequency=BarFrequency.M1,
                    bar_end=end,
                    trading_day=date(2026, 8, 3),
                    open=Decimal(100 + index),
                    high=Decimal(101 + index),
                    low=Decimal(99 + index),
                    close=Decimal(100 + index),
                    volume=Decimal("10"),
                    turnover=Decimal("1000"),
                    open_interest=Decimal("20"),
                    adjustment="none",
                    schema_version="canonical-bar-v1",
                )
                for index, end in enumerate(request.sessions[0].expected_bar_ends)
            )
            return ProviderBarBatch(
                request=request, bars=bars, data_version="rqdata-test-final-v1"
            )

        def fetch_rank1_map(self, request):
            raise AssertionError(
                "rank map must not be fetched during exact decision reconciliation"
            )

    with _session() as session:
        decision = _decision(session)
        adapter = Adapter()
        provider_final = RQDataProviderFinalLoader(adapter)(decision)

        assert adapter.request is not None
        assert adapter.request.dataset.contract_or_series == "JM2609"
        assert tuple(adapter.request.sessions[0].expected_bar_ends) == tuple(
            datetime.fromisoformat(item["bar_end"].replace("Z", "+00:00"))
            for item in decision.input_snapshot["live_inputs"]
        )
        assert provider_final.data_version == "rqdata-test-final-v1"
        assert len(provider_final.request_digest) == 64
        strategy = provider_final.strategy_input["strategy"]
        assert strategy["parameters"] == {
            "comparison": "confirmed_close_vs_ema21",
            "equal_close_policy": "no_signal",
            "period": 21,
            "round_digits": 6,
            "seed_policy": "sma_window",
        }
        assert strategy["future_looking"] is False
        assert strategy["auto_order"] is False


def test_eod_retries_exactly_three_times_then_records_gap() -> None:
    calls: list[tuple[int, datetime, datetime]] = []
    with _session() as session:
        decision = _decision(session)
        service = EodReconciliationService(session)

        def loader(_decision: SignalDecision) -> dict[str, object]:
            raise RuntimeError("provider unavailable")

        def gap_recorder(item: SignalDecision, start: datetime, end: datetime) -> None:
            calls.append((item.id, start, end))

        for expected_attempt in range(1, 4):
            row = service.run(
                decision,
                recipe_version="jm_ema21_confirmed_close_direction_v1",
                provider_final_loader=loader,
                gap_recorder=gap_recorder,
            )
            assert row.attempt_count == expected_attempt
        assert row.status == "failed"
        assert len(calls) == 1
        assert calls[0][1:] == (decision.input_window_start, decision.input_window_end)

        again = service.run(
            decision,
            recipe_version="jm_ema21_confirmed_close_direction_v1",
            provider_final_loader=loader,
            gap_recorder=gap_recorder,
        )
        assert again.attempt_count == 3
        assert len(calls) == 1


def test_eod_persists_only_redacted_error_fingerprint() -> None:
    with _session() as session:
        decision = _decision(session)
        row = EodReconciliationService(session).run(
            decision,
            recipe_version="jm_ema21_confirmed_close_direction_v1",
            provider_final_loader=lambda _: (_ for _ in ()).throw(
                RuntimeError("password=do-not-store https://secret.example/webhook")
            ),
            gap_recorder=lambda *_: None,
        )

        assert row.error_code == "RuntimeError"
        assert row.error_message is not None
        assert row.error_message.startswith("redacted_sha256:")
        assert "do-not-store" not in row.error_message
        assert "secret.example" not in row.error_message


def test_eod_gap_uses_decision_bound_dataset_and_is_idempotent() -> None:
    with _session() as session:
        decision = _decision(session)
        session.add(
            MarketDataset(
                provider="rqdata",
                dataset_kind="actual_dominant",
                symbol="jm",
                contract_or_series="JM2609",
                frequency="1m",
                adjustment="none",
                schema_version="canonical-bar-v1",
            )
        )
        session.flush()

        first = record_eod_data_gap(
            session, decision, decision.input_window_start, decision.input_window_end
        )
        second = record_eod_data_gap(
            session, decision, decision.input_window_start, decision.input_window_end
        )

        assert first.id == second.id
        assert first.reason_code == "eod_provider_final_unavailable"
        assert len(list(session.scalars(select(DataGap)))) == 1


def test_live_review_health_is_disabled_by_default_and_never_implies_order() -> None:
    health = build_live_review_health({})

    assert health == {
        "status": "disabled",
        "live_decision_enabled": False,
        "eod_enabled": False,
        "retention_scheduler_enabled": False,
        "notification_enabled": False,
        "review_enabled": False,
        "auto_order": False,
        "observation_only": True,
    }


def test_research_sample_requires_complete_human_labels_and_is_idempotent() -> None:
    with _session() as session:
        decision = _decision(session)
        reconciliation = EodReconciliationService(session).complete(
            decision,
            recipe_version="jm_ema21_confirmed_close_direction_v1",
            provider_final_snapshot=decision.input_snapshot,
            provider_data_version="rqdata-test-final-v1",
            provider_request_digest="c" * 64,
            recomputed_result={
                "result_kind": decision.result_kind,
                "direction": decision.direction,
                "payload": decision.result_payload,
            },
        )
        review = create_or_get_decision_review(session, decision.id)
        with pytest.raises(
            ResearchSampleError, match="RESEARCH_SAMPLE_LABELS_INCOMPLETE"
        ):
            extract_research_sample(session, review.id)

        review.market_phase = "trend"
        review.is_system_compliant = True
        review.rule_tags = ["confirmed-close"]
        review.lesson = "wait for confirmed close"
        first = extract_research_sample(session, review.id)
        second = extract_research_sample(session, review.id)

        assert first.id == second.id
        assert first.decision_key == decision.decision_key
        assert first.outcome["reconciliation_outcome"] == reconciliation.outcome
        assert len(list(session.scalars(select(ResearchSample)))) == 1


def test_retention_plan_is_exact_protects_sample_and_rejects_drift() -> None:
    as_of = datetime(2026, 8, 2, tzinfo=UTC)
    old = as_of - timedelta(days=31)
    with _session() as session:
        decision = _decision(session)
        session.execute(
            update(SignalDecision)
            .where(SignalDecision.id == decision.id)
            .values(created_at=old)
        )
        session.expire(decision)
        reconciliation = EodReconciliationService(session).complete(
            decision,
            recipe_version="jm_ema21_confirmed_close_direction_v1",
            provider_final_snapshot=decision.input_snapshot,
            provider_data_version="rqdata-test-final-v1",
            provider_request_digest="c" * 64,
            recomputed_result={
                "result_kind": decision.result_kind,
                "direction": decision.direction,
                "payload": decision.result_payload,
            },
        )
        reconciliation.created_at = old
        review = create_or_get_decision_review(session, decision.id)
        review.market_phase = "trend"
        review.is_system_compliant = True
        review.rule_tags = ["confirmed-close"]
        review.lesson = "wait"
        sample = extract_research_sample(session, review.id)
        session.flush()
        session.commit()

        service = RetentionService(session)
        plan = service.plan(as_of=as_of)
        assert plan.counts["signal_decisions"] == 1
        assert "research_samples" not in plan.ids

        session.execute(
            update(SignalDecision)
            .where(SignalDecision.id == decision.id)
            .values(result_payload={"drift": True})
        )
        with pytest.raises(RetentionDriftError, match="RETENTION_PLAN_DRIFT"):
            service.apply(plan)
        session.rollback()

        plan = service.plan(as_of=as_of)
        result = service.apply(plan)
        assert result["signal_decisions"] == 1
        session.commit()
        assert session.get(ResearchSample, sample.id) is not None
        assert session.get(ReviewNote, review.id) is not None
        assert session.get(SignalDecision, decision.id) is None
        assert session.get(SignalDecisionReconciliation, reconciliation.id) is None
