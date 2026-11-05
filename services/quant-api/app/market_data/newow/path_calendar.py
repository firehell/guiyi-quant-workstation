"""Bounded, request-local Calendar/Session projection; never downloads future facts."""
from datetime import timedelta
from hashlib import sha256
import json
from math import ceil


def unavailable(reason):
    return {"identity": sha256(reason.encode()).hexdigest(), "reason": reason}


def read_path_calendar(market_data, *, product, origin, as_of, now):
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("Asia/Shanghai")
    if as_of.astimezone(zone).date() != now.astimezone(zone).date():
        return unavailable("HISTORICAL_CALENDAR_PROOF_MISSING")
    try:
        through = origin + timedelta(days=366)
        rows = market_data.calendar_day_facts(symbol=product, since=origin, through=through)
        mapping = dict(rows)
        if len(mapping) != len(rows) or origin not in mapping:
            return unavailable("CALENDAR_INCOMPLETE")
        prefix_end = origin
        while prefix_end < through and prefix_end + timedelta(days=1) in mapping:
            prefix_end += timedelta(days=1)
        previous = market_data.previous_trading_day(product, origin)
        metadata = market_data.historical_metadata_evidence(symbol=product, since=previous, through=prefix_end)
        proved_rows = {day: is_open for day, is_open, *_ in metadata["calendar"]}
        if any(proved_rows.get(day.isoformat()) != mapping[day]
               for day in mapping if origin <= day <= prefix_end):
            return unavailable("CALENDAR_SOURCE_CHANGED")
        def verify():
            current = market_data.historical_metadata_evidence(symbol=product, since=previous, through=prefix_end)
            if current != metadata:
                raise ValueError("calendar/session source changed")
        identity = sha256(json.dumps([product, str(origin), rows, metadata], sort_keys=True, default=str).encode()).hexdigest()
        return {"identity": identity, "reason": None, "origin": origin,
                "rows": dict(rows), "verify": verify, "sessions": lambda day: market_data.session_windows(symbol=product, trading_day=day)}
    except Exception:
        return unavailable("CALENDAR_PROOF_UNAVAILABLE")


def apply_path_date(path, context, origin):
    eta = path.get("eta")
    if not eta or eta.get("status") != "ready":
        return
    context = context or unavailable("CALENDAR_PROOF_UNAVAILABLE")
    eta["date_reason"] = context.get("reason")
    if eta["date_reason"]:
        return
    weekly = eta["unit"] == "周"
    steps = ceil(eta["remain"] * (7 if weekly else 1))
    if steps > 366:
        eta["date_reason"] = "CALENDAR_HORIZON_EXCEEDED"
        return
    rows = context["rows"]
    remaining = steps
    for offset in range(367):
        day = origin + timedelta(days=offset)
        if day not in rows:
            eta["date_reason"] = "CALENDAR_INCOMPLETE"
            return
        if rows[day]:
            try:
                windows = context["sessions"](day)
                if not windows or any(w.end <= w.start for w in windows):
                    raise ValueError()
            except Exception:
                eta["date_reason"] = "SESSION_INCOMPLETE"
                return
            if (weekly and offset >= steps) or (not weekly and remaining == 0):
                try:
                    if context.get("verify"):
                        context["verify"]()
                except Exception:
                    eta["date_reason"] = "CALENDAR_SOURCE_CHANGED"
                    return
                eta.update(date=day.isoformat(), date_status="ready", date_reason=None,
                           date_source={"identity": context["identity"], "origin_trading_day": origin.isoformat(), "policy": "futures_calendar_ceil_v1"})
                return
            if not weekly:
                remaining -= 1
    eta["date_reason"] = "CALENDAR_HORIZON_EXCEEDED"
