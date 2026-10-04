"""Pure native D1/W1 wire, full curve, empty state and SPA-return validation."""

from __future__ import annotations
from datetime import date, timedelta
import re
from urllib.parse import urlsplit, parse_qs

from .context import Candidate, instant, need
from .curves import validate_curve_ui, record_ids_match
from .wire import validate_binding, validate_bars


def validate_away_snapshot_recovery(
    candidate: Candidate, observation: dict, responses: list[dict], mode: str, expected: dict
) -> bool:
    """Admit one proven partner 409 -> same-window chart -> reference chain."""
    rejected = [(i, r) for i, r in enumerate(responses) if r.get("http") != 200]
    if not rejected:
        return False
    need(len(rejected) == 1 and mode == "dual", "LEGACY_HTTP_ERROR")
    need(all(isinstance(r.get("xhr_binding"), dict) for r in responses), "LEGACY_RECOVERY_BINDING_MISSING")
    responses = sorted(responses, key=lambda r: r["xhr_binding"]["started_order"])
    need(
        len({r["xhr_binding"]["xhr_sequence"] for r in responses}) == len(responses)
        and len({r["xhr_binding"]["node_request_id"] for r in responses}) == len(responses)
        and len({r["xhr_binding"]["started_order"] for r in responses}) == len(responses),
        "LEGACY_RECOVERY_BINDING_DUPLICATE",
    )
    rejected = [(i, r) for i, r in enumerate(responses) if r.get("http") != 200]
    index, conflict = rejected[0]
    need(
        conflict.get("http") == 409
        and conflict.get("phase") == "away"
        and conflict.get("detail") == {"code": "NEWOW_SNAPSHOT_GENERATION_CONFLICT"},
        "LEGACY_RECOVERY_CONFLICT_INVALID",
    )

    def query(row: dict) -> dict[str, list[str]]:
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
            and q.get("frequency") == ["60m"]
            and q.get("strategy") == ["oscillation"]
            and q.get("series_kind") == ["actual_dominant"]
            and len(q.get("as_of", [])) == 1
            and instant(q["as_of"][0]) == instant(candidate.as_of),
            "LEGACY_RECOVERY_IDENTITY",
        )
        return q

    failed_q = query(conflict)
    need(
        failed_q.get("section") == ["reference"]
        and len(failed_q.get("snapshot_token", [])) == 1
        and failed_q.get("history_limit") == ["200"],
        "LEGACY_RECOVERY_REJECTED_REQUEST",
    )

    def matching(start: int, stop: int, section: str) -> list[tuple[int, dict]]:
        return [
            (i, r) for i, r in enumerate(responses[start:stop], start)
            if r.get("phase") == "away"
            and r.get("http") == 200
            and (q := parse_qs(urlsplit(r.get("url", "")).query)).get("product") == [candidate.product]
            and q.get("frequency") == ["60m"]
            and q.get("strategy") == ["oscillation"]
            and q.get("section") == [section]
        ]

    old_charts = matching(0, index, "chart")
    fresh_charts = matching(index + 1, len(responses), "chart")
    need(len(old_charts) == len(fresh_charts) == 1, "LEGACY_RECOVERY_CHART_COUNT")
    old_index, old = old_charts[0]
    fresh_index, fresh = fresh_charts[0]
    old_q, fresh_q = query(old), query(fresh)
    need(
        old_q == fresh_q
        and old_q.get("section") == ["chart"]
        and old_q.get("from") == [old["chart"]["value"]["from"]]
        and old_q.get("through") == [candidate.through]
        and old["chart"]["value"].get("through") == candidate.through
        and "snapshot_token" not in old_q
        and "chart_before" not in old_q
        and old.get("chart", {}).get("delivery") == "delivered"
        and fresh.get("chart", {}).get("delivery") == "delivered"
        and old["chart"].get("status", {}).get("status") == "ready"
        and fresh["chart"].get("status", {}).get("status") == "ready"
        and old["chart"].get("value") == fresh["chart"].get("value"),
        "LEGACY_RECOVERY_CHART_FACTS_CHANGED",
    )
    main_charts = [
        r for r in responses[:index]
        if r.get("phase") == "away" and r.get("http") == 200
        and (q := parse_qs(urlsplit(r.get("url", "")).query)).get("product") == [candidate.product]
        and q.get("frequency") == ["60m"] and q.get("strategy") == ["trend"]
        and q.get("section") == ["chart"]
    ]
    need(
        len(main_charts) == 1
        and main_charts[0].get("chart", {}).get("delivery") == "delivered"
        and main_charts[0]["chart"].get("status", {}).get("status") == "ready"
        and all(
            main_charts[0]["chart"]["value"].get(key) == old["chart"]["value"].get(key)
            for key in ("from", "through", "bars")
        ),
        "LEGACY_RECOVERY_MAIN_PARTNER_FACTS",
    )
    for chart_row in (main_charts[0], old, fresh):
        validate_bars(candidate, chart_row["chart"])
    main_meta = main_charts[0].get("meta") or {}
    need(
        main_meta.get("identity", {}).get("product") == candidate.product
        and main_meta["identity"].get("frequency") == "60m"
        and main_meta["identity"].get("strategy") == "trend"
        and main_meta["identity"].get("series_kind") == "actual_dominant"
        and main_meta["identity"].get("profile_id") == "newow_product_trend_60m_v1"
        and main_meta["identity"].get("formula_versions") == expected["base_identities"]["trend"]["formula_versions"]
        and instant(main_meta["as_of"]) == instant(candidate.as_of),
        "LEGACY_RECOVERY_MAIN_IDENTITY",
    )
    bars = old["chart"]["value"].get("bars")
    need(
        isinstance(bars, list) and bool(bars)
        and all(
            all(k in bar and bar[k] is not None for k in (
                "bar_end", "trading_day", "open", "high", "low", "close", "volume", "open_interest",
                "physical_contract", "segment_id", "calculation_segment_id", "source_identity",
                "completed", "observation_eligible",
            )) for bar in bars
        ),
        "LEGACY_RECOVERY_MARKET_FACTS_MISSING",
    )
    old_meta, fresh_meta = old.get("meta") or {}, fresh.get("meta") or {}
    old_token, fresh_token = old_meta.get("snapshot_token"), fresh_meta.get("snapshot_token")
    need(
        isinstance(old_token, str) and bool(old_token)
        and isinstance(fresh_token, str) and bool(fresh_token)
        and old_token != fresh_token
        and failed_q["snapshot_token"] == [old_token]
        and old_meta.get("identity") == fresh_meta.get("identity")
        and old_meta.get("identity", {}).get("product") == candidate.product
        and old_meta["identity"].get("frequency") == "60m"
        and old_meta["identity"].get("strategy") == "oscillation"
        and old_meta["identity"].get("series_kind") == "actual_dominant"
        and old_meta["identity"].get("profile_id") == "newow_product_oscillation_60m_v1"
        and old_meta["identity"].get("formula_versions") == expected["base_identities"]["oscillation"]["formula_versions"]
        and instant(old_meta["as_of"]) == instant(fresh_meta["as_of"]) == instant(candidate.as_of)
        and old_meta.get("input_content_sha256") == fresh_meta.get("input_content_sha256"),
        "LEGACY_RECOVERY_TOKEN_OR_SOURCE",
    )
    need(
        re.fullmatch("[a-f0-9]{64}", str(old_meta.get("input_content_sha256", ""))) is not None
        and re.fullmatch("[a-f0-9]{64}", str(main_meta.get("input_content_sha256", ""))) is not None,
        "LEGACY_RECOVERY_INPUT_HASH",
    )
    recovered = matching(fresh_index + 1, len(responses), "reference")
    need(len(recovered) == 1, "LEGACY_RECOVERY_REFERENCE_COUNT")
    recovered_index, reference = recovered[0]
    recovered_q = query(reference)
    need(
        {k: v for k, v in failed_q.items() if k != "snapshot_token"}
        == {k: v for k, v in recovered_q.items() if k != "snapshot_token"}
        and recovered_q.get("snapshot_token") == [fresh_token]
        and reference.get("meta", {}).get("snapshot_token") == fresh_token
        and reference["meta"].get("identity") == fresh_meta.get("identity")
        and instant(reference["meta"]["as_of"]) == instant(candidate.as_of)
        and re.fullmatch("[a-f0-9]{64}", str(reference["meta"].get("input_content_sha256", ""))) is not None
        and reference.get("reference", {}).get("delivery") == "delivered"
        and reference["reference"].get("status", {}).get("status") == "ready",
        "LEGACY_RECOVERY_REFERENCE_MISMATCH",
    )
    value = reference["reference"].get("value") or {}
    need(
        value.get("performance_since") == candidate.since
        and value.get("performance_through") == candidate.through
        and value.get("actual_available_through") == candidate.through
        and instant(value["reference_cutoff"]) <= instant(candidate.as_of)
        and re.fullmatch("[a-f0-9]{64}", str(value.get("reference_input_sha256", ""))) is not None
        and value["reference_input_sha256"] == reference["meta"]["input_content_sha256"]
        and value.get("page_parity", True) is True
        and value.get("executable") is False
        and value.get("auto_order") is False
        and isinstance(value.get("items"), list)
        and isinstance(value.get("curve_trades"), list),
        "LEGACY_RECOVERY_REFERENCE_FACTS",
    )
    latest_bar = old["chart"]["value"]["bars"][-1]
    need(
        instant(value["reference_cutoff"]) == instant(latest_bar["bar_end"])
        and value["actual_available_through"] == latest_bar["trading_day"]
        and value.get("summary", {}).get("membership_policy") == "entry_in_window_v1"
        and value["summary"].get("closed_count") == len(value["curve_trades"])
        and len({t["reference_trade_id"] for t in value["items"]}) == len(value["items"]),
        "LEGACY_RECOVERY_REFERENCE_RECORDS",
    )
    chain = [old, conflict, fresh, reference]
    need(
        old_index < index < fresh_index < recovered_index
        and all(
            a["xhr_binding"]["completed_order"] < b["xhr_binding"]["started_order"]
            and a["xhr_binding"]["xhr_sequence"] < b["xhr_binding"]["xhr_sequence"]
            for a, b in zip(chain, chain[1:])
        ),
        "LEGACY_RECOVERY_ORDER",
    )
    fusion_rows = [
        r for r in responses[recovered_index + 1:]
        if r.get("phase") == "away" and r.get("http") == 200
        and (q := parse_qs(urlsplit(r.get("url", "")).query)).get("section") == ["reference"]
        and q.get("include_fusion") == ["true"]
    ]
    need(len(fusion_rows) == 1, "LEGACY_RECOVERY_FUSION_WIRE_MISSING")
    fusion_row = fusion_rows[0]
    fusion_url = urlsplit(fusion_row["url"])
    fusion_q = parse_qs(fusion_url.query)
    fusion_meta = fusion_row.get("meta") or {}
    fusion_value = (fusion_row.get("reference") or {}).get("value") or {}
    fusion = fusion_value.get("fusion") or {}
    need(
        f"{fusion_url.scheme}://{fusion_url.netloc}" in (candidate.web_origin, candidate.api_origin)
        and fusion_url.path == "/api/v1/market/newow/strategy-detail"
        and not fusion_url.fragment and fusion_url.username is None and fusion_url.password is None
        and fusion_q.get("product") == [candidate.product]
        and fusion_q.get("frequency") == ["60m"]
        and fusion_q.get("strategy") == ["trend"]
        and fusion_q.get("series_kind") == ["actual_dominant"]
        and fusion_q.get("section") == ["reference"]
        and fusion_q.get("include_fusion") == ["true"]
        and fusion_q.get("snapshot_token") == [main_meta["snapshot_token"]]
        and fusion_q.get("performance_since") == [candidate.since]
        and fusion_q.get("performance_through") == [candidate.through]
        and len(fusion_q.get("as_of", [])) == 1
        and instant(fusion_q["as_of"][0]) == instant(candidate.as_of)
        and fusion_meta.get("snapshot_token") == main_meta["snapshot_token"]
        and fusion_meta.get("identity") == main_meta.get("identity")
        and instant(fusion_meta["as_of"]) == instant(candidate.as_of)
        and re.fullmatch("[a-f0-9]{64}", str(fusion_meta.get("input_content_sha256", ""))) is not None
        and fusion_row["reference"].get("delivery") == "delivered"
        and fusion_row["reference"].get("status", {}).get("status") == "ready"
        and fusion_value.get("reference_input_sha256") == fusion_meta.get("input_content_sha256")
        and fusion_value.get("reference_cutoff") == value["reference_cutoff"]
        and fusion.get("product") == candidate.product
        and fusion.get("frequency") == "60m"
        and fusion.get("reference_input_sha256") == fusion_value["reference_input_sha256"]
        and fusion.get("reference_cutoff") == value["reference_cutoff"]
        and fusion.get("performance_since") == candidate.since
        and fusion.get("performance_through") == candidate.through
        and fusion.get("snapshot_schema") == "newow_fusion_reference_snapshot_v2"
        and fusion.get("source_profiles") == [main_meta["identity"]["profile_id"], old_meta["identity"]["profile_id"]]
        and fusion.get("source_formula_versions") == main_meta["identity"]["formula_versions"] + old_meta["identity"]["formula_versions"]
        and fusion.get("reference_model_version") == expected["reference_model_version"]
        and fusion.get("page_parity") is True
        and fusion.get("executable") is False
        and fusion_row["xhr_binding"]["started_order"] > reference["xhr_binding"]["completed_order"]
        and fusion_row["xhr_binding"]["xhr_sequence"] > reference["xhr_binding"]["xhr_sequence"],
        "LEGACY_RECOVERY_FUSION_WIRE_CHANGED",
    )
    away = observation.get("away") or {}
    away_query = parse_qs(urlsplit(away.get("url", "")).query)
    need(
        away_query.get("frequency") == ["60m"]
        and away_query.get("symbol") == [candidate.product]
        and away.get("mode") == ["双策略"]
        and type(away.get("observed_at")) is int
        and away["observed_at"] > 0
        and away["observed_at"] >= reference["xhr_binding"]["completed_at"]
        and away["observed_at"] >= fusion_row["xhr_binding"]["completed_at"]
        and away.get("scopeBusy") is False
        and away.get("all") == "true"
        and isinstance(away.get("cards"), list)
        and isinstance(away.get("curves"), list)
        and all(c.get("width", 0) > 0 and c.get("height", 0) > 0 for c in away["curves"])
        and not any(
            re.search("正在读取|读取中|另一策略参考收益暂不可用|无法对齐|读取失败", s)
            for s in away.get("statuses", [])
        ),
        "LEGACY_RECOVERY_AWAY_DOM",
    )
    anchor = (instant(fusion["reference_cutoff"]) + timedelta(hours=8)).date()
    try:
        record_since = anchor.replace(year=anchor.year - 1).isoformat()
    except ValueError:
        record_since = anchor.replace(year=anchor.year - 1, day=28).isoformat()
    items = [
        t for t in fusion["items"]
        if t["status"] == "OPEN"
        or (t.get("entry_trading_day") or t["entry_bar_end"][:10]) >= record_since
    ]
    need(record_ids_match(items, away["cards"]), "LEGACY_RECOVERY_AWAY_RECORDS")
    validate_curve_ui(fusion, [c["points"] for c in away["curves"]], away.get("statuses", []), True)
    return True


def validate_legacy_capture(
    candidate: Candidate, native: dict, observation: dict, frequency: str, mode: str,
    *, partner_observation: dict | None = None,
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
    need(responses, "LEGACY_HTTP_ERROR")
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
    recovered_away = validate_away_snapshot_recovery(candidate, observation, responses, mode, expected)
    response_count = len(responses)
    responses = [r for r in responses if r["http"] == 200]
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
        validate_bars(
            candidate, row["chart"], frequency=frequency,
            strategy=row["meta"]["identity"]["strategy"],
        )
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

    def rewarming_disclosed(value: dict, source: str, source_observation: dict) -> bool:
        # Compact captures omit coverage_intervals; the rendered coverage is
        # retained verbatim. Require bounded, ordered physical intervals and
        # an explicit excluded source-price interval, never just a warming label.
        prefix = "历史覆盖不完整；仅统计有效区段内已完成的参考交易，跨中断记录不计入收益。"
        pattern = re.compile(
            r"(\d{4}-\d{2}-\d{2}) → (\d{4}-\d{2}-\d{2}) · "
            r"([A-Z]+\d{3,4}) · (有效计算区段|来源价格不可用|重新预热中)"
        )
        for phase in ("full", "before", "returned"):
            statuses = source_observation[phase].get("statuses", [])
            coverage = [s for s in statuses if s.startswith(prefix)]
            if len(coverage) != 1 or not any(
                "当前数据不足" in s for s in statuses
            ) or not any(
                "来源价格不可用后，当前策略参考正在重新预热" in s for s in statuses
            ):
                return False
            text = coverage[0][len(prefix):]
            intervals = list(pattern.finditer(text))
            if not intervals or "".join(m.group(0) for m in intervals) != text:
                return False
            previous = None
            has_gap = False
            for match in intervals:
                since, through, contract, label = match.groups()
                try:
                    date.fromisoformat(since)
                    date.fromisoformat(through)
                except ValueError:
                    return False
                if not (
                    candidate.since <= since <= through <= value["actual_available_through"]
                    and (previous is None or previous < since)
                    and re.fullmatch(re.escape(candidate.product.upper()) + r"\d{3,4}", contract)
                ):
                    return False
                previous = through
                has_gap |= label == "来源价格不可用"
            _, tail, contract, label = intervals[-1].groups()
            if not (
                has_gap and label == "重新预热中"
                and tail == value["actual_available_through"]
                and contract == latest[source]["physical_contract"]
            ):
                return False
        return True

    def reference_valid(
        row: dict, require_full: bool = False, source_observation: dict | None = None,
    ) -> bool:
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
            need(
                state.get("status") == "ready" or (
                    frequency in ("1d", "1w")
                    and s == "oscillation"
                    and state.get("status") == "warming"
                    and state.get("evidence_status") == "ACTIVE_CODE_VERIFIED"
                    and state.get("reason_code") == "NEWOW_SOURCE_PRICE_UNAVAILABLE_REWARMING"
                    and rewarming_disclosed(v, s, source_observation or observation)
                ),
                "LEGACY_REFERENCE_NOT_READY",
            )
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
    partner_evidence = "SAME_SCENE"
    if mode == "dual":
        partner = [
            r
            for r in references
            if r["meta"]["identity"]["strategy"] == "oscillation"
            and reference_valid(r, True)
        ]
        if not partner and partner_observation is not None:
            # A separate scene is never represented as a dual-scene XHR.
            # First verify its complete native wire/DOM/Decimal/return proof.
            validate_legacy_capture(
                candidate, native, partner_observation, frequency, "oscillation",
            )
            separate_charts = [
                r for r in partner_observation["responses"]
                if r.get("http") == 200
                and r.get("chart", {}).get("delivery") == "delivered"
                and r["meta"]["identity"]["frequency"] == frequency
                and r["meta"]["identity"]["strategy"] == "oscillation"
            ]
            for chart in chart_by_strategy["oscillation"]:
                need(any(
                    r["meta"]["identity"] == chart["meta"]["identity"]
                    and r["meta"]["snapshot_token"] == chart["meta"]["snapshot_token"]
                    and r["meta"]["input_content_sha256"] == chart["meta"]["input_content_sha256"]
                    and r["chart"]["value"] == chart["chart"]["value"]
                    and (r.get("phase") == "return") == (chart.get("phase") == "return")
                    for r in separate_charts
                ), "LEGACY_SEPARATE_PARTNER_SNAPSHOT_MISMATCH")
            for row in partner_observation["responses"]:
                if (
                    row.get("http") == 200
                    and row.get("reference", {}).get("delivery") == "delivered"
                    and row["meta"]["identity"]["frequency"] == frequency
                    and row["meta"]["identity"]["strategy"] == "oscillation"
                ):
                    identity(row)
                    if reference_valid(row, True, partner_observation):
                        partner.append(row)
            partner_evidence = "SAME_SNAPSHOT_SEPARATE_SCENE"
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
        away_snapshot_recovery="PASS" if recovered_away else "NOT_OBSERVED",
    )
    if mode == "dual":
        checks["partner_reference_evidence"] = partner_evidence
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
        historical_actual_xhr_binding=bound_count == response_count,
        historical_unbound_compatibility=not binding_required
        and bound_count < response_count,
        source_DB_not_reverified=True,
    )


def validate_legacy(
    candidate: Candidate, native: dict, frequency: str, mode: str, observation: dict,
    *, partner_observation: dict | None = None,
) -> dict:
    """Bundle-facing argument order; the capture validator is also public."""
    return validate_legacy_capture(
        candidate, native, observation, frequency, mode,
        partner_observation=partner_observation,
    )
