"""Offline numerical/wire/DOM audit. Never certifies visual review or production."""

from __future__ import annotations
import re
from urllib.parse import urlsplit, parse_qs, urlunsplit
from .context import Candidate, instant, need
from .curves import validate_curve_ui, record_ids_match
from .evidence import EvidenceStore, digest
from .wire import validate_binding, validate_bars


def candidate_get_url(url: str, candidate: Candidate, frequency: str) -> str:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    need(
        f"{parsed.scheme}://{parsed.netloc}"
        in (candidate.api_origin, candidate.web_origin)
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and parsed.path == "/api/v1/market/newow/strategy-detail"
        and query.get("product") == [candidate.product]
        and query.get("frequency") == [frequency]
        and query.get("section") == ["reference"],
        "GET_OUTSIDE_FROZEN_SCOPE",
    )
    origin = urlsplit(candidate.api_origin)
    return urlunsplit((origin.scheme, origin.netloc, parsed.path, parsed.query, ""))


def section_identity(
    meta: dict, candidate: Candidate, frequency: str, strategy: str
) -> None:
    identity = meta["identity"]
    need(
        identity.get("product") == candidate.product
        and identity.get("frequency") == frequency
        and identity.get("strategy") == strategy
        and instant(meta["as_of"]) == instant(candidate.as_of)
        and isinstance(meta.get("snapshot_token"), str)
        and bool(meta["snapshot_token"])
        and re.fullmatch("[a-f0-9]{64}", str(meta.get("input_content_sha256", "")))
        is not None,
        "SECTION_IDENTITY_MISMATCH",
    )


def _bind_wire(
    candidate: Candidate, wire: dict, readback: dict, frequency: str, strategy: str
) -> dict:
    need(
        wire.get("http") == readback.get("http") == 200, "ACTUAL_WIRE_BINDING_REQUIRED"
    )
    validate_binding(wire.get("xhr_binding"), wire["url"], wire["http"])
    need(
        readback["observed_url"] == wire["url"]
        and readback["transport_url"]
        == candidate_get_url(wire["url"], candidate, frequency),
        "GET_URL_BINDING_CHANGED",
    )
    original = wire["payload"]["meta"]
    current = readback["payload"]["meta"]
    query = parse_qs(urlsplit(wire["url"]).query)
    need(
        query.get("strategy") == [strategy]
        and len(query.get("as_of", [])) == 1
        and instant(query["as_of"][0]) == instant(candidate.as_of)
        and query.get("snapshot_token") == [original["snapshot_token"]],
        "REFERENCE_REQUEST_IDENTITY",
    )
    section_identity(original, candidate, frequency, strategy)
    section_identity(current, candidate, frequency, strategy)
    need(
        {k: v for k, v in original.items() if k != "read_at"}
        == {k: v for k, v in current.items() if k != "read_at"},
        "GET_SECTION_META_CHANGED",
    )
    part = readback["payload"]["reference"]
    value = part["value"]
    need(
        part.get("delivery") == "delivered"
        and part.get("status", {}).get("status") == "ready",
        "REFERENCE_NOT_READY",
    )
    need(
        value.get("reference_input_sha256") == current["input_content_sha256"]
        and value.get("executable") is False
        and value.get("auto_order") is False,
        "REFERENCE_FACT_IDENTITY",
    )
    observed_value = wire["payload"]["reference"]["value"]
    for field in (
        "items",
        "next_before",
        "executable",
        "auto_order",
        "summary",
        "performance_since",
        "performance_through",
        "actual_available_through",
        "reference_cutoff",
        "reference_input_sha256",
    ):
        need(
            observed_value.get(field) == value.get(field), "WIRE_REFERENCE_FACT_CHANGED"
        )
    return value


def validate_full_capture(
    candidate: Candidate, capture: dict, frequency: str, mode: str
) -> dict:
    strategy = "oscillation" if mode == "oscillation" else "trend"
    need(
        capture.get("frequency") == frequency
        and capture.get("mode") == mode
        and not capture.get("errors"),
        "CAPTURE_SCOPE_OR_ERRORS",
    )
    for name, expected in (
        ("identity", candidate.code_sha),
        ("webIdentity", candidate.web_code_sha or candidate.code_sha),
    ):
        identity = capture[name]
        need(
            identity.get("code_sha") == expected
            and identity.get("mode") == "local_candidate_readonly"
            and identity.get("realtime") is False
            and instant(identity["as_of"]) == instant(candidate.as_of),
            "CAPTURE_PROCESS_IDENTITY",
        )
    need(
        capture["webIdentity"].get("candidate_origin") == candidate.api_origin,
        "WEB_CANDIDATE_ORIGIN",
    )
    ref = capture["reference"]
    chart = capture["chart"]
    need(
        chart.get("http") == 200 and chart.get("xhr_binding"),
        "CHART_WIRE_BINDING_REQUIRED",
    )
    validate_binding(chart.get("xhr_binding"), chart["url"], chart["http"])
    bars = validate_bars(candidate, chart["payload"]["chart"])
    section_identity(chart["payload"]["meta"], candidate, frequency, strategy)
    need(
        chart["payload"]["meta"]["snapshot_token"]
        == ref["payload"]["meta"]["snapshot_token"],
        "CHART_REFERENCE_SNAPSHOT_CHANGED",
    )
    value = _bind_wire(candidate, ref, capture["fullReadback"], frequency, strategy)
    need(
        value.get("performance_since") == candidate.since
        and value.get("performance_through") == candidate.through
        and value.get("actual_available_through") == candidate.through
        and instant(value["reference_cutoff"]) < instant(candidate.as_of),
        "FULL_WINDOW_OR_CUTOFF_MISMATCH",
    )
    need(
        instant(value["reference_cutoff"]) == instant(bars[-1]["bar_end"]),
        "REFERENCE_CHART_CUTOFF_CHANGED",
    )
    curve_value = value["fusion_comparison"] if mode == "dual" else value
    source = curve_value["curve"] if mode == "dual" else curve_value["curve_trades"]
    need(isinstance(source, list), "COMPLETE_CURVE_ARRAY_REQUIRED")
    observed_value = ref["payload"]["reference"]["value"]
    observed_curve = (
        (observed_value.get("fusion_comparison") or {}).get("curve")
        if mode == "dual"
        else observed_value.get("curve_trades")
    )
    actual_digest = digest(source)
    if isinstance(observed_curve, list):
        need(digest(observed_curve) == actual_digest, "COMPLETE_WIRE_ARRAY_CHANGED")
    else:
        proof = capture.get("original_api_curve_proof", {})
        need(
            proof.get("code_sha") == candidate.code_sha
            and proof.get("count") == len(source)
            and proof.get("sha256") == actual_digest,
            "COMPLETE_ARRAY_WIRE_PROOF_REQUIRED",
        )
    dom = capture["dom"]
    need(
        dom.get("product") == candidate.product
        and dom.get("frequency") == frequency
        and dom.get("all") is True
        and dom.get("closed") is True
        and dom.get("busy") is False
        and {"trend": "趋势策略", "oscillation": "震荡策略", "dual": "双策略"}[mode]
        in dom.get("mode", []),
        "FULL_CLOSED_DOM_REQUIRED",
    )
    curves = dom.get("curves", [])
    points = [c["points"] for c in curves]
    need(
        all(c["rect"]["width"] > 0 and c["rect"]["height"] > 0 for c in curves),
        "CURVE_NOT_VISIBLE",
    )
    curve_proof = validate_curve_ui(
        curve_value, points, dom.get("statuses", []), mode == "dual"
    )
    need(
        capture["after"]["ids"] == dom["ids"] and capture["after"]["curves"] == points,
        "GET_CHANGED_ACTUAL_DOM",
    )
    records = capture["records"]
    records_value = _bind_wire(
        candidate, records, capture["recordsReadback"], frequency, strategy
    )
    need(
        records["payload"]["meta"]["snapshot_token"]
        == ref["payload"]["meta"]["snapshot_token"],
        "RECORDS_SNAPSHOT_CHANGED",
    )
    if mode != "dual":
        need(
            parse_qs(urlsplit(records["url"]).query).get("history_limit") == ["200"],
            "ACTUAL_HISTORY_LIMIT_REQUIRED",
        )
    items = (
        records_value["fusion_comparison"]["items"]
        if mode == "dual"
        else records_value["items"]
    )
    original_records = records["payload"]["reference"]["value"]
    original_records = (
        original_records["fusion_comparison"] if mode == "dual" else original_records
    )
    current_records = (
        records_value["fusion_comparison"] if mode == "dual" else records_value
    )
    need(
        all(
            original_records.get(k) == current_records.get(k)
            for k in (
                "items",
                "next_cursor",
                "next_before",
                "reference_input_sha256",
                "reference_revision",
            )
        ),
        "RAW_RECORD_ARRAY_CHANGED",
    )
    need(record_ids_match(items, dom["ids"]), "ACTUAL_RECORD_DOM_IDS_MISMATCH")
    return dict(
        frequency=frequency,
        mode=mode,
        complete_curve_sha256=actual_digest,
        input_sha256=value["reference_input_sha256"],
        snapshot=ref["payload"]["meta"]["snapshot_token"],
        **curve_proof,
    )


def validate_index(candidate: Candidate, store: EvidenceStore, index: dict) -> dict:
    need(
        index.get("task_sha256") == candidate.task_sha256
        and index.get("product") == candidate.product
        and index.get("code_sha") == candidate.code_sha,
        "INDEX_TASK_IDENTITY",
    )
    rows = index.get("evidence", [])
    need(
        rows and len({r["path"] for r in rows}) == len(rows), "EVIDENCE_INDEX_REQUIRED"
    )
    for row in rows:
        current = store.reference(row["path"])
        need(
            all(current[k] == row[k] for k in ("path", "sha256", "bytes")),
            "EVIDENCE_BYTES_CHANGED",
        )
    need(
        index.get("visual_review") in ("NOT_PERFORMED", "PENDING_INDEPENDENT_REVIEW"),
        "INDEX_CANNOT_CERTIFY_VISUAL_REVIEW",
    )
    return candidate.proof(
        evidence_count=len(rows), visual_review=index["visual_review"]
    )
