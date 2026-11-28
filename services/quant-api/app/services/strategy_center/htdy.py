"""HTDY identities and sanitized TQKQ account monitor readback."""

from datetime import datetime
import re

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
    if (view["readback_status"] == "verified"
            and (view.get("trading_scope") or {}).get("native_readback_verified") is True
            and view.get("source_times")):
        return "AVAILABLE"
    return "UNVERIFIED"


def runtime():
    packet = snapshot()
    view = packet["overview"]
    observer = view.get("observer") or {}
    scope = view.get("trading_scope") or {}
    tag, commit = packet.get("runtime_tag"), packet.get("runtime_commit")
    identity = (isinstance(tag, str) and re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag)
                and isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit))
    status = _status(view)
    journal_signal = next((row for row in packet.get("records", ()) if row.get("kind") == "signal"), None)
    bar_end = (journal_signal.get("facts") or {}).get("bar_end") if journal_signal else None
    signal_at = None
    if isinstance(bar_end, str):
        try:
            parsed = datetime.fromisoformat(bar_end)
            if parsed.tzinfo is not None:
                signal_at = parsed.isoformat()
        except ValueError:
            pass
    return projection(
        SOURCE, status,
        source_as_of=view["generated_at"] if view["snapshot"] is not None else None,
        diagnostic=view["block_code"] or ("TQKQ_INPUT_OR_READBACK_UNPROVEN" if status == "UNVERIFIED" else None),
        domain_status=view["status"], deployment=tag if identity else None, commit=commit if identity else None,
        heartbeat_at=observer.get("published_at"), heartbeat_status=observer.get("status"), observer=observer or None,
        authorization={"opening_enabled": observer.get("opening_enabled"), "scope_status": scope.get("status"),
                       "native_readback_verified": scope.get("native_readback_verified"),
                       "executable_products": observer.get("executable_product_count")},
        readback_at=view["readback_at"], readback_status=view["readback_status"],
        watermark=view.get("source_times") or None, latest_journal_signal_at=signal_at,
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
