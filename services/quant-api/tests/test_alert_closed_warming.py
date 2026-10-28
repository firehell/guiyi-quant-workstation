"""Explicit cohort-only warming classification; kernel and native gate stay strict."""

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.alerts.evaluators import AlertEvaluationError, SubingThsEvaluator
from app.alerts.models import AlertRule
from app.alerts.registry import (
    SUBING_THS_ALERT_RULE_CODE,
    SUBING_QUALITY_REWARM_POLICY_V2,
)
from app.market_data.market_read_service import (
    MarketReadService,
    MarketReadWindow,
    MarketReadWindowError,
)
from tests.test_closed_runtime_warmup import canonical_reader, DAY, NOW, phase
from app.market_data.market_phase import MarketPhase


@pytest.fixture
def closed_segment(monkeypatch):
    from app.alerts import composition

    market, source = canonical_reader()
    source.bars = source.bars[-26:]
    bars = source.bars
    window = MarketReadWindow(
        "jm",
        "actual_dominant",
        "1w",
        DAY,
        "JM2701",
        bars[-1].bar_end,
        bars,
        ("JM2701",) * len(bars),
        input_policy_version=SUBING_QUALITY_REWARM_POLICY_V2,
    )
    quality = {"window": window}

    def read_as_of(self, query, *, as_of):
        assert as_of == NOW and query.frequency.value == "1w"
        return quality["window"]

    def read_current(self, query, *, trading_day):
        assert trading_day == DAY and query.frequency.value == "1w"
        return quality["window"]

    monkeypatch.setattr(
        MarketReadService, "latest_subing_quality_window_as_of", read_as_of
    )
    monkeypatch.setattr(MarketReadService, "latest_subing_quality_window", read_current)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AlertRule.__table__.create(engine)
    factory = sessionmaker(engine)
    with factory.begin() as session:
        session.add(
            AlertRule(
                rule_code=SUBING_THS_ALERT_RULE_CODE,
                enabled=True,
                scope_product_frequencies={"jm": ["1w"]},
            )
        )
    statements, closes = [], []
    event.listen(
        engine,
        "before_cursor_execute",
        lambda _c, _cursor, sql, *_: statements.append(sql),
    )
    runtime = SimpleNamespace(
        _validate_startup_composition=lambda: None,
        _session_factory=factory,
        _market_read_factory=lambda _: market,
        _evaluators={SUBING_THS_ALERT_RULE_CODE: SubingThsEvaluator()},
        message_source=SimpleNamespace(close=lambda: closes.append(True)),
    )
    monkeypatch.setattr(composition, "build_alert_runtime", lambda: runtime)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(composition, "datetime", Clock)
    yield SimpleNamespace(
        market=market,
        source=source,
        runtime=runtime,
        quality=quality,
        statements=statements,
        closes=closes,
    )
    engine.dispose()


def test_cohort_classifies_real_closed_26_bar_kernel_warming_without_claiming_calculated(
    closed_segment,
):
    from app.alerts.composition import warmup_alert_runtime

    result = warmup_alert_runtime(allow_closed_warming=True)
    assert result == {
        "calculated": 0,
        "total": 1,
        "natural_signals_verified": False,
        "warming": [
            {
                "rule_code": SUBING_THS_ALERT_RULE_CODE,
                "symbol": "jm",
                "frequency": "1w",
                "contract": "JM2701",
                "bar_count": 26,
            }
        ],
    }
    assert closed_segment.closes == [True]
    assert all(
        not sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for sql in closed_segment.statements
    )


def test_native_default_still_rejects_real_short_quality_segment(closed_segment):
    from app.alerts.composition import warmup_alert_runtime

    with pytest.raises(AlertEvaluationError, match="ALERT_EVALUATION_WARMING_UP"):
        warmup_alert_runtime()
    assert closed_segment.closes == [True]


@pytest.mark.parametrize(
    "error",
    [
        AlertEvaluationError("ALERT_EVALUATION_INPUT_INVALID"),
        MarketReadWindowError("MARKET_READ_CONTRACT_UNAVAILABLE"),
        RuntimeError("ALERT_EVALUATION_WARMING_UP"),
    ],
)
def test_cohort_never_classifies_other_failures_as_warming(closed_segment, error):
    from app.alerts.composition import warmup_alert_runtime

    def fail(*_):
        raise error

    closed_segment.runtime._evaluators[SUBING_THS_ALERT_RULE_CODE] = SimpleNamespace(
        evaluate_candidates=fail
    )
    with pytest.raises(type(error), match=str(error)):
        warmup_alert_runtime(allow_closed_warming=True)


def test_cohort_never_accepts_warming_from_nonclosed_reader(closed_segment):
    from app.alerts.composition import warmup_alert_runtime

    closed_segment.market._phase_resolver = SimpleNamespace(
        resolve=lambda *_: phase(MarketPhase.TRADING, DAY)
    )
    closed_segment.market.history_page = lambda _: SimpleNamespace(
        bars=closed_segment.quality["window"].bars
    )
    closed_segment.market.bars_until = lambda *_args, **_kwargs: closed_segment.quality[
        "window"
    ]
    closed_segment.market.assert_window_current = lambda _: None
    with pytest.raises(AlertEvaluationError, match="ALERT_EVALUATION_WARMING_UP"):
        warmup_alert_runtime(allow_closed_warming=True)


def test_cohort_never_classifies_nonquality_policy_even_when_evaluator_says_warming(
    closed_segment,
):
    from app.alerts.composition import warmup_alert_runtime

    closed_segment.quality["window"] = replace(
        closed_segment.quality["window"], input_policy_version=None
    )

    def warming(*_):
        raise AlertEvaluationError("ALERT_EVALUATION_WARMING_UP")

    closed_segment.runtime._evaluators[SUBING_THS_ALERT_RULE_CODE] = SimpleNamespace(
        evaluate_candidates=warming
    )
    with pytest.raises(AlertEvaluationError, match="ALERT_EVALUATION_WARMING_UP"):
        warmup_alert_runtime(allow_closed_warming=True)


def test_cohort_quality_error_before_evaluation_still_blocks(
    closed_segment, monkeypatch
):
    from app.alerts.composition import warmup_alert_runtime

    def corrupt(*_args, **_kwargs):
        raise MarketReadWindowError("MARKET_READ_WINDOW_INCOMPLETE")

    monkeypatch.setattr(
        MarketReadService, "latest_subing_quality_window_as_of", corrupt
    )
    with pytest.raises(MarketReadWindowError, match="MARKET_READ_WINDOW_INCOMPLETE"):
        warmup_alert_runtime(allow_closed_warming=True)


def test_cohort_never_classifies_intraday_warming(closed_segment):
    from app.alerts.composition import warmup_alert_runtime

    with closed_segment.runtime._session_factory.begin() as session:
        rule = session.query(AlertRule).one()
        rule.scope_product_frequencies = {"jm": ["60m"]}

    def warming(*_):
        raise AlertEvaluationError("ALERT_EVALUATION_WARMING_UP")

    closed_segment.runtime._evaluators[SUBING_THS_ALERT_RULE_CODE] = SimpleNamespace(
        evaluate_candidates=warming
    )
    with pytest.raises(AlertEvaluationError, match="ALERT_EVALUATION_WARMING_UP"):
        warmup_alert_runtime(allow_closed_warming=True)


def test_cohort_never_classifies_an_unknown_subclass_as_the_exact_warming_error(
    closed_segment,
):
    from app.alerts.composition import warmup_alert_runtime

    class UnknownWarming(AlertEvaluationError):
        pass

    def unknown(*_):
        raise UnknownWarming("ALERT_EVALUATION_WARMING_UP")

    closed_segment.runtime._evaluators[SUBING_THS_ALERT_RULE_CODE] = SimpleNamespace(
        evaluate_candidates=unknown
    )
    with pytest.raises(UnknownWarming):
        warmup_alert_runtime(allow_closed_warming=True)


def test_cohort_break_warmup_requires_feed_before_and_after(closed_segment, monkeypatch):
    from app.alerts import composition
    from app.market_data import composition as market_composition
    calls = []
    closed_segment.market._phase_resolver = SimpleNamespace(
        resolve=lambda *_: phase(MarketPhase.BREAK, DAY))
    monkeypatch.setattr(market_composition, 'build_market_feed_service', lambda session: SimpleNamespace(
        quiescent=lambda at: calls.append(at) or True))
    result = composition.warmup_alert_runtime(allow_closed_warming=True, allow_break=True)
    assert calls == [NOW, NOW]
    assert result['calculated'] == 0 and len(result['warming']) == 1
    assert all(not sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))
               for sql in closed_segment.statements)


@pytest.mark.parametrize('proofs', [(False,), (True, False)])
def test_cohort_break_warmup_rejects_unproved_feed(closed_segment, monkeypatch, proofs):
    from app.alerts import composition
    from app.market_data import composition as market_composition
    values = iter(proofs)
    monkeypatch.setattr(market_composition, 'build_market_feed_service', lambda session: SimpleNamespace(
        quiescent=lambda at: next(values)))
    with pytest.raises(MarketReadWindowError, match='MARKET_READ_PHASE_UNAVAILABLE'):
        composition.warmup_alert_runtime(allow_closed_warming=True, allow_break=True)
    assert closed_segment.closes == [True]
