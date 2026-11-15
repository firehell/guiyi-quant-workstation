"""Read-only six-combination page analysis via the existing validated reader."""
from dataclasses import dataclass
from datetime import date, datetime
from itertools import groupby
from hashlib import sha256
import json

from guiyi_quant.newow.ai_analysis import AnalysisCombo, estimate_segments, rank_combos
from guiyi_quant.newow.four_step import (
    FourStepEvent, FourStepSummary, MODEL_VERSION, FUTURES_ADAPTER_VERSION,
    PAGE_MIN_BARS, PAGE_SOURCE_SHA256, fold_four_step, summarize_four_step,
)
from guiyi_quant.newow.product_adapters import build_product_identity, iter_label_calculation_segments, iter_replay_strategy_steps
from guiyi_quant.newow.product_contracts import ActionKind, ProductFrequency, ProductStrategy, TradeEligibility, lifecycle_input_sha256
from .product_query import NewowProductQuery
from .product_reader import NewowProductReadError

# Public AI fetchKlineForAI's period-specific windows, explicitly exposed in UI.
STARTS = ((ProductFrequency.WEEKLY, date(2024, 6, 1)), (ProductFrequency.DAILY, date(2025, 9, 1)), (ProductFrequency.HOURLY, date(2026, 4, 1)))


@dataclass(frozen=True, slots=True)
class FourStepAnalysis:
    since: str
    through: str | None
    source_bars: int
    input_sha256: str | None
    summary: FourStepSummary | None
    page_baseline: FourStepSummary | None
    reason_code: str | None
    model_version: str = MODEL_VERSION
    futures_adapter_version: str = FUTURES_ADAPTER_VERSION
    page_source_sha256: str = PAGE_SOURCE_SHA256


@dataclass(frozen=True, slots=True)
class ProductAnalysis:
    combos: tuple[AnalysisCombo, ...]
    four_step: FourStepAnalysis | None


def _owner(bar):
    return bar.bar.physical_contract, bar.bar.segment_id, bar.calculation_segment_id


def _four_step_analysis(product, read, bars, since, through, digest, cancelled):
    scope = (since.isoformat(), through, len(bars), digest)
    if len(bars) < PAGE_MIN_BARS:
        return FourStepAnalysis(*scope, None, None, "NEWOW_FOUR_STEP_INSUFFICIENT_BARS")
    owners = {}
    index = {}
    inputs = {bar.bar.bar_end for bar in bars}
    trend_identity = build_product_identity(
        product, ProductStrategy.TREND, ProductFrequency.DAILY, input_quality_policy=read.input_quality_policy,
    )
    labeled = (bar for bar in iter_label_calculation_segments(
        trend_identity, read.replay_bars, read.data_interruptions,
    ) if bar.bar.observation_eligible and bar.bar.bar_end in inputs)
    for owner, group in groupby(labeled, key=_owner):
        rows = tuple(group)
        owners[owner] = (rows, [])
        index.update(((owner, row.bar.bar_end), i) for i, row in enumerate(rows))
    for strategy in (ProductStrategy.OSCILLATION, ProductStrategy.TREND):
        identity = build_product_identity(
            product, strategy, ProductFrequency.DAILY, input_quality_policy=read.input_quality_policy,
        )
        for frame, _ in iter_replay_strategy_steps(
            identity, read.replay_bars, lifecycle_evidence=read.lifecycle_evidence,
            data_interruptions=read.data_interruptions,
        ):
            if cancelled():
                from .product_reader import NewowProductReadCancelled
                raise NewowProductReadCancelled("NEWOW_READ_CANCELLED")
            for action in frame.actions:
                owner = action.physical_contract, action.segment_id, action.calculation_segment_id
                position = index.get((owner, action.bar_end))
                if position is None or action.kind not in (ActionKind.BUILD, ActionKind.CLEAR):
                    continue
                if action.trade_eligibility not in (
                    TradeEligibility.ELIGIBLE, TradeEligibility.NO_ELIGIBLE_ENTRY,
                    TradeEligibility.INITIAL_CLEAR_NO_ENTRY,
                ):
                    continue
                owners[owner][1].append(FourStepEvent(
                    position, strategy.value, action.kind.value, action.reference_price, action.sequence,
                ))
    replays = [fold_four_step(len(rows), rows[-1].bar.close, events, minimum_bars=1)
               for rows, events in owners.values()]
    summary = summarize_four_step(trade for replay in replays for trade in replay.trades)
    baseline = summarize_four_step(trade for replay in replays for trade in replay.page_baseline)
    return FourStepAnalysis(*scope, summary, baseline, None if summary else "NEWOW_FOUR_STEP_NO_ENTRIES")


def analysis_input_sha256(bars, quality_policy):
    if not bars:
        return None
    payload = {"lifecycle_input_sha256": lifecycle_input_sha256(bars),
               "input_quality_policy": str(quality_policy),
               "calculation_segments": [(b.bar.segment_id, b.calculation_segment_id, b.source_bar_sha256) for b in bars]}
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def analyze_product(product: str, as_of: datetime, reader_factory, cancelled, enforce_frequency, *, include_four_step=True):
    combos = []
    four_step = None
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
            if include_four_step and frequency is ProductFrequency.DAILY:
                four_step = _four_step_analysis(product, read, bars, since, through, digest, cancelled)
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
            if include_four_step and frequency is ProductFrequency.DAILY:
                four_step = FourStepAnalysis(since.isoformat(), None, 0, None, None, None, code)
    return ProductAnalysis(rank_combos(combos), four_step)
