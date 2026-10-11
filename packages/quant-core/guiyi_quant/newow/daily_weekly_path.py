"""Independent completed W1/D1/60m illustration; never executable price predictions."""

from .cross_period_prices import PriceSource

VERSION = "guiyi_daily_weekly_path_v2"


def build_daily_weekly_path(*, as_of, current, periods):
    rows = []
    for frequency in ("1w", "1d", "60m"):
        state, frames, target = periods.get(frequency, (None, (), None))
        row = {
            "frequency": frequency,
            "state": state,
            "status": "unavailable",
            "cost": None,
            "current": None,
            "target": None,
            "reason": "PERIOD_CONTEXT_UNAVAILABLE",
        }
        if state is None or not frames or current is None:
            rows.append(row)
            continue
        tail = frames[-1].bar
        owner = (tail.bar.physical_contract, tail.bar.segment_id)
        calc = tail.calculation_segment_id
        if (
            (current.physical_contract, current.segment_id) != owner
            or current.bar_end > as_of
            or current.source_category != "canonical_completed_close"
            or (current.frequency == frequency and current.calculation_segment_id != calc)
            or not tail.bar.observation_eligible
            or tail.bar.bar_end > as_of
        ):
            rows.append(row)
            continue
        row["current"] = current.wire()
        valid_target = (
            target is not None
            and target.frequency == frequency
            and target.source_category == "canonical_channel"
            and target.bar_end == tail.bar.bar_end
            and target.bar_end <= as_of
            and (
                target.physical_contract,
                target.segment_id,
                target.calculation_segment_id,
            )
            == (*owner, calc)
        )
        row["target"] = target.wire() if valid_target else None
        open_entries = {}
        cleared_entry = None
        for frame in frames:
            if (
                not frame.bar.bar.observation_eligible
                or frame.bar.bar.bar_end > as_of
                or (
                    frame.bar.bar.physical_contract,
                    frame.bar.bar.segment_id,
                    frame.bar.calculation_segment_id,
                )
                != (*owner, calc)
            ):
                continue
            for action in frame.actions:
                if action.bar_end > as_of or (
                    action.physical_contract,
                    action.segment_id,
                    action.calculation_segment_id,
                ) != (*owner, calc):
                    continue
                if action.kind.value == "BUILD":
                    open_entries[action.signal_id] = (action, frame.bar)
                elif action.kind.value == "CLEAR":
                    cleared_entry = open_entries.pop(action.related_build_id, None)
        active = state in ("buy", "hold")
        candidates = open_entries if active else ({"closed": cleared_entry} if state == "sell" and cleared_entry else {})
        # Exactly one unmatched identity is required; ambiguous/missing entry is not guessed.
        if (
            len(candidates) == 1
            and next(iter(candidates.values()))[0].bar_end <= current.bar_end
        ):
            entry, bar = next(iter(candidates.values()))
            cost = PriceSource(
                entry.reference_price,
                frequency,
                entry.bar_end,
                entry.physical_contract,
                entry.segment_id,
                calc,
                bar.bar.source_identity,
                "canonical_strategy_build",
            )
            row["cost"] = {**cost.wire(), "entry_marker_id": entry.signal_id}
        row["status"] = (
            "ready" if valid_target and (not active or row["cost"]) else "partial"
        )
        row["reason"] = (
            "FLAT_NO_OPEN_ENTRY"
            if not active and row["cost"] is None
            else "OPEN_ENTRY_UNAVAILABLE"
            if row["cost"] is None
            else "TARGET_UNAVAILABLE"
            if not valid_target
            else None
        )
        rows.append(row)
    return {
        "version": VERSION,
        "as_of": as_of.isoformat(),
        "page_parity": True,
        "executable": False,
        "periods": rows,
        "source_note": "独立周、日、60分钟趋势 BUILD 参考成本与同周期 Canonical HHV10 目标（期货适配，非牛哇私有 batch 价格）；页面示意，不保证未来路径，不代表成交。",
    }
