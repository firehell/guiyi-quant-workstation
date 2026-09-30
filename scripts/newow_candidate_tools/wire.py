"""Exact actual XHR bindings and completed physical bars shared by offline audits."""

import re
from .context import Candidate, instant, need


def validate_binding(binding: dict, url: str, http: int) -> None:
    need(
        isinstance(binding, dict)
        and binding.get("evidence_kind") == "xhr_response_text_compact"
        and binding.get("url") == url
        and binding.get("http") == http
        and all(
            type(binding.get(k)) is int and binding[k] > 0
            for k in (
                "xhr_sequence",
                "node_request_id",
                "started_order",
                "completed_order",
                "started_at",
                "completed_at",
                "response_text_chars",
            )
        )
        and binding["started_order"] < binding["completed_order"]
        and binding["started_at"] <= binding["completed_at"],
        "ACTUAL_XHR_BINDING_IDENTITY",
    )


def validate_bars(candidate: Candidate, part: dict) -> list:
    bars = (part.get("value") or {}).get("bars", [])
    need(
        part.get("delivery") == "delivered"
        and part.get("status", {}).get("status") == "ready"
        and isinstance(bars, list)
        and bool(bars),
        "ACTUAL_CHART_NOT_READY",
    )
    ends = [instant(b["bar_end"]) for b in bars]
    need(
        all(a < b for a, b in zip(ends, ends[1:]))
        and all(
            t < instant(candidate.as_of)
            and b.get("completed") is True
            and b.get("observation_eligible") is True
            and re.fullmatch(
                re.escape(candidate.product.upper()) + r"\d{3,4}",
                str(b.get("physical_contract", "")),
            )
            and b.get("segment_id")
            and b.get("source_identity")
            and b.get("trading_day")
            for t, b in zip(ends, bars)
        ),
        "CHART_COMPLETED_PHYSICAL_BARS",
    )
    return bars
