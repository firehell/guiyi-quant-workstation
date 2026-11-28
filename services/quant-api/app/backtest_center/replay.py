"""Locate recorded trade evidence on the chart saved with a Run."""

from bisect import bisect_left
from datetime import datetime, timedelta


def fill_roles(trade: dict) -> dict:
    roles = {}
    for leg, kind in (("entry", "ENTRY"), ("exit", "EXIT")):
        linked = trade.get(f"native_{leg}_ids")
        if linked is not None and not isinstance(linked, list):
            raise ValueError("RUN_CHART_EVIDENCE_MISMATCH")
        ids = list(linked or ())
        if native_id := trade.get(f"native_{leg}_id"):
            ids.append(native_id)
        for native_id in ids:
            if not isinstance(native_id, str) or not native_id:
                raise ValueError("RUN_CHART_EVIDENCE_MISMATCH")
            if roles.setdefault(native_id, kind) != kind:
                roles[native_id] = None
    return roles


def scoped_chart(bars: list, markers: list, contract: str, config: dict, snapshot: dict) -> tuple[list, list]:
    recorded_contract = snapshot.get("physical_contract") or config["contract"]
    if config["contract_selection"] == "physical" and not contract == config["contract"] == recorded_contract:
        raise ValueError("RUN_CHART_EVIDENCE_MISMATCH")
    scope = {"data_revision": snapshot["data_revision"], "input_sha256": snapshot["input_sha256"],
             "frequency": config["signal_frequency"]}
    selected = []
    for rows in (bars, markers):
        matching = [row for row in rows if row.get("contract", recorded_contract) == contract]
        if any(row.get(field, expected) != expected for row in matching for field, expected in scope.items()):
            raise ValueError("RUN_CHART_EVIDENCE_MISMATCH")
        selected.append(matching)
    return tuple(selected)


def chart_window(bars: list, markers: list, trade: dict, fills: list, roles: dict, frequency: str) -> tuple[list, list]:
    if not bars:
        return [], []
    start = trade.get("entry_at")
    open_position = trade.get("status") in ("OPEN", "ROLLOVER_INTERRUPTED")
    closing_fill = None if open_position else trade.get("exit_at")
    stop = closing_fill or trade.get("marked_at") or trade.get("valuation_at")
    if not start or not stop:
        return [], []
    times = [datetime.fromisoformat(bar["at"]) for bar in bars]
    entry, end = datetime.fromisoformat(start), datetime.fromisoformat(stop)
    if (entry.utcoffset() is None or end.utcoffset() is None or any(t.utcoffset() is None for t in times)
            or any(left >= right for left, right in zip(times, times[1:]))):
        raise ValueError("RUN_CHART_EVIDENCE_MISMATCH")
    bucket = timedelta(minutes=int(frequency[:-1])) if frequency.endswith("m") else timedelta(0)
    first, last = bisect_left(times, entry), bisect_left(times, end)
    if last == len(times) and not closing_fill and times[-1].date() == end.astimezone(times[-1].tzinfo).date():
        last -= 1  # A daily valuation can follow the last intraday bucket.
    if (first == len(times) or last == len(times) or last < first or end < entry
            or times[first] - entry > bucket or closing_fill and times[last] - end > bucket):
        return [], []
    lo = max(0, first - 25)
    hi = min(len(times), last + 26)
    scoped = []
    for marker in markers:
        if marker.get("native_trade_id") in roles:
            continue
        marker_at = datetime.fromisoformat(marker["at"])
        anchor = bisect_left(times, marker_at)
        if lo <= anchor < hi and marker_at >= times[lo] and times[anchor] - marker_at <= bucket:
            scoped.append({**marker, "event_at": marker["at"], "at": bars[anchor]["at"]})

    if roles:
        if set(roles.values()) - {"ENTRY", "EXIT"} or {fill["native_trade_id"] for fill in fills} != roles.keys():
            raise ValueError("RUN_CHART_EVIDENCE_MISMATCH")
        if len(fills) != len(roles):
            raise ValueError("RUN_CHART_EVIDENCE_MISMATCH")
        for fill in fills:
            native_id = fill["native_trade_id"]
            kind = roles[native_id]
            at = datetime.fromisoformat(fill["modeled_fill_at"])
            anchor = bisect_left(times, at)
            allowed_effects = ("OPEN",) if kind == "ENTRY" else ("CLOSE", "CLOSE_TODAY")
            if (not entry <= at <= end or not first <= anchor <= last or times[anchor] - at > bucket
                    or fill.get("position_effect") not in allowed_effects
                    or type(fill.get("quantity")) is not int or fill["quantity"] <= 0):
                raise ValueError("RUN_CHART_EVIDENCE_MISMATCH")
            scoped.append({"at": bars[anchor]["at"], "event_at": at.isoformat(), "kind": kind,
                           "price": fill["price"], "quantity": fill["quantity"], "label": kind,
                           "trade_id": trade["trade_id"], "native_trade_id": native_id})
    else:
        # Older archives can link a paired record without a separate list of execution legs.
        for leg, kind, event_at, anchor in (("entry", "ENTRY", entry, first), ("exit", "EXIT", end, last)):
            if leg == "entry" or closing_fill:
                scoped.append({"at": bars[anchor]["at"], "event_at": event_at.isoformat(), "kind": kind,
                               "price": trade.get(f"{leg}_price"), "label": kind, "trade_id": trade["trade_id"]})
    if not closing_fill and trade.get("mark_price") is not None:
        scoped.append({"at": bars[last]["at"], "event_at": end.isoformat(), "kind": "VALUATION",
                       "price": trade["mark_price"], "label": "VALUATION", "trade_id": trade["trade_id"]})
    scoped.sort(key=lambda item: datetime.fromisoformat(item["event_at"]))
    return [dict(bar, in_position=first <= index <= last) for index, bar in enumerate(bars[lo:hi], lo)], scoped
