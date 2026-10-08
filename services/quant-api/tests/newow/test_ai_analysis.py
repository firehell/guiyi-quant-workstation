import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from guiyi_quant.newow.ai_analysis import AnalysisCombo, AnalysisSummary, PAGE_SOURCE_SHA256, estimate_segments, rank_combos
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_contracts import ProductBar, ProductFrequency
from app.market_data.newow.ai_analysis import analyze_product, analysis_input_sha256
from app.market_data.newow.product_reader import NewowProductReadError

ORACLE = json.loads((Path(__file__).parent / "fixtures/ai-analysis-public-oracle.json").read_text())


@pytest.mark.parametrize("case", ORACLE["cases"])
@pytest.mark.parametrize("strategy", ("oscillation", "trend"))
def test_public_source_backtest_oracle(case, strategy):
    assert ORACLE["source_sha256"] == PAGE_SOURCE_SHA256
    rows = [tuple(Decimal(str(row[k])) for k in ("high", "low", "close")) for row in case["bars"]]
    summary = estimate_segments([rows], strategy)
    expected = case[strategy]
    if expected is None:
        assert summary is None
    else:
        assert summary.cumulative_return == Decimal(str(expected["cumReturn"]))
        assert summary.max_drawdown == Decimal(str(expected["maxDrawdown"]))
        assert summary.trade_count == expected["tradeCount"]
        assert summary.win_rate == expected["accuracy"]


def test_public_source_four_combo_scores():
    values = []
    for i, s in enumerate(ORACLE["score_inputs"]):
        summary = AnalysisSummary(Decimal(str(s["cumReturn"])), s["accuracy"], Decimal(str(s["maxDrawdown"])), s["tradeCount"], 0, 1, 0)
        values.append(AnalysisCombo("oscillation" if i < 2 else "trend", "1w" if i % 2 == 0 else "1d", "2024-06-01", None, 11, None, summary))
    for combo, expected in zip(rank_combos(values), ORACLE["score_outputs"]):
        assert combo.score == Decimal(str(expected["score"]))
        assert combo.is_best == expected["is_best"]
        assert combo.confidence == expected["confidence"]


def test_sample_gate_all_equal_negative_scores_and_tie_break():
    summary = AnalysisSummary(Decimal("-5"), 0, Decimal("10"), 3, 0, 1, 0)
    a = AnalysisCombo("trend", "1d", "2025-09-01", None, 20, None, summary)
    b = replace(a, frequency="1w", summary=replace(summary, trade_count=10))
    c = replace(a, strategy="oscillation", summary=replace(summary, trade_count=2))
    values = rank_combos([a, b, c])
    assert [x.score for x in values] == [Decimal("0"), Decimal("0"), None]
    assert [x.is_best for x in values] == [False, True, False]
    assert not any(x.is_best for x in rank_combos([c, replace(c, summary=None)]))


def test_segment_terminal_estimates_cannot_pair_across_prices_or_use_short_segments():
    a = [(Decimal("110"), Decimal("90"), Decimal("100"))] * 11
    b = [(Decimal("1100"), Decimal("900"), Decimal("1000"))] * 11
    result = estimate_segments([a, b, a[:5]], "oscillation")
    assert result.trade_count == 4 and result.terminal_valuation_count == 2
    assert result.cumulative_return == Decimal("66.67")
    assert result.warming_segment_count == 1
    assert result.max_drawdown == 0
    with pytest.raises(ValueError):
        estimate_segments([[(Decimal("NaN"), Decimal(1), Decimal(1))] * 11], "trend")


def bars(frequency, contract="JM2609", segment="owned", eligible=True):
    output = []
    for i in range(15):
        day = date(2026, 7, 1) + timedelta(days=i)
        output.append(ProductBar(NewowDailyBar("jm", contract, segment, day,
          datetime.combine(day, datetime.min.time(), UTC), Decimal(100), Decimal(110), Decimal(90), Decimal(100),
          1, 0, f"canonical:{i}", eligible, True), frequency))
    return tuple(output)


def test_reader_scopes_six_combos_one_cutoff_and_omits_nonowned_warmup():
    cutoff = datetime(2026, 8, 1, tzinfo=UTC)
    calls = []
    def factory(frequency):
        class Reader:
            def resolve_performance_window(self, product, period, since, through, as_of):
                calls.append((frequency, since, as_of))
                return SimpleNamespace(actual_through=date(2026, 7, 31))
            def load(self, query, as_of):
                assert query.as_of == as_of == cutoff
                # Real reader returns per-owner physical warm-up prefixes, which
                # overlap in time and must not become eligible AI observations.
                owned = bars(frequency)
                prefix = tuple(replace(b, bar=replace(b.bar, observation_eligible=False)) for b in owned)
                return SimpleNamespace(replay_bars=(*prefix, *owned), input_quality_policy="test_quality_v1")
        return Reader()
    combos = analyze_product("jm", cutoff, factory, lambda: False, lambda f: None)
    assert len(combos) == 6 and {c.frequency for c in combos} == {"1w", "1d", "60m"}
    assert all(c.source_bars == 15 and len(c.input_sha256) == 64 for c in combos)
    assert calls == [(ProductFrequency.WEEKLY, date(2024, 6, 1), cutoff), (ProductFrequency.DAILY, date(2025, 9, 1), cutoff), (ProductFrequency.HOURLY, date(2026, 4, 1), cutoff)]


def test_ai_input_digest_binds_quality_segmentation_and_policy():
    original = bars(ProductFrequency.DAILY)
    split = tuple(replace(b, calculation_segment_id="quality-after-gap") if i >= 11 else b for i, b in enumerate(original))
    assert analysis_input_sha256(original, "v1") != analysis_input_sha256(split, "v1")
    assert analysis_input_sha256(original, "v1") != analysis_input_sha256(original, "v2")


def test_integrity_failure_does_not_degrade_to_a_recommendation():
    class Reader:
        def resolve_performance_window(self, *_args):
            raise NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID")
    with pytest.raises(NewowProductReadError):
        analyze_product("jm", datetime(2026, 8, 1, tzinfo=UTC), lambda f: Reader(), lambda: False, lambda f: None)


def test_endpoint_rejects_unknown_duplicate_future_naive_and_hourly_inputs(monkeypatch):
    from app.api import market_newow
    from app.main import app
    from app.db.session import get_db
    app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr(market_newow, "_build_snapshot_inputs", lambda *args: pytest.fail("invalid query must not read data"))
    try:
        with TestClient(app) as client:
            for params in ["product=jm&as_of=2026-01-01", "product=jm&as_of=2099-01-01T00:00:00Z",
                           "product=jm&product=rb&as_of=2026-01-01T00:00:00Z",
                           "product=jm&frequency=60m&as_of=2026-01-01T00:00:00Z"]:
                response = client.get("/api/v1/market/newow/ai-analysis?" + params)
                assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_missing_hourly_keeps_six_cards_without_recommendation_for_hourly():
    cutoff = datetime(2026, 8, 1, tzinfo=UTC)
    class Reader:
        def resolve_performance_window(self, *_args):
            return SimpleNamespace(actual_through=date(2026, 7, 31))
        def load(self, query, as_of):
            return SimpleNamespace(replay_bars=bars(query.frequency), input_quality_policy="test_quality_v1")
    def admit(f):
        if f == "60m":
            raise NewowProductReadError("NEWOW_COMPLETE_PERIOD_MISSING")
    values = analyze_product("jm", cutoff, lambda f: Reader(), lambda: False, admit)
    assert len(values) == 6
    missing = [c for c in values if c.frequency == "60m"]
    assert len(missing) == 2 and all(c.summary is None and not c.is_best for c in missing)


def test_hourly_cancellation_does_not_return_partial_four_combo_ranking():
    from app.market_data.newow.product_reader import NewowProductReadCancelled
    calls = []
    class Reader:
        def resolve_performance_window(self, *_args):
            return SimpleNamespace(actual_through=date(2026, 7, 31))
        def load(self, query, as_of):
            calls.append(query.frequency)
            return SimpleNamespace(replay_bars=bars(query.frequency), input_quality_policy="test_quality_v1")
    with pytest.raises(NewowProductReadCancelled):
        analyze_product("jm", datetime(2026, 8, 1, tzinfo=UTC), lambda f: Reader(),
            lambda: len(calls) == 2, lambda f: None)
