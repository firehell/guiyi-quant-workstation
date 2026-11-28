"""Read the single existing SuBing Paper snapshot and its replay registration."""

from pathlib import Path
import re

from app.api.subing_portfolio import read_registration, read_status
from app.new_subing_research.store import _safe_root
from app.subing_portfolio_paths import HISTORY
from guiyi_quant.subing_one_lot import EXPANDED_PORTFOLIO_PRODUCTS, portfolio_policy

from .reads import projection, version

SOURCE = "SuBing PortfolioJournal / heartbeat"
HISTORY_SOURCE = "SuBing replay registration"


def overview():
    policy = portfolio_policy(EXPANDED_PORTFOLIO_PRODUCTS)
    return {
        "source": "SuBing Portfolio policy",
        "capability": {period: policy["products"] for period in ("1m", "30m", "60m")},
        "input_requirements": ["completed 1m / 30m / 60m", "Canonical 1d / 30m / 60m warm-up"],
        "allowed_uses": ["paper", "historical_replay"],
        "result_owner": "SuBing PortfolioJournal",
        "references": [version("portfolio_policy", policy["version"], "SuBing Portfolio policy")],
        "policy": policy,
    }


def _status(data):
    raw = data["status"]
    if raw == "STALE_OR_STOPPED":
        return "STALE"
    if raw == "NOT_STARTED":
        return "UNKNOWN"
    if raw in {"INTERRUPTED", "BLOCKED"}:
        return "BLOCKED"
    if raw.startswith("WAITING_") or raw == "WARMING_UP":
        return "WAITING"
    if raw in {"RUNNING", "SESSION_BREAK", "SESSION_COMPLETE", "SESSION_CLOSED"}:
        return "AVAILABLE"
    return "UNKNOWN"


def runtime(data=None):
    if data is None:
        data = read_status(include_charts=False)
    return projection(
        SOURCE, _status(data), source_as_of=data.get("worker_at"),
        diagnostic=data.get("worker_code"), domain_status=data["status"],
        heartbeat_status=data.get("worker_status"), heartbeat_at=data.get("worker_at"),
        run_id=data["run_id"], sequence=data.get("sequence"), watermark=data.get("observed_at"),
        diagnostics={"missing_observations": data.get("missing_observations", [])},
        authorization={"mode": "paper", "auto_order": data["auto_order"]},
    )


def bindings(data=None):
    if data is None:
        data = read_status(include_charts=False)
    return projection(
        SOURCE, "REGISTERED" if data["run_id"] else "NOT_REGISTERED",
        source_as_of=data.get("observed_at"), run_id=data["run_id"],
        products=[row["product"] for row in data["products"] if row["enabled"]],
        policy=data["account"].get("policy"),
    )


def history():
    try:
        entry = read_registration(HISTORY)
        if entry is None:
            return projection(HISTORY_SOURCE, "NOT_REGISTERED")
        if re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]) is None:
            raise ValueError("PORTFOLIO_HISTORY_INVALID")
        _safe_root(Path(entry["path"]).parent)
        return projection(HISTORY_SOURCE, "REGISTERED_UNVERIFIED", run_id=entry["sha256"])
    except (KeyError, TypeError, ValueError, OSError):
        return projection(HISTORY_SOURCE, "UNAVAILABLE", diagnostic="PORTFOLIO_HISTORY_UNAVAILABLE")


def evidence(data=None):
    replay = history()
    if data is None:
        try:
            data = read_status(include_charts=False)
        except Exception:
            return projection(SOURCE, "UNAVAILABLE", diagnostic="PORTFOLIO_STATUS_UNAVAILABLE", history=replay)
    if not data["run_id"]:
        return projection(SOURCE, "NOT_PUBLISHED", history=replay)
    account = data["account"]
    return projection(
        SOURCE, "PUBLISHED", source_as_of=data.get("observed_at"), runtime_status=data["status"],
        run_id=data["run_id"], sequence=data.get("sequence"), history=replay,
        account={key: account.get(key) for key in
                 ("cash", "equity", "margin", "valuation_unproven", "pending_exit_contracts")},
        day_net=data.get("day_net"),
        products=[{"product": row["product"], "contracts": [
            {key: contract[key] for key in ("contract", "status", "valuation_at", "latest_decision")}
            | {"fills": contract["fills"][-3:]}
            for contract in row["accounts"]
        ]} for row in data["products"] if row["enabled"]],
    )
