"""Bounded Web projections of one verified Newow reference result.

The complete calculation stays authoritative. These projections never derive a
summary from sampled chart points or a paginated history response.
"""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
import math
from typing import Any
from zoneinfo import ZoneInfo


_MAX_POINTS = 2000
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_COMMON = (
    "performance_since", "performance_through", "actual_available_through",
    "reference_cutoff", "reference_input_sha256", "history_coverage",
    "storage_mode", "executable", "auto_order", "allowed_uses",
    "record_since", "records_window_limited",
)


def _curve_points(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Retain endpoints, extrema and every physical/gap boundary exactly."""
    total = len(points)
    if total <= _MAX_POINTS:
        return {"points": [{**point, "position": index} for index, point in enumerate(points)],
                "total_points": total, "sampled": False}
    mandatory = {0, total - 1}
    for index in range(1, total):
        left, right = points[index - 1], points[index]
        if (left.get("segment_id") != right.get("segment_id")
            or left.get("physical_contract") != right.get("physical_contract")
            or left.get("calculation_segment_id") != right.get("calculation_segment_id")
            or (left.get("value") is None) != (right.get("value") is None)
            or left.get("status") in {"INTERRUPTED", "GAP"}
            or right.get("status") in {"INTERRUPTED", "GAP"}):
            mandatory.update((index - 1, index))
    if len(mandatory) > _MAX_POINTS:
        raise ValueError("NEWOW_REFERENCE_CURVE_BUDGET_EXCEEDED")
    # Each bucket contributes both extrema where budget permits. Decimal keeps
    # the original percentage-point values and avoids display-rounding ties.
    remaining = _MAX_POINTS - len(mandatory)
    if remaining:
        bucket_count = max(1, remaining // 2)
        for bucket in range(bucket_count):
            start = bucket * total // bucket_count
            stop = (bucket + 1) * total // bucket_count
            eligible = [index for index in range(start, stop) if index not in mandatory
                        and points[index].get("value") is not None]
            if not eligible:
                continue
            minimum = min(eligible, key=lambda index: (Decimal(str(points[index]["value"])), index))
            maximum = max(eligible, key=lambda index: (Decimal(str(points[index]["value"])), -index))
            mandatory.update((minimum, maximum))
        if len(mandatory) < _MAX_POINTS:
            slots = _MAX_POINTS - len(mandatory)
            for step in range(1, slots + 1):
                mandatory.add(step * (total - 1) // (slots + 1))
    selected = sorted(mandatory)
    if len(selected) > _MAX_POINTS:
        raise ValueError("NEWOW_REFERENCE_CURVE_BUDGET_EXCEEDED")
    return {"points": [{**points[index], "position": index} for index in selected],
            "total_points": total, "sampled": True}


def _trade_curve(trades: list[dict[str, Any]], *, theoretical: dict | None = None) -> list[dict[str, Any]]:
    closed = sorted((trade for trade in trades if trade["status"] == "CLOSED"
                     and trade["statistics_membership"] == "entry_in_window_v1"),
                    key=lambda trade: (trade["exit_bar_end"], trade["reference_trade_id"]))
    theory = None if theoretical is None else {
        row["reference_trade_id"]: row["return_pct"] for row in theoretical["returns"]
    }
    if theory is not None and (len(theory) != len(closed)
                               or set(theory) != {trade["reference_trade_id"] for trade in closed}):
        raise ValueError("NEWOW_REFERENCE_CURVE_IDENTITY_CONFLICT")
    cumulative = Decimal(0)
    output = []
    for trade in closed:
        return_pct = theory[trade["reference_trade_id"]] if theory is not None else trade["reference_return_pct"]
        if return_pct is None or trade["exit_bar_end"] is None:
            raise ValueError("NEWOW_REFERENCE_CURVE_IDENTITY_CONFLICT")
        cumulative += Decimal(str(return_pct))
        output.append({
            "bar_end": trade["exit_bar_end"], "trading_day": trade["exit_trading_day"],
            "physical_contract": trade["physical_contract"], "segment_id": trade["segment_id"],
            "reference_trade_id": trade["reference_trade_id"], "value": str(cumulative),
            "return_pct": str(return_pct),
            "trade": trade,
        })
    return output


def _annualized(start: str, end: str, days: float) -> str | None:
    before, after = float(start), float(end)
    if (not all(math.isfinite(value) for value in (before, after, days))
            or days <= 0 or before <= -100 or after <= -100):
        return None
    try:
        value = (((100 + after) / (100 + before)) ** (365 / days) - 1) * 100
    except (OverflowError, ZeroDivisionError, ValueError):
        return None
    return str(value) if math.isfinite(value) else None


def _calendar_day(raw: str) -> date:
    if len(raw) == 10:
        return date.fromisoformat(raw)
    timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if timestamp.utcoffset() is None:
        raise ValueError("NEWOW_REFERENCE_CURVE_IDENTITY_CONFLICT")
    return timestamp.astimezone(_SHANGHAI).date()


def _page_annuals(result: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    dates, equity, segments = (result[key] for key in ("dates", "equity", "segment_ids"))
    if not (len(dates) == len(equity) == len(segments)):
        raise ValueError("NEWOW_REFERENCE_CURVE_IDENTITY_CONFLICT")
    blocks: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        if not blocks or blocks[-1]["segment_id"] != segment:
            blocks.append({"segment_id": segment, "first": index, "last": index})
        else:
            blocks[-1]["last"] = index
    if len({block["segment_id"] for block in blocks}) != len(blocks):
        raise ValueError("NEWOW_REFERENCE_CURVE_IDENTITY_CONFLICT")
    annuals = []
    for block in blocks:
        first, last = block["first"], block["last"]
        days = (_calendar_day(dates[last]) - _calendar_day(dates[first])).days
        annuals.append({"segment_id": block["segment_id"], "since": dates[first],
                        "through": dates[last], "annualized_pct": _annualized(equity[first], equity[last], days)})
    if len(dates) < 2:
        return None, annuals
    span = (_calendar_day(dates[-1]) - _calendar_day(dates[0])).days
    return _annualized(equity[0], equity[-1], span), annuals


def _drawdown(points: list[dict[str, Any]]) -> str | None:
    if not points:
        return None
    peak = Decimal(100)
    greatest = Decimal(0)
    for point in points:
        raw = point.get("value")
        if raw is None:
            continue
        equity = Decimal(100) + Decimal(str(raw))
        peak = max(peak, equity)
        if peak > 0:
            greatest = max(greatest, (peak - equity) / peak * 100)
    return format(greatest.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _history_cursor(mode: str, value: dict[str, Any], token: str | None,
                    as_of: str, rows: list[dict[str, Any]], offset: int) -> str:
    proof = sha256(json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    payload = {"v": 1, "mode": mode, "token": token, "hash": value["reference_input_sha256"],
               "cutoff": str(value["reference_cutoff"]), "since": str(value["performance_since"]),
               "through": str(value["performance_through"]), "as_of": as_of,
               "rows": proof, "offset": offset}
    return urlsafe_b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")


def _history_offset(cursor: str | None, mode: str, value: dict[str, Any],
                    token: str | None, as_of: str, rows: list[dict[str, Any]]) -> int:
    if cursor is None:
        return 0
    if not 1 <= len(cursor) <= 2048:
        raise ValueError("NEWOW_CURSOR_INVALID")
    try:
        payload = json.loads(urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (ValueError, TypeError, Base64Error) as error:
        raise ValueError("NEWOW_CURSOR_INVALID") from error
    if not isinstance(payload, dict):
        raise ValueError("NEWOW_CURSOR_INVALID")
    expected = _history_cursor(mode, value, token, as_of, rows, payload.get("offset"))
    if cursor != expected or type(payload.get("offset")) is not int or not 0 <= payload["offset"] <= len(rows):
        raise ValueError("NEWOW_CURSOR_GENERATION_CONFLICT")
    return payload["offset"]


def _page_curve(page: dict[str, Any], kind: str) -> tuple[list[dict[str, Any]], dict | None]:
    result = page.get(kind)
    if result is None:
        return [], None
    points = [
        {"bar_end": at, "trading_day": day, "segment_id": segment,
         "value": equity}
        for at, day, segment, equity in zip(
            result["dates"], result["trading_days"], result["segment_ids"],
            result["equity"], strict=True,
        )
    ]
    return points, {"summary": result["summary"], "drawdown_kind": result.get("drawdown_kind"),
                    "period": result["period"]}


def _result_hash(value: dict[str, Any], selected: dict[str, Any], mode: str,
                 token: str | None, as_of: str, page_result: dict | None,
                 calculation_version: str) -> str:
    local_mode = mode.removeprefix("fusion_")
    selected_facts = (
        page_result if local_mode.startswith("page_") else
        selected.get("holding_curve") if local_mode == "holding" else
        selected.get("theoretical") if local_mode == "theoretical" else
        selected.get("curve") if mode.startswith("fusion_") else
        selected.get("curve_trades")
    )
    model_identity = (selected.get("page_performance") if page_result is not None else
                      selected.get("reference_model_version") if mode.startswith("fusion_") else None)
    proof = {
        "version": "newow_reference_split_result_v1", "mode": mode,
        "calculation_version": calculation_version,
        "window": [str(value["performance_since"]), str(value["performance_through"]),
                   str(value["reference_cutoff"])],
        "as_of": as_of, "token": token,
        "source": value["reference_input_sha256"],
        "base_result": value.get("result_identity_sha256"),
        "selected_facts": selected_facts,
        "selected_model_identity": model_identity,
        "selected_summary": selected.get("groups") if mode.startswith("fusion_") else value["summary"],
        "fusion_revision": selected.get("reference_revision") if mode.startswith("fusion_") else None,
    }
    return sha256(json.dumps(proof, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def project_reference_part(
    value: dict[str, Any], part: str, mode: str | None, *,
    history_before: str | None = None, snapshot_token: str | None = None,
    as_of: str = "", calculation_version: str = "",
) -> dict[str, Any]:
    if mode is None or (part != "history" and history_before is not None):
        raise ValueError("NEWOW_SECTION_PARAMETER_INVALID")
    common = {key: value[key] for key in _COMMON if key in value}
    common["reference_part"] = part
    common["reference_mode"] = mode
    fusion = mode.startswith("fusion_")
    selected = value.get("fusion_comparison") if fusion else value
    if not isinstance(selected, dict):
        raise ValueError("NEWOW_REFERENCE_CURVE_UNAVAILABLE")
    local_mode = mode.removeprefix("fusion_")
    page_mode = local_mode in {"page_ordinary", "page_ideal"}
    page = selected.get("page_performance") if page_mode else None
    page_result = page.get(local_mode.removeprefix("page_")) if isinstance(page, dict) else None
    if page_mode and not isinstance(page_result, dict):
        raise ValueError("NEWOW_REFERENCE_CURVE_UNAVAILABLE")
    common["result_hash"] = _result_hash(value, selected, mode, snapshot_token, as_of,
                                          page_result, calculation_version)
    if page_mode:
        common["record_since"] = value["performance_since"]
        common["records_window_limited"] = False
    elif fusion and selected.get("record_since") is not None:
        common["record_since"] = selected["record_since"]
        common["records_window_limited"] = str(selected["record_since"]) > str(value["performance_since"])
    else:
        common["record_since"] = value.get("record_since", value["performance_since"])
        common["records_window_limited"] = value.get("records_window_limited", False)
    recent_source = (list(reversed(page_result["trades"])) if page_mode
                     else selected.get("items", []))
    overview = {}
    if part in {"overview", "panel"}:
        page_summaries = ({local_mode.removeprefix("page_"): page_result["summary"]}
                          if page_mode else {})
        overview = {"summary": value["summary"],
                "unavailable_days": value["unavailable_days"],
                "coverage_intervals": value["coverage_intervals"],
                "recent_items": recent_source[:3], "page_summaries": page_summaries,
                **({"fusion_groups": selected["groups"]} if fusion else {})}
        if part == "overview":
            return {**common, **overview}
    if part == "history":
        if page_mode or (fusion and value.get("storage_mode") != "persisted"):
            offset = _history_offset(history_before, mode, value, snapshot_token, as_of, recent_source)
            rows = recent_source[offset:offset + 50]
            next_before = (_history_cursor(mode, value, snapshot_token, as_of,
                                           recent_source, offset + len(rows))
                           if offset + len(rows) < len(recent_source) else None)
        else:
            rows = selected.get("items", [])[:50]
            next_before = selected.get("next_cursor") if fusion else value["next_before"]
        return {**common, "items": rows, "next_before": next_before}
    if part not in {"curve", "panel"}:
        raise ValueError("NEWOW_SECTION_PARAMETER_INVALID")
    extra: dict[str, Any] = {}
    if local_mode in {"page_ordinary", "page_ideal"}:
        page = selected.get("page_performance")
        if not isinstance(page, dict):
            raise ValueError("NEWOW_REFERENCE_CURVE_UNAVAILABLE")
        points, details = _page_curve(page, local_mode.removeprefix("page_"))
        extra.update(details or {})
        extra["model_version"] = page["version"]
        extra["source_identity"] = {"source_version": page["source_version"],
                                     "source_sha256": page["source_sha256"],
                                     "input_sha256": page["input_sha256"],
                                     "source_evidence_sha256": page["source_evidence_sha256"]}
        extra["annualized_pct"], extra["segment_annuals"] = _page_annuals(page_result)
        extra["metrics"] = {"return_percentage_points": page_result["summary"]["cumReturn"],
                            "win_rate_pct": str(page_result["summary"]["accuracy"]),
                            "closed_count": page_result["summary"]["tradeCount"],
                            "drawdown": page_result["summary"]["maxDrawdown"],
                            "drawdown_kind": page_result.get("drawdown_kind")}
    elif local_mode == "holding":
        holding = selected.get("holding_curve")
        if not isinstance(holding, dict):
            raise ValueError("NEWOW_REFERENCE_CURVE_UNAVAILABLE")
        points = [{**point, "value": point["marked_return_percentage_points"]}
                  for point in holding["points"]]
        valid_points = [point for point in points if point["value"] is not None]
        extra["model_version"] = holding["model_version"]
        extra["annualized_pct"] = (_annualized(valid_points[0]["value"], valid_points[-1]["value"],
                                   (datetime.fromisoformat(str(valid_points[-1]["bar_end"]).replace("Z", "+00:00"))
                                    - datetime.fromisoformat(str(valid_points[0]["bar_end"]).replace("Z", "+00:00"))).total_seconds() / 86400)
                                   if len(valid_points) >= 2 else None)
        if value["history_coverage"] != "FULL":
            extra["annualized_pct"] = None
        selected_summary = (next((group for group in selected["groups"] if group["model"] == "fusion"), {})
                            if fusion else value["summary"])
        extra["metrics"] = {"return_percentage_points": valid_points[-1]["value"] if valid_points else None,
                            "win_rate_pct": selected_summary.get("win_rate_pct"),
                            "closed_count": selected_summary.get("closed_count"),
                            "drawdown": _drawdown(points) if value["history_coverage"] == "FULL" else None,
                            "drawdown_kind": "equity_ratio"}
    else:
        trades = selected.get("curve") if fusion else selected.get("curve_trades")
        if not isinstance(trades, list):
            raise ValueError("NEWOW_REFERENCE_CURVE_UNAVAILABLE")
        theory = selected.get("theoretical") if local_mode == "theoretical" else None
        if local_mode == "theoretical" and not isinstance(theory, dict):
            raise ValueError("NEWOW_REFERENCE_CURVE_UNAVAILABLE")
        points = _trade_curve(trades, theoretical=theory)
        expected = (next((group["closed_count"] for group in selected["groups"] if group["model"] == "fusion"), None)
                    if fusion else value["summary"]["closed_count"])
        if expected != len(points):
            raise ValueError("NEWOW_REFERENCE_CURVE_IDENTITY_CONFLICT")
        extra["summary"] = theory if theory is not None else (
            next(group for group in selected["groups"] if group["model"] == "fusion")
            if fusion else value["summary"])
        effective = extra["summary"]
        total = (effective.get("sum_return_percentage_points") if isinstance(effective, dict) else None)
        closed_count = (effective.get("closed_count") if isinstance(effective, dict) else None)
        through = min(str(value["performance_through"]), str(value["actual_available_through"]))
        extra["annualized_pct"] = (_annualized("0", total,
            (date.fromisoformat(through) - date.fromisoformat(str(value["performance_since"]))).days)
            if points and total is not None and value["history_coverage"] == "FULL" else None)
        win_rate = effective.get("win_rate_pct") if isinstance(effective, dict) else None
        if win_rate is None and points:
            win_rate = str(sum(Decimal(point["return_pct"]) > 0 for point in points) * 100 / len(points))
        extra["metrics"] = {"return_percentage_points": total,
                            "win_rate_pct": win_rate,
                            "closed_count": closed_count if closed_count is not None else len(points),
                            "drawdown": _drawdown(points) if value["history_coverage"] == "FULL" else None,
                            "drawdown_kind": "equity_ratio"}
        extra["model_version"] = selected["reference_model_version"] if fusion else None
    return {**common, **overview, "reference_mode": mode,
            "curve": {"mode": mode, **_curve_points(points), **extra}}
