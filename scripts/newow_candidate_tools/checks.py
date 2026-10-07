"""Pure offline functional, earlier-window and native cancellation checks.

The pagination rules were materialized from accepted per-product readers. No
historical helper, dynamic Python source or production resolver is loaded.
"""

from datetime import datetime, date
from urllib.parse import urlparse, parse_qs, urlsplit
import re
import json
from hashlib import sha256
from .context import Candidate, instant, need
from .audit import section_identity
from .wire import validate_binding, validate_bars

CHECKS = (
    "main_chart",
    "reference_records",
    "reference_curve",
    "auxiliary",
    "same_day_pagination",
    "switch_identity",
    "errors_warmup",
)


def validate_supplemental_partner(candidate, frequency, mode, observed):
    """Authenticate one explicitly collected response, never a UI delivery claim."""
    actions = [a for a in observed.get('actions', []) if isinstance(a, dict) and a.get('kind') == 'supplemental_partner_reference']
    need(len(actions) <= 1, 'SUPPLEMENT_COUNT')
    if not actions:
        return dict(count=0, resolved_failures=[])
    a = actions[0]
    need(mode == 'dual' and a.get('source') == 'collector_true_xhr'
         and a.get('ui_composable_received') is False and a.get('phase') == 'initial'
         and a.get('status') == 'RESPONSE_BOUND' and a.get('frequency') == frequency
         and a.get('strategy') in ('trend', 'oscillation')
         and type(a.get('request_floor')) is int and a['request_floor'] >= 0, 'SUPPLEMENT_ACTION')
    url, strategy, floor = a['url'], a['strategy'], a['request_floor']
    q = scoped_url(candidate, url, frequency, 'reference', strategy)
    need(set(q) == {'product', 'strategy', 'frequency', 'series_kind', 'section', 'as_of', 'history_limit', 'snapshot_token'}
         and all(len(v) == 1 for v in q.values()) and q['series_kind'] == ['actual_dominant']
         and q['history_limit'] == ['200'] and q['snapshot_token'] == [a['snapshot_token']], 'SUPPLEMENT_URL')
    aborted = a['aborted_request']
    need(type(aborted.get('id')) is int and aborted['id'] > floor and aborted.get('url') == url
         and aborted.get('method') == 'GET' and aborted.get('phase') == 'seed'
         and aborted.get('failed') is True and aborted.get('error') == 'net::ERR_ABORTED'
         and [r for r in observed.get('requestEvidence', []) if r.get('id') == aborted['id']] == [aborted], 'SUPPLEMENT_ABORT')
    resolved = dict(url=url, error='net::ERR_ABORTED', phase='seed', request_phase='seed')
    need([f for f in observed.get('failures', []) if f.get('url') == url] == [resolved], 'SUPPLEMENT_FAILURE_BINDING')
    charts = [r for r in observed.get('responses', []) if r.get('request_id') == a['chart_request_id']]
    need(len(charts) == 1, 'SUPPLEMENT_CHART_COUNT')
    chart = charts[0]; meta = chart.get('payload', {}).get('meta', {})
    scoped_url(candidate, chart['url'], frequency, 'chart', strategy)
    validate_binding(chart.get('xhr_binding'), chart['url'], 200)
    section_identity(meta, candidate, frequency, strategy)
    need(chart.get('http') == 200 and chart.get('row_request') is True and chart.get('request_phase') == 'seed'
         and floor < chart['request_id'] < aborted['id'] and chart['xhr_binding'] == a['chart_binding']
         and chart['xhr_binding']['node_request_id'] == chart['request_id']
         and meta['snapshot_token'] == a['snapshot_token']
         and (chart['payload'].get('chart') or {}).get('delivery') == 'delivered'
         and (chart['payload']['chart'].get('status') or {}).get('status') == 'ready'
         and chart['payload']['chart']['status'].get('evidence_status') == 'ACTIVE_CODE_VERIFIED', 'SUPPLEMENT_CHART')
    raw = a['response_readback']; text = raw.get('response_text')
    need(raw.get('evidence_kind') == 'same_xhr_full_response_readback' and raw.get('extra_get') is False
         and raw.get('http') == 200 and raw.get('url') == url and isinstance(text, str)
         and raw.get('response_text_chars') == len(text.encode('utf-16-le')) // 2
         and raw.get('response_text_sha256') == sha256(text.encode()).hexdigest(), 'SUPPLEMENT_RAW')
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        raise ValueError('SUPPLEMENT_RAW_JSON') from None
    need(parsed == raw.get('payload') and raw.get('payload_sha256') == sha256(json.dumps(parsed, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest(), 'SUPPLEMENT_PAYLOAD_HASH')
    rows = [r for r in observed.get('responses', []) if r.get('request_id') == raw.get('response_request_id')]
    need(len(rows) == 1, 'SUPPLEMENT_RESPONSE_COUNT')
    row = rows[0]; rm = row.get('payload', {}).get('meta', {}); part = parsed.get('reference') or {}
    validate_binding(raw.get('xhr_binding'), url, 200)
    section_identity(parsed.get('meta', {}), candidate, frequency, strategy)
    need(row.get('http') == 200 and row.get('row_request') is True and row.get('url') == url
         and row.get('request_phase') == 'seed' and row['request_id'] > aborted['id']
         and raw['xhr_binding'] == row.get('xhr_binding')
         and raw['xhr_binding']['response_text_chars'] == raw['response_text_chars']
         and raw['xhr_binding']['node_request_id'] == raw['response_request_id']
         and parsed['meta'] == rm and rm['snapshot_token'] == a['snapshot_token']
         and part.get('delivery') == 'delivered' and part.get('status') == row['payload']['reference']['status']
         and part['status'].get('status') == 'ready' and part['status'].get('evidence_status') == 'ACTIVE_CODE_VERIFIED', 'SUPPLEMENT_RESPONSE_BINDING')
    requests = [r for r in observed.get('requestEvidence', []) if r.get('id') == row['request_id']]
    need(len(requests) == 1 and requests[0].get('url') == url and requests[0].get('method') == 'GET'
         and requests[0].get('phase') == 'seed' and requests[0].get('finished') is True
         and not requests[0].get('failed'), 'SUPPLEMENT_REQUEST_BINDING')
    value, compact = part.get('value') or {}, row['payload']['reference'].get('value') or {}
    need(value.get('reference_input_sha256') == rm['input_content_sha256'] and value.get('executable') is False
         and value.get('auto_order') is False and all(value.get(k) == compact.get(k) for k in ('items', 'summary', 'reference_input_sha256', 'performance_since', 'performance_through', 'next_before')), 'SUPPLEMENT_REFERENCE_FACTS')
    trades = value.get('curve_trades')
    need(isinstance(trades, list), 'SUPPLEMENT_FULL_CURVE_REQUIRED')
    if 'curve_trades' in compact:
        need(trades == compact['curve_trades'], 'SUPPLEMENT_FULL_CURVE_CHANGED')
    else:
        need(compact.get('curve_trades_summary') == dict(count=len(trades), first=trades[0] if trades else None, last=trades[-1] if trades else None), 'SUPPLEMENT_CURVE_SUMMARY_CHANGED')
    return dict(count=1, resolved_failures=[resolved], response_request_id=row['request_id'], ui_composable_received=False)


def functional_checks(
    candidate: Candidate, frequency: str, mode: str, observed: dict
) -> dict:
    CODE = candidate.code_sha
    WEB_CODE = candidate.web_code_sha or CODE
    ASOF = instant(candidate.as_of).isoformat()
    supplement = validate_supplemental_partner(candidate, frequency, mode, observed)

    def before_asof(value):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.tzinfo is not None and parsed <= datetime.fromisoformat(ASOF)
        except (ValueError, TypeError, AttributeError):
            return False

    def complete_window(value, url):
        since = candidate.since
        through = candidate.through
        return (
            value.get("performance_since") == since
            and value.get("performance_through") == through
            and value.get("actual_available_through") == through
            and before_asof(value.get("reference_cutoff"))
            and bool(value.get("reference_input_sha256"))
        )

    def reference_page(r, mode):
        value = r.get("payload", {}).get("reference", {}).get("value", {})
        return value.get("fusion_comparison", {}) if mode == "dual" else value

    def reference_pagination(responses, mode, before, after):
        pages = [
            r
            for r in responses
            if ("fusion_before=" if mode == "dual" else "history_before=")
            in r.get("url", "")
            and isinstance(reference_page(r, mode).get("items"), list)
        ]
        initial = [
            r
            for r in responses
            if "fusion_before=" not in r.get("url", "")
            and "history_before=" not in r.get("url", "")
            and isinstance(reference_page(r, mode).get("items"), list)
        ]
        if mode != "dual":
            initial = [
                r
                for r in initial
                if parse_qs(urlparse(r["url"]).query).get("history_limit") == ["200"]
            ]
        # Base DOM records are the explicit history_limit=200 reader; full statistics may happen to contain identical IDs.
        if not initial:
            return "NOT_RUN", "REFERENCE_FIRST_PAGE_MISSING"

        # The records panel and full-statistics request are independent readers. Bind
        # the initial records payload to every actual DOM card, in its displayed order.
        def matches_dom(r):
            items = reference_page(r, mode)["items"]
            ids = [x.get("reference_trade_id") for x in items]
            return (
                len(ids) == len(before)
                and len(set(ids)) == len(ids)
                and all(
                    isinstance(t, str) and t and isinstance(d, str) and d.endswith(t)
                    for d, t in zip(before, ids)
                )
            )

        initial = [r for r in initial if matches_dom(r)]
        if not initial:
            return "NOT_RUN", "REFERENCE_DOM_FIRST_PAGE_MISSING"
        firstmeta = initial[-1].get("payload", {}).get("meta", {})
        if not firstmeta.get("snapshot_token") or not reference_page(
            initial[-1], mode
        ).get("reference_input_sha256"):
            return "NOT_RUN", "REFERENCE_SNAPSHOT_CHANGED"
        if (
            len(
                {
                    (
                        reference_page(r, mode).get(
                            "next_cursor" if mode == "dual" else "next_before"
                        ),
                        r.get("payload", {}).get("meta", {}).get("snapshot_token"),
                        reference_page(r, mode).get("reference_input_sha256"),
                    )
                    for r in initial
                }
            )
            != 1
        ):
            return "NOT_RUN", "REFERENCE_DOM_PAGE_AMBIGUOUS"
        first = reference_page(initial[-1], mode)
        cursor = first.get("next_cursor" if mode == "dual" else "next_before")
        if not cursor:
            return "NOT_APPLICABLE", "VERIFIED_REFERENCE_NO_NEXT_CURSOR"
        if not pages:
            return "NOT_RUN", "REFERENCE_CURSOR_NOT_CLICKED"
        page = pages[0]
        second = reference_page(page, mode)
        actual = parse_qs(urlparse(page["url"]).query).get(
            "fusion_before" if mode == "dual" else "history_before", [None]
        )[0]
        left = first["items"]
        right = second["items"]
        a = [r.get("reference_trade_id") for r in left]
        b = [r.get("reference_trade_id") for r in right]
        firstmeta = initial[-1].get("payload", {}).get("meta", {})
        secondmeta = page.get("payload", {}).get("meta", {})
        if (
            not firstmeta.get("snapshot_token")
            or not first.get("reference_input_sha256")
            or firstmeta.get("snapshot_token") != secondmeta.get("snapshot_token")
            or first.get("reference_input_sha256")
            != second.get("reference_input_sha256")
        ):
            return "NOT_RUN", "REFERENCE_SNAPSHOT_CHANGED"
        if (
            actual != cursor
            or not left
            or not right
            or None in a + b
            or len(set(a + b)) != len(a + b)
        ):
            return "NOT_RUN", "REFERENCE_CURSOR_OR_IDS_CONFLICT"

        def shown(ids, trade):
            return any(i and i.endswith(trade) for i in ids)

        if (
            not before
            or len(after) <= len(before)
            or len(set(after)) != len(after)
            or not set(before) <= set(after)
            or not all(shown(after, i) for i in b)
        ):
            return "NOT_RUN", "REFERENCE_DOM_APPEND_NOT_VERIFIED"
        if left[-1].get("entry_trading_day") != right[0].get("entry_trading_day"):
            return "NOT_APPLICABLE", "OBSERVED_REFERENCE_CURSOR_CROSSES_TRADING_DAY"
        return "PASS", "SAME_TRADING_DAY_REFERENCE_CURSOR_OBSERVED"

    def failure_is_expected(failure, product, frequency, obs):
        if failure.get("error") != "net::ERR_ABORTED":
            return False
        q = parse_qs(urlparse(failure.get("url", "")).query)
        target = (q.get("product", [None])[0], q.get("frequency", [None])[0])
        if target == (product, frequency):
            return failure in supplement['resolved_failures']  # only the authenticated exact initial abort
        actions = obs.get("actions", [])
        seed = obs.get("seedIdentity", {})
        if (
            failure.get("request_phase") == "seed"
            and target == (seed.get("product"), seed.get("frequency"))
            and any(a in actions for a in ("switch_product", "switch_frequency"))
        ):
            return True
        away = "30m" if frequency == "60m" else "60m"
        if "switch_away_and_return" not in actions or failure.get("phase") not in (
            "away",
            "return",
        ):
            return False
        if target == (product, away) and failure.get("request_phase") == "away":
            return True
        return target == (product, "1d") and q.get("section") == ["explanation"]

    def identity_matches(obs):
        identity = obs.get("identity") or {}
        if not isinstance(identity, dict) or any(
            not isinstance(identity.get(n), dict) for n in ("api", "web")
        ):
            return False
        return (
            obs.get("identity_valid") is True
            and all(
                identity.get(name, {}).get("code_sha") == code
                and identity.get(name, {}).get("as_of", "").replace("Z", "+00:00")
                == ASOF
                and identity.get(name, {}).get("mode") == "local_candidate_readonly"
                and identity.get(name, {}).get("realtime") is False
                for name, code in (("api", CODE), ("web", WEB_CODE))
            )
            and identity.get("webHttp") == identity.get("apiHttp") == 200
            and identity["web"].get("candidate_origin") == candidate.api_origin
        )

    def check_observation(product, frequency, mode, obs):
        checks = {k: "NOT_RUN" for k in CHECKS}
        reasons = []
        if obs.get("identity_valid") is not True:
            return checks, ["ACTUAL_IDENTITY_MISSING"]
        if not identity_matches(obs):
            return checks, ["ACTUAL_PROCESS_IDENTITY_MISMATCH"]
        if obs.get("bodyReadErrors"):
            return checks, ["RESPONSE_BODY_READ_FAILED"]
        responses = obs.get("responses", [])
        wanted = "oscillation" if mode == "oscillation" else "trend"
        delivered = []
        partners = []
        for r in responses:
            meta = (r.get("payload") or {}).get("meta", {})
            identity = meta.get("identity", {})
            if (
                identity.get("product") == product
                and identity.get("frequency") == frequency
                and meta.get("as_of", "").replace("Z", "+00:00") == ASOF
            ):
                if identity.get("strategy") == wanted:
                    delivered.append(r)
                elif identity.get("strategy") == "oscillation":
                    partners.append(r)
        chart = [r for r in delivered if r.get("bars")]
        final = obs.get("final", {})
        if (
            chart
            and final.get("chartVisible")
            and all(
                b.get("physical_contract") and b.get("bar_end")
                for b in chart[-1]["bars"]
            )
        ):
            checks["main_chart"] = "PASS"

        def ready_reference(rows):
            return [
                r
                for r in rows
                if r.get("payload", {}).get("reference", {}).get("delivery")
                == "delivered"
                and r["payload"]["reference"].get("status", {}).get("status") == "ready"
            ]

        ready = ready_reference(delivered)
        full = [
            r
            for r in ready
            if complete_window(r["payload"]["reference"].get("value", {}), r["url"])
            and r["payload"].get("meta", {}).get("snapshot_token")
            and r["payload"]["meta"].get("input_content_sha256")
            == r["payload"]["reference"]["value"].get("reference_input_sha256")
        ]
        # Both persisted source references and the explicit fusion snapshot/render must be proven.
        dual_ok = True
        if mode == "dual":
            other = [
                r
                for r in ready_reference(partners)
                if complete_window(r["payload"]["reference"].get("value", {}), r["url"])
            ]
            fusion = [
                reference_page(r, mode)
                for r in full
                if r["payload"]["reference"]["value"].get("fusion_comparison")
                is not None
            ]
            dual_ok = bool(
                other
                and fusion
                and final.get("fusionCards", 0) > 0
                and final.get("fusionCurves", 0) > 0
                and all(
                    f.get("product") == product
                    and f.get("frequency") == frequency
                    and f.get("reference_revision")
                    and f.get("fusion_input_sha256")
                    and f.get("executable") is False
                    and before_asof(f.get("reference_cutoff"))
                    and {g.get("model") for g in f.get("groups", [])}
                    == {"trend", "oscillation", "fusion"}
                    for f in fusion
                )
            )
        if (
            full
            and obs.get("fullSelected")
            and dual_ok
            and final.get("cards", 0) > 0
            and all(
                r["payload"]["reference"]["value"].get("executable") is False
                for r in full
            )
        ):
            checks["reference_records"] = "PASS"
        curves = obs.get("visibleCurves", [])
        if (
            full
            and obs.get("fullSelected")
            and dual_ok
            and curves
            and all(
                r.get("finite")
                and r.get("width", 0) > 0
                and r.get("height", 0) > 0
                and r.get("pointCount", 0) >= 2
                for r in curves
            )
            and obs.get("curvesBefore") == obs.get("curvesAfter")
        ):
            checks["reference_curve"] = "PASS"
        aux = obs.get("auxiliary", [])
        if len(aux) == 5 and all(
            x.get("pressed") == "true" and x.get("text") for x in aux
        ):
            components = {x["component"] for x in aux}
            sections = [
                r
                for r in delivered
                if any("component=" + c in r.get("url", "") for c in components)
            ]
            statuses = []
            for c in components:
                matches = [r for r in sections if "component=" + c in r["url"]]
                if not matches:
                    break
                section = matches[-1].get("payload", {}).get("auxiliary", {})
                status = section.get("status", {})
                kind = status.get("status")
                if matches[-1]["http"] != 200 or section.get("delivery") != "delivered":
                    break
                if kind == "ready" and section.get("value") is not None:
                    statuses.append("PASS")
                elif kind in ("warming", "not_applicable") and status.get(
                    "reason_code"
                ):
                    statuses.append(kind.upper())
                    reasons.append("AUXILIARY_" + c + ":" + status["reason_code"])
                else:
                    break
            if len(statuses) == 5:
                checks["auxiliary"] = (
                    "PASS"
                    if all(s == "PASS" for s in statuses)
                    else "WARMING"
                    if "WARMING" in statuses
                    else "NOT_APPLICABLE"
                )
        # Chart cursor is separately required; it never substitutes for a reference trading-day boundary.
        checks["same_day_pagination"], reason = reference_pagination(
            [r for r in ready if r in obs.get("pagingResponses", ready)],
            mode,
            obs.get("idsBefore", []),
            obs.get("idsAfter", []),
        )
        reasons.append(reason)
        chartpages = [
            r
            for r in chart
            if "chart_before=" in r.get("url", "")
            or "chart_older_window=" in r.get("url", "")
        ]
        if not chartpages:
            reasons.append("MAIN_CHART_CURSOR_NOT_OBSERVED")
            if chart and chart[0].get("chartNext"):
                checks["same_day_pagination"] = "NOT_RUN"
        elif not all(
            r.get("http") == 200
            and r.get("bars")
            and r.get("payload", {}).get("meta", {}).get("snapshot_token")
            == chart[0].get("payload", {}).get("meta", {}).get("snapshot_token")
            for r in chartpages
        ):
            checks["same_day_pagination"] = "NOT_RUN"
            reasons.append("MAIN_CHART_CURSOR_CONFLICT")
        if (
            "switch_away_and_return" in obs.get("actions", [])
            and any(
                r.get("payload", {}).get("meta", {}).get("identity", {}).get("product")
                == product
                and r.get("payload", {})
                .get("meta", {})
                .get("identity", {})
                .get("frequency")
                == frequency
                for r in obs.get("returnResponses", [])
            )
            and f"symbol={product}" in final.get("url", "")
            and f"frequency={frequency}" in final.get("url", "")
        ):
            checks["switch_identity"] = "PASS"
        expected_failures = [
            f
            for f in obs.get("failures", [])
            if failure_is_expected(f, product, frequency, obs)
        ]
        reasons.extend("EXPECTED_SPA_CANCEL:" + f["url"] for f in expected_failures)
        if (
            obs.get("initialTerminal", {}).get("kind") != "blocked"
            and not any(r.get("http", 0) >= 400 for r in obs.get("responses", []))
            and not obs.get("errors")
            and not obs.get("pageErrors")
            and len(expected_failures) == len(obs.get("failures", []))
            and ready
            and not any("正在读取" in s for s in final.get("statuses", []))
        ):
            checks["errors_warmup"] = "PASS"
        return checks, reasons

    for row in observed.get("responses", []):
        meta = row.get("payload", {}).get("meta", {})
        if (
            meta.get("identity", {}).get("product") == candidate.product
            and meta["identity"].get("frequency") == frequency
        ):
            validate_binding(row.get("xhr_binding"), row["url"], row["http"])
            section_identity(meta, candidate, frequency, meta["identity"]["strategy"])
            if row.get("payload", {}).get("chart", {}).get("value"):
                validate_bars(candidate, row["payload"]["chart"])
    checks, reasons = check_observation(candidate.product, frequency, mode, observed)
    need(
        all(v in ("PASS", "NOT_APPLICABLE", "WARMING") for v in checks.values()),
        "FUNCTIONAL_GATE",
    )
    return dict(status="PASS", checks=checks, reasons=reasons, supplemental_partner=supplement)


def process_identities(candidate: Candidate, identities: dict) -> None:
    for name, code in (
        ("api", candidate.code_sha),
        ("web", candidate.web_code_sha or candidate.code_sha),
    ):
        identity = identities.get(name, {})
        need(
            identity.get("code_sha") == code
            and identity.get("mode") == "local_candidate_readonly"
            and identity.get("realtime") is False
            and instant(identity["as_of"]) == instant(candidate.as_of),
            "OBSERVED_PROCESS_IDENTITY",
        )
    need(
        identities["web"].get("candidate_origin") == candidate.api_origin,
        "OBSERVED_PROCESS_ORIGIN",
    )


def scoped_url(
    candidate: Candidate, url: str, frequency: str, section: str, strategy: str
) -> dict:
    parsed = urlsplit(url)
    q = parse_qs(parsed.query)
    need(
        f"{parsed.scheme}://{parsed.netloc}"
        in (candidate.api_origin, candidate.web_origin)
        and parsed.path == "/api/v1/market/newow/strategy-detail"
        and not parsed.fragment
        and q.get("product") == [candidate.product]
        and q.get("frequency") == [frequency]
        and q.get("section") == [section]
        and q.get("strategy") == [strategy]
        and len(q.get("as_of", [])) == 1
        and instant(q["as_of"][0]) == instant(candidate.as_of),
        "OBSERVED_URL_SCOPE",
    )
    return q


def validate_earlier(
    candidate: Candidate, frequency: str, mode: str, observed: dict
) -> dict:
    need(
        not observed.get("errors") and bool(observed.get("pages")),
        "EARLIER_ACTUAL_PAGES_REQUIRED",
    )
    process_identities(candidate, observed["identities"])
    strategy = "oscillation" if mode == "oscillation" else "trend"
    initial = observed["initial"]
    section_identity(initial["meta"], candidate, frequency, strategy)
    base = initial["chart"]["value"]
    prior = instant(base["bars"][0]["bar_end"])
    token = initial["meta"]["snapshot_token"]
    older = None
    for page in observed["pages"]:
        q = scoped_url(candidate, page["url"], frequency, "chart", strategy)
        validate_binding(page.get("binding"), page["url"], page["http"])
        validate_bars(candidate, page["payload"]["chart"])
        value = page["payload"]["chart"]["value"]
        meta = page["payload"]["meta"]
        section_identity(meta, candidate, frequency, strategy)
        need(
            page["http"] == 200
            and page.get("binding")
            and meta["snapshot_token"] == token
            and page["payload"]["chart"]["status"]["status"] == "ready"
            and instant(value["bars"][-1]["bar_end"]) < prior,
            "EARLIER_CURSOR_OR_SNAPSHOT",
        )
        need(
            all(
                b.get("physical_contract")
                and b.get("completed") is True
                and instant(b["bar_end"]) < instant(candidate.as_of)
                for b in value["bars"]
            ),
            "EARLIER_PHYSICAL_BARS",
        )
        prior = instant(value["bars"][0]["bar_end"])
        if "chart_older_window" in q:
            older = value
    need(
        older is not None
        and date.fromisoformat(older["chart_through"])
        < date.fromisoformat(base["chart_from"]),
        "OLDER_WINDOW_REQUIRED",
    )
    need(
        observed["final"].get("chartVisible")
        and observed["topPriceBefore"] == observed["topPriceAfter"],
        "EARLIER_QUOTE_CHANGED",
    )
    settling = observed.get("settling", [])[-5:]
    need(
        len(settling) == 5
        and all(s.get("active") == 0 and s.get("ready") is True for s in settling)
        and len({s.get("price") for s in settling}) == 1,
        "EARLIER_SETTLEMENT_REQUIRED",
    )
    ends = {instant(b["bar_end"]) for b in older["bars"]}
    visible = []
    for action in observed.get("visibleActions", []):
        at = action.get("time")
        if not at:
            match = re.search(
                r"\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:\d{2})",
                action.get("title", ""),
            )
            at = match.group(0) if match else None
        if (
            at
            and instant(at) in ends
            and action["rect"]["width"] > 0
            and action["rect"]["height"] > 0
        ):
            visible.append(at)
    need(bool(visible), "OLDER_ACTION_NOT_VISIBLE")
    return dict(
        status="PASS",
        older_pages=len(observed["pages"]),
        visible_older_bar_ends=visible,
    )


def validate_snapshot_recovery(candidate: Candidate, observed: dict) -> dict:
    calls = observed.get("http_calls", [])
    need(len(calls) == 5, "SNAPSHOT_FIVE_ACTUAL_GETS_REQUIRED")
    seed, wrong_chart, wrong_ref, fresh_chart, fresh_ref = calls
    expected = (
        ("5m", "chart", 200),
        ("15m", "chart", 409),
        ("15m", "reference", 409),
        ("15m", "chart", 200),
        ("15m", "reference", 200),
    )
    for call, (frequency, section, http) in zip(calls, expected):
        q = scoped_url(candidate, call["url"], frequency, section, "trend")
        need(
            call["http"] == http
            and all(q.get(k) == [str(v)] for k, v in call["params"].items()),
            "RECOVERY_GET_SEQUENCE",
        )
    section_identity(seed["payload"]["meta"], candidate, "5m", "trend")
    old = seed["payload"]["meta"]["snapshot_token"]
    for call in (wrong_chart, wrong_ref):
        need(
            call["params"].get("snapshot_token") == old
            and call["payload"].get("detail", {}).get("code")
            == "NEWOW_SNAPSHOT_GENERATION_CONFLICT",
            "NATIVE_SNAPSHOT_CONFLICT_REQUIRED",
        )
    for call in (fresh_chart, fresh_ref):
        section_identity(call["payload"]["meta"], candidate, "15m", "trend")
    fresh = fresh_chart["payload"]["meta"]["snapshot_token"]
    need(
        fresh != old
        and fresh_ref["payload"]["meta"]["snapshot_token"] == fresh
        and fresh_ref["params"].get("snapshot_token") == fresh
        and "snapshot_token" not in fresh_chart["params"],
        "FRESH_RECOVERY_SNAPSHOT",
    )
    need(
        seed["payload"]["chart"]["status"]["status"] == "ready"
        and fresh_chart["payload"]["chart"]["status"]["status"] == "ready"
        and fresh_ref["payload"]["reference"]["status"]["status"] == "ready",
        "RECOVERY_NATIVE_READY",
    )
    return dict(
        status="PASS",
        wrong_frequency_http=409,
        fresh_chart_reference_same_snapshot=True,
    )


def validate_recovery(candidate: Candidate, observed: dict) -> dict:
    need(
        observed.get("identity_valid") is True
        and observed.get("pendingAtSwitch") is True,
        "ACTUAL_PENDING_CANCEL_REQUIRED",
    )
    process_identities(candidate, observed["identity"])
    target = observed["targetUrl"]
    scoped_url(candidate, target, "5m", "reference", "trend")
    need(
        observed.get("targetId") is not None
        and any(
            e.get("event") == "failed"
            and e.get("id") == observed["targetId"]
            and e.get("url") == target
            and "abort" in e.get("error", "").lower()
            for e in observed["events"]
        ),
        "ACTUAL_CANCEL_EVENT_REQUIRED",
    )
    timeout = observed["timeout"]
    if timeout.get("outcome") == "ACTUAL_CLIENT_TIMEOUT":
        need(
            timeout.get("error") == "AbortError"
            and 0.2 <= timeout.get("seconds", 0) <= 1,
            "ACTUAL_TIMEOUT_REQUIRED",
        )
    else:
        need(
            timeout.get("outcome") == "COMPLETED_BEFORE_DEADLINE"
            and timeout.get("http") == 200
            and 0 <= timeout.get("seconds", 1) < 0.25,
            "TIMEOUT_NOT_APPLICABLE_NEEDS_ACTUAL_COMPLETION",
        )
        section_identity(timeout["meta"], candidate, "5m", "trend")
    returned = observed["returnedChart"]
    section_identity(returned["meta"], candidate, "5m", "trend")
    validate_binding(
        returned.get("xhr_binding"),
        (returned.get("xhr_binding") or {}).get("url", ""),
        returned["http"],
    )
    scoped_url(candidate, returned["xhr_binding"]["url"], "5m", "chart", "trend")
    validate_bars(candidate, returned["chart"])
    bars = returned["chart"]["value"]["bars"]
    final = observed["final"]
    q = parse_qs(urlsplit(final["url"]).query)
    need(
        returned["http"] == 200
        and returned.get("xhr_binding")
        and returned["chart"]["delivery"] == "delivered"
        and returned["chart"]["status"]["status"] == "ready"
        and bool(bars)
        and all(
            b.get("completed") is True
            and b.get("physical_contract")
            and instant(b["bar_end"]) < instant(candidate.as_of)
            for b in bars
        )
        and final.get("cards", 0) > 0
        and final.get("curves", 0) > 0
        and q.get("symbol") == [candidate.product]
        and q.get("frequency") == ["5m"]
        and not any("正在读取" in s for s in final.get("statuses", [])),
        "ACTUAL_RETURN_RECOVERY_REQUIRED",
    )
    proof = validate_snapshot_recovery(candidate, observed["snapshot_recovery"])
    return dict(
        status="PASS",
        pending_cancel="OBSERVED_CANCELLED",
        short_timeout=timeout["outcome"],
        snapshot=proof,
    )
