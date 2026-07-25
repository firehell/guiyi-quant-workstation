from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.htdy_realtime_alert import (
    ALERT_POLICY,
    INDICATOR_CODE,
    INDICATOR_VERSION,
)

SCHEMA_VERSION = "htdy_realtime_alert_approval_v1"
GATE = "HTDY_ORIGINAL_REALTIME_ALERT_APPROVED"
S6_08_GATE = "LIVE_SIGNAL_EVENT_GATE_PASSED"


class HtdyRealtimeAlertGateError(RuntimeError):
    pass


def canonical_packet_hash(packet: Mapping[str, Any]) -> str:
    value = deepcopy(dict(packet))
    value.pop("packet_hash", None)
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_approval_packet(
    *,
    current_facts: Mapping[str, Any],
    enable_wechat: bool,
) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "gate": GATE,
        "prerequisite": {
            "gate": S6_08_GATE,
            "receipt_path": str(current_facts["s6_08_receipt_path"]),
            "receipt_sha256": str(current_facts["s6_08_receipt_sha256"]),
        },
        "runtime": {
            "commit": str(current_facts["runtime_commit"]),
            "database_revision": str(current_facts["database_revision"]),
        },
        "indicator": {
            "code": INDICATOR_CODE,
            "version": INDICATOR_VERSION,
            "alert_policy": ALERT_POLICY,
            "source_sha256": str(current_facts["indicator_source_sha256"]),
            "future_looking": True,
            "repainting_risk": "known",
            "repaint_followup": "none",
        },
        "scope": {
            "product": "jm",
            "actual_dominant_contract_only": True,
            "period": "15m",
            "confirmed_bar_only": True,
            "observation_alert": True,
            "wechat_autosend": bool(enable_wechat),
            "formal_signal_event": False,
            "backtest": False,
            "order_or_trade": False,
        },
    }
    packet["packet_hash"] = canonical_packet_hash(packet)
    return packet


def collect_current_facts(
    *,
    project_root: Path,
    s6_08_receipt_path: Path,
    session: Session,
) -> dict[str, Any]:
    receipt_path = s6_08_receipt_path.resolve()
    indicator_path = (
        project_root
        / "packages"
        / "quant-core"
        / "guiyi_quant"
        / "indicators"
        / "htdy_original.py"
    )
    return {
        "runtime_commit": _git_commit(project_root),
        "database_revision": _database_revision(session),
        "indicator_source_sha256": _file_sha256(indicator_path),
        "s6_08_receipt_path": str(receipt_path),
        "s6_08_receipt_sha256": _file_sha256(receipt_path),
    }


def load_packet(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HtdyRealtimeAlertGateError("packet_not_object")
    return value


def verify_approval_packet(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    current_facts: Mapping[str, Any],
    alerts_enabled: bool,
    wechat_enabled: bool,
) -> None:
    checks = (
        (packet.get("schema_version") == SCHEMA_VERSION, "schema_version_invalid"),
        (packet.get("gate") == GATE, "gate_invalid"),
        (_is_sha256(approval_hash), "approval_hash_invalid"),
        (canonical_packet_hash(packet) == approval_hash, "approval_hash_mismatch"),
        (packet.get("packet_hash") == approval_hash, "packet_hash_mismatch"),
    )
    _require(checks)
    prerequisite = packet.get("prerequisite") or {}
    runtime = packet.get("runtime") or {}
    indicator = packet.get("indicator") or {}
    scope = packet.get("scope") or {}
    _require(
        (
            (prerequisite.get("gate") == S6_08_GATE, "s6_08_gate_invalid"),
            (
                prerequisite.get("receipt_path")
                == current_facts.get("s6_08_receipt_path"),
                "s6_08_receipt_path_changed",
            ),
            (
                prerequisite.get("receipt_sha256")
                == current_facts.get("s6_08_receipt_sha256"),
                "s6_08_receipt_changed",
            ),
            (
                runtime.get("commit") == current_facts.get("runtime_commit"),
                "runtime_commit_changed",
            ),
            (
                runtime.get("database_revision")
                == current_facts.get("database_revision")
                == "20260725_0026",
                "database_revision_changed",
            ),
            (
                indicator.get("source_sha256")
                == current_facts.get("indicator_source_sha256"),
                "indicator_source_changed",
            ),
            (indicator.get("code") == INDICATOR_CODE, "indicator_code_invalid"),
            (indicator.get("version") == INDICATOR_VERSION, "indicator_version_invalid"),
            (indicator.get("alert_policy") == ALERT_POLICY, "alert_policy_invalid"),
            (indicator.get("future_looking") is True, "future_looking_ack_missing"),
            (indicator.get("repainting_risk") == "known", "repainting_ack_missing"),
            (indicator.get("repaint_followup") == "none", "repaint_followup_invalid"),
            (scope.get("product") == "jm", "product_scope_invalid"),
            (scope.get("period") == "15m", "period_scope_invalid"),
            (scope.get("actual_dominant_contract_only") is True, "contract_scope_invalid"),
            (scope.get("confirmed_bar_only") is True, "confirmed_scope_invalid"),
            (scope.get("observation_alert") is True, "observation_scope_invalid"),
            (scope.get("formal_signal_event") is False, "formal_signal_scope_invalid"),
            (scope.get("backtest") is False, "backtest_scope_invalid"),
            (scope.get("order_or_trade") is False, "trading_scope_invalid"),
            (alerts_enabled is True, "alerts_must_be_enabled"),
            (
                scope.get("wechat_autosend") is bool(wechat_enabled),
                "wechat_scope_mismatch",
            ),
        )
    )
    _verify_s6_08_receipt(
        Path(str(current_facts["s6_08_receipt_path"])),
        expected_sha256=str(current_facts["s6_08_receipt_sha256"]),
    )


def _verify_s6_08_receipt(path: Path, *, expected_sha256: str) -> None:
    if _file_sha256(path) != expected_sha256:
        raise HtdyRealtimeAlertGateError("s6_08_receipt_changed")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("gate") != S6_08_GATE:
        raise HtdyRealtimeAlertGateError("s6_08_gate_not_passed")


def _git_commit(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _database_revision(session: Session) -> str:
    value = session.execute(text("select version_num from alembic_version")).scalar_one()
    return str(value)


def _file_sha256(path: Path) -> str:
    if not path.is_file():
        raise HtdyRealtimeAlertGateError("bound_file_missing")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _require(checks: tuple[tuple[bool, str], ...]) -> None:
    for valid, reason in checks:
        if not valid:
            raise HtdyRealtimeAlertGateError(reason)


__all__ = [
    "GATE",
    "HtdyRealtimeAlertGateError",
    "build_approval_packet",
    "canonical_packet_hash",
    "collect_current_facts",
    "load_packet",
    "verify_approval_packet",
]
