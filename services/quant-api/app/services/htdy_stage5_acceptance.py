from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from app.backtest.htdy_trusted_report import file_sha256, packet_hash
from app.services.backtest_validation_context import (
    X503_PACKET,
    X504_PACKET,
    X505_PACKET,
    build_backtest_validation_context,
    verify_context_hash,
)
from app.services.htdy_review_closed_loop import verify_closed_loop_packet


SCHEMA_VERSION = "htdy_stage5_acceptance_x507_v1"
TASK_ID = "HTDY-STAGE5-ACCEPTANCE-X507"
PIPELINE_READY_GATE = "STRATEGY_EVALUATION_PIPELINE_READY"
BLOCKED_GATE = "STRATEGY_VALIDATION_BLOCKED"
VALIDATED_OUTCOME = "VALIDATED_RESEARCH_CANDIDATE"
REJECTED_OUTCOME = "REJECTED_RESEARCH_CANDIDATE"
X506_PACKET = Path(
    "data/reports/htdy_strategy_review_x5_06b/"
    "STRATEGY_REVIEW_CLOSED_LOOP_READY.json"
)
X506_ARTIFACTS = {
    "review_db_evidence": "review_db_evidence.json",
    "validation_context": "validation_context.json",
    "browser_smoke": "BROWSER_SMOKE_EVIDENCE.json",
}


class Stage5AcceptanceEvidenceError(ValueError):
    """Fail-closed error for incomplete or drifted Stage 5 evidence."""


def verify_acceptance_packet(packet: Mapping[str, Any]) -> bool:
    payload = dict(packet)
    expected = str(payload.pop("packet_hash", ""))
    return bool(expected) and expected == packet_hash(payload)


def decide_stage5_outcome(
    *,
    x504_gate: str,
    x505_label: str,
    x506_gate: str,
) -> tuple[str, str | None]:
    if x506_gate != "STRATEGY_REVIEW_CLOSED_LOOP_READY":
        return BLOCKED_GATE, None
    if x505_label == BLOCKED_GATE:
        return BLOCKED_GATE, None
    if (
        x504_gate == "OOS_VALIDATION_EXECUTED"
        and x505_label == "PROPOSED_VALIDATED_RESEARCH_CANDIDATE"
    ):
        return PIPELINE_READY_GATE, VALIDATED_OUTCOME
    rejection_labels = {
        "PROPOSED_REJECTED_RESEARCH_CANDIDATE",
        "DIAGNOSTIC_CONFIRMS_REJECTION",
        "DIAGNOSTIC_INCONCLUSIVE_REJECTION_REMAINS",
    }
    if x504_gate == "OOS_HARD_REJECT_TRIGGERED" or x505_label in rejection_labels:
        return PIPELINE_READY_GATE, REJECTED_OUTCOME
    return BLOCKED_GATE, None


def build_stage5_acceptance(repo_root: Path, *, source_commit: str) -> dict[str, Any]:
    root = repo_root.expanduser().resolve()
    try:
        evidence = _verify_stage5_evidence(root)
        gate, outcome = decide_stage5_outcome(
            x504_gate=str(evidence["x504"]["gate"]),
            x505_label=str(evidence["x505"]["proposal_label"]),
            x506_gate=str(evidence["x506"]["gate"]),
        )
        if gate == BLOCKED_GATE:
            raise Stage5AcceptanceEvidenceError("Stage 5 labels do not form a terminal decision")
        packet = _ready_packet(source_commit=source_commit, evidence=evidence, gate=gate, outcome=outcome)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        packet = _blocked_packet(source_commit=source_commit, reason=_redacted_reason(exc))
    packet["packet_hash"] = packet_hash(packet)
    return packet


def _verify_stage5_evidence(root: Path) -> dict[str, Any]:
    x503_path = root / X503_PACKET
    x504_path = root / X504_PACKET
    x505_path = root / X505_PACKET
    x506_path = root / X506_PACKET
    x503 = _read_json(x503_path)
    candidate = x503.get("candidate_identity") or {}
    report = candidate.get("report") or {}
    task = candidate.get("task") or {}
    snapshot = x503.get("execution_snapshot") or {}
    report_identity = {
        "id": report.get("id"),
        "report_no": report.get("report_no"),
        "task_id": task.get("id"),
        "task_no": task.get("task_no"),
        "profile_id": snapshot.get("profile_id"),
        "market_data_file_id": snapshot.get("market_data_file_id"),
    }
    rebuilt_context = build_backtest_validation_context(root, report_identity=report_identity)
    x504 = _read_json(x504_path)
    x505 = _read_json(x505_path)
    x506 = _read_json(x506_path)
    if not verify_closed_loop_packet(x506):
        raise Stage5AcceptanceEvidenceError("X5-06B packet hash invalid")
    if x506.get("gate") != "STRATEGY_REVIEW_CLOSED_LOOP_READY":
        raise Stage5AcceptanceEvidenceError("X5-06B Gate is not ready")
    _verify_x506_artifacts(x506_path.parent, x506)
    stored_context = _read_json(x506_path.parent / X506_ARTIFACTS["validation_context"])
    if not verify_context_hash(stored_context):
        raise Stage5AcceptanceEvidenceError("X5-06B validation context hash invalid")
    if stored_context != rebuilt_context:
        raise Stage5AcceptanceEvidenceError("X5-06B validation context drift")
    if x506.get("validation_context_hash") != rebuilt_context.get("context_hash"):
        raise Stage5AcceptanceEvidenceError("X5-06B context identity mismatch")
    if x506.get("report_id") != report.get("id"):
        raise Stage5AcceptanceEvidenceError("X5-06B candidate report identity mismatch")
    selected_trade = x506.get("selected_trade") or {}
    if selected_trade.get("report_id") != report.get("id"):
        raise Stage5AcceptanceEvidenceError("X5-06B selected trade identity mismatch")
    report14_status = ((x503.get("audits") or {}).get("report14") or {}).get("audit_status")
    if report14_status != "passed" or (x506.get("report_invariance") or {}).get("report14") is not True:
        raise Stage5AcceptanceEvidenceError("report14 regression failed")
    if ((x503.get("audits") or {}).get("candidate") or {}).get("audit_status") != "passed":
        raise Stage5AcceptanceEvidenceError("candidate trust audit failed")
    return {
        "x503": x503,
        "x504": x504,
        "x505": x505,
        "x506": x506,
        "context": rebuilt_context,
        "packet_files": {
            "x503": file_sha256(x503_path),
            "x504": file_sha256(x504_path),
            "x505": file_sha256(x505_path),
            "x506": file_sha256(x506_path),
        },
    }


def _verify_x506_artifacts(directory: Path, packet: Mapping[str, Any]) -> None:
    artifacts = packet.get("artifacts") or {}
    for key, filename in X506_ARTIFACTS.items():
        path = directory / filename
        expected = str(artifacts.get(key) or "")
        if not expected or not path.is_file() or file_sha256(path) != expected:
            raise Stage5AcceptanceEvidenceError(f"X5-06B artifact hash invalid: {key}")
    browser = packet.get("browser_smoke") or {}
    screenshot_name = str(browser.get("screenshot") or "")
    if not screenshot_name or Path(screenshot_name).name != screenshot_name:
        raise Stage5AcceptanceEvidenceError("X5-06B screenshot path invalid")
    screenshot = directory / screenshot_name
    expected = str(artifacts.get("screenshot") or "")
    if not expected or not screenshot.is_file() or file_sha256(screenshot) != expected:
        raise Stage5AcceptanceEvidenceError("X5-06B screenshot hash invalid")


def _ready_packet(
    *,
    source_commit: str,
    evidence: Mapping[str, Any],
    gate: str,
    outcome: str | None,
) -> dict[str, Any]:
    x503 = evidence["x503"]
    x504 = evidence["x504"]
    x505 = evidence["x505"]
    x506 = evidence["x506"]
    context = evidence["context"]
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "status": "completed",
        "gate": gate,
        "research_outcome": outcome,
        "source_commit": source_commit,
        "candidate_identity": deepcopy(x503.get("candidate_identity") or {}),
        "x503_gate": x503.get("gate"),
        "x504_gate": x504.get("gate"),
        "x505_label": x505.get("proposal_label"),
        "x506_gate": x506.get("gate"),
        "protocol_hash": x503.get("protocol_hash"),
        "parameter_hash": x503.get("parameter_hash"),
        "binding_identity": deepcopy(context.get("binding_identity") or {}),
        "evidence_hashes": {
            "x503_packet_hash": x503.get("packet_hash"),
            "x504_packet_hash": x504.get("packet_hash"),
            "x505_packet_hash": x505.get("packet_hash"),
            "x506_packet_hash": x506.get("packet_hash"),
            "validation_context_hash": context.get("context_hash"),
            "packet_file_sha256": deepcopy(evidence["packet_files"]),
        },
        "trust_audits": {
            "candidate": ((x503.get("audits") or {}).get("candidate") or {}).get("audit_status"),
            "report14": ((x503.get("audits") or {}).get("report14") or {}).get("audit_status"),
        },
        "report14_regression": {
            "status": "passed",
            "trust_audit": ((x503.get("audits") or {}).get("report14") or {}).get("audit_status"),
            "invariance_after_review": (x506.get("report_invariance") or {}).get("report14"),
            "consistency_hash": ((x503.get("audits") or {}).get("report14") or {}).get("consistency_hash"),
        },
        "decision_basis": {
            "x504_hard_reject_preserved": x505.get("x504_hard_reject_preserved"),
            "hard_reject": deepcopy(x504.get("hard_reject") or {}),
            "review_candidate_status": x506.get("candidate_status"),
            "rejection_may_be_flipped": False,
        },
        "boundaries": {
            "canonical_db_write": False,
            "strategy_or_parameter_changed": False,
            "report_or_report14_changed": False,
            "automatic_rerun": False,
        },
        "blocked_reason": None,
    }


def _blocked_packet(*, source_commit: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "status": "blocked",
        "gate": BLOCKED_GATE,
        "research_outcome": None,
        "source_commit": source_commit,
        "blocked_reason": reason,
        "boundaries": {
            "canonical_db_write": False,
            "strategy_or_parameter_changed": False,
            "report_or_report14_changed": False,
            "automatic_rerun": False,
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise Stage5AcceptanceEvidenceError(f"missing evidence: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage5AcceptanceEvidenceError(f"evidence is not an object: {path.name}")
    return value


def _redacted_reason(exc: BaseException) -> str:
    text = str(exc).replace("\\", "/")
    parts = text.split()
    safe = [Path(part).name if "/" in part else part for part in parts]
    return " ".join(safe)[:500] or exc.__class__.__name__


__all__ = [
    "BLOCKED_GATE",
    "PIPELINE_READY_GATE",
    "REJECTED_OUTCOME",
    "Stage5AcceptanceEvidenceError",
    "VALIDATED_OUTCOME",
    "build_stage5_acceptance",
    "decide_stage5_outcome",
    "verify_acceptance_packet",
]
