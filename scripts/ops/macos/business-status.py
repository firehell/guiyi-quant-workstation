#!/usr/bin/env python3
"""Project existing local read-only APIs into one bounded business status report."""

import argparse
import hashlib
import json
import os
import re
import stat
from datetime import date, datetime
from http.client import HTTPConnection, HTTPException
from pathlib import Path


RUNTIME = "/api/runtime/health"
PAPER = "/api/v1/subing-portfolio/status"
TQKQ = "/api/simulation/monitor/overview"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
RESEARCH_PRODUCT_COUNTS = {
    "THREE_PRODUCT_RETROSPECTIVE_HISTORICAL_RESEARCH": 3,
    "SEEN_14_PRODUCT_RETROSPECTIVE_HISTORICAL_RESEARCH": 14,
}


def read_local(path):
    timeout = 20 if path == RUNTIME else 5
    connection = HTTPConnection("127.0.0.1", 8000, timeout=timeout)
    try:
        connection.request("GET", path, headers={"Accept": "application/json"})
        with connection.getresponse() as response:
            if response.status != 200:
                return None
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) <= MAX_RESPONSE_BYTES:
            return mapping(json.loads(raw))
    except (OSError, HTTPException, ValueError, RecursionError):
        return None
    finally:
        connection.close()


def mapping(value):
    return value if isinstance(value, dict) else {}


def token(value):
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", value)
        else None
    )


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
        return value if parsed.utcoffset() is not None else None
    except ValueError:
        return None


def day(value):
    if not isinstance(value, str):
        return None
    try:
        return value if date.fromisoformat(value).isoformat() == value else None
    except ValueError:
        return None


def count(value):
    return value if type(value) is int and value >= 0 else None


def list_count(value):
    return len(value) if isinstance(value, list) else None


def is_sha256(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def read_research_result(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError
            raw = source.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError
        result = mapping(json.loads(raw))
        product_count = RESEARCH_PRODUCT_COUNTS.get(result.get("kind"))
        products = result.get("products")
        dates = result.get("requested")
        coverage = result.get("coverage")
        runs = mapping(result.get("portfolio_runs"))
        facts = mapping(result.get("execution_facts_sha256"))
        if (
            product_count is None
            or not isinstance(products, list)
            or len(products) != product_count
            or not all(
                isinstance(p, str) and re.fullmatch(r"[a-z]{1,4}", p) for p in products
            )
            or len(set(products)) != product_count
            or not isinstance(dates, list)
            or len(dates) != 2
            or not all(day(value) for value in dates)
            or dates[0] > dates[1]
            or not is_sha256(result.get("plan_hash"))
            or not is_sha256(result.get("input_id"))
            or set(facts) != set(products)
            or not all(is_sha256(value) for value in facts.values())
            or set(runs) != {"A", "B"}
            or not all(
                isinstance(mapping(run).get("policy"), dict) for run in runs.values()
            )
            or not isinstance(coverage, list)
            or any(mapping(item).get("status") != "VERIFIED" for item in coverage)
            or {mapping(item).get("product") for item in coverage} != set(products)
        ):
            raise ValueError
        return {
            "status": "available",
            "scope": {"products": products, "since": dates[0], "through": dates[1]},
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    except OSError:
        return {"status": "unavailable"}
    except (ValueError, TypeError, RecursionError):
        return {"status": "invalid"}


def row(status, scope, reason=None, *, progress=None, **success):
    observed = {key: value for key, value in success.items() if value is not None}
    return {
        "status": status or "unknown",
        "scope": scope,
        "reason": reason
        if status and status != "unknown"
        else (reason or "SOURCE_UNAVAILABLE"),
        "progress": progress or {},
        "last_success": observed or None,
    }


def historical_research(audit):
    status = token(audit.get("status"))
    success = status == "passed"
    return row(
        status,
        {
            "kind": "operational_full_history_audit",
            "products": count(audit.get("total")),
        },
        token(audit.get("error_type")) or (status if status != "passed" else None),
        progress={
            "products_completed": count(audit.get("completed")),
            "through": day(audit.get("through")),
            "findings": count(audit.get("finding_count")),
        },
        audit_finished_at=timestamp(audit.get("finished_at")) if success else None,
        audited_through=day(audit.get("through")) if success else None,
    )


def market(live, after_market):
    live_status = token(live.get("status"))
    canonical_status = token(after_market.get("status"))
    statuses = (live_status, canonical_status)
    status = next(
        (
            value
            for value in ("failed", "degraded", "unknown", "pending")
            if value in statuses
        ),
        live_status or canonical_status,
    )
    coverage = token(live.get("coverage_state"))
    reason = (
        token(live.get("error_type"))
        or token(after_market.get("error_type"))
        or (coverage if coverage not in {"ok", "not_due"} else None)
    )
    return row(
        status,
        {
            "kind": "operational_products",
            "products": count(live.get("operational_count")),
        },
        reason,
        progress={
            "live_status": live_status,
            "live_coverage": coverage,
            "subscribed_products": count(live.get("subscribed_count")),
            "after_market_status": canonical_status,
            "after_market_run_state": token(after_market.get("run_state")),
            "after_market_stage": token(
                mapping(after_market.get("current_run")).get("stage")
            ),
        },
        last_completed_bar_at=timestamp(live.get("last_bar_at")),
        canonical_trading_day=day(after_market.get("last_successful_trading_day")),
    )


def alerts(alert):
    coverage = token(alert.get("coverage_state"))
    return row(
        token(alert.get("status")),
        {
            "kind": "enabled_rule_scope",
            "products": count(alert.get("scope_product_count")),
            "rules": count(alert.get("enabled_rule_count")),
        },
        token(alert.get("error_type"))
        or token(alert.get("processing_error_type"))
        or token(alert.get("notification_error_type"))
        or (coverage if coverage not in {"ok", "not_due"} else None),
        progress={
            "coverage": coverage,
            "processing": token(alert.get("processing_state")),
            "notification": token(alert.get("notification_state")),
            "last_processed_bar_at": timestamp(alert.get("last_processed_bar_at")),
        },
        processing_at=timestamp(alert.get("last_processing_success_at")),
        provider_accepted_at=timestamp(alert.get("last_provider_accepted_at")),
    )


def paper_observation_gaps(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 16 * 3:
        return None
    gaps = []
    seen = set()
    for item in value:
        item = mapping(item)
        product, contract, frequency = (
            item.get(key) for key in ("product", "contract", "frequency")
        )
        first_missing_at = timestamp(item.get("first_missing_at"))
        missing = count(item.get("count"))
        if (
            not isinstance(product, str)
            or re.fullmatch(r"[a-z]{1,4}", product) is None
            or not isinstance(contract, str)
            or re.fullmatch(product.upper() + r"[0-9]{4}", contract) is None
            or frequency not in ("1m", "30m", "60m")
            or (product, frequency) in seen
            or first_missing_at is None
            or missing is None
            or not 0 < missing <= 1440
        ):
            return None
        seen.add((product, frequency))
        gaps.append(
            dict(
                product=product,
                contract=contract,
                frequency=frequency,
                first_missing_at=first_missing_at,
                count=missing,
            )
        )
    return {"count": sum(item["count"] for item in gaps), "groups": gaps}


def subing_paper(paper):
    if paper.get("auto_order") is not False:
        paper = {}
    status = token(paper.get("status"))
    registered = isinstance(paper.get("run_id"), str) and bool(paper["run_id"])
    account = mapping(paper.get("account"))
    products = paper.get("products")
    reason = token(paper.get("worker_code"))
    if status in {
        "NOT_STARTED",
        "WARMING_UP",
        "WAITING_MARKET_METADATA",
        "WAITING_OBSERVATIONS",
        "WAITING_EXECUTION_FACTS",
        "STALE_OR_STOPPED",
        "BLOCKED",
    }:
        reason = reason or status
    return row(
        status,
        {
            "kind": "shared_paper",
            "products": (
                sum(mapping(p).get("enabled") is True for p in products)
                if registered and isinstance(products, list)
                else None
            ),
        },
        reason,
        progress={
            "registered": registered if status else None,
            "sequence": count(paper.get("sequence")),
            "next_open": timestamp(paper.get("next_open")),
            "observation_gaps": paper_observation_gaps(
                paper.get("missing_observations")
            ),
            "pending_exit_contracts": list_count(account.get("pending_exit_contracts")),
            "valuation_unproven_contracts": list_count(
                account.get("valuation_unproven")
            ),
        },
        committed_observation_at=timestamp(paper.get("observed_at"))
        if registered
        else None,
    )


def tqkq(monitor):
    if monitor.get("version") != "simulation_monitor_v1":
        monitor = {}
    status = token(monitor.get("status"))
    scope = mapping(monitor.get("trading_scope"))
    observer = mapping(monitor.get("observer"))
    scope_status = token(scope.get("status"))
    readback_status = token(monitor.get("readback_status"))
    verified = (
        readback_status == "verified"
        and monitor.get("position_projection_complete") is True
    )
    return row(
        status,
        {"kind": "tqkq_simulation", "products": list_count(scope.get("products"))},
        token(monitor.get("block_code"))
        or (scope_status if scope_status == "FLATTEN_PENDING" else None)
        or (readback_status if readback_status != "verified" else None),
        progress={
            "readback_status": readback_status,
            "readback_at": timestamp(monitor.get("readback_at")),
            "observer_status": token(observer.get("status")),
            "scope_status": scope_status,
            "executable_products": count(observer.get("executable_product_count")),
            "blocked_products": count(observer.get("blocked_product_count")),
            "issues": count(monitor.get("issue_count")),
            "pending_positions": list_count(scope.get("pending_positions")),
            "pending_orders": list_count(scope.get("pending_order_ids")),
            "pending_reservations": list_count(scope.get("pending_reservation_ids")),
        },
        account_readback_at=timestamp(monitor.get("readback_at")) if verified else None,
    )


def collect(read=read_local, *, replay=None):
    runtime = mapping(read(RUNTIME))
    components = (
        mapping(runtime.get("components")) if runtime.get("readonly") is True else {}
    )
    return {
        "readonly": True,
        "businesses": {
            "historical_research": {
                **historical_research(mapping(components.get("weekly_audit"))),
                "offline_replay": replay or {"status": "not_supplied"},
            },
            "market": market(
                mapping(components.get("live_market")),
                mapping(components.get("after_market")),
            ),
            "alerts": alerts(mapping(components.get("alert"))),
            "subing_paper": subing_paper(mapping(read(PAPER))),
            "tqkq": tqkq(mapping(read(TQKQ))),
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--research-result",
        type=Path,
        help="completed SuBing historical A/B comparison JSON",
    )
    args = parser.parse_args()
    replay = (
        read_research_result(args.research_result) if args.research_result else None
    )
    print(json.dumps(collect(replay=replay), indent=2))
