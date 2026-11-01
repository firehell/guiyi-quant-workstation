"""Project page estimates from the unified reader's completed physical prefixes."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal
from zoneinfo import ZoneInfo

from guiyi_quant.newow.page_performance import (
    PageAction, PageBar, PageSegment, build_page_performance_material,
    project_page_performance_material,
)
from guiyi_quant.newow.product_adapters import (
    build_product_identity, iter_label_calculation_segments, iter_replay_strategy_steps,
)
from guiyi_quant.newow.product_contracts import (
    ActionKind, LifecycleInputDigest, ProductStrategy, TradeEligibility,
)

from app.reference_trading.json_spool import JsonSpoolSequence


_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise ValueError("REFERENCE_PAGE_MATERIAL_INTERRUPTED")


class _CancellableSequence(Sequence):
    """Keep core validation scans responsive without copying sealed inputs."""

    def __init__(self, values: Sequence, cancelled: Callable[[], bool] | None):
        self._values = values
        self._cancelled = cancelled

    def __len__(self) -> int:
        return len(self._values)

    def __getitem__(self, index):
        return self._values[index]

    def __iter__(self):
        for index, item in enumerate(self._values):
            if index % 256 == 0:
                _check_cancelled(self._cancelled)
            yield item


def _encode_page_bar(item: PageBar) -> dict[str, object]:
    return {
        "date": item.date, "high": str(item.high), "low": str(item.low),
        "close": str(item.close), "observation_eligible": item.observation_eligible,
        "trading_day": item.trading_day,
    }


def _decode_page_bar(raw: object) -> PageBar:
    if not isinstance(raw, dict) or set(raw) != {
        "date", "high", "low", "close", "observation_eligible", "trading_day",
    } or not isinstance(raw["date"], str) or type(raw["observation_eligible"]) is not bool:
        raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
    day = raw["trading_day"]
    if day is not None and not isinstance(day, str):
        raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
    return PageBar(raw["date"], Decimal(raw["high"]), Decimal(raw["low"]),
                   Decimal(raw["close"]), raw["observation_eligible"], day)


def _new_page_spool() -> JsonSpoolSequence[PageBar]:
    return JsonSpoolSequence[PageBar](encode=_encode_page_bar, decode=_decode_page_bar)


def _fusion_page_actions(read, identity, replays, cancelled=None):
    actions: dict[tuple[str, str, str | None], list[PageAction]] = {}
    supplied = dict(replays or {})
    for strategy in (ProductStrategy.OSCILLATION, ProductStrategy.TREND):
        if strategy in supplied:
            action_iter = iter(supplied[strategy].actions)
        else:
            source_identity = build_product_identity(
                identity.product, strategy, identity.frequency,
                input_quality_policy=identity.input_quality_policy,
            )
            action_iter = (
                action for frame, _ in iter_replay_strategy_steps(
                    source_identity, _CancellableSequence(read.replay_bars, cancelled),
                    lifecycle_evidence=read.lifecycle_evidence,
                    data_interruptions=read.data_interruptions,
                ) for action in frame.actions
            )
        for index, action in enumerate(action_iter):
            if index % 256 == 0:
                _check_cancelled(cancelled)
            allowed = (TradeEligibility.ELIGIBLE, TradeEligibility.NO_ELIGIBLE_ENTRY)
            if strategy is ProductStrategy.TREND:
                allowed = (*allowed, TradeEligibility.INITIAL_CLEAR_NO_ENTRY)
            if (action.trade_eligibility not in allowed
                or action.kind not in (ActionKind.BUILD, ActionKind.CLEAR)):
                continue
            owner = (action.physical_contract, action.segment_id,
                     action.calculation_segment_id)
            actions.setdefault(owner, []).append(PageAction(
                action.bar_end.astimezone(_SHANGHAI).isoformat(),
                "buy" if action.kind is ActionKind.BUILD else "sell",
                action.reference_price,
            ))
    return actions


def build_page_material(read, identity, resolved, *, fusion=False, replays=None,
                        cancelled: Callable[[], bool] | None = None):
    """Build cutoff-locked page material without retaining ProductBar arrays.

    Warm-up prefixes remain inside their own physical/calculation owner. A final
    source boundary/gap invalidates terminal marking instead of closing a trade.
    """
    digest = LifecycleInputDigest()
    grouped: list[tuple[tuple[str, str, str | None], JsonSpoolSequence[PageBar]]] = []
    current_owner: tuple[str, str, str | None] | None = None
    current_bars: JsonSpoolSequence[PageBar] | None = None
    last = None
    latest_replay = None
    try:
        _check_cancelled(cancelled)
        for input_index, item in enumerate(iter_label_calculation_segments(
            identity, read.replay_bars, read.data_interruptions,
        )):
            if input_index % 256 == 0:
                _check_cancelled(cancelled)
            if item.bar.bar_end > resolved.cutoff:
                continue
            digest.add(item)
            latest_replay = max(latest_replay or item.bar.bar_end, item.bar.bar_end)
            owner = (item.bar.physical_contract, item.bar.segment_id,
                     item.calculation_segment_id)
            if owner != current_owner:
                if current_bars is not None:
                    current_bars.seal()
                current_bars = _new_page_spool()
                try:
                    grouped.append((owner, current_bars))
                except BaseException:
                    current_bars.close()
                    raise
                current_owner = owner
            if current_bars is None:
                raise ValueError("REFERENCE_PAGE_MATERIAL_INVALID")
            current_bars.append(PageBar(
                item.bar.bar_end.astimezone(_SHANGHAI).isoformat(),
                item.bar.high, item.bar.low, item.bar.close,
                item.bar.observation_eligible, item.bar.trading_day.isoformat(),
            ))
            if item.bar.observation_eligible:
                last = max(last or item.bar.bar_end, item.bar.bar_end)
        if current_bars is not None:
            current_bars.seal()

        _check_cancelled(cancelled)
        actions = _fusion_page_actions(read, identity, replays, cancelled) if fusion else {}
        terminal_blocked = last is None or not resolved.complete or any(
            gap.effective_at <= resolved.cutoff and gap.effective_at >= last
            for gap in read.data_interruptions)
        if last is not None:
            terminal_blocked = terminal_blocked or any(
                boundary.effective_at <= resolved.cutoff and boundary.effective_at >= last
                for boundary in read.boundaries)
        segments = []
        for index, (owner, bars) in enumerate(grouped):
            _check_cancelled(cancelled)
            candidates = actions.get(owner, ())
            if candidates:
                candidate_dates = {action.date for action in candidates}
                matched_dates = set()
                for bar_index, bar in enumerate(bars):
                    if bar_index % 256 == 0:
                        _check_cancelled(cancelled)
                    if bar.date in candidate_dates:
                        matched_dates.add(bar.date)
                selected_actions = tuple(action for action in candidates
                                         if action.date in matched_dates)
            else:
                selected_actions = ()
            segments.append(PageSegment(
                "|".join(str(value) for value in owner), bars,
                index == len(grouped) - 1 and not terminal_blocked
                and bool(bars) and bars[-1].observation_eligible,
                selected_actions,
            ))
        material = build_page_performance_material(
            segments, "fusion" if fusion else identity.strategy.value,
            period=identity.frequency.value, cancelled=cancelled,
        )
        from app.market_data.newow.product_reader import has_unresolved_source_tail
        _check_cancelled(cancelled)
        return {
            "schema": "newow_page_material_envelope_v1",
            "has_unresolved_tail_gap": has_unresolved_source_tail(
                read.data_interruptions, as_of=resolved.cutoff, latest_bar_end=latest_replay),
            "coverage": {
                "data_interruptions": [
                    {
                        "product": gap.product,
                        "frequency": gap.frequency.value,
                        "physical_contract": gap.physical_contract,
                        "segment_id": gap.segment_id,
                        "trading_day": gap.trading_day.isoformat(),
                        "effective_at": gap.effective_at.isoformat(),
                        "source_identity": gap.source_identity,
                    }
                    for gap in read.data_interruptions
                    if gap.effective_at <= resolved.cutoff
                ],
            },
            "material": material,
            "input_sha256": digest.hexdigest(),
            "source_evidence_sha256": read.reference_source_evidence_sha256,
        }
    finally:
        for _, bars in grouped:
            bars.close()


def project_page_material(envelope, *, since, through, selected_mode=None):
    """Apply a preset window to cutoff-locked, source-bound page material."""
    if (not isinstance(envelope, dict)
        or envelope.get("schema") != "newow_page_material_envelope_v1"
        or not isinstance(envelope.get("input_sha256"), str)
        or not isinstance(envelope.get("source_evidence_sha256"), (str, type(None)))):
        raise ValueError("NEWOW_PAGE_MATERIAL_INVALID")
    result = project_page_performance_material(
        envelope["material"], since=since, through=through,
        selected_mode=selected_mode,
    )
    result["input_sha256"] = envelope["input_sha256"]
    result["source_evidence_sha256"] = envelope["source_evidence_sha256"]
    return result


def project_page_performance(read, identity, resolved, *, fusion=False, replays=None,
                             selected_mode=None):
    """Keep the ordinary reader path on the exact material projection kernel."""
    return project_page_material(
        build_page_material(read, identity, resolved, fusion=fusion, replays=replays),
        since=resolved.requested_since.isoformat(),
        through=resolved.requested_through.isoformat(),
        selected_mode=selected_mode,
    )
