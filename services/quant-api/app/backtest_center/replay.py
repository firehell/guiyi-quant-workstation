"""Pick a reproducible chart window from the Run's saved chart output."""

from bisect import bisect_left
from datetime import datetime, timedelta


def chart_window(bars: list, markers: list, trade: dict) -> tuple[list, list]:
    if not bars:
        return [], []
    start = trade.get("entry_at")
    closing_fill = trade.get("exit_at")
    stop = closing_fill or trade.get("marked_at") or trade.get("valuation_at")
    if not start or not stop:
        return [], []
    times = [datetime.fromisoformat(bar["at"]) for bar in bars]
    entry, exit = datetime.fromisoformat(start), datetime.fromisoformat(stop)
    first, last = bisect_left(times, entry), bisect_left(times, exit)
    if last == len(times) and not closing_fill and times[-1].date() == exit.date():
        last -= 1  # Settlement may be after the last chart bar of the trading day.
    if (first == len(times) or last == len(times) or last < first or exit < entry
            or times[first] - entry > timedelta(minutes=5)
            or closing_fill and times[last] - exit > timedelta(minutes=5)):
        return [], []
    lo = max(0, first - 25)
    hi = min(len(times), last + 26)
    scoped = []
    selected_ids = {key for key in (trade.get("native_entry_id"), trade.get("native_exit_id")) if key is not None}
    plotted = set()
    for marker in markers:
        marker_at = datetime.fromisoformat(marker["at"])
        anchor = bisect_left(times, marker_at)
        if lo <= anchor < hi and marker_at >= times[lo]:
            native_id = marker.get("native_trade_id")
            selection = {"trade_id": trade["trade_id"]} if native_id in selected_ids else {}
            if selection:
                plotted.add(native_id)
            scoped.append({**marker, **selection, "event_at": marker["at"], "at": bars[anchor]["at"]})
    for prefix, kind, event_at, anchor in (
        ("entry", "ENTRY", entry, first), ("exit", "EXIT", exit, last),
    ):
        if (prefix == "exit" and not closing_fill) or trade.get(f"native_{prefix}_id") in plotted:
            continue
        scoped.append({"at": bars[anchor]["at"], "event_at": event_at.isoformat(), "kind": kind,
                       "price": trade.get(f"{prefix}_price"), "label": kind, "trade_id": trade["trade_id"]})
    return [dict(bar, in_position=first <= index <= last) for index, bar in enumerate(bars[lo:hi], lo)], scoped
