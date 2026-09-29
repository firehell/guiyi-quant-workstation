"""Pure native D1/W1 wire, full curve, empty state and SPA-return validation."""

from __future__ import annotations
from datetime import timedelta
import re
from urllib.parse import urlsplit, parse_qs

from .context import Candidate, instant, need
from .curves import validate_curve_ui, record_ids_match
from .wire import validate_binding, validate_bars


def validate_legacy_capture(
    candidate: Candidate, native: dict, observation: dict, frequency: str, mode: str
) -> dict:
    """Verify saved real observations; does not certify source DB or visual review."""
    need(
        frequency in ("1d", "1w") and mode in ("trend", "oscillation", "dual"),
        "LEGACY_SCOPE_INVALID",
    )
    need(
        native.get("code_sha") == candidate.code_sha
        and native.get("product", candidate.product) == candidate.product,
        "LEGACY_NATIVE_IDENTITY_CHANGED",
    )
    if native.get("task_sha256") is not None:
        need(
            native["task_sha256"] == candidate.task_sha256, "LEGACY_NATIVE_TASK_CHANGED"
        )
    expected = native["rows"][frequency]
    need(
        len(expected.get("source_profiles", [])) == 2
        and expected.get("source_formula_versions")
        and expected.get("reference_model_version"),
        "LEGACY_NATIVE_PROFILES_REQUIRED",
    )
    need(
        observation.get("status") == "OBSERVED_NEEDS_REVIEW"
        and not observation.get("bodyErrors")
        and not observation.get("failures")
        and not observation.get("pageErrors"),
        "LEGACY_OBSERVATION_ERRORS",
    )
    for name, code in (
        ("identity", candidate.code_sha),
        ("webIdentity", candidate.web_code_sha or candidate.code_sha),
    ):
        ident = observation[name]
        need(
            ident.get("code_sha") == code
            and ident.get("mode") == "local_candidate_readonly"
            and ident.get("realtime") is False
            and instant(ident["as_of"]) == instant(candidate.as_of),
            "LEGACY_PROCESS_IDENTITY",
        )
    need(
        observation["webIdentity"].get("candidate_origin") == candidate.api_origin,
        "LEGACY_CANDIDATE_ORIGIN",
    )
    responses = observation["responses"]
    need(
        responses and all(r.get("http") == 200 for r in responses), "LEGACY_HTTP_ERROR"
    )
    binding_required = (
        native.get("task_sha256") is not None
        or observation.get("capture_schema") == "newow_legacy_xhr_v1"
    )
    bound_count = 0
    for row in responses:
        binding = row.get("xhr_binding", row.get("binding"))
        if binding_required or binding is not None:
            validate_binding(binding, row["url"], row["http"])
            bound_count += 1
    strategy = "oscillation" if mode == "oscillation" else "trend"
    cutoff = instant(candidate.as_of)
    bases = expected.get("base_identities", {})

    def identity(row: dict) -> str:
        meta = row["meta"]
        ident = meta["identity"]
        s = ident["strategy"]
        need(
            s in ("trend", "oscillation")
            and ident.get("product") == candidate.product
            and ident.get("frequency") == frequency
            and instant(meta["as_of"]) == cutoff
            and isinstance(meta.get("snapshot_token"), str)
            and bool(meta["snapshot_token"])
            and re.fullmatch("[a-f0-9]{64}", str(meta.get("input_content_sha256", "")))
            is not None,
            "LEGACY_SECTION_IDENTITY",
        )
        expected_profile = expected["source_profiles"][0 if s == "trend" else 1]
        need(
            ident.get("profile_id") == expected_profile,
            "LEGACY_NATIVE_PROFILE_MISMATCH",
        )
        versions = ident.get("formula_versions")
        if s in bases:
            need(
                bases[s].get("profile_id") == expected_profile
                and versions == bases[s].get("formula_versions"),
                "LEGACY_NATIVE_FORMULA_MISMATCH",
            )
        else:
            # Historical prepared proofs lack per-base formula grouping. They
            # remain explicitly reported; fresh prepare binds each base exactly.
            need(
                versions
                and all(v in expected["source_formula_versions"] for v in versions),
                "LEGACY_NATIVE_FORMULA_MISMATCH",
            )
        parsed = urlsplit(row["url"])
        q = parse_qs(parsed.query)
        need(
            f"{parsed.scheme}://{parsed.netloc}"
            in (candidate.web_origin, candidate.api_origin)
            and parsed.path == "/api/v1/market/newow/strategy-detail"
            and not parsed.fragment
            and parsed.username is None
            and parsed.password is None
            and q.get("product") == [candidate.product]
            and q.get("frequency") == [frequency]
            and q.get("strategy") == [s]
            and len(q.get("as_of", [])) == 1
            and instant(q["as_of"][0]) == cutoff,
            "LEGACY_SECTION_URL",
        )
        return s

    rows = []
    for row in responses:
        ident = (row.get("meta") or {}).get("identity", {})
        need(
            ident.get("product") == candidate.product, "LEGACY_RESPONSE_PRODUCT_CHANGED"
        )
        if ident.get("frequency") == frequency:
            identity(row)
            rows.append(row)
    primary = [r for r in rows if r["meta"]["identity"]["strategy"] == strategy]
    need(primary, "LEGACY_PRIMARY_RESPONSES_MISSING")
    charts = [r for r in rows if (r.get("chart") or {}).get("delivery") == "delivered"]
    need(charts, "LEGACY_CHART_MISSING")
    for row in charts:
        validate_bars(candidate, row["chart"])
    chart_by_strategy = {
        s: [r for r in charts if r["meta"]["identity"]["strategy"] == s]
        for s in ("trend", "oscillation")
    }
    need(
        chart_by_strategy[strategy]
        and (mode != "dual" or chart_by_strategy["oscillation"]),
        "LEGACY_PARTNER_CHART_MISSING",
    )
    latest = {
        s: max(
            (b for r in group for b in r["chart"]["value"]["bars"]),
            key=lambda b: instant(b["bar_end"]),
        )
        for s, group in chart_by_strategy.items()
        if group
    }
    references = [
        r
        for r in rows
        if (r.get("reference") or {}).get("delivery") == "delivered"
        and r["reference"].get("value")
    ]
    need(references, "LEGACY_REFERENCE_MISSING")

    def reference_valid(row: dict, require_full: bool = False) -> bool:
        v = row["reference"]["value"]
        meta = row["meta"]
        s = meta["identity"]["strategy"]
        state = row["reference"]["status"]
        need(
            v.get("reference_input_sha256") == meta["input_content_sha256"]
            and v.get("executable") is False
            and v.get("auto_order") is False
            and v.get("page_parity", True) is True,
            "LEGACY_REFERENCE_FACT_IDENTITY",
        )
        need(
            s in latest
            and instant(v["reference_cutoff"]) == instant(latest[s]["bar_end"])
            and v.get("actual_available_through") == latest[s]["trading_day"]
            and instant(v["reference_cutoff"]) < cutoff
            and isinstance(v.get("performance_since"), str)
            and v["performance_since"] <= v["performance_through"]
            and v["actual_available_through"]
            <= v["performance_through"]
            <= candidate.through,
            "LEGACY_COMPLETED_WINDOW_UNPROVEN",
        )
        q = parse_qs(urlsplit(row["url"]).query)
        need(
            q.get("snapshot_token") == [meta["snapshot_token"]]
            and any(
                c["meta"]["snapshot_token"] == meta["snapshot_token"]
                for c in chart_by_strategy[s]
                if row.get("phase") != "return" or c.get("phase") == "return"
            ),
            "LEGACY_SNAPSHOT_BINDING",
        )
        if v["actual_available_through"] == v["performance_through"]:
            need(state.get("status") == "ready", "LEGACY_REFERENCE_NOT_READY")
        else:
            need(
                frequency == "1w"
                and state.get("status") == "warming"
                and state.get("reason_code") == "NEWOW_REFERENCE_WEEKLY_WINDOW_PARTIAL",
                "LEGACY_WEEKLY_PARTIAL_REASON",
            )
        if frequency == "1d":
            need(
                v["actual_available_through"]
                == v["performance_through"]
                == candidate.through,
                "LEGACY_D1_CUTOFF_MISMATCH",
            )
        return not require_full or v["performance_since"] == candidate.since

    for row in references:
        reference_valid(row)
    full = [
        r
        for r in references
        if r["meta"]["identity"]["strategy"] == strategy
        and reference_valid(r, True)
        and (mode != "dual" or r["reference"]["value"].get("fusion"))
    ]
    need(full, "LEGACY_FULL_WINDOW_MISSING")
    if mode == "dual":
        partner = [
            r
            for r in references
            if r["meta"]["identity"]["strategy"] == "oscillation"
            and reference_valid(r, True)
        ]
        need(partner, "LEGACY_PARTNER_REFERENCE_MISSING")
        trend_versions = next(r["meta"]["identity"]["formula_versions"] for r in full)
        oscillation_versions = next(
            r["meta"]["identity"]["formula_versions"] for r in partner
        )
        need(
            trend_versions + oscillation_versions
            == expected["source_formula_versions"],
            "LEGACY_TWO_SOURCE_FORMULAS_CHANGED",
        )
        for row in full:
            v = row["reference"]["value"]
            f = v.get("fusion")
            need(
                isinstance(f, dict)
                and f.get("product") == candidate.product
                and f.get("frequency") == frequency
                and re.fullmatch("[a-f0-9]{64}", str(f.get("reference_revision", "")))
                is not None
                and f.get("snapshot_schema") == "newow_fusion_reference_snapshot_v2"
                and f.get("source_profiles") == expected["source_profiles"]
                and f.get("source_formula_versions")
                == expected["source_formula_versions"]
                and f.get("reference_model_version")
                == expected["reference_model_version"]
                and f.get("reference_input_sha256") == v["reference_input_sha256"]
                and instant(f["reference_cutoff"]) == instant(v["reference_cutoff"])
                and f.get("performance_since") == v["performance_since"]
                and f.get("performance_through") == v["performance_through"]
                and f.get("page_parity") is True
                and f.get("executable") is False
                and len(f.get("groups", [])) == 3
                and {g.get("model") for g in f["groups"]}
                == {"trend", "oscillation", "fusion"},
                "LEGACY_DUAL_NATIVE_IDENTITY",
            )
    checks = dict(
        main_chart="PASS",
        auxiliary="PASS",
        complete_closed_curve="PASS",
        near_year_records="PASS",
        switch_return="PASS",
        errors="PASS",
    )
    auxiliary = observation.get("auxiliary", [])
    need(
        len(auxiliary) == 2
        and {a.get("component") for a in auxiliary} == {"macd", "trend_reversal"},
        "LEGACY_AUXILIARY_REQUIRED",
    )
    for item in auxiliary:
        status = item["status"]
        need(
            status.get("status") in ("ready", "warming")
            and (status.get("status") != "warming" or status.get("reason_code")),
            "LEGACY_AUXILIARY_STATUS",
        )
        ident = item["meta"]["identity"]
        need(
            ident.get("product") == candidate.product
            and ident.get("frequency") == frequency
            and instant(item["meta"]["as_of"]) == cutoff,
            "LEGACY_AUXILIARY_IDENTITY",
        )
        if item.get("dom"):
            need(
                item["dom"].get("component") == item["component"],
                "LEGACY_AUXILIARY_DOM",
            )
        if status["status"] == "warming":
            checks["auxiliary"] = "WARMING"
    proofs = []
    for phase in ("full", "before", "returned"):
        dom = observation[phase]
        selected = {"trend": "趋势策略", "oscillation": "震荡策略", "dual": "双策略"}[
            mode
        ]
        query = parse_qs(urlsplit(dom["url"]).query)
        need(
            query.get("symbol") == [candidate.product]
            and query.get("frequency") == [frequency]
            and dom.get("mode") == [selected]
            and not dom.get("scopeBusy")
            and dom.get("all") == "true",
            "LEGACY_DOM_IDENTITY",
        )
        candidates = [
            r for r in full if (r.get("phase") == "return") == (phase == "returned")
        ]
        need(candidates, "LEGACY_RETURN_WIRE_MISSING")
        for curve in dom["curves"]:
            need(
                curve.get("width", 0) > 0 and curve.get("height", 0) > 0,
                "LEGACY_CURVE_NOT_VISIBLE",
            )
        results = [
            validate_curve_ui(
                r["reference"]["value"]["fusion"]
                if mode == "dual"
                else r["reference"]["value"],
                [c["points"] for c in dom["curves"]],
                dom.get("statuses", []),
                mode == "dual",
            )
            for r in candidates
        ]
        proofs.append(results[-1])
        record_candidates = [
            r
            for r in references
            if r["meta"]["identity"]["strategy"] == strategy
            and (r.get("phase") == "return") == (phase == "returned")
        ]
        matched = False
        for row in record_candidates:
            value = row["reference"]["value"]
            if mode == "dual":
                value = value.get("fusion")
                if not value:
                    continue
                anchor = (
                    instant(value["reference_cutoff"]) + timedelta(hours=8)
                ).date()
                try:
                    record_since = anchor.replace(year=anchor.year - 1).isoformat()
                except ValueError:
                    record_since = anchor.replace(
                        year=anchor.year - 1, day=28
                    ).isoformat()
                items = [
                    t
                    for t in value["items"]
                    if t["status"] == "OPEN"
                    or (t.get("entry_trading_day") or t["entry_bar_end"][:10])
                    >= record_since
                ]
            else:
                if parse_qs(urlsplit(row["url"]).query).get("history_limit") != ["200"]:
                    continue
                items = value["items"]
            need(
                len({t["reference_trade_id"] for t in items}) == len(items),
                "LEGACY_DUPLICATE_RECORD",
            )
            if record_ids_match(items, dom["cards"]):
                matched = True
        need(matched, "LEGACY_RECORD_DOM_IDENTITY")
    need(
        observation["returned"]["cards"] == observation["before"]["cards"],
        "LEGACY_SWITCH_RETURN_CARDS_CHANGED",
    )
    need(
        all(
            p["closed_ids"] == proofs[0]["closed_ids"]
            and p["cumulative_decimal"] == proofs[0]["cumulative_decimal"]
            for p in proofs
        ),
        "LEGACY_RETURN_FULL_CURVE_CHANGED",
    )
    if proofs[0]["closed_count"] == 0:
        checks["complete_closed_curve"] = "NOT_APPLICABLE"
    warming = any(r["reference"]["status"].get("status") == "warming" for r in full)
    return candidate.proof(
        frequency=frequency,
        mode=mode,
        checks=checks,
        curve=proofs[0],
        completed_week_window_warming=warming,
        visual_review="NOT_RUN",
        native_base_formulas_exact=bool(bases),
        historical_actual_xhr_binding=bound_count == len(responses),
        historical_unbound_compatibility=not binding_required
        and bound_count < len(responses),
        source_DB_not_reverified=True,
    )


def validate_legacy(
    candidate: Candidate, native: dict, frequency: str, mode: str, observation: dict
) -> dict:
    """Bundle-facing argument order; the capture validator is also public."""
    return validate_legacy_capture(candidate, native, observation, frequency, mode)
