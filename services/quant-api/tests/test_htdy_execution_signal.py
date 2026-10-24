"""The new offline policy consumes the existing validated observation kernel."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.alerts.evaluators import HtdyOriginalEvaluator
from app.htdy_execution import signal_from_window
from app.market_data.domain import CanonicalBar
from app.market_data.market_read_service import MarketReadWindow


def window():
    start = datetime(2026, 10, 1, tzinfo=UTC)
    bars = tuple(CanonicalBar(start + timedelta(hours=i), date(2026, 10, 1),
        Decimal("3500"), Decimal("3510"), Decimal("3490"), Decimal("3501"), Decimal("100"), None, None)
        for i in range(32))
    return MarketReadWindow(symbol="RB", series_kind="actual_dominant", frequency="60m",
        trading_day=bars[-1].trading_day, cutoff=bars[-1].bar_end, contract="RB2701",
        bars=bars, bar_contracts=("RB2701",) * 32)


class ValidatedReader:
    def __init__(self, failure=False):
        self.checked = []
        self.failure = failure

    def validate_alert_window(self, value, *, context_bars):
        self.checked.append((value, context_bars))
        if self.failure:
            raise ValueError("AUTHORITATIVE_GAP")


def test_signal_uses_shared_evaluator_and_freezes_current_window_identity():
    w = window()
    reader = ValidatedReader()
    observed = w.cutoff + timedelta(seconds=2)
    result = signal_from_window(reader, w, source_id="journal-1", observed_at=observed)
    assert result.directions == HtdyOriginalEvaluator().evaluate(w).observation_types
    assert result.previous_bar_end == w.bars[-2].bar_end
    assert result.bar_end == w.cutoff
    assert result.observed_at == observed
    assert reader.checked == [(w, 32)]
    assert len(result.input_hash) == 64
    changed = replace(w, bars=(replace(w.bars[0], high=Decimal("3511")),) + w.bars[1:])
    assert signal_from_window(reader, changed, source_id="j2", observed_at=observed).input_hash != result.input_hash


def test_authority_failure_is_not_replaced_by_chart_or_retrospective_signal():
    w = window()
    with pytest.raises(ValueError, match="AUTHORITATIVE_GAP"):
        signal_from_window(ValidatedReader(True), w, source_id="j", observed_at=w.cutoff + timedelta(seconds=2))


@pytest.mark.parametrize("frequency", ["15m", "1d"])
def test_only_sixty_minute_input_is_accepted(frequency):
    w = replace(window(), frequency=frequency)
    with pytest.raises(ValueError, match="60M"):
        signal_from_window(ValidatedReader(), w, source_id="j", observed_at=w.cutoff + timedelta(seconds=2))


def test_operational_bootstrap_freezes_existing_universe_without_a_new_resolver():
    from app.htdy_execution import start_operational
    from app.market_data.operational_universe import load_operational_products
    from guiyi_quant.htdy_execution import AccountSnapshot
    at = datetime(2026, 10, 26, tzinfo=UTC)
    state = start_operational("simnow-test", at, AccountSnapshot(
        "simnow-test", at, Decimal("100000"), Decimal("90000")))
    assert tuple(p.product for p in state.products) == tuple(p.upper() for p in load_operational_products())
