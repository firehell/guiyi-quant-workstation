from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.alerts.evaluators import AlertObservationCandidate
from app.alerts.models import AlertEvent, AlertRule, SubingSignalAlignment
from app.alerts.registry import SUBING_QUALITY_REWARM_POLICY_V2, SUBING_THS_ALERT_RULE_CODE
from app.alerts.runtime import AlertRuntime, _CanonicalUpdatedTrigger
from app.market_data.domain import CanonicalBar
from app.market_data.market_read_service import MarketReadWindow, MarketReadWindowError


@pytest.mark.parametrize("drift_at", ("before_evaluation", "after_evaluation"))
def test_canonical_quality_source_drift_never_commits_event_or_claim(drift_at):
    """The canonical trigger must retain the old replay's two source checks."""
    now = datetime(2026, 10, 15, 7, tzinfo=UTC)
    engine = create_engine("sqlite://")
    for table in (AlertRule.__table__, AlertEvent.__table__, SubingSignalAlignment.__table__):
        table.create(engine)
    with Session(engine) as session:
        session.add(AlertRule(
            rule_code=SUBING_THS_ALERT_RULE_CODE, enabled=True,
            scope_product_frequencies={"rb": ["1d"]},
        ))
        session.commit()
    bar = CanonicalBar(now, now.date(), "1", "1", "1", "1", "1", None, None)
    window = MarketReadWindow(
        "rb", "actual_dominant", "1d", now.date(), "RB2701", now,
        (bar,), ("RB2701",), input_policy_version=SUBING_QUALITY_REWARM_POLICY_V2,
    )

    class Reader:
        changed = False
        checks = 0

        def latest_subing_quality_window(self, query, *, trading_day):
            self.changed = drift_at == "before_evaluation"
            return window

        def assert_window_current(self, value):
            assert value is window
            self.checks += 1
            if self.changed:
                raise MarketReadWindowError("MARKET_READ_CONTRACT_UNAVAILABLE")

    reader = Reader()

    class Evaluator:
        calls = 0

        def evaluate_candidates(self, market_read, value):
            self.calls += 1
            reader.changed = True
            return (AlertObservationCandidate(
                now, now.date(), "RB2701", ("buy",), SUBING_QUALITY_REWARM_POLICY_V2,
            ),)

    evaluator = Evaluator()
    runtime = AlertRuntime(
        session_factory=lambda: Session(engine), market_read_factory=lambda _: reader,
        evaluators={SUBING_THS_ALERT_RULE_CODE: evaluator}, sender=None,
        operational_products=("rb",), taxonomy={}, clock=lambda: now,
    )
    runtime._process_canonical_updated(_CanonicalUpdatedTrigger(now.date()))
    expected_calls = int(drift_at == "after_evaluation")
    assert evaluator.calls == expected_calls
    assert reader.checks == expected_calls + 1
    with Session(engine) as session:
        # No Event implies no per-event eligibility, HTTP claim, or batch receipt.
        assert session.scalar(select(AlertEvent)) is None
        assert session.scalar(select(SubingSignalAlignment)) is None
    assert runtime._coverage_progress[(SUBING_THS_ALERT_RULE_CODE, "rb", "1d")]["state"] == "evaluation_failed"
    engine.dispose()
