"""HTDY identities and sanitized TQKQ account monitor readback."""

from app.api.simulation_monitor import snapshot
from guiyi_quant.htdy_account_execution.model import POLICY_VERSION as ACCOUNT_POLICY
from guiyi_quant.htdy_account_execution.tq_types import TQ_EXECUTION_VERSION, TQ_RISK_VERSION
from guiyi_quant.htdy_execution import FORMULA_VERSION, POLICY_VERSION

from .reads import projection, version

SOURCE = "TQKQ simulation monitor"


def overview():
    return {
        "source": "HTDY signal / TQKQ account policy",
        "capability": {"60m": None},
        "input_requirements": ["60m completed signal", "1m execution eligibility"],
        "allowed_uses": ["retrospective_repainting_observation", "domain_authorized_tqkq_simulation"],
        "result_owner": "TQKQ Journal",
        "references": [
            version("formula", FORMULA_VERSION, "HTDY original"),
            version("fixed_one_lot_policy", POLICY_VERSION, "HTDY execution"),
            version("account_policy", ACCOUNT_POLICY, "HTDY account"),
            version("risk_policy", TQ_RISK_VERSION, "TQKQ risk"),
            version("quote_policy", TQ_EXECUTION_VERSION, "TQKQ execution"),
        ],
    }


def _status(view):
    if view["snapshot"] is None:
        return "UNKNOWN"
    if view["readback_status"] == "stale":
        return "STALE"
    if view["block_code"]:
        return "BLOCKED"
    if view["readback_status"] == "verified":
        return "AVAILABLE"
    return "UNVERIFIED"


def runtime():
    view = snapshot()["overview"]
    observer = view.get("observer") or {}
    scope = view.get("trading_scope") or {}
    return projection(
        SOURCE, _status(view),
        source_as_of=view["generated_at"] if view["snapshot"] is not None else None,
        diagnostic=view["block_code"], domain_status=view["status"],
        heartbeat_at=observer.get("published_at"), observer=observer or None,
        authorization={"opening_enabled": observer.get("opening_enabled"),
                       "scope_status": scope.get("status")},
        readback_at=view["readback_at"], readback_status=view["readback_status"],
        watermark=view.get("source_times"),
    )


def bindings():
    view = snapshot()["overview"]
    scope = view.get("trading_scope") or {}
    account = view.get("account")
    return projection(
        SOURCE, "REGISTERED" if account else "NOT_OBSERVED",
        source_as_of=view["generated_at"] if view["snapshot"] is not None else None,
        account_key=account["key"] if account else None,
        scope=scope or None, domain_status=scope.get("status"),
    )


def evidence():
    packet = snapshot()
    view = packet["overview"]
    if view["snapshot"] is None:
        return projection(SOURCE, "NOT_PUBLISHED")
    return projection(
        SOURCE, _status(view), source_as_of=view["generated_at"], diagnostic=view["block_code"],
        snapshot=view["snapshot"], readback_at=view["readback_at"], readback_status=view["readback_status"],
        account=view["account"], metrics=view["metrics"], positions=view["positions"],
        records={kind: [row for row in packet["records"] if row["kind"] == kind][:8]
                 for kind in ("signal", "risk", "order", "fill")},
        source_times=view["source_times"],
    )
