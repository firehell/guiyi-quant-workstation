"""Read-only six-combination page analysis via the existing validated reader."""
from datetime import date, datetime
from itertools import groupby
from hashlib import sha256
import json

from guiyi_quant.newow.ai_analysis import AnalysisCombo, estimate_segments, rank_combos
from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy, lifecycle_input_sha256
from .product_query import NewowProductQuery
from .product_reader import NewowProductReadError

# Public AI fetchKlineForAI's period-specific windows, explicitly exposed in UI.
STARTS = ((ProductFrequency.WEEKLY, date(2024, 6, 1)), (ProductFrequency.DAILY, date(2025, 9, 1)), (ProductFrequency.HOURLY, date(2026, 4, 1)))


def analysis_input_sha256(bars, quality_policy):
    if not bars:
        return None
    payload = {"lifecycle_input_sha256": lifecycle_input_sha256(bars),
               "input_quality_policy": str(quality_policy),
               "calculation_segments": [(b.bar.segment_id, b.calculation_segment_id, b.source_bar_sha256) for b in bars]}
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def analyze_product(product: str, as_of: datetime, reader_factory, cancelled, enforce_frequency):
    combos = []
    for frequency, since in STARTS:
        if cancelled():
            from .product_reader import NewowProductReadCancelled
            raise NewowProductReadCancelled("NEWOW_READ_CANCELLED")
        try:
            enforce_frequency(frequency.value)
            reader = reader_factory(frequency)
            window = reader.resolve_performance_window(product, frequency, since, None, as_of)
            read = reader.load(NewowProductQuery(product, ProductStrategy.TREND, frequency,
                              since, window.actual_through, performance_since=since,
                              performance_through=window.actual_through, as_of=as_of), as_of)
            bars = tuple(b for b in read.replay_bars if since <= b.bar.trading_day <= window.actual_through
                         and b.bar.bar_end <= as_of and b.bar.observation_eligible)
            if any(b.frequency != frequency or b.bar.product != product or not b.bar.completed for b in bars):
                raise NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID")
            if any(b.bar.bar_end <= a.bar.bar_end for a, b in zip(bars, bars[1:])):
                raise NewowProductReadError("NEWOW_DATA_OUT_OF_ORDER")
            segments = []
            seen = set()
            for key, group in groupby(bars, key=lambda b: (b.bar.physical_contract, b.bar.segment_id, b.calculation_segment_id)):
                if key in seen:
                    raise NewowProductReadError("NEWOW_DATA_IDENTITY_INVALID")
                seen.add(key)
                segments.append(tuple((b.bar.high, b.bar.low, b.bar.close) for b in group))
            through = bars[-1].bar.trading_day.isoformat() if bars else None
            digest = analysis_input_sha256(bars, read.input_quality_policy)
            for strategy in ("oscillation", "trend"):
                summary = estimate_segments(segments, strategy)
                combos.append(AnalysisCombo(strategy, frequency.value, since.isoformat(), through,
                              len(bars), digest, summary, None if summary else "NEWOW_AI_WARMUP_INSUFFICIENT"))
        except Exception as error:
            # Known unavailable inputs keep their two cards visible; integrity,
            # cancellation and unexpected faults fail the entire request closed.
            from .public_errors import public_product_error
            status, detail = public_product_error(error)
            code = detail["code"]
            unavailable = {"NEWOW_COMPLETE_TRADING_DAY_MISSING", "NEWOW_COMPLETE_PERIOD_MISSING",
                           "NEWOW_FREQUENCY_NOT_OPEN", "NEWOW_PRODUCT_FREQUENCY_NOT_OPEN"}
            if status != 409 or code not in unavailable:
                raise
            combos.extend(AnalysisCombo(s, frequency.value, since.isoformat(), None, 0, None, None, code)
                          for s in ("oscillation", "trend"))
    return rank_combos(combos)
